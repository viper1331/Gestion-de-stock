"""Gestion spécialisée pour l'inventaire pharmaceutique.

Ce module fournit une couche d'abstraction pour manipuler les lots de
médicaments, gérer les dates de péremption et synchroniser les quantités
avec la table ``items`` existante. L'objectif est d'offrir une
fonctionnalité dédiée à la pharmacie sans alourdir ``gestion_stock``.
"""

from __future__ import annotations

import os
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
        inventory_db_path_getter: Optional[Callable[[], str]] = None,
        items_db_path_getter: Optional[Callable[[], str]] = None,
        *,
        db_path_getter: Optional[Callable[[], str]] = None,
        lock,
        log_stock_movement: Callable,
        parse_user_date: Callable[[Optional[str]], Optional[str]],
    ) -> None:
        if db_path_getter is not None:
            if inventory_db_path_getter is None:
                inventory_db_path_getter = db_path_getter
            if items_db_path_getter is None:
                items_db_path_getter = db_path_getter
        if inventory_db_path_getter is None:
            raise TypeError("inventory_db_path_getter ou db_path_getter doit être fourni")
        if items_db_path_getter is None:
            items_db_path_getter = inventory_db_path_getter
        self._inventory_db_path_getter = inventory_db_path_getter
        self._items_db_path_getter = items_db_path_getter
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

    def _open_inventory_connection(self, db_path: Optional[str] = None) -> sqlite3.Connection:
        path = db_path or self._inventory_db_path_getter()
        return sqlite3.connect(path, timeout=30)

    def _open_items_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self._items_db_path_getter(), timeout=30)

    def _open_coupled_connections(
        self, db_path: Optional[str] = None
    ) -> tuple[sqlite3.Connection, sqlite3.Connection, bool]:
        inventory_path = os.path.abspath(db_path or self._inventory_db_path_getter())
        items_path = os.path.abspath(self._items_db_path_getter())
        inv_conn = self._open_inventory_connection(db_path)
        if inventory_path == items_path:
            return inv_conn, inv_conn, True
        items_conn = self._open_items_connection()
        return inv_conn, items_conn, False

    def _ensure_items_schema(self, cursor: sqlite3.Cursor) -> None:
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

    def _ensure_inventory_schema(self, cursor: sqlite3.Cursor) -> None:
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
                UNIQUE(item_id, lot_number, expiration_date)
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
            self._ensure_items_schema(cursor)
            with self._lock:
                inv_conn = self._open_inventory_connection(db_path)
                try:
                    inv_cursor = inv_conn.cursor()
                    self._ensure_inventory_schema(inv_cursor)
                    inv_conn.commit()
                finally:
                    inv_conn.close()
            return

        with self._lock:
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_cursor if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_conn.commit()
                if not shared:
                    items_conn.commit()
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()

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
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_cursor if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                category_id = self._ensure_category(items_cursor, category)
                item_id = self._ensure_item(
                    items_cursor,
                    name,
                    barcode,
                    category_id,
                    dosage,
                    form,
                    storage_condition,
                )
                existing = self._match_batch(inv_cursor, item_id, lot_number, normalized_expiration)
                now = datetime.now().isoformat()
                if existing:
                    batch_id, previous_qty = existing
                    new_quantity = previous_qty + quantity
                    inv_cursor.execute(
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
                    inv_cursor.execute(
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
                    batch_id = inv_cursor.lastrowid
                    delta = quantity
                    new_quantity = quantity
                item_state = self._apply_item_quantity_change(
                    items_cursor,
                    item_id,
                    delta,
                    operator,
                    source,
                    note,
                )
                inv_conn.commit()
                if not shared:
                    items_conn.commit()
            except Exception:
                inv_conn.rollback()
                if not shared:
                    items_conn.rollback()
                raise
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()
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
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_cursor if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_cursor.execute(
                    """
                    SELECT item_id, quantity, lot_number, expiration_date
                      FROM pharmacy_inventory
                     WHERE id = ?
                    """,
                    (batch_id,),
                )
                row = inv_cursor.fetchone()
                if not row:
                    return None
                item_id, old_qty, lot_number, expiration = row
                new_qty = old_qty + delta
                if new_qty < 0:
                    new_qty = 0
                now = datetime.now().isoformat()
                inv_cursor.execute(
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
                    items_cursor,
                    item_id,
                    new_qty - old_qty,
                    operator,
                    source,
                    note,
                )
                inv_conn.commit()
                if not shared:
                    items_conn.commit()
            except Exception:
                inv_conn.rollback()
                if not shared:
                    items_conn.rollback()
                raise
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()
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
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_conn.cursor() if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_cursor.execute(
                    """
                    SELECT id, item_id, lot_number, expiration_date, quantity,
                           storage_condition, prescription_required
                      FROM pharmacy_inventory
                     WHERE expiration_date IS NOT NULL
                    """
                )
                rows = inv_cursor.fetchall()
                item_ids = {row[1] for row in rows}
                items_data: dict[int, tuple[str, Optional[str], Optional[str], Optional[str]]] = {}
                if item_ids:
                    placeholders = ",".join("?" for _ in item_ids)
                    items_cursor.execute(
                        f"SELECT id, name, dosage, medication_form, storage_condition FROM items WHERE id IN ({placeholders})",
                        tuple(item_ids),
                    )
                    for item_id, name, dosage, form, storage in items_cursor.fetchall():
                        items_data[item_id] = (name, dosage, form, storage)
                for row in rows:
                    batch_id, item_id, lot_number, expiration_str, quantity, storage_condition, prescription_required = row
                    try:
                        expiration_date = (
                            datetime.fromisoformat(expiration_str).date()
                            if expiration_str
                            else None
                        )
                    except ValueError:
                        expiration_date = None
                    if expiration_date is None:
                        continue
                    if expiration_date <= cutoff:
                        quantity = quantity or 0
                        if not include_empty and quantity <= 0:
                            continue
                        item_name, dosage, form, item_storage = items_data.get(item_id, ("Inconnu", None, None, None))
                        batches.append(
                            PharmacyBatch(
                                id=batch_id,
                                item_id=item_id,
                                name=item_name,
                                lot_number=lot_number,
                                expiration_date=expiration_str,
                                quantity=quantity,
                                dosage=dosage,
                                form=form,
                                storage_condition=storage_condition or item_storage,
                                prescription_required=bool(prescription_required),
                                days_left=(expiration_date - datetime.now().date()).days,
                            )
                        )
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()
        return batches

    def summarize_stock(self, *, db_path: Optional[str] = None) -> dict:
        summary = {
            "total_batches": 0,
            "total_quantity": 0,
            "by_form": {},
            "by_prescription_requirement": {"required": 0, "not_required": 0},
        }
        with self._lock:
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_conn.cursor() if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_cursor.execute(
                    "SELECT id, item_id, quantity, prescription_required FROM pharmacy_inventory"
                )
                rows = inv_cursor.fetchall()
                summary["total_batches"] = len(rows)
                total_quantity = 0
                prescription_totals = {True: 0, False: 0}
                item_ids = {row[1] for row in rows}
                if item_ids:
                    placeholders = ",".join("?" for _ in item_ids)
                    items_cursor.execute(
                        f"SELECT id, medication_form FROM items WHERE id IN ({placeholders})",
                        tuple(item_ids),
                    )
                    form_map = {item_id: form for item_id, form in items_cursor.fetchall()}
                else:
                    form_map = {}
                form_totals: dict[str, int] = {}
                for _batch_id, item_id, qty, prescription_required in rows:
                    quantity = int(qty or 0)
                    total_quantity += quantity
                    form_key = form_map.get(item_id) or "Autres"
                    form_totals[form_key] = form_totals.get(form_key, 0) + quantity
                    prescription_totals[bool(prescription_required)] += quantity
                summary["total_quantity"] = total_quantity
                summary["by_form"].update(form_totals)
                summary["by_prescription_requirement"]["required"] = prescription_totals[True]
                summary["by_prescription_requirement"]["not_required"] = prescription_totals[False]
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()
        return summary

    def get_batch(
        self,
        batch_id: int,
        *,
        db_path: Optional[str] = None,
    ) -> Optional[dict]:
        with self._lock:
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_conn.cursor() if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_cursor.execute(
                    """
                    SELECT id, item_id, lot_number, expiration_date, quantity,
                           storage_condition, prescription_required, note
                      FROM pharmacy_inventory
                     WHERE id = ?
                    """,
                    (batch_id,),
                )
                row = inv_cursor.fetchone()
                if row is None:
                    return None
                batch_id, item_id, lot_number, expiration_date, quantity, storage_condition, prescription_required, note = row
                items_cursor.execute(
                    "SELECT name, barcode, category_id, dosage, medication_form, storage_condition FROM items WHERE id = ?",
                    (item_id,),
                )
                item_row = items_cursor.fetchone()
                if item_row is None:
                    item_name = "Inconnu"
                    barcode = None
                    category_name = None
                    dosage = None
                    form = None
                    item_storage = None
                else:
                    item_name, barcode, category_id, dosage, form, item_storage = item_row
                    if category_id is not None:
                        items_cursor.execute(
                            "SELECT name FROM categories WHERE id = ?",
                            (category_id,),
                        )
                        category_row = items_cursor.fetchone()
                        category_name = category_row[0] if category_row else None
                    else:
                        category_name = None
                return {
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "name": item_name,
                    "lot_number": lot_number,
                    "expiration_date": expiration_date,
                    "quantity": quantity,
                    "barcode": barcode,
                    "category": category_name,
                    "dosage": dosage,
                    "form": form,
                    "storage_condition": storage_condition or item_storage,
                    "prescription_required": bool(prescription_required),
                    "note": note,
                }
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()

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
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_cursor if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_cursor.execute(
                    "SELECT item_id, quantity FROM pharmacy_inventory WHERE id = ?",
                    (batch_id,),
                )
                row = inv_cursor.fetchone()
                if row is None:
                    return None
                item_id, previous_qty = row
                category_id = self._ensure_category(items_cursor, category)
                now = datetime.now().isoformat()
                items_cursor.execute(
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
                inv_cursor.execute(
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
                    items_cursor,
                    item_id,
                    delta,
                    operator,
                    source,
                    note,
                )
                inv_conn.commit()
                if not shared:
                    items_conn.commit()
                return {
                    "batch_id": batch_id,
                    "item_id": item_id,
                    "lot_number": lot_number,
                    "quantity": quantity,
                    "expiration_date": normalized_expiration,
                    "item_quantity": item_state[0],
                    "change": item_state[1],
                }
            except Exception:
                inv_conn.rollback()
                if not shared:
                    items_conn.rollback()
                raise
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()

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
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_cursor if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_cursor.execute(
                    "SELECT item_id, quantity FROM pharmacy_inventory WHERE id = ?",
                    (batch_id,),
                )
                row = inv_cursor.fetchone()
                if row is None:
                    return False
                item_id, quantity = row
                inv_cursor.execute(
                    "DELETE FROM pharmacy_inventory WHERE id = ?",
                    (batch_id,),
                )
                if quantity:
                    self._apply_item_quantity_change(
                        items_cursor,
                        item_id,
                        -int(quantity),
                        operator,
                        source,
                        note,
                    )
                inv_conn.commit()
                if not shared:
                    items_conn.commit()
                return True
            except Exception:
                inv_conn.rollback()
                if not shared:
                    items_conn.rollback()
                raise
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()

    def list_batches(
        self,
        *,
        search: Optional[str] = None,
        include_zero: bool = True,
        db_path: Optional[str] = None,
    ) -> list[PharmacyBatch]:
        """Retourne l'ensemble des lots en respectant le filtre fourni."""

        normalized_search = search.strip().lower() if search else None
        batches: list[PharmacyBatch] = []
        with self._lock:
            inv_conn, items_conn, shared = self._open_coupled_connections(db_path)
            try:
                inv_cursor = inv_conn.cursor()
                items_cursor = inv_conn.cursor() if shared else items_conn.cursor()
                self._ensure_inventory_schema(inv_cursor)
                self._ensure_items_schema(items_cursor)
                inv_cursor.execute(
                    """
                    SELECT id, item_id, lot_number, expiration_date, quantity,
                           storage_condition, prescription_required
                      FROM pharmacy_inventory
                    """
                )
                rows = inv_cursor.fetchall()
                item_ids = {row[1] for row in rows}
                items_data: dict[int, tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]] = {}
                if item_ids:
                    placeholders = ",".join("?" for _ in item_ids)
                    items_cursor.execute(
                        f"SELECT id, name, dosage, medication_form, storage_condition, barcode FROM items WHERE id IN ({placeholders})",
                        tuple(item_ids),
                    )
                    for item_id, name, dosage, form, storage, barcode_value in items_cursor.fetchall():
                        items_data[item_id] = (name, dosage, form, storage, barcode_value)
                filtered_rows = []
                for batch_id, item_id, lot_number, expiration_str, quantity, storage_condition, prescription_required in rows:
                    if not include_zero and int(quantity or 0) <= 0:
                        continue
                    item_info = items_data.get(item_id)
                    if item_info is None:
                        item_name = "Inconnu"
                        dosage = None
                        form = None
                        item_storage = None
                        barcode_value = None
                    else:
                        item_name, dosage, form, item_storage, barcode_value = item_info
                    if normalized_search:
                        target_values = [
                            item_name.lower(),
                            (lot_number or "").lower(),
                            (barcode_value or "").lower(),
                        ]
                        if not any(normalized_search in value for value in target_values):
                            continue
                    filtered_rows.append(
                        (
                            batch_id,
                            item_id,
                            item_name,
                            lot_number,
                            expiration_str,
                            int(quantity or 0),
                            dosage,
                            form,
                            storage_condition or item_storage,
                            bool(prescription_required),
                        )
                    )
                filtered_rows.sort(
                    key=lambda entry: (
                        entry[2].lower(),
                        entry[4] is None,
                        entry[4] or "",
                    )
                )
                for row in filtered_rows:
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
                            quantity=row[5],
                            dosage=row[6],
                            form=row[7],
                            storage_condition=row[8],
                            prescription_required=row[9],
                            days_left=days_left,
                        )
                        )
            finally:
                inv_conn.close()
                if not shared:
                    items_conn.close()
        return batches


__all__ = [
    "PharmacyInventoryManager",
    "PharmacyBatch",
]
