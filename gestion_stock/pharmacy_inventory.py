"""Gestion spécialisée pour l'inventaire pharmaceutique.

Ce module fournit une couche d'abstraction pour manipuler les lots de
médicaments, gérer les dates de péremption et synchroniser les quantités
avec la table ``items`` existante. L'objectif est d'offrir une
fonctionnalité dédiée à la pharmacie sans alourdir ``gestion_stock``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional


@dataclass
class PharmacyBatch:
    """Représente un lot de médicament stocké dans la base de données."""

    id: int
    item_id: int
    name: str
    lot_number: str
    expiration_date: Optional[str]
    quantity: int
    dosage: Optional[str]
    form: Optional[str]
    storage_condition: Optional[str]
    prescription_required: bool
    days_left: Optional[int]


class PharmacyInventoryManager:
    """Gestionnaire des opérations spécifiques à l'inventaire pharmacie."""

    def __init__(
        self,
        db_path_getter: Callable[[], str],
        lock,
        *,
        log_stock_movement: Callable,
        parse_user_date: Callable[[Optional[str]], Optional[str]],
    ) -> None:
        self._db_path_getter = db_path_getter
        self._lock = lock
        self._log_stock_movement = log_stock_movement
        self._parse_user_date = parse_user_date

    # ------------------------------------------------------------------
    #  Utilitaires internes
    # ------------------------------------------------------------------
    def _normalize_expiration(self, expiration: Optional[str | date | datetime]) -> Optional[str]:
        if expiration in (None, ""):
            return None
        if isinstance(expiration, datetime):
            return expiration.date().isoformat()
        if isinstance(expiration, date):
            return expiration.isoformat()
        if isinstance(expiration, str):
            parsed = self._parse_user_date(expiration)
            return parsed
        raise TypeError("expiration doit être une date, datetime, str ou None")

    def _open_connection(self, db_path: Optional[str] = None) -> sqlite3.Connection:
        path = db_path or self._db_path_getter()
        return sqlite3.connect(path, timeout=30)

    def _ensure_schema(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("PRAGMA table_info(items)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if "is_medicine" not in existing_columns:
            cursor.execute("ALTER TABLE items ADD COLUMN is_medicine INTEGER NOT NULL DEFAULT 0")
        if "dosage" not in existing_columns:
            cursor.execute("ALTER TABLE items ADD COLUMN dosage TEXT")
        if "medication_form" not in existing_columns:
            cursor.execute("ALTER TABLE items ADD COLUMN medication_form TEXT")
        if "storage_condition" not in existing_columns:
            cursor.execute("ALTER TABLE items ADD COLUMN storage_condition TEXT")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS pharmacy_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                lot_number TEXT NOT NULL,
                expiration_date TEXT,
                quantity INTEGER NOT NULL DEFAULT 0,
                storage_condition TEXT,
                prescription_required INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(item_id, lot_number, expiration_date),
                FOREIGN KEY(item_id) REFERENCES items(id)
            )
            """
        )

        cursor.execute("PRAGMA table_info(pharmacy_inventory)")
        inventory_columns = {row[1] for row in cursor.fetchall()}
        if "storage_condition" not in inventory_columns:
            cursor.execute("ALTER TABLE pharmacy_inventory ADD COLUMN storage_condition TEXT")
        if "prescription_required" not in inventory_columns:
            cursor.execute(
                "ALTER TABLE pharmacy_inventory ADD COLUMN prescription_required INTEGER NOT NULL DEFAULT 0"
            )
        if "note" not in inventory_columns:
            cursor.execute("ALTER TABLE pharmacy_inventory ADD COLUMN note TEXT")
        if "created_at" not in inventory_columns:
            cursor.execute(
                "ALTER TABLE pharmacy_inventory ADD COLUMN created_at TEXT DEFAULT ''"
            )
            cursor.execute(
                "UPDATE pharmacy_inventory SET created_at = COALESCE(created_at, datetime('now'))"
            )
        if "updated_at" not in inventory_columns:
            cursor.execute(
                "ALTER TABLE pharmacy_inventory ADD COLUMN updated_at TEXT DEFAULT ''"
            )
            cursor.execute(
                "UPDATE pharmacy_inventory SET updated_at = COALESCE(updated_at, datetime('now'))"
            )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pharmacy_expiration
            ON pharmacy_inventory(expiration_date)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pharmacy_item
            ON pharmacy_inventory(item_id)
            """
        )

    def ensure_schema(
        self,
        *,
        db_path: Optional[str] = None,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> None:
        if cursor is not None:
            self._ensure_schema(cursor)
            return
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cur = conn.cursor()
                self._ensure_schema(cur)
                conn.commit()
            finally:
                conn.close()

    def _ensure_category(self, cursor: sqlite3.Cursor, category: Optional[str]) -> Optional[int]:
        if not category:
            return None
        cursor.execute("SELECT id FROM categories WHERE name = ?", (category,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute("INSERT INTO categories (name) VALUES (?)", (category,))
        return cursor.lastrowid

    def _ensure_item(
        self,
        cursor: sqlite3.Cursor,
        name: str,
        barcode: Optional[str],
        category_id: Optional[int],
        dosage: Optional[str],
        form: Optional[str],
        storage_condition: Optional[str],
    ) -> int:
        if barcode:
            cursor.execute("SELECT id FROM items WHERE barcode = ?", (barcode,))
            row = cursor.fetchone()
            if row:
                item_id = row[0]
            else:
                item_id = None
        else:
            item_id = None

        if item_id is None:
            cursor.execute("SELECT id FROM items WHERE name = ?", (name,))
            row = cursor.fetchone()
            item_id = row[0] if row else None

        now = datetime.now().isoformat()
        if item_id is None:
            cursor.execute(
                """
                INSERT INTO items (
                    name, barcode, category_id, size, quantity,
                    last_updated, unit_cost, reorder_point, preferred_supplier_id,
                    is_medicine, dosage, medication_form, storage_condition
                ) VALUES (?, ?, ?, NULL, 0, ?, 0, NULL, NULL, 1, ?, ?, ?)
                """,
                (
                    name,
                    barcode,
                    category_id,
                    now,
                    dosage,
                    form,
                    storage_condition,
                ),
            )
            return cursor.lastrowid

        update_fields = ["is_medicine = 1", "last_updated = ?"]
        update_params: list[object] = [now]
        if barcode:
            update_fields.append("barcode = COALESCE(?, barcode)")
            update_params.append(barcode)
        if category_id is not None:
            update_fields.append("category_id = COALESCE(?, category_id)")
            update_params.append(category_id)
        if dosage is not None:
            update_fields.append("dosage = ?")
            update_params.append(dosage)
        if form is not None:
            update_fields.append("medication_form = ?")
            update_params.append(form)
        if storage_condition is not None:
            update_fields.append("storage_condition = ?")
            update_params.append(storage_condition)
        update_params.append(item_id)
        cursor.execute(
            f"UPDATE items SET {', '.join(update_fields)} WHERE id = ?",
            tuple(update_params),
        )
        return item_id

    def _match_batch(
        self,
        cursor: sqlite3.Cursor,
        item_id: int,
        lot_number: str,
        expiration: Optional[str],
    ) -> Optional[tuple[int, int]]:
        cursor.execute(
            """
            SELECT id, quantity
            FROM pharmacy_inventory
            WHERE item_id = ?
              AND lot_number = ?
              AND (
                    (expiration_date IS NULL AND ? IS NULL)
                 OR expiration_date = ?
              )
            """,
            (item_id, lot_number, expiration, expiration),
        )
        row = cursor.fetchone()
        return (row[0], row[1]) if row else None

    def _apply_item_quantity_change(
        self,
        cursor: sqlite3.Cursor,
        item_id: int,
        delta: int,
        operator: Optional[str],
        source: str,
        note: Optional[str],
    ) -> tuple[int, int, int]:
        cursor.execute("SELECT quantity FROM items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
        if not row:
            raise LookupError(f"Article introuvable pour l'identifiant {item_id}")
        old_qty = row[0] or 0
        if delta == 0:
            return old_qty, 0, old_qty
        new_qty = old_qty + delta
        if new_qty < 0:
            new_qty = 0
        timestamp = datetime.now().isoformat()
        cursor.execute(
            "UPDATE items SET quantity = ?, last_updated = ?, is_medicine = 1 WHERE id = ?",
            (new_qty, timestamp, item_id),
        )
        change = new_qty - old_qty
        if change != 0:
            movement_type = "IN" if change > 0 else "OUT"
            self._log_stock_movement(
                cursor,
                item_id,
                change,
                movement_type,
                source,
                operator,
                note,
                timestamp,
            )
        return new_qty, change, old_qty

    # ------------------------------------------------------------------
    #  API publique
    # ------------------------------------------------------------------
    def register_batch(
        self,
        *,
        name: str,
        lot_number: str,
        quantity: int,
        expiration_date: Optional[str | date | datetime] = None,
        barcode: Optional[str] = None,
        category: Optional[str] = None,
        dosage: Optional[str] = None,
        form: Optional[str] = None,
        storage_condition: Optional[str] = None,
        prescription_required: bool = False,
        note: Optional[str] = None,
        operator: Optional[str] = None,
        source: str = "pharmacy_module",
        db_path: Optional[str] = None,
    ) -> dict:
        if quantity < 0:
            raise ValueError("quantity doit être positif pour l'enregistrement d'un lot")
        normalized_expiration = self._normalize_expiration(expiration_date)
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                category_id = self._ensure_category(cursor, category)
                item_id = self._ensure_item(
                    cursor,
                    name,
                    barcode,
                    category_id,
                    dosage,
                    form,
                    storage_condition,
                )
                existing = self._match_batch(cursor, item_id, lot_number, normalized_expiration)
                now = datetime.now().isoformat()
                if existing:
                    batch_id, previous_qty = existing
                    new_quantity = previous_qty + quantity
                    cursor.execute(
                        """
                        UPDATE pharmacy_inventory
                           SET quantity = ?,
                               storage_condition = COALESCE(?, storage_condition),
                               prescription_required = ?,
                               note = COALESCE(?, note),
                               updated_at = ?
                         WHERE id = ?
                        """,
                        (
                            new_quantity,
                            storage_condition,
                            int(prescription_required),
                            note,
                            now,
                            batch_id,
                        ),
                    )
                    delta = new_quantity - previous_qty
                else:
                    cursor.execute(
                        """
                        INSERT INTO pharmacy_inventory (
                            item_id, lot_number, expiration_date, quantity,
                            storage_condition, prescription_required, note,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            lot_number,
                            normalized_expiration,
                            quantity,
                            storage_condition,
                            int(prescription_required),
                            note,
                            now,
                            now,
                        ),
                    )
                    batch_id = cursor.lastrowid
                    delta = quantity
                    new_quantity = quantity
                item_state = self._apply_item_quantity_change(
                    cursor,
                    item_id,
                    delta,
                    operator,
                    source,
                    note,
                )
                conn.commit()
            finally:
                conn.close()
        return {
            "batch_id": batch_id,
            "item_id": item_id,
            "lot_number": lot_number,
            "quantity": new_quantity,
            "expiration_date": normalized_expiration,
            "item_quantity": item_state[0],
            "change": item_state[1],
        }

    def adjust_batch_quantity(
        self,
        batch_id: int,
        delta: int,
        *,
        operator: Optional[str] = None,
        source: str = "pharmacy_module",
        note: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> Optional[dict]:
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                cursor.execute(
                    """
                    SELECT item_id, quantity, lot_number, expiration_date
                      FROM pharmacy_inventory
                     WHERE id = ?
                    """,
                    (batch_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                item_id, old_qty, lot_number, expiration = row
                new_qty = old_qty + delta
                if new_qty < 0:
                    new_qty = 0
                now = datetime.now().isoformat()
                cursor.execute(
                    """
                    UPDATE pharmacy_inventory
                       SET quantity = ?,
                           note = COALESCE(?, note),
                           updated_at = ?
                     WHERE id = ?
                    """,
                    (new_qty, note, now, batch_id),
                )
                item_state = self._apply_item_quantity_change(
                    cursor,
                    item_id,
                    new_qty - old_qty,
                    operator,
                    source,
                    note,
                )
                conn.commit()
            finally:
                conn.close()
        return {
            "batch_id": batch_id,
            "item_id": item_id,
            "lot_number": lot_number,
            "expiration_date": expiration,
            "quantity": new_qty,
            "item_quantity": item_state[0],
            "change": item_state[1],
        }

    def list_expiring_batches(
        self,
        *,
        within_days: int = 30,
        include_empty: bool = False,
        db_path: Optional[str] = None,
    ) -> list[PharmacyBatch]:
        cutoff = datetime.now().date() + timedelta(days=max(within_days, 0))
        batches: list[PharmacyBatch] = []
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                cursor.execute(
                    """
                    SELECT
                        b.id,
                        b.item_id,
                        i.name,
                        b.lot_number,
                        b.expiration_date,
                        b.quantity,
                        i.dosage,
                        i.medication_form,
                        COALESCE(b.storage_condition, i.storage_condition),
                        b.prescription_required
                      FROM pharmacy_inventory AS b
                      JOIN items AS i ON i.id = b.item_id
                     WHERE b.expiration_date IS NOT NULL
                    """,
                )
                for row in cursor.fetchall():
                    expiration_str = row[4]
                    try:
                        expiration_date = (
                            datetime.fromisoformat(expiration_str).date()
                            if expiration_str
                            else None
                        )
                    except ValueError:
                        # Si la date est mal formée, elle est ignorée pour la comparaison
                        expiration_date = None
                    if expiration_date is None:
                        continue
                    if expiration_date <= cutoff:
                        quantity = row[5] or 0
                        if not include_empty and quantity <= 0:
                            continue
                        batches.append(
                            PharmacyBatch(
                                id=row[0],
                                item_id=row[1],
                                name=row[2],
                                lot_number=row[3],
                                expiration_date=row[4],
                                quantity=quantity,
                                dosage=row[6],
                                form=row[7],
                                storage_condition=row[8],
                                prescription_required=bool(row[9]),
                                days_left=(expiration_date - datetime.now().date()).days,
                            )
                        )
            finally:
                conn.close()
        return batches

    def summarize_stock(self, *, db_path: Optional[str] = None) -> dict:
        summary = {
            "total_batches": 0,
            "total_quantity": 0,
            "by_form": {},
            "by_prescription_requirement": {"required": 0, "not_required": 0},
        }
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                cursor.execute(
                    "SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM pharmacy_inventory"
                )
                row = cursor.fetchone()
                if row:
                    summary["total_batches"] = row[0] or 0
                    summary["total_quantity"] = row[1] or 0

                cursor.execute(
                    """
                    SELECT COALESCE(items.medication_form, ''),
                           COALESCE(SUM(pharmacy_inventory.quantity), 0)
                      FROM pharmacy_inventory
                      JOIN items ON items.id = pharmacy_inventory.item_id
                  GROUP BY items.medication_form
                    """
                )
                for form, qty in cursor.fetchall():
                    summary["by_form"][form or "Autres"] = qty or 0

                cursor.execute(
                    """
                    SELECT prescription_required, COALESCE(SUM(quantity), 0)
                      FROM pharmacy_inventory
                  GROUP BY prescription_required
                    """
                )
                for required, qty in cursor.fetchall():
                    key = "required" if required else "not_required"
                    summary["by_prescription_requirement"][key] = qty or 0
            finally:
                conn.close()
                return summary

    def get_batch(
        self,
        batch_id: int,
        *,
        db_path: Optional[str] = None,
    ) -> Optional[dict]:
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                cursor.execute(
                    """
                    SELECT
                        b.id,
                        b.item_id,
                        i.name,
                        b.lot_number,
                        b.expiration_date,
                        b.quantity,
                        i.barcode,
                        c.name,
                        i.dosage,
                        i.medication_form,
                        COALESCE(b.storage_condition, i.storage_condition),
                        b.prescription_required,
                        b.note
                    FROM pharmacy_inventory AS b
                    JOIN items AS i ON i.id = b.item_id
                    LEFT JOIN categories AS c ON c.id = i.category_id
                    WHERE b.id = ?
                    """,
                    (batch_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                return {
                    "batch_id": row[0],
                    "item_id": row[1],
                    "name": row[2],
                    "lot_number": row[3],
                    "expiration_date": row[4],
                    "quantity": row[5],
                    "barcode": row[6],
                    "category": row[7],
                    "dosage": row[8],
                    "form": row[9],
                    "storage_condition": row[10],
                    "prescription_required": bool(row[11]),
                    "note": row[12],
                }
            finally:
                conn.close()

    def update_batch(
        self,
        batch_id: int,
        *,
        name: str,
        lot_number: str,
        quantity: int,
        expiration_date: Optional[str | date | datetime] = None,
        barcode: Optional[str] = None,
        category: Optional[str] = None,
        dosage: Optional[str] = None,
        form: Optional[str] = None,
        storage_condition: Optional[str] = None,
        prescription_required: bool = False,
        note: Optional[str] = None,
        operator: Optional[str] = None,
        source: str = "pharmacy_module",
        db_path: Optional[str] = None,
    ) -> Optional[dict]:
        if quantity < 0:
            raise ValueError("La quantité doit être positive ou nulle.")
        normalized_expiration = self._normalize_expiration(expiration_date)
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                cursor.execute(
                    "SELECT item_id, quantity FROM pharmacy_inventory WHERE id = ?",
                    (batch_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                item_id, previous_qty = row
                category_id = self._ensure_category(cursor, category)
                now = datetime.now().isoformat()
                cursor.execute(
                    """
                    UPDATE items
                       SET name = ?,
                           barcode = ?,
                           category_id = ?,
                           dosage = ?,
                           medication_form = ?,
                           storage_condition = ?,
                           last_updated = ?,
                           is_medicine = 1
                     WHERE id = ?
                    """,
                    (
                        name,
                        barcode,
                        category_id,
                        dosage,
                        form,
                        storage_condition,
                        now,
                        item_id,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE pharmacy_inventory
                       SET lot_number = ?,
                           expiration_date = ?,
                           quantity = ?,
                           storage_condition = ?,
                           prescription_required = ?,
                           note = ?,
                           updated_at = ?
                     WHERE id = ?
                    """,
                    (
                        lot_number,
                        normalized_expiration,
                        quantity,
                        storage_condition,
                        int(prescription_required),
                        note,
                        now,
                        batch_id,
                    ),
                )
                delta = quantity - previous_qty
                item_state = self._apply_item_quantity_change(
                    cursor,
                    item_id,
                    delta,
                    operator,
                    source,
                    note,
                )
                conn.commit()
                return {
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "lot_number": lot_number,
                    "quantity": quantity,
                    "expiration_date": normalized_expiration,
                    "item_quantity": item_state[0],
                    "change": item_state[1],
                }
            finally:
                conn.close()

    def delete_batch(
        self,
        batch_id: int,
        *,
        operator: Optional[str] = None,
        source: str = "pharmacy_module",
        note: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> bool:
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                cursor.execute(
                    "SELECT item_id, quantity FROM pharmacy_inventory WHERE id = ?",
                    (batch_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return False
                item_id, quantity = row
                cursor.execute(
                    "DELETE FROM pharmacy_inventory WHERE id = ?",
                    (batch_id,),
                )
                if quantity:
                    self._apply_item_quantity_change(
                        cursor,
                        item_id,
                        -int(quantity),
                        operator,
                        source,
                        note,
                    )
                conn.commit()
                return True
            finally:
                conn.close()

    def list_batches(
        self,
        *,
        search: Optional[str] = None,
        include_zero: bool = True,
        db_path: Optional[str] = None,
    ) -> list[PharmacyBatch]:
        """Retourne l'ensemble des lots en respectant le filtre fourni."""

        normalized_search = search.strip().lower() if search else None
        wildcard = f"%{normalized_search}%" if normalized_search else None
        query = [
            "SELECT",
            "    b.id,",
            "    b.item_id,",
            "    i.name,",
            "    b.lot_number,",
            "    b.expiration_date,",
            "    b.quantity,",
            "    i.dosage,",
            "    i.medication_form,",
            "    COALESCE(b.storage_condition, i.storage_condition),",
            "    b.prescription_required",
            "  FROM pharmacy_inventory AS b",
            "  JOIN items AS i ON i.id = b.item_id",
        ]
        conditions: list[str] = []
        params: list[object] = []
        if normalized_search:
            conditions.append(
                "(LOWER(i.name) LIKE ? OR LOWER(b.lot_number) LIKE ? OR LOWER(COALESCE(i.barcode, '')) LIKE ?)"
            )
            params.extend([wildcard, wildcard, wildcard])
        if not include_zero:
            conditions.append("b.quantity > 0")
        if conditions:
            query.append(" WHERE ")
            query.append(" AND ".join(conditions))
        query.append(
            " ORDER BY i.name COLLATE NOCASE, b.expiration_date IS NULL, b.expiration_date"
        )
        sql = "".join(query)

        batches: list[PharmacyBatch] = []
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cursor = conn.cursor()
                self._ensure_schema(cursor)
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
            finally:
                conn.close()

        for row in rows:
            expiration_str = row[4]
            days_left: Optional[int]
            if expiration_str:
                try:
                    expiration_date = datetime.fromisoformat(expiration_str).date()
                    days_left = (expiration_date - datetime.now().date()).days
                except ValueError:
                    days_left = None
            else:
                days_left = None
            batches.append(
                PharmacyBatch(
                    id=row[0],
                    item_id=row[1],
                    name=row[2],
                    lot_number=row[3],
                    expiration_date=row[4],
                    quantity=row[5] or 0,
                    dosage=row[6],
                    form=row[7],
                    storage_condition=row[8],
                    prescription_required=bool(row[9]),
                    days_left=days_left,
                )
            )
        return batches


__all__ = [
    "PharmacyInventoryManager",
    "PharmacyBatch",
]
