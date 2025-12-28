"""Services métier pour Gestion Stock Pro."""
from __future__ import annotations

import html
import io
import json
import logging
import math
import os
import random
import shutil
import threading
import time
from collections import defaultdict
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from textwrap import wrap
from typing import Any, BinaryIO, Callable, Iterable, Iterator, Optional
from uuid import uuid4

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from backend.core import db, models, security
from backend.core.storage import (
    MEDIA_ROOT,
    PHARMACY_LOT_MEDIA_DIR,
    REMISE_LOT_MEDIA_DIR,
    VEHICLE_CATEGORY_MEDIA_DIR,
    VEHICLE_ITEM_MEDIA_DIR,
    VEHICLE_PHOTO_MEDIA_DIR,
    relative_to_media,
)
from backend.services import barcode as barcode_service
from backend.services.pdf import VehiclePdfOptions, render_vehicle_inventory_pdf

# Initialisation des bases de données au chargement du module
_db_initialized = False

logger = logging.getLogger(__name__)

_AUTO_PO_CLOSED_STATUSES = ("CANCELLED", "RECEIVED")

_AVAILABLE_MODULE_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("barcode", "Code-barres"),
    ("clothing", "Habillement"),
    ("suppliers", "Fournisseurs"),
    ("dotations", "Dotations"),
    ("pharmacy", "Pharmacie"),
    ("vehicle_qrcodes", "QR véhicules"),
    ("vehicle_inventory", "Inventaire véhicules"),
    ("inventory_remise", "Inventaire remises"),
)
_AVAILABLE_MODULE_KEYS: set[str] = {key for key, _ in _AVAILABLE_MODULE_DEFINITIONS}

_MODULE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "suppliers": ("clothing",),
    "dotations": ("clothing",),
    "vehicle_qrcodes": ("vehicle_inventory",),
}


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
    "pharmacy": _InventoryModuleConfig(
        tables=_InventoryTables(
            items="pharmacy_items",
            categories="pharmacy_categories",
            category_sizes="pharmacy_category_sizes",
            movements="pharmacy_movements",
        )
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

_BARCODE_MODULE_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("clothing", "items", "sku"),
    ("pharmacy", "pharmacy_items", "barcode"),
    ("inventory_remise", "remise_items", "sku"),
    ("vehicle_inventory", "vehicle_items", "sku"),
)

DEFAULT_VEHICLE_VIEW_NAME = "VUE PRINCIPALE"

_MEDIA_URL_PREFIX = "/media"
_ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _build_media_url(path: str | None) -> str | None:
    if not path:
        return None
    return f"{_MEDIA_URL_PREFIX}/{path}"


def _sanitize_image_suffix(filename: str | None) -> str:
    if not filename:
        return ".png"
    suffix = Path(filename).suffix.lower()
    if suffix in _ALLOWED_IMAGE_SUFFIXES:
        return suffix
    return ".png"


def _resolve_media_path(relative_path: str | None) -> Path | None:
    """Return an absolute media path if it stays within ``MEDIA_ROOT``.

    User-provided paths (stored in the database or coming from HTTP payloads)
    must never allow traversing outside the media directory. Using ``resolve``
    followed by ``relative_to`` ensures that sequences such as ``../`` are
    rejected instead of silently deleting or copying arbitrary files on disk.
    """

    if not relative_path:
        return None
    try:
        candidate = (MEDIA_ROOT / Path(relative_path)).resolve()
    except (OSError, TypeError):
        return None
    try:
        candidate.relative_to(MEDIA_ROOT)
    except ValueError:
        return None
    return candidate


def _store_media_file(directory: Path, stream: BinaryIO, filename: str | None) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = _sanitize_image_suffix(filename)
    target = directory / f"{uuid4().hex}{suffix}"
    stream.seek(0)
    with open(target, "wb") as buffer:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            buffer.write(chunk)
    return relative_to_media(target)


def _delete_media_file(relative_path: str | None) -> None:
    target = _resolve_media_path(relative_path)
    if target is None:
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass


def _clone_media_file(source_relative_path: str | None, directory: Path) -> str | None:
    source_path = _resolve_media_path(source_relative_path)
    if source_path is None or not source_path.exists() or not source_path.is_file():
        return None
    directory.mkdir(parents=True, exist_ok=True)
    suffix = _sanitize_image_suffix(source_path.name)
    target = directory / f"{uuid4().hex}{suffix}"
    shutil.copyfile(source_path, target)
    return relative_to_media(target)


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(float(value))
    except (TypeError, ValueError):
        return datetime.now()


def _get_inventory_config(module: str) -> _InventoryModuleConfig:
    try:
        return _INVENTORY_MODULE_CONFIGS[module]
    except KeyError as exc:  # pragma: no cover - defensive programming
        raise ValueError(f"Module d'inventaire inconnu: {module}") from exc


_INVENTORY_SNAPSHOT_DIR = db.DATA_DIR / "inventory_snapshots"
_INVENTORY_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
_INVENTORY_SNAPSHOT_LOCKS: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)


def _inventory_snapshot_path(module: str) -> Path:
    return _INVENTORY_SNAPSHOT_DIR / f"{module}_snapshot.json"


def _replace_snapshot_file(tmp_path: Path, path: Path, module: str) -> None:
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            tmp_path.replace(path)
            return
        except OSError as exc:
            winerror = getattr(exc, "winerror", None)
            is_win32_share = isinstance(exc, PermissionError) or winerror == 32
            if not is_win32_share or attempt >= attempts:
                logger.error(
                    "[INVENTORY_SNAPSHOT] Replace failed pid=%s module=%s tmp=%s dest=%s",
                    os.getpid(),
                    module,
                    tmp_path,
                    path,
                    exc_info=True,
                )
                raise
            delay = 0.05 + random.random() * 0.1
            logger.warning(
                "[INVENTORY_SNAPSHOT] Replace retry pid=%s module=%s attempt=%s/%s tmp=%s dest=%s delay=%.3fs",
                os.getpid(),
                module,
                attempt,
                attempts,
                tmp_path,
                path,
                delay,
            )
            time.sleep(delay)


def _fetch_table_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    info_rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    order_clause = "ORDER BY id" if any(row["name"] == "id" for row in info_rows) else ""
    cur = conn.execute(f"SELECT * FROM {table} {order_clause}")
    return [dict(row) for row in cur.fetchall()]


def _persist_inventory_module(conn: sqlite3.Connection, module: str) -> None:
    config = _get_inventory_config(module)
    snapshot = {
        "categories": _fetch_table_rows(conn, config.tables.categories),
        "category_sizes": _fetch_table_rows(conn, config.tables.category_sizes),
        "items": _fetch_table_rows(conn, config.tables.items),
        "movements": _fetch_table_rows(conn, config.tables.movements),
    }
    path = _inventory_snapshot_path(module)
    tmp_path = path.with_suffix(".tmp")
    with _INVENTORY_SNAPSHOT_LOCKS[module]:
        with open(tmp_path, "w", encoding="utf-8") as buffer:
            json.dump(snapshot, buffer, ensure_ascii=False, indent=2)
        _replace_snapshot_file(tmp_path, path, module)


def _inventory_modules_to_persist(module: str) -> tuple[str, ...]:
    modules: list[str] = [module]
    if module == "vehicle_inventory":
        modules.append("inventory_remise")
    return tuple(dict.fromkeys(modules))


def _persist_after_commit(conn: sqlite3.Connection, *modules: str) -> None:
    conn.commit()
    seen: set[str] = set()
    for module in modules:
        if not module or module in seen:
            continue
        seen.add(module)
        try:
            _persist_inventory_module(conn, module)
        except ValueError:
            continue


def _restore_inventory_module(conn: sqlite3.Connection, module: str) -> None:
    path = _inventory_snapshot_path(module)
    if not path.exists():
        return
    config = _get_inventory_config(module)
    cur = conn.execute(f"SELECT COUNT(*) AS count FROM {config.tables.items}")
    row = cur.fetchone()
    if row and row["count"]:
        return
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):  # pragma: no cover - invalid snapshot ignored
        return

    def restore_table(table_name: str, rows: list[dict[str, Any]]) -> None:
        conn.execute(f"DELETE FROM {table_name}")
        if not rows:
            return
        info_rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = [info_row["name"] for info_row in info_rows]
        placeholders = ", ".join("?" for _ in columns)
        values = [tuple(row.get(column) for column in columns) for row in rows]
        conn.executemany(
            f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )

    restore_table(config.tables.categories, snapshot.get("categories", []))
    restore_table(config.tables.category_sizes, snapshot.get("category_sizes", []))
    restore_table(config.tables.items, snapshot.get("items", []))
    restore_table(config.tables.movements, snapshot.get("movements", []))


def _restore_inventory_snapshots() -> None:
    with db.get_stock_connection() as conn:
        for module in ("default", "inventory_remise", "vehicle_inventory", "pharmacy"):
            try:
                _restore_inventory_module(conn, module)
            except ValueError:  # pragma: no cover - skip unknown module
                continue
        conn.commit()


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
    db.init_databases()
    _apply_schema_migrations()

    if not _db_initialized:
        _restore_inventory_snapshots()
        seed_default_admin()
        _db_initialized = True


def _ensure_vehicle_item_columns(conn: sqlite3.Connection) -> None:
    vehicle_item_info = conn.execute("PRAGMA table_info(vehicle_items)").fetchall()
    vehicle_item_columns = {row["name"] for row in vehicle_item_info}

    if "image_path" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN image_path TEXT")
    if "position_x" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN position_x REAL")
    if "position_y" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN position_y REAL")
    if "remise_item_id" not in vehicle_item_columns:
        conn.execute(
            "ALTER TABLE vehicle_items ADD COLUMN remise_item_id INTEGER REFERENCES remise_items(id) ON DELETE SET NULL"
        )
    if "documentation_url" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN documentation_url TEXT")
    if "tutorial_url" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN tutorial_url TEXT")
    if "shared_file_url" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN shared_file_url TEXT")
    if "lot_id" not in vehicle_item_columns:
        conn.execute(
            "ALTER TABLE vehicle_items ADD COLUMN lot_id INTEGER REFERENCES remise_lots(id) ON DELETE SET NULL"
        )
    if "show_in_qr" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN show_in_qr INTEGER NOT NULL DEFAULT 1")

    if "vehicle_type" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN vehicle_type TEXT")

    if "pharmacy_item_id" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN pharmacy_item_id INTEGER REFERENCES pharmacy_items(id)")


def _ensure_vehicle_category_columns(conn: sqlite3.Connection) -> None:
    category_info = conn.execute("PRAGMA table_info(vehicle_categories)").fetchall()
    category_columns = {row["name"] for row in category_info}

    if "vehicle_type" not in category_columns:
        conn.execute("ALTER TABLE vehicle_categories ADD COLUMN vehicle_type TEXT")


def _ensure_vehicle_view_settings_columns(conn: sqlite3.Connection) -> None:
    view_settings_info = conn.execute("PRAGMA table_info(vehicle_view_settings)").fetchall()
    view_settings_columns = {row["name"] for row in view_settings_info}

    if "pointer_mode_enabled" not in view_settings_columns:
        conn.execute(
            "ALTER TABLE vehicle_view_settings ADD COLUMN pointer_mode_enabled INTEGER NOT NULL DEFAULT 0"
        )

    if "hide_edit_buttons" not in view_settings_columns:
        conn.execute(
            "ALTER TABLE vehicle_view_settings ADD COLUMN hide_edit_buttons INTEGER NOT NULL DEFAULT 0"
        )


def _ensure_remise_item_columns(conn: sqlite3.Connection) -> None:
    remise_item_info = conn.execute("PRAGMA table_info(remise_items)").fetchall()
    remise_item_columns = {row["name"] for row in remise_item_info}

    if "track_low_stock" not in remise_item_columns:
        conn.execute(
            "ALTER TABLE remise_items ADD COLUMN track_low_stock INTEGER NOT NULL DEFAULT 1"
        )
    if "expiration_date" not in remise_item_columns:
        conn.execute("ALTER TABLE remise_items ADD COLUMN expiration_date TEXT")


def _ensure_remise_lot_columns(conn: sqlite3.Connection) -> None:
    lot_info = conn.execute("PRAGMA table_info(remise_lots)").fetchall()
    lot_columns = {row["name"] for row in lot_info}

    if "image_path" not in lot_columns:
        conn.execute("ALTER TABLE remise_lots ADD COLUMN image_path TEXT")


def _ensure_pharmacy_lot_columns(conn: sqlite3.Connection) -> None:
    lot_info = conn.execute("PRAGMA table_info(pharmacy_lots)").fetchall()
    lot_columns = {row["name"] for row in lot_info}

    if "image_path" not in lot_columns:
        conn.execute("ALTER TABLE pharmacy_lots ADD COLUMN image_path TEXT")


def _ensure_vehicle_item_qr_tokens(conn: sqlite3.Connection) -> None:
    vehicle_item_info = conn.execute("PRAGMA table_info(vehicle_items)").fetchall()
    vehicle_item_columns = {row["name"] for row in vehicle_item_info}
    updated_schema = False

    if "qr_token" not in vehicle_item_columns:
        conn.execute("ALTER TABLE vehicle_items ADD COLUMN qr_token TEXT")
        updated_schema = True

    missing_tokens = conn.execute(
        "SELECT id FROM vehicle_items WHERE qr_token IS NULL OR qr_token = ''"
    ).fetchall()
    for row in missing_tokens:
        conn.execute(
            "UPDATE vehicle_items SET qr_token = ? WHERE id = ?",
            (uuid4().hex, row["id"]),
        )
        updated_schema = True

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_items_qr_token ON vehicle_items(qr_token)"
    )

    if updated_schema:
        _persist_after_commit(conn, "vehicle_inventory")


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
            CREATE TABLE IF NOT EXISTS pharmacy_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                image_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name)
            );
            CREATE TABLE IF NOT EXISTS pharmacy_lot_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_id INTEGER NOT NULL REFERENCES pharmacy_lots(id) ON DELETE CASCADE,
                pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                UNIQUE(lot_id, pharmacy_item_id)
            );
            CREATE INDEX IF NOT EXISTS idx_pharmacy_lot_items_lot ON pharmacy_lot_items(lot_id);
            CREATE INDEX IF NOT EXISTS idx_pharmacy_lot_items_item ON pharmacy_lot_items(pharmacy_item_id);
            CREATE TABLE IF NOT EXISTS vehicle_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                image_path TEXT,
                vehicle_type TEXT
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
                vehicle_type TEXT,
                size TEXT,
                quantity INTEGER NOT NULL DEFAULT 0,
                low_stock_threshold INTEGER NOT NULL DEFAULT 0,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                image_path TEXT,
                position_x REAL,
                position_y REAL,
                remise_item_id INTEGER REFERENCES remise_items(id) ON DELETE SET NULL,
                documentation_url TEXT,
                tutorial_url TEXT,
                shared_file_url TEXT,
                qr_token TEXT,
                show_in_qr INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS vehicle_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL REFERENCES vehicle_items(id) ON DELETE CASCADE,
                delta INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_vehicle_movements_item ON vehicle_movements(item_id);
            CREATE TABLE IF NOT EXISTS vehicle_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS vehicle_view_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL REFERENCES vehicle_categories(id) ON DELETE CASCADE,
                name TEXT NOT NULL COLLATE NOCASE,
                background_photo_id INTEGER REFERENCES vehicle_photos(id) ON DELETE SET NULL,
                pointer_mode_enabled INTEGER NOT NULL DEFAULT 0,
                hide_edit_buttons INTEGER NOT NULL DEFAULT 0,
                UNIQUE(category_id, name)
            );
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
                track_low_stock INTEGER NOT NULL DEFAULT 1,
                expiration_date TEXT,
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
            CREATE TABLE IF NOT EXISTS remise_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                image_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name)
            );
            CREATE TABLE IF NOT EXISTS remise_lot_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_id INTEGER NOT NULL REFERENCES remise_lots(id) ON DELETE CASCADE,
                remise_item_id INTEGER NOT NULL REFERENCES remise_items(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                UNIQUE(lot_id, remise_item_id)
            );
            CREATE INDEX IF NOT EXISTS idx_remise_lot_items_lot ON remise_lot_items(lot_id);
            CREATE INDEX IF NOT EXISTS idx_remise_lot_items_item ON remise_lot_items(remise_item_id);
            CREATE TABLE IF NOT EXISTS remise_purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                note TEXT,
                auto_created INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS remise_purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL REFERENCES remise_purchase_orders(id) ON DELETE CASCADE,
                remise_item_id INTEGER NOT NULL REFERENCES remise_items(id) ON DELETE CASCADE,
                quantity_ordered INTEGER NOT NULL,
                quantity_received INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        _ensure_remise_item_columns(conn)
        _ensure_remise_lot_columns(conn)
        _ensure_pharmacy_lot_columns(conn)
        _ensure_vehicle_category_columns(conn)
        _ensure_vehicle_view_settings_columns(conn)
        _ensure_vehicle_item_columns(conn)
        _ensure_vehicle_item_qr_tokens(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vehicle_items_remise ON vehicle_items(remise_item_id)"
        )

        _sync_vehicle_inventory_with_remise(conn)

        pharmacy_category_info = conn.execute("PRAGMA table_info(pharmacy_items)").fetchall()
        pharmacy_category_columns = {row["name"] for row in pharmacy_category_info}
        if "category_id" not in pharmacy_category_columns:
            conn.execute(
                """
                ALTER TABLE pharmacy_items
                ADD COLUMN category_id INTEGER REFERENCES pharmacy_categories(id) ON DELETE SET NULL
                """
            )

        _persist_after_commit(conn, "vehicle_inventory")


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


def _prepare_vehicle_item_sku(
    conn: sqlite3.Connection, sku: Optional[str], remise_item_id: int
) -> tuple[Optional[str], bool]:
    """Return the SKU to use for a remise item and relink existing items when needed."""

    if not sku:
        return None, False

    row = conn.execute(
        "SELECT id, remise_item_id FROM vehicle_items WHERE sku = ?",
        (sku,),
    ).fetchone()
    if row is None:
        return sku, False

    existing_remise_id = row["remise_item_id"]
    if existing_remise_id == remise_item_id:
        return sku, False

    if existing_remise_id is None:
        conn.execute(
            "UPDATE vehicle_items SET remise_item_id = ? WHERE id = ?",
            (remise_item_id, row["id"]),
        )
        return sku, True

    # Another remise item already owns this SKU; fall back to a NULL SKU to avoid conflicts.
    return None, False


def _sync_vehicle_item_from_remise(conn: sqlite3.Connection, source: sqlite3.Row) -> None:
    remise_item_id = source["id"]
    sku_value, sku_relinked = _prepare_vehicle_item_sku(conn, source["sku"], remise_item_id)

    existing_rows = conn.execute(
        "SELECT id, category_id FROM vehicle_items WHERE remise_item_id = ?",
        (remise_item_id,),
    ).fetchall()
    if not existing_rows:
        if sku_relinked:
            existing_rows = conn.execute(
                "SELECT id, category_id FROM vehicle_items WHERE remise_item_id = ?",
                (remise_item_id,),
            ).fetchall()
        if not existing_rows:
            conn.execute(
                """
                INSERT INTO vehicle_items (
                    name,
                    sku,
                    category_id,
                    size,
                    quantity,
                    low_stock_threshold,
                    supplier_id,
                    position_x,
                    position_y,
                    remise_item_id
                )
                VALUES (?, ?, NULL, ?, 0, 0, ?, NULL, NULL, ?)
                """,
                (source["name"], sku_value, source["size"], source["supplier_id"], remise_item_id),
            )
            return

    template_assignments = ["name = ?", "size = ?"]
    template_params: list[object] = [source["name"], source["size"]]
    assigned_assignments = ["name = ?"]
    assigned_params: list[object] = [source["name"]]
    supplier_id = source["supplier_id"]
    if supplier_id is not None:
        template_assignments.append("supplier_id = ?")
        template_params.append(supplier_id)
        assigned_assignments.append("supplier_id = ?")
        assigned_params.append(supplier_id)
    template_params.append(remise_item_id)
    assigned_params.append(remise_item_id)
    conn.execute(
        f"UPDATE vehicle_items SET {', '.join(template_assignments)} WHERE remise_item_id = ? AND category_id IS NULL",
        template_params,
    )
    conn.execute(
        f"UPDATE vehicle_items SET {', '.join(assigned_assignments)} WHERE remise_item_id = ? AND category_id IS NOT NULL",
        assigned_params,
    )

    conn.execute(
        "UPDATE vehicle_items SET sku = ? WHERE remise_item_id = ? AND category_id IS NULL",
        (sku_value, remise_item_id),
    )

    template_row = conn.execute(
        "SELECT id FROM vehicle_items WHERE remise_item_id = ? AND category_id IS NULL",
        (remise_item_id,),
    ).fetchone()
    if template_row is None:
        conn.execute(
            """
            INSERT INTO vehicle_items (
                name,
                sku,
                category_id,
                size,
                quantity,
                low_stock_threshold,
                supplier_id,
                position_x,
                position_y,
                remise_item_id
            )
            VALUES (?, ?, NULL, ?, 0, 0, ?, NULL, NULL, ?)
            """,
            (source["name"], sku_value, source["size"], source["supplier_id"], remise_item_id),
        )


def _sync_vehicle_inventory_with_remise(conn: sqlite3.Connection) -> None:
    remise_rows = conn.execute(
        "SELECT id, name, sku, supplier_id, size FROM remise_items"
    ).fetchall()
    seen_ids: list[int] = []
    for row in remise_rows:
        _sync_vehicle_item_from_remise(conn, row)
        seen_ids.append(row["id"])
    if seen_ids:
        placeholders = ", ".join("?" for _ in seen_ids)
        conn.execute(
            f"DELETE FROM vehicle_items WHERE remise_item_id IS NOT NULL AND remise_item_id NOT IN ({placeholders})",
            seen_ids,
        )
    else:
        conn.execute("DELETE FROM vehicle_items WHERE remise_item_id IS NOT NULL")


def _sync_single_vehicle_item(remise_item_id: int) -> None:
    with db.get_stock_connection() as conn:
        source = conn.execute(
            "SELECT id, name, sku, supplier_id, size FROM remise_items WHERE id = ?",
            (remise_item_id,),
        ).fetchone()
        if source is None:
            conn.execute("DELETE FROM vehicle_items WHERE remise_item_id = ?", (remise_item_id,))
        else:
            _sync_vehicle_item_from_remise(conn, source)
        _persist_after_commit(conn, "vehicle_inventory")


def _build_inventory_item(row: sqlite3.Row) -> models.Item:
    image_url = None
    if "image_path" in row.keys():
        image_url = _build_media_url(row["image_path"])
    position_x = row["position_x"] if "position_x" in row.keys() else None
    position_y = row["position_y"] if "position_y" in row.keys() else None
    documentation_url = None
    tutorial_url = None
    qr_token = None
    shared_file_url = None
    show_in_qr = True
    if "documentation_url" in row.keys():
        documentation_url = row["documentation_url"]
    if "tutorial_url" in row.keys():
        tutorial_url = row["tutorial_url"]
    if "qr_token" in row.keys():
        qr_token = row["qr_token"]
    if "shared_file_url" in row.keys():
        shared_file_url = row["shared_file_url"]
    if "show_in_qr" in row.keys():
        show_in_qr = bool(row["show_in_qr"])
    lot_id = row["lot_id"] if "lot_id" in row.keys() else None
    lot_name = None
    if "lot_name" in row.keys():
        lot_name = row["lot_name"]
    lot_names: list[str] = []
    lot_names_raw = row["lot_names"] if "lot_names" in row.keys() else None
    if lot_names_raw:
        lot_names = [name.strip() for name in str(lot_names_raw).split(",") if name and name.strip()]
    lot_count = row["lot_count"] if "lot_count" in row.keys() else None
    name = row["pharmacy_name"] if "pharmacy_name" in row.keys() and row["pharmacy_name"] else None
    if not name:
        name = row["remise_name"] if "remise_name" in row.keys() and row["remise_name"] else row["name"]
    sku = row["pharmacy_sku"] if "pharmacy_sku" in row.keys() and row["pharmacy_sku"] else None
    if not sku:
        sku = row["remise_sku"] if "remise_sku" in row.keys() and row["remise_sku"] else row["sku"]
    supplier_id = row["supplier_id"] if "supplier_id" in row.keys() else None
    if supplier_id is None and "pharmacy_supplier_id" in row.keys():
        supplier_id = row["pharmacy_supplier_id"]
    if supplier_id is None and "remise_supplier_id" in row.keys():
        supplier_id = row["remise_supplier_id"]
    remise_item_id = row["remise_item_id"] if "remise_item_id" in row.keys() else None
    pharmacy_item_id = row["pharmacy_item_id"] if "pharmacy_item_id" in row.keys() else None
    remise_quantity = None
    if "remise_quantity" in row.keys():
        remise_quantity = row["remise_quantity"]
    pharmacy_quantity = None
    if "pharmacy_quantity" in row.keys():
        pharmacy_quantity = row["pharmacy_quantity"]
    track_low_stock = True
    if "track_low_stock" in row.keys():
        track_low_stock = bool(row["track_low_stock"])
    expiration_date = None
    if "expiration_date" in row.keys():
        expiration_date = row["expiration_date"]
    assigned_vehicle_names: list[str] = []
    if "assigned_vehicle_names" in row.keys() and row["assigned_vehicle_names"]:
        assigned_vehicle_names = [
            name.strip()
            for name in str(row["assigned_vehicle_names"]).split(",")
            if name and name.strip()
        ]
    size_value = row["resolved_size"] if "resolved_size" in row.keys() else row["size"]

    return models.Item(
        id=row["id"],
        name=name,
        sku=sku,
        category_id=row["category_id"],
        size=size_value,
        quantity=row["quantity"],
        low_stock_threshold=row["low_stock_threshold"],
        track_low_stock=track_low_stock,
        supplier_id=supplier_id,
        expiration_date=expiration_date,
        remise_item_id=remise_item_id,
        pharmacy_item_id=pharmacy_item_id,
        remise_quantity=remise_quantity,
        pharmacy_quantity=pharmacy_quantity,
        image_url=image_url,
        shared_file_url=shared_file_url,
        position_x=position_x,
        position_y=position_y,
        documentation_url=documentation_url,
        tutorial_url=tutorial_url,
        qr_token=qr_token,
        lot_id=lot_id,
        lot_name=lot_name,
        lot_names=lot_names,
        is_in_lot=bool(lot_id) or bool(lot_names) or bool(lot_count),
        show_in_qr=show_in_qr,
        vehicle_type=row["vehicle_type"] if "vehicle_type" in row.keys() else None,
        assigned_vehicle_names=assigned_vehicle_names,
    )


def _list_inventory_items_internal(
    module: str, search: str | None = None
) -> list[models.Item]:
    ensure_database_ready()
    config = _get_inventory_config(module)
    if module == "vehicle_inventory":
        with db.get_stock_connection() as conn:
            _ensure_vehicle_item_columns(conn)
    params: tuple[object, ...] = ()
    if module == "vehicle_inventory":
        query = (
            "SELECT vi.*, "
            "COALESCE(vi.size, ri.size) AS resolved_size, "
            "ri.name AS remise_name, "
            "ri.sku AS remise_sku, "
            "ri.supplier_id AS remise_supplier_id, "
            "ri.quantity AS remise_quantity, "
            "pi.name AS pharmacy_name, "
            "pi.barcode AS pharmacy_sku, "
            "pi.quantity AS pharmacy_quantity, "
            "rl.name AS lot_name "
            "FROM vehicle_items AS vi "
            "LEFT JOIN remise_items AS ri ON ri.id = vi.remise_item_id "
            "LEFT JOIN pharmacy_items AS pi ON pi.id = vi.pharmacy_item_id "
            "LEFT JOIN remise_lots AS rl ON rl.id = vi.lot_id"
        )
        if search:
            query += " WHERE COALESCE(ri.name, vi.name) LIKE ? OR COALESCE(ri.sku, vi.sku) LIKE ?"
            like = f"%{search}%"
            params = (like, like)
        query += " ORDER BY COALESCE(ri.name, vi.name) COLLATE NOCASE"
    elif module == "inventory_remise":
        query = (
            "SELECT ri.*, assignments.vehicle_names AS assigned_vehicle_names, "
            "lot_memberships.lot_names, lot_memberships.lot_count "
            "FROM remise_items AS ri "
            "LEFT JOIN ("
            "  SELECT vi.remise_item_id, GROUP_CONCAT(DISTINCT vc.name) AS vehicle_names "
            "  FROM vehicle_items AS vi "
            "  JOIN vehicle_categories AS vc ON vc.id = vi.category_id "
            "  WHERE vi.remise_item_id IS NOT NULL "
            "  GROUP BY vi.remise_item_id"
            ") AS assignments ON assignments.remise_item_id = ri.id "
            "LEFT JOIN ("
            "  SELECT rli.remise_item_id, GROUP_CONCAT(DISTINCT rl.name) AS lot_names, "
            "         COUNT(DISTINCT rl.id) AS lot_count "
            "  FROM remise_lot_items AS rli "
            "  JOIN remise_lots AS rl ON rl.id = rli.lot_id "
            "  GROUP BY rli.remise_item_id"
            ") AS lot_memberships ON lot_memberships.remise_item_id = ri.id"
        )
        if search:
            query += " WHERE ri.name LIKE ? OR ri.sku LIKE ?"
            like = f"%{search}%"
            params = (like, like)
        query += " ORDER BY ri.name COLLATE NOCASE"
    else:
        query = f"SELECT * FROM {config.tables.items}"
        if search:
            query += " WHERE name LIKE ? OR sku LIKE ?"
            like = f"%{search}%"
            params = (like, like)
        query += " ORDER BY name COLLATE NOCASE"
    with db.get_stock_connection() as conn:
        if module == "inventory_remise":
            _ensure_remise_item_columns(conn)
        cur = conn.execute(query, params)
        return [_build_inventory_item(row) for row in cur.fetchall()]


def _get_inventory_item_internal(module: str, item_id: int) -> models.Item:
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        if module == "inventory_remise":
            _ensure_remise_item_columns(conn)
        if module == "vehicle_inventory":
            _ensure_vehicle_item_columns(conn)
        if module == "vehicle_inventory":
            cur = conn.execute(
                """
                SELECT vi.*, COALESCE(vi.size, ri.size) AS resolved_size, ri.name AS remise_name, ri.sku AS remise_sku,
                       ri.supplier_id AS remise_supplier_id, ri.quantity AS remise_quantity, pi.name AS pharmacy_name,
                       pi.barcode AS pharmacy_sku, pi.quantity AS pharmacy_quantity, rl.name AS lot_name
                FROM vehicle_items AS vi
                LEFT JOIN remise_items AS ri ON ri.id = vi.remise_item_id
                LEFT JOIN pharmacy_items AS pi ON pi.id = vi.pharmacy_item_id
                LEFT JOIN remise_lots AS rl ON rl.id = vi.lot_id
                WHERE vi.id = ?
                """,
                (item_id,),
            )
        elif module == "inventory_remise":
            cur = conn.execute(
                """
                SELECT ri.*, assignments.vehicle_names AS assigned_vehicle_names,
                       lot_memberships.lot_names, lot_memberships.lot_count
                FROM remise_items AS ri
                LEFT JOIN (
                    SELECT vi.remise_item_id, GROUP_CONCAT(DISTINCT vc.name) AS vehicle_names
                    FROM vehicle_items AS vi
                    JOIN vehicle_categories AS vc ON vc.id = vi.category_id
                    WHERE vi.remise_item_id IS NOT NULL
                    GROUP BY vi.remise_item_id
                ) AS assignments ON assignments.remise_item_id = ri.id
                LEFT JOIN (
                    SELECT rli.remise_item_id, GROUP_CONCAT(DISTINCT rl.name) AS lot_names,
                           COUNT(DISTINCT rl.id) AS lot_count
                    FROM remise_lot_items AS rli
                    JOIN remise_lots AS rl ON rl.id = rli.lot_id
                    GROUP BY rli.remise_item_id
                ) AS lot_memberships ON lot_memberships.remise_item_id = ri.id
                WHERE ri.id = ?
                """,
                (item_id,),
            )
        else:
            cur = conn.execute(
                f"SELECT * FROM {config.tables.items} WHERE id = ?",
                (item_id,),
            )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        return _build_inventory_item(row)


def _update_remise_quantity(
    conn: sqlite3.Connection, remise_item_id: int, delta: int
) -> None:
    if delta == 0:
        return
    row = conn.execute(
        "SELECT quantity FROM remise_items WHERE id = ?",
        (remise_item_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Article de remise introuvable")
    updated = row["quantity"] + delta
    if updated < 0:
        raise ValueError("Stock insuffisant en remise pour cette affectation.")
    cursor = conn.execute(
        "UPDATE remise_items SET quantity = ? WHERE id = ?",
        (updated, remise_item_id),
    )
    logger.info(
        "[VEHICLE_INVENTORY] Delete rowcount step=update-remise-quantity remise_item_id=%s rowcount=%s",
        remise_item_id,
        cursor.rowcount,
    )


def _update_pharmacy_quantity(
    conn: sqlite3.Connection, pharmacy_item_id: int, delta: int
) -> bool:
    if delta == 0:
        return True
    row = conn.execute(
        "SELECT quantity FROM pharmacy_items WHERE id = ?",
        (pharmacy_item_id,),
    ).fetchone()
    if row is None:
        logger.info(
            "[VEHICLE_INVENTORY] Delete rowcount step=update-pharmacy-quantity pharmacy_item_id=%s rowcount=%s",
            pharmacy_item_id,
            0,
        )
        return False
    updated = row["quantity"] + delta
    if updated < 0:
        raise ValueError("Stock insuffisant en pharmacie pour cette affectation.")
    cursor = conn.execute(
        "UPDATE pharmacy_items SET quantity = ? WHERE id = ?",
        (updated, pharmacy_item_id),
    )
    logger.info(
        "[VEHICLE_INVENTORY] Delete rowcount step=update-pharmacy-quantity pharmacy_item_id=%s rowcount=%s",
        pharmacy_item_id,
        cursor.rowcount,
    )
    return cursor.rowcount > 0


def resolve_or_create_pharmacy_item(
    conn: sqlite3.Connection,
    vehicle_row: dict,
) -> int:
    pharmacy_item_id = vehicle_row.get("pharmacy_item_id")
    if pharmacy_item_id is not None:
        row = conn.execute(
            "SELECT id FROM pharmacy_items WHERE id = ?",
            (pharmacy_item_id,),
        ).fetchone()
        if row is not None:
            logger.info(
                "[VEHICLE_INVENTORY] Delete step=resolve-pharmacy-item found_by=id pharmacy_item_id=%s",
                pharmacy_item_id,
            )
            return row["id"]

    try:
        barcode = _normalize_barcode(vehicle_row.get("sku"))
    except ValueError:
        barcode = None

    if barcode:
        row = conn.execute(
            "SELECT id FROM pharmacy_items WHERE barcode = ?",
            (barcode,),
        ).fetchone()
        if row is not None:
            logger.info(
                "[VEHICLE_INVENTORY] Delete step=resolve-pharmacy-item found_by=sku pharmacy_item_id=%s",
                row["id"],
            )
            return row["id"]

    row = conn.execute(
        """
        SELECT id
        FROM pharmacy_items
        WHERE name = ? COLLATE NOCASE
          AND category_id IS ?
        """,
        (vehicle_row.get("name"), vehicle_row.get("category_id")),
    ).fetchone()
    if row is not None:
        logger.info(
            "[VEHICLE_INVENTORY] Delete step=resolve-pharmacy-item found_by=name pharmacy_item_id=%s",
            row["id"],
        )
        return row["id"]

    low_stock_threshold = vehicle_row.get("low_stock_threshold") or 0
    try:
        cursor = conn.execute(
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
                vehicle_row.get("name"),
                None,
                None,
                barcode,
                0,
                low_stock_threshold,
                None,
                None,
                vehicle_row.get("category_id"),
            ),
        )
    except sqlite3.IntegrityError:
        if barcode:
            row = conn.execute(
                "SELECT id FROM pharmacy_items WHERE barcode = ?",
                (barcode,),
            ).fetchone()
            if row is not None:
                logger.info(
                    "[VEHICLE_INVENTORY] Delete step=resolve-pharmacy-item found_by=sku pharmacy_item_id=%s",
                    row["id"],
                )
                return row["id"]
        row = conn.execute(
            """
            SELECT id
            FROM pharmacy_items
            WHERE name = ? COLLATE NOCASE
              AND category_id IS ?
            """,
            (vehicle_row.get("name"), vehicle_row.get("category_id")),
        ).fetchone()
        if row is not None:
            logger.info(
                "[VEHICLE_INVENTORY] Delete step=resolve-pharmacy-item found_by=name pharmacy_item_id=%s",
                row["id"],
            )
            return row["id"]
        raise

    pharmacy_item_id = cursor.lastrowid
    logger.info(
        "[VEHICLE_INVENTORY] Delete step=resolve-pharmacy-item found_by=created pharmacy_item_id=%s",
        pharmacy_item_id,
    )
    return pharmacy_item_id


def _restack_vehicle_item_template(
    conn: sqlite3.Connection,
    item_id: int,
    remise_item_id: int,
    image_path: str | None,
) -> int | None:
    template_row = conn.execute(
        """
        SELECT id
        FROM vehicle_items
        WHERE remise_item_id = ? AND category_id IS NULL
        ORDER BY id
        LIMIT 1
        """,
        (remise_item_id,),
    ).fetchone()
    if template_row is None:
        return None
    template_id = template_row["id"]
    if template_id == item_id:
        return template_id
    if image_path:
        _delete_media_file(image_path)
    conn.execute("DELETE FROM vehicle_items WHERE id = ?", (item_id,))
    return template_id


def _create_inventory_item_internal(
    module: str, payload: models.ItemCreate
) -> models.Item:
    ensure_database_ready()
    config = _get_inventory_config(module)
    if (
        module == "vehicle_inventory"
        and payload.category_id is not None
        and payload.quantity <= 0
    ):
        raise ValueError("La quantité affectée au véhicule doit être strictement positive.")
    with db.get_stock_connection() as conn:
        if module == "inventory_remise":
            _ensure_remise_item_columns(conn)
        vehicle_type = payload.vehicle_type
        if module == "vehicle_inventory":
            _ensure_vehicle_item_columns(conn)
            _ensure_vehicle_category_columns(conn)
            if payload.category_id is not None:
                target_view = (payload.size or "").strip()
                if not target_view:
                    default_view_row = conn.execute(
                        """
                        SELECT name
                        FROM vehicle_category_sizes
                        WHERE category_id = ?
                        ORDER BY name COLLATE NOCASE
                        LIMIT 1
                        """,
                        (payload.category_id,),
                    ).fetchone()
                    target_view = (
                        default_view_row["name"]
                        if default_view_row is not None
                        else DEFAULT_VEHICLE_VIEW_NAME
                    )
                payload.size = target_view
        cloned_image_path: str | None = None
        name = payload.name
        sku = payload.sku
        insert_sku = sku
        supplier_id = payload.supplier_id
        expiration_date = (
            payload.expiration_date.isoformat() if payload.expiration_date else None
        )
        remise_item_id: int | None = None
        pharmacy_item_id: int | None = None
        lot_id: int | None = None
        if module == "vehicle_inventory":
            remise_item_id = payload.remise_item_id
            pharmacy_item_id = payload.pharmacy_item_id
            lot_id = payload.lot_id
            if remise_item_id is None and pharmacy_item_id is None:
                raise ValueError(
                    "Un article de remise ou de pharmacie doit être sélectionné."
                )
            if remise_item_id is not None and pharmacy_item_id is not None:
                raise ValueError(
                    "Sélectionnez une seule source de matériel (remise ou pharmacie)."
                )
            if lot_id is not None:
                if payload.category_id is None:
                    raise ValueError(
                        "Un lot ne peut être affecté qu'à un véhicule depuis l'inventaire véhicules."
                    )
                _require_remise_lot(conn, lot_id)
            source_column = "pharmacy_item_id" if pharmacy_item_id else "remise_item_id"
            source_id = pharmacy_item_id if pharmacy_item_id is not None else remise_item_id
            source_query = (
                "SELECT id, name, barcode AS sku FROM pharmacy_items WHERE id = ?"
                if pharmacy_item_id is not None
                else "SELECT id, name, sku, supplier_id FROM remise_items WHERE id = ?"
            )
            source = conn.execute(source_query, (source_id,)).fetchone()
            if source is None:
                raise ValueError(
                    "Article de pharmacie introuvable"
                    if pharmacy_item_id is not None
                    else "Article de remise introuvable"
                )
            name = source["name"]
            sku = source["sku"]
            if pharmacy_item_id is not None and not sku:
                sku = f"PHARM-{source['id']}"
            insert_sku = sku
            if supplier_id is None and "supplier_id" in source.keys():
                supplier_id = source["supplier_id"]
            if payload.category_id is not None:
                category_row = conn.execute(
                    "SELECT vehicle_type FROM vehicle_categories WHERE id = ?",
                    (payload.category_id,),
                ).fetchone()
                if category_row is None:
                    raise ValueError("Catégorie de véhicule introuvable")
                vehicle_type = category_row["vehicle_type"]
            template_row = conn.execute(
                f"""
                SELECT id, quantity, image_path
                FROM {config.tables.items}
                WHERE {source_column} = ? AND category_id IS NULL
                ORDER BY id
                LIMIT 1
                """,
                (source_id,),
            ).fetchone()
            if payload.category_id is None and template_row is not None:
                existing = template_row
                delta_vehicle = payload.quantity - existing["quantity"]
                if delta_vehicle:
                    if pharmacy_item_id is not None:
                        _update_pharmacy_quantity(conn, pharmacy_item_id, -delta_vehicle)
                    else:
                        _update_remise_quantity(conn, remise_item_id, -delta_vehicle)
                conn.execute(
                    f"""
                    UPDATE {config.tables.items}
                    SET name = ?,
                        sku = ?,
                        category_id = ?,
                        size = ?,
                        quantity = ?,
                        low_stock_threshold = ?,
                        supplier_id = ?,
                        position_x = ?,
                        position_y = ?
                    WHERE id = ?
                    """,
                    (
                        name,
                        sku,
                        payload.category_id,
                        payload.size,
                        payload.quantity,
                        payload.low_stock_threshold,
                        supplier_id,
                        payload.position_x,
                        payload.position_y,
                        existing["id"],
                    ),
                )
                _persist_after_commit(conn, *_inventory_modules_to_persist(module))
                return _get_inventory_item_internal(module, existing["id"])
            if template_row is not None and template_row["image_path"]:
                cloned_image_path = _clone_media_file(
                    template_row["image_path"],
                    VEHICLE_ITEM_MEDIA_DIR,
                )
            if payload.category_id is not None:
                insert_sku = f"{sku}-{uuid4().hex[:6]}"
            if pharmacy_item_id is not None:
                _update_pharmacy_quantity(conn, pharmacy_item_id, -payload.quantity)
            else:
                _update_remise_quantity(conn, remise_item_id, -payload.quantity)
        columns = [
            "name",
            "sku",
            "category_id",
        ]
        values: list[object | None] = [
            name,
            insert_sku,
            payload.category_id,
        ]
        if module == "vehicle_inventory":
            columns.extend(["vehicle_type", "remise_item_id", "pharmacy_item_id"])
            values.extend([vehicle_type, remise_item_id, pharmacy_item_id])
        columns.extend([
            "size",
            "quantity",
            "low_stock_threshold",
            "supplier_id",
        ])
        values.extend(
            [
                payload.size,
                payload.quantity,
                payload.low_stock_threshold,
                supplier_id,
            ]
        )
        if module == "inventory_remise":
            columns.append("track_low_stock")
            values.append(int(payload.track_low_stock))
            columns.append("expiration_date")
            values.append(expiration_date)
        if module == "vehicle_inventory":
            columns.append("lot_id")
            values.append(lot_id)
            columns.extend(["position_x", "position_y"])
            values.extend([payload.position_x, payload.position_y])
            columns.extend(["documentation_url", "tutorial_url", "shared_file_url", "qr_token"])
            values.extend(
                [
                    payload.documentation_url,
                    payload.tutorial_url,
                    payload.shared_file_url,
                    uuid4().hex,
                ]
            )
            columns.append("show_in_qr")
            values.append(int(payload.show_in_qr))
            if cloned_image_path:
                columns.append("image_path")
                values.append(cloned_image_path)
        placeholders = ",".join("?" for _ in columns)
        cur = conn.execute(
            f"INSERT INTO {config.tables.items} ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        item_id = cur.lastrowid
        if config.auto_purchase_orders:
            _maybe_create_auto_purchase_order(conn, item_id)
        _persist_after_commit(conn, *_inventory_modules_to_persist(module))
    return _get_inventory_item_internal(module, item_id)


def _update_inventory_item_internal(
    module: str, item_id: int, payload: models.ItemUpdate
) -> models.Item:
    ensure_database_ready()
    config = _get_inventory_config(module)
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    fields.pop("image_url", None)
    fields.pop("qr_token", None)
    fields.pop("lot_id", None)
    if module != "vehicle_inventory":
        fields.pop("show_in_qr", None)
        fields.pop("vehicle_type", None)
        fields.pop("pharmacy_item_id", None)
    if module != "inventory_remise":
        fields.pop("expiration_date", None)
    elif "expiration_date" in fields:
        fields["expiration_date"] = (
            fields["expiration_date"].isoformat()
            if fields["expiration_date"] is not None
            else None
        )
    if not fields:
        return _get_inventory_item_internal(module, item_id)
    if module == "vehicle_inventory":
        # Vehicle inventory items mirror remise inventory metadata.
        fields.pop("name", None)
        fields.pop("sku", None)
        if "show_in_qr" in fields and fields["show_in_qr"] is not None:
            fields["show_in_qr"] = int(bool(fields["show_in_qr"]))
    result_item_id = item_id
    should_restack_to_template = False
    with db.get_stock_connection() as conn:
        if module == "inventory_remise":
            _ensure_remise_item_columns(conn)
        current_row: sqlite3.Row | None = None
        if module == "vehicle_inventory":
            _ensure_vehicle_item_columns(conn)
            current_row = conn.execute(
                f"SELECT quantity, remise_item_id, pharmacy_item_id, category_id, image_path, lot_id, vehicle_type FROM {config.tables.items} WHERE id = ?",
                (item_id,),
            ).fetchone()
            if current_row is None:
                raise ValueError("Article introuvable")
            current_quantity = current_row["quantity"]
            current_remise_item_id = current_row["remise_item_id"]
            current_pharmacy_item_id = current_row["pharmacy_item_id"]
            current_category_id = current_row["category_id"]
            current_vehicle_type = current_row["vehicle_type"]
            current_lot_id = current_row["lot_id"]
            target_category_id = fields.get("category_id", current_category_id)
            target_vehicle_type = current_vehicle_type
            if target_category_id is not None:
                category_row = conn.execute(
                    "SELECT vehicle_type FROM vehicle_categories WHERE id = ?",
                    (target_category_id,),
                ).fetchone()
                if category_row is None:
                    raise ValueError("Catégorie de véhicule introuvable")
                target_vehicle_type = category_row["vehicle_type"]
            if module == "vehicle_inventory":
                fields["vehicle_type"] = target_vehicle_type
            target_remise_item_id = fields.get("remise_item_id", current_remise_item_id)
            target_pharmacy_item_id = fields.get("pharmacy_item_id", current_pharmacy_item_id)
            if target_remise_item_id is None and target_pharmacy_item_id is None:
                raise ValueError(
                    "Un article de remise ou de pharmacie doit être sélectionné."
                )
            if target_remise_item_id is not None and target_pharmacy_item_id is not None:
                raise ValueError(
                    "Sélectionnez une seule source de matériel (remise ou pharmacie)."
                )
            if "remise_item_id" in fields or "pharmacy_item_id" in fields:
                source_id = (
                    fields.get("pharmacy_item_id")
                    if fields.get("pharmacy_item_id") is not None
                    else fields.get("remise_item_id")
                )
                source_query = (
                    "SELECT id, name, barcode AS sku FROM pharmacy_items WHERE id = ?"
                    if fields.get("pharmacy_item_id") is not None
                    else "SELECT id, name, sku, supplier_id FROM remise_items WHERE id = ?"
                )
                source = conn.execute(source_query, (source_id,)).fetchone()
                if source is None:
                    raise ValueError(
                        "Article de pharmacie introuvable"
                        if fields.get("pharmacy_item_id") is not None
                        else "Article de remise introuvable"
                    )
                fields["name"] = source["name"]
                new_sku = source["sku"]
                if fields.get("pharmacy_item_id") is not None and not new_sku:
                    new_sku = f"PHARM-{source['id']}"
                if target_category_id is not None:
                    new_sku = f"{new_sku}-{uuid4().hex[:6]}"
                fields["sku"] = new_sku
                if fields.get("supplier_id") is None and "supplier_id" in source.keys():
                    fields["supplier_id"] = source["supplier_id"]
            target_quantity = fields.get("quantity", current_quantity)
            if (
                target_category_id is not None
                and target_quantity is not None
                and target_quantity <= 0
            ):
                raise ValueError(
                    "La quantité d'un matériel affecté au véhicule doit être strictement positive."
                )
            if current_lot_id is not None:
                lock_message = (
                    "Impossible de retirer ce matériel : il est rattaché à un lot. Modifiez le lot dans l'inventaire remises."
                )
                if "category_id" in fields:
                    if fields["category_id"] != current_category_id:
                        raise ValueError(lock_message)
                    fields.pop("category_id", None)
                    target_category_id = current_category_id
                if "quantity" in fields:
                    if fields["quantity"] != current_quantity:
                        raise ValueError(lock_message)
                    fields.pop("quantity", None)
                    target_quantity = current_quantity
                if "remise_item_id" in fields or "pharmacy_item_id" in fields:
                    if fields.get("remise_item_id", current_remise_item_id) != current_remise_item_id or fields.get(
                        "pharmacy_item_id", current_pharmacy_item_id
                    ) != current_pharmacy_item_id:
                        raise ValueError(lock_message)
                    fields.pop("remise_item_id", None)
                    fields.pop("pharmacy_item_id", None)
                    target_remise_item_id = current_remise_item_id
                    target_pharmacy_item_id = current_pharmacy_item_id
            should_restack_to_template = (
                "category_id" in fields
                and fields["category_id"] is None
                and current_category_id is not None
            )
            current_source = "pharmacy" if current_pharmacy_item_id else "remise"
            target_source = "pharmacy" if target_pharmacy_item_id else "remise"
            current_source_id = current_pharmacy_item_id or current_remise_item_id
            target_source_id = target_pharmacy_item_id or target_remise_item_id

            def _update_source_quantity(source: str, source_id: int, delta: int) -> None:
                if source == "pharmacy":
                    _update_pharmacy_quantity(conn, source_id, delta)
                else:
                    _update_remise_quantity(conn, source_id, delta)

            if current_source == target_source and current_source_id == target_source_id:
                delta = current_quantity - target_quantity
                if delta:
                    _update_source_quantity(target_source, target_source_id, delta)
            else:
                if current_source_id is not None and current_quantity:
                    _update_source_quantity(current_source, current_source_id, current_quantity)
                _update_source_quantity(target_source, target_source_id, -target_quantity)
        if not fields:
            return _get_inventory_item_internal(module, item_id)
        assignments = ", ".join(f"{col} = ?" for col in fields)
        values = list(fields.values())
        values.append(item_id)
        should_check_low_stock = any(
            key in fields for key in {"quantity", "low_stock_threshold", "supplier_id"}
        )
        conn.execute(
            f"UPDATE {config.tables.items} SET {assignments} WHERE id = ?",
            values,
        )
        if config.auto_purchase_orders and should_check_low_stock:
            _maybe_create_auto_purchase_order(conn, item_id)
        if module == "vehicle_inventory" and should_restack_to_template and current_row is not None:
            template_id = _restack_vehicle_item_template(
                conn,
                item_id,
                target_remise_item_id,
                current_row["image_path"],
            )
            if template_id is not None:
                result_item_id = template_id
        _persist_after_commit(conn, *_inventory_modules_to_persist(module))
    return _get_inventory_item_internal(module, result_item_id)


def _delete_inventory_item_internal(module: str, item_id: int) -> None:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        if module == "vehicle_inventory":
            cur = conn.execute(
                f"SELECT image_path, lot_id FROM {config.tables.items} WHERE id = ?",
                (item_id,),
            )
            row = cur.fetchone()
            if row and row["lot_id"]:
                raise ValueError(
                    "Impossible de supprimer ce matériel depuis l'inventaire véhicules : il est rattaché à un lot."
                )
            if row and row["image_path"]:
                _delete_media_file(row["image_path"])
        conn.execute(
            f"DELETE FROM {config.tables.items} WHERE id = ?",
            (item_id,),
        )
        _persist_after_commit(conn, *_inventory_modules_to_persist(module))


def unassign_vehicle_lot(lot_id: int, category_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_vehicle_item_columns(conn)
        _require_remise_lot(conn, lot_id)
        rows = conn.execute(
            """
            SELECT id, quantity, remise_item_id, image_path
            FROM vehicle_items
            WHERE lot_id = ? AND category_id = ?
            ORDER BY id
            """,
            (lot_id, category_id),
        ).fetchall()
        if not rows:
            raise ValueError("Aucun matériel de ce lot n'est associé à ce véhicule.")
        for row in rows:
            remise_item_id = row["remise_item_id"]
            if remise_item_id is None:
                raise ValueError("Impossible de réapprovisionner ce matériel sans article de remise associé.")
            quantity = row["quantity"] or 0
            if quantity:
                _update_remise_quantity(conn, remise_item_id, quantity)
            image_path = row["image_path"]
            if image_path:
                _delete_media_file(image_path)
        conn.execute(
            "DELETE FROM vehicle_items WHERE lot_id = ? AND category_id = ?",
            (lot_id, category_id),
        )
        _persist_after_commit(conn, *_inventory_modules_to_persist("vehicle_inventory"))


def _list_inventory_categories_internal(module: str) -> list[models.Category]:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        if module == "vehicle_inventory":
            _ensure_vehicle_category_columns(conn)
        select_columns = "id, name"
        if module == "vehicle_inventory":
            select_columns += ", image_path, vehicle_type"
        cur = conn.execute(
            f"SELECT {select_columns} FROM {config.tables.categories} ORDER BY name COLLATE NOCASE"
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
                value = size["name"]
                if module == "vehicle_inventory":
                    value = _normalize_view_name(value)
                sizes_map.setdefault(size["category_id"], []).append(value)

        view_configs_map: dict[int, list[models.VehicleViewConfig]] | None = None
        if module == "vehicle_inventory":
            view_configs_map = {category_id: [] for category_id in category_ids}
            settings_map = _collect_vehicle_view_settings(conn, category_ids)
            for category_id in category_ids:
                view_names = sizes_map.get(category_id, [])
                if not view_names:
                    view_names = [DEFAULT_VEHICLE_VIEW_NAME]
                configs: list[models.VehicleViewConfig] = []
                stored_settings = settings_map.get(category_id, {})
                for view_name in view_names:
                    key = _view_settings_key(view_name)
                    stored = stored_settings.get(key)
                    if stored is not None:
                        configs.append(
                            models.VehicleViewConfig(
                                name=_normalize_view_name(view_name),
                                background_photo_id=stored.background_photo_id,
                                background_url=stored.background_url,
                            )
                        )
                    else:
                        configs.append(
                            models.VehicleViewConfig(name=_normalize_view_name(view_name))
                        )
                view_configs_map[category_id] = configs

        categories: list[models.Category] = []
        for row in rows:
            category_id = row["id"]
            sizes = sizes_map.get(category_id, [])
            if module != "vehicle_inventory":
                category_view_configs = None
            else:
                category_view_configs = view_configs_map.get(category_id, []) if view_configs_map else []
            image_url = None
            if module == "vehicle_inventory" and "image_path" in row.keys():
                image_url = _build_media_url(row["image_path"])
            categories.append(
                models.Category(
                    id=category_id,
                    name=row["name"],
                    sizes=sizes,
                    view_configs=category_view_configs,
                    image_url=image_url,
                    vehicle_type=row["vehicle_type"] if module == "vehicle_inventory" else None,
                )
            )
        return categories


def _get_inventory_category_internal(
    module: str, category_id: int
) -> Optional[models.Category]:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        if module == "vehicle_inventory":
            _ensure_vehicle_category_columns(conn)
        select_columns = "id, name"
        if module == "vehicle_inventory":
            select_columns += ", image_path, vehicle_type"
        cur = conn.execute(
            f"SELECT {select_columns} FROM {config.tables.categories} WHERE id = ?",
            (category_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        size_rows = conn.execute(
            f"SELECT name FROM {config.tables.category_sizes} WHERE category_id = ? ORDER BY name COLLATE NOCASE",
            (category_id,),
        ).fetchall()
        sizes = [size_row["name"] for size_row in size_rows]
        view_configs: list[models.VehicleViewConfig] | None = None
        if module == "vehicle_inventory":
            sizes = [_normalize_view_name(name) for name in sizes]
            view_names = sizes if sizes else [DEFAULT_VEHICLE_VIEW_NAME]
            settings_map = _collect_vehicle_view_settings(conn, [category_id])
            stored_settings = settings_map.get(category_id, {})
            view_configs = []
            for view_name in view_names:
                key = _view_settings_key(view_name)
                stored = stored_settings.get(key)
                if stored is not None:
                    view_configs.append(
                        models.VehicleViewConfig(
                            name=_normalize_view_name(view_name),
                            background_photo_id=stored.background_photo_id,
                            background_url=stored.background_url,
                        )
                    )
                else:
                    view_configs.append(
                        models.VehicleViewConfig(name=_normalize_view_name(view_name))
                    )
        image_url = None
        if "image_path" in row.keys():
            image_url = _build_media_url(row["image_path"])
        return models.Category(
            id=row["id"],
            name=row["name"],
            sizes=sizes,
            view_configs=view_configs,
            image_url=image_url,
            vehicle_type=row["vehicle_type"] if module == "vehicle_inventory" else None,
        )


def _create_inventory_category_internal(
    module: str, payload: models.CategoryCreate
) -> models.Category:
    ensure_database_ready()
    config = _get_inventory_config(module)
    normalized_sizes = _normalize_sizes(payload.sizes)
    with db.get_stock_connection() as conn:
        columns = ["name"]
        values: list[object] = [payload.name]
        if module == "vehicle_inventory":
            _ensure_vehicle_category_columns(conn)
            columns.append("vehicle_type")
            values.append(payload.vehicle_type)
        cur = conn.execute(
            f"INSERT INTO {config.tables.categories} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            values,
        )
        category_id = cur.lastrowid
        if normalized_sizes:
            conn.executemany(
                f"INSERT INTO {config.tables.category_sizes} (category_id, name) VALUES (?, ?)",
                ((category_id, size) for size in normalized_sizes),
            )
        _persist_after_commit(conn, *_inventory_modules_to_persist(module))
    created = _get_inventory_category_internal(module, category_id)
    if created is None:  # pragma: no cover - defensive programming
        raise ValueError("Catégorie introuvable")
    return created


def _update_inventory_category_internal(
    module: str, category_id: int, payload: models.CategoryUpdate
) -> models.Category:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        if module == "vehicle_inventory":
            _ensure_vehicle_category_columns(conn)
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
        if module == "vehicle_inventory" and payload.vehicle_type is not None:
            updates.append("vehicle_type = ?")
            values.append(payload.vehicle_type)
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
            if module == "vehicle_inventory":
                keep_names = normalized_sizes if normalized_sizes else [DEFAULT_VEHICLE_VIEW_NAME]
                normalized_keep = [_normalize_view_name(name) for name in keep_names]
                if normalized_keep:
                    placeholders = ",".join("?" for _ in normalized_keep)
                    conn.execute(
                        f"""
                        DELETE FROM vehicle_view_settings
                        WHERE category_id = ? AND name NOT IN ({placeholders})
                        """,
                        (category_id, *normalized_keep),
                    )
                else:
                    conn.execute(
                        "DELETE FROM vehicle_view_settings WHERE category_id = ?",
                        (category_id,),
                    )
        _persist_after_commit(conn, *_inventory_modules_to_persist(module))

    updated = _get_inventory_category_internal(module, category_id)
    if updated is None:  # pragma: no cover - deleted row in concurrent context
        raise ValueError("Catégorie introuvable")
    return updated


def _delete_inventory_category_internal(module: str, category_id: int) -> None:
    ensure_database_ready()
    config = _get_inventory_config(module)
    with db.get_stock_connection() as conn:
        previous_path: str | None = None
        if module == "vehicle_inventory":
            cur = conn.execute(
                f"SELECT image_path FROM {config.tables.categories} WHERE id = ?",
                (category_id,),
            )
            row = cur.fetchone()
            if row:
                previous_path = row["image_path"]
        conn.execute(
            f"DELETE FROM {config.tables.category_sizes} WHERE category_id = ?",
            (category_id,),
        )
        conn.execute(
            f"DELETE FROM {config.tables.categories} WHERE id = ?",
            (category_id,),
        )
        _persist_after_commit(conn, *_inventory_modules_to_persist(module))
    if previous_path:
        _delete_media_file(previous_path)


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
        _persist_after_commit(conn, *_inventory_modules_to_persist(module))


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
    items = _list_inventory_items_internal("vehicle_inventory", search)
    for item in items:
        if item.category_id is None:
            item.qr_token = None
    return items


def _ensure_vehicle_pharmacy_templates() -> None:
    """Ensure pharmacy items are visible in the vehicle library."""

    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_vehicle_item_columns(conn)
        missing_templates = conn.execute(
            """
            SELECT pi.id AS pharmacy_item_id
            FROM pharmacy_items AS pi
            WHERE NOT EXISTS (
                SELECT 1
                FROM vehicle_items AS vi
                WHERE vi.pharmacy_item_id = pi.id AND vi.category_id IS NULL
            )
            ORDER BY pi.id
            """
        ).fetchall()

        for row in missing_templates:
            _create_inventory_item_internal(
                "vehicle_inventory",
                models.ItemCreate(
                    name=f"Pharmacie-{row['pharmacy_item_id']}",
                    sku=f"PHARM-{row['pharmacy_item_id']}",
                    quantity=0,
                    pharmacy_item_id=row["pharmacy_item_id"],
                    vehicle_type="secours_a_personne",
                ),
            )


def create_vehicle_item(payload: models.ItemCreate) -> models.Item:
    return _create_inventory_item_internal("vehicle_inventory", payload)


def assign_vehicle_item_from_remise(
    payload: models.VehicleAssignmentFromRemise,
) -> models.Item:
    category = get_vehicle_category(payload.category_id)
    if category is None:
        raise ValueError("Catégorie de véhicule introuvable")
    target_view = payload.target_view.strip()
    if not target_view:
        raise ValueError("Vehicle item created without view (size)")
    vehicle_type = payload.vehicle_type or category.vehicle_type
    if category.vehicle_type and payload.vehicle_type and payload.vehicle_type != category.vehicle_type:
        raise ValueError("Le type de véhicule ne correspond pas à la catégorie ciblée.")

    logger.info(
        "[VEHICLE_INVENTORY] Assignation remise -> véhicule",
        extra={
            "remise_item_id": payload.remise_item_id,
            "vehicle_category_id": payload.category_id,
            "vehicle_type": vehicle_type,
            "target_view": target_view,
            "quantity": payload.quantity,
        },
    )

    assignment_payload = models.ItemCreate(
        name="",  # The source name will be applied during creation
        sku="",  # The source SKU will be applied during creation
        category_id=payload.category_id,
        size=target_view,
        quantity=payload.quantity,
        low_stock_threshold=0,
        track_low_stock=True,
        supplier_id=None,
        expiration_date=None,
        position_x=payload.position.x,
        position_y=payload.position.y,
        remise_item_id=payload.remise_item_id,
        pharmacy_item_id=None,
        shared_file_url=None,
        documentation_url=None,
        tutorial_url=None,
        lot_id=None,
        show_in_qr=True,
        vehicle_type=vehicle_type,
    )

    created_item = _create_inventory_item_internal("vehicle_inventory", assignment_payload)
    if not created_item.size:
        raise ValueError("Vehicle item created without view (size)")
    return created_item


def get_vehicle_item(item_id: int) -> models.Item:
    item = _get_inventory_item_internal("vehicle_inventory", item_id)
    if item.category_id is None:
        item.qr_token = None
    return item


def update_vehicle_item(item_id: int, payload: models.ItemUpdate) -> models.Item:
    return _update_inventory_item_internal("vehicle_inventory", item_id, payload)


def delete_vehicle_item(item_id: int) -> bool:
    ensure_database_ready()
    config = _get_inventory_config("vehicle_inventory")
    try:
        with db.get_stock_connection() as conn:
            _ensure_vehicle_item_columns(conn)
            total_count = conn.execute(
                f"SELECT COUNT(*) as n FROM {config.tables.items}"
            ).fetchone()
            existence = conn.execute(
                f"SELECT id FROM {config.tables.items} WHERE id = ?",
                (item_id,),
            ).fetchone()
            logger.info(
                "[VEHICLE_INVENTORY] Delete lookup pid=%s db=%s item_id=%s vehicle_items_count=%s exists=%s",
                os.getpid(),
                db.STOCK_DB_PATH.resolve(),
                item_id,
                total_count["n"] if total_count else None,
                None if existence is None else existence["id"],
            )
            row = conn.execute(
                f"""
                SELECT id,
                       name,
                       sku,
                       quantity,
                       size,
                       vehicle_type,
                       low_stock_threshold,
                       position_x,
                       position_y,
                       remise_item_id,
                       pharmacy_item_id,
                        image_path,
                       lot_id,
                       category_id
                FROM {config.tables.items}
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Article introuvable")
            row = dict(row)
            safe_snapshot = {
                "id": row.get("id"),
                "name": row.get("name"),
                "category_id": row.get("category_id"),
                "vehicle_type": row.get("vehicle_type"),
                "size": row.get("size"),
                "quantity": row.get("quantity"),
                "position_x": row.get("position_x"),
                "position_y": row.get("position_y"),
            }
            logger.info(
                "[VEHICLE_INVENTORY] Delete row snapshot %s",
                safe_snapshot,
            )
            if row["lot_id"]:
                raise ValueError(
                    "Impossible de supprimer ce matériel depuis l'inventaire véhicules : il est rattaché à un lot."
                )

            quantity = row["quantity"] or 0
            if quantity <= 0:
                if row["category_id"] is None:
                    logger.info(
                        "[VEHICLE_INVENTORY] Delete step=delete-vehicle-item-zero-quantity id=%s",
                        item_id,
                    )
                    delete_cursor = conn.execute(
                        f"DELETE FROM {config.tables.items} WHERE id = ?",
                        (item_id,),
                    )
                    logger.info(
                        "[VEHICLE_INVENTORY] Delete rowcount step=delete-vehicle-item-zero-quantity id=%s rowcount=%s",
                        item_id,
                        delete_cursor.rowcount,
                    )
                    image_path = row["image_path"]
                    if image_path:
                        _delete_media_file(image_path)
                    _persist_after_commit(
                        conn, *_inventory_modules_to_persist("vehicle_inventory")
                    )
                    return True
                raise ValueError(
                    "Impossible de restituer ce matériel : la quantité en véhicule est nulle."
                )

            if row["remise_item_id"] is not None:
                logger.info(
                    "[VEHICLE_INVENTORY] Delete step=update-remise-quantity id=%s remise_item_id=%s delta=%s",
                    item_id,
                    row["remise_item_id"],
                    quantity,
                )
                _update_remise_quantity(conn, row["remise_item_id"], quantity)
            elif row["pharmacy_item_id"] is not None:
                pharmacy_item_id = resolve_or_create_pharmacy_item(conn, row)
                logger.info(
                    "[VEHICLE_INVENTORY] Delete step=update-pharmacy-quantity id=%s pharmacy_item_id=%s delta=%s",
                    item_id,
                    pharmacy_item_id,
                    quantity,
                )
                updated = _update_pharmacy_quantity(conn, pharmacy_item_id, quantity)
                if not updated:
                    raise RuntimeError(
                        "Echec de restitution : article pharmacie introuvable après résolution."
                    )

            logger.info(
                "[VEHICLE_INVENTORY] Delete step=delete-vehicle-item id=%s",
                item_id,
            )
            delete_cursor = conn.execute(
                f"DELETE FROM {config.tables.items} WHERE id = ?",
                (item_id,),
            )
            logger.info(
                "[VEHICLE_INVENTORY] Delete rowcount step=delete-vehicle-item id=%s rowcount=%s",
                item_id,
                delete_cursor.rowcount,
            )
            image_path = row["image_path"]
            if image_path:
                _delete_media_file(image_path)
            _persist_after_commit(
                conn, *_inventory_modules_to_persist("vehicle_inventory")
            )
    except Exception:
        logger.exception("[VEHICLE_INVENTORY] Delete failed id=%s", item_id)
        raise

    logger.info(
        "[VEHICLE_INVENTORY] Restitution véhicule -> remise",
        extra={
            "vehicle_item_id": item_id,
            "remise_item_id": row["remise_item_id"],
            "pharmacy_item_id": row["pharmacy_item_id"],
            "quantity": quantity,
        },
    )
    return True


def list_remise_items(search: str | None = None) -> list[models.Item]:
    return _list_inventory_items_internal("inventory_remise", search)


def attach_vehicle_item_image(item_id: int, stream: BinaryIO, filename: str | None) -> models.Item:
    ensure_database_ready()
    config = _get_inventory_config("vehicle_inventory")
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT image_path FROM {config.tables.items} WHERE id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        previous_path = row["image_path"]
        stored_path = _store_media_file(VEHICLE_ITEM_MEDIA_DIR, stream, filename)
        conn.execute(
            f"UPDATE {config.tables.items} SET image_path = ? WHERE id = ?",
            (stored_path, item_id),
        )
        _persist_after_commit(conn, "vehicle_inventory")
    if previous_path and previous_path != stored_path:
        _delete_media_file(previous_path)
    return _get_inventory_item_internal("vehicle_inventory", item_id)


def remove_vehicle_item_image(item_id: int) -> models.Item:
    ensure_database_ready()
    config = _get_inventory_config("vehicle_inventory")
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT image_path FROM {config.tables.items} WHERE id = ?",
            (item_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        previous_path = row["image_path"]
        conn.execute(
            f"UPDATE {config.tables.items} SET image_path = NULL WHERE id = ?",
            (item_id,),
        )
        _persist_after_commit(conn, "vehicle_inventory")
    if previous_path:
        _delete_media_file(previous_path)
    return _get_inventory_item_internal("vehicle_inventory", item_id)


def attach_vehicle_category_image(
    category_id: int, stream: BinaryIO, filename: str | None
) -> models.Category:
    ensure_database_ready()
    config = _get_inventory_config("vehicle_inventory")
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT image_path FROM {config.tables.categories} WHERE id = ?",
            (category_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Catégorie introuvable")
        previous_path = row["image_path"]
        stored_path = _store_media_file(VEHICLE_CATEGORY_MEDIA_DIR, stream, filename)
        conn.execute(
            f"UPDATE {config.tables.categories} SET image_path = ? WHERE id = ?",
            (stored_path, category_id),
        )
        conn.commit()
    if previous_path and previous_path != stored_path:
        _delete_media_file(previous_path)
    updated = _get_inventory_category_internal("vehicle_inventory", category_id)
    if updated is None:  # pragma: no cover - deleted row in concurrent context
        raise ValueError("Catégorie introuvable")
    return updated


def remove_vehicle_category_image(category_id: int) -> models.Category:
    ensure_database_ready()
    config = _get_inventory_config("vehicle_inventory")
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"SELECT image_path FROM {config.tables.categories} WHERE id = ?",
            (category_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Catégorie introuvable")
        previous_path = row["image_path"]
        if not previous_path:
            updated = _get_inventory_category_internal("vehicle_inventory", category_id)
            if updated is None:  # pragma: no cover - deleted row in concurrent context
                raise ValueError("Catégorie introuvable")
            return updated
        conn.execute(
            f"UPDATE {config.tables.categories} SET image_path = NULL WHERE id = ?",
            (category_id,),
        )
        conn.commit()
    _delete_media_file(previous_path)
    updated = _get_inventory_category_internal("vehicle_inventory", category_id)
    if updated is None:  # pragma: no cover - deleted row in concurrent context
        raise ValueError("Catégorie introuvable")
    return updated


def list_vehicle_photos() -> list[models.VehiclePhoto]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT id, file_path, uploaded_at FROM vehicle_photos ORDER BY uploaded_at DESC"
        )
        rows = cur.fetchall()
    return [
        models.VehiclePhoto(
            id=row["id"],
            image_url=_build_media_url(row["file_path"]),
            uploaded_at=_coerce_datetime(row["uploaded_at"]),
        )
        for row in rows
    ]


def add_vehicle_photo(stream: BinaryIO, filename: str | None) -> models.VehiclePhoto:
    ensure_database_ready()
    stored_path = _store_media_file(VEHICLE_PHOTO_MEDIA_DIR, stream, filename)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "INSERT INTO vehicle_photos (file_path) VALUES (?)",
            (stored_path,),
        )
        photo_id = cur.lastrowid
        conn.commit()
    return get_vehicle_photo(photo_id)


def get_vehicle_photo(photo_id: int) -> models.VehiclePhoto:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT id, file_path, uploaded_at FROM vehicle_photos WHERE id = ?",
            (photo_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError("Photo introuvable")
    return models.VehiclePhoto(
        id=row["id"],
        image_url=_build_media_url(row["file_path"]),
        uploaded_at=_coerce_datetime(row["uploaded_at"]),
    )


def delete_vehicle_photo(photo_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT file_path FROM vehicle_photos WHERE id = ?",
            (photo_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Photo introuvable")
        conn.execute("DELETE FROM vehicle_photos WHERE id = ?", (photo_id,))
        conn.commit()
    _delete_media_file(row["file_path"])


def create_remise_item(payload: models.ItemCreate) -> models.Item:
    created = _create_inventory_item_internal("inventory_remise", payload)
    _sync_single_vehicle_item(created.id)
    return created


def get_remise_item(item_id: int) -> models.Item:
    return _get_inventory_item_internal("inventory_remise", item_id)


def update_remise_item(item_id: int, payload: models.ItemUpdate) -> models.Item:
    updated = _update_inventory_item_internal("inventory_remise", item_id, payload)
    _sync_single_vehicle_item(updated.id)
    return updated


def delete_remise_item(item_id: int) -> None:
    _delete_inventory_item_internal("inventory_remise", item_id)
    _sync_single_vehicle_item(item_id)


def update_vehicle_view_background(
    category_id: int, payload: models.VehicleViewBackgroundUpdate
) -> models.VehicleViewConfig:
    ensure_database_ready()
    normalized_name = _normalize_view_name(payload.name)
    with db.get_stock_connection() as conn:
        category_row = conn.execute(
            "SELECT id FROM vehicle_categories WHERE id = ?",
            (category_id,),
        ).fetchone()
        if category_row is None:
            raise ValueError("Véhicule introuvable")
        view_exists = conn.execute(
            "SELECT 1 FROM vehicle_category_sizes WHERE category_id = ? AND name = ?",
            (category_id, normalized_name),
        ).fetchone()
        if view_exists is None and normalized_name != DEFAULT_VEHICLE_VIEW_NAME:
            raise ValueError("Vue introuvable")
        if payload.photo_id is not None:
            photo_row = conn.execute(
                "SELECT id FROM vehicle_photos WHERE id = ?",
                (payload.photo_id,),
            ).fetchone()
            if photo_row is None:
                raise ValueError("Photo introuvable")
        conn.execute(
            """
            INSERT INTO vehicle_view_settings (category_id, name, background_photo_id)
            VALUES (?, ?, ?)
            ON CONFLICT(category_id, name)
            DO UPDATE SET background_photo_id = excluded.background_photo_id
            """,
            (category_id, normalized_name, payload.photo_id),
        )
        conn.commit()
    return _get_vehicle_view_config(category_id, normalized_name)


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


def _normalize_view_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed:
        raise ValueError("Le nom de la vue est obligatoire")
    return trimmed.upper()


def _view_settings_key(name: str) -> str:
    return _normalize_view_name(name).casefold()


def _build_vehicle_view_config(
    name: str,
    background_photo_id: int | None,
    file_path: str | None,
    *,
    pointer_mode_enabled: bool = False,
    hide_edit_buttons: bool = False,
) -> models.VehicleViewConfig:
    normalized = _normalize_view_name(name)
    return models.VehicleViewConfig(
        name=normalized,
        background_photo_id=background_photo_id,
        background_url=_build_media_url(file_path) if background_photo_id else None,
        pointer_mode_enabled=pointer_mode_enabled,
        hide_edit_buttons=hide_edit_buttons,
    )


def _collect_vehicle_view_settings(
    conn: sqlite3.Connection, category_ids: list[int]
) -> dict[int, dict[str, models.VehicleViewConfig]]:
    if not category_ids:
        return {}
    placeholders = ",".join("?" for _ in category_ids)
    rows = conn.execute(
        f"""
        SELECT
            vvs.category_id,
            vvs.name,
            vvs.background_photo_id,
            vvs.pointer_mode_enabled,
            vvs.hide_edit_buttons,
            vp.file_path
        FROM vehicle_view_settings AS vvs
        LEFT JOIN vehicle_photos AS vp ON vp.id = vvs.background_photo_id
        WHERE vvs.category_id IN ({placeholders})
        """,
        category_ids,
    ).fetchall()
    settings: dict[int, dict[str, models.VehicleViewConfig]] = {}
    for row in rows:
        config = _build_vehicle_view_config(
            row["name"],
            row["background_photo_id"],
            row["file_path"],
            pointer_mode_enabled=bool(row["pointer_mode_enabled"]),
            hide_edit_buttons=bool(row["hide_edit_buttons"]),
        )
        settings.setdefault(row["category_id"], {})[_view_settings_key(config.name)] = config
    return settings


def _get_vehicle_view_config(
    category_id: int, name: str
) -> models.VehicleViewConfig:
    normalized = _normalize_view_name(name)
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT
                vvs.name,
                vvs.background_photo_id,
                vvs.pointer_mode_enabled,
                vvs.hide_edit_buttons,
                vp.file_path
            FROM vehicle_view_settings AS vvs
            LEFT JOIN vehicle_photos AS vp ON vp.id = vvs.background_photo_id
            WHERE vvs.category_id = ? AND vvs.name = ?
            """,
            (category_id, normalized),
        ).fetchone()
    if row is None:
        return models.VehicleViewConfig(name=normalized)
    return _build_vehicle_view_config(
        row["name"],
        row["background_photo_id"],
        row["file_path"],
        pointer_mode_enabled=bool(row["pointer_mode_enabled"]),
        hide_edit_buttons=bool(row["hide_edit_buttons"]),
    )


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


def get_vehicle_item_qr_token(item_id: int, *, regenerate: bool = False) -> str:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_vehicle_item_qr_tokens(conn)
        row = conn.execute(
            "SELECT qr_token, category_id FROM vehicle_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        if row["category_id"] is None:
            raise ValueError(
                "Les QR codes ne peuvent être générés que pour le matériel déjà affecté à un véhicule."
            )
        token = row["qr_token"]
        if regenerate or not token:
            token = uuid4().hex
            conn.execute(
                "UPDATE vehicle_items SET qr_token = ? WHERE id = ?",
                (token, item_id),
            )
            _persist_after_commit(conn, "vehicle_inventory")
        return token


def get_vehicle_item_public_info(qr_token: str) -> models.VehicleQrInfo:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_vehicle_item_qr_tokens(conn)
        _ensure_vehicle_item_columns(conn)
        row = conn.execute(
            """
            SELECT vi.id,
                   COALESCE(ri.name, vi.name) AS name,
                   COALESCE(ri.sku, vi.sku) AS sku,
                   vi.documentation_url,
                   vi.tutorial_url,
                   vi.shared_file_url,
                   vi.image_path,
                   vc.name AS category_name,
                   vi.show_in_qr
            FROM vehicle_items AS vi
            LEFT JOIN remise_items AS ri ON ri.id = vi.remise_item_id
            LEFT JOIN vehicle_categories AS vc ON vc.id = vi.category_id
            WHERE vi.qr_token = ?
            """,
            (qr_token,),
        ).fetchone()
    if row is None:
        raise ValueError("QR code invalide ou expiré")
    if "show_in_qr" in row.keys() and not row["show_in_qr"]:
        raise ValueError("Ce matériel a été masqué pour le QR code.")
    image_url = _build_media_url(row["image_path"]) if "image_path" in row.keys() else None
    return models.VehicleQrInfo(
        item_id=row["id"],
        name=row["name"],
        sku=row["sku"],
        category_name=row["category_name"],
        image_url=image_url,
        shared_file_url=row["shared_file_url"] if "shared_file_url" in row.keys() else None,
        documentation_url=row["documentation_url"] if "documentation_url" in row.keys() else None,
        tutorial_url=row["tutorial_url"] if "tutorial_url" in row.keys() else None,
    )


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


def _build_remise_lot(row: sqlite3.Row) -> models.RemiseLot:
    return models.RemiseLot(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        created_at=_coerce_datetime(row["created_at"]),
        image_url=_build_media_url(row["image_path"]),
        item_count=row["item_count"],
        total_quantity=row["total_quantity"],
    )


def _require_remise_lot(conn: sqlite3.Connection, lot_id: int) -> None:
    exists = conn.execute("SELECT 1 FROM remise_lots WHERE id = ?", (lot_id,)).fetchone()
    if exists is None:
        raise ValueError("Lot introuvable")


def list_remise_lots() -> list[models.RemiseLot]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        rows = conn.execute(
            """
            SELECT rl.id, rl.name, rl.description, rl.created_at, rl.image_path,
                   COUNT(rli.id) AS item_count,
                   COALESCE(SUM(rli.quantity), 0) AS total_quantity
            FROM remise_lots AS rl
            LEFT JOIN remise_lot_items AS rli ON rli.lot_id = rl.id
            GROUP BY rl.id
            ORDER BY rl.created_at DESC, rl.name
            """
        ).fetchall()
    return [_build_remise_lot(row) for row in rows]


def get_remise_lot(lot_id: int) -> models.RemiseLot:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT rl.id, rl.name, rl.description, rl.created_at, rl.image_path,
                   COUNT(rli.id) AS item_count,
                   COALESCE(SUM(rli.quantity), 0) AS total_quantity
            FROM remise_lots AS rl
            LEFT JOIN remise_lot_items AS rli ON rli.lot_id = rl.id
            WHERE rl.id = ?
            GROUP BY rl.id
            """,
            (lot_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Lot introuvable")
    return _build_remise_lot(row)


def list_remise_lots_with_items() -> list[models.RemiseLotWithItems]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        lot_rows = conn.execute(
            """
            SELECT rl.id, rl.name, rl.description, rl.created_at, rl.image_path,
                   COUNT(rli.id) AS item_count,
                   COALESCE(SUM(rli.quantity), 0) AS total_quantity
            FROM remise_lots AS rl
            LEFT JOIN remise_lot_items AS rli ON rli.lot_id = rl.id
            GROUP BY rl.id
            ORDER BY rl.created_at DESC, rl.name
            """
        ).fetchall()

        if not lot_rows:
            return []

        lot_ids = [row["id"] for row in lot_rows]
        placeholders = ",".join("?" for _ in lot_ids)
        item_rows = conn.execute(
            f"""
            SELECT rli.id, rli.lot_id, rli.remise_item_id, rli.quantity,
                   ri.name AS remise_name, ri.sku AS remise_sku, ri.size AS size, ri.quantity AS available_quantity
            FROM remise_lot_items AS rli
            JOIN remise_items AS ri ON ri.id = rli.remise_item_id
            WHERE rli.lot_id IN ({placeholders})
            ORDER BY rli.lot_id, ri.name
            """,
            lot_ids,
        ).fetchall()

    items_by_lot: dict[int, list[models.RemiseLotItem]] = defaultdict(list)
    for row in item_rows:
        items_by_lot[row["lot_id"]].append(_build_remise_lot_item(row))

    lots: list[models.RemiseLotWithItems] = []
    for row in lot_rows:
        lot_model = _build_remise_lot(row)
        lots.append(
            models.RemiseLotWithItems(
                **lot_model.model_dump(),
                items=items_by_lot.get(lot_model.id, []),
            )
        )

    return lots


def create_remise_lot(payload: models.RemiseLotCreate) -> models.RemiseLot:
    ensure_database_ready()
    description = payload.description.strip() if payload.description else None
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "INSERT INTO remise_lots (name, description) VALUES (?, ?)",
            (payload.name.strip(), description),
        )
        lot_id = cur.lastrowid
        _persist_after_commit(conn)
    return get_remise_lot(lot_id)


def update_remise_lot(lot_id: int, payload: models.RemiseLotUpdate) -> models.RemiseLot:
    ensure_database_ready()
    assignments: list[str] = []
    values: list[object] = []
    if payload.name is not None:
        assignments.append("name = ?")
        values.append(payload.name.strip())
    if payload.description is not None:
        assignments.append("description = ?")
        values.append(payload.description.strip() or None)
    if not assignments:
        return get_remise_lot(lot_id)

    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"UPDATE remise_lots SET {', '.join(assignments)} WHERE id = ?",
            (*values, lot_id),
        )
        if cur.rowcount == 0:
            raise ValueError("Lot introuvable")
        _persist_after_commit(conn)
    return get_remise_lot(lot_id)


def attach_remise_lot_image(
    lot_id: int, stream: BinaryIO, filename: str | None
) -> models.RemiseLot:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_remise_lot_columns(conn)
        row = conn.execute(
            "SELECT image_path FROM remise_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Lot introuvable")
        previous_path = row["image_path"]
        stored_path = _store_media_file(REMISE_LOT_MEDIA_DIR, stream, filename)
        conn.execute(
            "UPDATE remise_lots SET image_path = ? WHERE id = ?",
            (stored_path, lot_id),
        )
        _persist_after_commit(conn)
    if previous_path and previous_path != stored_path:
        _delete_media_file(previous_path)
    return get_remise_lot(lot_id)


def remove_remise_lot_image(lot_id: int) -> models.RemiseLot:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT image_path FROM remise_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Lot introuvable")
        previous_path = row["image_path"]
        if not previous_path:
            return get_remise_lot(lot_id)
        conn.execute(
            "UPDATE remise_lots SET image_path = NULL WHERE id = ?",
            (lot_id,),
        )
        _persist_after_commit(conn)
    _delete_media_file(previous_path)
    return get_remise_lot(lot_id)


def delete_remise_lot(lot_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT image_path FROM remise_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Lot introuvable")
        image_path = row["image_path"]
        _ensure_vehicle_item_columns(conn)
        conn.execute("UPDATE vehicle_items SET lot_id = NULL WHERE lot_id = ?", (lot_id,))
        conn.execute("DELETE FROM remise_lot_items WHERE lot_id = ?", (lot_id,))
        conn.execute("DELETE FROM remise_lots WHERE id = ?", (lot_id,))
        _persist_after_commit(conn)
    _delete_media_file(image_path)


def _build_remise_lot_item(row: sqlite3.Row) -> models.RemiseLotItem:
    return models.RemiseLotItem(
        id=row["id"],
        lot_id=row["lot_id"],
        remise_item_id=row["remise_item_id"],
        quantity=row["quantity"],
        remise_name=row["remise_name"],
        remise_sku=row["remise_sku"],
        size=row["size"],
        available_quantity=row["available_quantity"],
    )


def _get_remise_lot_item(
    conn: sqlite3.Connection, lot_id: int, lot_item_id: int
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT rli.id, rli.lot_id, rli.remise_item_id, rli.quantity,
               ri.name AS remise_name, ri.sku AS remise_sku, ri.size AS size, ri.quantity AS available_quantity
        FROM remise_lot_items AS rli
        JOIN remise_items AS ri ON ri.id = rli.remise_item_id
        WHERE rli.id = ? AND rli.lot_id = ?
        """,
        (lot_item_id, lot_id),
    ).fetchone()
    if row is None:
        raise ValueError("Affectation introuvable")
    return row


def _ensure_lot_reservation_capacity(
    conn: sqlite3.Connection,
    remise_item_id: int,
    requested_quantity: int,
    *,
    exclude_lot_item_id: int | None = None,
) -> None:
    item_row = conn.execute(
        "SELECT quantity FROM remise_items WHERE id = ?",
        (remise_item_id,),
    ).fetchone()
    if item_row is None:
        raise ValueError("Article de remise introuvable")

    query = "SELECT COALESCE(SUM(quantity), 0) AS reserved FROM remise_lot_items WHERE remise_item_id = ?"
    params: list[object] = [remise_item_id]
    if exclude_lot_item_id is not None:
        query += " AND id != ?"
        params.append(exclude_lot_item_id)

    reserved_row = conn.execute(query, params).fetchone()
    reserved_quantity = 0
    if reserved_row is not None:
        if isinstance(reserved_row, sqlite3.Row):
            reserved_quantity = reserved_row["reserved"]
        else:
            reserved_quantity = reserved_row[0]
    available = item_row["quantity"] - reserved_quantity
    if requested_quantity > available:
        raise ValueError("Stock insuffisant en remise pour cette affectation.")


def list_remise_lot_items(lot_id: int) -> list[models.RemiseLotItem]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _require_remise_lot(conn, lot_id)
        rows = conn.execute(
            """
            SELECT rli.id, rli.lot_id, rli.remise_item_id, rli.quantity,
                   ri.name AS remise_name, ri.sku AS remise_sku, ri.size AS size, ri.quantity AS available_quantity
            FROM remise_lot_items AS rli
            JOIN remise_items AS ri ON ri.id = rli.remise_item_id
            WHERE rli.lot_id = ?
            ORDER BY ri.name
            """,
            (lot_id,),
        ).fetchall()
    return [_build_remise_lot_item(row) for row in rows]


def add_remise_lot_item(
    lot_id: int, payload: models.RemiseLotItemBase
) -> models.RemiseLotItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _require_remise_lot(conn, lot_id)
        existing = conn.execute(
            """
            SELECT id, quantity
            FROM remise_lot_items
            WHERE lot_id = ? AND remise_item_id = ?
            """,
            (lot_id, payload.remise_item_id),
        ).fetchone()
        if existing:
            new_quantity = existing["quantity"] + payload.quantity
            _ensure_lot_reservation_capacity(
                conn,
                payload.remise_item_id,
                new_quantity,
                exclude_lot_item_id=existing["id"],
            )
            conn.execute(
                "UPDATE remise_lot_items SET quantity = ? WHERE id = ?",
                (new_quantity, existing["id"]),
            )
            lot_item_id = existing["id"]
        else:
            _ensure_lot_reservation_capacity(conn, payload.remise_item_id, payload.quantity)
            cur = conn.execute(
                "INSERT INTO remise_lot_items (lot_id, remise_item_id, quantity) VALUES (?, ?, ?)",
                (lot_id, payload.remise_item_id, payload.quantity),
            )
            lot_item_id = cur.lastrowid
        _persist_after_commit(conn)
    with db.get_stock_connection() as conn:
        row = _get_remise_lot_item(conn, lot_id, lot_item_id)
    return _build_remise_lot_item(row)


def update_remise_lot_item(
    lot_id: int, lot_item_id: int, payload: models.RemiseLotItemUpdate
) -> models.RemiseLotItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = _get_remise_lot_item(conn, lot_id, lot_item_id)
        target_quantity = payload.quantity if payload.quantity is not None else row["quantity"]
        _ensure_lot_reservation_capacity(
            conn,
            row["remise_item_id"],
            target_quantity,
            exclude_lot_item_id=lot_item_id,
        )
        if target_quantity != row["quantity"]:
            conn.execute(
                "UPDATE remise_lot_items SET quantity = ? WHERE id = ?",
                (target_quantity, lot_item_id),
            )
        _persist_after_commit(conn)
    with db.get_stock_connection() as conn:
        updated_row = _get_remise_lot_item(conn, lot_id, lot_item_id)
    return _build_remise_lot_item(updated_row)


def remove_remise_lot_item(lot_id: int, lot_item_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _get_remise_lot_item(conn, lot_id, lot_item_id)
        conn.execute(
            "DELETE FROM remise_lot_items WHERE id = ? AND lot_id = ?",
            (lot_item_id, lot_id),
        )
        _persist_after_commit(conn)


def _build_pharmacy_lot(row: sqlite3.Row) -> models.PharmacyLot:
    return models.PharmacyLot(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        created_at=row["created_at"],
        image_url=_build_media_url(row["image_path"]),
        item_count=row["item_count"],
        total_quantity=row["total_quantity"],
    )


def _require_pharmacy_lot(conn: sqlite3.Connection, lot_id: int) -> None:
    exists = conn.execute("SELECT 1 FROM pharmacy_lots WHERE id = ?", (lot_id,)).fetchone()
    if not exists:
        raise ValueError("Lot introuvable")


def list_pharmacy_lots() -> list[models.PharmacyLot]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        rows = conn.execute(
            """
            SELECT pl.id, pl.name, pl.description, pl.image_path, pl.created_at,
                   COUNT(pli.id) AS item_count, COALESCE(SUM(pli.quantity), 0) AS total_quantity
            FROM pharmacy_lots AS pl
            LEFT JOIN pharmacy_lot_items AS pli ON pli.lot_id = pl.id
            GROUP BY pl.id
            ORDER BY pl.created_at DESC
            """,
        ).fetchall()
    return [_build_pharmacy_lot(row) for row in rows]


def get_pharmacy_lot(lot_id: int) -> models.PharmacyLot:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT pl.id, pl.name, pl.description, pl.image_path, pl.created_at,
                   COUNT(pli.id) AS item_count, COALESCE(SUM(pli.quantity), 0) AS total_quantity
            FROM pharmacy_lots AS pl
            LEFT JOIN pharmacy_lot_items AS pli ON pli.lot_id = pl.id
            WHERE pl.id = ?
            GROUP BY pl.id
            """,
            (lot_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Lot introuvable")
    return _build_pharmacy_lot(row)


def list_pharmacy_lots_with_items() -> list[models.PharmacyLotWithItems]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        lot_rows = conn.execute(
            """
            SELECT pl.id, pl.name, pl.description, pl.image_path, pl.created_at,
                   COUNT(pli.id) AS item_count, COALESCE(SUM(pli.quantity), 0) AS total_quantity
            FROM pharmacy_lots AS pl
            LEFT JOIN pharmacy_lot_items AS pli ON pli.lot_id = pl.id
            GROUP BY pl.id
            ORDER BY pl.created_at DESC
            """,
        ).fetchall()

        if not lot_rows:
            return []

        lot_ids = [row["id"] for row in lot_rows]
        placeholders = ",".join("?" for _ in lot_ids)
        item_rows = conn.execute(
            f"""
            SELECT pli.id, pli.lot_id, pli.pharmacy_item_id, pli.quantity,
                   pi.name AS pharmacy_name, pi.barcode AS pharmacy_sku, pi.quantity AS available_quantity
            FROM pharmacy_lot_items AS pli
            JOIN pharmacy_items AS pi ON pi.id = pli.pharmacy_item_id
            WHERE pli.lot_id IN ({placeholders})
            ORDER BY pli.lot_id, pi.name
            """,
            lot_ids,
        ).fetchall()

    items_by_lot: dict[int, list[models.PharmacyLotItem]] = defaultdict(list)
    for row in item_rows:
        items_by_lot[row["lot_id"]].append(_build_pharmacy_lot_item(row))

    lots: list[models.PharmacyLotWithItems] = []
    for row in lot_rows:
        lot_model = _build_pharmacy_lot(row)
        lots.append(
            models.PharmacyLotWithItems(
                **lot_model.model_dump(),
                items=items_by_lot.get(lot_model.id, []),
            )
        )

    return lots


def create_pharmacy_lot(payload: models.PharmacyLotCreate) -> models.PharmacyLot:
    ensure_database_ready()
    description = payload.description.strip() if payload.description else None
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "INSERT INTO pharmacy_lots (name, description) VALUES (?, ?)",
            (payload.name.strip(), description),
        )
        lot_id = cur.lastrowid
        _persist_after_commit(conn, "pharmacy")
    return get_pharmacy_lot(lot_id)


def update_pharmacy_lot(lot_id: int, payload: models.PharmacyLotUpdate) -> models.PharmacyLot:
    ensure_database_ready()
    assignments: list[str] = []
    values: list[object] = []
    if payload.name is not None:
        assignments.append("name = ?")
        values.append(payload.name.strip())
    if payload.description is not None:
        assignments.append("description = ?")
        values.append(payload.description.strip() or None)
    if not assignments:
        return get_pharmacy_lot(lot_id)

    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"UPDATE pharmacy_lots SET {', '.join(assignments)} WHERE id = ?",
            (*values, lot_id),
        )
        if cur.rowcount == 0:
            raise ValueError("Lot introuvable")
        _persist_after_commit(conn, "pharmacy")
    return get_pharmacy_lot(lot_id)


def attach_pharmacy_lot_image(
    lot_id: int, stream: BinaryIO, filename: str | None
) -> models.PharmacyLot:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_pharmacy_lot_columns(conn)
        row = conn.execute(
            "SELECT image_path FROM pharmacy_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Lot introuvable")
        previous_path = row["image_path"]
        stored_path = _store_media_file(PHARMACY_LOT_MEDIA_DIR, stream, filename)
        conn.execute(
            "UPDATE pharmacy_lots SET image_path = ? WHERE id = ?",
            (stored_path, lot_id),
        )
        _persist_after_commit(conn, "pharmacy")

    if previous_path:
        try:
            (MEDIA_ROOT / previous_path).unlink()
        except FileNotFoundError:
            pass
    return get_pharmacy_lot(lot_id)


def remove_pharmacy_lot_image(lot_id: int) -> models.PharmacyLot:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_pharmacy_lot_columns(conn)
        row = conn.execute(
            "SELECT image_path FROM pharmacy_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Lot introuvable")
        if not row["image_path"]:
            return get_pharmacy_lot(lot_id)

        conn.execute(
            "UPDATE pharmacy_lots SET image_path = NULL WHERE id = ?",
            (lot_id,),
        )
        _persist_after_commit(conn, "pharmacy")

    if row["image_path"]:
        try:
            (MEDIA_ROOT / row["image_path"]).unlink()
        except FileNotFoundError:
            pass
    return get_pharmacy_lot(lot_id)


def delete_pharmacy_lot(lot_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _require_pharmacy_lot(conn, lot_id)
        image_row = conn.execute(
            "SELECT image_path FROM pharmacy_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        conn.execute("DELETE FROM pharmacy_lot_items WHERE lot_id = ?", (lot_id,))
        conn.execute("DELETE FROM pharmacy_lots WHERE id = ?", (lot_id,))
        _persist_after_commit(conn, "pharmacy")

    if image_row and image_row["image_path"]:
        try:
            (MEDIA_ROOT / image_row["image_path"]).unlink()
        except FileNotFoundError:
            pass


def _build_pharmacy_lot_item(row: sqlite3.Row) -> models.PharmacyLotItem:
    return models.PharmacyLotItem(
        id=row["id"],
        lot_id=row["lot_id"],
        pharmacy_item_id=row["pharmacy_item_id"],
        quantity=row["quantity"],
        pharmacy_name=row["pharmacy_name"],
        pharmacy_sku=row["pharmacy_sku"],
        available_quantity=row["available_quantity"],
    )


def _get_pharmacy_lot_item(
    conn: sqlite3.Connection, lot_id: int, lot_item_id: int
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT pli.id, pli.lot_id, pli.pharmacy_item_id, pli.quantity,
               pi.name AS pharmacy_name, pi.barcode AS pharmacy_sku, pi.quantity AS available_quantity
        FROM pharmacy_lot_items AS pli
        JOIN pharmacy_items AS pi ON pi.id = pli.pharmacy_item_id
        WHERE pli.id = ? AND pli.lot_id = ?
        """,
        (lot_item_id, lot_id),
    ).fetchone()
    if row is None:
        raise ValueError("Affectation introuvable")
    return row


def _ensure_pharmacy_lot_capacity(
    conn: sqlite3.Connection,
    pharmacy_item_id: int,
    requested_quantity: int,
    *,
    exclude_lot_item_id: int | None = None,
) -> None:
    item_row = conn.execute(
        "SELECT quantity FROM pharmacy_items WHERE id = ?",
        (pharmacy_item_id,),
    ).fetchone()
    if item_row is None:
        raise ValueError("Article de pharmacie introuvable")

    query = "SELECT COALESCE(SUM(quantity), 0) AS reserved FROM pharmacy_lot_items WHERE pharmacy_item_id = ?"
    params: list[object] = [pharmacy_item_id]
    if exclude_lot_item_id is not None:
        query += " AND id != ?"
        params.append(exclude_lot_item_id)

    reserved_row = conn.execute(query, params).fetchone()
    reserved_quantity = reserved_row["reserved"] if reserved_row else 0
    available = item_row["quantity"] - reserved_quantity
    if requested_quantity > available:
        raise ValueError("Stock insuffisant en pharmacie pour cette affectation.")


def list_pharmacy_lot_items(lot_id: int) -> list[models.PharmacyLotItem]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _require_pharmacy_lot(conn, lot_id)
        rows = conn.execute(
            """
            SELECT pli.id, pli.lot_id, pli.pharmacy_item_id, pli.quantity,
                   pi.name AS pharmacy_name, pi.barcode AS pharmacy_sku, pi.quantity AS available_quantity
            FROM pharmacy_lot_items AS pli
            JOIN pharmacy_items AS pi ON pi.id = pli.pharmacy_item_id
            WHERE pli.lot_id = ?
            ORDER BY pi.name
            """,
            (lot_id,),
        ).fetchall()
    return [_build_pharmacy_lot_item(row) for row in rows]


def add_pharmacy_lot_item(
    lot_id: int, payload: models.PharmacyLotItemBase
) -> models.PharmacyLotItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _require_pharmacy_lot(conn, lot_id)
        existing = conn.execute(
            """
            SELECT id, quantity
            FROM pharmacy_lot_items
            WHERE lot_id = ? AND pharmacy_item_id = ?
            """,
            (lot_id, payload.pharmacy_item_id),
        ).fetchone()
        if existing:
            new_quantity = existing["quantity"] + payload.quantity
            _ensure_pharmacy_lot_capacity(
                conn,
                payload.pharmacy_item_id,
                new_quantity,
                exclude_lot_item_id=existing["id"],
            )
            conn.execute(
                "UPDATE pharmacy_lot_items SET quantity = ? WHERE id = ?",
                (new_quantity, existing["id"]),
            )
            lot_item_id = existing["id"]
        else:
            _ensure_pharmacy_lot_capacity(conn, payload.pharmacy_item_id, payload.quantity)
            cur = conn.execute(
                "INSERT INTO pharmacy_lot_items (lot_id, pharmacy_item_id, quantity) VALUES (?, ?, ?)",
                (lot_id, payload.pharmacy_item_id, payload.quantity),
            )
            lot_item_id = cur.lastrowid
        _persist_after_commit(conn, "pharmacy")

    with db.get_stock_connection() as conn:
        row = _get_pharmacy_lot_item(conn, lot_id, lot_item_id)
    return _build_pharmacy_lot_item(row)


def update_pharmacy_lot_item(
    lot_id: int, lot_item_id: int, payload: models.PharmacyLotItemUpdate
) -> models.PharmacyLotItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = _get_pharmacy_lot_item(conn, lot_id, lot_item_id)
        target_quantity = payload.quantity if payload.quantity is not None else row["quantity"]
        _ensure_pharmacy_lot_capacity(
            conn,
            row["pharmacy_item_id"],
            target_quantity,
            exclude_lot_item_id=lot_item_id,
        )
        if target_quantity != row["quantity"]:
            conn.execute(
                "UPDATE pharmacy_lot_items SET quantity = ? WHERE id = ?",
                (target_quantity, lot_item_id),
            )
        _persist_after_commit(conn, "pharmacy")

    with db.get_stock_connection() as conn:
        updated_row = _get_pharmacy_lot_item(conn, lot_id, lot_item_id)
    return _build_pharmacy_lot_item(updated_row)


def remove_pharmacy_lot_item(lot_id: int, lot_item_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _get_pharmacy_lot_item(conn, lot_id, lot_item_id)
        conn.execute(
            "DELETE FROM pharmacy_lot_items WHERE id = ? AND lot_id = ?",
            (lot_item_id, lot_id),
        )
        _persist_after_commit(conn, "pharmacy")


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


def _get_module_title(module_key: str) -> str:
    from configparser import ConfigParser

    titles = {key: label for key, label in _AVAILABLE_MODULE_DEFINITIONS}
    config_path = Path(__file__).resolve().parent.parent / "config.ini"
    parser = ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if parser.has_section("modules"):
        for key, value in parser.items("modules"):
            trimmed = value.strip()
            if trimmed:
                titles[key] = trimmed
    return titles.get(module_key, module_key)


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
    updates = payload.model_dump(exclude_unset=True)
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
    updates_raw = payload.model_dump(exclude_unset=True)
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


def _format_date_label(value: date | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d/%m/%Y")


def _render_remise_inventory_pdf(
    *, items: list[models.Item], category_map: dict[int, str], module_title: str
) -> bytes:
    buffer = io.BytesIO()
    page_size = landscape(A4)
    pdf = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size
    margin = 14 * mm
    base_row_padding = 10
    line_height = 12
    header_height = 24
    text_color = colors.Color(0.91, 0.93, 0.97)
    background_color = colors.Color(0.043, 0.059, 0.102)
    header_bg_color = colors.Color(0.082, 0.105, 0.156)
    row_bg_color = colors.Color(0.067, 0.082, 0.125)
    row_alt_bg_color = colors.Color(0.078, 0.098, 0.149)

    columns: list[tuple[str, float, str]] = [
        ("MATÉRIEL", 0.28, "left"),
        ("QUANTITÉ", 0.10, "center"),
        ("TAILLE / VARIANTE", 0.14, "center"),
        ("CATÉGORIE", 0.16, "center"),
        ("LOT(S)", 0.12, "center"),
        ("PÉREMPTION", 0.10, "center"),
        ("SEUIL", 0.10, "center"),
    ]

    table_width = width - 2 * margin
    generated_at = datetime.now()

    def _wrap_to_width(value: str, max_width: float, font_name: str, font_size: float) -> list[str]:
        """Wrap a text value to fit within the provided width.

        The function keeps whole words when possible and falls back to splitting long
        tokens to avoid truncation, ensuring all lot names remain fully visible in the
        PDF.
        """

        def _split_long_word(word: str) -> list[str]:
            parts: list[str] = []
            current = ""
            for char in word:
                if pdfmetrics.stringWidth(current + char, font_name, font_size) <= max_width:
                    current += char
                else:
                    if current:
                        parts.append(current)
                    current = char
            if current:
                parts.append(current)
            return parts or [word]

        words = value.split()
        if not words:
            return [""]

        lines: list[str] = []
        current_line = ""

        for word in words:
            word_parts = (
                _split_long_word(word)
                if pdfmetrics.stringWidth(word, font_name, font_size) > max_width
                else [word]
            )
            for part in word_parts:
                candidate = f"{current_line} {part}".strip()
                if current_line and pdfmetrics.stringWidth(candidate, font_name, font_size) > max_width:
                    lines.append(current_line)
                    current_line = part
                else:
                    current_line = candidate

        if current_line:
            lines.append(current_line)

        return lines or [value]

    def _format_cell(value: str | None) -> str:
        value = value or "-"
        return value

    def draw_page_background() -> None:
        pdf.setFillColor(background_color)
        pdf.rect(0, 0, width, height, stroke=0, fill=1)
        pdf.setFillColor(text_color)

    def start_page(page_number: int) -> float:
        draw_page_background()
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(margin, height - margin + 4, module_title)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(
            margin,
            height - margin - 10,
            f"Généré le {_format_date_label(generated_at.date())} à {generated_at.strftime('%H:%M')}",
        )
        pdf.drawRightString(width - margin, margin - 6, f"Page {page_number}")
        return height - margin - header_height

    def draw_header(y_position: float) -> float:
        pdf.setFillColor(header_bg_color)
        pdf.rect(margin, y_position - header_height + 4, table_width, header_height, stroke=0, fill=1)
        pdf.setFillColor(text_color)
        pdf.setFont("Helvetica-Bold", 9)
        x = margin
        for label, ratio, align in columns:
            cell_width = ratio * table_width
            if align == "center":
                pdf.drawCentredString(x + cell_width / 2, y_position - 6, label)
            else:
                pdf.drawString(x + 4, y_position - 6, label)
            x += cell_width
        pdf.setFont("Helvetica", 9)
        return y_position - header_height

    y = start_page(1)
    y = draw_header(y)
    page_number = 1

    for index, item in enumerate(items):
        category_label = _format_cell(category_map.get(item.category_id or -1, None) if item.category_id else None)
        lots_label = _format_cell(
            ", ".join(item.lot_names) if item.lot_names else None
        )
        expiration_label = _format_date_label(item.expiration_date)
        expiration_label = "-" if expiration_label == "—" else expiration_label
        threshold_label = str(item.low_stock_threshold or 1) if item.track_low_stock else "1"
        size_label = _format_cell(item.size)
        name_label = _format_cell(item.name)

        values: list[tuple[str, float, str]] = [
            (name_label, columns[0][1], "left"),
            (str(item.quantity or 0), columns[1][1], "center"),
            (size_label, columns[2][1], "center"),
            (category_label, columns[3][1], "center"),
            (lots_label, columns[4][1], "center"),
            (expiration_label, columns[5][1], "center"),
            (threshold_label, columns[6][1], "center"),
        ]

        wrapped_values: list[tuple[list[str], float, str]] = []
        max_line_count = 1
        for value, ratio, align in values:
            cell_width = ratio * table_width
            lines = _wrap_to_width(str(value), cell_width - 8, "Helvetica", 9)
            max_line_count = max(max_line_count, len(lines))
            wrapped_values.append((lines, cell_width, align))

        row_height = max_line_count * line_height + base_row_padding

        if y <= margin + row_height:
            pdf.showPage()
            page_number += 1
            y = start_page(page_number)
            y = draw_header(y)

        pdf.setFillColor(row_alt_bg_color if index % 2 else row_bg_color)
        pdf.rect(margin, y - row_height + 6, table_width, row_height, stroke=0, fill=1)
        pdf.setFillColor(text_color)

        x = margin
        for lines, cell_width, align in wrapped_values:
            text_y = y - 8
            for line in lines:
                if align == "center":
                    pdf.drawCentredString(x + cell_width / 2, text_y, line)
                else:
                    pdf.drawString(x + 4, text_y, line)
                text_y -= line_height
            x += cell_width

        y -= row_height

    pdf.save()
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


def generate_remise_purchase_order_pdf(order: models.RemisePurchaseOrderDetail) -> bytes:
    status_label = _PURCHASE_ORDER_STATUS_LABELS.get(order.status, order.status)
    created_at = order.created_at.strftime("%d/%m/%Y %H:%M")
    supplier = order.supplier_name or "Aucun"
    meta_lines = [
        f"Bon de commande remises n° {order.id}",
        f"Créé le : {created_at}",
        f"Fournisseur : {supplier}",
        f"Statut : {status_label}",
    ]
    if order.auto_created:
        meta_lines.append("Création automatique : Oui")
    note_lines = wrap(order.note or "", 90) if order.note else []
    item_rows = [
        (
            line.item_name or f"Article #{line.remise_item_id}",
            line.quantity_ordered,
            line.quantity_received,
        )
        for line in order.items
    ]
    return _render_purchase_order_pdf(
        title="Bon de commande inventaire remises",
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


def generate_vehicle_inventory_pdf(
    *, pointer_targets: dict[str, models.PointerTarget] | None = None, options: VehiclePdfOptions | None = None
) -> bytes:
    """Export the complete vehicle inventory as a PDF document."""

    ensure_database_ready()
    categories = list_vehicle_categories()
    items = list_vehicle_items()
    generated_at = datetime.now(timezone.utc)
    pdf_options = VehiclePdfOptions(**(options.model_dump() if options else {}))

    if pdf_options.category_ids:
        allowed_ids = set(pdf_options.category_ids)
        categories = [category for category in categories if category.id in allowed_ids]
        items = [item for item in items if item.category_id in allowed_ids]

    return render_vehicle_inventory_pdf(
        categories=categories,
        items=items,
        generated_at=generated_at,
        pointer_targets=pointer_targets,
        options=pdf_options,
        media_root=MEDIA_ROOT,
    )


def generate_remise_inventory_pdf() -> bytes:
    ensure_database_ready()
    items = [item for item in list_remise_items() if not item.assigned_vehicle_names]
    categories = {category.id: category.name for category in list_remise_categories()}

    return _render_remise_inventory_pdf(
        items=items,
        category_map=categories,
        module_title=_get_module_title("inventory_remise"),
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
            _persist_after_commit(conn, "default")
        except Exception:
            conn.rollback()
            raise
    return get_purchase_order(order_id)


def _build_remise_purchase_order_detail(
    conn: sqlite3.Connection, order_row: sqlite3.Row
) -> models.RemisePurchaseOrderDetail:
    items_cur = conn.execute(
        """
        SELECT rpoi.id,
               rpoi.purchase_order_id,
               rpoi.remise_item_id,
               rpoi.quantity_ordered,
               rpoi.quantity_received,
               ri.name AS item_name
        FROM remise_purchase_order_items AS rpoi
        JOIN remise_items AS ri ON ri.id = rpoi.remise_item_id
        WHERE rpoi.purchase_order_id = ?
        ORDER BY ri.name COLLATE NOCASE
        """,
        (order_row["id"],),
    )
    items = [
        models.RemisePurchaseOrderItem(
            id=item_row["id"],
            purchase_order_id=item_row["purchase_order_id"],
            remise_item_id=item_row["remise_item_id"],
            quantity_ordered=item_row["quantity_ordered"],
            quantity_received=item_row["quantity_received"],
            item_name=item_row["item_name"],
        )
        for item_row in items_cur.fetchall()
    ]
    return models.RemisePurchaseOrderDetail(
        id=order_row["id"],
        supplier_id=order_row["supplier_id"],
        supplier_name=order_row["supplier_name"],
        status=order_row["status"],
        created_at=order_row["created_at"],
        note=order_row["note"],
        auto_created=bool(order_row["auto_created"]),
        items=items,
    )


def list_remise_purchase_orders() -> list[models.RemisePurchaseOrderDetail]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name
            FROM remise_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            ORDER BY po.created_at DESC, po.id DESC
            """
        )
        rows = cur.fetchall()
        return [_build_remise_purchase_order_detail(conn, row) for row in rows]


def get_remise_purchase_order(order_id: int) -> models.RemisePurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name
            FROM remise_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        return _build_remise_purchase_order_detail(conn, row)


def create_remise_purchase_order(
    payload: models.RemisePurchaseOrderCreate,
) -> models.RemisePurchaseOrderDetail:
    ensure_database_ready()
    status = _normalize_purchase_order_status(payload.status)
    aggregated = _aggregate_positive_quantities(
        (line.remise_item_id, line.quantity_ordered) for line in payload.items
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
                INSERT INTO remise_purchase_orders (supplier_id, status, note, auto_created)
                VALUES (?, ?, ?, 0)
                """,
                (payload.supplier_id, status, payload.note),
            )
            order_id = cur.lastrowid
            for remise_item_id, quantity in aggregated.items():
                item_cur = conn.execute(
                    "SELECT 1 FROM remise_items WHERE id = ?", (remise_item_id,)
                )
                if item_cur.fetchone() is None:
                    raise ValueError("Article introuvable")
                conn.execute(
                    """
                    INSERT INTO remise_purchase_order_items (purchase_order_id, remise_item_id, quantity_ordered, quantity_received)
                    VALUES (?, ?, ?, 0)
                    """,
                    (order_id, remise_item_id, quantity),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return get_remise_purchase_order(order_id)


def update_remise_purchase_order(
    order_id: int, payload: models.RemisePurchaseOrderUpdate
) -> models.RemisePurchaseOrderDetail:
    ensure_database_ready()
    updates_raw = payload.model_dump(exclude_unset=True)
    if not updates_raw:
        return get_remise_purchase_order(order_id)
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
        return get_remise_purchase_order(order_id)
    assignments = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values())
    values.append(order_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            "SELECT 1 FROM remise_purchase_orders WHERE id = ?", (order_id,)
        )
        if cur.fetchone() is None:
            raise ValueError("Bon de commande introuvable")
        conn.execute(
            f"UPDATE remise_purchase_orders SET {assignments} WHERE id = ?", values
        )
        conn.commit()
    return get_remise_purchase_order(order_id)


def receive_remise_purchase_order(
    order_id: int, payload: models.RemisePurchaseOrderReceivePayload
) -> models.RemisePurchaseOrderDetail:
    ensure_database_ready()
    increments = _aggregate_positive_quantities(
        (line.remise_item_id, line.quantity) for line in payload.items
    )
    if not increments:
        raise ValueError("Aucune ligne de réception valide")
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT status FROM remise_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        try:
            for remise_item_id, increment in increments.items():
                line = conn.execute(
                    """
                    SELECT id, quantity_ordered, quantity_received
                    FROM remise_purchase_order_items
                    WHERE purchase_order_id = ? AND remise_item_id = ?
                    """,
                    (order_id, remise_item_id),
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
                    "UPDATE remise_purchase_order_items SET quantity_received = ? WHERE id = ?",
                    (new_received, line["id"]),
                )
                conn.execute(
                    "UPDATE remise_items SET quantity = quantity + ? WHERE id = ?",
                    (delta, remise_item_id),
                )
                conn.execute(
                    "INSERT INTO remise_movements (item_id, delta, reason) VALUES (?, ?, ?)",
                    (remise_item_id, delta, f"Réception bon de commande remise #{order_id}"),
                )
            totals = conn.execute(
                """
                SELECT quantity_ordered, quantity_received
                FROM remise_purchase_order_items
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
                    "UPDATE remise_purchase_orders SET status = ? WHERE id = ?",
                    (new_status, order_id),
                )
            _persist_after_commit(conn, "inventory_remise")
        except Exception:
            conn.rollback()
            raise
    return get_remise_purchase_order(order_id)


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
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
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
        _persist_after_commit(conn, "default")
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
        _persist_after_commit(conn, "default")
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
        _persist_after_commit(conn, "default")


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


def list_vehicle_library_items(
    vehicle_type: str,
    search: str | None = None,
    category_id: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[models.VehicleLibraryItem]:
    if vehicle_type != "secours_a_personne":
        return []
    ensure_database_ready()
    filters = ["quantity > 0"]
    params: list[object] = []
    if search:
        filters.append("(name LIKE ? OR barcode LIKE ?)")
        like = f"%{search.strip()}%"
        params.extend([like, like])
    if category_id is not None:
        filters.append("category_id = ?")
        params.append(category_id)
    where_clause = " AND ".join(filters)
    query = f"""
        SELECT id,
               name,
               barcode AS sku,
               category_id,
               quantity,
               expiration_date,
               low_stock_threshold
        FROM pharmacy_items
        WHERE {where_clause}
        ORDER BY name COLLATE NOCASE
    """
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
        if offset is not None:
            query += " OFFSET ?"
            params.append(offset)
    elif offset is not None:
        query += " LIMIT -1 OFFSET ?"
        params.append(offset)
    with db.get_stock_connection() as conn:
        cur = conn.execute(query, params)
        return [
            models.VehicleLibraryItem(
                id=row["id"],
                name=row["name"],
                sku=row["sku"],
                category_id=row["category_id"],
                quantity=row["quantity"],
                expiration_date=row["expiration_date"],
                image_url=None,
                track_low_stock=True,
                low_stock_threshold=row["low_stock_threshold"],
            )
            for row in cur.fetchall()
        ]


def _iter_module_barcode_values(
    conn: sqlite3.Connection, module: str, table: str, column: str
) -> Iterator[str]:
    """Itère sur les valeurs de codes-barres pour un module donné."""

    if module == "vehicle_inventory":
        query = f"""
            SELECT DISTINCT src.{column} AS value
            FROM {table} AS src
            LEFT JOIN remise_items AS base ON base.id = src.remise_item_id
            WHERE src.{column} IS NOT NULL
              AND TRIM(src.{column}) <> ""
              AND (src.remise_item_id IS NULL OR base.id IS NOT NULL)
        """
    else:
        query = f"""
            SELECT DISTINCT {column} AS value
            FROM {table}
            WHERE {column} IS NOT NULL AND TRIM({column}) <> ""
        """

    cur = conn.execute(query)
    for row in cur.fetchall():
        raw_value = row["value"]
        if not raw_value:
            continue
        normalized = raw_value.strip()
        if not normalized:
            continue
        yield normalized


def list_existing_barcodes(user: models.User) -> list[models.BarcodeValue]:
    ensure_database_ready()

    accessible_sources = [
        (module, table, column)
        for module, table, column in _BARCODE_MODULE_SOURCES
        if has_module_access(user, module, action="view")
    ]
    if not accessible_sources:
        return []

    existing_visual_keys = {
        asset.sku.strip().casefold()
        for asset in barcode_service.list_barcode_assets()
        if asset.sku.strip()
    }

    collected: dict[str, str] = {}
    with db.get_stock_connection() as conn:
        for module, table, column in accessible_sources:
            for normalized in _iter_module_barcode_values(conn, module, table, column):
                key = normalized.casefold()
                if key in existing_visual_keys:
                    continue
                if key not in collected:
                    collected[key] = normalized

    return [
        models.BarcodeValue(sku=value)
        for _, value in sorted(collected.items(), key=lambda item: item[1].casefold())
    ]


def _collect_normalized_barcode_values(
    conn: sqlite3.Connection, sources: Iterable[tuple[str, str, str]]
) -> set[str]:
    """Retourne les codes-barres connus pour les modules fournis (normalisés)."""

    collected: set[str] = set()
    for module, table, column in sources:
        for normalized in _iter_module_barcode_values(conn, module, table, column):
            key = normalized.casefold()
            collected.add(key)
            sanitized = normalized.replace("/", "-")
            if sanitized != normalized:
                collected.add(sanitized.casefold())
    return collected


def list_accessible_barcode_assets(user: models.User) -> list[barcode_service.BarcodeAsset]:
    """Retourne les fichiers de codes-barres consultables par l'utilisateur.

    Les fichiers orphelins (ne correspondant plus à un enregistrement existant) sont
    automatiquement purgés pour éviter d'exposer des visuels obsolètes.
    """

    assets = barcode_service.list_barcode_assets()
    if not assets:
        return []

    ensure_database_ready()

    if user.role == "admin":
        # Les administrateurs doivent pouvoir visualiser tous les fichiers générés,
        # même lorsqu'ils ne sont pas encore associés à une donnée métier. Cela
        # permet notamment de vérifier immédiatement un code-barres fraîchement
        # créé (les tests de régression couvrent ce comportement). On ne tente
        # donc pas de filtrer ni de purger ces visuels dans ce cas.
        return assets

    else:
        accessible_sources = [
            (module, table, column)
            for module, table, column in _BARCODE_MODULE_SOURCES
            if has_module_access(user, module, action="view")
        ]
        if not accessible_sources:
            return []

    with db.get_stock_connection() as conn:
        allowed_values = _collect_normalized_barcode_values(conn, accessible_sources)

    filtered_assets: list[barcode_service.BarcodeAsset] = []
    purge_candidates: list[barcode_service.BarcodeAsset] = []

    for asset in assets:
        normalized_sku = asset.sku.strip()
        if not normalized_sku:
            purge_candidates.append(asset)
            continue

        normalized_key = normalized_sku.casefold()

        if normalized_key in allowed_values:
            filtered_assets.append(asset)
            continue

        if user.role == "admin":
            # Si l'administrateur ne dispose pas de référence pour ce code,
            # il s'agit d'un fichier orphelin à supprimer dynamiquement.
            purge_candidates.append(asset)

    if user.role == "admin" and purge_candidates:
        for asset in purge_candidates:
            try:
                asset.path.unlink(missing_ok=True)
            except OSError:
                # L'échec de suppression ne doit pas bloquer l'affichage.
                pass

    return filtered_assets


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
    expiration_date = (
        payload.expiration_date.isoformat() if payload.expiration_date is not None else None
    )
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
                    expiration_date,
                    payload.location,
                    payload.category_id,
                ),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Ce code-barres est déjà utilisé") from exc
        _persist_after_commit(conn, "pharmacy")
        return get_pharmacy_item(cur.lastrowid)


def update_pharmacy_item(item_id: int, payload: models.PharmacyItemUpdate) -> models.PharmacyItem:
    ensure_database_ready()
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if "barcode" in fields:
        fields["barcode"] = _normalize_barcode(fields["barcode"])
    if "expiration_date" in fields and fields["expiration_date"] is not None:
        fields["expiration_date"] = fields["expiration_date"].isoformat()
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
        _persist_after_commit(conn, "pharmacy")
    return get_pharmacy_item(item_id)


def delete_pharmacy_item(item_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("DELETE FROM pharmacy_items WHERE id = ?", (item_id,))
        if cur.rowcount == 0:
            raise ValueError("Produit pharmaceutique introuvable")
        _persist_after_commit(conn, "pharmacy")


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
        _persist_after_commit(conn, "pharmacy")
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
        _persist_after_commit(conn, "pharmacy")

    return get_pharmacy_category(category_id)


def delete_pharmacy_category(category_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pharmacy_category_sizes WHERE category_id = ?", (category_id,))
        conn.execute("DELETE FROM pharmacy_categories WHERE id = ?", (category_id,))
        _persist_after_commit(conn, "pharmacy")


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
        _persist_after_commit(conn, "pharmacy")


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
    updates_raw = payload.model_dump(exclude_unset=True)
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
            _persist_after_commit(conn, "pharmacy")
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


def _iter_module_dependencies(module: str) -> list[str]:
    seen: set[str] = set()
    stack = list(_MODULE_DEPENDENCIES.get(module, ()))
    resolved: list[str] = []
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        resolved.append(current)
        stack.extend(_MODULE_DEPENDENCIES.get(current, ()))
    return resolved


def has_module_access(user: models.User, module: str, *, action: str = "view") -> bool:
    ensure_database_ready()
    if user.role == "admin":
        return True
    required_modules = [module, *_iter_module_dependencies(module)]
    for required in required_modules:
        permission = get_module_permission_for_user(user.id, required)
        if permission is None:
            return False
        if required == module:
            if action == "edit":
                if not permission.can_edit:
                    return False
            elif not permission.can_view:
                return False
        elif not permission.can_view:
            return False
    return True
