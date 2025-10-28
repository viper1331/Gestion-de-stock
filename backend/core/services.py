"""Services métier pour Gestion Stock Pro."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from backend.core import db, models, security

# Initialisation des bases de données au chargement du module
_db_initialized = False

_AUTO_PO_CLOSED_STATUSES = ("CANCELLED", "RECEIVED")


def ensure_database_ready() -> None:
    global _db_initialized
    if not _db_initialized:
        db.init_databases()
        _apply_schema_migrations()
        seed_default_admin()
        _db_initialized = True


def _apply_schema_migrations() -> None:
    with db.get_stock_connection() as conn:
        cur = conn.execute("PRAGMA table_info(items)")
        columns = {row["name"] for row in cur.fetchall()}
        if "supplier_id" not in columns:
            conn.execute(
                "ALTER TABLE items ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL"
            )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                note TEXT,
                auto_created INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                quantity_ordered INTEGER NOT NULL,
                quantity_received INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_purchase_order_items_item ON purchase_order_items(item_id);
            CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status);
        """
        )

        po_info = conn.execute("PRAGMA table_info(purchase_orders)").fetchall()
        po_columns = {row["name"] for row in po_info}
        if "auto_created" not in po_columns:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN auto_created INTEGER NOT NULL DEFAULT 0")
        if "note" not in po_columns:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN note TEXT")
        if "created_at" not in po_columns:
            conn.execute(
                "ALTER TABLE purchase_orders ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        if "status" not in po_columns:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'")
        if "supplier_id" not in po_columns:
            conn.execute("ALTER TABLE purchase_orders ADD COLUMN supplier_id INTEGER")

        poi_info = conn.execute("PRAGMA table_info(purchase_order_items)").fetchall()
        poi_columns = {row["name"] for row in poi_info}
        if "quantity_received" not in poi_columns:
            conn.execute(
                "ALTER TABLE purchase_order_items ADD COLUMN quantity_received INTEGER NOT NULL DEFAULT 0"
            )

        conn.commit()


def _maybe_create_auto_purchase_order(conn: sqlite3.Connection, item_id: int) -> None:
    cur = conn.execute(
        "SELECT id, name, quantity, low_stock_threshold, supplier_id FROM items WHERE id = ?",
        (item_id,),
    )
    item = cur.fetchone()
    if item is None:
        return
    supplier_id = item["supplier_id"]
    if supplier_id is None:
        return
    threshold = item["low_stock_threshold"] or 0
    if threshold <= 0:
        return
    quantity = item["quantity"] or 0
    shortage = threshold - quantity
    if shortage <= 0:
        return

    existing = conn.execute(
        """
        SELECT poi.id, poi.quantity_ordered, poi.quantity_received
        FROM purchase_order_items AS poi
        JOIN purchase_orders AS po ON po.id = poi.purchase_order_id
        WHERE poi.item_id = ?
          AND po.auto_created = 1
          AND UPPER(po.status) NOT IN ({placeholders})
        ORDER BY po.created_at DESC
        LIMIT 1
        """.format(
            placeholders=", ".join("?" for _ in _AUTO_PO_CLOSED_STATUSES)
        ),
        (item_id, *[status for status in _AUTO_PO_CLOSED_STATUSES]),
    ).fetchone()

    if existing:
        outstanding = existing["quantity_ordered"] - existing["quantity_received"]
        if outstanding < shortage:
            new_total = existing["quantity_received"] + shortage
            conn.execute(
                "UPDATE purchase_order_items SET quantity_ordered = ? WHERE id = ?",
                (new_total, existing["id"]),
            )
        return

    note = f"Commande automatique - {item['name']}"
    po_cur = conn.execute(
        """
        INSERT INTO purchase_orders (supplier_id, status, note, auto_created)
        VALUES (?, 'PENDING', ?, 1)
        """,
        (supplier_id, note),
    )
    order_id = po_cur.lastrowid
    conn.execute(
        """
        INSERT INTO purchase_order_items (purchase_order_id, item_id, quantity_ordered)
        VALUES (?, ?, ?)
        """,
        (order_id, item_id, shortage),
    )


def seed_default_admin() -> None:
    default_username = "admin"
    default_password = "admin123"
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT id, password, role, is_active FROM users WHERE username = ?",
            (default_username,),
        )
        row = cur.fetchone()
        hashed_password = security.hash_password(default_password)
        if row is None:
            conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
                (default_username, hashed_password, "admin"),
            )
            conn.commit()
            return

        needs_update = False
        if not security.verify_password(default_password, row["password"]):
            needs_update = True
        if row["role"] != "admin" or not bool(row["is_active"]):
            needs_update = True

        if needs_update:
            conn.execute(
                "UPDATE users SET password = ?, role = ?, is_active = 1 WHERE id = ?",
                (hashed_password, "admin", row["id"]),
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


def get_user_by_id(user_id: int) -> Optional[models.User]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        return models.User(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            is_active=bool(row["is_active"]),
        )


def list_users() -> list[models.User]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM users ORDER BY username COLLATE NOCASE",
        )
        rows = cur.fetchall()
        return [
            models.User(
                id=row["id"],
                username=row["username"],
                role=row["role"],
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]


def create_user(payload: models.UserCreate) -> models.User:
    ensure_database_ready()
    hashed = security.hash_password(payload.password)
    with db.get_users_connection() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
                (payload.username, hashed, payload.role),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Username already exists") from exc
        conn.commit()
        user_id = cur.lastrowid
    created = get_user_by_id(user_id)
    if created is None:  # pragma: no cover - inserted row should exist
        raise ValueError("Failed to create user")
    return created


def update_user(user_id: int, payload: models.UserUpdate) -> models.User:
    ensure_database_ready()
    current = get_user_by_id(user_id)
    if current is None:
        raise ValueError("User not found")

    if current.username == "admin":
        if payload.role is not None and payload.role != "admin":
            raise ValueError("Cannot change default admin role")
        if payload.is_active is not None and not payload.is_active:
            raise ValueError("Cannot deactivate default admin")

    fields: dict[str, object] = {}
    if payload.role is not None:
        fields["role"] = payload.role
    if payload.password is not None:
        fields["password"] = security.hash_password(payload.password)
    if payload.is_active is not None:
        fields["is_active"] = 1 if payload.is_active else 0

    if not fields:
        return current

    assignments = ", ".join(f"{column} = ?" for column in fields)
    values = list(fields.values())
    values.append(user_id)

    with db.get_users_connection() as conn:
        conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", values)
        conn.commit()

    updated = get_user_by_id(user_id)
    if updated is None:  # pragma: no cover
        raise ValueError("User not found")
    return updated


def delete_user(user_id: int) -> None:
    ensure_database_ready()
    current = get_user_by_id(user_id)
    if current is None:
        raise ValueError("User not found")
    if current.username == "admin":
        raise ValueError("Cannot delete default admin user")
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


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
                supplier_id=row["supplier_id"],
            )
            for row in rows
        ]


def create_item(payload: models.ItemCreate) -> models.Item:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO items (name, sku, category_id, size, quantity, low_stock_threshold, supplier_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                payload.sku,
                payload.category_id,
                payload.size,
                payload.quantity,
                payload.low_stock_threshold,
                payload.supplier_id,
            ),
        )
        item_id = cur.lastrowid
        _maybe_create_auto_purchase_order(conn, item_id)
        conn.commit()
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
                supplier_id=row["supplier_id"],
        )


def update_item(item_id: int, payload: models.ItemUpdate) -> models.Item:
    ensure_database_ready()
    fields = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if not fields:
        return get_item(item_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values())
    values.append(item_id)
    should_check_low_stock = any(key in fields for key in {"quantity", "low_stock_threshold", "supplier_id"})
    with db.get_stock_connection() as conn:
        conn.execute(f"UPDATE items SET {assignments} WHERE id = ?", values)
        if should_check_low_stock:
            _maybe_create_auto_purchase_order(conn, item_id)
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
                    supplier_id=row["supplier_id"],
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
        _maybe_create_auto_purchase_order(conn, item_id)
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


def list_suppliers() -> list[models.Supplier]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM suppliers ORDER BY name COLLATE NOCASE")
        return [
            models.Supplier(
                id=row["id"],
                name=row["name"],
                contact_name=row["contact_name"],
                phone=row["phone"],
                email=row["email"],
                address=row["address"],
            )
            for row in cur.fetchall()
        ]


def get_supplier(supplier_id: int) -> models.Supplier:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Supplier not found")
        return models.Supplier(
            id=row["id"],
            name=row["name"],
            contact_name=row["contact_name"],
            phone=row["phone"],
            email=row["email"],
            address=row["address"],
        )


def create_supplier(payload: models.SupplierCreate) -> models.Supplier:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO suppliers (name, contact_name, phone, email, address)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.name, payload.contact_name, payload.phone, payload.email, payload.address),
        )
        conn.commit()
        return get_supplier(cur.lastrowid)


def update_supplier(supplier_id: int, payload: models.SupplierUpdate) -> models.Supplier:
    ensure_database_ready()
    fields = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if not fields:
        return get_supplier(supplier_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values())
    values.append(supplier_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,))
        if cur.fetchone() is None:
            raise ValueError("Supplier not found")
        conn.execute(f"UPDATE suppliers SET {assignments} WHERE id = ?", values)
        conn.commit()
    return get_supplier(supplier_id)


def delete_supplier(supplier_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        if cur.rowcount == 0:
            raise ValueError("Supplier not found")
        conn.commit()


def list_collaborators() -> list[models.Collaborator]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM collaborators ORDER BY full_name COLLATE NOCASE")
        return [
            models.Collaborator(
                id=row["id"],
                full_name=row["full_name"],
                department=row["department"],
                email=row["email"],
                phone=row["phone"],
            )
            for row in cur.fetchall()
        ]


def get_collaborator(collaborator_id: int) -> models.Collaborator:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM collaborators WHERE id = ?", (collaborator_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Collaborator not found")
        return models.Collaborator(
            id=row["id"],
            full_name=row["full_name"],
            department=row["department"],
            email=row["email"],
            phone=row["phone"],
        )


def create_collaborator(payload: models.CollaboratorCreate) -> models.Collaborator:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO collaborators (full_name, department, email, phone)
            VALUES (?, ?, ?, ?)
            """,
            (payload.full_name, payload.department, payload.email, payload.phone),
        )
        conn.commit()
        return get_collaborator(cur.lastrowid)


def update_collaborator(collaborator_id: int, payload: models.CollaboratorUpdate) -> models.Collaborator:
    ensure_database_ready()
    fields = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if not fields:
        return get_collaborator(collaborator_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values())
    values.append(collaborator_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT 1 FROM collaborators WHERE id = ?", (collaborator_id,))
        if cur.fetchone() is None:
            raise ValueError("Collaborator not found")
        conn.execute(f"UPDATE collaborators SET {assignments} WHERE id = ?", values)
        conn.commit()
    return get_collaborator(collaborator_id)


def delete_collaborator(collaborator_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("DELETE FROM collaborators WHERE id = ?", (collaborator_id,))
        if cur.rowcount == 0:
            raise ValueError("Collaborator not found")
        conn.commit()


def list_dotations(
    *, collaborator_id: Optional[int] = None, item_id: Optional[int] = None
) -> list[models.Dotation]:
    ensure_database_ready()
    query = "SELECT * FROM dotations"
    clauses: list[str] = []
    params: list[object] = []
    if collaborator_id is not None:
        clauses.append("collaborator_id = ?")
        params.append(collaborator_id)
    if item_id is not None:
        clauses.append("item_id = ?")
        params.append(item_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY allocated_at DESC"
    with db.get_stock_connection() as conn:
        cur = conn.execute(query, tuple(params))
        return [
            models.Dotation(
                id=row["id"],
                collaborator_id=row["collaborator_id"],
                item_id=row["item_id"],
                quantity=row["quantity"],
                notes=row["notes"],
                allocated_at=row["allocated_at"],
            )
            for row in cur.fetchall()
        ]


def get_dotation(dotation_id: int) -> models.Dotation:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM dotations WHERE id = ?", (dotation_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Dotation not found")
        return models.Dotation(
            id=row["id"],
            collaborator_id=row["collaborator_id"],
            item_id=row["item_id"],
            quantity=row["quantity"],
            notes=row["notes"],
            allocated_at=row["allocated_at"],
        )


def create_dotation(payload: models.DotationCreate) -> models.Dotation:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT quantity FROM items WHERE id = ?", (payload.item_id,))
        item_row = cur.fetchone()
        if item_row is None:
            raise ValueError("Item not found")
        if item_row["quantity"] < payload.quantity:
            raise ValueError("Insufficient stock for allocation")

        collaborator_cur = conn.execute(
            "SELECT 1 FROM collaborators WHERE id = ?", (payload.collaborator_id,)
        )
        if collaborator_cur.fetchone() is None:
            raise ValueError("Collaborator not found")

        cur = conn.execute(
            """
            INSERT INTO dotations (collaborator_id, item_id, quantity, notes)
            VALUES (?, ?, ?, ?)
            """,
            (
                payload.collaborator_id,
                payload.item_id,
                payload.quantity,
                payload.notes,
            ),
        )
        conn.execute(
            "UPDATE items SET quantity = quantity - ? WHERE id = ?",
            (payload.quantity, payload.item_id),
        )
        conn.commit()
        return get_dotation(cur.lastrowid)


def delete_dotation(dotation_id: int, *, restock: bool = False) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT item_id, quantity FROM dotations WHERE id = ?", (dotation_id,)
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Dotation not found")
        conn.execute("DELETE FROM dotations WHERE id = ?", (dotation_id,))
        if restock:
            conn.execute(
                "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                (row["quantity"], row["item_id"]),
            )
        conn.commit()


def list_pharmacy_items() -> list[models.PharmacyItem]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM pharmacy_items ORDER BY name COLLATE NOCASE")
        return [
            models.PharmacyItem(
                id=row["id"],
                name=row["name"],
                dosage=row["dosage"],
                quantity=row["quantity"],
                expiration_date=row["expiration_date"],
                location=row["location"],
            )
            for row in cur.fetchall()
        ]


def get_pharmacy_item(item_id: int) -> models.PharmacyItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM pharmacy_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Pharmacy item not found")
        return models.PharmacyItem(
            id=row["id"],
            name=row["name"],
            dosage=row["dosage"],
            quantity=row["quantity"],
            expiration_date=row["expiration_date"],
            location=row["location"],
        )


def create_pharmacy_item(payload: models.PharmacyItemCreate) -> models.PharmacyItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO pharmacy_items (name, dosage, quantity, expiration_date, location)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload.name,
                payload.dosage,
                payload.quantity,
                payload.expiration_date,
                payload.location,
            ),
        )
        conn.commit()
        return get_pharmacy_item(cur.lastrowid)


def update_pharmacy_item(item_id: int, payload: models.PharmacyItemUpdate) -> models.PharmacyItem:
    ensure_database_ready()
    fields = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if not fields:
        return get_pharmacy_item(item_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values())
    values.append(item_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT 1 FROM pharmacy_items WHERE id = ?", (item_id,))
        if cur.fetchone() is None:
            raise ValueError("Pharmacy item not found")
        conn.execute(f"UPDATE pharmacy_items SET {assignments} WHERE id = ?", values)
        conn.commit()
    return get_pharmacy_item(item_id)


def delete_pharmacy_item(item_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("DELETE FROM pharmacy_items WHERE id = ?", (item_id,))
        if cur.rowcount == 0:
            raise ValueError("Pharmacy item not found")
        conn.commit()


def list_module_permissions() -> list[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions ORDER BY role, module COLLATE NOCASE"
        )
        return [
            models.ModulePermission(
                id=row["id"],
                role=row["role"],
                module=row["module"],
                can_view=bool(row["can_view"]),
                can_edit=bool(row["can_edit"]),
            )
            for row in cur.fetchall()
        ]


def list_module_permissions_for_role(role: str) -> list[models.ModulePermission]:
    ensure_database_ready()
    if role == "admin":
        # Admins implicitly have access to every module; return stored overrides for completeness.
        return list_module_permissions()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions WHERE role = ? ORDER BY module COLLATE NOCASE",
            (role,),
        )
        return [
            models.ModulePermission(
                id=row["id"],
                role=row["role"],
                module=row["module"],
                can_view=bool(row["can_view"]),
                can_edit=bool(row["can_edit"]),
            )
            for row in cur.fetchall()
        ]


def get_module_permission(role: str, module: str) -> Optional[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions WHERE role = ? AND module = ?",
            (role, module),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return models.ModulePermission(
            id=row["id"],
            role=row["role"],
            module=row["module"],
            can_view=bool(row["can_view"]),
            can_edit=bool(row["can_edit"]),
        )


def upsert_module_permission(payload: models.ModulePermissionUpsert) -> models.ModulePermission:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO module_permissions (role, module, can_view, can_edit)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(role, module) DO UPDATE SET
                can_view = excluded.can_view,
                can_edit = excluded.can_edit
            """,
            (
                payload.role,
                payload.module,
                int(payload.can_view),
                int(payload.can_edit),
            ),
        )
        conn.commit()
    permission = get_module_permission(payload.role, payload.module)
    if permission is None:
        raise RuntimeError("Failed to persist module permission")
    return permission


def delete_module_permission(role: str, module: str) -> None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "DELETE FROM module_permissions WHERE role = ? AND module = ?",
            (role, module),
        )
        if cur.rowcount == 0:
            raise ValueError("Module permission not found")
        conn.commit()


def has_module_access(role: str, module: str, *, action: str = "view") -> bool:
    ensure_database_ready()
    if role == "admin":
        return True
    permission = get_module_permission(role, module)
    if permission is None:
        return False
    if action == "edit":
        return permission.can_edit
    return permission.can_view
