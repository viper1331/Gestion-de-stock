"""Services métier pour Gestion Stock Pro."""
from __future__ import annotations

import io
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from textwrap import wrap
from typing import Callable, Iterable, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from backend.core import db, models, security

# Initialisation des bases de données au chargement du module
_db_initialized = False

_AUTO_PO_CLOSED_STATUSES = ("CANCELLED", "RECEIVED")

_AVAILABLE_MODULE_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("suppliers", "Fournisseurs"),
    ("dotations", "Dotations"),
    ("pharmacy", "Pharmacie"),
    ("vehicle_inventory", "Inventaire véhicules"),
    ("inventory_remise", "Inventaire remises"),
)
_AVAILABLE_MODULE_KEYS: set[str] = {key for key, _ in _AVAILABLE_MODULE_DEFINITIONS}


@dataclass(frozen=True)
class _InventoryTables:
    items: str
    categories: str
    category_sizes: str
    movements: str


@dataclass(frozen=True)
class _InventoryModuleConfig:
    tables: _InventoryTables
    auto_purchase_orders: bool = False


_INVENTORY_MODULE_CONFIGS: dict[str, _InventoryModuleConfig] = {
    "default": _InventoryModuleConfig(
        tables=_InventoryTables(
            items="items",
            categories="categories",
            category_sizes="category_sizes",
            movements="movements",
        ),
        auto_purchase_orders=True,
    ),
    "vehicle_inventory": _InventoryModuleConfig(
        tables=_InventoryTables(
            items="vehicle_items",
            categories="vehicle_categories",
            category_sizes="vehicle_category_sizes",
            movements="vehicle_movements",
        )
    ),
    "inventory_remise": _InventoryModuleConfig(
        tables=_InventoryTables(
            items="remise_items",
            categories="remise_categories",
            category_sizes="remise_category_sizes",
            movements="remise_movements",
        )
    ),
}


def _get_inventory_config(module: str) -> _InventoryModuleConfig:
    try:
        return _INVENTORY_MODULE_CONFIGS[module]
    except KeyError as exc:  # pragma: no cover - defensive programming
        raise ValueError(f"Module d'inventaire inconnu: {module}") from exc

_PURCHASE_ORDER_STATUSES: set[str] = {
    "PENDING",
    "ORDERED",
    "PARTIALLY_RECEIVED",
    "RECEIVED",
    "CANCELLED",
}

_PURCHASE_ORDER_STATUS_LABELS: dict[str, str] = {
    "PENDING": "En attente",
    "ORDERED": "Commandé",
    "PARTIALLY_RECEIVED": "Partiellement reçu",
    "RECEIVED": "Reçu",
    "CANCELLED": "Annulé",
}


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                return None
    return None


def _ensure_date(value: object, *, fallback: date | None = None) -> date:
    parsed = _parse_date(value)
    if parsed is not None:
        return parsed
    return fallback or date.today()


def _is_obsolete(perceived_at: date | None, *, reference: date | None = None) -> bool:
    if perceived_at is None:
        return False
    limit = (reference or date.today()) - timedelta(days=365)
    return perceived_at <= limit


def _normalize_purchase_order_status(status: str | None) -> str:
    candidate = (status or "PENDING").strip().upper()
    if candidate not in _PURCHASE_ORDER_STATUSES:
        raise ValueError("Statut de commande invalide")
    return candidate


def _aggregate_positive_quantities(entries: Iterable[tuple[int, int]]) -> dict[int, int]:
    aggregated: dict[int, int] = {}
    for item_id, quantity in entries:
        if quantity <= 0:
            continue
        aggregated[item_id] = aggregated.get(item_id, 0) + quantity
    return aggregated


def _normalize_supplier_modules(modules: Iterable[str] | None) -> list[str]:
    normalized: list[str] = []
    if modules:
        for module in modules:
            module_key = (module or "").strip().lower()
            if not module_key:
                continue
            normalized.append(module_key)
    unique = list(dict.fromkeys(normalized))
    if not unique:
        return ["suppliers"]
    return unique


def _replace_supplier_modules(
    conn: sqlite3.Connection, supplier_id: int, modules: Iterable[str]
) -> None:
    conn.execute("DELETE FROM supplier_modules WHERE supplier_id = ?", (supplier_id,))
    values = [(supplier_id, module) for module in modules]
    if values:
        conn.executemany(
            "INSERT INTO supplier_modules (supplier_id, module) VALUES (?, ?)",
            values,
        )


def _load_supplier_modules(
    conn: sqlite3.Connection, supplier_ids: list[int]
) -> dict[int, list[str]]:
    modules_map: dict[int, list[str]] = {supplier_id: [] for supplier_id in supplier_ids}
    if not supplier_ids:
        return modules_map
    placeholders = ", ".join("?" for _ in supplier_ids)
    cur = conn.execute(
        f"SELECT supplier_id, module FROM supplier_modules WHERE supplier_id IN ({placeholders})",
        supplier_ids,
    )
    for row in cur.fetchall():
        modules_map.setdefault(row["supplier_id"], []).append(row["module"])
    for supplier_id, modules in modules_map.items():
        if modules:
            modules_map[supplier_id] = sorted(set(modules))
    return modules_map


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

        dotation_info = conn.execute("PRAGMA table_info(dotations)").fetchall()
        dotation_columns = {row["name"] for row in dotation_info}
        if "perceived_at" not in dotation_columns:
            conn.execute("ALTER TABLE dotations ADD COLUMN perceived_at DATE DEFAULT CURRENT_DATE")
        if "is_lost" not in dotation_columns:
            conn.execute("ALTER TABLE dotations ADD COLUMN is_lost INTEGER NOT NULL DEFAULT 0")
        if "is_degraded" not in dotation_columns:
            conn.execute("ALTER TABLE dotations ADD COLUMN is_degraded INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "UPDATE dotations SET perceived_at = DATE(allocated_at) WHERE perceived_at IS NULL OR perceived_at = ''"
        )

        pharmacy_info = conn.execute("PRAGMA table_info(pharmacy_items)").fetchall()
        pharmacy_columns = {row["name"] for row in pharmacy_info}
        if "packaging" not in pharmacy_columns:
            conn.execute("ALTER TABLE pharmacy_items ADD COLUMN packaging TEXT")
        if "barcode" not in pharmacy_columns:
            conn.execute("ALTER TABLE pharmacy_items ADD COLUMN barcode TEXT")
        if "low_stock_threshold" not in pharmacy_columns:
            conn.execute(
                "ALTER TABLE pharmacy_items ADD COLUMN low_stock_threshold INTEGER NOT NULL DEFAULT 5"
            )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pharmacy_items_barcode
            ON pharmacy_items(barcode)
            WHERE barcode IS NOT NULL
            """
        )

        pharmacy_po_info = conn.execute("PRAGMA table_info(pharmacy_purchase_orders)").fetchall()
        pharmacy_po_columns = {row["name"] for row in pharmacy_po_info}
        if "supplier_id" not in pharmacy_po_columns:
            conn.execute(
                "ALTER TABLE pharmacy_purchase_orders ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL"
            )
        if "status" not in pharmacy_po_columns:
            conn.execute(
                "ALTER TABLE pharmacy_purchase_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'"
            )
        if "created_at" not in pharmacy_po_columns:
            conn.execute(
                "ALTER TABLE pharmacy_purchase_orders ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        if "note" not in pharmacy_po_columns:
            conn.execute("ALTER TABLE pharmacy_purchase_orders ADD COLUMN note TEXT")

        pharmacy_poi_info = conn.execute("PRAGMA table_info(pharmacy_purchase_order_items)").fetchall()
        pharmacy_poi_columns = {row["name"] for row in pharmacy_poi_info}
        if "quantity_received" not in pharmacy_poi_columns:
            conn.execute(
                "ALTER TABLE pharmacy_purchase_order_items ADD COLUMN quantity_received INTEGER NOT NULL DEFAULT 0"
            )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pharmacy_purchase_orders_status ON pharmacy_purchase_orders(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pharmacy_purchase_order_items_item ON pharmacy_purchase_order_items(pharmacy_item_id)"
        )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS supplier_modules (
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                module TEXT NOT NULL,
                PRIMARY KEY (supplier_id, module)
            );
            CREATE TABLE IF NOT EXISTS pharmacy_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pharmacy_category_sizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES pharmacy_categories(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                UNIQUE(category_id, name)
            );
            CREATE TABLE IF NOT EXISTS pharmacy_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
                delta INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_pharmacy_movements_item ON pharmacy_movements(pharmacy_item_id);
            CREATE TABLE IF NOT EXISTS vehicle_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vehicle_category_sizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES vehicle_categories(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                UNIQUE(category_id, name)
            );
            CREATE TABLE IF NOT EXISTS vehicle_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT UNIQUE NOT NULL,
                category_id INTEGER REFERENCES vehicle_categories(id) ON DELETE SET NULL,
                size TEXT,
                quantity INTEGER NOT NULL DEFAULT 0,
                low_stock_threshold INTEGER NOT NULL DEFAULT 0,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS vehicle_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES vehicle_items(id) ON DELETE CASCADE,
                delta INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_vehicle_movements_item ON vehicle_movements(item_id);
            CREATE TABLE IF NOT EXISTS remise_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS remise_category_sizes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES remise_categories(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                UNIQUE(category_id, name)
            );
            CREATE TABLE IF NOT EXISTS remise_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT UNIQUE NOT NULL,
                category_id INTEGER REFERENCES remise_categories(id) ON DELETE SET NULL,
                size TEXT,
                quantity INTEGER NOT NULL DEFAULT 0,
                low_stock_threshold INTEGER NOT NULL DEFAULT 0,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS remise_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES remise_items(id) ON DELETE CASCADE,
                delta INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_remise_movements_item ON remise_movements(item_id);
            """
        )

        pharmacy_category_info = conn.execute("PRAGMA table_info(pharmacy_items)").fetchall()
        pharmacy_category_columns = {row["name"] for row in pharmacy_category_info}
        if "category_id" not in pharmacy_category_columns:
            conn.execute(
                """
                ALTER TABLE pharmacy_items
                ADD COLUMN category_id INTEGER REFERENCES pharmacy_categories(id) ON DELETE SET NULL
                """
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


def _build_inventory_item(row: sqlite3.Row) -> models.Item:
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


def _list_inventory_items_internal(
    module: str, search: str | None = None
) -> list[models.Item]:
    ensure_database_ready()
    config = _get_inventory_config(module)
    query = f"SELECT * FROM {config.tables.items}"
    params: tuple[object, ...] = ()
    if search:
        query += " WHERE name LIKE ? OR sku LIKE ?"
        like = f"%{search}%"
        params = (like, like)
    query += " ORDER BY name COLLATE NOCASE"
    with db.get_stock_connection() as conn:
        cur = conn.execute(query, params)
        return [_build_inventory_item(row) for row in cur.fetchall()]


def _get_inventory_item_internal(module: str, item_id: int) -> models.Item:
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT * FROM {config.tables.items} WHERE id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        return _build_inventory_item(row)


def _create_inventory_item_internal(
    module: str, payload: models.ItemCreate
) -> models.Item:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"""
            INSERT INTO {config.tables.items} (name, sku, category_id, size, quantity, low_stock_threshold, supplier_id)
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
        if config.auto_purchase_orders:
            _maybe_create_auto_purchase_order(conn, item_id)
        conn.commit()
    return _get_inventory_item_internal(module, item_id)


def _update_inventory_item_internal(
    module: str, item_id: int, payload: models.ItemUpdate
) -> models.Item:
    ensure_database_ready()
    config = _get_inventory_config(module)
    fields = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if not fields:
        return _get_inventory_item_internal(module, item_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values())
    values.append(item_id)
    should_check_low_stock = any(
        key in fields for key in {"quantity", "low_stock_threshold", "supplier_id"}
    )
    with db.get_stock_connection() as conn:
        conn.execute(
            f"UPDATE {config.tables.items} SET {assignments} WHERE id = ?",
            values,
        )
        if config.auto_purchase_orders and should_check_low_stock:
            _maybe_create_auto_purchase_order(conn, item_id)
        conn.commit()
    return _get_inventory_item_internal(module, item_id)


def _delete_inventory_item_internal(module: str, item_id: int) -> None:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        conn.execute(
            f"DELETE FROM {config.tables.items} WHERE id = ?",
            (item_id,),
        )
        conn.commit()


def _list_inventory_categories_internal(module: str) -> list[models.Category]:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT id, name FROM {config.tables.categories} ORDER BY name COLLATE NOCASE"
        )
        rows = cur.fetchall()
        if not rows:
            return []
        category_ids = [row["id"] for row in rows]
        sizes_map: dict[int, list[str]] = {category_id: [] for category_id in category_ids}
        if category_ids:
            placeholders = ",".join("?" for _ in category_ids)
            size_rows = conn.execute(
                f"""
                SELECT category_id, name
                FROM {config.tables.category_sizes}
                WHERE category_id IN ({placeholders})
                ORDER BY name COLLATE NOCASE
                """,
                category_ids,
            ).fetchall()
            for size in size_rows:
                sizes_map.setdefault(size["category_id"], []).append(size["name"])
        return [
            models.Category(
                id=row["id"],
                name=row["name"],
                sizes=sizes_map.get(row["id"], []),
            )
            for row in rows
        ]


def _get_inventory_category_internal(
    module: str, category_id: int
) -> Optional[models.Category]:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT id, name FROM {config.tables.categories} WHERE id = ?",
            (category_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        size_rows = conn.execute(
            f"SELECT name FROM {config.tables.category_sizes} WHERE category_id = ? ORDER BY name COLLATE NOCASE",
            (category_id,),
        ).fetchall()
        return models.Category(
            id=row["id"],
            name=row["name"],
            sizes=[size_row["name"] for size_row in size_rows],
        )


def _create_inventory_category_internal(
    module: str, payload: models.CategoryCreate
) -> models.Category:
    ensure_database_ready()
    config = _get_inventory_config(module)
    normalized_sizes = _normalize_sizes(payload.sizes)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"INSERT INTO {config.tables.categories} (name) VALUES (?)",
            (payload.name,),
        )
        category_id = cur.lastrowid
        if normalized_sizes:
            conn.executemany(
                f"INSERT INTO {config.tables.category_sizes} (category_id, name) VALUES (?, ?)",
                ((category_id, size) for size in normalized_sizes),
            )
        conn.commit()
    return models.Category(id=category_id, name=payload.name, sizes=normalized_sizes)


def _update_inventory_category_internal(
    module: str, category_id: int, payload: models.CategoryUpdate
) -> models.Category:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT id FROM {config.tables.categories} WHERE id = ?",
            (category_id,),
        )
        if cur.fetchone() is None:
            raise ValueError("Catégorie introuvable")

        updates: list[str] = []
        values: list[object] = []
        if payload.name is not None:
            updates.append("name = ?")
            values.append(payload.name)
        if updates:
            values.append(category_id)
            conn.execute(
                f"UPDATE {config.tables.categories} SET {', '.join(updates)} WHERE id = ?",
                values,
            )

        if payload.sizes is not None:
            conn.execute(
                f"DELETE FROM {config.tables.category_sizes} WHERE category_id = ?",
                (category_id,),
            )
            normalized_sizes = _normalize_sizes(payload.sizes)
            if normalized_sizes:
                conn.executemany(
                    f"INSERT INTO {config.tables.category_sizes} (category_id, name) VALUES (?, ?)",
                    ((category_id, size) for size in normalized_sizes),
                )
        conn.commit()

    updated = _get_inventory_category_internal(module, category_id)
    if updated is None:  # pragma: no cover - deleted row in concurrent context
        raise ValueError("Catégorie introuvable")
    return updated


def _delete_inventory_category_internal(module: str, category_id: int) -> None:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        conn.execute(
            f"DELETE FROM {config.tables.category_sizes} WHERE category_id = ?",
            (category_id,),
        )
        conn.execute(
            f"DELETE FROM {config.tables.categories} WHERE id = ?",
            (category_id,),
        )
        conn.commit()


def _record_inventory_movement_internal(
    module: str, item_id: int, payload: models.MovementCreate
) -> None:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT quantity FROM {config.tables.items} WHERE id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        conn.execute(
            f"INSERT INTO {config.tables.movements} (item_id, delta, reason) VALUES (?, ?, ?)",
            (item_id, payload.delta, payload.reason),
        )
        conn.execute(
            f"UPDATE {config.tables.items} SET quantity = quantity + ? WHERE id = ?",
            (payload.delta, item_id),
        )
        if config.auto_purchase_orders:
            _maybe_create_auto_purchase_order(conn, item_id)
        conn.commit()


def _fetch_inventory_movements_internal(
    module: str, item_id: int
) -> list[models.Movement]:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT * FROM {config.tables.movements} WHERE item_id = ? ORDER BY created_at DESC",
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
            raise ValueError("Ce nom d'utilisateur existe déjà") from exc
        conn.commit()
        user_id = cur.lastrowid
    created = get_user_by_id(user_id)
    if created is None:  # pragma: no cover - inserted row should exist
        raise ValueError("Échec de la création de l'utilisateur")
    return created


def update_user(user_id: int, payload: models.UserUpdate) -> models.User:
    ensure_database_ready()
    current = get_user_by_id(user_id)
    if current is None:
        raise ValueError("Utilisateur introuvable")

    if current.username == "admin":
        if payload.role is not None and payload.role != "admin":
            raise ValueError("Impossible de modifier le rôle de l'administrateur par défaut")
        if payload.is_active is not None and not payload.is_active:
            raise ValueError("Impossible de désactiver l'administrateur par défaut")

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
        raise ValueError("Utilisateur introuvable")
    return updated


def delete_user(user_id: int) -> None:
    ensure_database_ready()
    current = get_user_by_id(user_id)
    if current is None:
        raise ValueError("Utilisateur introuvable")
    if current.username == "admin":
        raise ValueError("Impossible de supprimer l'utilisateur administrateur par défaut")
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
    return _list_inventory_items_internal("default", search)


def create_item(payload: models.ItemCreate) -> models.Item:
    return _create_inventory_item_internal("default", payload)


def get_item(item_id: int) -> models.Item:
    return _get_inventory_item_internal("default", item_id)


def update_item(item_id: int, payload: models.ItemUpdate) -> models.Item:
    return _update_inventory_item_internal("default", item_id, payload)


def delete_item(item_id: int) -> None:
    _delete_inventory_item_internal("default", item_id)


def list_vehicle_items(search: str | None = None) -> list[models.Item]:
    return _list_inventory_items_internal("vehicle_inventory", search)


def create_vehicle_item(payload: models.ItemCreate) -> models.Item:
    return _create_inventory_item_internal("vehicle_inventory", payload)


def get_vehicle_item(item_id: int) -> models.Item:
    return _get_inventory_item_internal("vehicle_inventory", item_id)


def update_vehicle_item(item_id: int, payload: models.ItemUpdate) -> models.Item:
    return _update_inventory_item_internal("vehicle_inventory", item_id, payload)


def delete_vehicle_item(item_id: int) -> None:
    _delete_inventory_item_internal("vehicle_inventory", item_id)


def list_remise_items(search: str | None = None) -> list[models.Item]:
    return _list_inventory_items_internal("inventory_remise", search)


def create_remise_item(payload: models.ItemCreate) -> models.Item:
    return _create_inventory_item_internal("inventory_remise", payload)


def get_remise_item(item_id: int) -> models.Item:
    return _get_inventory_item_internal("inventory_remise", item_id)


def update_remise_item(item_id: int, payload: models.ItemUpdate) -> models.Item:
    return _update_inventory_item_internal("inventory_remise", item_id, payload)


def delete_remise_item(item_id: int) -> None:
    _delete_inventory_item_internal("inventory_remise", item_id)


def _normalize_barcode(barcode: str | None) -> str | None:
    if barcode is None:
        return None
    normalized = barcode.strip()
    if not normalized:
        raise ValueError("Le code-barres ne peut pas être vide")
    return normalized.upper()


def _normalize_sizes(sizes: Iterable[str]) -> list[str]:
    unique: dict[str, str] = {}
    for raw in sizes:
        trimmed = raw.strip()
        if not trimmed:
            continue
        normalized = trimmed.upper()
        key = normalized.casefold()
        if key not in unique:
            unique[key] = normalized
    return sorted(unique.values(), key=str.lower)


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
    return _list_inventory_categories_internal("default")


def get_category(category_id: int) -> Optional[models.Category]:
    return _get_inventory_category_internal("default", category_id)


def create_category(payload: models.CategoryCreate) -> models.Category:
    return _create_inventory_category_internal("default", payload)


def delete_category(category_id: int) -> None:
    _delete_inventory_category_internal("default", category_id)


def update_category(category_id: int, payload: models.CategoryUpdate) -> models.Category:
    return _update_inventory_category_internal("default", category_id, payload)


def record_movement(item_id: int, payload: models.MovementCreate) -> None:
    _record_inventory_movement_internal("default", item_id, payload)


def fetch_movements(item_id: int) -> list[models.Movement]:
    return _fetch_inventory_movements_internal("default", item_id)


def list_vehicle_categories() -> list[models.Category]:
    return _list_inventory_categories_internal("vehicle_inventory")


def get_vehicle_category(category_id: int) -> Optional[models.Category]:
    return _get_inventory_category_internal("vehicle_inventory", category_id)


def create_vehicle_category(payload: models.CategoryCreate) -> models.Category:
    return _create_inventory_category_internal("vehicle_inventory", payload)


def update_vehicle_category(category_id: int, payload: models.CategoryUpdate) -> models.Category:
    return _update_inventory_category_internal("vehicle_inventory", category_id, payload)


def delete_vehicle_category(category_id: int) -> None:
    _delete_inventory_category_internal("vehicle_inventory", category_id)


def record_vehicle_movement(item_id: int, payload: models.MovementCreate) -> None:
    _record_inventory_movement_internal("vehicle_inventory", item_id, payload)


def fetch_vehicle_movements(item_id: int) -> list[models.Movement]:
    return _fetch_inventory_movements_internal("vehicle_inventory", item_id)


def list_remise_categories() -> list[models.Category]:
    return _list_inventory_categories_internal("inventory_remise")


def get_remise_category(category_id: int) -> Optional[models.Category]:
    return _get_inventory_category_internal("inventory_remise", category_id)


def create_remise_category(payload: models.CategoryCreate) -> models.Category:
    return _create_inventory_category_internal("inventory_remise", payload)


def update_remise_category(category_id: int, payload: models.CategoryUpdate) -> models.Category:
    return _update_inventory_category_internal("inventory_remise", category_id, payload)


def delete_remise_category(category_id: int) -> None:
    _delete_inventory_category_internal("inventory_remise", category_id)


def record_remise_movement(item_id: int, payload: models.MovementCreate) -> None:
    _record_inventory_movement_internal("inventory_remise", item_id, payload)


def fetch_remise_movements(item_id: int) -> list[models.Movement]:
    return _fetch_inventory_movements_internal("inventory_remise", item_id)


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


def list_suppliers(module: str | None = None) -> list[models.Supplier]:
    ensure_database_ready()
    module_filter = (module or "").strip().lower()
    with db.get_stock_connection() as conn:
        if module_filter:
            if module_filter == "suppliers":
                cur = conn.execute(
                    """
                    SELECT s.*
                    FROM suppliers AS s
                    WHERE EXISTS (
                        SELECT 1
                        FROM supplier_modules AS sm
                        WHERE sm.supplier_id = s.id AND sm.module = ?
                    )
                    OR NOT EXISTS (
                        SELECT 1 FROM supplier_modules AS sm WHERE sm.supplier_id = s.id
                    )
                    ORDER BY s.name COLLATE NOCASE
                    """,
                    (module_filter,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT s.*
                    FROM suppliers AS s
                    WHERE EXISTS (
                        SELECT 1
                        FROM supplier_modules AS sm
                        WHERE sm.supplier_id = s.id AND sm.module = ?
                    )
                    ORDER BY s.name COLLATE NOCASE
                    """,
                    (module_filter,),
                )
        else:
            cur = conn.execute("SELECT * FROM suppliers ORDER BY name COLLATE NOCASE")
        rows = cur.fetchall()
        modules_map = _load_supplier_modules(conn, [row["id"] for row in rows])
        suppliers: list[models.Supplier] = []
        for row in rows:
            modules = modules_map.get(row["id"]) or ["suppliers"]
            suppliers.append(
                models.Supplier(
                    id=row["id"],
                    name=row["name"],
                    contact_name=row["contact_name"],
                    phone=row["phone"],
                    email=row["email"],
                    address=row["address"],
                    modules=modules,
                )
            )
        return suppliers


def get_supplier(supplier_id: int) -> models.Supplier:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Fournisseur introuvable")
        modules_map = _load_supplier_modules(conn, [row["id"]])
        modules = modules_map.get(row["id"]) or ["suppliers"]
        return models.Supplier(
            id=row["id"],
            name=row["name"],
            contact_name=row["contact_name"],
            phone=row["phone"],
            email=row["email"],
            address=row["address"],
            modules=modules,
        )


def create_supplier(payload: models.SupplierCreate) -> models.Supplier:
    ensure_database_ready()
    modules = _normalize_supplier_modules(payload.modules)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO suppliers (name, contact_name, phone, email, address)
            VALUES (?, ?, ?, ?, ?)
            """,
            (payload.name, payload.contact_name, payload.phone, payload.email, payload.address),
        )
        supplier_id = cur.lastrowid
        _replace_supplier_modules(conn, supplier_id, modules)
        conn.commit()
        return get_supplier(supplier_id)


def update_supplier(supplier_id: int, payload: models.SupplierUpdate) -> models.Supplier:
    ensure_database_ready()
    updates = payload.dict(exclude_unset=True)
    modules_update = updates.pop("modules", None)
    fields = {k: v for k, v in updates.items()}
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,))
        if cur.fetchone() is None:
            raise ValueError("Fournisseur introuvable")
        if fields:
            assignments = ", ".join(f"{col} = ?" for col in fields)
            values = list(fields.values())
            values.append(supplier_id)
            conn.execute(f"UPDATE suppliers SET {assignments} WHERE id = ?", values)
        if modules_update is not None:
            modules = _normalize_supplier_modules(modules_update)
            _replace_supplier_modules(conn, supplier_id, modules)
        conn.commit()
    return get_supplier(supplier_id)


def delete_supplier(supplier_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        if cur.rowcount == 0:
            raise ValueError("Fournisseur introuvable")
        conn.commit()


def _build_purchase_order_detail(
    conn: sqlite3.Connection, order_row: sqlite3.Row
) -> models.PurchaseOrderDetail:
    items_cur = conn.execute(
        """
        SELECT poi.id,
               poi.purchase_order_id,
               poi.item_id,
               poi.quantity_ordered,
               poi.quantity_received,
               i.name AS item_name
        FROM purchase_order_items AS poi
        JOIN items AS i ON i.id = poi.item_id
        WHERE poi.purchase_order_id = ?
        ORDER BY i.name COLLATE NOCASE
        """,
        (order_row["id"],),
    )
    items = [
        models.PurchaseOrderItem(
            id=item_row["id"],
            purchase_order_id=item_row["purchase_order_id"],
            item_id=item_row["item_id"],
            quantity_ordered=item_row["quantity_ordered"],
            quantity_received=item_row["quantity_received"],
            item_name=item_row["item_name"],
        )
        for item_row in items_cur.fetchall()
    ]
    return models.PurchaseOrderDetail(
        id=order_row["id"],
        supplier_id=order_row["supplier_id"],
        supplier_name=order_row["supplier_name"],
        status=order_row["status"],
        created_at=order_row["created_at"],
        note=order_row["note"],
        auto_created=bool(order_row["auto_created"]),
        items=items,
    )


def list_purchase_orders() -> list[models.PurchaseOrderDetail]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name
            FROM purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            ORDER BY po.created_at DESC, po.id DESC
            """
        )
        rows = cur.fetchall()
        return [_build_purchase_order_detail(conn, row) for row in rows]


def get_purchase_order(order_id: int) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name
            FROM purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        return _build_purchase_order_detail(conn, row)


def create_purchase_order(payload: models.PurchaseOrderCreate) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    status = _normalize_purchase_order_status(payload.status)
    aggregated = _aggregate_positive_quantities(
        (line.item_id, line.quantity_ordered) for line in payload.items
    )
    if not aggregated:
        raise ValueError("Au moins un article est requis pour créer un bon de commande")
    with db.get_stock_connection() as conn:
        if payload.supplier_id is not None:
            supplier_cur = conn.execute(
                "SELECT 1 FROM suppliers WHERE id = ?", (payload.supplier_id,)
            )
            if supplier_cur.fetchone() is None:
                raise ValueError("Fournisseur introuvable")
        try:
            cur = conn.execute(
                """
                INSERT INTO purchase_orders (supplier_id, status, note, auto_created)
                VALUES (?, ?, ?, 0)
                """,
                (payload.supplier_id, status, payload.note),
            )
            order_id = cur.lastrowid
            for item_id, quantity in aggregated.items():
                item_cur = conn.execute(
                    "SELECT 1 FROM items WHERE id = ?", (item_id,)
                )
                if item_cur.fetchone() is None:
                    raise ValueError("Article introuvable")
                conn.execute(
                    """
                    INSERT INTO purchase_order_items (purchase_order_id, item_id, quantity_ordered, quantity_received)
                    VALUES (?, ?, ?, 0)
                    """,
                    (order_id, item_id, quantity),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_purchase_order(order_id)


def update_purchase_order(order_id: int, payload: models.PurchaseOrderUpdate) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    updates_raw = payload.dict(exclude_unset=True)
    if not updates_raw:
        return get_purchase_order(order_id)
    updates: dict[str, object] = {}
    if "supplier_id" in updates_raw:
        supplier_id = updates_raw["supplier_id"]
        if supplier_id is not None:
            with db.get_stock_connection() as conn:
                supplier_cur = conn.execute(
                    "SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)
                )
                if supplier_cur.fetchone() is None:
                    raise ValueError("Fournisseur introuvable")
        updates["supplier_id"] = supplier_id
    if "status" in updates_raw:
        updates["status"] = _normalize_purchase_order_status(updates_raw["status"])
    if "note" in updates_raw:
        updates["note"] = updates_raw["note"]
    if not updates:
        return get_purchase_order(order_id)
    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values())
    values.append(order_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT 1 FROM purchase_orders WHERE id = ?", (order_id,))
        if cur.fetchone() is None:
            raise ValueError("Bon de commande introuvable")
        conn.execute(f"UPDATE purchase_orders SET {assignments} WHERE id = ?", values)
        conn.commit()
    return get_purchase_order(order_id)


def _render_purchase_order_pdf(
    *,
    title: str,
    meta_lines: list[str],
    note_lines: list[str],
    items: list[tuple[str, int, int]],
) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 20 * mm

    def start_page(suffix: str = "") -> float:
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(margin, height - margin, f"{title}{suffix}")
        pdf.setFont("Helvetica", 10)
        y_position = height - margin - 18
        for meta in meta_lines:
            pdf.drawString(margin, y_position, meta)
            y_position -= 12
        return y_position - 6

    def draw_table_header(y_position: float) -> float:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(margin, y_position, "Article")
        pdf.drawRightString(width - margin - 60, y_position, "Commandé")
        pdf.drawRightString(width - margin, y_position, "Réceptionné")
        pdf.setFont("Helvetica", 10)
        return y_position - 12

    def draw_table_title(y_position: float, *, suffix: str = "") -> float:
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(margin, y_position, f"Lignes de commande{suffix}")
        y_position -= 16
        return draw_table_header(y_position)

    def ensure_space(
        y_position: float,
        needed: float,
        *,
        on_new_page: Optional[Callable[[float], float]] = None,
        suffix: str = " (suite)",
    ) -> float:
        if y_position <= margin + needed:
            pdf.showPage()
            y_new = start_page(suffix)
            if on_new_page is not None:
                y_new = on_new_page(y_new)
            return y_new
        return y_position

    y = start_page()

    def draw_note_heading(y_position: float) -> float:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(margin, y_position, "Note")
        y_position -= 12
        pdf.setFont("Helvetica", 10)
        return y_position

    if note_lines:
        y = ensure_space(y, 24)
        y = draw_note_heading(y)
        for line in note_lines:
            y = ensure_space(y, 18, on_new_page=draw_note_heading)
            pdf.drawString(margin, y, line)
            y -= 12
        y -= 6

    table_new_page = lambda pos: draw_table_title(pos, suffix=" (suite)")

    y = ensure_space(y, 60)
    y = draw_table_title(y)
    if not items:
        y = ensure_space(y, 24, on_new_page=table_new_page)
        pdf.drawString(margin, y, "Aucune ligne de commande enregistrée.")
        y -= 12
    else:
        for name, ordered, received in items:
            name_lines = wrap(name, 80) or ["-"]
            for index, line in enumerate(name_lines):
                y = ensure_space(y, 24, on_new_page=table_new_page)
                pdf.drawString(margin, y, line)
                if index == 0:
                    pdf.drawRightString(width - margin - 60, y, str(ordered))
                    pdf.drawRightString(width - margin, y, str(received))
                y -= 12
            y -= 4

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


def generate_purchase_order_pdf(order: models.PurchaseOrderDetail) -> bytes:
    status_label = _PURCHASE_ORDER_STATUS_LABELS.get(order.status, order.status)
    created_at = order.created_at.strftime("%d/%m/%Y %H:%M")
    supplier = order.supplier_name or "Aucun"
    meta_lines = [
        f"Bon de commande n° {order.id}",
        f"Créé le : {created_at}",
        f"Fournisseur : {supplier}",
        f"Statut : {status_label}",
    ]
    if order.auto_created:
        meta_lines.append("Création automatique : Oui")
    note_lines = wrap(order.note or "", 90) if order.note else []
    item_rows = [
        (
            line.item_name or f"Article #{line.item_id}",
            line.quantity_ordered,
            line.quantity_received,
        )
        for line in order.items
    ]
    return _render_purchase_order_pdf(
        title="Bon de commande inventaire",
        meta_lines=meta_lines,
        note_lines=note_lines,
        items=item_rows,
    )


def generate_pharmacy_purchase_order_pdf(
    order: models.PharmacyPurchaseOrderDetail,
) -> bytes:
    status_label = _PURCHASE_ORDER_STATUS_LABELS.get(order.status, order.status)
    created_at = order.created_at.strftime("%d/%m/%Y %H:%M")
    supplier = order.supplier_name or "Aucun"
    meta_lines = [
        f"Bon de commande pharmacie n° {order.id}",
        f"Créé le : {created_at}",
        f"Fournisseur : {supplier}",
        f"Statut : {status_label}",
    ]
    note_lines = wrap(order.note or "", 90) if order.note else []
    item_rows = [
        (
            line.pharmacy_item_name or f"Article #{line.pharmacy_item_id}",
            line.quantity_ordered,
            line.quantity_received,
        )
        for line in order.items
    ]
    return _render_purchase_order_pdf(
        title="Bon de commande pharmacie",
        meta_lines=meta_lines,
        note_lines=note_lines,
        items=item_rows,
    )


def receive_purchase_order(
    order_id: int, payload: models.PurchaseOrderReceivePayload
) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    increments = _aggregate_positive_quantities(
        (line.item_id, line.quantity) for line in payload.items
    )
    if not increments:
        raise ValueError("Aucune ligne de réception valide")
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT status FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        try:
            for item_id, increment in increments.items():
                line = conn.execute(
                    """
                    SELECT id, quantity_ordered, quantity_received
                    FROM purchase_order_items
                    WHERE purchase_order_id = ? AND item_id = ?
                    """,
                    (order_id, item_id),
                ).fetchone()
                if line is None:
                    raise ValueError("Article absent du bon de commande")
                remaining = line["quantity_ordered"] - line["quantity_received"]
                if remaining <= 0:
                    continue
                new_received = line["quantity_received"] + increment
                if new_received > line["quantity_ordered"]:
                    new_received = line["quantity_ordered"]
                delta = new_received - line["quantity_received"]
                if delta <= 0:
                    continue
                conn.execute(
                    "UPDATE purchase_order_items SET quantity_received = ? WHERE id = ?",
                    (new_received, line["id"]),
                )
                conn.execute(
                    "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                    (delta, item_id),
                )
                conn.execute(
                    "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                    (item_id, delta, f"Réception bon de commande #{order_id}"),
                )
                _maybe_create_auto_purchase_order(conn, item_id)
            totals = conn.execute(
                """
                SELECT quantity_ordered, quantity_received
                FROM purchase_order_items
                WHERE purchase_order_id = ?
                """,
                (order_id,),
            ).fetchall()
            if all(row["quantity_received"] >= row["quantity_ordered"] for row in totals):
                new_status = "RECEIVED"
            elif any(row["quantity_received"] > 0 for row in totals):
                new_status = "PARTIALLY_RECEIVED"
            else:
                new_status = order_row["status"]
            if new_status != order_row["status"]:
                conn.execute(
                    "UPDATE purchase_orders SET status = ? WHERE id = ?",
                    (new_status, order_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_purchase_order(order_id)


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
            raise ValueError("Collaborateur introuvable")
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
            raise ValueError("Collaborateur introuvable")
        conn.execute(f"UPDATE collaborators SET {assignments} WHERE id = ?", values)
        conn.commit()
    return get_collaborator(collaborator_id)


def delete_collaborator(collaborator_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("DELETE FROM collaborators WHERE id = ?", (collaborator_id,))
        if cur.rowcount == 0:
            raise ValueError("Collaborateur introuvable")
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
        rows = cur.fetchall()
        dotations: list[models.Dotation] = []
        for row in rows:
            allocated_at_value = row["allocated_at"]
            allocated_date = _ensure_date(allocated_at_value)
            perceived_at = _ensure_date(row["perceived_at"], fallback=allocated_date)
            dotations.append(
                models.Dotation(
                    id=row["id"],
                    collaborator_id=row["collaborator_id"],
                    item_id=row["item_id"],
                    quantity=row["quantity"],
                    notes=row["notes"],
                    perceived_at=perceived_at,
                    is_lost=bool(row["is_lost"]),
                    is_degraded=bool(row["is_degraded"]),
                    allocated_at=allocated_at_value,
                    is_obsolete=_is_obsolete(perceived_at),
                )
            )
        return dotations


def get_dotation(dotation_id: int) -> models.Dotation:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM dotations WHERE id = ?", (dotation_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Dotation introuvable")
        allocated_at_value = row["allocated_at"]
        allocated_date = _ensure_date(allocated_at_value)
        perceived_at = _ensure_date(row["perceived_at"], fallback=allocated_date)
        return models.Dotation(
            id=row["id"],
            collaborator_id=row["collaborator_id"],
            item_id=row["item_id"],
            quantity=row["quantity"],
            notes=row["notes"],
            perceived_at=perceived_at,
            is_lost=bool(row["is_lost"]),
            is_degraded=bool(row["is_degraded"]),
            allocated_at=allocated_at_value,
            is_obsolete=_is_obsolete(perceived_at),
        )


def create_dotation(payload: models.DotationCreate) -> models.Dotation:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT quantity FROM items WHERE id = ?", (payload.item_id,))
        item_row = cur.fetchone()
        if item_row is None:
            raise ValueError("Article introuvable")
        if item_row["quantity"] < payload.quantity:
            raise ValueError("Stock insuffisant pour la dotation")

        collaborator_cur = conn.execute(
            "SELECT full_name FROM collaborators WHERE id = ?",
            (payload.collaborator_id,),
        )
        collaborator_row = collaborator_cur.fetchone()
        if collaborator_row is None:
            raise ValueError("Collaborateur introuvable")
        collaborator_name = collaborator_row["full_name"]

        cur = conn.execute(
            """
            INSERT INTO dotations (
                collaborator_id,
                item_id,
                quantity,
                notes,
                perceived_at,
                is_lost,
                is_degraded
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.collaborator_id,
                payload.item_id,
                payload.quantity,
                payload.notes,
                payload.perceived_at.isoformat(),
                int(payload.is_lost),
                int(payload.is_degraded),
            ),
        )
        conn.execute(
            "UPDATE items SET quantity = quantity - ? WHERE id = ?",
            (payload.quantity, payload.item_id),
        )
        conn.execute(
            "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
            (
                payload.item_id,
                -payload.quantity,
                f"Dotation - {collaborator_name}",
            ),
        )
        conn.commit()
        return get_dotation(cur.lastrowid)


def update_dotation(dotation_id: int, payload: models.DotationUpdate) -> models.Dotation:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM dotations WHERE id = ?", (dotation_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Dotation introuvable")

        base_perceived_at = _ensure_date(row["perceived_at"], fallback=_ensure_date(row["allocated_at"]))
        new_collaborator_id = (
            payload.collaborator_id if payload.collaborator_id is not None else row["collaborator_id"]
        )
        new_item_id = payload.item_id if payload.item_id is not None else row["item_id"]
        new_quantity = payload.quantity if payload.quantity is not None else row["quantity"]
        if new_quantity <= 0:
            raise ValueError("La quantité doit être positive")
        new_notes = payload.notes if payload.notes is not None else row["notes"]
        new_perceived_at = payload.perceived_at if payload.perceived_at is not None else base_perceived_at
        new_is_lost = payload.is_lost if payload.is_lost is not None else bool(row["is_lost"])
        new_is_degraded = (
            payload.is_degraded if payload.is_degraded is not None else bool(row["is_degraded"])
        )

        collaborator_cur = conn.execute(
            "SELECT full_name FROM collaborators WHERE id = ?",
            (new_collaborator_id,),
        )
        collaborator_row = collaborator_cur.fetchone()
        if collaborator_row is None:
            raise ValueError("Collaborateur introuvable")
        collaborator_name = collaborator_row["full_name"]

        original_item_cur = conn.execute(
            "SELECT quantity FROM items WHERE id = ?",
            (row["item_id"],),
        )
        original_item_row = original_item_cur.fetchone()
        if original_item_row is None:
            raise ValueError("Article introuvable")

        target_item_cur = conn.execute(
            "SELECT quantity FROM items WHERE id = ?",
            (new_item_id,),
        )
        target_item_row = target_item_cur.fetchone()
        if target_item_row is None:
            raise ValueError("Article introuvable")

        reason = f"Ajustement dotation - {collaborator_name}"

        if new_item_id == row["item_id"]:
            delta_quantity = new_quantity - row["quantity"]
            if delta_quantity > 0:
                if target_item_row["quantity"] < delta_quantity:
                    raise ValueError("Stock insuffisant pour la dotation")
                conn.execute(
                    "UPDATE items SET quantity = quantity - ? WHERE id = ?",
                    (delta_quantity, new_item_id),
                )
                conn.execute(
                    "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                    (new_item_id, -delta_quantity, reason),
                )
            elif delta_quantity < 0:
                conn.execute(
                    "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                    (-delta_quantity, new_item_id),
                )
                conn.execute(
                    "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                    (new_item_id, -delta_quantity, reason),
                )
        else:
            if target_item_row["quantity"] < new_quantity:
                raise ValueError("Stock insuffisant pour la dotation")
            conn.execute(
                "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                (row["quantity"], row["item_id"]),
            )
            conn.execute(
                "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                (row["item_id"], row["quantity"], reason),
            )
            conn.execute(
                "UPDATE items SET quantity = quantity - ? WHERE id = ?",
                (new_quantity, new_item_id),
            )
            conn.execute(
                "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                (new_item_id, -new_quantity, reason),
            )

        conn.execute(
            """
            UPDATE dotations
            SET collaborator_id = ?,
                item_id = ?,
                quantity = ?,
                notes = ?,
                perceived_at = ?,
                is_lost = ?,
                is_degraded = ?
            WHERE id = ?
            """,
            (
                new_collaborator_id,
                new_item_id,
                new_quantity,
                new_notes,
                new_perceived_at.isoformat(),
                int(new_is_lost),
                int(new_is_degraded),
                dotation_id,
            ),
        )
        conn.commit()
    return get_dotation(dotation_id)


def delete_dotation(dotation_id: int, *, restock: bool = False) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT collaborator_id, item_id, quantity FROM dotations WHERE id = ?",
            (dotation_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Dotation introuvable")
        collaborator_name: str | None = None
        if row["collaborator_id"] is not None:
            name_cur = conn.execute(
                "SELECT full_name FROM collaborators WHERE id = ?",
                (row["collaborator_id"],),
            )
            collaborator_row = name_cur.fetchone()
            if collaborator_row is not None:
                collaborator_name = collaborator_row["full_name"]
        conn.execute("DELETE FROM dotations WHERE id = ?", (dotation_id,))
        if restock:
            conn.execute(
                "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                (row["quantity"], row["item_id"]),
            )
            reason = (
                f"Retour dotation - {collaborator_name}"
                if collaborator_name
                else "Retour dotation"
            )
            conn.execute(
                "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                (row["item_id"], row["quantity"], reason),
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
                packaging=row["packaging"],
                barcode=row["barcode"],
                quantity=row["quantity"],
                low_stock_threshold=row["low_stock_threshold"],
                expiration_date=row["expiration_date"],
                location=row["location"],
                category_id=row["category_id"],
            )
            for row in cur.fetchall()
        ]


def get_pharmacy_item(item_id: int) -> models.PharmacyItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM pharmacy_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Produit pharmaceutique introuvable")
        return models.PharmacyItem(
            id=row["id"],
            name=row["name"],
            dosage=row["dosage"],
            packaging=row["packaging"],
            barcode=row["barcode"],
            quantity=row["quantity"],
            low_stock_threshold=row["low_stock_threshold"],
            expiration_date=row["expiration_date"],
            location=row["location"],
            category_id=row["category_id"],
        )


def create_pharmacy_item(payload: models.PharmacyItemCreate) -> models.PharmacyItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        barcode = _normalize_barcode(payload.barcode)
        try:
            cur = conn.execute(
                """
                INSERT INTO pharmacy_items (
                    name,
                    dosage,
                    packaging,
                    barcode,
                    quantity,
                    low_stock_threshold,
                    expiration_date,
                    location,
                    category_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.name,
                    payload.dosage,
                    payload.packaging,
                    barcode,
                    payload.quantity,
                    payload.low_stock_threshold,
                    payload.expiration_date,
                    payload.location,
                    payload.category_id,
                ),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Ce code-barres est déjà utilisé") from exc
        conn.commit()
        return get_pharmacy_item(cur.lastrowid)


def update_pharmacy_item(item_id: int, payload: models.PharmacyItemUpdate) -> models.PharmacyItem:
    ensure_database_ready()
    fields = {k: v for k, v in payload.dict(exclude_unset=True).items()}
    if "barcode" in fields:
        fields["barcode"] = _normalize_barcode(fields["barcode"])
    if not fields:
        return get_pharmacy_item(item_id)
    assignments = ", ".join(f"{col} = ?" for col in fields)
    values = list(fields.values())
    values.append(item_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT 1 FROM pharmacy_items WHERE id = ?", (item_id,))
        if cur.fetchone() is None:
            raise ValueError("Produit pharmaceutique introuvable")
        try:
            conn.execute(f"UPDATE pharmacy_items SET {assignments} WHERE id = ?", values)
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Ce code-barres est déjà utilisé") from exc
        conn.commit()
    return get_pharmacy_item(item_id)


def delete_pharmacy_item(item_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("DELETE FROM pharmacy_items WHERE id = ?", (item_id,))
        if cur.rowcount == 0:
            raise ValueError("Produit pharmaceutique introuvable")
        conn.commit()


def list_pharmacy_categories() -> list[models.PharmacyCategory]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id, name FROM pharmacy_categories ORDER BY name COLLATE NOCASE")
        rows = cur.fetchall()
        if not rows:
            return []

        category_ids = [row["id"] for row in rows]
        sizes_map: dict[int, list[str]] = {category_id: [] for category_id in category_ids}
        placeholders = ",".join("?" for _ in category_ids)
        size_rows = conn.execute(
            f"""
            SELECT category_id, name
            FROM pharmacy_category_sizes
            WHERE category_id IN ({placeholders})
            ORDER BY name COLLATE NOCASE
            """,
            category_ids,
        ).fetchall()
        for size_row in size_rows:
            sizes_map.setdefault(size_row["category_id"], []).append(size_row["name"])

        return [
            models.PharmacyCategory(
                id=row["id"],
                name=row["name"],
                sizes=sizes_map.get(row["id"], []),
            )
            for row in rows
        ]


def get_pharmacy_category(category_id: int) -> models.PharmacyCategory:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id, name FROM pharmacy_categories WHERE id = ?", (category_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Catégorie pharmaceutique introuvable")
        size_rows = conn.execute(
            """
            SELECT name
            FROM pharmacy_category_sizes
            WHERE category_id = ?
            ORDER BY name COLLATE NOCASE
            """,
            (category_id,),
        ).fetchall()
        return models.PharmacyCategory(
            id=row["id"],
            name=row["name"],
            sizes=[size_row["name"] for size_row in size_rows],
        )


def create_pharmacy_category(payload: models.PharmacyCategoryCreate) -> models.PharmacyCategory:
    ensure_database_ready()
    normalized_sizes = _normalize_sizes(payload.sizes)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "INSERT INTO pharmacy_categories (name) VALUES (?)",
            (payload.name,),
        )
        category_id = cur.lastrowid
        if normalized_sizes:
            conn.executemany(
                "INSERT INTO pharmacy_category_sizes (category_id, name) VALUES (?, ?)",
                ((category_id, size) for size in normalized_sizes),
            )
        conn.commit()
        return models.PharmacyCategory(id=category_id, name=payload.name, sizes=normalized_sizes)


def update_pharmacy_category(
    category_id: int, payload: models.PharmacyCategoryUpdate
) -> models.PharmacyCategory:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id FROM pharmacy_categories WHERE id = ?", (category_id,))
        if cur.fetchone() is None:
            raise ValueError("Catégorie pharmaceutique introuvable")

        updates: list[str] = []
        values: list[object] = []
        if payload.name is not None:
            updates.append("name = ?")
            values.append(payload.name)
        if updates:
            values.append(category_id)
            conn.execute(
                f"UPDATE pharmacy_categories SET {', '.join(updates)} WHERE id = ?",
                values,
            )

        if payload.sizes is not None:
            conn.execute("DELETE FROM pharmacy_category_sizes WHERE category_id = ?", (category_id,))
            normalized_sizes = _normalize_sizes(payload.sizes)
            if normalized_sizes:
                conn.executemany(
                    "INSERT INTO pharmacy_category_sizes (category_id, name) VALUES (?, ?)",
                    ((category_id, size) for size in normalized_sizes),
                )
        conn.commit()

    return get_pharmacy_category(category_id)


def delete_pharmacy_category(category_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pharmacy_category_sizes WHERE category_id = ?", (category_id,))
        conn.execute("DELETE FROM pharmacy_categories WHERE id = ?", (category_id,))
        conn.commit()


def record_pharmacy_movement(item_id: int, payload: models.PharmacyMovementCreate) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT quantity FROM pharmacy_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Produit pharmaceutique introuvable")

        conn.execute(
            "INSERT INTO pharmacy_movements (pharmacy_item_id, delta, reason) VALUES (?, ?, ?)",
            (item_id, payload.delta, payload.reason),
        )
        conn.execute(
            "UPDATE pharmacy_items SET quantity = quantity + ? WHERE id = ?",
            (payload.delta, item_id),
        )
        conn.commit()


def fetch_pharmacy_movements(item_id: int) -> list[models.PharmacyMovement]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM pharmacy_movements
            WHERE pharmacy_item_id = ?
            ORDER BY created_at DESC
            """,
            (item_id,),
        )
        return [
            models.PharmacyMovement(
                id=row["id"],
                pharmacy_item_id=row["pharmacy_item_id"],
                delta=row["delta"],
                reason=row["reason"],
                created_at=row["created_at"],
            )
            for row in cur.fetchall()
        ]


def _build_pharmacy_purchase_order_detail(
    conn: sqlite3.Connection, order_row: sqlite3.Row
) -> models.PharmacyPurchaseOrderDetail:
    items_cur = conn.execute(
        """
        SELECT poi.id,
               poi.purchase_order_id,
               poi.pharmacy_item_id,
               poi.quantity_ordered,
               poi.quantity_received,
               pi.name AS pharmacy_item_name
        FROM pharmacy_purchase_order_items AS poi
        JOIN pharmacy_items AS pi ON pi.id = poi.pharmacy_item_id
        WHERE poi.purchase_order_id = ?
        ORDER BY pi.name COLLATE NOCASE
        """,
        (order_row["id"],),
    )
    items = [
        models.PharmacyPurchaseOrderItem(
            id=item_row["id"],
            purchase_order_id=item_row["purchase_order_id"],
            pharmacy_item_id=item_row["pharmacy_item_id"],
            quantity_ordered=item_row["quantity_ordered"],
            quantity_received=item_row["quantity_received"],
            pharmacy_item_name=item_row["pharmacy_item_name"],
        )
        for item_row in items_cur.fetchall()
    ]
    return models.PharmacyPurchaseOrderDetail(
        id=order_row["id"],
        supplier_id=order_row["supplier_id"],
        supplier_name=order_row["supplier_name"],
        status=order_row["status"],
        created_at=order_row["created_at"],
        note=order_row["note"],
        items=items,
    )


def list_pharmacy_purchase_orders() -> list[models.PharmacyPurchaseOrderDetail]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name
            FROM pharmacy_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            ORDER BY po.created_at DESC, po.id DESC
            """
        )
        rows = cur.fetchall()
        return [_build_pharmacy_purchase_order_detail(conn, row) for row in rows]


def get_pharmacy_purchase_order(order_id: int) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name
            FROM pharmacy_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        return _build_pharmacy_purchase_order_detail(conn, row)


def create_pharmacy_purchase_order(
    payload: models.PharmacyPurchaseOrderCreate,
) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    status = _normalize_purchase_order_status(payload.status)
    aggregated = _aggregate_positive_quantities(
        (line.pharmacy_item_id, line.quantity_ordered) for line in payload.items
    )
    if not aggregated:
        raise ValueError("Au moins un article pharmaceutique est requis")
    with db.get_stock_connection() as conn:
        if payload.supplier_id is not None:
            supplier_cur = conn.execute(
                "SELECT 1 FROM suppliers WHERE id = ?", (payload.supplier_id,)
            )
            if supplier_cur.fetchone() is None:
                raise ValueError("Fournisseur introuvable")
        try:
            cur = conn.execute(
                """
                INSERT INTO pharmacy_purchase_orders (supplier_id, status, note)
                VALUES (?, ?, ?)
                """,
                (payload.supplier_id, status, payload.note),
            )
            order_id = cur.lastrowid
            for item_id, quantity in aggregated.items():
                item_cur = conn.execute(
                    "SELECT 1 FROM pharmacy_items WHERE id = ?", (item_id,)
                )
                if item_cur.fetchone() is None:
                    raise ValueError("Article pharmaceutique introuvable")
                conn.execute(
                    """
                    INSERT INTO pharmacy_purchase_order_items (
                        purchase_order_id,
                        pharmacy_item_id,
                        quantity_ordered,
                        quantity_received
                    )
                    VALUES (?, ?, ?, 0)
                    """,
                    (order_id, item_id, quantity),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_pharmacy_purchase_order(order_id)


def update_pharmacy_purchase_order(
    order_id: int, payload: models.PharmacyPurchaseOrderUpdate
) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    updates_raw = payload.dict(exclude_unset=True)
    if not updates_raw:
        return get_pharmacy_purchase_order(order_id)
    updates: dict[str, object] = {}
    if "supplier_id" in updates_raw:
        supplier_id = updates_raw["supplier_id"]
        if supplier_id is not None:
            with db.get_stock_connection() as conn:
                supplier_cur = conn.execute(
                    "SELECT 1 FROM suppliers WHERE id = ?", (supplier_id,)
                )
                if supplier_cur.fetchone() is None:
                    raise ValueError("Fournisseur introuvable")
        updates["supplier_id"] = supplier_id
    if "status" in updates_raw:
        updates["status"] = _normalize_purchase_order_status(updates_raw["status"])
    if "note" in updates_raw:
        updates["note"] = updates_raw["note"]
    if not updates:
        return get_pharmacy_purchase_order(order_id)
    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values())
    values.append(order_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT 1 FROM pharmacy_purchase_orders WHERE id = ?", (order_id,)
        )
        if cur.fetchone() is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        conn.execute(
            f"UPDATE pharmacy_purchase_orders SET {assignments} WHERE id = ?",
            values,
        )
        conn.commit()
    return get_pharmacy_purchase_order(order_id)


def receive_pharmacy_purchase_order(
    order_id: int, payload: models.PharmacyPurchaseOrderReceivePayload
) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    increments = _aggregate_positive_quantities(
        (line.pharmacy_item_id, line.quantity) for line in payload.items
    )
    if not increments:
        raise ValueError("Aucune ligne de réception valide")
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT status FROM pharmacy_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        try:
            for item_id, increment in increments.items():
                line = conn.execute(
                    """
                    SELECT id, quantity_ordered, quantity_received
                    FROM pharmacy_purchase_order_items
                    WHERE purchase_order_id = ? AND pharmacy_item_id = ?
                    """,
                    (order_id, item_id),
                ).fetchone()
                if line is None:
                    raise ValueError("Article pharmaceutique absent du bon de commande")
                remaining = line["quantity_ordered"] - line["quantity_received"]
                if remaining <= 0:
                    continue
                new_received = line["quantity_received"] + increment
                if new_received > line["quantity_ordered"]:
                    new_received = line["quantity_ordered"]
                delta = new_received - line["quantity_received"]
                if delta <= 0:
                    continue
                conn.execute(
                    "UPDATE pharmacy_purchase_order_items SET quantity_received = ? WHERE id = ?",
                    (new_received, line["id"]),
                )
                conn.execute(
                    "UPDATE pharmacy_items SET quantity = quantity + ? WHERE id = ?",
                    (delta, item_id),
                )
                conn.execute(
                    "INSERT INTO pharmacy_movements (pharmacy_item_id, delta, reason) VALUES (?, ?, ?)",
                    (item_id, delta, f"Réception bon de commande pharmacie #{order_id}"),
                )
            totals = conn.execute(
                """
                SELECT quantity_ordered, quantity_received
                FROM pharmacy_purchase_order_items
                WHERE purchase_order_id = ?
                """,
                (order_id,),
            ).fetchall()
            if all(row["quantity_received"] >= row["quantity_ordered"] for row in totals):
                new_status = "RECEIVED"
            elif any(row["quantity_received"] > 0 for row in totals):
                new_status = "PARTIALLY_RECEIVED"
            else:
                new_status = order_row["status"]
            if new_status != order_row["status"]:
                conn.execute(
                    "UPDATE pharmacy_purchase_orders SET status = ? WHERE id = ?",
                    (new_status, order_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_pharmacy_purchase_order(order_id)


def list_available_modules() -> list[models.ModuleDefinition]:
    ensure_database_ready()
    definitions = [
        models.ModuleDefinition(key=key, label=label)
        for key, label in _AVAILABLE_MODULE_DEFINITIONS
    ]
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT DISTINCT module FROM module_permissions ORDER BY module COLLATE NOCASE"
        )
        for row in cur.fetchall():
            module_key = row["module"]
            if module_key in _AVAILABLE_MODULE_KEYS:
                continue
            definitions.append(
                models.ModuleDefinition(
                    key=module_key,
                    label=module_key.replace("_", " ").title(),
                )
            )
    return definitions


def list_module_permissions() -> list[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions ORDER BY user_id, module COLLATE NOCASE"
        )
        return [
            models.ModulePermission(
                id=row["id"],
                user_id=row["user_id"],
                module=row["module"],
                can_view=bool(row["can_view"]),
                can_edit=bool(row["can_edit"]),
            )
            for row in cur.fetchall()
        ]


def list_module_permissions_for_user(user_id: int) -> list[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions WHERE user_id = ? ORDER BY module COLLATE NOCASE",
            (user_id,),
        )
        return [
            models.ModulePermission(
                id=row["id"],
                user_id=row["user_id"],
                module=row["module"],
                can_view=bool(row["can_view"]),
                can_edit=bool(row["can_edit"]),
            )
            for row in cur.fetchall()
        ]


def get_module_permission_for_user(
    user_id: int, module: str
) -> Optional[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions WHERE user_id = ? AND module = ?",
            (user_id, module),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return models.ModulePermission(
            id=row["id"],
            user_id=row["user_id"],
            module=row["module"],
            can_view=bool(row["can_view"]),
            can_edit=bool(row["can_edit"]),
        )


def upsert_module_permission(payload: models.ModulePermissionUpsert) -> models.ModulePermission:
    ensure_database_ready()
    if get_user_by_id(payload.user_id) is None:
        raise ValueError("Utilisateur introuvable")
    with db.get_users_connection() as conn:
        if payload.module not in _AVAILABLE_MODULE_KEYS:
            cur = conn.execute(
                "SELECT 1 FROM module_permissions WHERE module = ? LIMIT 1",
                (payload.module,),
            )
            if cur.fetchone() is None:
                raise ValueError("Module introuvable")
        conn.execute(
            """
            INSERT INTO module_permissions (user_id, module, can_view, can_edit)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, module) DO UPDATE SET
                can_view = excluded.can_view,
                can_edit = excluded.can_edit
            """,
            (
                payload.user_id,
                payload.module,
                int(payload.can_view),
                int(payload.can_edit),
            ),
        )
        conn.commit()
    permission = get_module_permission_for_user(payload.user_id, payload.module)
    if permission is None:
        raise RuntimeError("Échec de l'enregistrement de la permission du module")
    return permission


def delete_module_permission_for_user(user_id: int, module: str) -> None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "DELETE FROM module_permissions WHERE user_id = ? AND module = ?",
            (user_id, module),
        )
        if cur.rowcount == 0:
            raise ValueError("Permission de module introuvable")
        conn.commit()


def has_module_access(user: models.User, module: str, *, action: str = "view") -> bool:
    ensure_database_ready()
    if user.role == "admin":
        return True
    permission = get_module_permission_for_user(user.id, module)
    if permission is None:
        return False
    if action == "edit":
        return permission.can_edit
    return permission.can_view
