"""Gestion spécialisée pour l'inventaire d'habillement.

Ce module isole les opérations liées aux dotations textiles
et accessoires afin de séparer complètement ce flux du reste
de l'application principale.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional


@dataclass
class ClothingItem:
    """Représente un article d'habillement stocké dans la base."""

    id: int
    name: str
    size: Optional[str]
    category: Optional[str]
    quantity: int
    location: Optional[str]
    note: Optional[str]
    operator: Optional[str]
    updated_at: Optional[str]


class ClothingInventoryManager:
    """Gestionnaire des opérations spécifiques à l'habillement."""

    def __init__(
        self,
        db_path_getter: Callable[[], str],
        lock,
    ) -> None:
        self._db_path_getter = db_path_getter
        self._lock = lock

    # ------------------------------------------------------------------
    #  Utilitaires internes
    # ------------------------------------------------------------------
    def _open_connection(self, db_path: Optional[str] = None) -> sqlite3.Connection:
        path = db_path or self._db_path_getter()
        return sqlite3.connect(path, timeout=30)

    def _ensure_schema(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS clothing_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                size TEXT,
                category TEXT,
                quantity INTEGER NOT NULL DEFAULT 0,
                location TEXT,
                note TEXT,
                operator TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS clothing_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clothing_id INTEGER NOT NULL,
                quantity_change INTEGER NOT NULL,
                movement_type TEXT NOT NULL,
                operator TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(clothing_id) REFERENCES clothing_inventory(id)
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_clothing_inventory_name
            ON clothing_inventory(name COLLATE NOCASE)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_clothing_inventory_category
            ON clothing_inventory(category COLLATE NOCASE)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_clothing_movements_clothing
            ON clothing_movements(clothing_id)
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

    def _record_movement(
        self,
        cursor: sqlite3.Cursor,
        clothing_id: int,
        quantity_change: int,
        movement_type: str,
        operator: Optional[str],
        note: Optional[str],
    ) -> None:
        if quantity_change == 0:
            return
        cursor.execute(
            """
            INSERT INTO clothing_movements (
                clothing_id, quantity_change, movement_type, operator, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                clothing_id,
                quantity_change,
                movement_type,
                operator,
                note,
                datetime.now().isoformat(),
            ),
        )

    def _fetch_item(self, cursor: sqlite3.Cursor, clothing_id: int) -> Optional[ClothingItem]:
        cursor.execute(
            """
            SELECT id, name, size, category, quantity, location, note, operator, updated_at
            FROM clothing_inventory
            WHERE id = ?
            """,
            (clothing_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return ClothingItem(*row)

    # ------------------------------------------------------------------
    #  Opérations publiques
    # ------------------------------------------------------------------
    def register_item(
        self,
        *,
        name: str,
        size: Optional[str],
        category: Optional[str],
        quantity: int,
        location: Optional[str],
        note: Optional[str],
        operator: Optional[str],
        db_path: Optional[str] = None,
    ) -> ClothingItem:
        if quantity < 0:
            raise ValueError("La quantité doit être positive ou nulle.")
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cur = conn.cursor()
                self._ensure_schema(cur)
                cur.execute(
                    """
                    SELECT id, quantity FROM clothing_inventory
                    WHERE name = ?
                      AND ((size IS NULL AND ? IS NULL) OR size = ?)
                      AND ((category IS NULL AND ? IS NULL) OR category = ?)
                    """,
                    (name, size, size, category, category),
                )
                row = cur.fetchone()
                now = datetime.now().isoformat()
                if row is None:
                    cur.execute(
                        """
                        INSERT INTO clothing_inventory (
                            name, size, category, quantity, location, note, operator, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (name, size, category, quantity, location, note, operator, now),
                    )
                    clothing_id = cur.lastrowid
                    self._record_movement(
                        cur,
                        clothing_id,
                        quantity,
                        "initialisation",
                        operator,
                        note,
                    )
                else:
                    clothing_id, current_quantity = row
                    delta = quantity - current_quantity
                    cur.execute(
                        """
                        UPDATE clothing_inventory
                        SET quantity = ?, location = ?, note = ?, operator = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (quantity, location, note, operator, now, clothing_id),
                    )
                    self._record_movement(
                        cur,
                        clothing_id,
                        delta,
                        "ajustement",
                        operator,
                        note,
                    )
                conn.commit()
                return self._fetch_item(cur, clothing_id)  # type: ignore[return-value]
            finally:
                conn.close()

    def adjust_quantity(
        self,
        clothing_id: int,
        delta: int,
        *,
        operator: Optional[str],
        note: Optional[str] = None,
        db_path: Optional[str] = None,
    ) -> Optional[ClothingItem]:
        if delta == 0:
            return self.get_item(clothing_id, db_path=db_path)
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cur = conn.cursor()
                self._ensure_schema(cur)
                cur.execute(
                    "SELECT quantity FROM clothing_inventory WHERE id = ?",
                    (clothing_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                current_quantity = int(row[0])
                new_quantity = current_quantity + delta
                if new_quantity < 0:
                    raise ValueError("La quantité ne peut pas devenir négative.")
                now = datetime.now().isoformat()
                cur.execute(
                    """
                    UPDATE clothing_inventory
                    SET quantity = ?, operator = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_quantity, operator, now, clothing_id),
                )
                movement_type = "entrée" if delta > 0 else "sortie"
                self._record_movement(
                    cur,
                    clothing_id,
                    delta,
                    movement_type,
                    operator,
                    note,
                )
                conn.commit()
                return self._fetch_item(cur, clothing_id)
            finally:
                conn.close()

    def list_items(
        self,
        *,
        search: str = "",
        include_zero: bool = True,
        db_path: Optional[str] = None,
    ) -> list[ClothingItem]:
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cur = conn.cursor()
                self._ensure_schema(cur)
                query = (
                    "SELECT id, name, size, category, quantity, location, note, operator, updated_at "
                    "FROM clothing_inventory"
                )
                params: list[object] = []
                conditions: list[str] = []
                if search:
                    pattern = f"%{search.strip()}%"
                    conditions.append(
                        "(name LIKE ? OR category LIKE ? OR size LIKE ? OR location LIKE ? OR note LIKE ?)"
                    )
                    params.extend([pattern] * 5)
                if not include_zero:
                    conditions.append("quantity > 0")
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " ORDER BY name COLLATE NOCASE, size COLLATE NOCASE"
                cur.execute(query, params)
                rows = cur.fetchall()
                return [ClothingItem(*row) for row in rows]
            finally:
                conn.close()

    def summarize_stock(
        self,
        *,
        db_path: Optional[str] = None,
    ) -> dict:
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cur = conn.cursor()
                self._ensure_schema(cur)
                cur.execute(
                    "SELECT COUNT(*), COALESCE(SUM(quantity), 0) FROM clothing_inventory"
                )
                total_items, total_quantity = cur.fetchone()
                cur.execute(
                    """
                    SELECT COUNT(*) FROM clothing_inventory
                    WHERE quantity <= 0
                    """
                )
                depleted = cur.fetchone()[0]
                return {
                    "total_items": int(total_items or 0),
                    "total_quantity": int(total_quantity or 0),
                    "depleted": int(depleted or 0),
                }
            finally:
                conn.close()

    def get_item(
        self,
        clothing_id: int,
        *,
        db_path: Optional[str] = None,
    ) -> Optional[ClothingItem]:
        with self._lock:
            conn = self._open_connection(db_path)
            try:
                cur = conn.cursor()
                self._ensure_schema(cur)
                return self._fetch_item(cur, clothing_id)
            finally:
                conn.close()
