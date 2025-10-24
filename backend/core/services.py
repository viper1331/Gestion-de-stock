"""Services métier pour Gestion Stock Pro."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from backend.core import db, models, security

# Initialisation des bases de données au chargement du module
_db_initialized = False


def ensure_database_ready() -> None:
    global _db_initialized
    if not _db_initialized:
        db.init_databases()
        seed_default_admin()
        _db_initialized = True


def seed_default_admin() -> None:
    with db.get_users_connection() as conn:
        cur = conn.execute("SELECT COUNT(*) AS count FROM users")
        if cur.fetchone()["count"] == 0:
            password = security.hash_password("admin123")
            conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ("admin", password, "admin"),
            )
            conn.commit()


def get_user(username: str) -> Optional[models.User]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row:
            return None
        return models.User(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            is_active=bool(row["is_active"]),
        )


def authenticate(username: str, password: str) -> Optional[models.User]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row:
            return None
        if not security.verify_password(password, row["password"]):
            return None
        return models.User(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            is_active=bool(row["is_active"]),
        )


def list_items(search: str | None = None) -> list[models.Item]:
    ensure_database_ready()
    query = "SELECT * FROM items"
    params: tuple[object, ...] = ()
    if search:
        query += " WHERE name LIKE ? OR sku LIKE ?"
        like = f"%{search}%"
        params = (like, like)
    query += " ORDER BY name COLLATE NOCASE"
    with db.get_stock_connection() as conn:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        return [
            models.Item(
                id=row["id"],
                name=row["name"],
                sku=row["sku"],
                category_id=row["category_id"],
                size=row["size"],
                quantity=row["quantity"],
                low_stock_threshold=row["low_stock_threshold"],
            )
            for row in rows
        ]


def create_item(payload: models.ItemCreate) -> models.Item:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO items (name, sku, category_id, size, quantity, low_stock_threshold)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                payload.sku,
                payload.category_id,
                payload.size,
                payload.quantity,
                payload.low_stock_threshold,
            ),
        )
        conn.commit()
        item_id = cur.lastrowid
        return get_item(item_id)


def get_item(item_id: int) -> models.Item:
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Item not found")
        return models.Item(
            id=row["id"],
            name=row["name"],
            sku=row["sku"],
            category_id=row["category_id"],
            size=row["size"],
            quantity=row["quantity"],
            low_stock_threshold=row["low_stock_threshold"],
        )


def update_item(item_id: int, payload: models.ItemUpdate) -> models.Item:
    ensure_database_ready()
    fields = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if not fields:
        return get_item(item_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values())
    values.append(item_id)
    with db.get_stock_connection() as conn:
        conn.execute(f"UPDATE items SET {assignments} WHERE id = ?", values)
        conn.commit()
    return get_item(item_id)


def delete_item(item_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()


def list_low_stock(threshold: int) -> list[models.LowStockReport]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            SELECT *, (low_stock_threshold - quantity) AS shortage
            FROM items
            WHERE quantity < low_stock_threshold AND low_stock_threshold >= ?
            ORDER BY shortage DESC
            """,
            (threshold,),
        )
        rows = cur.fetchall()
        return [
            models.LowStockReport(
                item=models.Item(
                    id=row["id"],
                    name=row["name"],
                    sku=row["sku"],
                    category_id=row["category_id"],
                    size=row["size"],
                    quantity=row["quantity"],
                    low_stock_threshold=row["low_stock_threshold"],
                ),
                shortage=row["shortage"],
            )
            for row in rows
        ]


def list_categories() -> list[models.Category]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM categories ORDER BY name COLLATE NOCASE")
        return [models.Category(id=row["id"], name=row["name"]) for row in cur.fetchall()]


def create_category(payload: models.CategoryCreate) -> models.Category:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "INSERT INTO categories (name) VALUES (?)",
            (payload.name,),
        )
        conn.commit()
        return models.Category(id=cur.lastrowid, name=payload.name)


def delete_category(category_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()


def record_movement(item_id: int, payload: models.MovementCreate) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT quantity FROM items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Item not found")

        conn.execute(
            "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
            (item_id, payload.delta, payload.reason),
        )
        conn.execute(
            "UPDATE items SET quantity = quantity + ? WHERE id = ?",
            (payload.delta, item_id),
        )
        conn.commit()


def fetch_movements(item_id: int) -> list[models.Movement]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM movements WHERE item_id = ? ORDER BY created_at DESC",
            (item_id,),
        )
        rows = cur.fetchall()
        return [
            models.Movement(
                id=row["id"],
                item_id=row["item_id"],
                delta=row["delta"],
                reason=row["reason"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


def export_items_to_csv(path: Path) -> Path:
    ensure_database_ready()
    import csv

    items = list_items()
    with path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["ID", "Nom", "SKU", "Catégorie", "Taille", "Quantité", "Seuil bas"])
        for item in items:
            writer.writerow(
                [
                    item.id,
                    item.name,
                    item.sku,
                    item.category_id,
                    item.size or "",
                    item.quantity,
                    item.low_stock_threshold,
                ]
            )
    return path


def available_config_sections() -> Iterable[str]:
    from configparser import ConfigParser

    ensure_database_ready()
    config_path = Path(__file__).resolve().parent.parent / "config.ini"
    parser = ConfigParser()
    parser.read(config_path, encoding="utf-8")
    return parser.sections()
