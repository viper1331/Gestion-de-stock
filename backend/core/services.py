"""Services métier pour Gestion Stock Pro."""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import math
import os
import random
import re
import secrets
import shutil
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from textwrap import wrap
from typing import Any, BinaryIO, Callable, ContextManager, Iterable, Iterator, Optional, TypeVar
from urllib.parse import urlparse
from uuid import uuid4

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from backend.core import db, menu_registry, models, security, sites, system_config
from backend.services.purchase_order_pdf import render_purchase_order_pdf
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
from backend.services import email_sender, notifications
from backend.services.pdf_config import (
    draw_watermark,
    effective_density_scale,
    margins_for_format,
    page_size_for_format,
    render_filename,
    resolve_pdf_config,
)
from backend.services.pdf.theme import apply_theme_reportlab, resolve_reportlab_theme, scale_reportlab_theme
from backend.services.pdf import VehiclePdfOptions, render_vehicle_inventory_pdf
from backend.services.pdf.grouping import GroupNode, build_group_tree, compute_group_stats
from backend.services.backup_settings import (
    DEFAULT_BACKUP_INTERVAL_MINUTES,
    DEFAULT_BACKUP_RETENTION_COUNT,
)

# Initialisation des bases de données au chargement du module
_db_initialized = False
_db_init_lock = threading.Lock()
_MIGRATION_LOCK_PATH = db.DATA_DIR / "schema_migration.lock"
_MIGRATION_LOCK_SLEEP_SECONDS = 0.1
_MIGRATION_RETRY_ATTEMPTS = 8
_MIGRATION_RETRY_BASE_DELAY_SECONDS = 0.1

T = TypeVar("T")

logger = logging.getLogger(__name__)

_AUTO_PO_CLOSED_STATUSES = ("CANCELLED", "RECEIVED")

MESSAGE_ARCHIVE_ROOT = db.DATA_DIR / "message_archive"

_MESSAGE_RATE_LIMIT_DEFAULT_COUNT = 5
_MESSAGE_RATE_LIMIT_DEFAULT_WINDOW_SECONDS = 60
_PASSWORD_RESET_RATE_LIMIT_COUNT = 5
_PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS = 3600
_PASSWORD_RESET_MIN_LENGTH = 10

_MENU_ORDER_MAX_ITEMS = 200
_MENU_ORDER_MAX_ID_LENGTH = 100

_SUPPLIER_MIGRATION_LOCK = threading.Lock()
_SUPPLIER_MIGRATED_SITES: set[str] = set()

class MessageRateLimitError(RuntimeError):
    def __init__(self, *, count: int, window_seconds: int) -> None:
        self.count = count
        self.window_seconds = window_seconds
        super().__init__("Trop de messages envoyés. Réessayez dans quelques secondes.")


class PasswordResetRateLimitError(RuntimeError):
    def __init__(self, *, count: int, window_seconds: int) -> None:
        self.count = count
        self.window_seconds = window_seconds
        super().__init__("Trop de demandes de réinitialisation. Réessayez plus tard.")


class UsersDbNotReadyError(RuntimeError):
    pass

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

_PURCHASE_SUGGESTION_MODULES: tuple[str, ...] = (
    "clothing",
    "pharmacy",
    "inventory_remise",
)


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

_LINK_MODULE_CONFIG: dict[str, dict[str, Any]] = {
    "vehicle_qr": {
        "item_table": "vehicle_items",
        "link_table": "vehicle_item_links",
        "item_id_column": "vehicle_item_id",
        "legacy_map": {
            "onedrive": "shared_file_url",
            "documentation": "documentation_url",
            "tutoriel": "tutorial_url",
        },
    },
    "pharmacy": {
        "item_table": "pharmacy_items",
        "link_table": "pharmacy_item_links",
        "item_id_column": "pharmacy_item_id",
        "legacy_map": {},
    },
}
_LINK_MODULE_ALIASES: dict[str, str] = {
    "pharmacy_links": "pharmacy",
    "pharmacy_qr": "pharmacy",
}

_BARCODE_MODULE_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("clothing", "items", "sku"),
    ("pharmacy", "pharmacy_items", "barcode"),
    ("inventory_remise", "remise_items", "sku"),
    ("vehicle_inventory", "vehicle_items", "sku"),
)

_BARCODE_CATALOG_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    ("clothing", "items", "sku", "name"),
    ("pharmacy", "pharmacy_items", "barcode", "name"),
    ("inventory_remise", "remise_items", "sku", "name"),
    ("vehicle_inventory", "vehicle_items", "sku", "name"),
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


def _get_site_stock_conn(site_key: str | int | None) -> ContextManager[sqlite3.Connection]:
    normalized = sites.normalize_site_key(str(site_key)) if site_key else db.DEFAULT_SITE_KEY
    return db.get_stock_connection(normalized)


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


def _get_purchase_suggestions_safety_buffer() -> int:
    config = system_config.get_config()
    raw = config.extra.get("purchase_suggestions_safety_buffer", 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _extract_reorder_qty(extra: dict[str, Any] | None) -> int | None:
    if not extra:
        return None
    value = extra.get("reorder_qty")
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _calculate_suggested_qty(
    quantity: int, threshold: int, reorder_qty: int | None, safety_buffer: int
) -> int:
    if reorder_qty is not None:
        return max(0, reorder_qty)
    return max(0, threshold - quantity) + max(0, safety_buffer)


def _build_purchase_suggestion_line(
    *,
    item_id: int,
    sku: str | None,
    label: str | None,
    quantity: int,
    threshold: int,
    unit: str | None,
    supplier_id: int | None,
    reorder_qty: int | None,
    safety_buffer: int,
) -> dict[str, Any]:
    qty_suggested = _calculate_suggested_qty(quantity, threshold, reorder_qty, safety_buffer)
    return {
        "item_id": item_id,
        "sku": sku,
        "label": label,
        "qty_suggested": qty_suggested,
        "qty_final": qty_suggested,
        "unit": unit,
        "reason": "Stock sous seuil",
        "stock_current": quantity,
        "threshold": threshold,
        "supplier_id": supplier_id,
    }


def _resolve_supplier_id_from_name(
    conn: sqlite3.Connection, supplier_name: str | None
) -> int | None:
    if not supplier_name:
        return None
    normalized = " ".join(str(supplier_name).strip().split())
    if not normalized:
        return None
    row = conn.execute(
        "SELECT id FROM suppliers WHERE lower(trim(name)) = ?",
        (normalized.lower(),),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _require_supplier_for_module(
    conn: sqlite3.Connection,
    supplier_id: int,
    *,
    module_key: str,
) -> None:
    row = conn.execute(
        "SELECT 1 FROM suppliers WHERE id = ?",
        (supplier_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Fournisseur invalide")
    modules = _load_supplier_modules(conn, [supplier_id]).get(supplier_id) or ["suppliers"]
    if module_key not in modules:
        raise ValueError("Fournisseur invalide")


def _get_reorder_candidates(
    conn: sqlite3.Connection,
    module_key: str,
    safety_buffer: int,
) -> list[dict[str, Any]]:
    if module_key == "clothing":
        rows = conn.execute(
            """
            SELECT id, name, sku, size, quantity, low_stock_threshold, supplier_id, track_low_stock
            FROM items
            WHERE quantity < low_stock_threshold AND low_stock_threshold > 0
            """
        ).fetchall()
        candidates: list[dict[str, Any]] = []
        for row in rows:
            if "track_low_stock" in row.keys() and not bool(row["track_low_stock"]):
                continue
            candidates.append(
                _build_purchase_suggestion_line(
                    item_id=row["id"],
                    sku=row["sku"],
                    label=row["name"],
                    quantity=row["quantity"],
                    threshold=row["low_stock_threshold"],
                    unit=row["size"],
                    supplier_id=row["supplier_id"],
                    reorder_qty=None,
                    safety_buffer=safety_buffer,
                )
            )
        return candidates
    if module_key == "pharmacy":
        rows = conn.execute(
            """
            SELECT id,
                   name,
                   barcode,
                   packaging,
                   dosage,
                   quantity,
                   low_stock_threshold,
                   supplier_id,
                   extra_json
            FROM pharmacy_items
            WHERE quantity < low_stock_threshold AND low_stock_threshold > 0
            """
        ).fetchall()
        candidates = []
        for row in rows:
            extra = _parse_extra_json(row["extra_json"])
            supplier_id = (
                row["supplier_id"] if "supplier_id" in row.keys() else None
            )
            if supplier_id is None:
                supplier_id = (
                    extra.get("supplier_id") if isinstance(extra.get("supplier_id"), int) else None
                )
            if supplier_id is None:
                supplier_id = _resolve_supplier_id_from_name(
                    conn,
                    extra.get("supplier_name")
                    or extra.get("supplier")
                    or extra.get("fournisseur"),
                )
            candidates.append(
                _build_purchase_suggestion_line(
                    item_id=row["id"],
                    sku=row["barcode"] or str(row["id"]),
                    label=row["name"],
                    quantity=row["quantity"],
                    threshold=row["low_stock_threshold"],
                    unit=row["packaging"] or row["dosage"],
                    supplier_id=supplier_id,
                    reorder_qty=_extract_reorder_qty(extra),
                    safety_buffer=safety_buffer,
                )
            )
        return candidates
    if module_key == "inventory_remise":
        rows = conn.execute(
            """
            SELECT id, name, sku, size, quantity, low_stock_threshold, supplier_id, track_low_stock, extra_json
            FROM remise_items
            WHERE quantity < low_stock_threshold AND low_stock_threshold > 0
            """
        ).fetchall()
        candidates = []
        for row in rows:
            if "track_low_stock" in row.keys() and not bool(row["track_low_stock"]):
                continue
            extra = _parse_extra_json(row["extra_json"])
            supplier_id = row["supplier_id"]
            if supplier_id is None:
                supplier_id = _resolve_supplier_id_from_name(
                    conn,
                    extra.get("supplier_name")
                    or extra.get("supplier")
                    or extra.get("fournisseur"),
                )
            candidates.append(
                _build_purchase_suggestion_line(
                    item_id=row["id"],
                    sku=row["sku"],
                    label=row["name"],
                    quantity=row["quantity"],
                    threshold=row["low_stock_threshold"],
                    unit=row["size"],
                    supplier_id=supplier_id,
                    reorder_qty=_extract_reorder_qty(extra),
                    safety_buffer=safety_buffer,
                )
            )
        return candidates
    raise ValueError(f"Module de suggestion inconnu: {module_key}")


def get_reorder_candidates(site_key: str, module_key: str) -> list[dict[str, Any]]:
    ensure_database_ready()
    if module_key not in _PURCHASE_SUGGESTION_MODULES:
        raise ValueError(f"Module de suggestion inconnu: {module_key}")
    safety_buffer = _get_purchase_suggestions_safety_buffer()
    with _get_site_stock_conn(site_key) as conn:
        return _get_reorder_candidates(conn, module_key, safety_buffer)


def _get_purchase_suggestion_lines(
    conn: sqlite3.Connection, suggestion_ids: list[int]
) -> dict[int, list[models.PurchaseSuggestionLine]]:
    if not suggestion_ids:
        return {}
    placeholders = ", ".join("?" for _ in suggestion_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM purchase_suggestion_lines
        WHERE suggestion_id IN ({placeholders})
        ORDER BY id
        """,
        suggestion_ids,
    ).fetchall()
    lines: dict[int, list[models.PurchaseSuggestionLine]] = defaultdict(list)
    for row in rows:
        line = models.PurchaseSuggestionLine(
            id=row["id"],
            suggestion_id=row["suggestion_id"],
            item_id=row["item_id"],
            sku=row["sku"],
            label=row["label"],
            qty_suggested=row["qty_suggested"],
            qty_final=row["qty_final"],
            unit=row["unit"],
            reason=row["reason"],
            stock_current=row["stock_current"],
            threshold=row["threshold"],
        )
        lines[line.suggestion_id].append(line)
    return lines


def _is_supplier_inactive(row: sqlite3.Row) -> bool:
    if "is_active" in row.keys() and not row["is_active"]:
        return True
    if "is_deleted" in row.keys() and row["is_deleted"]:
        return True
    if "deleted_at" in row.keys() and row["deleted_at"]:
        return True
    return False


def _resolve_suggestion_supplier_payload(
    row: sqlite3.Row | None,
) -> tuple[str | None, str | None, str]:
    if row is None:
        return None, None, "missing"
    display = row["name"]
    if _is_supplier_inactive(row):
        return display, None, "inactive"
    email = str(row["email"] or "").strip()
    if not email:
        return display, None, "no_email"
    normalized_email = _normalize_email(email)
    if len(normalized_email) < 5 or "@" not in normalized_email:
        return display, None, "no_email"
    return display, row["email"], "ok"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def migrate_legacy_suppliers_to_site(site_key: str | int | None) -> None:
    normalized_site_key = sites.normalize_site_key(str(site_key)) if site_key else db.DEFAULT_SITE_KEY
    if not normalized_site_key:
        normalized_site_key = db.DEFAULT_SITE_KEY
    if normalized_site_key == db.DEFAULT_SITE_KEY:
        return
    with _SUPPLIER_MIGRATION_LOCK:
        if normalized_site_key in _SUPPLIER_MIGRATED_SITES:
            return
        _SUPPLIER_MIGRATED_SITES.add(normalized_site_key)
    try:
        with db.get_stock_connection(db.DEFAULT_SITE_KEY) as legacy, db.get_stock_connection(
            normalized_site_key
        ) as site:
            if not _table_exists(legacy, "suppliers") or not _table_exists(site, "suppliers"):
                return
            legacy_count = legacy.execute("SELECT COUNT(1) FROM suppliers").fetchone()[0]
            site_count = site.execute("SELECT COUNT(1) FROM suppliers").fetchone()[0]
            if legacy_count <= 0 or site_count > 0:
                return
            rows = legacy.execute(
                "SELECT id, name, contact_name, phone, email, address FROM suppliers"
            ).fetchall()
            if rows:
                site.executemany(
                    """
                    INSERT OR IGNORE INTO suppliers (id, name, contact_name, phone, email, address)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            row["id"],
                            row["name"],
                            row["contact_name"],
                            row["phone"],
                            row["email"],
                            row["address"],
                        )
                        for row in rows
                    ],
                )
            if _table_exists(legacy, "supplier_modules") and _table_exists(site, "supplier_modules"):
                module_rows = legacy.execute(
                    "SELECT supplier_id, module FROM supplier_modules"
                ).fetchall()
                if module_rows:
                    site.executemany(
                        """
                        INSERT OR IGNORE INTO supplier_modules (supplier_id, module)
                        VALUES (?, ?)
                        """,
                        [(row["supplier_id"], row["module"]) for row in module_rows],
                    )
            site.commit()
    except Exception:
        with _SUPPLIER_MIGRATION_LOCK:
            _SUPPLIER_MIGRATED_SITES.discard(normalized_site_key)
        raise


def list_purchase_suggestions(
    *,
    site_key: str,
    status: str | None = None,
    module_key: str | None = None,
    allowed_modules: Iterable[str] | None = None,
) -> list[models.PurchaseSuggestionDetail]:
    ensure_database_ready()
    migrate_legacy_suppliers_to_site(site_key)
    with _get_site_stock_conn(site_key) as conn:
        query = """
            SELECT ps.*
            FROM purchase_suggestions AS ps
            WHERE ps.site_key = ?
        """
        params: list[Any] = [site_key]
        if status:
            query += " AND ps.status = ?"
            params.append(status)
        if module_key:
            query += " AND ps.module_key = ?"
            params.append(module_key)
        if allowed_modules is not None:
            allowed = list(allowed_modules)
            if not allowed:
                return []
            placeholders = ", ".join("?" for _ in allowed)
            query += f" AND ps.module_key IN ({placeholders})"
            params.extend(allowed)
        query += " ORDER BY ps.updated_at DESC, ps.id DESC"
        rows = conn.execute(query, params).fetchall()
        supplier_ids = sorted({row["supplier_id"] for row in rows if row["supplier_id"] is not None})
        suppliers_by_id: dict[int, sqlite3.Row] = {}
        if supplier_ids:
            placeholders = ", ".join("?" for _ in supplier_ids)
            supplier_rows = conn.execute(
                f"SELECT * FROM suppliers WHERE id IN ({placeholders})",
                supplier_ids,
            ).fetchall()
            suppliers_by_id = {row["id"]: row for row in supplier_rows}
        suggestion_ids = [row["id"] for row in rows]
        lines_by_suggestion = _get_purchase_suggestion_lines(conn, suggestion_ids)
        results: list[models.PurchaseSuggestionDetail] = []
        for row in rows:
            supplier_row = (
                suppliers_by_id.get(row["supplier_id"])
                if row["supplier_id"] is not None
                else None
            )
            supplier_display, supplier_email, supplier_status = _resolve_suggestion_supplier_payload(
                supplier_row
            )
            results.append(
                models.PurchaseSuggestionDetail(
                    id=row["id"],
                    site_key=row["site_key"],
                    module_key=row["module_key"],
                    supplier_id=row["supplier_id"],
                    supplier_name=supplier_display,
                    supplier_display=supplier_display,
                    supplier_email=supplier_email,
                    supplier_status=supplier_status,
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    created_by=row["created_by"],
                    lines=lines_by_suggestion.get(row["id"], []),
                )
            )
        return results


def get_purchase_suggestion(suggestion_id: int) -> models.PurchaseSuggestionDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT ps.*
            FROM purchase_suggestions AS ps
            WHERE ps.id = ?
            """,
            (suggestion_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Suggestion introuvable")
        supplier_row = None
        if row["supplier_id"] is not None:
            supplier_row = conn.execute(
                "SELECT * FROM suppliers WHERE id = ?",
                (row["supplier_id"],),
            ).fetchone()
        supplier_display, supplier_email, supplier_status = _resolve_suggestion_supplier_payload(
            supplier_row
        )
        lines_by_suggestion = _get_purchase_suggestion_lines(conn, [suggestion_id])
        return models.PurchaseSuggestionDetail(
            id=row["id"],
            site_key=row["site_key"],
            module_key=row["module_key"],
            supplier_id=row["supplier_id"],
            supplier_name=supplier_display,
            supplier_display=supplier_display,
            supplier_email=supplier_email,
            supplier_status=supplier_status,
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row["created_by"],
            lines=lines_by_suggestion.get(suggestion_id, []),
        )


def refresh_purchase_suggestions(
    *, site_key: str, module_keys: Iterable[str], created_by: str | None = None
) -> list[models.PurchaseSuggestionDetail]:
    ensure_database_ready()
    safety_buffer = _get_purchase_suggestions_safety_buffer()
    module_list = [module for module in module_keys if module in _PURCHASE_SUGGESTION_MODULES]
    if not module_list:
        return []
    migrate_legacy_suppliers_to_site(site_key)
    with _get_site_stock_conn(site_key) as conn:
        for module_key in module_list:
            candidates = _get_reorder_candidates(conn, module_key, safety_buffer)
            grouped: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
            for candidate in candidates:
                grouped[candidate["supplier_id"]].append(candidate)
            existing_rows = conn.execute(
                """
                SELECT id, supplier_id
                FROM purchase_suggestions
                WHERE site_key = ? AND module_key = ? AND status = 'draft'
                """,
                (site_key, module_key),
            ).fetchall()
            existing_by_supplier: dict[int | None, int] = {
                row["supplier_id"]: row["id"] for row in existing_rows
            }
            processed_suppliers: set[int | None] = set()
            for supplier_id, items in grouped.items():
                processed_suppliers.add(supplier_id)
                suggestion_id = existing_by_supplier.get(supplier_id)
                if suggestion_id is None:
                    cur = conn.execute(
                        """
                        INSERT INTO purchase_suggestions (
                            site_key, module_key, supplier_id, status, created_at, updated_at, created_by
                        )
                        VALUES (?, ?, ?, 'draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (site_key, module_key, supplier_id, created_by),
                    )
                    suggestion_id = int(cur.lastrowid)
                else:
                    conn.execute(
                        """
                        UPDATE purchase_suggestions
                        SET updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (suggestion_id,),
                    )
                current_item_ids = {item["item_id"] for item in items}
                for item in items:
                    row = conn.execute(
                        """
                        SELECT id, qty_final, qty_suggested
                        FROM purchase_suggestion_lines
                        WHERE suggestion_id = ? AND item_id = ?
                        """,
                        (suggestion_id, item["item_id"]),
                    ).fetchone()
                    if row is None:
                        conn.execute(
                            """
                            INSERT INTO purchase_suggestion_lines (
                                suggestion_id, item_id, sku, label, qty_suggested, qty_final, unit, reason,
                                stock_current, threshold
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                suggestion_id,
                                item["item_id"],
                                item["sku"],
                                item["label"],
                                item["qty_suggested"],
                                item["qty_final"],
                                item["unit"],
                                item["reason"],
                                item["stock_current"],
                                item["threshold"],
                            ),
                        )
                        continue
                    previous_suggested = row["qty_suggested"]
                    previous_final = row["qty_final"]
                    next_final = previous_final
                    if previous_final == previous_suggested:
                        next_final = item["qty_final"]
                    conn.execute(
                        """
                        UPDATE purchase_suggestion_lines
                        SET sku = ?, label = ?, qty_suggested = ?, qty_final = ?, unit = ?, reason = ?,
                            stock_current = ?, threshold = ?
                        WHERE id = ?
                        """,
                        (
                            item["sku"],
                            item["label"],
                            item["qty_suggested"],
                            next_final,
                            item["unit"],
                            item["reason"],
                            item["stock_current"],
                            item["threshold"],
                            row["id"],
                        ),
                    )
                if current_item_ids:
                    placeholders = ", ".join("?" for _ in current_item_ids)
                    conn.execute(
                        f"""
                        DELETE FROM purchase_suggestion_lines
                        WHERE suggestion_id = ? AND item_id NOT IN ({placeholders})
                        """,
                        (suggestion_id, *current_item_ids),
                    )
                else:
                    conn.execute(
                        "DELETE FROM purchase_suggestion_lines WHERE suggestion_id = ?",
                        (suggestion_id,),
                    )
            for row in existing_rows:
                if row["supplier_id"] in processed_suppliers:
                    continue
                conn.execute(
                    """
                    UPDATE purchase_suggestions
                    SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (row["id"],),
                )
                conn.execute(
                    "DELETE FROM purchase_suggestion_lines WHERE suggestion_id = ?",
                    (row["id"],),
                )
        conn.commit()
    return list_purchase_suggestions(
        site_key=site_key,
        module_key=None,
        status="draft",
        allowed_modules=module_list,
    )


def update_purchase_suggestion_lines(
    suggestion_id: int, payload: models.PurchaseSuggestionUpdatePayload
) -> models.PurchaseSuggestionDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT status FROM purchase_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Suggestion introuvable")
        if row["status"] != "draft":
            raise ValueError("Suggestion non modifiable")
        for line in payload.lines:
            if line.remove:
                conn.execute(
                    "DELETE FROM purchase_suggestion_lines WHERE id = ? AND suggestion_id = ?",
                    (line.id, suggestion_id),
                )
                continue
            if line.qty_final is not None:
                conn.execute(
                    """
                    UPDATE purchase_suggestion_lines
                    SET qty_final = ?
                    WHERE id = ? AND suggestion_id = ?
                    """,
                    (line.qty_final, line.id, suggestion_id),
                )
        remaining = conn.execute(
            "SELECT COUNT(1) AS total FROM purchase_suggestion_lines WHERE suggestion_id = ?",
            (suggestion_id,),
        ).fetchone()
        if remaining and remaining["total"] == 0:
            conn.execute(
                """
                UPDATE purchase_suggestions
                SET status = 'dismissed', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (suggestion_id,),
            )
        else:
            conn.execute(
                "UPDATE purchase_suggestions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (suggestion_id,),
            )
        conn.commit()
    return get_purchase_suggestion(suggestion_id)


def convert_purchase_suggestion_to_po(
    suggestion_id: int, user: models.User
) -> models.PurchaseSuggestionConvertResult:
    suggestion = get_purchase_suggestion(suggestion_id)
    if suggestion.status != "draft":
        raise ValueError("Suggestion déjà traitée")
    if suggestion.supplier_id is None:
        raise ValueError("Fournisseur introuvable")
    try:
        resolve_supplier(suggestion.site_key, suggestion.supplier_id)
    except SupplierResolutionError as exc:
        raise ValueError(exc.message) from exc
    valid_lines = [line for line in suggestion.lines if line.qty_final > 0]
    if not valid_lines:
        raise ValueError("Aucune ligne valide pour créer le bon de commande")
    if suggestion.module_key == "clothing":
        payload = models.PurchaseOrderCreate(
            supplier_id=suggestion.supplier_id,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=line.item_id, quantity_ordered=line.qty_final
                )
                for line in valid_lines
            ],
        )
        order = create_purchase_order(payload)
    elif suggestion.module_key == "pharmacy":
        payload = models.PharmacyPurchaseOrderCreate(
            supplier_id=suggestion.supplier_id,
            items=[
                models.PharmacyPurchaseOrderItemInput(
                    pharmacy_item_id=line.item_id, quantity_ordered=line.qty_final
                )
                for line in valid_lines
            ],
        )
        order = create_pharmacy_purchase_order(payload)
    elif suggestion.module_key == "inventory_remise":
        payload = models.RemisePurchaseOrderCreate(
            supplier_id=suggestion.supplier_id,
            items=[
                models.RemisePurchaseOrderItemInput(
                    remise_item_id=line.item_id, quantity_ordered=line.qty_final
                )
                for line in valid_lines
            ],
        )
        order = create_remise_purchase_order(payload)
    else:
        raise ValueError("Module de suggestion inconnu")
    with db.get_stock_connection() as conn:
        conn.execute(
            """
            UPDATE purchase_suggestions
            SET status = 'converted', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (suggestion_id,),
        )
        conn.commit()
    return models.PurchaseSuggestionConvertResult(
        suggestion_id=suggestion_id,
        purchase_order_id=order.id,
        module_key=suggestion.module_key,
    )


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


def _normalize_custom_field_scope(scope: str) -> str:
    normalized = scope.strip()
    if not normalized:
        raise ValueError("Le scope est obligatoire")
    return normalized


def _normalize_custom_field_key(key: str) -> str:
    normalized = key.strip()
    if not normalized:
        raise ValueError("La clé du champ est obligatoire")
    return normalized


def _normalize_custom_field_label(label: str) -> str:
    normalized = label.strip()
    if not normalized:
        raise ValueError("Le libellé est obligatoire")
    return normalized


def _normalize_custom_field_type(field_type: str) -> str:
    normalized = field_type.strip().lower()
    allowed = {"text", "number", "date", "bool", "select"}
    if normalized not in allowed:
        raise ValueError("Type de champ personnalisé invalide")
    return normalized


def _load_custom_field_definitions(
    conn: sqlite3.Connection,
    scope: str,
    *,
    active_only: bool = True,
) -> list[models.CustomFieldDefinition]:
    normalized_scope = _normalize_custom_field_scope(scope)
    query = (
        "SELECT * FROM custom_field_definitions WHERE scope = ?"
        + (" AND is_active = 1" if active_only else "")
        + " ORDER BY sort_order, label COLLATE NOCASE"
    )
    rows = conn.execute(query, (normalized_scope,)).fetchall()
    definitions: list[models.CustomFieldDefinition] = []
    for row in rows:
        default_json = None
        options_json = None
        if row["default_json"]:
            try:
                default_json = json.loads(row["default_json"])
            except json.JSONDecodeError:
                default_json = None
        if row["options_json"]:
            try:
                options_json = json.loads(row["options_json"])
            except json.JSONDecodeError:
                options_json = None
        definitions.append(
            models.CustomFieldDefinition(
                id=row["id"],
                scope=row["scope"],
                key=row["key"],
                label=row["label"],
                field_type=row["field_type"],
                required=bool(row["required"]),
                default_json=default_json,
                options_json=options_json,
                is_active=bool(row["is_active"]),
                sort_order=row["sort_order"],
            )
        )
    return definitions


def get_custom_fields(scope: str) -> list[models.CustomFieldDefinition]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        return _load_custom_field_definitions(conn, scope, active_only=True)


def validate_and_merge_extra(
    scope: str,
    extra_json: str | None,
    payload_extra: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = _parse_extra_json(extra_json)
    if payload_extra is None:
        return existing
    if not isinstance(payload_extra, dict):
        raise ValueError("Les champs personnalisés doivent être un objet JSON")
    with db.get_stock_connection() as conn:
        definitions = _load_custom_field_definitions(conn, scope, active_only=True)
    definitions_by_key = {definition.key: definition for definition in definitions}
    for key in payload_extra:
        if key not in definitions_by_key:
            raise ValueError(f"Champ personnalisé inconnu: {key}")
    merged = {**existing, **payload_extra}
    for definition in definitions:
        raw_value = merged.get(definition.key)
        if raw_value is None and definition.default_json is not None:
            merged[definition.key] = definition.default_json
            raw_value = merged.get(definition.key)
        if raw_value is None:
            if definition.required:
                raise ValueError(f"Champ personnalisé requis: {definition.key}")
            merged.pop(definition.key, None)
            continue
        field_type = definition.field_type
        if field_type == "text":
            if not isinstance(raw_value, str):
                raise ValueError(f"Champ {definition.key} invalide")
            if definition.required and not raw_value.strip():
                raise ValueError(f"Champ personnalisé requis: {definition.key}")
        elif field_type == "number":
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise ValueError(f"Champ {definition.key} invalide")
        elif field_type == "date":
            if not isinstance(raw_value, str):
                raise ValueError(f"Champ {definition.key} invalide")
            try:
                date.fromisoformat(raw_value)
            except ValueError as exc:
                raise ValueError(f"Champ {definition.key} invalide") from exc
        elif field_type == "bool":
            if not isinstance(raw_value, bool):
                raise ValueError(f"Champ {definition.key} invalide")
        elif field_type == "select":
            options = definition.options_json
            if options is not None and isinstance(options, list):
                if raw_value not in options:
                    raise ValueError(f"Champ {definition.key} invalide")
        else:
            raise ValueError(f"Type de champ personnalisé invalide: {field_type}")
    return merged


def list_vehicle_types() -> list[models.VehicleTypeEntry]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        rows = conn.execute(
            "SELECT id, code, label, is_active, created_at FROM vehicle_types ORDER BY label COLLATE NOCASE"
        ).fetchall()
    return [
        models.VehicleTypeEntry(
            id=row["id"],
            code=row["code"],
            label=row["label"],
            is_active=bool(row["is_active"]),
            created_at=_coerce_datetime(row["created_at"]),
        )
        for row in rows
    ]


def create_vehicle_type(payload: models.VehicleTypeCreate) -> models.VehicleTypeEntry:
    ensure_database_ready()
    code = payload.code.strip()
    label = payload.label.strip()
    if not code:
        raise ValueError("Le code du type de véhicule est obligatoire")
    if not label:
        raise ValueError("Le libellé du type de véhicule est obligatoire")
    with db.get_stock_connection() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO vehicle_types (code, label, is_active)
                VALUES (?, ?, ?)
                """,
                (code, label, int(payload.is_active)),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ce code de véhicule est déjà utilisé") from exc
        vehicle_type_id = cur.lastrowid
        conn.commit()
    return get_vehicle_type(vehicle_type_id)


def get_vehicle_type(vehicle_type_id: int) -> models.VehicleTypeEntry:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT id, code, label, is_active, created_at FROM vehicle_types WHERE id = ?",
            (vehicle_type_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Type de véhicule introuvable")
    return models.VehicleTypeEntry(
        id=row["id"],
        code=row["code"],
        label=row["label"],
        is_active=bool(row["is_active"]),
        created_at=_coerce_datetime(row["created_at"]),
    )


def update_vehicle_type(
    vehicle_type_id: int, payload: models.VehicleTypeUpdate
) -> models.VehicleTypeEntry:
    ensure_database_ready()
    updates: list[str] = []
    values: list[object] = []
    if payload.code is not None:
        code = payload.code.strip()
        if not code:
            raise ValueError("Le code du type de véhicule est obligatoire")
        updates.append("code = ?")
        values.append(code)
    if payload.label is not None:
        label = payload.label.strip()
        if not label:
            raise ValueError("Le libellé du type de véhicule est obligatoire")
        updates.append("label = ?")
        values.append(label)
    if payload.is_active is not None:
        updates.append("is_active = ?")
        values.append(int(payload.is_active))
    if not updates:
        return get_vehicle_type(vehicle_type_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id FROM vehicle_types WHERE id = ?", (vehicle_type_id,))
        if cur.fetchone() is None:
            raise ValueError("Type de véhicule introuvable")
        values.append(vehicle_type_id)
        try:
            conn.execute(
                f"UPDATE vehicle_types SET {', '.join(updates)} WHERE id = ?",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ce code de véhicule est déjà utilisé") from exc
        conn.commit()
    return get_vehicle_type(vehicle_type_id)


def delete_vehicle_type(vehicle_type_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id FROM vehicle_types WHERE id = ?", (vehicle_type_id,))
        if cur.fetchone() is None:
            raise ValueError("Type de véhicule introuvable")
        conn.execute("UPDATE vehicle_types SET is_active = 0 WHERE id = ?", (vehicle_type_id,))
        conn.commit()


def list_custom_field_definitions(scope: str | None = None) -> list[models.CustomFieldDefinition]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        if scope:
            return _load_custom_field_definitions(conn, scope, active_only=False)
        rows = conn.execute(
            "SELECT * FROM custom_field_definitions ORDER BY scope, sort_order, label COLLATE NOCASE"
        ).fetchall()
        definitions: list[models.CustomFieldDefinition] = []
        for row in rows:
            default_json = None
            options_json = None
            if row["default_json"]:
                try:
                    default_json = json.loads(row["default_json"])
                except json.JSONDecodeError:
                    default_json = None
            if row["options_json"]:
                try:
                    options_json = json.loads(row["options_json"])
                except json.JSONDecodeError:
                    options_json = None
            definitions.append(
                models.CustomFieldDefinition(
                    id=row["id"],
                    scope=row["scope"],
                    key=row["key"],
                    label=row["label"],
                    field_type=row["field_type"],
                    required=bool(row["required"]),
                    default_json=default_json,
                    options_json=options_json,
                    is_active=bool(row["is_active"]),
                    sort_order=row["sort_order"],
                )
            )
        return definitions


def create_custom_field_definition(
    payload: models.CustomFieldDefinitionCreate,
) -> models.CustomFieldDefinition:
    ensure_database_ready()
    scope = _normalize_custom_field_scope(payload.scope)
    key = _normalize_custom_field_key(payload.key)
    label = _normalize_custom_field_label(payload.label)
    field_type = _normalize_custom_field_type(payload.field_type)
    default_json = (
        json.dumps(payload.default_json, ensure_ascii=False)
        if payload.default_json is not None
        else None
    )
    options_json = (
        json.dumps(payload.options_json, ensure_ascii=False)
        if payload.options_json is not None
        else None
    )
    with db.get_stock_connection() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO custom_field_definitions (
                    scope, key, label, field_type, required, default_json, options_json, is_active, sort_order
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    key,
                    label,
                    field_type,
                    int(payload.required),
                    default_json,
                    options_json,
                    int(payload.is_active),
                    payload.sort_order,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ce champ personnalisé existe déjà") from exc
        custom_field_id = cur.lastrowid
        conn.commit()
    return get_custom_field_definition(custom_field_id)


def get_custom_field_definition(custom_field_id: int) -> models.CustomFieldDefinition:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT * FROM custom_field_definitions WHERE id = ?",
            (custom_field_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Champ personnalisé introuvable")
    default_json = None
    options_json = None
    if row["default_json"]:
        try:
            default_json = json.loads(row["default_json"])
        except json.JSONDecodeError:
            default_json = None
    if row["options_json"]:
        try:
            options_json = json.loads(row["options_json"])
        except json.JSONDecodeError:
            options_json = None
    return models.CustomFieldDefinition(
        id=row["id"],
        scope=row["scope"],
        key=row["key"],
        label=row["label"],
        field_type=row["field_type"],
        required=bool(row["required"]),
        default_json=default_json,
        options_json=options_json,
        is_active=bool(row["is_active"]),
        sort_order=row["sort_order"],
    )


def update_custom_field_definition(
    custom_field_id: int,
    payload: models.CustomFieldDefinitionUpdate,
) -> models.CustomFieldDefinition:
    ensure_database_ready()
    updates: list[str] = []
    values: list[object] = []
    if payload.scope is not None:
        updates.append("scope = ?")
        values.append(_normalize_custom_field_scope(payload.scope))
    if payload.key is not None:
        updates.append("key = ?")
        values.append(_normalize_custom_field_key(payload.key))
    if payload.label is not None:
        updates.append("label = ?")
        values.append(_normalize_custom_field_label(payload.label))
    if payload.field_type is not None:
        updates.append("field_type = ?")
        values.append(_normalize_custom_field_type(payload.field_type))
    if payload.required is not None:
        updates.append("required = ?")
        values.append(int(payload.required))
    if payload.default_json is not None:
        updates.append("default_json = ?")
        values.append(json.dumps(payload.default_json, ensure_ascii=False))
    if payload.options_json is not None:
        updates.append("options_json = ?")
        values.append(json.dumps(payload.options_json, ensure_ascii=False))
    if payload.is_active is not None:
        updates.append("is_active = ?")
        values.append(int(payload.is_active))
    if payload.sort_order is not None:
        updates.append("sort_order = ?")
        values.append(payload.sort_order)
    if not updates:
        return get_custom_field_definition(custom_field_id)
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id FROM custom_field_definitions WHERE id = ?", (custom_field_id,))
        if cur.fetchone() is None:
            raise ValueError("Champ personnalisé introuvable")
        values.append(custom_field_id)
        try:
            conn.execute(
                f"UPDATE custom_field_definitions SET {', '.join(updates)} WHERE id = ?",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ce champ personnalisé existe déjà") from exc
        conn.commit()
    return get_custom_field_definition(custom_field_id)


def delete_custom_field_definition(custom_field_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id FROM custom_field_definitions WHERE id = ?", (custom_field_id,))
        if cur.fetchone() is None:
            raise ValueError("Champ personnalisé introuvable")
        conn.execute(
            "UPDATE custom_field_definitions SET is_active = 0 WHERE id = ?",
            (custom_field_id,),
        )
        conn.commit()


def list_link_categories(module: str, *, include_inactive: bool = True) -> list[models.LinkCategory]:
    ensure_database_ready()
    module = _validate_link_module(module)
    with db.get_stock_connection() as conn:
        rows = _fetch_link_categories(conn, module, active_only=not include_inactive)
        return [
            models.LinkCategory(
                id=row["id"],
                module=row["module"],
                key=row["key"],
                label=row["label"],
                placeholder=row["placeholder"],
                help_text=row["help_text"],
                is_required=bool(row["is_required"]),
                sort_order=int(row["sort_order"] or 0),
                is_active=bool(row["is_active"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]


def create_link_category(payload: models.LinkCategoryCreate) -> models.LinkCategory:
    ensure_database_ready()
    module = _validate_link_module(payload.module)
    key = _normalize_link_key(payload.key)
    with db.get_stock_connection() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO link_categories (
                    module,
                    key,
                    label,
                    placeholder,
                    help_text,
                    is_required,
                    sort_order,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    module,
                    key,
                    payload.label.strip(),
                    payload.placeholder,
                    payload.help_text,
                    int(payload.is_required),
                    int(payload.sort_order),
                    int(payload.is_active),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Cette catégorie de lien existe déjà") from exc
        category_id = cur.lastrowid
    return get_link_category(category_id)


def get_link_category(category_id: int) -> models.LinkCategory:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT id,
                   module,
                   key,
                   label,
                   placeholder,
                   help_text,
                   is_required,
                   sort_order,
                   is_active,
                   created_at,
                   updated_at
            FROM link_categories
            WHERE id = ?
            """,
            (category_id,),
        ).fetchone()
    if row is None:
        raise ValueError("Catégorie de lien introuvable")
    return models.LinkCategory(
        id=row["id"],
        module=row["module"],
        key=row["key"],
        label=row["label"],
        placeholder=row["placeholder"],
        help_text=row["help_text"],
        is_required=bool(row["is_required"]),
        sort_order=int(row["sort_order"] or 0),
        is_active=bool(row["is_active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def update_link_category(
    category_id: int, payload: models.LinkCategoryUpdate
) -> models.LinkCategory:
    ensure_database_ready()
    updates: list[str] = []
    values: list[Any] = []
    if payload.module is not None:
        module = _validate_link_module(payload.module)
        updates.append("module = ?")
        values.append(module)
    if payload.key is not None:
        updates.append("key = ?")
        values.append(_normalize_link_key(payload.key))
    if payload.label is not None:
        updates.append("label = ?")
        values.append(payload.label.strip())
    if payload.placeholder is not None:
        updates.append("placeholder = ?")
        values.append(payload.placeholder)
    if payload.help_text is not None:
        updates.append("help_text = ?")
        values.append(payload.help_text)
    if payload.is_required is not None:
        updates.append("is_required = ?")
        values.append(int(payload.is_required))
    if payload.sort_order is not None:
        updates.append("sort_order = ?")
        values.append(int(payload.sort_order))
    if payload.is_active is not None:
        updates.append("is_active = ?")
        values.append(int(payload.is_active))

    if not updates:
        return get_link_category(category_id)

    updates.append("updated_at = CURRENT_TIMESTAMP")
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id FROM link_categories WHERE id = ?", (category_id,))
        if cur.fetchone() is None:
            raise ValueError("Catégorie de lien introuvable")
        values.append(category_id)
        try:
            conn.execute(
                f"UPDATE link_categories SET {', '.join(updates)} WHERE id = ?",
                tuple(values),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Cette catégorie de lien existe déjà") from exc
    return get_link_category(category_id)


def delete_link_category(category_id: int) -> None:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT id FROM link_categories WHERE id = ?", (category_id,))
        if cur.fetchone() is None:
            raise ValueError("Catégorie de lien introuvable")
        conn.execute(
            "UPDATE link_categories SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (category_id,),
        )
        conn.commit()


def get_item_links(module: str, item_id: int) -> list[models.LinkCategoryValue]:
    ensure_database_ready()
    module = _validate_link_module(module)
    config = _LINK_MODULE_CONFIG[module]
    item_table = config["item_table"]
    item_id_column = config["item_id_column"]
    legacy_map: dict[str, str] = config["legacy_map"]
    with db.get_stock_connection() as conn:
        legacy_columns = [column for column in legacy_map.values()]
        select_columns = ", ".join(["id"] + legacy_columns)
        row = conn.execute(
            f"SELECT {select_columns} FROM {item_table} WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        categories = conn.execute(
            """
            SELECT id,
                   key,
                   label,
                   placeholder,
                   help_text,
                   is_required,
                   sort_order
            FROM link_categories
            WHERE module = ? AND is_active = 1
            ORDER BY sort_order, label COLLATE NOCASE
            """,
            (module,),
        ).fetchall()
        if not categories:
            return []
        link_rows = conn.execute(
            f"""
            SELECT category_id, url
            FROM {config['link_table']}
            WHERE {item_id_column} = ?
            """,
            (item_id,),
        ).fetchall()
        link_map = {entry["category_id"]: entry["url"] for entry in link_rows}
        results: list[models.LinkCategoryValue] = []
        for category in categories:
            url_value = link_map.get(category["id"], "") or ""
            if (
                not url_value
                and module == "vehicle_qr"
                and category["key"] in legacy_map
                and legacy_map[category["key"]] in row.keys()
            ):
                url_value = row[legacy_map[category["key"]]] or ""
            results.append(
                models.LinkCategoryValue(
                    category_key=category["key"],
                    label=category["label"],
                    placeholder=category["placeholder"],
                    help_text=category["help_text"],
                    is_required=bool(category["is_required"]),
                    sort_order=int(category["sort_order"] or 0),
                    url=url_value,
                )
            )
        return results


def save_item_links(
    module: str, item_id: int, links: list[models.LinkItemEntry]
) -> list[models.LinkCategoryValue]:
    ensure_database_ready()
    module = _validate_link_module(module)
    config = _LINK_MODULE_CONFIG[module]
    item_table = config["item_table"]
    item_id_column = config["item_id_column"]
    legacy_map: dict[str, str] = config["legacy_map"]
    payload_map: dict[str, str] = {}
    for entry in links:
        key = _normalize_link_key(entry.category_key)
        if key in payload_map:
            raise ValueError("Catégorie de lien dupliquée")
        payload_map[key] = entry.url or ""

    with db.get_stock_connection() as conn:
        row = conn.execute(
            f"SELECT id FROM {item_table} WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Article introuvable")
        categories = conn.execute(
            """
            SELECT id,
                   key,
                   label,
                   is_required
            FROM link_categories
            WHERE module = ? AND is_active = 1
            ORDER BY sort_order, label COLLATE NOCASE
            """,
            (module,),
        ).fetchall()
        category_map = {category["key"]: category for category in categories}
        for key in payload_map:
            if key not in category_map:
                raise ValueError("Catégorie de lien inconnue")
        rows_to_save: list[tuple[int, int, str]] = []
        normalized_values: dict[str, str] = {}
        for category in categories:
            raw_value = payload_map.get(category["key"], "")
            normalized_value = _validate_link_url(
                raw_value, is_required=bool(category["is_required"])
            )
            rows_to_save.append((item_id, category["id"], normalized_value))
            normalized_values[category["key"]] = normalized_value

        if rows_to_save:
            conn.executemany(
                f"""
                INSERT INTO {config['link_table']} ({item_id_column}, category_id, url, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT({item_id_column}, category_id)
                DO UPDATE SET url = excluded.url, updated_at = CURRENT_TIMESTAMP
                """,
                rows_to_save,
            )

        if module == "vehicle_qr" and legacy_map:
            legacy_updates: list[str] = []
            legacy_values: list[Any] = []
            for key, column in legacy_map.items():
                if key in normalized_values:
                    legacy_updates.append(f"{column} = ?")
                    legacy_values.append(normalized_values[key] or None)
            if legacy_updates:
                legacy_values.append(item_id)
                conn.execute(
                    f"UPDATE vehicle_items SET {', '.join(legacy_updates)} WHERE id = ?",
                    tuple(legacy_values),
                )
        conn.commit()
    return get_item_links(module, item_id)


def ensure_database_ready() -> None:
    global _db_initialized
    if _db_initialized:
        return

    with _db_init_lock:
        if _db_initialized:
            return
        with _migration_lock():
            db.init_databases()
            apply_site_schema_migrations()

        _restore_inventory_snapshots()
        seed_default_admin()
        from backend.services import system_settings

        system_settings.seed_default_system_settings()
        _db_initialized = True


def ensure_site_database_ready(site_key: str) -> None:
    """Assure que la base d'un site est migrée, sans modifier l'état global."""

    with _db_init_lock:
        with _migration_lock():
            db.init_databases()
            _apply_schema_migrations_for_site(site_key)


def is_missing_table_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "no such table" in message


@contextmanager
def _migration_lock() -> Iterator[None]:
    while True:
        try:
            fd = os.open(_MIGRATION_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as lock_file:
                lock_file.write(str(os.getpid()))
            break
        except FileExistsError:
            time.sleep(_MIGRATION_LOCK_SLEEP_SECONDS)
    try:
        yield
    finally:
        try:
            _MIGRATION_LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def _run_migration_with_retry(operation: Callable[[], T]) -> T:
    delay = _MIGRATION_RETRY_BASE_DELAY_SECONDS
    for attempt in range(_MIGRATION_RETRY_ATTEMPTS):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "database is locked" not in message and "database schema is locked" not in message:
                raise
            if attempt >= _MIGRATION_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("Migration retry loop exhausted unexpectedly.")


def _execute_with_retry(
    conn: sqlite3.Connection, statement: str, params: tuple[Any, ...] = ()
) -> sqlite3.Cursor:
    return _run_migration_with_retry(lambda: conn.execute(statement, params))


def _executemany_with_retry(
    conn: sqlite3.Connection, statement: str, params: Iterable[tuple[Any, ...]]
) -> sqlite3.Cursor:
    return _run_migration_with_retry(lambda: conn.executemany(statement, params))


def _executescript_with_retry(conn: sqlite3.Connection, script: str) -> sqlite3.Cursor:
    return _run_migration_with_retry(lambda: conn.executescript(script))


def _parse_extra_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _dump_extra_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _validate_link_module(module: str) -> str:
    module = _LINK_MODULE_ALIASES.get(module, module)
    if module not in _LINK_MODULE_CONFIG:
        raise ValueError("Module de lien invalide")
    return module


def _normalize_link_key(value: str) -> str:
    return value.strip()


def _validate_link_url(value: str, *, is_required: bool) -> str:
    trimmed = value.strip()
    if not trimmed:
        if is_required:
            raise ValueError("Lien requis")
        return ""
    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Lien invalide (HTTP/HTTPS requis)")
    return trimmed


def _fetch_link_categories(
    conn: sqlite3.Connection, module: str, *, active_only: bool
) -> list[sqlite3.Row]:
    clause = " AND is_active = 1" if active_only else ""
    return conn.execute(
        f"""
        SELECT id,
               module,
               key,
               label,
               placeholder,
               help_text,
               is_required,
               sort_order,
               is_active,
               created_at,
               updated_at
        FROM link_categories
        WHERE module = ?{clause}
        ORDER BY sort_order, label COLLATE NOCASE
        """,
        (module,),
    ).fetchall()


def _ensure_vehicle_item_columns(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    vehicle_item_info = execute("PRAGMA table_info(vehicle_items)").fetchall()
    vehicle_item_columns = {row["name"] for row in vehicle_item_info}

    if "image_path" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN image_path TEXT")
    if "position_x" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN position_x REAL")
    if "position_y" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN position_y REAL")
    if "remise_item_id" not in vehicle_item_columns:
        execute(
            "ALTER TABLE vehicle_items ADD COLUMN remise_item_id INTEGER REFERENCES remise_items(id) ON DELETE SET NULL"
        )
    if "documentation_url" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN documentation_url TEXT")
    if "tutorial_url" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN tutorial_url TEXT")
    if "shared_file_url" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN shared_file_url TEXT")
    if "lot_id" not in vehicle_item_columns:
        execute(
            "ALTER TABLE vehicle_items ADD COLUMN lot_id INTEGER REFERENCES remise_lots(id) ON DELETE SET NULL"
        )
    if "show_in_qr" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN show_in_qr INTEGER NOT NULL DEFAULT 1")

    if "vehicle_type" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN vehicle_type TEXT")

    if "pharmacy_item_id" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN pharmacy_item_id INTEGER REFERENCES pharmacy_items(id)")
    if "extra_json" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")
    if "applied_lot_source" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN applied_lot_source TEXT")
    if "applied_lot_assignment_id" not in vehicle_item_columns:
        execute(
            "ALTER TABLE vehicle_items ADD COLUMN applied_lot_assignment_id INTEGER REFERENCES vehicle_applied_lots(id) ON DELETE SET NULL"
        )


def _ensure_vehicle_applied_lot_table(
    conn: sqlite3.Connection, executescript: Callable[[str], sqlite3.Cursor] | None = None
) -> None:
    if executescript is None:
        executescript = conn.executescript
    executescript(
        """
        CREATE TABLE IF NOT EXISTS vehicle_applied_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL REFERENCES vehicle_categories(id) ON DELETE CASCADE,
            vehicle_type TEXT,
            view TEXT,
            source TEXT NOT NULL,
            pharmacy_lot_id INTEGER REFERENCES pharmacy_lots(id) ON DELETE SET NULL,
            lot_name TEXT,
            position_x REAL,
            position_y REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_vehicle_applied_lots_vehicle
        ON vehicle_applied_lots(vehicle_id);
        CREATE INDEX IF NOT EXISTS idx_vehicle_applied_lots_view
        ON vehicle_applied_lots(view);
        """
    )


def _ensure_vehicle_category_columns(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    category_info = execute("PRAGMA table_info(vehicle_categories)").fetchall()
    category_columns = {row["name"] for row in category_info}

    if "vehicle_type" not in category_columns:
        execute("ALTER TABLE vehicle_categories ADD COLUMN vehicle_type TEXT")
    if "extra_json" not in category_columns:
        execute("ALTER TABLE vehicle_categories ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")


def _ensure_vehicle_view_settings_columns(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    view_settings_info = execute("PRAGMA table_info(vehicle_view_settings)").fetchall()
    view_settings_columns = {row["name"] for row in view_settings_info}

    if "pointer_mode_enabled" not in view_settings_columns:
        execute(
            "ALTER TABLE vehicle_view_settings ADD COLUMN pointer_mode_enabled INTEGER NOT NULL DEFAULT 0"
        )

    if "hide_edit_buttons" not in view_settings_columns:
        execute(
            "ALTER TABLE vehicle_view_settings ADD COLUMN hide_edit_buttons INTEGER NOT NULL DEFAULT 0"
        )


def _ensure_remise_item_columns(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    remise_item_info = execute("PRAGMA table_info(remise_items)").fetchall()
    remise_item_columns = {row["name"] for row in remise_item_info}

    if "track_low_stock" not in remise_item_columns:
        execute(
            "ALTER TABLE remise_items ADD COLUMN track_low_stock INTEGER NOT NULL DEFAULT 1"
        )
    if "expiration_date" not in remise_item_columns:
        execute("ALTER TABLE remise_items ADD COLUMN expiration_date TEXT")
    if "extra_json" not in remise_item_columns:
        execute("ALTER TABLE remise_items ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")


def _ensure_remise_lot_columns(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    lot_info = execute("PRAGMA table_info(remise_lots)").fetchall()
    lot_columns = {row["name"] for row in lot_info}

    if "image_path" not in lot_columns:
        execute("ALTER TABLE remise_lots ADD COLUMN image_path TEXT")
    if "extra_json" not in lot_columns:
        execute("ALTER TABLE remise_lots ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")


def _ensure_pharmacy_lot_columns(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    lot_info = execute("PRAGMA table_info(pharmacy_lots)").fetchall()
    lot_columns = {row["name"] for row in lot_info}

    if "image_path" not in lot_columns:
        execute("ALTER TABLE pharmacy_lots ADD COLUMN image_path TEXT")
    if "extra_json" not in lot_columns:
        execute("ALTER TABLE pharmacy_lots ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")


def _ensure_pharmacy_lot_item_columns(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
    executescript: Callable[[str], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    if executescript is None:
        executescript = conn.executescript
    lot_item_info = execute("PRAGMA table_info(pharmacy_lot_items)").fetchall()
    if not lot_item_info:
        return
    lot_item_columns = {row["name"] for row in lot_item_info}
    if "compartment_name" in lot_item_columns:
        return
    executescript(
        """
        CREATE TABLE IF NOT EXISTS pharmacy_lot_items_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_id INTEGER NOT NULL REFERENCES pharmacy_lots(id) ON DELETE CASCADE,
            pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            compartment_name TEXT,
            UNIQUE(lot_id, pharmacy_item_id, compartment_name)
        );
        INSERT INTO pharmacy_lot_items_new (id, lot_id, pharmacy_item_id, quantity, compartment_name)
        SELECT id, lot_id, pharmacy_item_id, quantity, NULL
        FROM pharmacy_lot_items;
        DROP TABLE pharmacy_lot_items;
        ALTER TABLE pharmacy_lot_items_new RENAME TO pharmacy_lot_items;
        CREATE INDEX IF NOT EXISTS idx_pharmacy_lot_items_lot ON pharmacy_lot_items(lot_id);
        CREATE INDEX IF NOT EXISTS idx_pharmacy_lot_items_item ON pharmacy_lot_items(pharmacy_item_id);
        """
    )


def _ensure_link_tables(
    conn: sqlite3.Connection, executescript: Callable[[str], sqlite3.Cursor] | None = None
) -> None:
    if executescript is None:
        executescript = conn.executescript
    executescript(
        """
        CREATE TABLE IF NOT EXISTS link_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            key TEXT NOT NULL,
            label TEXT NOT NULL,
            placeholder TEXT,
            help_text TEXT,
            is_required INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(module, key)
        );
        CREATE INDEX IF NOT EXISTS idx_link_categories_module ON link_categories(module);
        CREATE TABLE IF NOT EXISTS vehicle_item_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_item_id INTEGER NOT NULL REFERENCES vehicle_items(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES link_categories(id) ON DELETE CASCADE,
            url TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vehicle_item_id, category_id)
        );
        CREATE INDEX IF NOT EXISTS idx_vehicle_item_links_item ON vehicle_item_links(vehicle_item_id);
        CREATE TABLE IF NOT EXISTS pharmacy_item_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES link_categories(id) ON DELETE CASCADE,
            url TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(pharmacy_item_id, category_id)
        );
        CREATE INDEX IF NOT EXISTS idx_pharmacy_item_links_item ON pharmacy_item_links(pharmacy_item_id);
        """
    )


def _seed_default_link_categories(conn: sqlite3.Connection) -> None:
    for alias, canonical in _LINK_MODULE_ALIASES.items():
        if alias == canonical:
            continue
        conn.execute(
            "UPDATE link_categories SET module = ? WHERE module = ?",
            (canonical, alias),
        )
    defaults: list[tuple[str, str, str, str | None, str | None, int, int, int]] = [
        (
            "vehicle_qr",
            "onedrive",
            "Fichier OneDrive",
            "https://onedrive.live.com/...",
            "Lien partagé du fichier hébergé dans OneDrive.",
            0,
            0,
            1,
        ),
        (
            "vehicle_qr",
            "documentation",
            "Documentation",
            "https://...",
            None,
            0,
            10,
            1,
        ),
        (
            "vehicle_qr",
            "tutoriel",
            "Tutoriel",
            "https://...",
            None,
            0,
            20,
            1,
        ),
        (
            "pharmacy",
            "documentation",
            "Documentation",
            "https://...",
            None,
            0,
            10,
            1,
        ),
        (
            "pharmacy",
            "supplier",
            "Fournisseur",
            "https://...",
            "Lien vers la fiche fournisseur ou la notice.",
            0,
            20,
            1,
        ),
        (
            "pharmacy",
            "tutoriel",
            "Tutoriel",
            "https://...",
            None,
            0,
            30,
            1,
        ),
    ]
    conn.executemany(
        """
        INSERT OR IGNORE INTO link_categories (
            module,
            key,
            label,
            placeholder,
            help_text,
            is_required,
            sort_order,
            is_active,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        defaults,
    )
    conn.executemany(
        """
        UPDATE link_categories
        SET label = CASE WHEN label IS NULL OR label = '' THEN ? ELSE label END,
            placeholder = CASE
                WHEN placeholder IS NULL OR placeholder = '' THEN ? ELSE placeholder END,
            help_text = CASE WHEN help_text IS NULL OR help_text = '' THEN ? ELSE help_text END,
            is_active = CASE WHEN is_active IS NULL THEN ? ELSE is_active END,
            updated_at = CASE
                WHEN label IS NULL OR label = ''
                  OR placeholder IS NULL OR placeholder = ''
                  OR help_text IS NULL OR help_text = ''
                  OR is_active IS NULL
                THEN CURRENT_TIMESTAMP
                ELSE updated_at
            END
        WHERE module = ? AND key = ?
        """,
        [
            (
                label,
                placeholder,
                help_text,
                is_active,
                module,
                key,
            )
            for module, key, label, placeholder, help_text, _is_required, _sort_order, is_active in defaults
        ],
    )
    modules_with_defaults = {module for module, *_rest in defaults}
    for module in modules_with_defaults:
        has_active = conn.execute(
            "SELECT 1 FROM link_categories WHERE module = ? AND is_active = 1 LIMIT 1",
            (module,),
        ).fetchone()
        if has_active is not None:
            continue
        module_keys = [key for entry_module, key, *_rest in defaults if entry_module == module]
        if not module_keys:
            continue
        placeholders = ", ".join("?" for _ in module_keys)
        conn.execute(
            f"""
            UPDATE link_categories
            SET is_active = 1, updated_at = CURRENT_TIMESTAMP
            WHERE module = ? AND key IN ({placeholders})
            """,
            (module, *module_keys),
        )


def _migrate_vehicle_link_legacy_fields(conn: sqlite3.Connection) -> None:
    vehicle_item_info = conn.execute("PRAGMA table_info(vehicle_items)").fetchall()
    if not vehicle_item_info:
        return
    vehicle_item_columns = {row["name"] for row in vehicle_item_info}
    category_rows = conn.execute(
        "SELECT id, key FROM link_categories WHERE module = 'vehicle_qr'"
    ).fetchall()
    if not category_rows:
        return
    category_map = {row["key"]: row["id"] for row in category_rows}
    legacy_map: dict[str, str] = _LINK_MODULE_CONFIG["vehicle_qr"]["legacy_map"]
    for key, column in legacy_map.items():
        if column not in vehicle_item_columns:
            continue
        category_id = category_map.get(key)
        if not category_id:
            continue
        rows = conn.execute(
            f"""
            SELECT id, {column} AS legacy_url
            FROM vehicle_items
            WHERE {column} IS NOT NULL AND {column} != ''
            """
        ).fetchall()
        if not rows:
            continue
        conn.executemany(
            """
            INSERT OR IGNORE INTO vehicle_item_links (vehicle_item_id, category_id, url, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [(row["id"], category_id, row["legacy_url"]) for row in rows],
        )


def _ensure_vehicle_item_qr_tokens(
    conn: sqlite3.Connection,
    execute: Callable[[str, tuple[Any, ...]], sqlite3.Cursor] | None = None,
) -> None:
    if execute is None:
        execute = conn.execute
    vehicle_item_info = execute("PRAGMA table_info(vehicle_items)").fetchall()
    vehicle_item_columns = {row["name"] for row in vehicle_item_info}
    updated_schema = False

    if "qr_token" not in vehicle_item_columns:
        execute("ALTER TABLE vehicle_items ADD COLUMN qr_token TEXT")
        updated_schema = True

    missing_tokens = execute(
        "SELECT id FROM vehicle_items WHERE qr_token IS NULL OR qr_token = ''"
    ).fetchall()
    for row in missing_tokens:
        execute(
            "UPDATE vehicle_items SET qr_token = ? WHERE id = ?",
            (uuid4().hex, row["id"]),
        )
        updated_schema = True

    execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicle_items_qr_token ON vehicle_items(qr_token)"
    )

    if updated_schema:
        _persist_after_commit(conn, "vehicle_inventory")


def apply_site_schema_migrations() -> None:
    for site_key in db.list_site_keys():
        _apply_schema_migrations_for_site(site_key)
        logger.info("[DB] schema migrated/ok for site %s", site_key)


def _apply_schema_migrations_for_site(site_key: str) -> None:
    with db.get_stock_connection(site_key) as conn:
        def execute(statement: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
            return _execute_with_retry(conn, statement, params)

        def executemany(statement: str, params: Iterable[tuple[Any, ...]]) -> sqlite3.Cursor:
            return _executemany_with_retry(conn, statement, params)

        def executescript(script: str) -> sqlite3.Cursor:
            return _executescript_with_retry(conn, script)

        cur = execute("PRAGMA table_info(items)")
        columns = {row["name"] for row in cur.fetchall()}
        if "supplier_id" not in columns:
            execute(
                "ALTER TABLE items ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL"
            )
        if "track_low_stock" not in columns:
            execute(
                "ALTER TABLE items ADD COLUMN track_low_stock INTEGER NOT NULL DEFAULT 0"
            )
            execute("UPDATE items SET track_low_stock = 0 WHERE track_low_stock IS NULL")

        executescript(
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
            CREATE TABLE IF NOT EXISTS purchase_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_key TEXT NOT NULL,
                module_key TEXT NOT NULL,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT
            );
            CREATE TABLE IF NOT EXISTS purchase_suggestion_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suggestion_id INTEGER NOT NULL REFERENCES purchase_suggestions(id) ON DELETE CASCADE,
                item_id INTEGER NOT NULL,
                sku TEXT,
                label TEXT,
                qty_suggested INTEGER NOT NULL,
                qty_final INTEGER NOT NULL,
                unit TEXT,
                reason TEXT,
                stock_current INTEGER NOT NULL,
                threshold INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_purchase_suggestions_scope
            ON purchase_suggestions(site_key, module_key, supplier_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_suggestion_lines_item
            ON purchase_suggestion_lines(suggestion_id, item_id);
        """
        )
        execute(
            """
            CREATE TABLE IF NOT EXISTS ui_menu_prefs (
                username TEXT NOT NULL,
                menu_key TEXT NOT NULL,
                order_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (username, menu_key)
            );
            """
        )

        backup_settings_info = execute("PRAGMA table_info(backup_settings)").fetchall()
        backup_settings_columns = {row["name"] for row in backup_settings_info}
        if not backup_settings_info:
            executescript(
                f"""
                CREATE TABLE IF NOT EXISTS backup_settings (
                    site_key TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    interval_minutes INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_INTERVAL_MINUTES},
                    retention_count INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_RETENTION_COUNT},
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        elif "site_key" not in backup_settings_columns:
            execute(
                f"""
                CREATE TABLE IF NOT EXISTS backup_settings_new (
                    site_key TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    interval_minutes INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_INTERVAL_MINUTES},
                    retention_count INTEGER NOT NULL DEFAULT {DEFAULT_BACKUP_RETENTION_COUNT},
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            legacy_row = execute(
                """
                SELECT enabled, interval_minutes, retention_count, updated_at
                FROM backup_settings
                WHERE id = 1
                """
            ).fetchone()
            if legacy_row:
                execute(
                    """
                    INSERT INTO backup_settings_new (
                        site_key, enabled, interval_minutes, retention_count, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        site_key,
                        legacy_row["enabled"],
                        legacy_row["interval_minutes"],
                        legacy_row["retention_count"],
                        legacy_row["updated_at"] or datetime.now().isoformat(),
                    ),
                )
            execute("DROP TABLE backup_settings")
            execute("ALTER TABLE backup_settings_new RENAME TO backup_settings")
        elif "updated_at" not in backup_settings_columns:
            execute("ALTER TABLE backup_settings ADD COLUMN updated_at TEXT")
            execute(
                """
                UPDATE backup_settings
                SET updated_at = CURRENT_TIMESTAMP
                WHERE updated_at IS NULL
                """
            )

        po_info = execute("PRAGMA table_info(purchase_orders)").fetchall()
        po_columns = {row["name"] for row in po_info}
        if "auto_created" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN auto_created INTEGER NOT NULL DEFAULT 0")
        if "note" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN note TEXT")
        if "created_at" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN created_at TIMESTAMP")
            execute(
                """
                UPDATE purchase_orders
                SET created_at = CURRENT_TIMESTAMP
                WHERE created_at IS NULL
                """
            )
        if "status" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'")
        if "supplier_id" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN supplier_id INTEGER")
        if "last_sent_at" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN last_sent_at TEXT")
        if "last_sent_to" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN last_sent_to TEXT")
        if "last_sent_by" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN last_sent_by TEXT")

        poi_info = execute("PRAGMA table_info(purchase_order_items)").fetchall()
        poi_columns = {row["name"] for row in poi_info}
        if "quantity_received" not in poi_columns:
            execute(
                "ALTER TABLE purchase_order_items ADD COLUMN quantity_received INTEGER NOT NULL DEFAULT 0"
            )

        dotation_info = execute("PRAGMA table_info(dotations)").fetchall()
        dotation_columns = {row["name"] for row in dotation_info}
        if "perceived_at" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN perceived_at DATE")
        if "is_lost" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN is_lost INTEGER NOT NULL DEFAULT 0")
        if "is_degraded" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN is_degraded INTEGER NOT NULL DEFAULT 0")
        execute(
            "UPDATE dotations SET perceived_at = DATE(allocated_at) WHERE perceived_at IS NULL OR perceived_at = ''"
        )

        pharmacy_info = execute("PRAGMA table_info(pharmacy_items)").fetchall()
        pharmacy_columns = {row["name"] for row in pharmacy_info}
        if "packaging" not in pharmacy_columns:
            execute("ALTER TABLE pharmacy_items ADD COLUMN packaging TEXT")
        if "barcode" not in pharmacy_columns:
            execute("ALTER TABLE pharmacy_items ADD COLUMN barcode TEXT")
        if "low_stock_threshold" not in pharmacy_columns:
            execute(
                "ALTER TABLE pharmacy_items ADD COLUMN low_stock_threshold INTEGER NOT NULL DEFAULT 5"
            )
        if "supplier_id" not in pharmacy_columns:
            execute("ALTER TABLE pharmacy_items ADD COLUMN supplier_id INTEGER")
        if "extra_json" not in pharmacy_columns:
            execute("ALTER TABLE pharmacy_items ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}'")
        execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pharmacy_items_barcode
            ON pharmacy_items(barcode)
            WHERE barcode IS NOT NULL
            """
        )
        execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pharmacy_items_supplier_id
            ON pharmacy_items(supplier_id)
            """
        )

        pharmacy_po_info = execute("PRAGMA table_info(pharmacy_purchase_orders)").fetchall()
        pharmacy_po_columns = {row["name"] for row in pharmacy_po_info}
        if "supplier_id" not in pharmacy_po_columns:
            execute(
                "ALTER TABLE pharmacy_purchase_orders ADD COLUMN supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL"
            )
        if "status" not in pharmacy_po_columns:
            execute(
                "ALTER TABLE pharmacy_purchase_orders ADD COLUMN status TEXT NOT NULL DEFAULT 'PENDING'"
            )
        if "created_at" not in pharmacy_po_columns:
            execute("ALTER TABLE pharmacy_purchase_orders ADD COLUMN created_at TIMESTAMP")
            execute(
                """
                UPDATE pharmacy_purchase_orders
                SET created_at = CURRENT_TIMESTAMP
                WHERE created_at IS NULL
                """
            )
        if "note" not in pharmacy_po_columns:
            execute("ALTER TABLE pharmacy_purchase_orders ADD COLUMN note TEXT")

        pharmacy_poi_info = execute("PRAGMA table_info(pharmacy_purchase_order_items)").fetchall()
        pharmacy_poi_columns = {row["name"] for row in pharmacy_poi_info}
        if "quantity_received" not in pharmacy_poi_columns:
            execute(
                "ALTER TABLE pharmacy_purchase_order_items ADD COLUMN quantity_received INTEGER NOT NULL DEFAULT 0"
            )

        execute(
            "CREATE INDEX IF NOT EXISTS idx_pharmacy_purchase_orders_status ON pharmacy_purchase_orders(status)"
        )
        execute(
            "CREATE INDEX IF NOT EXISTS idx_pharmacy_purchase_order_items_item ON pharmacy_purchase_order_items(pharmacy_item_id)"
        )

        executescript(
            """
            CREATE TABLE IF NOT EXISTS supplier_modules (
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                module TEXT NOT NULL,
                PRIMARY KEY (supplier_id, module)
            );
            CREATE TABLE IF NOT EXISTS vehicle_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS custom_field_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                key TEXT NOT NULL,
                label TEXT NOT NULL,
                field_type TEXT NOT NULL,
                required INTEGER NOT NULL DEFAULT 0,
                default_json TEXT,
                options_json TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(scope, key)
            );
            CREATE INDEX IF NOT EXISTS idx_custom_fields_scope ON custom_field_definitions(scope);
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
                extra_json TEXT NOT NULL DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name)
            );
            CREATE TABLE IF NOT EXISTS pharmacy_lot_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lot_id INTEGER NOT NULL REFERENCES pharmacy_lots(id) ON DELETE CASCADE,
                pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                compartment_name TEXT,
                UNIQUE(lot_id, pharmacy_item_id, compartment_name)
            );
            CREATE INDEX IF NOT EXISTS idx_pharmacy_lot_items_lot ON pharmacy_lot_items(lot_id);
            CREATE INDEX IF NOT EXISTS idx_pharmacy_lot_items_item ON pharmacy_lot_items(pharmacy_item_id);
            CREATE TABLE IF NOT EXISTS vehicle_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                image_path TEXT,
                vehicle_type TEXT,
                extra_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS vehicle_applied_lots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL REFERENCES vehicle_categories(id) ON DELETE CASCADE,
                vehicle_type TEXT,
                view TEXT,
                source TEXT NOT NULL,
                pharmacy_lot_id INTEGER REFERENCES pharmacy_lots(id) ON DELETE SET NULL,
                lot_name TEXT,
                position_x REAL,
                position_y REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_vehicle_applied_lots_vehicle
            ON vehicle_applied_lots(vehicle_id);
            CREATE INDEX IF NOT EXISTS idx_vehicle_applied_lots_view
            ON vehicle_applied_lots(view);
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
                pharmacy_item_id INTEGER REFERENCES pharmacy_items(id),
                documentation_url TEXT,
                tutorial_url TEXT,
                shared_file_url TEXT,
                qr_token TEXT,
                show_in_qr INTEGER NOT NULL DEFAULT 1,
                lot_id INTEGER REFERENCES remise_lots(id) ON DELETE SET NULL,
                applied_lot_source TEXT,
                applied_lot_assignment_id INTEGER REFERENCES vehicle_applied_lots(id) ON DELETE SET NULL,
                extra_json TEXT NOT NULL DEFAULT '{}'
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
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                extra_json TEXT NOT NULL DEFAULT '{}'
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
                extra_json TEXT NOT NULL DEFAULT '{}',
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
        executemany(
            """
            INSERT OR IGNORE INTO vehicle_types (code, label, is_active)
            VALUES (?, ?, 1)
            """,
            [
                ("incendie", "Incendie"),
                ("secours_a_personne", "Secours à personne"),
            ],
        )
        _ensure_remise_item_columns(conn, execute=execute)
        _ensure_remise_lot_columns(conn, execute=execute)
        _ensure_pharmacy_lot_columns(conn, execute=execute)
        _ensure_pharmacy_lot_item_columns(conn, execute=execute, executescript=executescript)
        _ensure_vehicle_category_columns(conn, execute=execute)
        _ensure_vehicle_view_settings_columns(conn, execute=execute)
        _ensure_vehicle_applied_lot_table(conn, executescript=executescript)
        _ensure_vehicle_item_columns(conn, execute=execute)
        _ensure_vehicle_item_qr_tokens(conn, execute=execute)
        _ensure_link_tables(conn, executescript=executescript)
        _seed_default_link_categories(conn)
        _migrate_vehicle_link_legacy_fields(conn)
        execute(
            "CREATE INDEX IF NOT EXISTS idx_vehicle_items_remise ON vehicle_items(remise_item_id)"
        )
        executescript(
            """
            CREATE TABLE IF NOT EXISTS vehicle_pharmacy_lot_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_category_id INTEGER NOT NULL REFERENCES vehicle_categories(id) ON DELETE CASCADE,
                lot_id INTEGER NOT NULL REFERENCES pharmacy_lots(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(vehicle_category_id, lot_id)
            );
            CREATE INDEX IF NOT EXISTS idx_vehicle_pharmacy_lot_assignments_vehicle
            ON vehicle_pharmacy_lot_assignments(vehicle_category_id);
            """
        )

        _sync_vehicle_inventory_with_remise(conn)

        pharmacy_category_info = execute("PRAGMA table_info(pharmacy_items)").fetchall()
        pharmacy_category_columns = {row["name"] for row in pharmacy_category_info}
        if "category_id" not in pharmacy_category_columns:
            execute(
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
        INSERT INTO purchase_orders (supplier_id, status, note, auto_created, created_at)
        VALUES (?, 'PENDING', ?, 1, CURRENT_TIMESTAMP)
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
    applied_lot_source = row["applied_lot_source"] if "applied_lot_source" in row.keys() else None
    applied_lot_assignment_id = (
        row["applied_lot_assignment_id"] if "applied_lot_assignment_id" in row.keys() else None
    )
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
    extra = _parse_extra_json(row["extra_json"] if "extra_json" in row.keys() else None)

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
        applied_lot_source=applied_lot_source,
        applied_lot_assignment_id=applied_lot_assignment_id,
        show_in_qr=show_in_qr,
        vehicle_type=row["vehicle_type"] if "vehicle_type" in row.keys() else None,
        assigned_vehicle_names=assigned_vehicle_names,
        extra=extra,
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
    extra_scope = None
    if module == "inventory_remise":
        extra_scope = "remise_items"
    elif module == "vehicle_inventory":
        extra_scope = "vehicle_items"
    if (
        module == "vehicle_inventory"
        and payload.category_id is not None
        and payload.quantity <= 0
    ):
        raise ValueError("La quantité affectée au véhicule doit être strictement positive.")
    with db.get_stock_connection() as conn:
        if module == "inventory_remise":
            _ensure_remise_item_columns(conn)
        extra = validate_and_merge_extra(extra_scope, None, payload.extra) if extra_scope else {}
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
        if module == "default":
            columns.append("track_low_stock")
            values.append(int(payload.track_low_stock))
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
        if extra_scope:
            columns.append("extra_json")
            values.append(_dump_extra_json(extra))
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
    extra_payload = fields.pop("extra", None)
    extra_scope = None
    if module == "inventory_remise":
        extra_scope = "remise_items"
    elif module == "vehicle_inventory":
        extra_scope = "vehicle_items"
    if module != "vehicle_inventory":
        fields.pop("show_in_qr", None)
        fields.pop("vehicle_type", None)
        fields.pop("pharmacy_item_id", None)
    if module == "vehicle_inventory":
        fields.pop("track_low_stock", None)
    if module != "inventory_remise":
        fields.pop("expiration_date", None)
    elif "expiration_date" in fields:
        fields["expiration_date"] = (
            fields["expiration_date"].isoformat()
            if fields["expiration_date"] is not None
            else None
        )
    if module != "vehicle_inventory" and "track_low_stock" in fields:
        if fields["track_low_stock"] is not None:
            fields["track_low_stock"] = int(bool(fields["track_low_stock"]))
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
                f"SELECT quantity, remise_item_id, pharmacy_item_id, category_id, image_path, lot_id, vehicle_type, extra_json FROM {config.tables.items} WHERE id = ?",
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
        if extra_scope and extra_payload is not None:
            if module == "vehicle_inventory":
                if current_row is None:
                    raise ValueError("Article introuvable")
                existing_extra = current_row["extra_json"]
            else:
                row = conn.execute(
                    f"SELECT extra_json FROM {config.tables.items} WHERE id = ?",
                    (item_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("Article introuvable")
                existing_extra = row["extra_json"]
            merged_extra = validate_and_merge_extra(extra_scope, existing_extra, extra_payload)
            fields["extra_json"] = _dump_extra_json(merged_extra)
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
            select_columns += ", image_path, vehicle_type, extra_json"
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
            extra = _parse_extra_json(row["extra_json"] if "extra_json" in row.keys() else None)
            categories.append(
                models.Category(
                    id=category_id,
                    name=row["name"],
                    sizes=sizes,
                    view_configs=category_view_configs,
                    image_url=image_url,
                    vehicle_type=row["vehicle_type"] if module == "vehicle_inventory" else None,
                    extra=extra,
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
            select_columns += ", image_path, vehicle_type, extra_json"
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
        extra = _parse_extra_json(row["extra_json"] if "extra_json" in row.keys() else None)
        return models.Category(
            id=row["id"],
            name=row["name"],
            sizes=sizes,
            view_configs=view_configs,
            image_url=image_url,
            vehicle_type=row["vehicle_type"] if module == "vehicle_inventory" else None,
            extra=extra,
        )


def _create_inventory_category_internal(
    module: str, payload: models.CategoryCreate
) -> models.Category:
    ensure_database_ready()
    config = _get_inventory_config(module)
    normalized_sizes = _normalize_sizes(payload.sizes)
    extra = validate_and_merge_extra("vehicles", None, payload.extra) if module == "vehicle_inventory" else {}
    with db.get_stock_connection() as conn:
        columns = ["name"]
        values: list[object] = [payload.name]
        if module == "vehicle_inventory":
            _ensure_vehicle_category_columns(conn)
            columns.append("vehicle_type")
            values.append(payload.vehicle_type)
            columns.append("extra_json")
            values.append(_dump_extra_json(extra))
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
        if module == "vehicle_inventory" and payload.extra is not None:
            row = conn.execute(
                "SELECT extra_json FROM vehicle_categories WHERE id = ?",
                (category_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Catégorie introuvable")
            extra = validate_and_merge_extra("vehicles", row["extra_json"], payload.extra)
            updates.append("extra_json = ?")
            values.append(_dump_extra_json(extra))
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


def _normalize_email(value: str) -> str:
    return value.strip().lower()


_RESET_TOKEN_PEPPER_CACHE: str | None = None


def _allow_insecure_reset_dev() -> bool:
    return os.environ.get("ALLOW_INSECURE_RESET_DEV") == "1"


def _get_reset_token_pepper() -> str:
    global _RESET_TOKEN_PEPPER_CACHE
    if _RESET_TOKEN_PEPPER_CACHE is not None:
        return _RESET_TOKEN_PEPPER_CACHE
    pepper = os.environ.get("RESET_TOKEN_PEPPER")
    if pepper:
        _RESET_TOKEN_PEPPER_CACHE = pepper
        return pepper
    if _allow_insecure_reset_dev():
        _RESET_TOKEN_PEPPER_CACHE = "dev-reset-pepper"
        return _RESET_TOKEN_PEPPER_CACHE
    raise RuntimeError(
        "RESET_TOKEN_PEPPER manquant (définissez ALLOW_INSECURE_RESET_DEV=1 pour un mode dev)."
    )


def ensure_password_reset_configured() -> None:
    _get_reset_token_pepper()


def _get_reset_token_ttl_minutes() -> int:
    raw_ttl = os.environ.get("RESET_TOKEN_TTL_MINUTES")
    if raw_ttl is None:
        return 30
    try:
        return max(1, int(raw_ttl))
    except ValueError:
        return 30


def _get_password_reset_rate_limit_config() -> tuple[int, int]:
    raw_count = os.environ.get("RESET_RATE_LIMIT_COUNT")
    raw_window = os.environ.get("RESET_RATE_LIMIT_WINDOW_SECONDS")
    try:
        max_count = int(raw_count) if raw_count else _PASSWORD_RESET_RATE_LIMIT_COUNT
    except ValueError:
        max_count = _PASSWORD_RESET_RATE_LIMIT_COUNT
    try:
        window_seconds = (
            int(raw_window) if raw_window else _PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS
        )
    except ValueError:
        window_seconds = _PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS
    return max(1, max_count), max(60, window_seconds)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _hash_reset_token(token: str) -> str:
    payload = f"{token}{_get_reset_token_pepper()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_reset_password(password: str) -> None:
    if len(password) < _PASSWORD_RESET_MIN_LENGTH:
        raise ValueError("Mot de passe trop court")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Mot de passe insuffisamment complexe")


def _check_password_reset_rate_limit(email_normalized: str, ip_address: str | None) -> None:
    max_count, window_seconds = _get_password_reset_rate_limit_config()
    email_key = email_normalized or "unknown"
    ip_key = ip_address or "unknown"
    now = int(time.time())
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT window_start_ts, count
            FROM password_reset_rate_limits
            WHERE email_normalized = ? AND ip_address = ?
            """,
            (email_key, ip_key),
        ).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO password_reset_rate_limits (email_normalized, ip_address, window_start_ts, count)
                VALUES (?, ?, ?, 1)
                """,
                (email_key, ip_key, now),
            )
            return
        window_start = int(row["window_start_ts"])
        count = int(row["count"])
        if now - window_start >= window_seconds:
            conn.execute(
                """
                UPDATE password_reset_rate_limits
                SET window_start_ts = ?, count = 1
                WHERE email_normalized = ? AND ip_address = ?
                """,
                (now, email_key, ip_key),
            )
            return
        if count >= max_count:
            raise PasswordResetRateLimitError(count=max_count, window_seconds=window_seconds)
        conn.execute(
            """
            UPDATE password_reset_rate_limits
            SET count = ?
            WHERE email_normalized = ? AND ip_address = ?
            """,
            (count + 1, email_key, ip_key),
        )


def request_password_reset(
    email: str,
    request_ip: str | None = None,
    user_agent: str | None = None,
) -> str | None:
    ensure_database_ready()
    normalized_email = _normalize_email(email) if email else ""
    _check_password_reset_rate_limit(normalized_email, request_ip)
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT id, email, status
            FROM users
            WHERE email_normalized = ?
            """,
            (normalized_email,),
        ).fetchone()
        if not row or row["status"] != "active":
            return None
        now_iso = _utc_now_iso()
        ttl_minutes = _get_reset_token_ttl_minutes()
        expires_at = (_utc_now() + timedelta(minutes=ttl_minutes)).isoformat().replace("+00:00", "Z")
        conn.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = ?
            WHERE user_id = ? AND used_at IS NULL
            """,
            (now_iso, row["id"]),
        )
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_reset_token(raw_token)
        conn.execute(
            """
            INSERT INTO password_reset_tokens (
                user_id,
                token_hash,
                created_at,
                expires_at,
                used_at,
                request_ip,
                user_agent
            )
            VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (row["id"], token_hash, now_iso, expires_at, request_ip, user_agent),
        )
    notifications.enqueue_password_reset(
        str(row["email"] or email),
        raw_token,
        {"expires_at": expires_at},
    )
    if _allow_insecure_reset_dev():
        return raw_token
    return None


def confirm_password_reset(
    token: str,
    new_password: str,
    request_ip: str | None = None,
) -> None:
    ensure_database_ready()
    _validate_reset_password(new_password)
    token_hash = _hash_reset_token(token)
    now = _utc_now()
    now_iso = now.isoformat().replace("+00:00", "Z")
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT id, user_id, expires_at, used_at
            FROM password_reset_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if not row or row["used_at"]:
            raise ValueError("Token invalide ou expiré")
        expires_at_raw = row["expires_at"]
        try:
            expires_at = datetime.fromisoformat(str(expires_at_raw).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Token invalide ou expiré") from None
        if expires_at <= now:
            raise ValueError("Token invalide ou expiré")
        updated = conn.execute(
            """
            UPDATE password_reset_tokens
            SET used_at = ?
            WHERE id = ? AND used_at IS NULL
            """,
            (now_iso, row["id"]),
        )
        if updated.rowcount == 0:
            raise ValueError("Token invalide ou expiré")
        conn.execute(
            """
            UPDATE users
            SET password = ?, session_version = session_version + 1
            WHERE id = ?
            """,
            (security.hash_password(new_password), row["user_id"]),
        )
    logger.info("[AUTH] password_reset user_id=%s ip=%s", row["user_id"], request_ip or "unknown")

def seed_default_admin() -> None:
    default_username = "admin"
    default_password = "admin123"
    has_email = "@" in default_username
    normalized_email = _normalize_email(default_username) if has_email else None
    seed_email = default_username if has_email else None
    with db.get_users_connection() as conn:
        cur = conn.execute(
            """
            SELECT id, password, role, is_active, site_key, status, email, email_normalized
            FROM users
            WHERE username = ?
            """,
            (default_username,),
        )
        row = cur.fetchone()
        hashed_password = security.hash_password(default_password)
        if row is None:
            conn.execute(
                """
                INSERT INTO users (
                    username,
                    email,
                    email_normalized,
                    password,
                    role,
                    is_active,
                    status,
                    site_key,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 1, 'active', ?, CURRENT_TIMESTAMP)
                """,
                (
                    default_username,
                    seed_email,
                    normalized_email,
                    hashed_password,
                    "admin",
                    db.DEFAULT_SITE_KEY,
                ),
            )
            conn.commit()
            return

        needs_update = False
        if not security.verify_password(default_password, row["password"]):
            needs_update = True
        if row["role"] != "admin" or not bool(row["is_active"]):
            needs_update = True
        if row["site_key"] != db.DEFAULT_SITE_KEY:
            needs_update = True
        if has_email and row["email_normalized"] != normalized_email:
            needs_update = True

        if needs_update:
            conn.execute(
                """
                UPDATE users
                SET password = ?,
                    role = ?,
                    is_active = 1,
                    status = 'active',
                    site_key = ?,
                    email = ?,
                    email_normalized = ?
                WHERE id = ?
                """,
                (
                    hashed_password,
                    "admin",
                    db.DEFAULT_SITE_KEY,
                    seed_email if has_email else row["email"],
                    normalized_email if has_email else row["email_normalized"],
                    row["id"],
                ),
            )
            conn.commit()


def _build_user_from_row(row: sqlite3.Row) -> models.User:
    site_key = row["site_key"] if "site_key" in row.keys() and row["site_key"] else db.DEFAULT_SITE_KEY
    email = row["email"] if "email" in row.keys() and row["email"] else row["username"]
    if "status" in row.keys() and row["status"]:
        status = row["status"]
    else:
        status = "active" if bool(row["is_active"]) else "disabled"
    return models.User(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        site_key=site_key,
        email=email,
        status=status,
        session_version=row["session_version"] if "session_version" in row.keys() else 1,
        created_at=row["created_at"] if "created_at" in row.keys() else None,
        approved_at=row["approved_at"] if "approved_at" in row.keys() else None,
        approved_by=row["approved_by"] if "approved_by" in row.keys() else None,
        rejected_at=row["rejected_at"] if "rejected_at" in row.keys() else None,
        rejected_by=row["rejected_by"] if "rejected_by" in row.keys() else None,
        notify_on_approval=bool(row["notify_on_approval"])
        if "notify_on_approval" in row.keys()
        else True,
        otp_email_enabled=bool(row["otp_email_enabled"]) if "otp_email_enabled" in row.keys() else False,
        display_name=row["display_name"] if "display_name" in row.keys() else None,
    )


def get_user(username: str) -> Optional[models.User]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row:
            return None
        return _build_user_from_row(row)


def get_user_by_id(user_id: int) -> Optional[models.User]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        return _build_user_from_row(row)


def _normalize_menu_order_items(
    items: Iterable[models.MenuOrderItem],
) -> list[models.MenuOrderItem]:
    normalized: list[models.MenuOrderItem] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        normalized.append(item)
        if len(normalized) >= _MENU_ORDER_MAX_ITEMS:
            break
    return normalized


def _validate_menu_order_items(
    items: Iterable[models.MenuOrderItem],
) -> list[models.MenuOrderItem]:
    normalized = _normalize_menu_order_items(items)
    for item in normalized:
        if item.id not in menu_registry.ALL_MENU_IDS:
            raise ValueError(f"Identifiant de menu inconnu: {item.id}")
        if item.id in menu_registry.PINNED_IDS:
            raise ValueError(f"Identifiant de menu verrouillé: {item.id}")
        if len(item.id) > _MENU_ORDER_MAX_ID_LENGTH:
            raise ValueError(f"Identifiant de menu trop long: {item.id}")
        parent_id = item.parent_id
        if item.id in menu_registry.GROUP_IDS:
            if parent_id is not None:
                raise ValueError("Un groupe ne peut pas avoir de parent")
            continue
        if parent_id is None:
            raise ValueError("Un item doit appartenir à un groupe")
        if parent_id == item.id:
            raise ValueError("Un item ne peut pas être son propre parent")
        if parent_id in menu_registry.ITEM_IDS:
            raise ValueError("Un item ne peut pas être enfant d'un item")
        if parent_id not in menu_registry.GROUP_IDS:
            raise ValueError(f"Groupe parent inconnu: {parent_id}")
    return normalized


def get_menu_order(
    username: str, site_key: str, menu_key: str
) -> dict[str, Any] | None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT version, payload_json
            FROM ui_menu_prefs
            WHERE site_key = ? AND username = ? AND menu_key = ?
            """,
            (site_key, username, menu_key),
        ).fetchone()
    if not row:
        return None
    try:
        parsed = json.loads(row["payload_json"])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    items: list[models.MenuOrderItem] = []
    try:
        for entry in parsed:
            if not isinstance(entry, dict):
                return None
            items.append(models.MenuOrderItem(**entry))
    except Exception:
        return None
    return {"version": int(row["version"] or 1), "items": items}


def set_menu_order(
    username: str,
    site_key: str,
    menu_key: str,
    payload: models.MenuOrderPayload,
) -> dict[str, Any]:
    ensure_database_ready()
    normalized = _validate_menu_order_items(payload.items)
    payload_json = json.dumps(
        [
            item.model_dump(by_alias=True, exclude_none=True)
            for item in normalized
        ],
        ensure_ascii=False,
    )
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO ui_menu_prefs (site_key, username, menu_key, version, payload_json, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(site_key, username, menu_key)
            DO UPDATE SET
                version = excluded.version,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (site_key, username, menu_key, payload.version, payload_json),
        )
        conn.commit()
    return {"version": payload.version, "items": normalized}


def list_users(*, include_pending: bool = True) -> list[models.User]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        clause = "" if include_pending else "WHERE status != 'pending'"
        cur = conn.execute(
            f"SELECT * FROM users {clause} ORDER BY username COLLATE NOCASE",
        )
        rows = cur.fetchall()
        return [
            _build_user_from_row(row)
            for row in rows
        ]


def list_message_recipients(current_user: models.User) -> list[models.MessageRecipientInfo]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            """
            SELECT username, role
            FROM users
            WHERE status = 'active' AND username != ?
            ORDER BY username COLLATE NOCASE
            """,
            (current_user.username,),
        )
        rows = cur.fetchall()
    return [models.MessageRecipientInfo(username=row["username"], role=row["role"]) for row in rows]


def _get_message_rate_limit_settings() -> tuple[int, int]:
    raw_count = os.getenv("MESSAGE_RATE_LIMIT_COUNT")
    raw_window = os.getenv("MESSAGE_RATE_LIMIT_WINDOW_SECONDS")
    try:
        max_count = int(raw_count) if raw_count else _MESSAGE_RATE_LIMIT_DEFAULT_COUNT
    except ValueError:
        max_count = _MESSAGE_RATE_LIMIT_DEFAULT_COUNT
    try:
        window_seconds = int(raw_window) if raw_window else _MESSAGE_RATE_LIMIT_DEFAULT_WINDOW_SECONDS
    except ValueError:
        window_seconds = _MESSAGE_RATE_LIMIT_DEFAULT_WINDOW_SECONDS
    max_count = max(1, max_count)
    window_seconds = max(1, window_seconds)
    return max_count, window_seconds


def _enforce_message_rate_limit(conn: sqlite3.Connection, sender_username: str) -> None:
    max_count, window_seconds = _get_message_rate_limit_settings()
    now_ts = int(time.time())
    row = conn.execute(
        """
        SELECT window_start_ts, count
        FROM message_rate_limits
        WHERE sender_username = ?
        """,
        (sender_username,),
    ).fetchone()
    if row:
        window_start = int(row["window_start_ts"])
        count = int(row["count"])
        if now_ts - window_start < window_seconds:
            if count >= max_count:
                logger.info(
                    "[MESSAGE] rate_limit sender=%s count=%s window=%s",
                    sender_username,
                    count,
                    window_seconds,
                )
                raise MessageRateLimitError(count=count, window_seconds=window_seconds)
            conn.execute(
                "UPDATE message_rate_limits SET count = ? WHERE sender_username = ?",
                (count + 1, sender_username),
            )
            return
        conn.execute(
            "UPDATE message_rate_limits SET window_start_ts = ?, count = 1 WHERE sender_username = ?",
            (now_ts, sender_username),
        )
        return
    conn.execute(
        """
        INSERT INTO message_rate_limits (sender_username, window_start_ts, count)
        VALUES (?, ?, 1)
        """,
        (sender_username, now_ts),
    )


def send_message(payload: models.MessageSendRequest, sender: models.User) -> models.MessageSendResponse:
    ensure_database_ready()
    content = payload.content.strip()
    category = payload.category.strip()
    if not content:
        raise ValueError("Le contenu du message est requis")
    if not category:
        raise ValueError("La catégorie est requise")

    with db.get_users_connection() as conn:
        if payload.broadcast:
            cur = conn.execute(
                "SELECT username FROM users WHERE status = 'active' ORDER BY username COLLATE NOCASE"
            )
            recipients = [row["username"] for row in cur.fetchall()]
        else:
            recipients = [recipient.strip() for recipient in payload.recipients if recipient.strip()]

        recipients = list(dict.fromkeys(recipients))
        if not recipients:
            raise ValueError("Aucun destinataire sélectionné")

        placeholders = ", ".join("?" for _ in recipients)
        cur = conn.execute(
            f"""
            SELECT username
            FROM users
            WHERE status = 'active' AND username IN ({placeholders})
            """,
            recipients,
        )
        valid_recipients = [row["username"] for row in cur.fetchall()]
        if not valid_recipients:
            raise ValueError("Aucun destinataire valide")

        _enforce_message_rate_limit(conn, sender.username)

        cur = conn.execute(
            """
            INSERT INTO messages (sender_username, sender_role, category, content)
            VALUES (?, ?, ?, ?)
            """,
            (sender.username, sender.role, category, content),
        )
        message_id = int(cur.lastrowid)
        conn.executemany(
            """
            INSERT INTO message_recipients (message_id, recipient_username)
            VALUES (?, ?)
            """,
            [(message_id, recipient) for recipient in valid_recipients],
        )
        conn.commit()

        created_row = conn.execute(
            "SELECT created_at FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        created_at = created_row["created_at"] if created_row else None

    _archive_message_safe(
        message_id=message_id,
        created_at=created_at,
        sender_username=sender.username,
        sender_role=sender.role,
        recipients=valid_recipients,
        category=category,
        content=content,
    )

    logger.info(
        "[MESSAGE] send id=%s sender=%s role=%s recipients=%s broadcast=%s category=%s",
        message_id,
        sender.username,
        sender.role,
        len(valid_recipients),
        payload.broadcast,
        category,
    )

    return models.MessageSendResponse(message_id=message_id, recipients_count=len(valid_recipients))


def list_inbox_messages(
    user: models.User, *, limit: int = 50, include_archived: bool = False
) -> list[models.InboxMessage]:
    ensure_database_ready()
    limit_value = max(1, min(limit, 200))
    params: list[object] = [user.username]
    archive_clause = ""
    if not include_archived:
        archive_clause = "AND mr.is_archived = 0"
    params.append(limit_value)

    with db.get_users_connection() as conn:
        cur = conn.execute(
            f"""
            SELECT
                m.id,
                m.category,
                m.content,
                m.created_at,
                m.sender_username,
                m.sender_role,
                mr.is_read,
                mr.is_archived
            FROM message_recipients mr
            JOIN messages m ON m.id = mr.message_id
            WHERE mr.recipient_username = ?
            {archive_clause}
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            params,
        )
        rows = cur.fetchall()

    return [
        models.InboxMessage(
            id=row["id"],
            category=row["category"],
            content=row["content"],
            created_at=row["created_at"],
            sender_username=row["sender_username"],
            sender_role=row["sender_role"],
            is_read=bool(row["is_read"]),
            is_archived=bool(row["is_archived"]),
        )
        for row in rows
    ]


def list_sent_messages(user: models.User, *, limit: int = 50) -> list[models.SentMessage]:
    ensure_database_ready()
    limit_value = max(1, min(limit, 200))

    with db.get_users_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                m.id,
                m.category,
                m.content,
                m.created_at,
                COUNT(mr.id) AS recipients_total,
                SUM(CASE WHEN mr.read_at IS NOT NULL THEN 1 ELSE 0 END) AS recipients_read
            FROM messages m
            JOIN message_recipients mr ON mr.message_id = m.id
            WHERE m.sender_username = ?
            GROUP BY m.id
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (user.username, limit_value),
        ).fetchall()

        if not rows:
            return []

        message_ids = [row["id"] for row in rows]
        placeholders = ", ".join("?" for _ in message_ids)
        recipient_rows = conn.execute(
            f"""
            SELECT message_id, recipient_username, read_at
            FROM message_recipients
            WHERE message_id IN ({placeholders})
            ORDER BY recipient_username COLLATE NOCASE
            """,
            message_ids,
        ).fetchall()

    recipients_by_message: dict[int, list[models.MessageRecipientReadInfo]] = {msg_id: [] for msg_id in message_ids}
    for row in recipient_rows:
        recipients_by_message[int(row["message_id"])].append(
            models.MessageRecipientReadInfo(
                username=row["recipient_username"],
                read_at=row["read_at"],
            )
        )

    return [
        models.SentMessage(
            id=row["id"],
            category=row["category"],
            content=row["content"],
            created_at=row["created_at"],
            recipients_total=int(row["recipients_total"] or 0),
            recipients_read=int(row["recipients_read"] or 0),
            recipients=recipients_by_message.get(int(row["id"]), []),
        )
        for row in rows
    ]


def mark_message_read(message_id: int, user: models.User) -> None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT id, is_read
            FROM message_recipients
            WHERE message_id = ? AND recipient_username = ?
            """,
            (message_id, user.username),
        ).fetchone()
        if not row:
            raise PermissionError("Accès interdit")
        if not row["is_read"]:
            conn.execute(
                """
                UPDATE message_recipients
                SET is_read = 1, read_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
            conn.commit()


def archive_message(message_id: int, user: models.User) -> None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT id, is_archived
            FROM message_recipients
            WHERE message_id = ? AND recipient_username = ?
            """,
            (message_id, user.username),
        ).fetchone()
        if not row:
            raise PermissionError("Accès interdit")
        if not row["is_archived"]:
            conn.execute(
                """
                UPDATE message_recipients
                SET is_archived = 1, archived_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
            conn.commit()
            logger.info("[MESSAGE] archive id=%s by=%s", message_id, user.username)


def _format_archive_timestamp(value: str | None) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    if not value:
        return now.isoformat().replace("+00:00", "Z"), now
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return now.isoformat().replace("+00:00", "Z"), now
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), parsed


def _archive_message_safe(
    *,
    message_id: int,
    created_at: str | None,
    sender_username: str,
    sender_role: str,
    recipients: list[str],
    category: str,
    content: str,
) -> None:
    created_at_iso, created_at_dt = _format_archive_timestamp(created_at)
    archive_month = created_at_dt.strftime("%Y-%m")
    archive_dir = MESSAGE_ARCHIVE_ROOT / archive_month
    archive_path = archive_dir / "messages.jsonl"
    payload = {
        "id": message_id,
        "created_at": created_at_iso,
        "sender_username": sender_username,
        "sender_role": sender_role,
        "recipients": recipients,
        "category": category,
        "content": content,
    }
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        with archive_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Impossible d'archiver le message sur disque: %s", exc)


def create_user(payload: models.UserCreate) -> models.User:
    ensure_database_ready()
    hashed = security.hash_password(payload.password)
    site_key = sites.normalize_site_key(payload.site_key) if payload.site_key else db.DEFAULT_SITE_KEY
    email = payload.username.strip()
    normalized_email = _normalize_email(email)
    if not normalized_email:
        raise ValueError("L'email est requis")
    with db.get_users_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE email_normalized = ?",
            (normalized_email,),
        ).fetchone()
        if exists:
            raise ValueError("Cet email existe déjà")
        try:
            cur = conn.execute(
                """
                INSERT INTO users (
                    username,
                    email,
                    email_normalized,
                    password,
                    role,
                    is_active,
                    status,
                    site_key,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, 1, 'active', ?, CURRENT_TIMESTAMP)
                """,
                (payload.username, email, normalized_email, hashed, payload.role, site_key),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Cet email existe déjà") from exc
        conn.commit()
        user_id = cur.lastrowid
    created = get_user_by_id(user_id)
    if created is None:  # pragma: no cover - inserted row should exist
        raise ValueError("Échec de la création de l'utilisateur")
    sites.set_user_site_assignment(payload.username, site_key)
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
        if current.status in ("active", "disabled"):
            fields["is_active"] = 1 if payload.is_active else 0
            fields["status"] = "active" if payload.is_active else "disabled"
    if payload.site_key is not None:
        fields["site_key"] = sites.normalize_site_key(payload.site_key) or db.DEFAULT_SITE_KEY

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
    if payload.site_key is not None:
        sites.set_user_site_assignment(updated.username, updated.site_key)
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
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM user_site_assignments WHERE username = ?", (current.username,))
        conn.execute("DELETE FROM user_site_overrides WHERE username = ?", (current.username,))
        conn.execute("DELETE FROM user_page_layouts WHERE username = ?", (current.username,))
        conn.commit()


def authenticate_with_identifier(identifier: str, password: str) -> tuple[models.User | None, bool]:
    ensure_database_ready()
    normalized_identifier = identifier.strip()
    with db.get_users_connection() as conn:
        if "@" in normalized_identifier:
            normalized_email = _normalize_email(normalized_identifier)
            row = conn.execute(
                "SELECT * FROM users WHERE email_normalized = ?",
                (normalized_email,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?",
                (normalized_identifier,),
            ).fetchone()
        if not row:
            return None, False
        if not security.verify_password(password, row["password"]):
            return None, False
        email = row["email"] if "email" in row.keys() else None
        needs_email_upgrade = not email or not str(email).strip() or "@" not in str(email)
        return _build_user_from_row(row), needs_email_upgrade


def authenticate(username: str, password: str) -> Optional[models.User]:
    user, _ = authenticate_with_identifier(username, password)
    return user


def register_user(payload: models.RegisterRequest) -> models.User:
    ensure_database_ready()
    email = payload.email.strip() if payload.email else ""
    otp_email_enabled = bool(payload.otp_email_enabled)
    if payload.otp_method == "email":
        if not email:
            raise ValueError("L'email est requis")
        if "@" not in email:
            raise ValueError("Email invalide")
    if email and "@" not in email:
        raise ValueError("Email invalide")
    normalized_email = _normalize_email(email) if email else None
    username = email if email else _generate_pending_username(payload.display_name)
    hashed = security.hash_password(payload.password)
    with db.get_users_connection() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "email_normalized" not in columns:
            raise UsersDbNotReadyError("DB users pas migrée")
        if normalized_email:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE email_normalized = ?",
                (normalized_email,),
            ).fetchone()
            if exists:
                raise ValueError("Cet email existe déjà")
        cur = conn.execute(
            """
            INSERT INTO users (
                username,
                email,
                email_normalized,
                password,
                role,
                is_active,
                status,
                otp_email_enabled,
                site_key,
                display_name,
                created_at
            )
            VALUES (?, ?, ?, ?, 'user', 0, 'pending', ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                username,
                email or None,
                normalized_email,
                hashed,
                1 if otp_email_enabled else 0,
                db.DEFAULT_SITE_KEY,
                payload.display_name,
            ),
        )
        conn.commit()
        user_id = cur.lastrowid
    created = get_user_by_id(user_id)
    if created is None:  # pragma: no cover
        raise ValueError("Échec de la création de l'utilisateur")
    sites.set_user_site_assignment(created.username, db.DEFAULT_SITE_KEY)
    return created


def approve_user(user_id: int, approved_by: models.User) -> models.User:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ValueError("Utilisateur introuvable")
        conn.execute(
            """
            UPDATE users
            SET status = 'active',
                is_active = 1,
                approved_at = CURRENT_TIMESTAMP,
                approved_by = ?,
                rejected_at = NULL,
                rejected_by = NULL
            WHERE id = ?
            """,
            (approved_by.username, user_id),
        )
        conn.commit()
    updated = get_user_by_id(user_id)
    if updated is None:  # pragma: no cover
        raise ValueError("Utilisateur introuvable")
    return updated


def reject_user(user_id: int, rejected_by: models.User) -> models.User:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ValueError("Utilisateur introuvable")
        conn.execute(
            """
            UPDATE users
            SET status = 'rejected',
                is_active = 0,
                rejected_at = CURRENT_TIMESTAMP,
                rejected_by = ?,
                approved_at = NULL,
                approved_by = NULL
            WHERE id = ?
            """,
            (rejected_by.username, user_id),
        )
        conn.commit()
    updated = get_user_by_id(user_id)
    if updated is None:  # pragma: no cover
        raise ValueError("Utilisateur introuvable")
    return updated


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


def _generate_lot_positions(
    base: models.PointerTarget, count: int
) -> list[tuple[float, float]]:
    if count <= 0:
        return []
    if count == 1:
        return [(min(max(base.x, 0.0), 1.0), min(max(base.y, 0.0), 1.0))]

    radius = min(0.18, 0.04 + count * 0.015)
    positions: list[tuple[float, float]] = []
    for index in range(count):
        angle = (index / count) * math.pi * 2
        x = min(max(base.x + math.cos(angle) * radius, 0.0), 1.0)
        y = min(max(base.y + math.sin(angle) * radius, 0.0), 1.0)
        positions.append((x, y))
    return positions


def apply_pharmacy_lot(
    payload: models.VehiclePharmacyLotApply,
) -> models.VehiclePharmacyLotApplyResult:
    ensure_database_ready()
    target_view = payload.target_view.strip() if payload.target_view else None
    if target_view == "":
        target_view = None
    with db.get_stock_connection() as conn:
        _ensure_vehicle_item_columns(conn)
        _ensure_vehicle_category_columns(conn)
        _ensure_pharmacy_lot_item_columns(conn)
        _ensure_vehicle_applied_lot_table(conn)
        _require_pharmacy_lot(conn, payload.lot_id)

        vehicle_row = conn.execute(
            "SELECT id, vehicle_type FROM vehicle_categories WHERE id = ?",
            (payload.vehicle_id,),
        ).fetchone()
        if vehicle_row is None:
            raise ValueError("Catégorie de véhicule introuvable")
        if vehicle_row["vehicle_type"] and vehicle_row["vehicle_type"] != "secours_a_personne":
            raise ValueError("Ce lot pharmacie est réservé aux véhicules VSAV.")

        existing = conn.execute(
            """
            SELECT 1
            FROM vehicle_pharmacy_lot_assignments
            WHERE vehicle_category_id = ? AND lot_id = ?
            """,
            (payload.vehicle_id, payload.lot_id),
        ).fetchone()
        if existing:
            raise ValueError("Ce lot pharmacie a déjà été appliqué à ce véhicule.")

        lot_items = conn.execute(
            """
            SELECT pli.pharmacy_item_id,
                   pli.quantity,
                   pi.name,
                   pi.barcode AS sku,
                   pi.quantity AS available_quantity
            FROM pharmacy_lot_items AS pli
            JOIN pharmacy_items AS pi ON pi.id = pli.pharmacy_item_id
            WHERE pli.lot_id = ?
            ORDER BY pi.name COLLATE NOCASE
            """,
            (payload.lot_id,),
        ).fetchall()
        if not lot_items:
            raise ValueError("Lot vide")

        base_position = payload.drop_position or models.PointerTarget(x=0.5, y=0.5)
        distributed_positions = _generate_lot_positions(base_position, len(lot_items))

        missing_items: list[str] = []
        for row in lot_items:
            available = row["available_quantity"] or 0
            required = row["quantity"] or 0
            if available < required:
                shortage = required - available
                missing_items.append(f"{row['name']} ({shortage} manquant(s))")
        if missing_items:
            details = ", ".join(missing_items)
            raise ValueError(
                "Stock insuffisant en pharmacie pour appliquer ce lot. "
                f"Manquants : {details}."
            )

        lot_name_row = conn.execute(
            "SELECT name FROM pharmacy_lots WHERE id = ?",
            (payload.lot_id,),
        ).fetchone()
        lot_name = lot_name_row["name"] if lot_name_row else None
        applied_lot_cursor = conn.execute(
            """
            INSERT INTO vehicle_applied_lots (
                vehicle_id,
                vehicle_type,
                view,
                source,
                pharmacy_lot_id,
                lot_name,
                position_x,
                position_y
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.vehicle_id,
                vehicle_row["vehicle_type"],
                target_view,
                "pharmacy",
                payload.lot_id,
                lot_name,
                base_position.x,
                base_position.y,
            ),
        )
        applied_lot_id = int(applied_lot_cursor.lastrowid)

        created_item_ids: list[int] = []
        for index, row in enumerate(lot_items):
            pharmacy_item_id = row["pharmacy_item_id"]
            sku = row["sku"] or f"PHARM-{pharmacy_item_id}"
            insert_sku = f"{sku}-{uuid4().hex[:6]}"
            position_x, position_y = distributed_positions[index]
            cursor = conn.execute(
                """
                INSERT INTO vehicle_items (
                    name,
                    sku,
                    category_id,
                    vehicle_type,
                    size,
                    quantity,
                    low_stock_threshold,
                    supplier_id,
                    remise_item_id,
                    pharmacy_item_id,
                    position_x,
                    position_y,
                    documentation_url,
                    tutorial_url,
                    shared_file_url,
                    qr_token,
                    show_in_qr,
                    lot_id,
                    applied_lot_source,
                    applied_lot_assignment_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["name"],
                    insert_sku,
                    payload.vehicle_id,
                    vehicle_row["vehicle_type"],
                    target_view,
                    row["quantity"],
                    0,
                    None,
                    None,
                    pharmacy_item_id,
                    position_x,
                    position_y,
                    None,
                    None,
                    None,
                    uuid4().hex,
                    1,
                    None,
                    "pharmacy",
                    applied_lot_id,
                ),
            )
            created_item_ids.append(int(cursor.lastrowid))
            _update_pharmacy_quantity(conn, pharmacy_item_id, -row["quantity"])

        conn.execute(
            """
            INSERT INTO vehicle_pharmacy_lot_assignments (vehicle_category_id, lot_id)
            VALUES (?, ?)
            """,
            (payload.vehicle_id, payload.lot_id),
        )

        logger.info(
            "[VEHICLE_INVENTORY] apply-pharmacy-lot vehicle_id=%s lot_id=%s target_view=%s created=%s",
            payload.vehicle_id,
            payload.lot_id,
            target_view,
            len(created_item_ids),
        )

        _persist_after_commit(conn, *_inventory_modules_to_persist("vehicle_inventory"))
        return models.VehiclePharmacyLotApplyResult(
            created_item_ids=created_item_ids,
            created_count=len(created_item_ids),
        )


def _build_vehicle_applied_lot(row: sqlite3.Row) -> models.VehicleAppliedLot:
    return models.VehicleAppliedLot(
        id=row["id"],
        vehicle_id=row["vehicle_id"],
        vehicle_type=row["vehicle_type"] if "vehicle_type" in row.keys() else None,
        view=row["view"] if "view" in row.keys() else None,
        source=row["source"],
        pharmacy_lot_id=row["pharmacy_lot_id"] if "pharmacy_lot_id" in row.keys() else None,
        lot_name=row["lot_name"] if "lot_name" in row.keys() else None,
        position_x=row["position_x"] if "position_x" in row.keys() else None,
        position_y=row["position_y"] if "position_y" in row.keys() else None,
        created_at=row["created_at"] if "created_at" in row.keys() else None,
    )


def list_vehicle_applied_lots(
    *, vehicle_id: int | None = None, vehicle_type: str | None = None, view: str | None = None
) -> list[models.VehicleAppliedLot]:
    ensure_database_ready()
    query = "SELECT * FROM vehicle_applied_lots WHERE source = ?"
    params: list[object] = ["pharmacy"]
    if vehicle_id is not None:
        query += " AND vehicle_id = ?"
        params.append(vehicle_id)
    if vehicle_type is not None:
        query += " AND vehicle_type = ?"
        params.append(vehicle_type)
    if view is not None:
        query += " AND view = ?"
        params.append(view)
    query += " ORDER BY created_at DESC"
    with db.get_stock_connection() as conn:
        _ensure_vehicle_applied_lot_table(conn)
        rows = conn.execute(query, tuple(params)).fetchall()
        return [_build_vehicle_applied_lot(row) for row in rows]


def update_vehicle_applied_lot_position(
    assignment_id: int, payload: models.VehicleAppliedLotUpdate
) -> models.VehicleAppliedLot:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_vehicle_applied_lot_table(conn)
        cursor = conn.execute(
            """
            UPDATE vehicle_applied_lots
            SET position_x = ?, position_y = ?
            WHERE id = ?
            """,
            (payload.position_x, payload.position_y, assignment_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Lot appliqué introuvable")
        row = conn.execute(
            "SELECT * FROM vehicle_applied_lots WHERE id = ?",
            (assignment_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Lot appliqué introuvable")
        _persist_after_commit(conn, *_inventory_modules_to_persist("vehicle_inventory"))
        return _build_vehicle_applied_lot(row)


def delete_vehicle_applied_lot(assignment_id: int) -> models.VehicleAppliedLotDeleteResult:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        _ensure_vehicle_applied_lot_table(conn)
        _ensure_vehicle_item_columns(conn)
        row = conn.execute(
            "SELECT * FROM vehicle_applied_lots WHERE id = ?",
            (assignment_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Lot appliqué introuvable")
        if row["source"] != "pharmacy":
            raise ValueError("Lot appliqué introuvable")

        item_rows = conn.execute(
            """
            SELECT id
            FROM vehicle_items
            WHERE applied_lot_source = ? AND applied_lot_assignment_id = ?
            """,
            ("pharmacy", assignment_id),
        ).fetchall()
        item_ids = [int(item["id"]) for item in item_rows]

    deleted_item_ids: list[int] = []
    for item_id in item_ids:
        delete_vehicle_item(item_id)
        deleted_item_ids.append(item_id)

    with db.get_stock_connection() as conn:
        _ensure_vehicle_applied_lot_table(conn)
        _ensure_vehicle_item_columns(conn)
        conn.execute("DELETE FROM vehicle_applied_lots WHERE id = ?", (assignment_id,))

        pharmacy_lot_id = row["pharmacy_lot_id"] if "pharmacy_lot_id" in row.keys() else None
        vehicle_id = row["vehicle_id"] if "vehicle_id" in row.keys() else None
        if pharmacy_lot_id is not None and vehicle_id is not None:
            conn.execute(
                """
                DELETE FROM vehicle_pharmacy_lot_assignments
                WHERE vehicle_category_id = ? AND lot_id = ?
                """,
                (vehicle_id, pharmacy_lot_id),
            )

        _persist_after_commit(conn, *_inventory_modules_to_persist("vehicle_inventory"))
        return models.VehicleAppliedLotDeleteResult(
            restored=True,
            lot_id=pharmacy_lot_id,
            items_removed=len(deleted_item_ids),
            deleted_assignment_id=assignment_id,
            deleted_item_ids=deleted_item_ids,
            deleted_items_count=len(deleted_item_ids),
        )


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
                db.get_stock_db_path().resolve(),
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
        extra=_parse_extra_json(row["extra_json"] if "extra_json" in row.keys() else None),
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
            SELECT rl.id, rl.name, rl.description, rl.created_at, rl.image_path, rl.extra_json,
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
            SELECT rl.id, rl.name, rl.description, rl.created_at, rl.image_path, rl.extra_json,
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
            SELECT rl.id, rl.name, rl.description, rl.created_at, rl.image_path, rl.extra_json,
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
    extra = validate_and_merge_extra("remise_lots", None, payload.extra)
    with db.get_stock_connection() as conn:
        _ensure_remise_lot_columns(conn)
        cur = conn.execute(
            "INSERT INTO remise_lots (name, description, extra_json) VALUES (?, ?, ?)",
            (payload.name.strip(), description, _dump_extra_json(extra)),
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
    if payload.extra is not None:
        with db.get_stock_connection() as conn:
            _ensure_remise_lot_columns(conn)
            row = conn.execute("SELECT extra_json FROM remise_lots WHERE id = ?", (lot_id,)).fetchone()
        if row is None:
            raise ValueError("Lot introuvable")
        extra = validate_and_merge_extra("remise_lots", row["extra_json"], payload.extra)
        assignments.append("extra_json = ?")
        values.append(_dump_extra_json(extra))
    if not assignments:
        return get_remise_lot(lot_id)

    with db.get_stock_connection() as conn:
        _ensure_remise_lot_columns(conn)
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
        extra=_parse_extra_json(row["extra_json"] if "extra_json" in row.keys() else None),
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
            SELECT pl.id, pl.name, pl.description, pl.image_path, pl.created_at, pl.extra_json,
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
            SELECT pl.id, pl.name, pl.description, pl.image_path, pl.created_at, pl.extra_json,
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


def list_pharmacy_lots_with_items(
    *, exclude_applied_vehicle_id: int | None = None
) -> list[models.PharmacyLotWithItems]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        if exclude_applied_vehicle_id is not None:
            _ensure_vehicle_applied_lot_table(conn)
        params: list[object] = []
        query = """
            SELECT pl.id, pl.name, pl.description, pl.image_path, pl.created_at, pl.extra_json,
                   COUNT(pli.id) AS item_count, COALESCE(SUM(pli.quantity), 0) AS total_quantity
            FROM pharmacy_lots AS pl
            LEFT JOIN pharmacy_lot_items AS pli ON pli.lot_id = pl.id
            """
        if exclude_applied_vehicle_id is not None:
            query += """
            WHERE pl.id NOT IN (
                SELECT pharmacy_lot_id
                FROM vehicle_applied_lots
                WHERE vehicle_id = ? AND source = 'pharmacy'
            )
            """
            params.append(exclude_applied_vehicle_id)
        query += """
            GROUP BY pl.id
            ORDER BY pl.created_at DESC
            """
        lot_rows = conn.execute(query, params).fetchall()

        if not lot_rows:
            return []

        lot_ids = [row["id"] for row in lot_rows]
        placeholders = ",".join("?" for _ in lot_ids)
        item_rows = conn.execute(
            f"""
            SELECT pli.id, pli.lot_id, pli.pharmacy_item_id, pli.quantity, pli.compartment_name,
                   pi.name AS pharmacy_name, pi.barcode AS pharmacy_sku, pi.quantity AS available_quantity
            FROM pharmacy_lot_items AS pli
            JOIN pharmacy_items AS pi ON pi.id = pli.pharmacy_item_id
            WHERE pli.lot_id IN ({placeholders})
            ORDER BY pli.lot_id, COALESCE(pli.compartment_name, ''), pi.name
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
    extra = validate_and_merge_extra("pharmacy_lots", None, payload.extra)
    with db.get_stock_connection() as conn:
        _ensure_pharmacy_lot_columns(conn)
        cur = conn.execute(
            "INSERT INTO pharmacy_lots (name, description, extra_json) VALUES (?, ?, ?)",
            (payload.name.strip(), description, _dump_extra_json(extra)),
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
    if payload.extra is not None:
        with db.get_stock_connection() as conn:
            _ensure_pharmacy_lot_columns(conn)
            row = conn.execute("SELECT extra_json FROM pharmacy_lots WHERE id = ?", (lot_id,)).fetchone()
        if row is None:
            raise ValueError("Lot introuvable")
        extra = validate_and_merge_extra("pharmacy_lots", row["extra_json"], payload.extra)
        assignments.append("extra_json = ?")
        values.append(_dump_extra_json(extra))
    if not assignments:
        return get_pharmacy_lot(lot_id)

    with db.get_stock_connection() as conn:
        _ensure_pharmacy_lot_columns(conn)
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
        compartment_name=row["compartment_name"],
        pharmacy_name=row["pharmacy_name"],
        pharmacy_sku=row["pharmacy_sku"],
        available_quantity=row["available_quantity"],
    )


def _get_pharmacy_lot_item(
    conn: sqlite3.Connection, lot_id: int, lot_item_id: int
) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT pli.id, pli.lot_id, pli.pharmacy_item_id, pli.quantity, pli.compartment_name,
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
            SELECT pli.id, pli.lot_id, pli.pharmacy_item_id, pli.quantity, pli.compartment_name,
                   pi.name AS pharmacy_name, pi.barcode AS pharmacy_sku, pi.quantity AS available_quantity
            FROM pharmacy_lot_items AS pli
            JOIN pharmacy_items AS pi ON pi.id = pli.pharmacy_item_id
            WHERE pli.lot_id = ?
            ORDER BY COALESCE(pli.compartment_name, ''), pi.name
            """,
            (lot_id,),
        ).fetchall()
    return [_build_pharmacy_lot_item(row) for row in rows]


def add_pharmacy_lot_item(
    lot_id: int, payload: models.PharmacyLotItemBase
) -> models.PharmacyLotItem:
    ensure_database_ready()
    compartment_name = (payload.compartment_name or "").strip() or None
    with db.get_stock_connection() as conn:
        _require_pharmacy_lot(conn, lot_id)
        existing = conn.execute(
            """
            SELECT id, quantity
            FROM pharmacy_lot_items
            WHERE lot_id = ? AND pharmacy_item_id = ? AND compartment_name IS ?
            """,
            (lot_id, payload.pharmacy_item_id, compartment_name),
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
                """
                INSERT INTO pharmacy_lot_items (lot_id, pharmacy_item_id, quantity, compartment_name)
                VALUES (?, ?, ?, ?)
                """,
                (lot_id, payload.pharmacy_item_id, payload.quantity, compartment_name),
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
        compartment_name = (payload.compartment_name or "").strip() or None
        target_quantity = payload.quantity if payload.quantity is not None else row["quantity"]
        _ensure_pharmacy_lot_capacity(
            conn,
            row["pharmacy_item_id"],
            target_quantity,
            exclude_lot_item_id=lot_item_id,
        )
        updates: list[str] = []
        params: list[object] = []
        if target_quantity != row["quantity"]:
            updates.append("quantity = ?")
            params.append(target_quantity)
        if payload.compartment_name is not None and compartment_name != row["compartment_name"]:
            conflict = conn.execute(
                """
                SELECT 1
                FROM pharmacy_lot_items
                WHERE lot_id = ? AND pharmacy_item_id = ? AND compartment_name IS ? AND id != ?
                """,
                (lot_id, row["pharmacy_item_id"], compartment_name, lot_item_id),
            ).fetchone()
            if conflict:
                raise ValueError("Ce compartiment contient déjà cet article.")
            updates.append("compartment_name = ?")
            params.append(compartment_name)
        if updates:
            params.append(lot_item_id)
            conn.execute(
                f"UPDATE pharmacy_lot_items SET {', '.join(updates)} WHERE id = ?",
                params,
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


def list_suppliers(
    site_key: str | int | None = None, module: str | None = None
) -> list[models.Supplier]:
    ensure_database_ready()
    resolved_site_key = (
        sites.normalize_site_key(str(site_key)) if site_key else db.get_current_site_key()
    )
    migrate_legacy_suppliers_to_site(resolved_site_key)
    module_filter = (module or "").strip().lower()
    with _get_site_stock_conn(resolved_site_key) as conn:
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


def get_supplier(site_key: str | int | None, supplier_id: int) -> models.Supplier:
    ensure_database_ready()
    resolved_site_key = (
        sites.normalize_site_key(str(site_key)) if site_key else db.get_current_site_key()
    )
    migrate_legacy_suppliers_to_site(resolved_site_key)
    with _get_site_stock_conn(resolved_site_key) as conn:
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


def create_supplier(
    site_key: str | int | None, payload: models.SupplierCreate
) -> models.Supplier:
    ensure_database_ready()
    resolved_site_key = (
        sites.normalize_site_key(str(site_key)) if site_key else db.get_current_site_key()
    )
    modules = _normalize_supplier_modules(payload.modules)
    with _get_site_stock_conn(resolved_site_key) as conn:
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
        return get_supplier(resolved_site_key, supplier_id)


def update_supplier(
    site_key: str | int | None, supplier_id: int, payload: models.SupplierUpdate
) -> models.Supplier:
    ensure_database_ready()
    resolved_site_key = (
        sites.normalize_site_key(str(site_key)) if site_key else db.get_current_site_key()
    )
    updates = payload.model_dump(exclude_unset=True)
    modules_update = updates.pop("modules", None)
    fields = {k: v for k, v in updates.items()}
    with _get_site_stock_conn(resolved_site_key) as conn:
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
    return get_supplier(resolved_site_key, supplier_id)


def delete_supplier(site_key: str | int | None, supplier_id: int) -> None:
    ensure_database_ready()
    resolved_site_key = (
        sites.normalize_site_key(str(site_key)) if site_key else db.get_current_site_key()
    )
    with _get_site_stock_conn(resolved_site_key) as conn:
        cur = conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        if cur.rowcount == 0:
            raise ValueError("Fournisseur introuvable")
        conn.commit()


class SupplierResolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_supplier(site_key: str | int, supplier_id: int) -> models.Supplier:
    ensure_database_ready()
    normalized_site_key = sites.normalize_site_key(str(site_key)) if site_key is not None else None
    if not normalized_site_key:
        normalized_site_key = db.DEFAULT_SITE_KEY
    migrate_legacy_suppliers_to_site(normalized_site_key)
    with _get_site_stock_conn(normalized_site_key) as conn:
        row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
        if row is None:
            raise SupplierResolutionError(
                "SUPPLIER_NOT_FOUND",
                "Fournisseur introuvable",
            )
        if "is_active" in row.keys() and not row["is_active"]:
            raise SupplierResolutionError(
                "SUPPLIER_INACTIVE",
                "Fournisseur supprimé ou inactif",
            )
        if "is_deleted" in row.keys() and row["is_deleted"]:
            raise SupplierResolutionError(
                "SUPPLIER_INACTIVE",
                "Fournisseur supprimé ou inactif",
            )
        if "deleted_at" in row.keys() and row["deleted_at"]:
            raise SupplierResolutionError(
                "SUPPLIER_INACTIVE",
                "Fournisseur supprimé ou inactif",
            )
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


def resolve_supplier_for_order(
    conn: sqlite3.Connection,
    site_id: str | int,
    supplier_id: int | None,
) -> models.Supplier | None:
    if supplier_id is None:
        return None
    row = conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()
    if row is None or _is_supplier_inactive(row):
        return None
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


def get_supplier_for_order(site_id: str | int, supplier_id: int | None) -> models.Supplier:
    if supplier_id is None:
        raise SupplierResolutionError(
            "SUPPLIER_MISSING",
            "Bon de commande non associé à un fournisseur",
        )
    migrate_legacy_suppliers_to_site(site_id)
    with db.get_stock_connection(site_id) as conn:
        supplier = resolve_supplier_for_order(conn, site_id, supplier_id)
    if supplier is None:
        raise SupplierResolutionError(
            "SUPPLIER_NOT_FOUND",
            "Fournisseur introuvable",
        )
    return supplier


def require_supplier_email(supplier: models.Supplier) -> str:
    raw_email = str(supplier.email or "").strip()
    if not raw_email:
        raise SupplierResolutionError("SUPPLIER_EMAIL_MISSING", "Email fournisseur manquant")
    normalized = _normalize_email(raw_email)
    if len(normalized) < 5 or "@" not in normalized:
        raise SupplierResolutionError("SUPPLIER_EMAIL_INVALID", "Email fournisseur invalide")
    return normalized


def resolve_supplier_email_for_order(
    *,
    site_id: str | int,
    supplier_id: int | None,
    legacy_supplier_name: str | None,
    legacy_supplier_email: str | None,
) -> tuple[str | None, models.Supplier | None]:
    ensure_database_ready()
    normalized_site_key = sites.normalize_site_key(str(site_id)) if site_id is not None else None
    if not normalized_site_key:
        normalized_site_key = db.DEFAULT_SITE_KEY
    migrate_legacy_suppliers_to_site(normalized_site_key)
    with db.get_stock_connection(normalized_site_key) as conn:
        supplier = resolve_supplier_for_order(conn, normalized_site_key, supplier_id)
    if supplier is None:
        if supplier_id is None:
            raise SupplierResolutionError(
                "SUPPLIER_MISSING",
                "Bon de commande non associé à un fournisseur",
            )
        raise SupplierResolutionError(
            "SUPPLIER_NOT_FOUND",
            "Fournisseur introuvable sur le site actif.",
        )
    normalized_email = require_supplier_email(supplier)
    return normalized_email, supplier


def _build_purchase_order_detail(
    conn: sqlite3.Connection,
    order_row: sqlite3.Row,
    *,
    site_key: str | None = None,
) -> models.PurchaseOrderDetail:
    items_cur = conn.execute(
        """
        SELECT poi.id,
               poi.purchase_order_id,
               poi.item_id,
               poi.quantity_ordered,
               poi.quantity_received,
               i.name AS item_name,
               i.sku AS sku,
               COALESCE(NULLIF(TRIM(i.size), ''), 'Unité') AS unit
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
            sku=item_row["sku"],
            unit=item_row["unit"],
        )
        for item_row in items_cur.fetchall()
    ]
    resolved_email = None
    supplier_has_email = False
    supplier_missing_reason = None
    supplier_id = order_row["supplier_id"]
    supplier = resolve_supplier_for_order(conn, site_key or db.get_current_site_key(), supplier_id)
    if supplier_id is None:
        supplier_missing_reason = "SUPPLIER_MISSING"
    elif supplier is None:
        supplier_missing_reason = "SUPPLIER_NOT_FOUND"
    else:
        try:
            resolved_email = require_supplier_email(supplier)
            supplier_has_email = True
        except SupplierResolutionError as exc:
            supplier_missing_reason = exc.code
    return models.PurchaseOrderDetail(
        id=order_row["id"],
        supplier_id=supplier_id,
        supplier_name=order_row["supplier_name"],
        supplier_email=supplier.email if supplier else None,
        supplier_email_resolved=resolved_email,
        supplier_has_email=supplier_has_email,
        supplier_missing_reason=supplier_missing_reason,
        status=order_row["status"],
        created_at=order_row["created_at"],
        note=order_row["note"],
        auto_created=bool(order_row["auto_created"]),
        last_sent_at=order_row["last_sent_at"],
        last_sent_to=order_row["last_sent_to"],
        last_sent_by=order_row["last_sent_by"],
        items=items,
    )


def list_purchase_orders() -> list[models.PurchaseOrderDetail]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            ORDER BY po.created_at DESC, po.id DESC
            """
        )
        rows = cur.fetchall()
        return [
            _build_purchase_order_detail(conn, row, site_key=db.get_current_site_key())
            for row in rows
        ]


def get_purchase_order(order_id: int) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        return _build_purchase_order_detail(conn, row, site_key=db.get_current_site_key())


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
                INSERT INTO purchase_orders (supplier_id, status, note, auto_created, created_at)
                VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
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


def _build_purchase_order_blocks(
    order: models.PurchaseOrderDetail
    | models.RemisePurchaseOrderDetail
    | models.PharmacyPurchaseOrderDetail,
) -> tuple[dict[str, str | None], dict[str, str | None], dict[str, str | None]]:
    supplier = None
    if order.supplier_id is not None:
        with db.get_stock_connection() as conn:
            supplier = resolve_supplier_for_order(
                conn, db.get_current_site_key(), order.supplier_id
            )
    supplier_name = order.supplier_name or (supplier.name if supplier else None)
    buyer_block = {
        "Nom": None,
        "Téléphone": None,
        "Email": None,
    }
    supplier_block = {
        "Nom": supplier_name,
        "Contact": supplier.contact_name if supplier else None,
        "Téléphone": supplier.phone if supplier else None,
        "Email": supplier.email if supplier else None,
        "Adresse": supplier.address if supplier else None,
    }
    delivery_block: dict[str, str | None] = {
        "Adresse": None,
        "Date souhaitée": None,
        "Contact": None,
    }
    return buyer_block, supplier_block, delivery_block


def _format_date_label(value: date | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d/%m/%Y")


def _render_remise_inventory_pdf(
    *, items: list[models.Item], category_map: dict[int, str], module_title: str
) -> bytes:
    resolved = resolve_pdf_config("remise_inventory")
    pdf_config = resolved.config
    buffer = io.BytesIO()
    page_size = page_size_for_format(pdf_config.format)
    pdf = canvas.Canvas(buffer, pagesize=page_size)
    width, height = page_size
    margin_top, margin_right, margin_bottom, margin_left = margins_for_format(pdf_config.format)
    scale = effective_density_scale(pdf_config.format)
    base_row_padding = 10 * scale
    line_height = 12 * scale
    header_height = 24 * scale
    theme = scale_reportlab_theme(resolve_reportlab_theme(pdf_config.theme), scale)

    base_columns: list[tuple[str, float, str, str]] = [
        ("name", "MATÉRIEL", 0.28, "left"),
        ("quantity", "QUANTITÉ", 0.10, "center"),
        ("size", "TAILLE / VARIANTE", 0.14, "center"),
        ("category", "CATÉGORIE", 0.16, "center"),
        ("lots", "LOT(S)", 0.12, "center"),
        ("expiration", "PÉREMPTION", 0.10, "center"),
        ("threshold", "SEUIL", 0.10, "center"),
    ]
    visible_keys = [col.key for col in pdf_config.content.columns if col.visible]
    if visible_keys:
        columns = [col for col in base_columns if col[0] in visible_keys]
    else:
        columns = base_columns

    table_width = width - margin_left - margin_right
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
        apply_theme_reportlab(pdf, page_size, pdf_config.theme, scale=scale)
        pdf.setFillColor(theme.text_color)

    def start_page(page_number: int) -> float:
        draw_page_background()
        draw_watermark(pdf, pdf_config, page_size, scale=scale)
        y_offset = height - margin_top
        if pdf_config.header.enabled:
            pdf.setFont(theme.font_family, theme.heading_font_size)
            pdf.drawString(margin_left, y_offset + (4 * scale), module_title)
            pdf.setFont(theme.font_family, theme.base_font_size)
            pdf.setFillColor(theme.muted_text_color)
            pdf.drawString(
                margin_left,
                y_offset - (10 * scale),
                f"Généré le {_format_date_label(generated_at.date())} à {generated_at.strftime('%H:%M')}",
            )
            pdf.setFillColor(theme.text_color)
            y_offset -= header_height
        if pdf_config.footer.enabled and pdf_config.footer.show_pagination:
            pdf.drawRightString(width - margin_right, margin_bottom - (6 * scale), f"Page {page_number}")
        return y_offset

    def draw_header(y_position: float) -> float:
        pdf.setFillColor(theme.table_header_bg)
        pdf.rect(
            margin_left,
            y_position - header_height + (4 * scale),
            table_width,
            header_height,
            stroke=0,
            fill=1,
        )
        pdf.setFillColor(theme.table_header_text)
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        x = margin_left
        for _, label, ratio, align in columns:
            cell_width = ratio * table_width
            if align == "center":
                pdf.drawCentredString(x + cell_width / 2, y_position - (6 * scale), label)
            else:
                pdf.drawString(x + (4 * scale), y_position - (6 * scale), label)
            x += cell_width
        pdf.setStrokeColor(theme.border_color)
        pdf.rect(
            margin_left,
            y_position - header_height + (4 * scale),
            table_width,
            header_height,
            stroke=1,
            fill=0,
        )
        pdf.setFont(theme.font_family, theme.base_font_size - (1 * scale))
        pdf.setFillColor(theme.text_color)
        return y_position - header_height

    y = start_page(1)
    y = draw_header(y)
    page_number = 1

    row_index = 0
    grouping = pdf_config.grouping
    grouping_keys = [key for key in grouping.keys if key]
    if grouping.enabled and not grouping_keys and pdf_config.content.group_by:
        grouping_keys = [pdf_config.content.group_by]

    label_map = {key: label for key, label, _, _ in base_columns}

    def ensure_row_space(required_height: float) -> None:
        nonlocal y, page_number
        if y <= margin_bottom + required_height:
            pdf.showPage()
            page_number += 1
            y = start_page(page_number)
            y = draw_header(y)

    def render_group_header(group: GroupNode) -> None:
        nonlocal y
        if grouping.header_style == "none":
            return
        stats = compute_group_stats(group, value_fn=lambda row, key: row["raw"].get(key))
        count = stats.row_count if grouping.counts_scope == "leaf" else (
            stats.child_count if group.children else stats.row_count
        )
        label = label_map.get(group.key, group.key)
        value = group.value if group.value not in (None, "") else "—"
        header_text = f"{label} : {value}"
        if grouping.show_counts:
            header_text = f"{header_text} ({count})"
        header_height = 16
        ensure_row_space(header_height + base_row_padding)
        if grouping.header_style == "bar":
            pdf.setFillColor(theme.table_header_bg)
            pdf.rect(margin_left, y - header_height + 6, table_width, header_height, stroke=0, fill=1)
            pdf.setFillColor(theme.table_header_text)
        else:
            pdf.setFillColor(theme.text_color)
        pdf.setFont(theme.font_family, theme.base_font_size)
        pdf.drawString(margin_left + 4, y - 4, header_text)
        pdf.setFillColor(theme.text_color)
        y -= header_height

    def render_subtotal(group: GroupNode) -> None:
        nonlocal y
        if not grouping.show_subtotals:
            return
        if grouping.subtotal_scope == "leaf" and group.children:
            return
        subtotal_columns = set(grouping.subtotal_columns)
        if not subtotal_columns:
            return
        stats = compute_group_stats(
            group,
            subtotal_columns=subtotal_columns,
            value_fn=lambda row, key: row["raw"].get(key),
        )
        first_key = columns[0][0] if columns else "name"
        subtotal_display = {
            key: (str(stats.subtotals[key]) if key in stats.subtotals else "")
            for key, _, _, _ in base_columns
        }
        subtotal_display[first_key] = "Sous-total"
        wrapped_values: list[tuple[list[str], float, str]] = []
        for key, _, ratio, align in columns:
            cell_width = ratio * table_width
            value = subtotal_display.get(key, "")
            lines = _wrap_to_width(
                str(value),
                cell_width - 8,
                theme.font_family,
                theme.base_font_size - 1,
            )
            wrapped_values.append((lines, cell_width, align))
        row_height = line_height + base_row_padding
        ensure_row_space(row_height)
        pdf.setFillColor(theme.background_color)
        pdf.rect(margin_left, y - row_height + 6, table_width, row_height, stroke=0, fill=1)
        pdf.setStrokeColor(theme.border_color)
        pdf.rect(margin_left, y - row_height + 6, table_width, row_height, stroke=1, fill=0)
        pdf.setFillColor(theme.text_color)
        x = margin_left
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

    def render_row(row: dict[str, dict[str, object]]) -> None:
        nonlocal y, row_index
        values: list[tuple[str, float, str]] = [
            (str(row["display"].get(key, "")), ratio, align) for key, _, ratio, align in columns
        ]
        wrapped_values: list[tuple[list[str], float, str]] = []
        max_line_count = 1
        for value, ratio, align in values:
            cell_width = ratio * table_width
            lines = _wrap_to_width(
                str(value),
                cell_width - (8 * scale),
                theme.font_family,
                theme.base_font_size - (1 * scale),
            )
            max_line_count = max(max_line_count, len(lines))
            wrapped_values.append((lines, cell_width, align))

        row_height = max_line_count * line_height + base_row_padding
        ensure_row_space(row_height)

        pdf.setFillColor(theme.table_row_alt_bg if row_index % 2 else theme.background_color)
        pdf.rect(margin_left, y - row_height + 6, table_width, row_height, stroke=0, fill=1)
        pdf.setStrokeColor(theme.border_color)
        pdf.rect(margin_left, y - row_height + (6 * scale), table_width, row_height, stroke=1, fill=0)
        pdf.setFillColor(theme.text_color)

        x = margin_left
        for lines, cell_width, align in wrapped_values:
            text_y = y - (8 * scale)
            for line in lines:
                if align == "center":
                    pdf.drawCentredString(x + cell_width / 2, text_y, line)
                else:
                    pdf.drawString(x + (4 * scale), text_y, line)
                text_y -= line_height
            x += cell_width

        row_index += 1
        y -= row_height

    row_payloads: list[dict[str, dict[str, object]]] = []
    for item in items:
        category_label = _format_cell(category_map.get(item.category_id or -1, None) if item.category_id else None)
        lots_label = _format_cell(", ".join(item.lot_names) if item.lot_names else None)
        expiration_label = _format_date_label(item.expiration_date)
        expiration_label = "-" if expiration_label == "—" else expiration_label
        threshold_label = str(item.low_stock_threshold or 1) if item.track_low_stock else "1"
        size_label = _format_cell(item.size)
        name_label = _format_cell(item.name)

        display = {
            "name": name_label,
            "quantity": str(item.quantity or 0),
            "size": size_label,
            "category": category_label,
            "lots": lots_label,
            "expiration": expiration_label,
            "threshold": threshold_label,
        }
        raw = {
            "name": name_label,
            "quantity": item.quantity or 0,
            "size": size_label,
            "category": category_label,
            "lots": lots_label,
            "expiration": item.expiration_date,
            "threshold": item.low_stock_threshold or 1,
        }
        row_payloads.append({"display": display, "raw": raw})

    if grouping.enabled and grouping_keys:
        group_tree = build_group_tree(
            row_payloads,
            grouping_keys,
            key_fn=lambda row, key: row["raw"].get(key),
        )

        def render_group(group: GroupNode, *, level: int, is_first_level: bool) -> None:
            nonlocal y, page_number
            if grouping.page_break_between_level1 and level == 0 and not is_first_level:
                pdf.showPage()
                page_number += 1
                y = start_page(page_number)
                y = draw_header(y)
            render_group_header(group)
            if group.children:
                for index, child in enumerate(group.children):
                    render_group(child, level=level + 1, is_first_level=index == 0)
            else:
                for row in group.rows:
                    render_row(row)
            render_subtotal(group)

        for index, group in enumerate(group_tree):
            render_group(group, level=0, is_first_level=index == 0)
    else:
        for row in row_payloads:
            render_row(row)

    pdf.save()
    return buffer.getvalue()


def generate_purchase_order_pdf(order: models.PurchaseOrderDetail) -> bytes:
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(order)
    return render_purchase_order_pdf(
        title="BON DE COMMANDE",
        purchase_order=order,
        buyer_block=buyer_block,
        supplier_block=supplier_block,
        delivery_block=delivery_block,
        include_received=False,
    )


def generate_purchase_order_reception_pdf(order: models.PurchaseOrderDetail) -> bytes:
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(order)
    return render_purchase_order_pdf(
        title="BON DE COMMANDE",
        purchase_order=order,
        buyer_block=buyer_block,
        supplier_block=supplier_block,
        delivery_block=delivery_block,
        include_received=True,
    )


def _get_site_info_for_email(site_key: str) -> models.SiteInfo:
    try:
        sites_list = sites.list_sites()
    except Exception:
        sites_list = []
    for site in sites_list:
        if site.site_key == site_key:
            return site
    return models.SiteInfo(
        site_key=site_key,
        display_name=site_key,
        db_path=str(db.get_stock_db_path(site_key)),
        is_active=True,
    )


def _record_purchase_order_email_log(
    *,
    created_at: str,
    site_key: str,
    module_key: str,
    purchase_order_id: int,
    purchase_order_number: str | None,
    supplier_id: int | None,
    supplier_email: str,
    user_id: int | None,
    user_email: str | None,
    status: str,
    message_id: str | None = None,
    error_message: str | None = None,
) -> None:
    with db.get_core_connection() as conn:
        conn.execute(
            """
            INSERT INTO purchase_order_email_log (
                created_at,
                site_key,
                module_key,
                purchase_order_id,
                purchase_order_number,
                supplier_id,
                supplier_email,
                user_id,
                user_email,
                status,
                message_id,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                site_key,
                module_key,
                purchase_order_id,
                purchase_order_number,
                supplier_id,
                supplier_email,
                user_id,
                user_email,
                status,
                message_id,
                error_message,
            ),
        )
        conn.commit()


def _record_purchase_order_audit_log(
    *,
    created_at: str,
    site_key: str,
    module_key: str,
    action: str,
    purchase_order_id: int,
    supplier_id: int | None,
    supplier_name: str | None,
    supplier_email: str | None,
    recipient_email: str | None,
    user_id: int | None,
    user_email: str | None,
    status: str,
    message: str | None,
) -> None:
    with db.get_core_connection() as conn:
        conn.execute(
            """
            INSERT INTO purchase_order_audit_log (
                created_at,
                site_key,
                module_key,
                action,
                purchase_order_id,
                supplier_id,
                supplier_name,
                supplier_email,
                recipient_email,
                user_id,
                user_email,
                status,
                message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                site_key,
                module_key,
                action,
                purchase_order_id,
                supplier_id,
                supplier_name,
                supplier_email,
                recipient_email,
                user_id,
                user_email,
                status,
                message,
            ),
        )
        conn.commit()


def send_purchase_order_to_supplier(
    site_key: str,
    purchase_order_id: int,
    sent_by_user: models.User,
    *,
    to_email_override: str | None = None,
) -> models.PurchaseOrderSendResponse:
    ensure_database_ready()
    normalized_site_key = sites.normalize_site_key(site_key) or db.DEFAULT_SITE_KEY
    with db.get_stock_connection(normalized_site_key) as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (purchase_order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        order = _build_purchase_order_detail(conn, row, site_key=normalized_site_key)
        supplier_id = row["supplier_id"]
        supplier_name = row["supplier_name"]
        supplier_email = row["supplier_email"]

    try:
        supplier = get_supplier_for_order(normalized_site_key, supplier_id)
        resolved_email = require_supplier_email(supplier)
    except SupplierResolutionError as exc:
        sent_at = datetime.now(timezone.utc).isoformat()
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="purchase_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=None,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="error",
            message=str(exc),
        )
        raise

    to_email = resolved_email
    supplier_name = supplier.name if supplier else supplier_name
    supplier_email = supplier.email if supplier else supplier_email
    if to_email_override:
        to_email = _normalize_email(to_email_override)
    sent_at = datetime.now(timezone.utc).isoformat()
    site_info = _get_site_info_for_email(normalized_site_key)
    subject, body_text, body_html = notifications.build_purchase_order_email(
        order, site_info, sent_by_user
    )
    pdf_bytes = generate_purchase_order_pdf(order)
    resolved = resolve_pdf_config("purchase_orders")
    filename = render_filename(
        resolved.config.filename.pattern,
        module_key="purchase_orders",
        module_title=resolved.module_label,
        context={"order_id": order.id, "ref": order.id},
    )
    reply_to = sent_by_user.email if sent_by_user.email and "@" in sent_by_user.email else None
    try:
        message_id = email_sender.send_email(
            to_email,
            subject,
            body_text,
            body_html,
            reply_to=reply_to,
            attachments=[(filename, pdf_bytes, "application/pdf")],
            sensitive=True,
        )
        _record_purchase_order_email_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="purchase_orders",
            purchase_order_id=order.id,
            purchase_order_number=str(order.id),
            supplier_id=supplier_id,
            supplier_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="sent",
            message_id=message_id,
        )
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="purchase_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="ok",
            message=f"Email envoyé ({message_id})",
        )
    except email_sender.EmailSendError as exc:
        _record_purchase_order_email_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="purchase_orders",
            purchase_order_id=order.id,
            purchase_order_number=str(order.id),
            supplier_id=supplier_id,
            supplier_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="failed",
            error_message=str(exc),
        )
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="purchase_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="error",
            message=str(exc),
        )
        raise

    with db.get_stock_connection(normalized_site_key) as conn:
        conn.execute(
            """
            UPDATE purchase_orders
            SET last_sent_at = ?, last_sent_to = ?, last_sent_by = ?
            WHERE id = ?
            """,
            (
                sent_at,
                to_email,
                sent_by_user.email or sent_by_user.username,
                order.id,
            ),
        )
        conn.commit()

    return models.PurchaseOrderSendResponse(
        status="sent",
        sent_to=to_email,
        sent_at=sent_at,
        message_id=message_id,
    )


def send_remise_purchase_order_to_supplier(
    site_key: str,
    purchase_order_id: int,
    sent_by_user: models.User,
    *,
    to_email_override: str | None = None,
) -> models.PurchaseOrderSendResponse:
    ensure_database_ready()
    normalized_site_key = sites.normalize_site_key(site_key) or db.DEFAULT_SITE_KEY
    with db.get_stock_connection(normalized_site_key) as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name
            FROM remise_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (purchase_order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        order = _build_remise_purchase_order_detail(
            conn,
            row,
            site_key=normalized_site_key,
        )
        supplier_id = row["supplier_id"]
        supplier_name = row["supplier_name"]

    try:
        supplier = get_supplier_for_order(normalized_site_key, supplier_id)
        resolved_email = require_supplier_email(supplier)
    except SupplierResolutionError as exc:
        sent_at = datetime.now(timezone.utc).isoformat()
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="remise_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=None,
            recipient_email=None,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="error",
            message=str(exc),
        )
        raise

    to_email = resolved_email
    supplier_name = supplier.name if supplier else supplier_name
    supplier_email = supplier.email if supplier else None
    if to_email_override:
        to_email = _normalize_email(to_email_override)
    site_info = _get_site_info_for_email(normalized_site_key)
    subject, body_text, body_html = notifications.build_purchase_order_email(
        order, site_info, sent_by_user
    )
    subject = f"Bon de commande REMISE - {site_info.display_name or site_info.site_key} - #{order.id}"
    pdf_bytes = generate_remise_purchase_order_pdf(order)
    resolved = resolve_pdf_config("remise_orders")
    filename = render_filename(
        resolved.config.filename.pattern,
        module_key="remise_orders",
        module_title=resolved.module_label,
        context={"order_id": order.id, "ref": order.id},
    )
    reply_to = sent_by_user.email if sent_by_user.email and "@" in sent_by_user.email else None
    sent_at = datetime.now(timezone.utc).isoformat()
    try:
        message_id = email_sender.send_email(
            to_email,
            subject,
            body_text,
            body_html,
            reply_to=reply_to,
            attachments=[(filename, pdf_bytes, "application/pdf")],
            sensitive=True,
        )
        _record_purchase_order_email_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="remise_orders",
            purchase_order_id=order.id,
            purchase_order_number=str(order.id),
            supplier_id=supplier_id,
            supplier_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="sent",
            message_id=message_id,
        )
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="remise_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="ok",
            message=f"Email envoyé ({message_id})",
        )
    except email_sender.EmailSendError as exc:
        _record_purchase_order_email_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="remise_orders",
            purchase_order_id=order.id,
            purchase_order_number=str(order.id),
            supplier_id=supplier_id,
            supplier_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="failed",
            error_message=str(exc),
        )
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="remise_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="error",
            message=str(exc),
        )
        raise

    return models.PurchaseOrderSendResponse(
        status="sent",
        sent_to=to_email,
        sent_at=sent_at,
        message_id=message_id,
    )


def list_purchase_order_email_logs(
    site_key: str,
    purchase_order_id: int,
    module_key: str | None = None,
) -> list[models.PurchaseOrderEmailLogEntry]:
    ensure_database_ready()
    normalized_site_key = sites.normalize_site_key(site_key) or db.DEFAULT_SITE_KEY
    with db.get_core_connection() as conn:
        if module_key:
            rows = conn.execute(
                """
                SELECT *
                FROM purchase_order_email_log
                WHERE site_key = ? AND purchase_order_id = ? AND module_key = ?
                ORDER BY created_at DESC
                """,
                (normalized_site_key, purchase_order_id, module_key),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM purchase_order_email_log
                WHERE site_key = ? AND purchase_order_id = ?
                ORDER BY created_at DESC
                """,
                (normalized_site_key, purchase_order_id),
            ).fetchall()
    return [
        models.PurchaseOrderEmailLogEntry(
            id=row["id"],
            created_at=row["created_at"],
            site_key=row["site_key"],
            module_key=row["module_key"],
            purchase_order_id=row["purchase_order_id"],
            purchase_order_number=row["purchase_order_number"],
            supplier_id=row["supplier_id"],
            supplier_email=row["supplier_email"],
            user_id=row["user_id"],
            user_email=row["user_email"],
            status=row["status"],
            message_id=row["message_id"],
            error_message=row["error_message"],
        )
        for row in rows
    ]


def _delete_purchase_order_record(
    *,
    site_key: str,
    purchase_order_id: int,
    module_key: str,
    order_table: str,
    items_table: str,
    not_found_message: str,
    requested_by: models.User,
) -> None:
    ensure_database_ready()
    normalized_site_key = sites.normalize_site_key(site_key) or db.DEFAULT_SITE_KEY
    with db.get_stock_connection(normalized_site_key) as conn:
        row = conn.execute(
            f"""
            SELECT po.id,
                   po.status,
                   po.supplier_id,
                   s.name AS supplier_name,
                   s.email AS supplier_email
            FROM {order_table} AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (purchase_order_id,),
        ).fetchone()
        if row is None:
            raise ValueError(not_found_message)
        status = str(row["status"] or "").strip().upper()
        if status == "RECEIVED":
            sent_at = datetime.now(timezone.utc).isoformat()
            _record_purchase_order_audit_log(
                created_at=sent_at,
                site_key=normalized_site_key,
                module_key=module_key,
                action="delete",
                purchase_order_id=purchase_order_id,
                supplier_id=row["supplier_id"],
                supplier_name=row["supplier_name"],
                supplier_email=row["supplier_email"],
                recipient_email=None,
                user_id=requested_by.id,
                user_email=requested_by.email,
                status="error",
                message="Impossible de supprimer un BC reçu",
            )
            raise ValueError("Impossible de supprimer un BC reçu")
        try:
            conn.execute("BEGIN")
            conn.execute(
                f"DELETE FROM {items_table} WHERE purchase_order_id = ?",
                (purchase_order_id,),
            )
            conn.execute(f"DELETE FROM {order_table} WHERE id = ?", (purchase_order_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    sent_at = datetime.now(timezone.utc).isoformat()
    _record_purchase_order_audit_log(
        created_at=sent_at,
        site_key=normalized_site_key,
        module_key=module_key,
        action="delete",
        purchase_order_id=purchase_order_id,
        supplier_id=row["supplier_id"],
        supplier_name=row["supplier_name"],
        supplier_email=row["supplier_email"],
        recipient_email=None,
        user_id=requested_by.id,
        user_email=requested_by.email,
        status="ok",
        message="Suppression effectuée",
    )


def delete_purchase_order(site_key: str, order_id: int, user: models.User) -> None:
    _delete_purchase_order_record(
        site_key=site_key,
        purchase_order_id=order_id,
        module_key="purchase_orders",
        order_table="purchase_orders",
        items_table="purchase_order_items",
        not_found_message="Bon de commande introuvable",
        requested_by=user,
    )


def delete_remise_purchase_order(site_key: str, order_id: int, user: models.User) -> None:
    _delete_purchase_order_record(
        site_key=site_key,
        purchase_order_id=order_id,
        module_key="remise_orders",
        order_table="remise_purchase_orders",
        items_table="remise_purchase_order_items",
        not_found_message="Bon de commande remise introuvable",
        requested_by=user,
    )


def delete_pharmacy_purchase_order(site_key: str, order_id: int, user: models.User) -> None:
    _delete_purchase_order_record(
        site_key=site_key,
        purchase_order_id=order_id,
        module_key="pharmacy_orders",
        order_table="pharmacy_purchase_orders",
        items_table="pharmacy_purchase_order_items",
        not_found_message="Bon de commande pharmacie introuvable",
        requested_by=user,
    )


def send_pharmacy_purchase_order_to_supplier(
    site_key: str,
    purchase_order_id: int,
    sent_by_user: models.User,
) -> models.PurchaseOrderSendResponse:
    ensure_database_ready()
    normalized_site_key = sites.normalize_site_key(site_key) or db.DEFAULT_SITE_KEY
    with db.get_stock_connection(normalized_site_key) as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM pharmacy_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (purchase_order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        order = _build_pharmacy_purchase_order_detail(conn, row, site_key=normalized_site_key)
        supplier_id = row["supplier_id"]
        supplier_name = row["supplier_name"]
        supplier_email = row["supplier_email"]

    try:
        supplier = get_supplier_for_order(normalized_site_key, supplier_id)
        resolved_email = require_supplier_email(supplier)
    except SupplierResolutionError as exc:
        sent_at = datetime.now(timezone.utc).isoformat()
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="pharmacy_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=None,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="error",
            message=str(exc),
        )
        raise
    to_email = resolved_email
    supplier_name = supplier.name if supplier else supplier_name
    supplier_email = supplier.email if supplier else supplier_email
    site_info = _get_site_info_for_email(normalized_site_key)
    subject, body_text, body_html = notifications.build_purchase_order_email(
        order, site_info, sent_by_user
    )
    pdf_bytes = generate_pharmacy_purchase_order_pdf(order)
    resolved = resolve_pdf_config("pharmacy_orders")
    filename = render_filename(
        resolved.config.filename.pattern,
        module_key="pharmacy_orders",
        module_title=resolved.module_label,
        context={"order_id": order.id, "ref": order.id},
    )
    reply_to = sent_by_user.email if sent_by_user.email and "@" in sent_by_user.email else None
    sent_at = datetime.now(timezone.utc).isoformat()
    try:
        message_id = email_sender.send_email(
            to_email,
            subject,
            body_text,
            body_html,
            reply_to=reply_to,
            attachments=[(filename, pdf_bytes, "application/pdf")],
            sensitive=True,
        )
        _record_purchase_order_email_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="pharmacy_orders",
            purchase_order_id=order.id,
            purchase_order_number=str(order.id),
            supplier_id=supplier_id,
            supplier_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="sent",
            message_id=message_id,
        )
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="pharmacy_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="ok",
            message=f"Email envoyé ({message_id})",
        )
    except email_sender.EmailSendError as exc:
        _record_purchase_order_email_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="pharmacy_orders",
            purchase_order_id=order.id,
            purchase_order_number=str(order.id),
            supplier_id=supplier_id,
            supplier_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="failed",
            error_message=str(exc),
        )
        _record_purchase_order_audit_log(
            created_at=sent_at,
            site_key=normalized_site_key,
            module_key="pharmacy_orders",
            action="send_to_supplier",
            purchase_order_id=order.id,
            supplier_id=supplier_id,
            supplier_name=supplier_name,
            supplier_email=supplier_email,
            recipient_email=to_email,
            user_id=sent_by_user.id,
            user_email=sent_by_user.email,
            status="error",
            message=str(exc),
        )
        raise

    return models.PurchaseOrderSendResponse(
        status="sent",
        sent_to=to_email,
        sent_at=sent_at,
        message_id=message_id,
    )


def generate_remise_purchase_order_pdf(order: models.RemisePurchaseOrderDetail) -> bytes:
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(order)
    return render_purchase_order_pdf(
        title="BON DE COMMANDE",
        purchase_order=order,
        buyer_block=buyer_block,
        supplier_block=supplier_block,
        delivery_block=delivery_block,
        include_received=False,
    )


def generate_pharmacy_purchase_order_pdf(
    order: models.PharmacyPurchaseOrderDetail,
) -> bytes:
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(order)
    return render_purchase_order_pdf(
        title="BON DE COMMANDE",
        purchase_order=order,
        buyer_block=buyer_block,
        supplier_block=supplier_block,
        delivery_block=delivery_block,
        include_received=False,
    )


def generate_vehicle_inventory_pdf(
    *,
    pointer_targets: dict[str, models.PointerTarget] | None = None,
    options: VehiclePdfOptions | None = None,
    progress_callback: Callable[[str, int | None, int | None], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> bytes:
    """Export the complete vehicle inventory as a PDF document."""

    start_time = time.perf_counter()
    if cancel_check:
        cancel_check()
    ensure_database_ready()
    if progress_callback:
        progress_callback("fetch_data", 1, 3)
    categories = list_vehicle_categories()
    items = list_vehicle_items()
    fetch_time = time.perf_counter()
    generated_at = datetime.now(timezone.utc)
    pdf_options = VehiclePdfOptions(**(options.model_dump() if options else {}))

    if pdf_options.category_ids:
        allowed_ids = set(pdf_options.category_ids)
        categories = [category for category in categories if category.id in allowed_ids]
        items = [item for item in items if item.category_id in allowed_ids]

    if cancel_check:
        cancel_check()
    if progress_callback:
        progress_callback("image_preprocessing", 2, 3)
    render_start = time.perf_counter()
    if progress_callback:
        progress_callback("build_pdf", 3, 3)
    pdf_bytes = render_vehicle_inventory_pdf(
        categories=categories,
        items=items,
        generated_at=generated_at,
        pointer_targets=pointer_targets,
        options=pdf_options,
        media_root=MEDIA_ROOT,
        cancel_check=cancel_check,
    )
    total_time = time.perf_counter()
    logger.info(
        "[vehicle_inventory_pdf] fetch_ms=%.2f render_ms=%.2f total_ms=%.2f size_bytes=%s",
        (fetch_time - start_time) * 1000,
        (total_time - render_start) * 1000,
        (total_time - start_time) * 1000,
        len(pdf_bytes),
    )
    return pdf_bytes


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
    conn: sqlite3.Connection,
    order_row: sqlite3.Row,
    *,
    site_key: str | None = None,
    suppliers_map: dict[int, models.Supplier] | None = None,
) -> models.RemisePurchaseOrderDetail:
    items_cur = conn.execute(
        """
        SELECT rpoi.id,
               rpoi.purchase_order_id,
               rpoi.remise_item_id,
               rpoi.quantity_ordered,
               rpoi.quantity_received,
               ri.name AS item_name,
               ri.sku AS sku,
               COALESCE(NULLIF(TRIM(ri.size), ''), 'Unité') AS unit
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
            sku=item_row["sku"],
            unit=item_row["unit"],
        )
        for item_row in items_cur.fetchall()
    ]
    supplier_email = None
    resolved_email = None
    supplier_has_email = False
    supplier_missing_reason = None
    supplier_missing = False
    supplier_id = order_row["supplier_id"]
    supplier = None
    if supplier_id is None:
        supplier_missing_reason = "SUPPLIER_MISSING"
    else:
        if suppliers_map is not None:
            supplier = suppliers_map.get(supplier_id)
        else:
            supplier = resolve_supplier_for_order(conn, site_key or db.get_current_site_key(), supplier_id)
        if supplier is None:
            supplier_missing = True
            supplier_missing_reason = "SUPPLIER_NOT_FOUND"
        else:
            supplier_email = supplier.email
            try:
                resolved_email = require_supplier_email(supplier)
                supplier_has_email = True
            except SupplierResolutionError as exc:
                supplier_missing_reason = exc.code
    return models.RemisePurchaseOrderDetail(
        id=order_row["id"],
        supplier_id=supplier_id,
        supplier_name=order_row["supplier_name"],
        supplier_email=supplier_email,
        supplier_email_resolved=resolved_email,
        supplier_has_email=supplier_has_email,
        supplier_missing_reason=supplier_missing_reason,
        supplier_missing=supplier_missing,
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
        supplier_ids = {row["supplier_id"] for row in rows if row["supplier_id"] is not None}
        suppliers_map: dict[int, models.Supplier] = {}
        if supplier_ids:
            placeholders = ", ".join("?" for _ in supplier_ids)
            supplier_rows = conn.execute(
                f"SELECT * FROM suppliers WHERE id IN ({placeholders})",
                tuple(supplier_ids),
            ).fetchall()
            modules_map = _load_supplier_modules(
                conn, [supplier_row["id"] for supplier_row in supplier_rows]
            )
            suppliers_map = {
                supplier_row["id"]: models.Supplier(
                    id=supplier_row["id"],
                    name=supplier_row["name"],
                    contact_name=supplier_row["contact_name"],
                    phone=supplier_row["phone"],
                    email=supplier_row["email"],
                    address=supplier_row["address"],
                    modules=modules_map.get(supplier_row["id"]) or ["suppliers"],
                )
                for supplier_row in supplier_rows
                if not _is_supplier_inactive(supplier_row)
            }
        return [
            _build_remise_purchase_order_detail(
                conn,
                row,
                site_key=db.get_current_site_key(),
                suppliers_map=suppliers_map,
            )
            for row in rows
        ]


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
        supplier_ids = [row["supplier_id"]] if row["supplier_id"] is not None else []
        suppliers_map: dict[int, models.Supplier] = {}
        if supplier_ids:
            supplier_row = conn.execute(
                "SELECT * FROM suppliers WHERE id = ?",
                (supplier_ids[0],),
            ).fetchone()
            if supplier_row is not None and not _is_supplier_inactive(supplier_row):
                modules_map = _load_supplier_modules(conn, [supplier_row["id"]])
                suppliers_map = {
                    supplier_row["id"]: models.Supplier(
                        id=supplier_row["id"],
                        name=supplier_row["name"],
                        contact_name=supplier_row["contact_name"],
                        phone=supplier_row["phone"],
                        email=supplier_row["email"],
                        address=supplier_row["address"],
                        modules=modules_map.get(supplier_row["id"]) or ["suppliers"],
                    )
                }
        return _build_remise_purchase_order_detail(
            conn,
            row,
            site_key=db.get_current_site_key(),
            suppliers_map=suppliers_map,
        )


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


def _normalize_collaborator_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def _normalize_collaborator_email(value: str | None) -> str | None:
    normalized = _normalize_collaborator_text(value)
    if not normalized:
        return None
    lowered = normalized.lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", lowered):
        raise ValueError("Adresse email invalide")
    return lowered


def _normalize_collaborator_phone(value: str | None) -> str | None:
    normalized = _normalize_collaborator_text(value)
    if not normalized:
        return None
    keep_plus = normalized.startswith("+")
    digits = re.sub(r"\D", "", normalized)
    if not digits:
        return None
    return f"+{digits}" if keep_plus else digits


def bulk_import_collaborators(
    payload: models.CollaboratorBulkImportPayload,
) -> models.CollaboratorBulkImportResult:
    ensure_database_ready()
    created = 0
    updated = 0
    skipped = 0
    errors: list[models.CollaboratorBulkImportError] = []
    seen_keys: set[str] = set()
    with db.get_stock_connection() as conn:
        try:
            conn.execute("BEGIN")
            for index, row in enumerate(payload.rows, start=1):
                full_name = _normalize_collaborator_text(row.full_name)
                department = _normalize_collaborator_text(row.department)
                phone = _normalize_collaborator_phone(row.phone)
                try:
                    email = _normalize_collaborator_email(row.email)
                except ValueError as exc:
                    errors.append(
                        models.CollaboratorBulkImportError(rowIndex=index, message=str(exc))
                    )
                    skipped += 1
                    continue
                if not full_name:
                    errors.append(
                        models.CollaboratorBulkImportError(
                            rowIndex=index,
                            message="Nom complet manquant",
                        )
                    )
                    skipped += 1
                    continue
                dedupe_key = email or f"{full_name.lower()}::{phone or ''}"
                if dedupe_key in seen_keys:
                    errors.append(
                        models.CollaboratorBulkImportError(
                            rowIndex=index,
                            message="Doublon dans le fichier",
                        )
                    )
                    skipped += 1
                    continue
                seen_keys.add(dedupe_key)
                existing_id: int | None = None
                if email:
                    existing_row = conn.execute(
                        "SELECT id FROM collaborators WHERE lower(email) = ?",
                        (email,),
                    ).fetchone()
                    if existing_row is not None:
                        existing_id = int(existing_row["id"])
                savepoint_active = False
                try:
                    conn.execute("SAVEPOINT collaborator_import")
                    savepoint_active = True
                    if existing_id is not None and payload.mode == "upsert":
                        conn.execute(
                            """
                            UPDATE collaborators
                            SET full_name = ?, department = ?, email = ?, phone = ?
                            WHERE id = ?
                            """,
                            (full_name, department, email, phone, existing_id),
                        )
                        updated += 1
                    elif existing_id is not None and payload.mode == "skip_duplicates":
                        skipped += 1
                    else:
                        conn.execute(
                            """
                            INSERT INTO collaborators (full_name, department, email, phone)
                            VALUES (?, ?, ?, ?)
                            """,
                            (full_name, department, email, phone),
                        )
                        created += 1
                    conn.execute("RELEASE SAVEPOINT collaborator_import")
                except Exception as exc:
                    if savepoint_active:
                        conn.execute("ROLLBACK TO SAVEPOINT collaborator_import")
                        conn.execute("RELEASE SAVEPOINT collaborator_import")
                    errors.append(
                        models.CollaboratorBulkImportError(
                            rowIndex=index,
                            message=f"Erreur import : {exc}",
                        )
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return models.CollaboratorBulkImportResult(
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


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
        rows = cur.fetchall()
        supplier_ids = sorted({row["supplier_id"] for row in rows if row["supplier_id"] is not None})
        suppliers_by_id: dict[int, sqlite3.Row] = {}
        if supplier_ids:
            placeholders = ", ".join("?" for _ in supplier_ids)
            supplier_rows = conn.execute(
                f"SELECT id, name, email FROM suppliers WHERE id IN ({placeholders})",
                supplier_ids,
            ).fetchall()
            suppliers_by_id = {row["id"]: row for row in supplier_rows}
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
                supplier_id=row["supplier_id"] if "supplier_id" in row.keys() else None,
                supplier_name=(
                    suppliers_by_id.get(row["supplier_id"])["name"]
                    if row["supplier_id"] is not None and row["supplier_id"] in suppliers_by_id
                    else None
                ),
                supplier_email=(
                    suppliers_by_id.get(row["supplier_id"])["email"]
                    if row["supplier_id"] is not None and row["supplier_id"] in suppliers_by_id
                    else None
                ),
                extra=_parse_extra_json(row["extra_json"] if "extra_json" in row.keys() else None),
            )
            for row in rows
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
                pharmacy_item_id=row["id"],
                name=row["name"],
                sku=row["sku"],
                category_id=None,
                quantity=row["quantity"],
                expiration_date=row["expiration_date"],
                image_url=None,
                vehicle_type="secours_a_personne",
                track_low_stock=True,
                low_stock_threshold=row["low_stock_threshold"],
            )
            for row in cur.fetchall()
        ]


def list_vehicle_pharmacy_lots(
    vehicle_type: str, vehicle_id: int | None = None
) -> list[models.PharmacyLotWithItems]:
    if vehicle_type != "secours_a_personne":
        return []
    return list_pharmacy_lots_with_items(exclude_applied_vehicle_id=vehicle_id)


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
    site_key = db.get_current_site_key()

    accessible_sources = [
        (module, table, column)
        for module, table, column in _BARCODE_MODULE_SOURCES
        if has_module_access(user, module, action="view")
    ]
    if not accessible_sources:
        return []

    existing_visual_keys = {
        asset.sku.strip().casefold()
        for asset in barcode_service.list_barcode_assets(site_key=site_key)
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


def list_barcode_catalog(
    user: models.User, module: str | None = None, q: str | None = None
) -> list[models.BarcodeCatalogEntry]:
    ensure_database_ready()

    normalized_module = (module or "all").strip().lower()
    search = (q or "").strip()

    accessible_sources = [
        source
        for source in _BARCODE_CATALOG_SOURCES
        if user.role == "admin" or has_module_access(user, source[0], action="view")
    ]
    if not accessible_sources:
        return []

    if normalized_module not in {"all", ""}:
        accessible_sources = [
            source for source in accessible_sources if source[0] == normalized_module
        ]
        if not accessible_sources:
            return []

    entries: list[models.BarcodeCatalogEntry] = []
    like = f"%{search}%"

    with db.get_stock_connection() as conn:
        for module_key, table, sku_column, name_column in accessible_sources:
            if module_key == "vehicle_inventory":
                where_clauses = [
                    f"vi.{sku_column} IS NOT NULL",
                    f"TRIM(vi.{sku_column}) <> ''",
                    "(vi.remise_item_id IS NULL OR base.id IS NOT NULL)",
                ]
                params: list[object] = []
                if search:
                    where_clauses.append(
                        f"(vi.{name_column} LIKE ? OR vi.{sku_column} LIKE ?)"
                    )
                    params.extend([like, like])
                where_clause = " AND ".join(where_clauses)
                query = f"""
                    SELECT vi.id AS item_id,
                           vi.{name_column} AS name,
                           vi.{sku_column} AS sku
                    FROM {table} AS vi
                    LEFT JOIN remise_items AS base ON base.id = vi.remise_item_id
                    WHERE {where_clause}
                    ORDER BY vi.{name_column} COLLATE NOCASE, vi.{sku_column} COLLATE NOCASE
                """
            else:
                where_clauses = [
                    f"{sku_column} IS NOT NULL",
                    f"TRIM({sku_column}) <> ''",
                ]
                params = []
                if search:
                    where_clauses.append(f"({name_column} LIKE ? OR {sku_column} LIKE ?)")
                    params.extend([like, like])
                where_clause = " AND ".join(where_clauses)
                query = f"""
                    SELECT id AS item_id,
                           {name_column} AS name,
                           {sku_column} AS sku
                    FROM {table}
                    WHERE {where_clause}
                    ORDER BY {name_column} COLLATE NOCASE, {sku_column} COLLATE NOCASE
                """

            rows = conn.execute(query, params).fetchall()
            for row in rows:
                sku_value = (row["sku"] or "").strip()
                name_value = (row["name"] or "").strip()
                if not sku_value or not name_value:
                    continue
                label = f"{name_value} ({sku_value})"
                entries.append(
                    models.BarcodeCatalogEntry(
                        sku=sku_value,
                        label=label,
                        name=name_value,
                        module=module_key,
                        item_id=row["item_id"],
                    )
                )

    return sorted(
        entries,
        key=lambda entry: (entry.name.casefold(), entry.sku.casefold(), entry.module),
    )


def _allowed_generated_barcode_sources(
    user: models.User,
) -> list[tuple[str, str, str, str]]:
    sources: list[tuple[str, str, str, str]] = []
    for module_key, table, sku_column, name_column in _BARCODE_CATALOG_SOURCES:
        if module_key == "vehicle_inventory":
            continue
        if user.role == "admin" or has_module_access(user, module_key, action="view"):
            sources.append((module_key, table, sku_column, name_column))
    return sources


def _resolve_generated_barcode_metadata(
    conn: sqlite3.Connection,
    skus: Iterable[str],
    sources: list[tuple[str, str, str, str]],
) -> dict[str, tuple[str, str]]:
    normalized_skus = {
        sku.strip().casefold(): sku.strip()
        for sku in skus
        if sku and sku.strip()
    }
    if not normalized_skus or not sources:
        return {}

    lower_skus = list(normalized_skus.keys())
    placeholders = ",".join(["?"] * len(lower_skus))
    resolved: dict[str, tuple[str, str]] = {}

    for module_key, table, sku_column, name_column in sources:
        query = f"""
            SELECT {sku_column} AS sku,
                   {name_column} AS name
            FROM {table}
            WHERE LOWER({sku_column}) IN ({placeholders})
        """
        rows = conn.execute(query, lower_skus).fetchall()
        for row in rows:
            sku_value = (row["sku"] or "").strip()
            if not sku_value:
                continue
            key = sku_value.casefold()
            if key in resolved:
                continue
            name_value = (row["name"] or "").strip()
            label = f"{name_value} ({sku_value})" if name_value else sku_value
            resolved[key] = (module_key, label)

    return resolved


def list_generated_barcodes(
    user: models.User, module: str | None = None, q: str | None = None
) -> list[models.BarcodeGeneratedEntry]:
    ensure_database_ready()

    normalized_module = (module or "").strip().lower()
    search = (q or "").strip().casefold()

    sources = _allowed_generated_barcode_sources(user)
    allowed_modules = {source[0] for source in sources}
    if not sources:
        return []

    if normalized_module and normalized_module not in {"all"}:
        if normalized_module not in allowed_modules:
            raise PermissionError("Module non autorisé")
        sources = [source for source in sources if source[0] == normalized_module]

    site_key = db.get_current_site_key()
    assets = barcode_service.list_barcode_assets(site_key=site_key)
    if not assets:
        return []

    with db.get_stock_connection() as conn:
        resolved = _resolve_generated_barcode_metadata(
            conn, (asset.sku for asset in assets), sources
        )

    entries: list[models.BarcodeGeneratedEntry] = []
    for asset in assets:
        sku_value = asset.sku.strip()
        if not sku_value:
            continue
        resolved_key = sku_value.casefold()
        meta = resolved.get(resolved_key)
        if not meta:
            continue
        module_key, label = meta
        if search:
            haystack = f"{label} {sku_value}".casefold()
            if search not in haystack:
                continue
        entries.append(
            models.BarcodeGeneratedEntry(
                sku=sku_value,
                module=module_key,
                label=label,
                created_at=asset.modified_at,
                modified_at=asset.modified_at,
                filename=asset.filename,
                asset_path=f"/barcode/assets/{asset.filename}",
            )
        )

    return entries


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

    site_key = db.get_current_site_key()
    assets = barcode_service.list_barcode_assets(site_key=site_key)
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
            supplier_id=row["supplier_id"] if "supplier_id" in row.keys() else None,
            extra=_parse_extra_json(row["extra_json"] if "extra_json" in row.keys() else None),
        )


def create_pharmacy_item(payload: models.PharmacyItemCreate) -> models.PharmacyItem:
    ensure_database_ready()
    expiration_date = (
        payload.expiration_date.isoformat() if payload.expiration_date is not None else None
    )
    extra = validate_and_merge_extra("pharmacy_items", None, payload.extra)
    with db.get_stock_connection() as conn:
        barcode = _normalize_barcode(payload.barcode)
        supplier_id = payload.supplier_id
        if supplier_id is not None:
            _require_supplier_for_module(conn, supplier_id, module_key="pharmacy")
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
                    category_id,
                    supplier_id,
                    extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    supplier_id,
                    _dump_extra_json(extra),
                ),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Ce code-barres est déjà utilisé") from exc
        _persist_after_commit(conn, "pharmacy")
        return get_pharmacy_item(cur.lastrowid)


def update_pharmacy_item(item_id: int, payload: models.PharmacyItemUpdate) -> models.PharmacyItem:
    ensure_database_ready()
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    extra_payload = fields.pop("extra", None)
    if "barcode" in fields:
        fields["barcode"] = _normalize_barcode(fields["barcode"])
    if "expiration_date" in fields and fields["expiration_date"] is not None:
        fields["expiration_date"] = fields["expiration_date"].isoformat()
    if extra_payload is not None:
        with db.get_stock_connection() as conn:
            row = conn.execute(
                "SELECT extra_json FROM pharmacy_items WHERE id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Produit pharmaceutique introuvable")
        merged_extra = validate_and_merge_extra("pharmacy_items", row["extra_json"], extra_payload)
        fields["extra_json"] = _dump_extra_json(merged_extra)
    if "supplier_id" in fields and fields["supplier_id"] is not None:
        with db.get_stock_connection() as conn:
            _require_supplier_for_module(conn, int(fields["supplier_id"]), module_key="pharmacy")
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
    conn: sqlite3.Connection,
    order_row: sqlite3.Row,
    *,
    site_key: str | None = None,
) -> models.PharmacyPurchaseOrderDetail:
    items_cur = conn.execute(
        """
        SELECT poi.id,
               poi.purchase_order_id,
               poi.pharmacy_item_id,
               poi.quantity_ordered,
               poi.quantity_received,
               pi.name AS pharmacy_item_name,
               NULLIF(TRIM(pi.barcode), '') AS sku,
               COALESCE(NULLIF(TRIM(pi.packaging), ''), 'Unité') AS unit
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
            sku=item_row["sku"],
            unit=item_row["unit"],
        )
        for item_row in items_cur.fetchall()
    ]
    resolved_email = None
    supplier_has_email = False
    supplier_missing_reason = None
    supplier_id = order_row["supplier_id"]
    supplier = resolve_supplier_for_order(conn, site_key or db.get_current_site_key(), supplier_id)
    if supplier_id is None:
        supplier_missing_reason = "SUPPLIER_MISSING"
    elif supplier is None:
        supplier_missing_reason = "SUPPLIER_NOT_FOUND"
    else:
        try:
            resolved_email = require_supplier_email(supplier)
            supplier_has_email = True
        except SupplierResolutionError as exc:
            supplier_missing_reason = exc.code
    return models.PharmacyPurchaseOrderDetail(
        id=order_row["id"],
        supplier_id=supplier_id,
        supplier_name=order_row["supplier_name"],
        supplier_email=supplier.email if supplier else None,
        supplier_email_resolved=resolved_email,
        supplier_has_email=supplier_has_email,
        supplier_missing_reason=supplier_missing_reason,
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
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM pharmacy_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            ORDER BY po.created_at DESC, po.id DESC
            """
        )
        rows = cur.fetchall()
        return [
            _build_pharmacy_purchase_order_detail(conn, row, site_key=db.get_current_site_key())
            for row in rows
        ]


def get_pharmacy_purchase_order(order_id: int) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM pharmacy_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            WHERE po.id = ?
            """,
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        return _build_pharmacy_purchase_order_detail(conn, row, site_key=db.get_current_site_key())


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
                INSERT INTO pharmacy_purchase_orders (supplier_id, status, note, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
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
