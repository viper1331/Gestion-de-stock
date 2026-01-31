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
import unicodedata
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, replace
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
from backend.services import email_sender, notifications, system_settings
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
_MESSAGE_CONTENT_MAX_LENGTH = 2000
_MESSAGE_IDEMPOTENCY_MAX_LENGTH = 128
_PASSWORD_RESET_RATE_LIMIT_COUNT = 5
_PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS = 3600
_PASSWORD_RESET_MIN_LENGTH = 10

_MENU_ORDER_MAX_ITEMS = 200
_MENU_ORDER_MAX_ID_LENGTH = 100
_TABLE_PREFS_VERSION = 1
_TABLE_PREFS_MAX_BYTES = 50_000

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

@dataclass(frozen=True)
class _ModuleDefinitionMeta:
    key: str
    label: str
    category: str
    is_admin_only: bool
    sort_order: int


_AVAILABLE_MODULE_DEFINITIONS: tuple[_ModuleDefinitionMeta, ...] = (
    _ModuleDefinitionMeta(
        key="barcode",
        label="Codes-barres",
        category="Outils",
        is_admin_only=False,
        sort_order=10,
    ),
    _ModuleDefinitionMeta(
        key="clothing",
        label="Inventaire habillement",
        category="Habillement",
        is_admin_only=False,
        sort_order=20,
    ),
    _ModuleDefinitionMeta(
        key="suppliers",
        label="Fournisseurs",
        category="Habillement",
        is_admin_only=False,
        sort_order=30,
    ),
    _ModuleDefinitionMeta(
        key="purchase_suggestions",
        label="Suggestions de commandes",
        category="Habillement",
        is_admin_only=False,
        sort_order=40,
    ),
    _ModuleDefinitionMeta(
        key="purchase_orders",
        label="Bons de commande",
        category="Habillement",
        is_admin_only=False,
        sort_order=50,
    ),
    _ModuleDefinitionMeta(
        key="collaborators",
        label="Collaborateurs",
        category="Habillement",
        is_admin_only=False,
        sort_order=60,
    ),
    _ModuleDefinitionMeta(
        key="dotations",
        label="Dotations",
        category="Habillement",
        is_admin_only=False,
        sort_order=70,
    ),
    _ModuleDefinitionMeta(
        key="reports",
        label="Rapports",
        category="Habillement",
        is_admin_only=False,
        sort_order=80,
    ),
    _ModuleDefinitionMeta(
        key="vehicle_inventory",
        label="Inventaire véhicules",
        category="Inventaires spécialisés",
        is_admin_only=False,
        sort_order=90,
    ),
    _ModuleDefinitionMeta(
        key="vehicle_qr",
        label="QR codes véhicules",
        category="Inventaires spécialisés",
        is_admin_only=False,
        sort_order=100,
    ),
    _ModuleDefinitionMeta(
        key="inventory_remise",
        label="Inventaire remises",
        category="Inventaires spécialisés",
        is_admin_only=False,
        sort_order=110,
    ),
    _ModuleDefinitionMeta(
        key="pharmacy",
        label="Pharmacie",
        category="Pharmacie",
        is_admin_only=False,
        sort_order=120,
    ),
    _ModuleDefinitionMeta(
        key="pharmacy_links",
        label="Liens Pharmacie",
        category="Pharmacie",
        is_admin_only=False,
        sort_order=130,
    ),
    _ModuleDefinitionMeta(
        key="messages",
        label="Messagerie",
        category="Communication",
        is_admin_only=False,
        sort_order=140,
    ),
    _ModuleDefinitionMeta(
        key="link_categories",
        label="Configuration liens",
        category="Administration",
        is_admin_only=True,
        sort_order=200,
    ),
    _ModuleDefinitionMeta(
        key="settings",
        label="Paramètres",
        category="Administration",
        is_admin_only=True,
        sort_order=210,
    ),
    _ModuleDefinitionMeta(
        key="advanced_settings",
        label="Paramètres avancés",
        category="Administration",
        is_admin_only=True,
        sort_order=220,
    ),
    _ModuleDefinitionMeta(
        key="pdf_config",
        label="Configuration PDF",
        category="Administration",
        is_admin_only=True,
        sort_order=230,
    ),
    _ModuleDefinitionMeta(
        key="users",
        label="Utilisateurs",
        category="Administration",
        is_admin_only=True,
        sort_order=240,
    ),
    _ModuleDefinitionMeta(
        key="permissions_admin",
        label="Permissions",
        category="Administration",
        is_admin_only=True,
        sort_order=250,
    ),
    _ModuleDefinitionMeta(
        key="updates",
        label="Mises à jour",
        category="Administration",
        is_admin_only=True,
        sort_order=260,
    ),
    _ModuleDefinitionMeta(
        key="system_config",
        label="Configuration système",
        category="Administration",
        is_admin_only=True,
        sort_order=270,
    ),
)
_AVAILABLE_MODULE_INDEX: dict[str, _ModuleDefinitionMeta] = {
    entry.key: entry for entry in _AVAILABLE_MODULE_DEFINITIONS
}
_AVAILABLE_MODULE_KEYS: set[str] = {
    entry.key for entry in _AVAILABLE_MODULE_DEFINITIONS if not entry.is_admin_only
}

_MODULE_KEY_ALIASES: dict[str, str] = {
    "vehicle_qrcodes": "vehicle_qr",
    "item_links": "pharmacy_links",
}
_MODULE_CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "vehicle_qr": ("vehicle_qrcodes",),
    "pharmacy_links": ("item_links",),
}

_MODULE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "suppliers": ("clothing",),
    "collaborators": ("clothing",),
    "dotations": ("clothing",),
    "vehicle_qr": ("vehicle_inventory",),
    "pharmacy_links": ("pharmacy",),
}

_PURCHASE_SUGGESTION_MODULES: tuple[str, ...] = (
    "clothing",
    "pharmacy",
    "inventory_remise",
)


def normalize_module_key(module: str) -> str:
    normalized = (module or "").strip().lower()
    return _MODULE_KEY_ALIASES.get(normalized, normalized)


def _module_lookup_keys(module: str) -> list[str]:
    canonical = normalize_module_key(module)
    aliases = _MODULE_CANONICAL_ALIASES.get(canonical, ())
    return [canonical, *aliases]


def _is_admin_only_module(module: str) -> bool:
    canonical = normalize_module_key(module)
    entry = _AVAILABLE_MODULE_INDEX.get(canonical)
    return bool(entry and entry.is_admin_only)


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
        ),
        auto_purchase_orders=True,
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


def _assert_purchase_order_archivable(status: str) -> None:
    if status != "RECEIVED":
        raise ValueError("Seuls les bons de commande reçus peuvent être archivés")


def _are_purchase_order_lines_received(order: models.PurchaseOrderDetail) -> bool:
    if not order.items:
        return False
    return all(
        item.quantity_received >= item.quantity_ordered for item in order.items
    )


def _has_latest_nonconforming_receipt(order: models.PurchaseOrderDetail) -> bool:
    latest_by_line: dict[int, models.PurchaseOrderReceipt] = {}
    for receipt in order.receipts:
        existing = latest_by_line.get(receipt.purchase_order_line_id)
        if existing is None:
            latest_by_line[receipt.purchase_order_line_id] = receipt
            continue
        existing_time = _coerce_datetime(existing.created_at)
        receipt_time = _coerce_datetime(receipt.created_at)
        if receipt_time > existing_time or (
            receipt_time == existing_time and receipt.id > existing.id
        ):
            latest_by_line[receipt.purchase_order_line_id] = receipt
    return any(
        receipt.conformity_status == "non_conforme"
        for receipt in latest_by_line.values()
    )


def _resolve_latest_supplier_returns(
    supplier_returns: Iterable[models.ClothingSupplierReturn],
) -> tuple[dict[int, models.ClothingSupplierReturn], list[models.ClothingSupplierReturn]]:
    latest_by_line: dict[int, models.ClothingSupplierReturn] = {}
    unlinked: list[models.ClothingSupplierReturn] = []
    for supplier_return in supplier_returns:
        line_id = supplier_return.purchase_order_line_id
        if line_id is None:
            unlinked.append(supplier_return)
            continue
        existing = latest_by_line.get(line_id)
        if existing is None:
            latest_by_line[line_id] = supplier_return
            continue
        existing_time = _coerce_datetime(existing.created_at)
        return_time = _coerce_datetime(supplier_return.created_at)
        if return_time > existing_time or (
            return_time == existing_time and supplier_return.id > existing.id
        ):
            latest_by_line[line_id] = supplier_return
    return latest_by_line, unlinked


def _map_supplier_return_status(status: str) -> str:
    if status == "prepared":
        return "to_prepare"
    if status in {"shipped", "supplier_received"}:
        return status
    return "none"


def _has_blocking_supplier_return(order: models.PurchaseOrderDetail) -> bool:
    blocking_statuses = {"to_prepare", "shipped"}
    latest_by_line, unlinked_returns = _resolve_latest_supplier_returns(order.supplier_returns)
    if any(
        supplier_return.status in {"prepared", "shipped"}
        for supplier_return in latest_by_line.values()
    ):
        return True
    if any(
        supplier_return.status in {"prepared", "shipped"} for supplier_return in unlinked_returns
    ):
        return True
    for item in order.items:
        if item.id in latest_by_line:
            continue
        if (item.return_status or "none") in blocking_statuses:
            return True
    return False


def _assert_purchase_order_archivable_detail(
    order: models.PurchaseOrderDetail,
) -> None:
    if order.status != "RECEIVED" and not _are_purchase_order_lines_received(order):
        raise ValueError("Seuls les bons de commande reçus peuvent être archivés")
    pending_assignments = [
        assignment
        for assignment in order.pending_assignments
        if assignment.status == "pending"
    ]
    if pending_assignments:
        raise ValueError("Des attributions sont encore en attente de validation")
    if _has_blocking_supplier_return(order):
        raise ValueError("Un retour fournisseur est encore en cours")
    has_nonconformity_history = any(
        receipt.conformity_status == "non_conforme" for receipt in order.receipts
    ) or bool(order.nonconformities)
    if has_nonconformity_history:
        if order.replacement_flow_status != "closed":
            raise ValueError("La demande de remplacement doit être clôturée avant archivage")
        if not order.replacement_assignment_completed:
            raise ValueError("L'attribution doit être validée avant archivage")
        if _has_latest_nonconforming_receipt(order):
            raise ValueError("La réception conforme finale est attendue avant archivage")


def _get_purchase_suggestions_safety_buffer() -> int:
    config = system_config.get_config()
    raw = config.extra.get("purchase_suggestions_safety_buffer", 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _get_purchase_suggestions_expiry_soon_days() -> int:
    settings = system_settings.get_purchase_suggestion_settings()
    return max(0, settings.expiry_soon_days)


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


_SUGGESTION_REASON_ORDER = ("LOW_STOCK", "EXPIRY_SOON")


def _normalize_reason_codes(codes: Iterable[str]) -> list[str]:
    normalized = {code for code in codes if code}
    return [code for code in _SUGGESTION_REASON_ORDER if code in normalized]


def _build_reason_label(reason_codes: Iterable[str], expiry_days_left: int | None) -> str | None:
    parts: list[str] = []
    reason_set = set(reason_codes)
    if "LOW_STOCK" in reason_set:
        parts.append("Stock sous seuil")
    if "EXPIRY_SOON" in reason_set:
        suffix = f" (J-{expiry_days_left})" if expiry_days_left is not None else ""
        parts.append(f"Péremption proche{suffix}")
    return " + ".join(parts) if parts else None


def _suggested_qty_for_expiry(
    quantity: int,
    threshold: int,
    reorder_qty: int | None,
    safety_buffer: int,
) -> int:
    if reorder_qty is not None or threshold > 0:
        return _calculate_suggested_qty(quantity, threshold, reorder_qty, safety_buffer)
    return 1


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
    reason_codes: Iterable[str],
    expiry_date: date | None = None,
    expiry_days_left: int | None = None,
    reason_label: str | None = None,
    suggested_qty_override: int | None = None,
) -> dict[str, Any]:
    qty_suggested = suggested_qty_override
    if qty_suggested is None:
        qty_suggested = _calculate_suggested_qty(quantity, threshold, reorder_qty, safety_buffer)
    normalized_reason_codes = _normalize_reason_codes(reason_codes)
    reason_label = reason_label or _build_reason_label(normalized_reason_codes, expiry_days_left)
    expiry_date_value = expiry_date.isoformat() if expiry_date else None
    return {
        "item_id": item_id,
        "sku": sku,
        "label": label,
        "qty_suggested": qty_suggested,
        "qty_final": qty_suggested,
        "unit": unit,
        "reason": reason_label,
        "reason_codes": normalized_reason_codes,
        "expiry_date": expiry_date_value,
        "expiry_days_left": expiry_days_left,
        "reason_label": reason_label,
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


def _resolve_pharmacy_supplier_id(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    extra: dict[str, Any],
) -> int | None:
    supplier_id = _row_get(row, "supplier_id")
    if supplier_id is None:
        supplier_id = extra.get("supplier_id") if isinstance(extra.get("supplier_id"), int) else None
    if supplier_id is None:
        supplier_id = _resolve_supplier_id_from_name(
            conn,
            extra.get("supplier_name") or extra.get("supplier") or extra.get("fournisseur"),
        )
    return supplier_id


def _row_has(row: sqlite3.Row, key: str) -> bool:
    return hasattr(row, "keys") and key in row.keys()


def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    return row[key] if _row_has(row, key) else default


def _resolve_remise_supplier_id(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    extra: dict[str, Any],
) -> int | None:
    supplier_id = _row_get(row, "supplier_id")
    if supplier_id is None:
        supplier_id = _resolve_supplier_id_from_name(
            conn,
            extra.get("supplier_name") or extra.get("supplier") or extra.get("fournisseur"),
        )
    return supplier_id


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
    expiry_soon_days: int,
) -> list[dict[str, Any]]:
    candidates_by_item: dict[int, dict[str, Any]] = {}

    if module_key == "clothing":
        supplier_column = (
            "supplier_id" if _table_has_column(conn, "items", "supplier_id") else "NULL AS supplier_id"
        )
        rows = conn.execute(
            """
            SELECT id, name, sku, size, quantity, low_stock_threshold, {supplier_column}, track_low_stock
            FROM items
            WHERE quantity < low_stock_threshold AND low_stock_threshold > 0
            """.format(
                supplier_column=supplier_column
            )
        ).fetchall()
        for row in rows:
            if "track_low_stock" in row.keys() and not bool(row["track_low_stock"]):
                continue
            candidates_by_item[row["id"]] = _build_purchase_suggestion_line(
                item_id=row["id"],
                sku=row["sku"],
                label=row["name"],
                quantity=row["quantity"],
                threshold=row["low_stock_threshold"],
                unit=row["size"],
                supplier_id=row["supplier_id"],
                reorder_qty=None,
                safety_buffer=safety_buffer,
                reason_codes=["LOW_STOCK"],
            )
        return list(candidates_by_item.values())

    if module_key == "pharmacy":
        supplier_column = (
            "supplier_id"
            if _table_has_column(conn, "pharmacy_items", "supplier_id")
            else "NULL AS supplier_id"
        )
        low_stock_rows = conn.execute(
            """
            SELECT id,
                   name,
                   barcode,
                   packaging,
                   dosage,
                   quantity,
                   low_stock_threshold,
                   {supplier_column},
                   extra_json
            FROM pharmacy_items
            WHERE quantity < low_stock_threshold AND low_stock_threshold > 0
            """.format(
                supplier_column=supplier_column
            )
        ).fetchall()
        for row in low_stock_rows:
            extra = _parse_extra_json(row["extra_json"])
            supplier_id = _resolve_pharmacy_supplier_id(conn, row, extra)
            candidates_by_item[row["id"]] = _build_purchase_suggestion_line(
                item_id=row["id"],
                sku=row["barcode"] or str(row["id"]),
                label=row["name"],
                quantity=row["quantity"],
                threshold=row["low_stock_threshold"],
                unit=row["packaging"] or row["dosage"],
                supplier_id=supplier_id,
                reorder_qty=_extract_reorder_qty(extra),
                safety_buffer=safety_buffer,
                reason_codes=["LOW_STOCK"],
            )
        if _table_has_column(conn, "pharmacy_items", "expiration_date") and expiry_soon_days >= 0:
            expiry_rows = conn.execute(
                """
                SELECT id,
                       name,
                       barcode,
                       packaging,
                       dosage,
                       quantity,
                       low_stock_threshold,
                       expiration_date,
                       {supplier_column},
                       extra_json
                FROM pharmacy_items
                WHERE expiration_date IS NOT NULL
                """.format(
                    supplier_column=supplier_column
                )
            ).fetchall()
            today = date.today()
            for row in expiry_rows:
                expiry_date = _parse_date(row["expiration_date"])
                if expiry_date is None:
                    continue
                days_left = (expiry_date - today).days
                if days_left < 0 or days_left > expiry_soon_days:
                    continue
                extra = _parse_extra_json(row["extra_json"])
                supplier_id = _resolve_pharmacy_supplier_id(conn, row, extra)
                existing = candidates_by_item.get(row["id"])
                if existing:
                    existing["reason_codes"] = _normalize_reason_codes(
                        [*existing.get("reason_codes", []), "EXPIRY_SOON"]
                    )
                    existing["expiry_date"] = expiry_date.isoformat()
                    existing["expiry_days_left"] = days_left
                    existing["reason_label"] = _build_reason_label(
                        existing["reason_codes"], days_left
                    )
                    existing["reason"] = existing["reason_label"]
                    continue
                suggested_qty = _suggested_qty_for_expiry(
                    row["quantity"],
                    row["low_stock_threshold"],
                    _extract_reorder_qty(extra),
                    safety_buffer,
                )
                candidates_by_item[row["id"]] = _build_purchase_suggestion_line(
                    item_id=row["id"],
                    sku=row["barcode"] or str(row["id"]),
                    label=row["name"],
                    quantity=row["quantity"],
                    threshold=row["low_stock_threshold"],
                    unit=row["packaging"] or row["dosage"],
                    supplier_id=supplier_id,
                    reorder_qty=_extract_reorder_qty(extra),
                    safety_buffer=safety_buffer,
                    reason_codes=["EXPIRY_SOON"],
                    expiry_date=expiry_date,
                    expiry_days_left=days_left,
                    suggested_qty_override=suggested_qty,
                )
        return list(candidates_by_item.values())

    if module_key == "inventory_remise":
        supplier_column = (
            "supplier_id"
            if _table_has_column(conn, "remise_items", "supplier_id")
            else "NULL AS supplier_id"
        )
        low_stock_rows = conn.execute(
            """
            SELECT id, name, sku, size, quantity, low_stock_threshold, {supplier_column}, track_low_stock, extra_json
            FROM remise_items
            WHERE quantity < low_stock_threshold AND low_stock_threshold > 0
            """.format(
                supplier_column=supplier_column
            )
        ).fetchall()
        for row in low_stock_rows:
            if "track_low_stock" in row.keys() and not bool(row["track_low_stock"]):
                continue
            extra = _parse_extra_json(row["extra_json"])
            supplier_id = _resolve_remise_supplier_id(conn, row, extra)
            candidates_by_item[row["id"]] = _build_purchase_suggestion_line(
                item_id=row["id"],
                sku=row["sku"],
                label=row["name"],
                quantity=row["quantity"],
                threshold=row["low_stock_threshold"],
                unit=row["size"],
                supplier_id=supplier_id,
                reorder_qty=_extract_reorder_qty(extra),
                safety_buffer=safety_buffer,
                reason_codes=["LOW_STOCK"],
            )
        if _table_has_column(conn, "remise_items", "expiration_date") and expiry_soon_days >= 0:
            expiry_rows = conn.execute(
                """
                SELECT id,
                       name,
                       sku,
                       size,
                       quantity,
                       low_stock_threshold,
                       {supplier_column},
                       track_low_stock,
                       extra_json,
                       expiration_date
                FROM remise_items
                WHERE expiration_date IS NOT NULL
                """.format(
                    supplier_column=supplier_column
                )
            ).fetchall()
            today = date.today()
            for row in expiry_rows:
                expiry_date = _parse_date(row["expiration_date"])
                if expiry_date is None:
                    continue
                days_left = (expiry_date - today).days
                if days_left < 0 or days_left > expiry_soon_days:
                    continue
                extra = _parse_extra_json(row["extra_json"])
                supplier_id = _resolve_remise_supplier_id(conn, row, extra)
                existing = candidates_by_item.get(row["id"])
                if existing:
                    existing["reason_codes"] = _normalize_reason_codes(
                        [*existing.get("reason_codes", []), "EXPIRY_SOON"]
                    )
                    existing["expiry_date"] = expiry_date.isoformat()
                    existing["expiry_days_left"] = days_left
                    existing["reason_label"] = _build_reason_label(
                        existing["reason_codes"], days_left
                    )
                    existing["reason"] = existing["reason_label"]
                    continue
                suggested_qty = _suggested_qty_for_expiry(
                    row["quantity"],
                    row["low_stock_threshold"],
                    _extract_reorder_qty(extra),
                    safety_buffer,
                )
                candidates_by_item[row["id"]] = _build_purchase_suggestion_line(
                    item_id=row["id"],
                    sku=row["sku"],
                    label=row["name"],
                    quantity=row["quantity"],
                    threshold=row["low_stock_threshold"],
                    unit=row["size"],
                    supplier_id=supplier_id,
                    reorder_qty=_extract_reorder_qty(extra),
                    safety_buffer=safety_buffer,
                    reason_codes=["EXPIRY_SOON"],
                    expiry_date=expiry_date,
                    expiry_days_left=days_left,
                    suggested_qty_override=suggested_qty,
                )
        return list(candidates_by_item.values())

    raise ValueError(f"Module de suggestion inconnu: {module_key}")


def get_reorder_candidates(site_key: str, module_key: str) -> list[dict[str, Any]]:
    ensure_database_ready()
    if module_key not in _PURCHASE_SUGGESTION_MODULES:
        raise ValueError(f"Module de suggestion inconnu: {module_key}")
    safety_buffer = _get_purchase_suggestions_safety_buffer()
    expiry_soon_days = _get_purchase_suggestions_expiry_soon_days()
    with _get_site_stock_conn(site_key) as conn:
        return _get_reorder_candidates(conn, module_key, safety_buffer, expiry_soon_days)


def _get_purchase_suggestion_lines(
    conn: sqlite3.Connection, suggestion_ids: list[int]
) -> dict[int, list[models.PurchaseSuggestionLine]]:
    if not suggestion_ids:
        return {}
    placeholders = ", ".join("?" for _ in suggestion_ids)
    rows = conn.execute(
        f"""
        SELECT psl.*, ps.module_key
        FROM purchase_suggestion_lines AS psl
        JOIN purchase_suggestions AS ps ON ps.id = psl.suggestion_id
        WHERE psl.suggestion_id IN ({placeholders})
        ORDER BY psl.id
        """,
        suggestion_ids,
    ).fetchall()
    item_ids_by_module: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        item_ids_by_module[row["module_key"]].add(row["item_id"])
    items_by_module: dict[str, dict[int, sqlite3.Row]] = {}
    module_tables = {
        "clothing": "items",
        "pharmacy": "pharmacy_items",
        "inventory_remise": "remise_items",
    }
    for module_key, item_ids in item_ids_by_module.items():
        if not item_ids:
            continue
        table = module_tables.get(module_key)
        if not table:
            continue
        item_placeholders = ", ".join("?" for _ in item_ids)
        item_rows = conn.execute(
            f"SELECT * FROM {table} WHERE id IN ({item_placeholders})",
            list(item_ids),
        ).fetchall()
        items_by_module[module_key] = {item_row["id"]: item_row for item_row in item_rows}
    custom_fields_by_scope: dict[str, list[models.CustomFieldDefinition]] = {}
    if "clothing" in item_ids_by_module:
        custom_fields_by_scope["items"] = _load_custom_field_definitions(
            conn, "items", active_only=True
        )
    if "inventory_remise" in item_ids_by_module:
        custom_fields_by_scope["remise_items"] = _load_custom_field_definitions(
            conn, "remise_items", active_only=True
        )
    lines: dict[int, list[models.PurchaseSuggestionLine]] = defaultdict(list)
    for row in rows:
        module_key = row["module_key"]
        item_row = items_by_module.get(module_key, {}).get(row["item_id"])
        reason_codes: list[str] = []
        raw_reason_codes = row["reason_codes"] if "reason_codes" in row.keys() else None
        if raw_reason_codes:
            try:
                parsed = json.loads(raw_reason_codes)
                if isinstance(parsed, list):
                    reason_codes = [str(code) for code in parsed if code]
            except json.JSONDecodeError:
                reason_codes = []
        reason_label = row["reason_label"] if "reason_label" in row.keys() else None
        if not reason_label:
            reason_label = row["reason"]
        if not reason_codes and reason_label:
            if "Péremption" in reason_label:
                reason_codes.append("EXPIRY_SOON")
            if "Stock" in reason_label:
                reason_codes.append("LOW_STOCK")
        reason_codes = _normalize_reason_codes(reason_codes)
        line = models.PurchaseSuggestionLine(
            id=row["id"],
            suggestion_id=row["suggestion_id"],
            item_id=row["item_id"],
            sku=_row_get(row, "sku"),
            label=row["label"],
            variant_label=_resolve_variant_label(
                module_key, item_row, custom_fields_by_scope=custom_fields_by_scope
            ),
            qty_suggested=row["qty_suggested"],
            qty_final=row["qty_final"],
            unit=_row_get(row, "unit"),
            reason=row["reason"],
            reason_codes=reason_codes,
            expiry_date=row["expiry_date"] if "expiry_date" in row.keys() else None,
            expiry_days_left=row["expiry_days_left"] if "expiry_days_left" in row.keys() else None,
            reason_label=reason_label,
            stock_current=row["stock_current"],
            threshold=row["threshold"],
        )
        lines[line.suggestion_id].append(line)
    for suggestion_id, suggestion_lines in lines.items():
        suggestion_lines.sort(
            key=lambda line: (
                line.expiry_days_left
                if line.expiry_days_left is not None
                else 999999,
                0 if "LOW_STOCK" in line.reason_codes else 1,
                (line.label or "").lower(),
            )
        )
    return lines


def _normalize_variant_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _append_note(existing: str | None, note: str) -> str:
    if existing and existing.strip():
        return f"{existing.strip()} | {note}"
    return note


def _truncate_note(note: str, max_length: int = 256) -> str:
    if len(note) <= max_length:
        return note
    return f"{note[: max_length - 1].rstrip()}…"


def _extract_variant_from_row(row: sqlite3.Row | None, fields: Iterable[str]) -> str | None:
    if row is None:
        return None
    for field in fields:
        if field in row.keys():
            value = _normalize_variant_value(row[field])
            if value:
                return value
    return None


def _extract_variant_from_custom_fields(
    extra: dict[str, Any],
    definitions: Iterable[models.CustomFieldDefinition],
) -> str | None:
    if not extra:
        return None
    target_labels = {"taille", "size", "variant", "variante"}
    for key, value in extra.items():
        if str(key).strip().lower() in target_labels:
            variant_value = _normalize_variant_value(value)
            if variant_value:
                return variant_value
    for definition in definitions:
        label_key = definition.label.strip().lower()
        key_key = definition.key.strip().lower()
        if label_key in target_labels or key_key in target_labels:
            variant_value = _normalize_variant_value(extra.get(definition.key))
            if variant_value:
                return variant_value
    return None


def _resolve_variant_label(
    module_key: str,
    item_row: sqlite3.Row | None,
    *,
    custom_fields_by_scope: dict[str, list[models.CustomFieldDefinition]],
) -> str | None:
    if item_row is None:
        return None
    if module_key == "pharmacy":
        dosage = _normalize_variant_value(item_row["dosage"]) if "dosage" in item_row.keys() else None
        packaging = (
            _normalize_variant_value(item_row["packaging"])
            if "packaging" in item_row.keys()
            else None
        )
        parts = [part for part in [dosage, packaging] if part]
        return " • ".join(parts) if parts else None
    direct_fields = ["size", "taille", "variant", "variante"]
    direct_value = _extract_variant_from_row(item_row, direct_fields)
    if direct_value:
        return direct_value
    extra = {}
    if "extra_json" in item_row.keys():
        extra = _parse_extra_json(item_row["extra_json"])
    scope = "remise_items" if module_key == "inventory_remise" else "items"
    definitions = custom_fields_by_scope.get(scope, [])
    return _extract_variant_from_custom_fields(extra, definitions)


def _is_supplier_inactive(row: sqlite3.Row) -> bool:
    if _row_has(row, "is_active") and not row["is_active"]:
        return True
    if _row_has(row, "is_deleted") and row["is_deleted"]:
        return True
    if _row_has(row, "deleted_at") and row["deleted_at"]:
        return True
    return False


def _resolve_suggestion_supplier_payload(
    row: sqlite3.Row | None,
) -> tuple[str | None, str | None, str]:
    if row is None:
        return None, None, "missing"
    display = _row_get(row, "name")
    if _is_supplier_inactive(row):
        return display, None, "inactive"
    email = str(_row_get(row, "email") or "").strip()
    if not email:
        return display, None, "no_email"
    normalized_email = _normalize_email(email)
    if len(normalized_email) < 5 or "@" not in normalized_email:
        return display, None, "no_email"
    return display, _row_get(row, "email"), "ok"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    columns = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    return column_name in columns


@dataclass(frozen=True)
class _ReportModuleConfig:
    module_key: str
    inventory_module: str | None
    items_table: str | None
    movements_table: str | None
    movement_item_column: str | None
    orders_table: str | None


_REPORT_MODULES: dict[str, _ReportModuleConfig] = {
    "clothing": _ReportModuleConfig(
        module_key="clothing",
        inventory_module="default",
        items_table="items",
        movements_table="movements",
        movement_item_column="item_id",
        orders_table="purchase_orders",
    ),
    "pharmacy": _ReportModuleConfig(
        module_key="pharmacy",
        inventory_module="pharmacy",
        items_table="pharmacy_items",
        movements_table="pharmacy_movements",
        movement_item_column="pharmacy_item_id",
        orders_table="pharmacy_purchase_orders",
    ),
    "inventory_remise": _ReportModuleConfig(
        module_key="inventory_remise",
        inventory_module="inventory_remise",
        items_table="remise_items",
        movements_table="remise_movements",
        movement_item_column="item_id",
        orders_table="remise_purchase_orders",
    ),
    "vehicle_inventory": _ReportModuleConfig(
        module_key="vehicle_inventory",
        inventory_module="vehicle_inventory",
        items_table="vehicle_items",
        movements_table="vehicle_movements",
        movement_item_column="item_id",
        orders_table=None,
    ),
}

_REPORT_ORDER_DEPENDENCIES: dict[str, list[str]] = {
    "purchase_orders": [
        "purchase_order_items",
        "purchase_order_receipts",
        "purchase_order_nonconformities",
        "pending_clothing_assignments",
    ],
    "pharmacy_purchase_orders": ["pharmacy_purchase_order_items"],
    "remise_purchase_orders": ["remise_purchase_order_items"],
}


def _resolve_report_module(module: str) -> _ReportModuleConfig | None:
    normalized = (module or "").strip().lower()
    return _REPORT_MODULES.get(normalized)


def get_inventory_stats(module_key: str) -> models.InventoryStats:
    ensure_database_ready()
    resolved = _resolve_report_module(module_key)
    if not resolved or not resolved.items_table:
        raise ValueError("Module introuvable")
    with db.get_stock_connection() as conn:
        if resolved.inventory_module == "inventory_remise":
            _ensure_remise_item_columns(conn)
        if not _table_exists(conn, resolved.items_table):
            return models.InventoryStats(
                references=0,
                total_stock=0,
                low_stock=0,
                purchase_orders_open=0,
                stockouts=0,
            )
        item_columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({resolved.items_table})").fetchall()
        }
        references = int(
            conn.execute(
                f"SELECT COUNT(1) AS count FROM {resolved.items_table}"
            ).fetchone()["count"]
            or 0
        )
        total_stock = int(
            conn.execute(
                f"SELECT SUM(quantity) AS total FROM {resolved.items_table}"
            ).fetchone()["total"]
            or 0
        )
        stockouts_where = ["quantity = 0"]
        if "track_low_stock" in item_columns:
            stockouts_where.append("track_low_stock = 1")
        stockouts = int(
            conn.execute(
                f"""
                SELECT COUNT(1) AS count
                FROM {resolved.items_table}
                WHERE {" AND ".join(stockouts_where)}
                """
            ).fetchone()["count"]
            or 0
        )
        low_stock = 0
        if "low_stock_threshold" in item_columns:
            low_stock_where = ["low_stock_threshold > 0", "quantity <= low_stock_threshold"]
            if "track_low_stock" in item_columns:
                low_stock_where.append("track_low_stock = 1")
            low_stock = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.items_table}
                    WHERE {" AND ".join(low_stock_where)}
                    """
                ).fetchone()["count"]
                or 0
            )
        purchase_orders_open = 0
        if resolved.orders_table and _table_exists(conn, resolved.orders_table):
            purchase_orders_open = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.orders_table}
                    WHERE status IN ('PENDING', 'ORDERED', 'PARTIALLY_RECEIVED')
                    """
                ).fetchone()["count"]
                or 0
            )
    return models.InventoryStats(
        references=references,
        total_stock=total_stock,
        low_stock=low_stock,
        purchase_orders_open=purchase_orders_open,
        stockouts=stockouts,
    )


def _auto_report_bucket(start: date, end: date) -> str:
    delta_days = max(0, (end - start).days)
    if delta_days <= 31:
        return "day"
    if delta_days <= 120:
        return "week"
    return "month"


def _iter_report_buckets(start: date, end: date, bucket: str) -> list[date]:
    if start > end:
        start, end = end, start
    if bucket == "week":
        current = start - timedelta(days=start.weekday())
    elif bucket == "month":
        current = date(start.year, start.month, 1)
    else:
        current = start
    buckets: list[date] = []
    while current <= end:
        buckets.append(current)
        if bucket == "day":
            current += timedelta(days=1)
        elif bucket == "week":
            current += timedelta(weeks=1)
        else:
            next_month = current.month + 1
            year = current.year + (next_month - 1) // 12
            month = ((next_month - 1) % 12) + 1
            current = date(year, month, 1)
    return buckets


def _bucket_key(value: datetime, bucket: str) -> str:
    target_date = value.date()
    if bucket == "week":
        target_date = target_date - timedelta(days=target_date.weekday())
    elif bucket == "month":
        target_date = date(target_date.year, target_date.month, 1)
    return target_date.isoformat()


def _should_include_reason(
    reason: str | None, *, include_dotation: bool, include_adjustment: bool
) -> bool:
    if not reason:
        return True
    lowered = reason.lower()
    if not include_dotation and "dotation" in lowered:
        return False
    if not include_adjustment and "ajust" in lowered:
        return False
    return True


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
            legacy_columns = {
                row["name"] for row in legacy.execute("PRAGMA table_info(suppliers)").fetchall()
            }
            contact_expr = "contact_name" if "contact_name" in legacy_columns else "NULL AS contact_name"
            phone_expr = "phone" if "phone" in legacy_columns else "NULL AS phone"
            address_expr = "address" if "address" in legacy_columns else "NULL AS address"
            email_expr = "email" if "email" in legacy_columns else "NULL AS email"
            rows = legacy.execute(
                f"SELECT id, name, {contact_expr}, {phone_expr}, {email_expr}, {address_expr} FROM suppliers"
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
                            _row_get(row, "contact_name"),
                            _row_get(row, "phone"),
                            _row_get(row, "email"),
                            _row_get(row, "address"),
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
    expiry_soon_days = _get_purchase_suggestions_expiry_soon_days()
    module_list = [module for module in module_keys if module in _PURCHASE_SUGGESTION_MODULES]
    if not module_list:
        return []
    migrate_legacy_suppliers_to_site(site_key)
    with _get_site_stock_conn(site_key) as conn:
        for module_key in module_list:
            candidates = _get_reorder_candidates(
                conn, module_key, safety_buffer, expiry_soon_days
            )
            supplier_ids = sorted(
                {
                    candidate["supplier_id"]
                    for candidate in candidates
                    if candidate.get("supplier_id") is not None
                }
            )
            suppliers_by_id: dict[int, sqlite3.Row] = {}
            if supplier_ids:
                placeholders = ", ".join("?" for _ in supplier_ids)
                supplier_rows = conn.execute(
                    f"SELECT * FROM suppliers WHERE id IN ({placeholders})",
                    supplier_ids,
                ).fetchall()
                suppliers_by_id = {row["id"]: row for row in supplier_rows}
            for candidate in candidates:
                supplier_id = candidate.get("supplier_id")
                if supplier_id is None:
                    logger.info(
                        "[PURCHASE_SUGGESTIONS] missing supplier module=%s item_id=%s",
                        module_key,
                        candidate["item_id"],
                    )
                    continue
                supplier_row = suppliers_by_id.get(supplier_id)
                if supplier_row is None:
                    logger.info(
                        "[PURCHASE_SUGGESTIONS] supplier not found module=%s supplier_id=%s item_id=%s",
                        module_key,
                        supplier_id,
                        candidate["item_id"],
                    )
                    candidate["supplier_id"] = None
                    continue
                if _is_supplier_inactive(supplier_row):
                    logger.info(
                        "[PURCHASE_SUGGESTIONS] supplier inactive module=%s supplier_id=%s item_id=%s",
                        module_key,
                        supplier_id,
                        candidate["item_id"],
                    )
                    candidate["supplier_id"] = None
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
                                reason_codes, expiry_date, expiry_days_left, reason_label, stock_current, threshold
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                                json.dumps(item.get("reason_codes") or [], ensure_ascii=False),
                                item.get("expiry_date"),
                                item.get("expiry_days_left"),
                                item.get("reason_label"),
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
                            reason_codes = ?, expiry_date = ?, expiry_days_left = ?, reason_label = ?,
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
                            json.dumps(item.get("reason_codes") or [], ensure_ascii=False),
                            item.get("expiry_date"),
                            item.get("expiry_days_left"),
                            item.get("reason_label"),
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
        if not _table_exists(conn, "link_categories"):
            _ensure_link_tables(conn)
        _seed_default_link_categories(conn)
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
    logger.info("[DB] schema migrated/ok for site %s", site_key)


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
    if "supplier_id" not in remise_item_columns:
        execute("ALTER TABLE remise_items ADD COLUMN supplier_id INTEGER")
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
                "ALTER TABLE items ADD COLUMN track_low_stock INTEGER NOT NULL DEFAULT 1"
            )
            execute("UPDATE items SET track_low_stock = 1 WHERE track_low_stock IS NULL")

        executescript(
            """
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                note TEXT,
                auto_created INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT
            );
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                quantity_ordered INTEGER NOT NULL,
                quantity_received INTEGER NOT NULL DEFAULT 0,
                sku TEXT,
                unit TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_purchase_order_items_item ON purchase_order_items(item_id);
            CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_orders_idempotency_key
            ON purchase_orders(idempotency_key);
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
                reason_codes TEXT,
                expiry_date TEXT,
                expiry_days_left INTEGER,
                reason_label TEXT,
                stock_current INTEGER NOT NULL,
                threshold INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_purchase_suggestions_scope
            ON purchase_suggestions(site_key, module_key, supplier_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_suggestion_lines_item
            ON purchase_suggestion_lines(suggestion_id, item_id);
            """
        )

        purchase_order_info = execute("PRAGMA table_info(purchase_orders)").fetchall()
        purchase_order_columns = {row["name"] for row in purchase_order_info}
        if "idempotency_key" not in purchase_order_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN idempotency_key TEXT")
        execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_purchase_orders_idempotency_key ON purchase_orders(idempotency_key)"
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

        suggestion_line_columns = {
            row["name"] for row in execute("PRAGMA table_info(purchase_suggestion_lines)").fetchall()
        }
        if "reason_codes" not in suggestion_line_columns:
            execute("ALTER TABLE purchase_suggestion_lines ADD COLUMN reason_codes TEXT")
        if "expiry_date" not in suggestion_line_columns:
            execute("ALTER TABLE purchase_suggestion_lines ADD COLUMN expiry_date TEXT")
        if "expiry_days_left" not in suggestion_line_columns:
            execute("ALTER TABLE purchase_suggestion_lines ADD COLUMN expiry_days_left INTEGER")
        if "reason_label" not in suggestion_line_columns:
            execute("ALTER TABLE purchase_suggestion_lines ADD COLUMN reason_label TEXT")
        if "sku" not in suggestion_line_columns:
            execute("ALTER TABLE purchase_suggestion_lines ADD COLUMN sku TEXT")
        if "unit" not in suggestion_line_columns:
            execute("ALTER TABLE purchase_suggestion_lines ADD COLUMN unit TEXT")

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
        if "replacement_sent_at" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN replacement_sent_at TEXT")
        if "replacement_closed_at" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN replacement_closed_at TEXT")
        if "replacement_closed_by" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN replacement_closed_by TEXT")
        if "parent_id" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN parent_id INTEGER")
        if "replacement_for_line_id" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN replacement_for_line_id INTEGER")
        if "kind" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN kind TEXT NOT NULL DEFAULT 'standard'")
        if "is_archived" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
        if "archived_at" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN archived_at TIMESTAMP")
        if "archived_by" not in po_columns:
            execute("ALTER TABLE purchase_orders ADD COLUMN archived_by INTEGER")

        poi_info = execute("PRAGMA table_info(purchase_order_items)").fetchall()
        poi_columns = {row["name"] for row in poi_info}
        if "quantity_received" not in poi_columns:
            execute(
                "ALTER TABLE purchase_order_items ADD COLUMN quantity_received INTEGER NOT NULL DEFAULT 0"
            )
        if "sku" not in poi_columns:
            execute("ALTER TABLE purchase_order_items ADD COLUMN sku TEXT")
        if "unit" not in poi_columns:
            execute("ALTER TABLE purchase_order_items ADD COLUMN unit TEXT")
        if "nonconformity_reason" not in poi_columns:
            execute("ALTER TABLE purchase_order_items ADD COLUMN nonconformity_reason TEXT")
        if "is_nonconforme" not in poi_columns:
            execute(
                "ALTER TABLE purchase_order_items ADD COLUMN is_nonconforme INTEGER NOT NULL DEFAULT 0"
            )
        if "beneficiary_employee_id" not in poi_columns:
            execute("ALTER TABLE purchase_order_items ADD COLUMN beneficiary_employee_id INTEGER")
        if "line_type" not in poi_columns:
            execute(
                "ALTER TABLE purchase_order_items ADD COLUMN line_type TEXT NOT NULL DEFAULT 'standard'"
            )
        if "return_expected" not in poi_columns:
            execute(
                "ALTER TABLE purchase_order_items ADD COLUMN return_expected INTEGER NOT NULL DEFAULT 0"
            )
        if "return_reason" not in poi_columns:
            execute("ALTER TABLE purchase_order_items ADD COLUMN return_reason TEXT")
        if "return_employee_item_id" not in poi_columns:
            execute("ALTER TABLE purchase_order_items ADD COLUMN return_employee_item_id INTEGER")
        if "target_dotation_id" not in poi_columns:
            execute("ALTER TABLE purchase_order_items ADD COLUMN target_dotation_id INTEGER")
        if "return_qty" not in poi_columns:
            execute(
                "ALTER TABLE purchase_order_items ADD COLUMN return_qty INTEGER NOT NULL DEFAULT 0"
            )
        if "return_status" not in poi_columns:
            execute(
                "ALTER TABLE purchase_order_items ADD COLUMN return_status TEXT NOT NULL DEFAULT 'none'"
            )

        dotation_info = execute("PRAGMA table_info(dotations)").fetchall()
        dotation_columns = {row["name"] for row in dotation_info}
        if "perceived_at" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN perceived_at DATE")
        if "is_lost" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN is_lost INTEGER NOT NULL DEFAULT 0")
        if "is_degraded" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN is_degraded INTEGER NOT NULL DEFAULT 0")
        if "degraded_qty" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN degraded_qty INTEGER NOT NULL DEFAULT 0")
        if "lost_qty" not in dotation_columns:
            execute("ALTER TABLE dotations ADD COLUMN lost_qty INTEGER NOT NULL DEFAULT 0")
        execute(
            "UPDATE dotations SET degraded_qty = quantity WHERE is_degraded = 1 AND degraded_qty = 0"
        )
        execute("UPDATE dotations SET lost_qty = quantity WHERE is_lost = 1 AND lost_qty = 0")
        _consolidate_dotation_rows(conn)
        execute("DROP INDEX IF EXISTS idx_dotations_unique")
        execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_dotations_unique
                ON dotations(collaborator_id, item_id)
            """
        )
        execute(
            "UPDATE dotations SET perceived_at = DATE(allocated_at) WHERE perceived_at IS NULL OR perceived_at = ''"
        )
        executescript(
            """
            CREATE TABLE IF NOT EXISTS dotation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dotation_id INTEGER NOT NULL REFERENCES dotations(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                order_id INTEGER,
                item_id INTEGER,
                item_name TEXT,
                sku TEXT,
                size TEXT,
                quantity INTEGER,
                reason TEXT,
                message TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_dotation_events_dotation
                ON dotation_events(dotation_id);
            CREATE INDEX IF NOT EXISTS idx_dotation_events_created
                ON dotation_events(created_at);
            """
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
        if "track_low_stock" not in pharmacy_columns:
            execute(
                "ALTER TABLE pharmacy_items ADD COLUMN track_low_stock INTEGER NOT NULL DEFAULT 1"
            )
        if "supplier_id" not in pharmacy_columns:
            execute("ALTER TABLE pharmacy_items ADD COLUMN supplier_id INTEGER")
        if "size_format" not in pharmacy_columns:
            execute("ALTER TABLE pharmacy_items ADD COLUMN size_format TEXT")
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

        if _table_exists(conn, "suppliers"):
            suppliers_info = execute("PRAGMA table_info(suppliers)").fetchall()
            suppliers_columns = {row["name"] for row in suppliers_info}
            if "contact_name" not in suppliers_columns:
                execute("ALTER TABLE suppliers ADD COLUMN contact_name TEXT")
            if "phone" not in suppliers_columns:
                execute("ALTER TABLE suppliers ADD COLUMN phone TEXT")
            if "address" not in suppliers_columns:
                execute("ALTER TABLE suppliers ADD COLUMN address TEXT")

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
        if "auto_created" not in pharmacy_po_columns:
            execute(
                "ALTER TABLE pharmacy_purchase_orders ADD COLUMN auto_created INTEGER NOT NULL DEFAULT 0"
            )
        if "is_archived" not in pharmacy_po_columns:
            execute(
                "ALTER TABLE pharmacy_purchase_orders ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0"
            )
        if "archived_at" not in pharmacy_po_columns:
            execute("ALTER TABLE pharmacy_purchase_orders ADD COLUMN archived_at TIMESTAMP")
        if "archived_by" not in pharmacy_po_columns:
            execute("ALTER TABLE pharmacy_purchase_orders ADD COLUMN archived_by INTEGER")

        pharmacy_poi_info = execute("PRAGMA table_info(pharmacy_purchase_order_items)").fetchall()
        pharmacy_poi_columns = {row["name"] for row in pharmacy_poi_info}
        if "quantity_received" not in pharmacy_poi_columns:
            execute(
                "ALTER TABLE pharmacy_purchase_order_items ADD COLUMN quantity_received INTEGER NOT NULL DEFAULT 0"
            )
        if "sku" not in pharmacy_poi_columns:
            execute("ALTER TABLE pharmacy_purchase_order_items ADD COLUMN sku TEXT")
        if "unit" not in pharmacy_poi_columns:
            execute("ALTER TABLE pharmacy_purchase_order_items ADD COLUMN unit TEXT")

        execute(
            "CREATE INDEX IF NOT EXISTS idx_pharmacy_purchase_orders_status ON pharmacy_purchase_orders(status)"
        )
        execute(
            "CREATE INDEX IF NOT EXISTS idx_pharmacy_purchase_order_items_item ON pharmacy_purchase_order_items(pharmacy_item_id)"
        )

        executescript(
            """
            CREATE TABLE IF NOT EXISTS purchase_order_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_key TEXT NOT NULL,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                purchase_order_line_id INTEGER NOT NULL REFERENCES purchase_order_items(id) ON DELETE CASCADE,
                module TEXT NOT NULL DEFAULT 'clothing',
                received_qty INTEGER NOT NULL,
                conformity_status TEXT NOT NULL,
                nonconformity_reason TEXT,
                nonconformity_action TEXT,
                note TEXT,
                created_by TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_purchase_order_receipts_order
            ON purchase_order_receipts(purchase_order_id);
            CREATE INDEX IF NOT EXISTS idx_purchase_order_receipts_line
            ON purchase_order_receipts(purchase_order_line_id);
            CREATE TABLE IF NOT EXISTS pending_clothing_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_key TEXT NOT NULL,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                purchase_order_line_id INTEGER NOT NULL REFERENCES purchase_order_items(id) ON DELETE CASCADE,
                receipt_id INTEGER NOT NULL REFERENCES purchase_order_receipts(id) ON DELETE CASCADE,
                employee_id INTEGER NOT NULL REFERENCES collaborators(id) ON DELETE CASCADE,
                new_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                new_item_sku TEXT,
                new_item_size TEXT,
                qty INTEGER NOT NULL,
                return_employee_item_id INTEGER REFERENCES dotations(id) ON DELETE SET NULL,
                target_dotation_id INTEGER REFERENCES dotations(id) ON DELETE SET NULL,
                return_reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                validated_at TIMESTAMP,
                validated_by TEXT,
                UNIQUE(site_key, receipt_id, purchase_order_line_id)
            );
            CREATE TABLE IF NOT EXISTS clothing_supplier_returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_key TEXT NOT NULL,
                purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                purchase_order_line_id INTEGER REFERENCES purchase_order_items(id) ON DELETE SET NULL,
                employee_id INTEGER REFERENCES collaborators(id) ON DELETE SET NULL,
                employee_item_id INTEGER REFERENCES dotations(id) ON DELETE SET NULL,
                item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
                qty INTEGER NOT NULL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'prepared',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_clothing_supplier_returns_order
            ON clothing_supplier_returns(purchase_order_id);
            """
        )

        receipt_info = execute("PRAGMA table_info(purchase_order_receipts)").fetchall()
        receipt_columns = {row["name"] for row in receipt_info}
        if "module" not in receipt_columns:
            execute(
                "ALTER TABLE purchase_order_receipts ADD COLUMN module TEXT NOT NULL DEFAULT 'clothing'"
            )
            execute(
                """
                UPDATE purchase_order_receipts
                SET module = 'clothing'
                WHERE module IS NULL
                """
            )

        pending_info = execute("PRAGMA table_info(pending_clothing_assignments)").fetchall()
        pending_columns = {row["name"] for row in pending_info}
        if pending_info and "target_dotation_id" not in pending_columns:
            execute(
                "ALTER TABLE pending_clothing_assignments ADD COLUMN target_dotation_id INTEGER"
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
                auto_created INTEGER NOT NULL DEFAULT 0,
                idempotency_key TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0,
                archived_at TIMESTAMP,
                archived_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS remise_purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_order_id INTEGER NOT NULL REFERENCES remise_purchase_orders(id) ON DELETE CASCADE,
                remise_item_id INTEGER NOT NULL REFERENCES remise_items(id) ON DELETE CASCADE,
                quantity_ordered INTEGER NOT NULL,
                quantity_received INTEGER NOT NULL DEFAULT 0,
                sku TEXT,
                unit TEXT
            );
            """
        )
        remise_po_info = execute("PRAGMA table_info(remise_purchase_orders)").fetchall()
        remise_po_columns = {row["name"] for row in remise_po_info}
        if "is_archived" not in remise_po_columns:
            execute("ALTER TABLE remise_purchase_orders ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")
        if "archived_at" not in remise_po_columns:
            execute("ALTER TABLE remise_purchase_orders ADD COLUMN archived_at TIMESTAMP")
        if "archived_by" not in remise_po_columns:
            execute("ALTER TABLE remise_purchase_orders ADD COLUMN archived_by INTEGER")
        if "idempotency_key" not in remise_po_columns:
            execute("ALTER TABLE remise_purchase_orders ADD COLUMN idempotency_key TEXT")
        execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_remise_purchase_orders_idempotency_key "
            "ON remise_purchase_orders(idempotency_key)"
        )

        remise_poi_info = execute("PRAGMA table_info(remise_purchase_order_items)").fetchall()
        remise_poi_columns = {row["name"] for row in remise_poi_info}
        if "sku" not in remise_poi_columns:
            execute("ALTER TABLE remise_purchase_order_items ADD COLUMN sku TEXT")
        if "unit" not in remise_poi_columns:
            execute("ALTER TABLE remise_purchase_order_items ADD COLUMN unit TEXT")
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


@dataclass(frozen=True)
class _AutoPurchaseOrderSpec:
    items_table: str
    orders_table: str
    order_items_table: str
    item_id_column: str
    sku_columns: tuple[str, ...]
    unit_columns: tuple[str, ...]
    extra_json_column: str | None
    supplier_resolver: Callable[
        [sqlite3.Connection, sqlite3.Row, dict[str, Any]], int | None
    ]


_AUTO_PO_SPECS: dict[str, _AutoPurchaseOrderSpec] = {
    "default": _AutoPurchaseOrderSpec(
        items_table="items",
        orders_table="purchase_orders",
        order_items_table="purchase_order_items",
        item_id_column="item_id",
        sku_columns=("sku",),
        unit_columns=("size",),
        extra_json_column=None,
        supplier_resolver=lambda _conn, row, _extra: _row_get(row, "supplier_id"),
    ),
    "inventory_remise": _AutoPurchaseOrderSpec(
        items_table="remise_items",
        orders_table="remise_purchase_orders",
        order_items_table="remise_purchase_order_items",
        item_id_column="remise_item_id",
        sku_columns=("sku",),
        unit_columns=("size",),
        extra_json_column="extra_json",
        supplier_resolver=_resolve_remise_supplier_id,
    ),
    "pharmacy": _AutoPurchaseOrderSpec(
        items_table="pharmacy_items",
        orders_table="pharmacy_purchase_orders",
        order_items_table="pharmacy_purchase_order_items",
        item_id_column="pharmacy_item_id",
        sku_columns=("barcode",),
        unit_columns=("packaging", "dosage"),
        extra_json_column="extra_json",
        supplier_resolver=_resolve_pharmacy_supplier_id,
    ),
}


_AUTO_PO_MODULE_ALIASES = {
    "purchase_orders": "default",
    "inventory_remise": "inventory_remise",
    "pharmacy": "pharmacy",
}


def resolve_auto_purchase_order_module_key(module_key: str) -> str:
    normalized = normalize_module_key(module_key)
    resolved = _AUTO_PO_MODULE_ALIASES.get(normalized)
    if resolved is None:
        raise ValueError("Module de bons de commande automatique inconnu.")
    return resolved


def _resolve_first_non_empty(row: sqlite3.Row, columns: Iterable[str]) -> str | None:
    for column in columns:
        value = row[column] if column in row.keys() else None
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def _auto_po_date_bucket() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _build_auto_purchase_order_idempotency_key(
    module: str, supplier_id: int, *, item_id: int | None = None
) -> str:
    key = f"auto:{module}:{db.get_current_site_key()}:{supplier_id}:{_auto_po_date_bucket()}"
    if item_id is None:
        return key
    return f"{key}:{item_id}"


def _list_open_auto_orders_by_supplier(
    conn: sqlite3.Connection, spec: _AutoPurchaseOrderSpec, supplier_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        f"""
        SELECT id, supplier_id, created_at
        FROM {spec.orders_table}
        WHERE auto_created = 1
          AND supplier_id = ?
          AND UPPER(status) NOT IN ({", ".join("?" for _ in _AUTO_PO_CLOSED_STATUSES)})
        ORDER BY created_at DESC, id DESC
        """,
        (supplier_id, *[status for status in _AUTO_PO_CLOSED_STATUSES]),
    ).fetchall()


def _merge_duplicate_auto_orders(
    conn: sqlite3.Connection,
    spec: _AutoPurchaseOrderSpec,
    primary_id: int,
    duplicate_ids: Iterable[int],
) -> None:
    has_sku = _table_has_column(conn, spec.order_items_table, "sku")
    has_unit = _table_has_column(conn, spec.order_items_table, "unit")
    sku_select = ", sku" if has_sku else ""
    unit_select = ", unit" if has_unit else ""
    for duplicate_id in duplicate_ids:
        lines = conn.execute(
            f"""
            SELECT {spec.item_id_column} AS item_id,
                   quantity_ordered,
                   quantity_received{sku_select}{unit_select}
            FROM {spec.order_items_table}
            WHERE purchase_order_id = ?
            """,
            (duplicate_id,),
        ).fetchall()
        for line in lines:
            existing = conn.execute(
                f"""
                SELECT id, quantity_ordered, quantity_received
                FROM {spec.order_items_table}
                WHERE purchase_order_id = ?
                  AND {spec.item_id_column} = ?
                """,
                (primary_id, line["item_id"]),
            ).fetchone()
            if existing:
                target_qty = max(existing["quantity_ordered"], line["quantity_ordered"])
                if target_qty != existing["quantity_ordered"]:
                    conn.execute(
                        f"UPDATE {spec.order_items_table} SET quantity_ordered = ? WHERE id = ?",
                        (target_qty, existing["id"]),
                    )
                continue
            columns = ["purchase_order_id", spec.item_id_column, "quantity_ordered", "quantity_received"]
            values: list[object] = [
                primary_id,
                line["item_id"],
                line["quantity_ordered"],
                line["quantity_received"],
            ]
            if has_sku:
                columns.append("sku")
                values.append(line["sku"])
            if has_unit:
                columns.append("unit")
                values.append(line["unit"])
            conn.execute(
                f"INSERT INTO {spec.order_items_table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                values,
            )
        conn.execute(
            f"DELETE FROM {spec.order_items_table} WHERE purchase_order_id = ?",
            (duplicate_id,),
        )
        conn.execute(
            f"DELETE FROM {spec.orders_table} WHERE id = ?",
            (duplicate_id,),
        )


def _fetch_auto_po_item(
    conn: sqlite3.Connection, module: str, item_id: int
) -> tuple[sqlite3.Row, dict[str, Any], _AutoPurchaseOrderSpec] | None:
    spec = _AUTO_PO_SPECS.get(module)
    if spec is None:
        return None
    columns = [
        "id",
        "name",
        "quantity",
        "low_stock_threshold",
        "supplier_id",
    ]
    columns.extend(spec.sku_columns)
    columns.extend(spec.unit_columns)
    if spec.extra_json_column and _table_has_column(conn, spec.items_table, spec.extra_json_column):
        columns.append(spec.extra_json_column)
    row = conn.execute(
        f"SELECT {', '.join(columns)} FROM {spec.items_table} WHERE id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    extra = {}
    if spec.extra_json_column and spec.extra_json_column in row.keys():
        extra = _parse_extra_json(row[spec.extra_json_column])
    return row, extra, spec


def _maybe_create_auto_purchase_order(
    conn: sqlite3.Connection, module: str, item_id: int
) -> None:
    fetched = _fetch_auto_po_item(conn, module, item_id)
    if fetched is None:
        return
    item, extra, spec = fetched
    supplier_id = spec.supplier_resolver(conn, item, extra)
    if supplier_id is None:
        logger.info(
            "[AUTO_PO] skipped missing supplier module=%s item_id=%s",
            module,
            item_id,
        )
        return
    threshold = item["low_stock_threshold"] or 0
    if threshold <= 0:
        return
    quantity = item["quantity"] or 0
    shortage = threshold - quantity
    if shortage <= 0:
        return

    existing = conn.execute(
        f"""
        SELECT poi.id, poi.quantity_ordered, poi.quantity_received
        FROM {spec.order_items_table} AS poi
        JOIN {spec.orders_table} AS po ON po.id = poi.purchase_order_id
        WHERE poi.{spec.item_id_column} = ?
          AND po.auto_created = 1
          AND UPPER(po.status) NOT IN ({", ".join("?" for _ in _AUTO_PO_CLOSED_STATUSES)})
        ORDER BY po.created_at DESC, po.id DESC
        LIMIT 1
        """,
        (item_id, *[status for status in _AUTO_PO_CLOSED_STATUSES]),
    ).fetchone()

    if existing:
        outstanding = existing["quantity_ordered"] - existing["quantity_received"]
        if outstanding < shortage:
            new_total = existing["quantity_received"] + shortage
            conn.execute(
                f"UPDATE {spec.order_items_table} SET quantity_ordered = ? WHERE id = ?",
                (new_total, existing["id"]),
            )
        return

    note = f"Commande automatique - {item['name']}"
    idempotency_key = None
    if _table_has_column(conn, spec.orders_table, "idempotency_key"):
        idempotency_key = _build_auto_purchase_order_idempotency_key(
            module, supplier_id, item_id=item_id
        )
        existing_order = conn.execute(
            f"""
            SELECT id
            FROM {spec.orders_table}
            WHERE idempotency_key = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (idempotency_key,),
        ).fetchone()
        if existing_order is not None:
            return
    try:
        if idempotency_key:
            po_cur = conn.execute(
                f"""
                INSERT INTO {spec.orders_table} (
                    supplier_id,
                    status,
                    note,
                    auto_created,
                    created_at,
                    idempotency_key
                )
                VALUES (?, 'PENDING', ?, 1, CURRENT_TIMESTAMP, ?)
                """,
                (supplier_id, note, idempotency_key),
            )
        else:
            po_cur = conn.execute(
                f"""
                INSERT INTO {spec.orders_table} (supplier_id, status, note, auto_created, created_at)
                VALUES (?, 'PENDING', ?, 1, CURRENT_TIMESTAMP)
                """,
                (supplier_id, note),
            )
    except sqlite3.IntegrityError:
        if idempotency_key:
            return
        raise
    order_id = int(po_cur.lastrowid)
    has_sku = _table_has_column(conn, spec.order_items_table, "sku")
    has_unit = _table_has_column(conn, spec.order_items_table, "unit")
    columns = ["purchase_order_id", spec.item_id_column, "quantity_ordered"]
    values: list[object] = [order_id, item_id, shortage]
    if has_sku:
        columns.append("sku")
        values.append(_resolve_first_non_empty(item, spec.sku_columns))
    if has_unit:
        columns.append("unit")
        values.append(_resolve_first_non_empty(item, spec.unit_columns))
    conn.execute(
        f"INSERT INTO {spec.order_items_table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        values,
    )


def refresh_auto_purchase_orders(module_key: str) -> models.PurchaseOrderAutoRefreshResponse:
    resolved_module = resolve_auto_purchase_order_module_key(module_key)
    with db.get_stock_connection() as conn:
        spec = _AUTO_PO_SPECS[resolved_module]
        item_columns = ["id", "name", "quantity", "low_stock_threshold"]
        if _table_has_column(conn, spec.items_table, "track_low_stock"):
            item_columns.append("track_low_stock")
        if _table_has_column(conn, spec.items_table, "supplier_id"):
            item_columns.append("supplier_id")
        for column in (*spec.sku_columns, *spec.unit_columns):
            if _table_has_column(conn, spec.items_table, column) and column not in item_columns:
                item_columns.append(column)
        if spec.extra_json_column and _table_has_column(conn, spec.items_table, spec.extra_json_column):
            item_columns.append(spec.extra_json_column)

        low_stock_where = ["quantity < low_stock_threshold", "low_stock_threshold > 0"]
        if "track_low_stock" in item_columns:
            low_stock_where.append("track_low_stock = 1")
        rows = conn.execute(
            f"SELECT {', '.join(item_columns)} FROM {spec.items_table} WHERE {' AND '.join(low_stock_where)}"
        ).fetchall()

        items_by_supplier: dict[int | None, list[dict[str, Any]]] = defaultdict(list)
        items_below_threshold = 0
        skipped = 0
        for row in rows:
            extra: dict[str, Any] = {}
            if spec.extra_json_column and spec.extra_json_column in row.keys():
                extra = _parse_extra_json(row[spec.extra_json_column])
            supplier_id = spec.supplier_resolver(conn, row, extra)
            if supplier_id is None:
                skipped += 1
                continue
            threshold = row["low_stock_threshold"] or 0
            quantity = row["quantity"] or 0
            shortage = threshold - quantity
            if shortage <= 0:
                continue
            items_below_threshold += 1
            items_by_supplier[supplier_id].append(
                {
                    "item_id": row["id"],
                    "name": row["name"],
                    "shortage": shortage,
                    "sku": _resolve_first_non_empty(row, spec.sku_columns),
                    "unit": _resolve_first_non_empty(row, spec.unit_columns),
                }
            )

        has_sku = _table_has_column(conn, spec.order_items_table, "sku")
        has_unit = _table_has_column(conn, spec.order_items_table, "unit")
        has_order_idempotency = _table_has_column(conn, spec.orders_table, "idempotency_key")
        open_orders = conn.execute(
            f"""
            SELECT id, supplier_id, created_at
            FROM {spec.orders_table}
            WHERE auto_created = 1
              AND UPPER(status) NOT IN ({", ".join("?" for _ in _AUTO_PO_CLOSED_STATUSES)})
            ORDER BY created_at DESC, id DESC
            """,
            _AUTO_PO_CLOSED_STATUSES,
        ).fetchall()

        existing_orders: dict[int | None, int] = {}
        merged_duplicate_ids: set[int] = set()
        for supplier_id in {row["supplier_id"] for row in open_orders}:
            if supplier_id is None:
                continue
            supplier_orders = _list_open_auto_orders_by_supplier(
                conn, spec, supplier_id
            )
            if not supplier_orders:
                continue
            primary_id = supplier_orders[0]["id"]
            duplicate_ids = [row["id"] for row in supplier_orders[1:]]
            if duplicate_ids:
                _merge_duplicate_auto_orders(
                    conn,
                    spec,
                    primary_id=primary_id,
                    duplicate_ids=duplicate_ids,
                )
                merged_duplicate_ids.update(duplicate_ids)
            if supplier_id not in existing_orders:
                existing_orders[supplier_id] = primary_id

        created = 0
        updated = 0
        touched_orders: set[int] = set()
        for supplier_id, items in items_by_supplier.items():
            order_id = existing_orders.get(supplier_id)
            if order_id is None:
                note = "Commande automatique - Stock sous seuil"
                idempotency_key = None
                if has_order_idempotency:
                    idempotency_key = _build_auto_purchase_order_idempotency_key(
                        resolved_module, supplier_id
                    )
                    existing_by_key = conn.execute(
                        f"""
                        SELECT id
                        FROM {spec.orders_table}
                        WHERE idempotency_key = ?
                          AND UPPER(status) NOT IN ({", ".join("?" for _ in _AUTO_PO_CLOSED_STATUSES)})
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (idempotency_key, *[status for status in _AUTO_PO_CLOSED_STATUSES]),
                    ).fetchone()
                    if existing_by_key is not None:
                        order_id = existing_by_key["id"]
                if order_id is None:
                    if has_order_idempotency:
                        cur = conn.execute(
                            f"""
                            INSERT INTO {spec.orders_table} (
                                supplier_id,
                                status,
                                note,
                                auto_created,
                                created_at,
                                idempotency_key
                            )
                            VALUES (?, 'PENDING', ?, 1, CURRENT_TIMESTAMP, ?)
                            """,
                            (supplier_id, note, idempotency_key),
                        )
                    else:
                        cur = conn.execute(
                            f"""
                            INSERT INTO {spec.orders_table} (supplier_id, status, note, auto_created, created_at)
                            VALUES (?, 'PENDING', ?, 1, CURRENT_TIMESTAMP)
                            """,
                            (supplier_id, note),
                        )
                    order_id = int(cur.lastrowid)
                    created += 1
                else:
                    updated += 1
            else:
                updated += 1
            touched_orders.add(order_id)

            existing_lines = conn.execute(
                f"""
                SELECT id, {spec.item_id_column} AS item_id, quantity_ordered, quantity_received
                FROM {spec.order_items_table}
                WHERE purchase_order_id = ?
                """,
                (order_id,),
            ).fetchall()
            existing_by_item = {row["item_id"]: row for row in existing_lines}
            current_item_ids = {item["item_id"] for item in items}
            for item in items:
                existing_line = existing_by_item.get(item["item_id"])
                if existing_line:
                    target_qty = existing_line["quantity_received"] + item["shortage"]
                    if existing_line["quantity_ordered"] != target_qty:
                        conn.execute(
                            f"UPDATE {spec.order_items_table} SET quantity_ordered = ? WHERE id = ?",
                            (target_qty, existing_line["id"]),
                        )
                    continue
                columns = ["purchase_order_id", spec.item_id_column, "quantity_ordered"]
                values: list[object] = [order_id, item["item_id"], item["shortage"]]
                if has_sku:
                    columns.append("sku")
                    values.append(item["sku"])
                if has_unit:
                    columns.append("unit")
                    values.append(item["unit"])
                conn.execute(
                    f"INSERT INTO {spec.order_items_table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )

            for line in existing_lines:
                if line["item_id"] not in current_item_ids:
                    conn.execute(
                        f"DELETE FROM {spec.order_items_table} WHERE id = ?",
                        (line["id"],),
                    )

        for row in open_orders:
            order_id = row["id"]
            if order_id in merged_duplicate_ids:
                continue
            if order_id in touched_orders:
                continue
            supplier_id = row["supplier_id"]
            if supplier_id in items_by_supplier:
                continue
            conn.execute(
                f"DELETE FROM {spec.order_items_table} WHERE purchase_order_id = ?",
                (order_id,),
            )
            updated += 1
            touched_orders.add(order_id)

        order_id = next(iter(touched_orders)) if len(touched_orders) == 1 else None
        logger.info(
            "[AUTO_PO] refresh module=%s created=%s updated=%s items=%s skipped=%s",
            module_key,
            created,
            updated,
            items_below_threshold,
            skipped,
        )
        return models.PurchaseOrderAutoRefreshResponse(
            created=created,
            updated=updated,
            skipped=skipped,
            items_below_threshold=items_below_threshold,
            purchase_order_id=order_id,
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


def _sync_vehicle_item_from_remise(conn: sqlite3.Connection, source: sqlite3.Row) -> bool:
    remise_item_id = source["id"]
    raw_sku = source["sku"]
    normalized_sku = raw_sku.strip() if isinstance(raw_sku, str) else ""
    if not normalized_sku:
        site_key = db.get_current_site_key()
        logger.warning(
            "[SYNC] skipping remise item without sku remise_item_id=%s name=%s site_key=%s",
            remise_item_id,
            source["name"],
            site_key,
        )
        return True

    sku_value, sku_relinked = _prepare_vehicle_item_sku(
        conn, normalized_sku, remise_item_id
    )

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
            if sku_value is None:
                return False
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
            return False

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

    if sku_value is not None:
        conn.execute(
            "UPDATE vehicle_items SET sku = ? WHERE remise_item_id = ? AND category_id IS NULL",
            (sku_value, remise_item_id),
        )

    template_row = conn.execute(
        "SELECT id FROM vehicle_items WHERE remise_item_id = ? AND category_id IS NULL",
        (remise_item_id,),
    ).fetchone()
    if template_row is None and sku_value is not None:
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
    return False


def _sync_vehicle_inventory_with_remise(conn: sqlite3.Connection) -> None:
    remise_rows = conn.execute(
        "SELECT id, name, sku, supplier_id, size FROM remise_items"
    ).fetchall()
    seen_ids: list[int] = []
    skipped = 0
    for row in remise_rows:
        if _sync_vehicle_item_from_remise(conn, row):
            skipped += 1
        seen_ids.append(row["id"])
    if skipped:
        logger.warning(
            "[SYNC] skipped %s remise items without sku site_key=%s",
            skipped,
            db.get_current_site_key(),
        )
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
        track_stock_alerts=track_low_stock,
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
    _maybe_create_auto_purchase_order(conn, "inventory_remise", remise_item_id)
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
    _maybe_create_auto_purchase_order(conn, "pharmacy", pharmacy_item_id)
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


def _validate_sku_requirements(name: str | None, quantity: int | None, supplier_id: int | None) -> None:
    trimmed_name = name.strip() if isinstance(name, str) else ""
    if not trimmed_name:
        raise ValueError("Nom obligatoire")
    if quantity is None or quantity < 0:
        raise ValueError("Quantité obligatoire")


def _sku_requires_validation(new_sku: str | None, current_sku: str | None) -> bool:
    if new_sku is None:
        return False
    normalized_new = new_sku.strip()
    if not normalized_new:
        return False
    normalized_current = current_sku.strip() if isinstance(current_sku, str) else ""
    return normalized_new.casefold() != normalized_current.casefold()


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
        if sku and str(sku).strip():
            _validate_sku_requirements(name, payload.quantity, supplier_id)
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
            _maybe_create_auto_purchase_order(conn, module, item_id)
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
        if module != "vehicle_inventory" and _sku_requires_validation(fields.get("sku"), None):
            current_row = conn.execute(
                f"SELECT sku FROM {config.tables.items} WHERE id = ?",
                (item_id,),
            ).fetchone()
            if current_row is None:
                raise ValueError("Article introuvable")
            if _sku_requires_validation(fields.get("sku"), current_row["sku"]):
                _validate_sku_requirements(
                    fields.get("name"),
                    fields.get("quantity"),
                    fields.get("supplier_id"),
                )
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
            _maybe_create_auto_purchase_order(conn, module, item_id)
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
            _maybe_create_auto_purchase_order(conn, module, item_id)
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


def _generate_pending_username(display_name: str | None) -> str:
    base_source = display_name or "user"
    normalized = unicodedata.normalize("NFKD", base_source)
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    if not slug:
        slug = "user"
    with db.get_users_connection() as conn:
        for _ in range(50):
            suffix = secrets.token_hex(2)
            candidate = f"pending-{slug}-{suffix}"
            exists = conn.execute(
                "SELECT 1 FROM users WHERE username = ?",
                (candidate,),
            ).fetchone()
            if not exists:
                return candidate
    raise ValueError("Impossible de générer un identifiant unique")


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


def _validate_table_prefs_payload(prefs: dict[str, Any]) -> dict[str, Any]:
    if prefs.get("v") != _TABLE_PREFS_VERSION:
        raise ValueError("Version de préférences invalide.")
    visible = prefs.get("visible")
    if visible is not None:
        if not isinstance(visible, dict):
            raise ValueError("Champ visible invalide.")
        for key, value in visible.items():
            if not isinstance(key, str):
                raise ValueError("Clé de colonne invalide.")
            if not isinstance(value, bool):
                raise ValueError("Valeur de visibilité invalide.")
    order = prefs.get("order")
    if order is not None:
        if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
            raise ValueError("Ordre des colonnes invalide.")
    widths = prefs.get("widths")
    if widths is not None:
        if not isinstance(widths, dict):
            raise ValueError("Largeurs des colonnes invalides.")
        for key, value in widths.items():
            if not isinstance(key, str):
                raise ValueError("Clé de colonne invalide.")
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("Valeur de largeur invalide.")
    return prefs


def get_table_prefs(user_id: int, site_key: str, table_key: str) -> dict[str, Any] | None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT prefs_json
            FROM user_table_prefs
            WHERE user_id = ? AND site_key = ? AND table_key = ?
            """,
            (user_id, site_key, table_key),
        ).fetchone()
    if not row:
        return None
    try:
        parsed = json.loads(row["prefs_json"])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    try:
        return _validate_table_prefs_payload(parsed)
    except ValueError:
        return None


def set_table_prefs(
    user_id: int, site_key: str, table_key: str, prefs: dict[str, Any]
) -> dict[str, Any]:
    ensure_database_ready()
    if not isinstance(prefs, dict):
        raise ValueError("Préférences invalides.")
    validated = _validate_table_prefs_payload(prefs)
    payload_json = json.dumps(validated, ensure_ascii=False)
    if len(payload_json.encode("utf-8")) > _TABLE_PREFS_MAX_BYTES:
        raise ValueError("Préférences trop volumineuses.")
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_table_prefs (user_id, site_key, table_key, prefs_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, site_key, table_key)
            DO UPDATE SET
                prefs_json = excluded.prefs_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, site_key, table_key, payload_json),
        )
        conn.commit()
    return validated


def delete_table_prefs(user_id: int, site_key: str, table_key: str) -> None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute(
            """
            DELETE FROM user_table_prefs
            WHERE user_id = ? AND site_key = ? AND table_key = ?
            """,
            (user_id, site_key, table_key),
        )
        conn.commit()


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


def _get_message_content_limit() -> int:
    raw_limit = os.getenv("MESSAGE_MAX_LENGTH")
    try:
        limit = int(raw_limit) if raw_limit else _MESSAGE_CONTENT_MAX_LENGTH
    except ValueError:
        limit = _MESSAGE_CONTENT_MAX_LENGTH
    return max(1, limit)


def _normalize_idempotency_key(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    trimmed = raw_value.strip()
    if not trimmed:
        return None
    if len(trimmed) > _MESSAGE_IDEMPOTENCY_MAX_LENGTH:
        raise ValueError("Clé d'idempotence trop longue")
    return trimmed


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
    idempotency_key = _normalize_idempotency_key(payload.idempotency_key)
    max_length = _get_message_content_limit()
    if not content:
        raise ValueError("Le contenu du message est requis")
    if len(content) > max_length:
        raise ValueError(f"Le message dépasse la limite de {max_length} caractères")
    if not category:
        raise ValueError("La catégorie est requise")
    with db.get_users_connection() as conn:
        if idempotency_key:
            existing_row = conn.execute(
                """
                SELECT id
                FROM messages
                WHERE sender_username = ? AND idempotency_key = ?
                """,
                (sender.username, idempotency_key),
            ).fetchone()
            if existing_row:
                message_id = int(existing_row["id"])
                recipients_count = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM message_recipients
                    WHERE message_id = ?
                    """,
                    (message_id,),
                ).fetchone()
                return models.MessageSendResponse(
                    message_id=message_id,
                    recipients_count=int(recipients_count["total"] if recipients_count else 0),
                )

        if payload.broadcast:
            cur = conn.execute(
                """
                SELECT username
                FROM users
                WHERE status = 'active' AND is_active = 1
                ORDER BY username COLLATE NOCASE
                """,
            )
            recipients = [row["username"] for row in cur.fetchall()]
        else:
            recipients = [recipient.strip() for recipient in payload.recipients if recipient.strip()]

        recipients = list(dict.fromkeys(recipients))
        if not recipients:
            raise ValueError("Aucun destinataire sélectionné")

        placeholders = ", ".join("?" for _ in recipients)
        exclude_sender_clause = "" if payload.broadcast else "AND username != ?"
        valid_params: list[str] = [*recipients]
        if not payload.broadcast:
            valid_params.append(sender.username)
        cur = conn.execute(
            f"""
            SELECT username
            FROM users
            WHERE status = 'active' AND is_active = 1 AND username IN ({placeholders})
              {exclude_sender_clause}
            """,
            valid_params,
        )
        valid_recipients = [row["username"] for row in cur.fetchall()]
        if not valid_recipients:
            raise ValueError("Aucun destinataire valide")

        _enforce_message_rate_limit(conn, sender.username)

        try:
            cur = conn.execute(
                """
                INSERT INTO messages (sender_username, sender_role, category, content, idempotency_key)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sender.username, sender.role, category, content, idempotency_key),
            )
            message_id = int(cur.lastrowid)
        except sqlite3.IntegrityError:
            if idempotency_key:
                existing_row = conn.execute(
                    """
                    SELECT id
                    FROM messages
                    WHERE sender_username = ? AND idempotency_key = ?
                    """,
                    (sender.username, idempotency_key),
                ).fetchone()
                if existing_row:
                    message_id = int(existing_row["id"])
                    recipients_count = conn.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM message_recipients
                        WHERE message_id = ?
                        """,
                        (message_id,),
                    ).fetchone()
                    return models.MessageSendResponse(
                        message_id=message_id,
                        recipients_count=int(recipients_count["total"] if recipients_count else 0),
                    )
            raise
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
        if payload.broadcast:
            resolved_recipient_usernames = [
                row["username"]
                for row in conn.execute(
                    """
                    SELECT username
                    FROM users
                    WHERE status = 'active' AND is_active = 1
                    ORDER BY username COLLATE NOCASE
                    """
                ).fetchall()
            ]
        else:
            resolved_recipient_usernames = sorted(valid_recipients, key=str.casefold)

    _archive_message_safe(
        message_id=message_id,
        created_at=created_at,
        sender_username=sender.username,
        sender_role=sender.role,
        recipients=resolved_recipient_usernames,
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
    user: models.User,
    *,
    limit: int = 50,
    include_archived: bool = False,
    archived_only: bool = False,
    query: str | None = None,
    category: str | None = None,
    cursor: int | None = None,
) -> list[models.InboxMessage]:
    ensure_database_ready()
    limit_value = max(1, min(limit, 200))
    params: list[object] = [user.username]
    clauses = ["mr.recipient_username = ?", "mr.deleted_at IS NULL"]
    if archived_only:
        clauses.append("mr.is_archived = 1")
    elif not include_archived:
        clauses.append("mr.is_archived = 0")
    if query:
        like_value = f"%{query.strip()}%"
        if like_value.strip("%"):
            clauses.append("(m.content LIKE ? OR m.sender_username LIKE ?)")
            params.extend([like_value, like_value])
    if category:
        clauses.append("m.category = ?")
        params.append(category.strip())
    if cursor:
        clauses.append("m.id < ?")
        params.append(cursor)
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
            WHERE {" AND ".join(clauses)}
            ORDER BY m.created_at DESC, m.id DESC
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


def list_sent_messages(
    user: models.User,
    *,
    limit: int = 50,
    query: str | None = None,
    category: str | None = None,
    cursor: int | None = None,
) -> list[models.SentMessage]:
    ensure_database_ready()
    limit_value = max(1, min(limit, 200))
    params: list[object] = [user.username]
    clauses = ["m.sender_username = ?"]
    if query:
        like_value = f"%{query.strip()}%"
        if like_value.strip("%"):
            clauses.append("m.content LIKE ?")
            params.append(like_value)
    if category:
        clauses.append("m.category = ?")
        params.append(category.strip())
    if cursor:
        clauses.append("m.id < ?")
        params.append(cursor)
    params.append(limit_value)

    with db.get_users_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT
                m.id,
                m.category,
                m.content,
                m.created_at,
                COUNT(mr.id) AS recipients_total,
                SUM(CASE WHEN mr.read_at IS NOT NULL THEN 1 ELSE 0 END) AS recipients_read
            FROM messages m
            JOIN message_recipients mr ON mr.message_id = m.id
            WHERE {" AND ".join(clauses)}
            GROUP BY m.id
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT ?
            """,
            params,
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


def mark_message_unread(message_id: int, user: models.User) -> None:
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
        if row["is_read"]:
            conn.execute(
                """
                UPDATE message_recipients
                SET is_read = 0, read_at = NULL
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


def unarchive_message(message_id: int, user: models.User) -> None:
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
        if row["is_archived"]:
            conn.execute(
                """
                UPDATE message_recipients
                SET is_archived = 0, archived_at = NULL
                WHERE id = ?
                """,
                (row["id"],),
            )
            conn.commit()
            logger.info("[MESSAGE] unarchive id=%s by=%s", message_id, user.username)


def delete_message(message_id: int, user: models.User) -> None:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT id, deleted_at
            FROM message_recipients
            WHERE message_id = ? AND recipient_username = ?
            """,
            (message_id, user.username),
        ).fetchone()
        if not row:
            raise PermissionError("Accès interdit")
        if not row["deleted_at"]:
            conn.execute(
                """
                UPDATE message_recipients
                SET deleted_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
            conn.commit()
            logger.info("[MESSAGE] delete id=%s by=%s", message_id, user.username)


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


def find_items_by_barcode(module: str, barcode: str) -> list[models.BarcodeLookupItem]:
    ensure_database_ready()
    normalized_input = barcode.strip().replace(" ", "")
    if not normalized_input:
        raise ValueError("Le code-barres ne peut pas être vide")
    normalized = normalized_input.upper()

    if module == "clothing":
        table = "items"
        column = "sku"
    elif module == "remise":
        table = "remise_items"
        column = "sku"
    elif module == "pharmacy":
        table = "pharmacy_items"
        column = "barcode"
    else:
        raise ValueError("Module invalide")

    query = (
        f"SELECT id, name FROM {table} "
        f"WHERE UPPER(REPLACE(TRIM({column}), ' ', '')) = ? "
        "ORDER BY name COLLATE NOCASE"
    )
    with db.get_stock_connection() as conn:
        if module == "remise":
            _ensure_remise_item_columns(conn)
        rows = conn.execute(query, (normalized,)).fetchall()

    return [models.BarcodeLookupItem(id=row["id"], name=row["name"]) for row in rows]


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
        item_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(items)").fetchall()
        }
        where_clauses = ["quantity < low_stock_threshold", "low_stock_threshold >= ?"]
        if "track_low_stock" in item_columns:
            where_clauses.append("track_low_stock = 1")
        cur = conn.execute(
            f"""
            SELECT *, (low_stock_threshold - quantity) AS shortage
            FROM items
            WHERE {" AND ".join(where_clauses)}
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
                    track_low_stock=bool(row["track_low_stock"])
                    if "track_low_stock" in row.keys()
                    else True,
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
    cover_image_path = None
    if "cover_image_path" in row.keys():
        cover_image_path = row["cover_image_path"]
    else:
        cover_image_path = row["image_path"]
    return models.RemiseLot(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        created_at=_coerce_datetime(row["created_at"]),
        image_url=_build_media_url(row["image_path"]),
        cover_image_url=_build_media_url(cover_image_path),
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
    cover_image_path = row["cover_image_path"] if "cover_image_path" in row.keys() else None
    return models.PharmacyLot(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        created_at=row["created_at"],
        image_url=_build_media_url(row["image_path"]),
        cover_image_url=_build_media_url(cover_image_path),
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
                   rl.cover_image_path AS cover_image_path,
                   COUNT(pli.id) AS item_count, COALESCE(SUM(pli.quantity), 0) AS total_quantity
            FROM pharmacy_lots AS pl
            LEFT JOIN (
                SELECT LOWER(name) AS normalized_name,
                       MAX(image_path) AS cover_image_path
                FROM remise_lots
                GROUP BY LOWER(name)
            ) AS rl ON rl.normalized_name = LOWER(pl.name)
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
                   rl.cover_image_path AS cover_image_path,
                   COUNT(pli.id) AS item_count, COALESCE(SUM(pli.quantity), 0) AS total_quantity
            FROM pharmacy_lots AS pl
            LEFT JOIN (
                SELECT LOWER(name) AS normalized_name,
                       MAX(image_path) AS cover_image_path
                FROM remise_lots
                GROUP BY LOWER(name)
            ) AS rl ON rl.normalized_name = LOWER(pl.name)
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
                   rl.cover_image_path AS cover_image_path,
                   COUNT(pli.id) AS item_count, COALESCE(SUM(pli.quantity), 0) AS total_quantity
            FROM pharmacy_lots AS pl
            LEFT JOIN (
                SELECT LOWER(name) AS normalized_name,
                       MAX(image_path) AS cover_image_path
                FROM remise_lots
                GROUP BY LOWER(name)
            ) AS rl ON rl.normalized_name = LOWER(pl.name)
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

    titles = {entry.key: entry.label for entry in _AVAILABLE_MODULE_DEFINITIONS}
    config_path = Path(__file__).resolve().parent.parent / "config.ini"
    parser = ConfigParser()
    parser.read(config_path, encoding="utf-8")
    if parser.has_section("modules"):
        for key, value in parser.items("modules"):
            trimmed = value.strip()
            if trimmed:
                titles[normalize_module_key(key)] = trimmed
    normalized = normalize_module_key(module_key)
    return titles.get(normalized, normalized or module_key)


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
                    name=_row_get(row, "name", ""),
                    contact_name=_row_get(row, "contact_name"),
                    phone=_row_get(row, "phone"),
                    email=_row_get(row, "email"),
                    address=_row_get(row, "address"),
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
            name=_row_get(row, "name", ""),
            contact_name=_row_get(row, "contact_name"),
            phone=_row_get(row, "phone"),
            email=_row_get(row, "email"),
            address=_row_get(row, "address"),
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


SUPPLIER_NOT_FOUND_ACTIVE_SITE_MESSAGE = "Fournisseur introuvable sur le site actif."
SUPPLIER_EMAIL_MISSING_MESSAGE = (
    "Email fournisseur manquant. Ajoutez un email au fournisseur pour activer l'envoi."
)


class SupplierResolutionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PendingAssignmentConflictError(ValueError):
    pass


class NonConformeReceiptRequiredError(ValueError):
    pass


class ReplacementReceptionLockedError(ValueError):
    pass


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
                SUPPLIER_NOT_FOUND_ACTIVE_SITE_MESSAGE,
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
            name=_row_get(row, "name", ""),
            contact_name=_row_get(row, "contact_name"),
            phone=_row_get(row, "phone"),
            email=_row_get(row, "email"),
            address=_row_get(row, "address"),
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
        name=_row_get(row, "name", ""),
        contact_name=_row_get(row, "contact_name"),
        phone=_row_get(row, "phone"),
        email=_row_get(row, "email"),
        address=_row_get(row, "address"),
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
            SUPPLIER_NOT_FOUND_ACTIVE_SITE_MESSAGE,
        )
    return supplier


def require_supplier_email(supplier: models.Supplier) -> str:
    raw_email = str(supplier.email or "").strip()
    if not raw_email:
        raise SupplierResolutionError("SUPPLIER_EMAIL_MISSING", SUPPLIER_EMAIL_MISSING_MESSAGE)
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
    has_line_sku = _table_has_column(conn, "purchase_order_items", "sku")
    has_line_unit = _table_has_column(conn, "purchase_order_items", "unit")
    has_line_nonconformity_reason = _table_has_column(
        conn, "purchase_order_items", "nonconformity_reason"
    )
    has_line_is_nonconforme = _table_has_column(conn, "purchase_order_items", "is_nonconforme")
    has_beneficiary = _table_has_column(conn, "purchase_order_items", "beneficiary_employee_id")
    has_line_type = _table_has_column(conn, "purchase_order_items", "line_type")
    has_return_expected = _table_has_column(conn, "purchase_order_items", "return_expected")
    has_return_reason = _table_has_column(conn, "purchase_order_items", "return_reason")
    has_return_employee_item_id = _table_has_column(
        conn, "purchase_order_items", "return_employee_item_id"
    )
    has_target_dotation_id = _table_has_column(
        conn, "purchase_order_items", "target_dotation_id"
    )
    has_return_qty = _table_has_column(conn, "purchase_order_items", "return_qty")
    has_return_status = _table_has_column(conn, "purchase_order_items", "return_status")
    sku_expr = "i.sku AS sku"
    unit_expr = "COALESCE(NULLIF(TRIM(i.size), ''), 'Unité') AS unit"
    if has_line_sku:
        sku_expr = "COALESCE(NULLIF(TRIM(poi.sku), ''), i.sku) AS sku"
    if has_line_unit:
        unit_expr = "COALESCE(NULLIF(TRIM(poi.unit), ''), NULLIF(TRIM(i.size), ''), 'Unité') AS unit"
    beneficiary_expr = "NULL AS beneficiary_employee_id"
    beneficiary_name_expr = "NULL AS beneficiary_name"
    if has_beneficiary:
        beneficiary_expr = "poi.beneficiary_employee_id AS beneficiary_employee_id"
        beneficiary_name_expr = "c.full_name AS beneficiary_name"
    nonconformity_reason_expr = "NULL AS nonconformity_reason"
    if has_line_nonconformity_reason:
        nonconformity_reason_expr = "poi.nonconformity_reason AS nonconformity_reason"
    is_nonconforme_expr = "0 AS is_nonconforme"
    if has_line_is_nonconforme:
        is_nonconforme_expr = "poi.is_nonconforme AS is_nonconforme"
    line_type_expr = "'standard' AS line_type"
    if has_line_type:
        line_type_expr = "poi.line_type AS line_type"
    return_expected_expr = "0 AS return_expected"
    if has_return_expected:
        return_expected_expr = "poi.return_expected AS return_expected"
    return_reason_expr = "NULL AS return_reason"
    if has_return_reason:
        return_reason_expr = "poi.return_reason AS return_reason"
    return_employee_expr = "NULL AS return_employee_item_id"
    if has_return_employee_item_id:
        return_employee_expr = "poi.return_employee_item_id AS return_employee_item_id"
    target_dotation_expr = "NULL AS target_dotation_id"
    if has_target_dotation_id:
        target_dotation_expr = "poi.target_dotation_id AS target_dotation_id"
    return_qty_expr = "0 AS return_qty"
    if has_return_qty:
        return_qty_expr = "poi.return_qty AS return_qty"
    return_status_expr = "'none' AS return_status"
    if has_return_status:
        return_status_expr = "poi.return_status AS return_status"
    items_cur = conn.execute(
        f"""
        SELECT poi.id,
               poi.purchase_order_id,
               poi.item_id,
               poi.quantity_ordered,
               poi.quantity_received,
               i.name AS item_name,
               i.size AS size,
               {sku_expr},
               {unit_expr},
               {beneficiary_expr},
               {beneficiary_name_expr},
               {nonconformity_reason_expr},
               {is_nonconforme_expr},
               {line_type_expr},
               {return_expected_expr},
               {return_reason_expr},
               {return_employee_expr},
               {target_dotation_expr},
               {return_qty_expr},
               {return_status_expr}
        FROM purchase_order_items AS poi
        JOIN items AS i ON i.id = poi.item_id
        LEFT JOIN collaborators AS c ON c.id = poi.beneficiary_employee_id
        WHERE poi.purchase_order_id = ?
        ORDER BY i.name COLLATE NOCASE
        """,
        (order_row["id"],),
    )
    items_rows = items_cur.fetchall()
    resolved_email = None
    supplier_has_email = False
    supplier_missing_reason = None
    supplier_id = _row_get(order_row, "supplier_id")
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
    resolved_site_key = site_key or db.get_current_site_key()
    receipts: list[models.PurchaseOrderReceipt] = []
    receipt_summaries: dict[int, dict[str, int]] = {}
    receipt_counts: dict[int, int] = {}
    if _table_exists(conn, "purchase_order_receipts"):
        receipt_rows = conn.execute(
            """
            SELECT *
            FROM purchase_order_receipts
            WHERE purchase_order_id = ? AND site_key = ?
            ORDER BY created_at DESC, id DESC
            """,
            (order_row["id"], resolved_site_key),
        ).fetchall()
        receipts = [
            models.PurchaseOrderReceipt(
                id=row["id"],
                site_key=row["site_key"],
                purchase_order_id=row["purchase_order_id"],
                purchase_order_line_id=row["purchase_order_line_id"],
                module=_row_get(row, "module"),
                received_qty=row["received_qty"],
                conformity_status=row["conformity_status"],
                nonconformity_reason=_row_get(row, "nonconformity_reason"),
                nonconformity_action=_row_get(row, "nonconformity_action"),
                note=_row_get(row, "note"),
                created_by=_row_get(row, "created_by"),
                created_at=row["created_at"],
            )
            for row in receipt_rows
        ]
        summary_rows = conn.execute(
            """
            SELECT purchase_order_line_id,
                   conformity_status,
                   SUM(received_qty) AS total
            FROM purchase_order_receipts
            WHERE purchase_order_id = ? AND site_key = ?
            GROUP BY purchase_order_line_id, conformity_status
            """,
            (order_row["id"], resolved_site_key),
        ).fetchall()
        for row in summary_rows:
            line_id = row["purchase_order_line_id"]
            receipt_summaries.setdefault(line_id, {})[row["conformity_status"]] = int(
                row["total"] or 0
            )
            receipt_counts[line_id] = receipt_counts.get(line_id, 0) + 1
    nonconformities: list[models.PurchaseOrderNonconformity] = []
    if _table_exists(conn, "purchase_order_nonconformities"):
        module_expr = "module AS module"
        if not _table_has_column(conn, "purchase_order_nonconformities", "module"):
            module_expr = "'clothing' AS module"
        note_expr = "note AS note"
        if not _table_has_column(conn, "purchase_order_nonconformities", "note"):
            note_expr = "NULL AS note"
        requested_expr = "requested_replacement AS requested_replacement"
        if not _table_has_column(conn, "purchase_order_nonconformities", "requested_replacement"):
            requested_expr = "0 AS requested_replacement"
        created_by_expr = "created_by AS created_by"
        if not _table_has_column(conn, "purchase_order_nonconformities", "created_by"):
            created_by_expr = "NULL AS created_by"
        updated_at_expr = "updated_at AS updated_at"
        if not _table_has_column(conn, "purchase_order_nonconformities", "updated_at"):
            updated_at_expr = "created_at AS updated_at"
        try:
            nonconformity_rows = conn.execute(
                f"""
                SELECT id,
                       site_key,
                       {module_expr},
                       purchase_order_id,
                       purchase_order_line_id,
                       receipt_id,
                       status,
                       reason,
                       {note_expr},
                       {requested_expr},
                       {created_by_expr},
                       created_at,
                       {updated_at_expr}
                FROM purchase_order_nonconformities
                WHERE purchase_order_id = ? AND site_key = ?
                ORDER BY created_at DESC, id DESC
                """,
                (order_row["id"], resolved_site_key),
            ).fetchall()
            nonconformities = [
                models.PurchaseOrderNonconformity(
                    id=row["id"],
                    site_key=row["site_key"],
                    module=row["module"],
                    purchase_order_id=row["purchase_order_id"],
                    purchase_order_line_id=row["purchase_order_line_id"],
                    receipt_id=row["receipt_id"],
                    status=row["status"],
                    reason=row["reason"],
                    note=_row_get(row, "note"),
                    requested_replacement=bool(_row_get(row, "requested_replacement", 0)),
                    created_by=_row_get(row, "created_by"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in nonconformity_rows
            ]
        except sqlite3.OperationalError:
            nonconformities = []
    items = [
        models.PurchaseOrderItem(
            id=item_row["id"],
            purchase_order_id=item_row["purchase_order_id"],
            item_id=item_row["item_id"],
            quantity_ordered=item_row["quantity_ordered"],
            quantity_received=item_row["quantity_received"],
            item_name=item_row["item_name"],
            size=_row_get(item_row, "size"),
            sku=_row_get(item_row, "sku"),
            unit=_row_get(item_row, "unit"),
            nonconformity_reason=_row_get(item_row, "nonconformity_reason"),
            is_nonconforme=bool(_row_get(item_row, "is_nonconforme", 0)),
            beneficiary_employee_id=_row_get(item_row, "beneficiary_employee_id"),
            beneficiary_name=_row_get(item_row, "beneficiary_name"),
            line_type=_row_get(item_row, "line_type", "standard"),
            return_expected=bool(_row_get(item_row, "return_expected", 0)),
            return_reason=_row_get(item_row, "return_reason"),
            return_employee_item_id=_row_get(item_row, "return_employee_item_id"),
            target_dotation_id=_row_get(item_row, "target_dotation_id"),
            return_qty=_row_get(item_row, "return_qty", 0),
            return_status=_row_get(item_row, "return_status", "none"),
            received_conforme_qty=(
                receipt_summaries.get(item_row["id"], {}).get("conforme", 0)
                if receipt_counts.get(item_row["id"])
                else item_row["quantity_received"]
            ),
            received_non_conforme_qty=(
                receipt_summaries.get(item_row["id"], {}).get("non_conforme", 0)
                if receipt_counts.get(item_row["id"])
                else 0
            ),
        )
        for item_row in items_rows
    ]
    pending_assignments: list[models.PendingClothingAssignment] = []
    if _table_exists(conn, "pending_clothing_assignments"):
        pending_rows = conn.execute(
            """
            SELECT *
            FROM pending_clothing_assignments
            WHERE purchase_order_id = ? AND site_key = ?
            ORDER BY created_at DESC, id DESC
            """,
            (order_row["id"], resolved_site_key),
        ).fetchall()
        receipt_by_id = {receipt.id: receipt for receipt in receipts}
        pending_assignments = [
            models.PendingClothingAssignment(
                id=row["id"],
                site_key=row["site_key"],
                purchase_order_id=row["purchase_order_id"],
                purchase_order_line_id=row["purchase_order_line_id"],
                receipt_id=row["receipt_id"],
                employee_id=row["employee_id"],
                new_item_id=row["new_item_id"],
                new_item_sku=_row_get(row, "new_item_sku"),
                new_item_size=_row_get(row, "new_item_size"),
                qty=row["qty"],
                return_employee_item_id=_row_get(row, "return_employee_item_id"),
                target_dotation_id=_row_get(row, "target_dotation_id"),
                return_reason=_row_get(row, "return_reason"),
                status=row["status"],
                created_at=row["created_at"],
                validated_at=_row_get(row, "validated_at"),
                validated_by=_row_get(row, "validated_by"),
                source_receipt=receipt_by_id.get(row["receipt_id"]),
            )
            for row in pending_rows
        ]
    supplier_returns: list[models.ClothingSupplierReturn] = []
    if _table_exists(conn, "clothing_supplier_returns"):
        return_rows = conn.execute(
            """
            SELECT *
            FROM clothing_supplier_returns
            WHERE purchase_order_id = ? AND site_key = ?
            ORDER BY created_at DESC, id DESC
            """,
            (order_row["id"], resolved_site_key),
        ).fetchall()
        supplier_returns = [
            models.ClothingSupplierReturn(
                id=row["id"],
                site_key=row["site_key"],
                purchase_order_id=row["purchase_order_id"],
                purchase_order_line_id=_row_get(row, "purchase_order_line_id"),
                employee_id=_row_get(row, "employee_id"),
                employee_item_id=_row_get(row, "employee_item_id"),
                item_id=_row_get(row, "item_id"),
                qty=row["qty"],
                reason=_row_get(row, "reason"),
                status=row["status"],
                created_at=row["created_at"],
            )
            for row in return_rows
        ]
    latest_returns_by_line, _ = _resolve_latest_supplier_returns(supplier_returns)
    if latest_returns_by_line:
        for item in items:
            latest_return = latest_returns_by_line.get(item.id)
            if latest_return is not None:
                item.return_status = _map_supplier_return_status(latest_return.status)
    has_nonconforming_receipt = any(
        summary.get("non_conforme", 0) > 0 for summary in receipt_summaries.values()
    )
    latest_nonconforming_receipt_at: datetime | None = None
    for receipt in receipts:
        if receipt.conformity_status != "non_conforme":
            continue
        receipt_time = _coerce_datetime(receipt.created_at)
        if latest_nonconforming_receipt_at is None or receipt_time > latest_nonconforming_receipt_at:
            latest_nonconforming_receipt_at = receipt_time
    replacement_sent_at = _row_get(order_row, "replacement_sent_at")
    replacement_closed_at = _row_get(order_row, "replacement_closed_at")
    replacement_closed_by = _row_get(order_row, "replacement_closed_by")
    replacement_closed_effective = False
    if replacement_closed_at:
        closed_at_dt = _coerce_datetime(replacement_closed_at)
        if latest_nonconforming_receipt_at is None or closed_at_dt >= latest_nonconforming_receipt_at:
            replacement_closed_effective = True
    requested_replacements = [
        nonconformity
        for nonconformity in nonconformities
        if nonconformity.requested_replacement
    ]
    replacement_flow_status = "none"
    if requested_replacements:
        replacement_flow_status = "closed" if replacement_closed_effective else "open"
    replacement_flow_open = replacement_flow_status == "open"
    replacement_lock_reception = has_nonconforming_receipt and not replacement_closed_effective
    replacement_assignment_completed = (
        replacement_flow_status == "closed"
        and not any(assignment.status == "pending" for assignment in pending_assignments)
    )
    return models.PurchaseOrderDetail(
        id=order_row["id"],
        supplier_id=supplier_id,
        parent_id=_row_get(order_row, "parent_id"),
        replacement_for_line_id=_row_get(order_row, "replacement_for_line_id"),
        kind=_row_get(order_row, "kind", "standard") or "standard",
        supplier_name=order_row["supplier_name"],
        supplier_email=supplier.email if supplier else None,
        supplier_email_resolved=resolved_email,
        supplier_has_email=supplier_has_email,
        supplier_missing_reason=supplier_missing_reason,
        replacement_flow_status=replacement_flow_status,
        replacement_flow_open=replacement_flow_open,
        replacement_lock_reception=replacement_lock_reception,
        replacement_assignment_completed=replacement_assignment_completed,
        replacement_sent_at=replacement_sent_at,
        replacement_closed_at=replacement_closed_at,
        replacement_closed_by=replacement_closed_by,
        status=order_row["status"],
        created_at=order_row["created_at"],
        note=order_row["note"],
        auto_created=bool(order_row["auto_created"]),
        last_sent_at=order_row["last_sent_at"],
        last_sent_to=order_row["last_sent_to"],
        last_sent_by=order_row["last_sent_by"],
        is_archived=bool(_row_get(order_row, "is_archived", 0)),
        archived_at=_row_get(order_row, "archived_at"),
        archived_by=_row_get(order_row, "archived_by"),
        items=items,
        receipts=receipts,
        nonconformities=nonconformities,
        pending_assignments=pending_assignments,
        supplier_returns=supplier_returns,
    )


def list_purchase_orders(
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[models.PurchaseOrderDetail]:
    ensure_database_ready()
    where_clause = ""
    params: tuple[object, ...] = ()
    if archived_only:
        where_clause = "WHERE COALESCE(po.is_archived, 0) = 1"
    elif not include_archived:
        where_clause = "WHERE COALESCE(po.is_archived, 0) = 0"
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"""
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            {where_clause}
            ORDER BY po.created_at DESC, po.id DESC
            """,
            params,
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


def archive_purchase_order(
    order_id: int,
    *,
    archived_by: int | None = None,
) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    order = get_purchase_order(order_id)
    if order.is_archived:
        return order
    _assert_purchase_order_archivable_detail(order)
    with db.get_stock_connection() as conn:
        conn.execute(
            """
            UPDATE purchase_orders
            SET is_archived = 1,
                archived_at = CURRENT_TIMESTAMP,
                archived_by = ?
            WHERE id = ?
            """,
            (archived_by, order_id),
        )
    return get_purchase_order(order_id)


def unarchive_purchase_order(
    order_id: int,
) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        conn.execute(
            """
            UPDATE purchase_orders
            SET is_archived = 0,
                archived_at = NULL,
                archived_by = NULL
            WHERE id = ?
            """,
            (order_id,),
        )
    return get_purchase_order(order_id)


def _normalize_purchase_order_payload(
    payload: models.PurchaseOrderCreate,
    *,
    status: str,
    created_by: int | None,
    date_bucket: str,
) -> dict[str, object]:
    normalized_lines = []
    for line in payload.items:
        line_type = (line.line_type or "standard").strip().lower()
        normalized_lines.append(
            {
                "item_id": line.item_id,
                "quantity_ordered": line.quantity_ordered,
                "line_type": line_type,
                "beneficiary_employee_id": line.beneficiary_employee_id,
                "return_expected": bool(line.return_expected),
                "return_reason": line.return_reason.strip() if line.return_reason else None,
                "return_employee_item_id": line.return_employee_item_id,
                "target_dotation_id": line.target_dotation_id,
                "return_qty": line.return_qty,
            }
        )
    normalized_lines.sort(
        key=lambda item: (
            item["item_id"],
            item["quantity_ordered"],
            item["line_type"],
            item["beneficiary_employee_id"] or 0,
            item["return_expected"],
            item["return_reason"] or "",
            item["return_employee_item_id"] or 0,
            item["target_dotation_id"] or 0,
            item["return_qty"] or 0,
        )
    )
    return {
        "site_key": db.get_current_site_key(),
        "supplier_id": payload.supplier_id,
        "status": status,
        "created_by": created_by,
        "date_bucket": date_bucket,
        "items": normalized_lines,
    }


def build_purchase_order_payload_hash(
    payload: models.PurchaseOrderCreate,
    *,
    created_by: int | None,
    date_bucket: str | None = None,
    status: str | None = None,
) -> str:
    normalized_status = _normalize_purchase_order_status(status or payload.status)
    bucket = date_bucket or datetime.now(timezone.utc).date().isoformat()
    normalized = _normalize_purchase_order_payload(
        payload,
        status=normalized_status,
        created_by=created_by,
        date_bucket=bucket,
    )
    serialized = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_purchase_order_idempotency_key(
    payload: models.PurchaseOrderCreate,
    *,
    created_by: int | None,
    idempotency_key: str | None = None,
    date_bucket: str | None = None,
    status: str | None = None,
) -> str | None:
    if idempotency_key:
        return idempotency_key
    if created_by is None:
        return None
    if payload.supplier_id is None:
        return None
    return build_purchase_order_payload_hash(
        payload,
        created_by=created_by,
        date_bucket=date_bucket,
        status=status,
    )


def create_purchase_order(
    payload: models.PurchaseOrderCreate,
    *,
    idempotency_key: str | None = None,
    created_by: int | None = None,
) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    status = _normalize_purchase_order_status(payload.status)
    if not payload.items:
        raise ValueError("Au moins un article est requis pour créer un bon de commande")
    if payload.supplier_id is None:
        raise ValueError("Fournisseur obligatoire")
    with db.get_stock_connection() as conn:
        if payload.supplier_id is not None:
            supplier_cur = conn.execute(
                "SELECT 1 FROM suppliers WHERE id = ?", (payload.supplier_id,)
            )
            if supplier_cur.fetchone() is None:
                raise ValueError("Fournisseur introuvable")
        has_idempotency_key = _table_has_column(conn, "purchase_orders", "idempotency_key")
        effective_idempotency_key = None
        if has_idempotency_key:
            effective_idempotency_key = build_purchase_order_idempotency_key(
                payload,
                created_by=created_by,
                idempotency_key=idempotency_key,
                status=status,
            )
            if effective_idempotency_key:
                existing = conn.execute(
                    """
                    SELECT id
                    FROM purchase_orders
                    WHERE idempotency_key = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (effective_idempotency_key,),
                ).fetchone()
                if existing is not None:
                    logger.info(
                        "[PO] duplicate create detected idempotency_key=%s order_id=%s",
                        effective_idempotency_key,
                        existing["id"],
                    )
                    return get_purchase_order(existing["id"])
        try:
            if has_idempotency_key:
                cur = conn.execute(
                    """
                    INSERT INTO purchase_orders (
                        supplier_id,
                        status,
                        note,
                        auto_created,
                        created_at,
                        idempotency_key
                    )
                    VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP, ?)
                    """,
                    (payload.supplier_id, status, payload.note, effective_idempotency_key),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO purchase_orders (supplier_id, status, note, auto_created, created_at)
                    VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
                    """,
                    (payload.supplier_id, status, payload.note),
                )
            order_id = cur.lastrowid
            has_line_sku = _table_has_column(conn, "purchase_order_items", "sku")
            has_line_unit = _table_has_column(conn, "purchase_order_items", "unit")
            has_beneficiary = _table_has_column(
                conn, "purchase_order_items", "beneficiary_employee_id"
            )
            has_line_type = _table_has_column(conn, "purchase_order_items", "line_type")
            has_return_expected = _table_has_column(conn, "purchase_order_items", "return_expected")
            has_return_reason = _table_has_column(conn, "purchase_order_items", "return_reason")
            has_return_employee_item_id = _table_has_column(
                conn, "purchase_order_items", "return_employee_item_id"
            )
            has_target_dotation_id = _table_has_column(
                conn, "purchase_order_items", "target_dotation_id"
            )
            has_return_qty = _table_has_column(conn, "purchase_order_items", "return_qty")
            has_return_status = _table_has_column(conn, "purchase_order_items", "return_status")
            for line in payload.items:
                item_id = line.item_id
                quantity = line.quantity_ordered
                if quantity <= 0:
                    continue
                item_row = conn.execute(
                    "SELECT sku, size FROM items WHERE id = ?", (item_id,)
                ).fetchone()
                if item_row is None:
                    raise ValueError("Article introuvable")
                line_type = (line.line_type or "standard").strip().lower()
                if line_type not in {"standard", "replacement"}:
                    raise ValueError("Type de ligne invalide")
                beneficiary_id = line.beneficiary_employee_id
                if beneficiary_id:
                    collaborator_row = conn.execute(
                        "SELECT 1 FROM collaborators WHERE id = ?",
                        (beneficiary_id,),
                    ).fetchone()
                    if collaborator_row is None:
                        raise ValueError("Collaborateur introuvable")
                return_expected = bool(line.return_expected)
                return_reason = (line.return_reason or "").strip() if line.return_reason else None
                target_dotation_id = line.target_dotation_id or line.return_employee_item_id
                return_employee_item_id = line.return_employee_item_id or target_dotation_id
                return_qty = line.return_qty if line.return_qty is not None else 0
                return_status = "none"
                if line_type == "replacement":
                    if not beneficiary_id:
                        raise ValueError("Le bénéficiaire est requis pour un remplacement")
                    return_expected = True
                    if not return_reason:
                        raise ValueError("Le motif de retour est requis pour un remplacement")
                    if return_qty <= 0:
                        return_qty = quantity
                    if return_qty <= 0:
                        raise ValueError("La quantité de retour doit être positive")
                    if not target_dotation_id:
                        raise ValueError(
                            "La dotation à remplacer est requise pour un remplacement"
                        )
                    dotation_row = conn.execute(
                        """
                        SELECT collaborator_id, degraded_qty, lost_qty
                        FROM dotations
                        WHERE id = ?
                        """,
                        (target_dotation_id,),
                    ).fetchone()
                    if dotation_row is None:
                        raise ValueError("Article attribué introuvable pour le retour")
                    if dotation_row["collaborator_id"] != beneficiary_id:
                        raise ValueError("L'article retourné n'appartient pas au bénéficiaire")
                    if not (dotation_row["lost_qty"] or dotation_row["degraded_qty"]):
                        raise ValueError(
                            "La dotation sélectionnée doit être en perte ou dégradation."
                        )
                    if dotation_row["lost_qty"]:
                        return_expected = False
                        return_qty = 0
                        return_status = "none"
                    else:
                        return_status = "to_prepare"
                elif return_expected:
                    if not return_reason:
                        raise ValueError("Le motif de retour est requis")
                    if return_qty <= 0:
                        raise ValueError("La quantité de retour doit être positive")
                    return_status = "to_prepare"
                columns = [
                    "purchase_order_id",
                    "item_id",
                    "quantity_ordered",
                    "quantity_received",
                ]
                values: list[object] = [order_id, item_id, quantity, 0]
                if has_line_sku:
                    columns.append("sku")
                    values.append(item_row["sku"])
                if has_line_unit:
                    columns.append("unit")
                    values.append(item_row["size"] if item_row["size"] else None)
                if has_beneficiary:
                    columns.append("beneficiary_employee_id")
                    values.append(beneficiary_id)
                if has_line_type:
                    columns.append("line_type")
                    values.append(line_type)
                if has_return_expected:
                    columns.append("return_expected")
                    values.append(int(return_expected))
                if has_return_reason:
                    columns.append("return_reason")
                    values.append(return_reason)
                if has_return_employee_item_id:
                    columns.append("return_employee_item_id")
                    values.append(return_employee_item_id)
                if has_target_dotation_id:
                    columns.append("target_dotation_id")
                    values.append(target_dotation_id)
                if has_return_qty:
                    columns.append("return_qty")
                    values.append(return_qty)
                if has_return_status:
                    columns.append("return_status")
                    values.append(return_status)
                conn.execute(
                    f"INSERT INTO purchase_order_items ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            if has_idempotency_key and effective_idempotency_key:
                existing = conn.execute(
                    """
                    SELECT id
                    FROM purchase_orders
                    WHERE idempotency_key = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (effective_idempotency_key,),
                ).fetchone()
                if existing is not None:
                    conn.rollback()
                    logger.info(
                        "[PO] idempotency conflict resolved idempotency_key=%s order_id=%s",
                        effective_idempotency_key,
                        existing["id"],
                    )
                    return get_purchase_order(existing["id"])
            conn.rollback()
            raise
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


def _resolve_user_display_name(user: models.User | None) -> str | None:
    if not user:
        return None
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    if first_name or last_name:
        return " ".join(part for part in (first_name, last_name) if part)
    display_name = getattr(user, "display_name", None)
    if display_name:
        return display_name
    return getattr(user, "username", None)


def _resolve_user_phone(user: models.User | None) -> str | None:
    if not user:
        return None
    for attr in ("phone", "phone_number", "telephone"):
        value = getattr(user, attr, None)
        if value:
            return value
    return None


def _resolve_contact_value(user: models.User | None) -> str | None:
    if not user:
        return None
    parts = []
    name = _resolve_user_display_name(user)
    if name:
        parts.append(name)
    if user.email:
        parts.append(user.email)
    phone = _resolve_user_phone(user)
    if phone:
        parts.append(phone)
    return " / ".join(parts) if parts else None


def _resolve_site_address(site_info: models.SiteInfo | None) -> str | None:
    if not site_info:
        return None
    address_parts = []
    for attr in ("address", "street", "street_address"):
        value = getattr(site_info, attr, None)
        if value:
            address_parts.append(str(value))
    city_parts = []
    for attr in ("postal_code", "zip_code", "postcode"):
        value = getattr(site_info, attr, None)
        if value:
            city_parts.append(str(value))
    for attr in ("city", "town"):
        value = getattr(site_info, attr, None)
        if value:
            city_parts.append(str(value))
    if city_parts:
        address_parts.append(" ".join(city_parts))
    for attr in ("country",):
        value = getattr(site_info, attr, None)
        if value:
            address_parts.append(str(value))
    if address_parts:
        return ", ".join(address_parts)
    if site_info.display_name and site_info.display_name != site_info.site_key:
        return f"Site: {site_info.display_name} ({site_info.site_key})"
    return f"Site: {site_info.site_key}"


def _build_purchase_order_blocks(
    order: models.PurchaseOrderDetail
    | models.RemisePurchaseOrderDetail
    | models.PharmacyPurchaseOrderDetail,
    *,
    user: models.User | None = None,
    site_info: models.SiteInfo | None = None,
) -> tuple[dict[str, str | None], dict[str, str | None], dict[str, str | None]]:
    supplier = None
    if order.supplier_id is not None:
        with db.get_stock_connection() as conn:
            supplier = resolve_supplier_for_order(
                conn, db.get_current_site_key(), order.supplier_id
            )
    supplier_name = order.supplier_name or (supplier.name if supplier else None)
    buyer_block = {
        "Nom": _resolve_user_display_name(user),
        "Téléphone": _resolve_user_phone(user),
        "Email": user.email if user else None,
    }
    supplier_block = {
        "Nom": supplier_name,
        "Contact": supplier.contact_name if supplier else None,
        "Téléphone": supplier.phone if supplier else None,
        "Email": supplier.email if supplier else None,
        "Adresse": supplier.address if supplier else None,
    }
    delivery_block: dict[str, str | None] = {
        "Adresse": _resolve_site_address(site_info),
        "Date souhaitée": None,
        "Contact": _resolve_contact_value(user),
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


def generate_purchase_order_pdf(
    order: models.PurchaseOrderDetail,
    *,
    user: models.User | None = None,
    site_key: str | None = None,
) -> bytes:
    resolved_site_key = sites.normalize_site_key(site_key) if site_key else db.get_current_site_key()
    site_info = _get_site_info_for_email(resolved_site_key)
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(
        order,
        user=user,
        site_info=site_info,
    )
    return render_purchase_order_pdf(
        title="BON DE COMMANDE",
        purchase_order=order,
        buyer_block=buyer_block,
        supplier_block=supplier_block,
        delivery_block=delivery_block,
        include_received=False,
    )


def generate_purchase_order_reception_pdf(
    order: models.PurchaseOrderDetail,
    *,
    user: models.User | None = None,
    site_key: str | None = None,
) -> bytes:
    resolved_site_key = sites.normalize_site_key(site_key) if site_key else db.get_current_site_key()
    site_info = _get_site_info_for_email(resolved_site_key)
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(
        order,
        user=user,
        site_info=site_info,
    )
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
    context_note: str | None = None,
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
        order,
        site_info,
        sent_by_user,
        context_note=context_note,
    )
    pdf_bytes = generate_purchase_order_pdf(
        order,
        user=sent_by_user,
        site_key=normalized_site_key,
    )
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
        if order.kind == "replacement_request" and order.parent_id:
            conn.execute(
                """
                UPDATE purchase_orders
                SET replacement_sent_at = ?,
                    replacement_closed_at = NULL,
                    replacement_closed_by = NULL
                WHERE id = ?
                """,
                (sent_at, order.parent_id),
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
        order,
        site_info,
        sent_by_user,
        context_note=None,
    )
    subject = f"Bon de commande REMISE - {site_info.display_name or site_info.site_key} - #{order.id}"
    pdf_bytes = generate_remise_purchase_order_pdf(
        order,
        user=sent_by_user,
        site_key=normalized_site_key,
    )
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
        order,
        site_info,
        sent_by_user,
        context_note=None,
    )
    pdf_bytes = generate_pharmacy_purchase_order_pdf(
        order,
        user=sent_by_user,
        site_key=normalized_site_key,
    )
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


def generate_remise_purchase_order_pdf(
    order: models.RemisePurchaseOrderDetail,
    *,
    user: models.User | None = None,
    site_key: str | None = None,
) -> bytes:
    resolved_site_key = sites.normalize_site_key(site_key) if site_key else db.get_current_site_key()
    site_info = _get_site_info_for_email(resolved_site_key)
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(
        order,
        user=user,
        site_info=site_info,
    )
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
    *,
    user: models.User | None = None,
    site_key: str | None = None,
) -> bytes:
    resolved_site_key = sites.normalize_site_key(site_key) if site_key else db.get_current_site_key()
    site_info = _get_site_info_for_email(resolved_site_key)
    buyer_block, supplier_block, delivery_block = _build_purchase_order_blocks(
        order,
        user=user,
        site_info=site_info,
    )
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


def _is_replacement_reception_locked(
    conn: sqlite3.Connection,
    order_id: int,
    *,
    site_key: str | None = None,
) -> bool:
    normalized_site_key = site_key or db.get_current_site_key()
    if not _table_exists(conn, "purchase_order_receipts"):
        return False
    if not _table_exists(conn, "purchase_order_nonconformities"):
        return False
    nonconforme_row = conn.execute(
        """
        SELECT 1
        FROM purchase_order_receipts
        WHERE purchase_order_id = ?
          AND site_key = ?
          AND conformity_status = 'non_conforme'
        LIMIT 1
        """,
        (order_id, normalized_site_key),
    ).fetchone()
    if nonconforme_row is None:
        return False
    if _table_has_column(conn, "purchase_orders", "replacement_closed_at"):
        order_row = conn.execute(
            "SELECT replacement_closed_at FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        replacement_closed_at = _row_get(order_row, "replacement_closed_at") if order_row else None
        latest_nonconforming_row = conn.execute(
            """
            SELECT created_at
            FROM purchase_order_receipts
            WHERE purchase_order_id = ?
              AND site_key = ?
              AND conformity_status = 'non_conforme'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (order_id, normalized_site_key),
        ).fetchone()
        if latest_nonconforming_row is None:
            return False
        if not replacement_closed_at:
            return True
        closed_at_dt = _coerce_datetime(replacement_closed_at)
        latest_nonconforming_at = _coerce_datetime(latest_nonconforming_row["created_at"])
        return closed_at_dt < latest_nonconforming_at
    if not _table_has_column(conn, "purchase_order_nonconformities", "requested_replacement"):
        return False
    replacement_open = conn.execute(
        """
        SELECT 1
        FROM purchase_order_nonconformities
        WHERE purchase_order_id = ?
          AND site_key = ?
          AND requested_replacement = 1
          AND status != 'closed'
        LIMIT 1
        """,
        (order_id, normalized_site_key),
    ).fetchone()
    return replacement_open is not None


def receive_purchase_order(
    order_id: int, payload: models.PurchaseOrderReceivePayload
) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    line_increments: dict[int, int] = {}
    item_increments: dict[int, int] = {}
    if payload.lines:
        line_increments = _aggregate_positive_quantities(
            (line.line_id, line.qty) for line in payload.lines
        )
    elif payload.items:
        item_increments = _aggregate_positive_quantities(
            (line.item_id, line.quantity) for line in payload.items
        )
    if not line_increments and not item_increments:
        raise ValueError("Aucune ligne de réception valide")
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT status FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        if order_row["status"] == "CANCELLED":
            raise ValueError("Bon de commande annulé")
        if _is_replacement_reception_locked(conn, order_id):
            raise ReplacementReceptionLockedError(
                "Réception verrouillée : remplacement non clôturé"
            )
        try:
            if line_increments:
                for line_id, increment in line_increments.items():
                    line = conn.execute(
                        """
                        SELECT id, item_id, quantity_ordered, quantity_received
                        FROM purchase_order_items
                        WHERE purchase_order_id = ? AND id = ?
                        """,
                        (order_id, line_id),
                    ).fetchone()
                    if line is None:
                        raise ValueError("Ligne de commande introuvable")
                    remaining = line["quantity_ordered"] - line["quantity_received"]
                    if increment > remaining:
                        raise ValueError("Quantité reçue supérieure au restant")
                    if increment <= 0:
                        continue
                    new_received = line["quantity_received"] + increment
                    conn.execute(
                        "UPDATE purchase_order_items SET quantity_received = ? WHERE id = ?",
                        (new_received, line["id"]),
                    )
                    conn.execute(
                        "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                        (increment, line["item_id"]),
                    )
                    conn.execute(
                        "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                        (line["item_id"], increment, f"Réception bon de commande #{order_id}"),
                    )
                    _maybe_create_auto_purchase_order(conn, "default", line["item_id"])
            else:
                for item_id, increment in item_increments.items():
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
                    if increment > remaining:
                        raise ValueError("Quantité reçue supérieure au restant")
                    if increment <= 0:
                        continue
                    new_received = line["quantity_received"] + increment
                    conn.execute(
                        "UPDATE purchase_order_items SET quantity_received = ? WHERE id = ?",
                        (new_received, line["id"]),
                    )
                    conn.execute(
                        "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                        (increment, item_id),
                    )
                    conn.execute(
                        "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                        (item_id, increment, f"Réception bon de commande #{order_id}"),
                    )
                    _maybe_create_auto_purchase_order(conn, "default", item_id)
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


def receive_purchase_order_line(
    order_id: int,
    payload: models.PurchaseOrderReceiveLinePayload,
    *,
    created_by: str | None,
) -> models.PurchaseOrderReceiveLineResponse:
    ensure_database_ready()
    normalized_site_key = db.get_current_site_key()
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT status FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        if order_row["status"] == "CANCELLED":
            raise ValueError("Bon de commande annulé")
        if payload.conformity_status == "conforme" and _is_replacement_reception_locked(
            conn, order_id
        ):
            raise ReplacementReceptionLockedError(
                "Réception verrouillée : remplacement non clôturé"
            )
        line = conn.execute(
            """
            SELECT *
            FROM purchase_order_items
            WHERE purchase_order_id = ? AND id = ?
            """,
            (order_id, payload.purchase_order_line_id),
        ).fetchone()
        if line is None:
            raise ValueError("Ligne de commande introuvable")
        if payload.received_qty <= 0:
            raise ValueError("Quantité reçue invalide")
        remaining = line["quantity_ordered"] - line["quantity_received"]
        if payload.received_qty > remaining:
            raise ValueError("Quantité reçue supérieure au restant")
        if payload.conformity_status == "non_conforme":
            if not payload.nonconformity_reason:
                raise ValueError("Motif de non-conformité requis")
        try:
            if payload.conformity_status == "conforme":
                new_received = line["quantity_received"] + payload.received_qty
                conn.execute(
                    "UPDATE purchase_order_items SET quantity_received = ? WHERE id = ?",
                    (new_received, line["id"]),
                )
                conn.execute(
                    "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                    (payload.received_qty, line["item_id"]),
                )
                conn.execute(
                    "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                    (
                        line["item_id"],
                        payload.received_qty,
                        f"Réception bon de commande #{order_id}",
                    ),
                )
            receipt_cur = conn.execute(
                """
                INSERT INTO purchase_order_receipts (
                    site_key,
                    purchase_order_id,
                    purchase_order_line_id,
                    module,
                    received_qty,
                    conformity_status,
                    nonconformity_reason,
                    nonconformity_action,
                    note,
                    created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_site_key,
                    order_id,
                    payload.purchase_order_line_id,
                    "clothing",
                    payload.received_qty,
                    payload.conformity_status,
                    payload.nonconformity_reason,
                    payload.nonconformity_action,
                    payload.note,
                    created_by,
                ),
            )
            receipt_id = receipt_cur.lastrowid
            line_type = _row_get(line, "line_type", "standard")
            beneficiary_id = _row_get(line, "beneficiary_employee_id")
            if payload.conformity_status == "conforme" and line_type == "replacement":
                item_row = conn.execute(
                    "SELECT sku, size FROM items WHERE id = ?",
                    (line["item_id"],),
                ).fetchone()
                target_dotation_id = _row_get(line, "target_dotation_id") or _row_get(
                    line, "return_employee_item_id"
                )
                pending_columns = [
                    "site_key",
                    "purchase_order_id",
                    "purchase_order_line_id",
                    "receipt_id",
                    "employee_id",
                    "new_item_id",
                    "new_item_sku",
                    "new_item_size",
                    "qty",
                    "return_employee_item_id",
                    "return_reason",
                    "status",
                ]
                pending_values: list[object] = [
                    normalized_site_key,
                    order_id,
                    line["id"],
                    receipt_id,
                    beneficiary_id,
                    line["item_id"],
                    _row_get(item_row, "sku"),
                    _row_get(item_row, "size"),
                    payload.received_qty,
                    target_dotation_id,
                    _row_get(line, "return_reason"),
                    "pending",
                ]
                if _table_has_column(conn, "pending_clothing_assignments", "target_dotation_id"):
                    pending_columns.insert(-2, "target_dotation_id")
                    pending_values.insert(-2, target_dotation_id)
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO pending_clothing_assignments (
                        {", ".join(pending_columns)}
                    ) VALUES ({", ".join("?" for _ in pending_columns)})
                    """,
                    pending_values,
                )
                if _table_has_column(conn, "purchase_order_items", "return_status") and _row_get(
                    line, "return_expected", 0
                ):
                    conn.execute(
                        "UPDATE purchase_order_items SET return_status = ? WHERE id = ?",
                        ("to_prepare", line["id"]),
                    )
            if payload.conformity_status == "conforme":
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
    with db.get_stock_connection() as conn:
        summary_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN conformity_status = 'conforme' THEN received_qty END), 0)
                    AS received_conforme_qty,
                COALESCE(SUM(CASE WHEN conformity_status = 'non_conforme' THEN received_qty END), 0)
                    AS received_non_conforme_qty
            FROM purchase_order_receipts
            WHERE purchase_order_id = ? AND purchase_order_line_id = ? AND site_key = ?
            """,
            (order_id, payload.purchase_order_line_id, normalized_site_key),
        ).fetchone()
    return models.PurchaseOrderReceiveLineResponse(
        ok=True,
        line_id=payload.purchase_order_line_id,
        received_conforme_qty=int(summary_row["received_conforme_qty"] or 0),
        received_non_conforme_qty=int(summary_row["received_non_conforme_qty"] or 0),
        blocked_assignment=payload.conformity_status == "non_conforme",
    )


def request_purchase_order_replacement(
    order_id: int,
    payload: models.PurchaseOrderReplacementRequest,
    *,
    requested_by: str | None,
) -> models.PurchaseOrderReplacementResponse:
    ensure_database_ready()
    normalized_site_key = db.get_current_site_key()
    with db.get_stock_connection() as conn:
        receipt_row = conn.execute(
            """
            SELECT *
            FROM purchase_order_receipts
            WHERE id = ? AND purchase_order_id = ? AND site_key = ?
            """,
            (payload.receipt_id, order_id, normalized_site_key),
        ).fetchone()
        if receipt_row is None:
            raise ValueError("Réception introuvable")
        if receipt_row["purchase_order_line_id"] != payload.line_id:
            raise ValueError("Ligne de réception invalide")
        if receipt_row["conformity_status"] != "non_conforme":
            raise NonConformeReceiptRequiredError("La réception doit être non conforme.")
        reason = _row_get(receipt_row, "nonconformity_reason")
        if not reason:
            raise ValueError("Motif de non conformité manquant")
        note = _row_get(receipt_row, "note")
        conn.execute(
            """
            INSERT INTO purchase_order_nonconformities (
                site_key,
                module,
                purchase_order_id,
                purchase_order_line_id,
                receipt_id,
                status,
                reason,
                note,
                requested_replacement,
                created_by,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(site_key, receipt_id, purchase_order_line_id) DO UPDATE SET
                status = excluded.status,
                reason = excluded.reason,
                note = excluded.note,
                requested_replacement = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                normalized_site_key,
                "clothing",
                order_id,
                payload.line_id,
                payload.receipt_id,
                "replacement_requested",
                reason,
                note,
                requested_by,
            ),
        )
        row = conn.execute(
            """
            SELECT id, status
            FROM purchase_order_nonconformities
            WHERE site_key = ? AND receipt_id = ? AND purchase_order_line_id = ?
            """,
            (normalized_site_key, payload.receipt_id, payload.line_id),
        ).fetchone()
        if row is None:
            raise ValueError("Demande de remplacement introuvable")
        return models.PurchaseOrderReplacementResponse(
            ok=True,
            nonconformity_id=row["id"],
            status=row["status"],
        )


def request_purchase_order_replacement_order(
    order_id: int,
    line_id: int,
    *,
    requested_by: str | None,
) -> models.PurchaseOrderReplacementOrderResponse:
    ensure_database_ready()
    normalized_site_key = db.get_current_site_key()
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT * FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        line_row = conn.execute(
            """
            SELECT *
            FROM purchase_order_items
            WHERE id = ? AND purchase_order_id = ?
            """,
            (line_id, order_id),
        ).fetchone()
        if line_row is None:
            raise ValueError("Ligne de commande introuvable")
        existing_row = conn.execute(
            """
            SELECT id, status, supplier_id
            FROM purchase_orders
            WHERE parent_id = ? AND replacement_for_line_id = ? AND kind = 'replacement_request'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (order_id, line_id),
        ).fetchone()
        if existing_row is not None:
            can_send = False
            if existing_row["status"] in {"PENDING", "ORDERED"}:
                supplier = resolve_supplier_for_order(
                    conn, normalized_site_key, existing_row["supplier_id"]
                )
                if supplier is not None:
                    try:
                        require_supplier_email(supplier)
                        can_send = True
                    except SupplierResolutionError:
                        can_send = False
            return models.PurchaseOrderReplacementOrderResponse(
                replacement_order_id=existing_row["id"],
                replacement_order_status=existing_row["status"],
                can_send_to_supplier=can_send,
            )
        receipt_row = conn.execute(
            """
            SELECT *
            FROM purchase_order_receipts
            WHERE purchase_order_id = ?
              AND purchase_order_line_id = ?
              AND site_key = ?
              AND conformity_status = 'non_conforme'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (order_id, line_id, normalized_site_key),
        ).fetchone()
        if receipt_row is None:
            raise NonConformeReceiptRequiredError("La réception doit être non conforme.")
        reason = _row_get(receipt_row, "nonconformity_reason")
        if not reason:
            raise ValueError("Motif de non conformité manquant")
        total_row = conn.execute(
            """
            SELECT COALESCE(SUM(received_qty), 0) AS total
            FROM purchase_order_receipts
            WHERE purchase_order_id = ?
              AND purchase_order_line_id = ?
              AND site_key = ?
              AND conformity_status = 'non_conforme'
            """,
            (order_id, line_id, normalized_site_key),
        ).fetchone()
        total_nonconforme = int(total_row["total"] or 0)
        if total_nonconforme <= 0:
            raise ValueError("Quantité non conforme introuvable")
        supplier_id = _row_get(order_row, "supplier_id")
        if supplier_id is None:
            raise ValueError("Fournisseur obligatoire")
        note = f"Remplacement suite non-conformité BC #{order_id}"
        line_note = _row_get(receipt_row, "note")
        try:
            cur = conn.execute(
                """
                INSERT INTO purchase_orders (
                    supplier_id,
                    status,
                    note,
                    auto_created,
                    created_at,
                    parent_id,
                    replacement_for_line_id,
                    kind
                )
                VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP, ?, ?, 'replacement_request')
                """,
                (supplier_id, "PENDING", note, order_id, line_id),
            )
            replacement_order_id = cur.lastrowid
            item_row = conn.execute(
                "SELECT sku, size FROM items WHERE id = ?",
                (line_row["item_id"],),
            ).fetchone()
            if item_row is None:
                raise ValueError("Article introuvable")
            columns = [
                "purchase_order_id",
                "item_id",
                "quantity_ordered",
                "quantity_received",
            ]
            values: list[object] = [replacement_order_id, line_row["item_id"], total_nonconforme, 0]
            if _table_has_column(conn, "purchase_order_items", "sku"):
                columns.append("sku")
                values.append(item_row["sku"])
            if _table_has_column(conn, "purchase_order_items", "unit"):
                columns.append("unit")
                values.append(item_row["size"] if item_row["size"] else None)
            if _table_has_column(conn, "purchase_order_items", "nonconformity_reason"):
                columns.append("nonconformity_reason")
                values.append(reason)
            if _table_has_column(conn, "purchase_order_items", "is_nonconforme"):
                columns.append("is_nonconforme")
                values.append(1)
            if _table_has_column(conn, "purchase_order_items", "beneficiary_employee_id"):
                columns.append("beneficiary_employee_id")
                values.append(_row_get(line_row, "beneficiary_employee_id"))
            if _table_has_column(conn, "purchase_order_items", "line_type"):
                columns.append("line_type")
                values.append("standard")
            conn.execute(
                f"INSERT INTO purchase_order_items ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                values,
            )
            conn.execute(
                """
                INSERT INTO purchase_order_nonconformities (
                    site_key,
                    module,
                    purchase_order_id,
                    purchase_order_line_id,
                    receipt_id,
                    status,
                    reason,
                    note,
                    requested_replacement,
                    created_by,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(site_key, receipt_id, purchase_order_line_id) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    note = excluded.note,
                    requested_replacement = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_site_key,
                    "clothing",
                    order_id,
                    line_id,
                    receipt_row["id"],
                    "replacement_requested",
                    reason,
                    line_note,
                    requested_by,
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        can_send = False
        if supplier_id is not None:
            supplier = resolve_supplier_for_order(conn, normalized_site_key, supplier_id)
            if supplier is not None:
                try:
                    require_supplier_email(supplier)
                    can_send = True
                except SupplierResolutionError:
                    can_send = False
        return models.PurchaseOrderReplacementOrderResponse(
            replacement_order_id=replacement_order_id,
            replacement_order_status="PENDING",
            can_send_to_supplier=can_send,
        )


def close_purchase_order_replacement(
    order_id: int,
    *,
    closed_by: str | None,
) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    normalized_site_key = db.get_current_site_key()
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT id, replacement_sent_at FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        nonconforme_row = conn.execute(
            """
            SELECT 1
            FROM purchase_order_receipts
            WHERE purchase_order_id = ?
              AND site_key = ?
              AND conformity_status = 'non_conforme'
            LIMIT 1
            """,
            (order_id, normalized_site_key),
        ).fetchone()
        if nonconforme_row is None:
            raise ValueError("Aucune non-conformité en cours")
        has_replacement_request = False
        if _table_exists(conn, "purchase_order_nonconformities") and _table_has_column(
            conn, "purchase_order_nonconformities", "requested_replacement"
        ):
            requested_row = conn.execute(
                """
                SELECT 1
                FROM purchase_order_nonconformities
                WHERE purchase_order_id = ?
                  AND site_key = ?
                  AND requested_replacement = 1
                LIMIT 1
                """,
                (order_id, normalized_site_key),
            ).fetchone()
            has_replacement_request = requested_row is not None
        replacement_order_row = conn.execute(
            """
            SELECT 1
            FROM purchase_orders
            WHERE parent_id = ? AND kind = 'replacement_request'
            LIMIT 1
            """,
            (order_id,),
        ).fetchone()
        has_replacement_request = has_replacement_request or replacement_order_row is not None
        if not has_replacement_request:
            raise ValueError("Aucune demande de remplacement en cours")
        replacement_sent_at = _row_get(order_row, "replacement_sent_at")
        if not replacement_sent_at:
            sent_row = conn.execute(
                """
                SELECT last_sent_at
                FROM purchase_orders
                WHERE parent_id = ?
                  AND kind = 'replacement_request'
                  AND last_sent_at IS NOT NULL
                ORDER BY last_sent_at DESC, id DESC
                LIMIT 1
                """,
                (order_id,),
            ).fetchone()
            if sent_row is None:
                raise ValueError(
                    "La demande de remplacement doit être envoyée avant de pouvoir la clôturer"
                )
            replacement_sent_at = sent_row["last_sent_at"]
            conn.execute(
                "UPDATE purchase_orders SET replacement_sent_at = ? WHERE id = ?",
                (replacement_sent_at, order_id),
            )
        conn.execute(
            """
            UPDATE purchase_orders
            SET replacement_closed_at = CURRENT_TIMESTAMP,
                replacement_closed_by = ?
            WHERE id = ?
            """,
            (closed_by, order_id),
        )
        conn.commit()
    return get_purchase_order(order_id)


def finalize_purchase_order_nonconformity(
    order_id: int,
    *,
    finalized_by: str | None,
) -> models.PurchaseOrderDetail:
    ensure_database_ready()
    normalized_site_key = db.get_current_site_key()
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT id, note FROM purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        nonconforming_rows = conn.execute(
            """
            SELECT purchase_order_line_id,
                   COALESCE(SUM(received_qty), 0) AS total_non_conforme
            FROM purchase_order_receipts
            WHERE purchase_order_id = ?
              AND site_key = ?
              AND conformity_status = 'non_conforme'
            GROUP BY purchase_order_line_id
            """,
            (order_id, normalized_site_key),
        ).fetchall()
        if not nonconforming_rows:
            raise ValueError("Aucune ligne non conforme à finaliser")
        replacement_rows = conn.execute(
            """
            SELECT id, last_sent_at
            FROM purchase_orders
            WHERE parent_id = ? AND kind = 'replacement_request'
            ORDER BY created_at DESC, id DESC
            """,
            (order_id,),
        ).fetchall()
        if not replacement_rows:
            raise ValueError("Aucune demande de remplacement trouvée")
        sent_replacements = [
            row for row in replacement_rows if _row_get(row, "last_sent_at")
        ]
        if not sent_replacements:
            raise ValueError("La demande de remplacement doit être envoyée avant de finaliser")
        selected_replacement = max(
            sent_replacements,
            key=lambda row: _row_get(row, "last_sent_at") or "",
        )
        order_note = _row_get(order_row, "note")
        final_note = _truncate_note(
            _append_note(
                order_note,
                f"Finalisé conforme suite remplacement BC #{selected_replacement['id']}",
            )
        )
        receipt_targets: list[tuple[int, int]] = []
        for row in nonconforming_rows:
            line_id = row["purchase_order_line_id"]
            total_non_conforme = int(row["total_non_conforme"] or 0)
            if total_non_conforme <= 0:
                continue
            line_row = conn.execute(
                """
                SELECT id, quantity_ordered, quantity_received
                FROM purchase_order_items
                WHERE id = ? AND purchase_order_id = ?
                """,
                (line_id, order_id),
            ).fetchone()
            if line_row is None:
                raise ValueError("Ligne de commande introuvable")
            remaining = line_row["quantity_ordered"] - line_row["quantity_received"]
            if remaining <= 0:
                continue
            qty_to_receive = min(remaining, total_non_conforme)
            if qty_to_receive > 0:
                receipt_targets.append((line_id, qty_to_receive))
        if not receipt_targets:
            raise ValueError("Aucune quantité conforme à recevoir")
    for line_id, qty in receipt_targets:
        receive_purchase_order_line(
            order_id,
            models.PurchaseOrderReceiveLinePayload(
                purchase_order_line_id=line_id,
                received_qty=qty,
                conformity_status="conforme",
            ),
            created_by=finalized_by,
        )
    with db.get_stock_connection() as conn:
        if _table_exists(conn, "purchase_order_nonconformities"):
            conn.execute(
                """
                UPDATE purchase_order_nonconformities
                SET status = 'closed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE purchase_order_id = ? AND site_key = ? AND status != 'closed'
                """,
                (order_id, normalized_site_key),
            )
        conn.execute(
            "UPDATE purchase_orders SET note = ? WHERE id = ?",
            (final_note, order_id),
        )
        pending_rows = conn.execute(
            """
            SELECT id, purchase_order_line_id
            FROM pending_clothing_assignments
            WHERE purchase_order_id = ? AND site_key = ? AND status = 'pending'
            """,
            (order_id, normalized_site_key),
        ).fetchall()
    target_line_ids = {line_id for line_id, _ in receipt_targets}
    for pending in pending_rows:
        if pending["purchase_order_line_id"] in target_line_ids:
            validate_pending_assignment(
                order_id,
                pending["id"],
                validated_by=finalized_by,
            )
    return get_purchase_order(order_id)


def validate_pending_assignment(
    order_id: int,
    pending_id: int,
    *,
    validated_by: str | None,
) -> models.PendingClothingAssignment:
    ensure_database_ready()
    normalized_site_key = db.get_current_site_key()
    with db.get_stock_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        pending_row = conn.execute(
            """
            SELECT *
            FROM pending_clothing_assignments
            WHERE id = ? AND purchase_order_id = ? AND site_key = ?
            """,
            (pending_id, order_id, normalized_site_key),
        ).fetchone()
        if pending_row is None:
            raise ValueError("Attribution en attente introuvable")
        if pending_row["status"] == "validated":
            return models.PendingClothingAssignment(
                id=pending_row["id"],
                site_key=pending_row["site_key"],
                purchase_order_id=pending_row["purchase_order_id"],
                purchase_order_line_id=pending_row["purchase_order_line_id"],
                receipt_id=pending_row["receipt_id"],
                employee_id=pending_row["employee_id"],
                new_item_id=pending_row["new_item_id"],
                new_item_sku=_row_get(pending_row, "new_item_sku"),
                new_item_size=_row_get(pending_row, "new_item_size"),
                qty=pending_row["qty"],
                return_employee_item_id=_row_get(pending_row, "return_employee_item_id"),
                target_dotation_id=_row_get(pending_row, "target_dotation_id"),
                return_reason=_row_get(pending_row, "return_reason"),
                status=pending_row["status"],
                created_at=pending_row["created_at"],
                validated_at=_row_get(pending_row, "validated_at"),
                validated_by=_row_get(pending_row, "validated_by"),
            )
        if pending_row["status"] != "pending":
            raise ValueError("Attribution déjà traitée")
        line_row = conn.execute(
            "SELECT * FROM purchase_order_items WHERE id = ?",
            (pending_row["purchase_order_line_id"],),
        ).fetchone()
        if line_row is None:
            raise ValueError("Ligne de commande introuvable")
        last_receipt = conn.execute(
            """
            SELECT conformity_status
            FROM purchase_order_receipts
            WHERE purchase_order_id = ? AND purchase_order_line_id = ? AND site_key = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (order_id, pending_row["purchase_order_line_id"], normalized_site_key),
        ).fetchone()
        if last_receipt and last_receipt["conformity_status"] == "non_conforme":
            raise PendingAssignmentConflictError(
                "Réception non conforme : attribution impossible tant qu’une réception conforme n’a pas été enregistrée."
            )
        conforming_total = conn.execute(
            """
            SELECT COALESCE(SUM(received_qty), 0) AS total
            FROM purchase_order_receipts
            WHERE purchase_order_id = ?
              AND purchase_order_line_id = ?
              AND site_key = ?
              AND conformity_status = 'conforme'
            """,
            (order_id, pending_row["purchase_order_line_id"], normalized_site_key),
        ).fetchone()
        if conforming_total and conforming_total["total"] < pending_row["qty"]:
            raise PendingAssignmentConflictError(
                "Quantité reçue conforme insuffisante pour l'attribution."
            )
        target_dotation_id = _row_get(pending_row, "target_dotation_id") or _row_get(
            pending_row, "return_employee_item_id"
        )
        if not target_dotation_id:
            raise PendingAssignmentConflictError(
                "Remplacement : sélectionnez l’article en PERTE/DÉGRADATION à corriger."
            )
        dotation_row = conn.execute(
            "SELECT * FROM dotations WHERE id = ?",
            (target_dotation_id,),
        ).fetchone()
        if dotation_row is None:
            raise PendingAssignmentConflictError("Article attribué introuvable")
        if dotation_row["collaborator_id"] != pending_row["employee_id"]:
            raise PendingAssignmentConflictError(
                "L'article retourné n'appartient pas au collaborateur"
            )
        degraded_qty = int(_row_get(dotation_row, "degraded_qty", 0) or 0)
        lost_qty = int(_row_get(dotation_row, "lost_qty", 0) or 0)
        if not (lost_qty or degraded_qty):
            raise PendingAssignmentConflictError(
                "Remplacement : la dotation ciblée doit être en PERTE ou DÉGRADATION."
            )
        return_expected = bool(_row_get(line_row, "return_expected", 1))
        lost_offset_qty = 0
        if lost_qty:
            return_expected = False
            lost_offset_qty = min(pending_row["qty"], lost_qty)
        return_qty = _row_get(line_row, "return_qty", pending_row["qty"])
        if return_expected:
            if return_qty <= 0:
                return_qty = pending_row["qty"]
            if degraded_qty < return_qty:
                raise PendingAssignmentConflictError(
                    "Quantité retour > quantité dégradée à remplacer"
                )
            if dotation_row["quantity"] < return_qty:
                raise PendingAssignmentConflictError(
                    "Quantité à retirer > quantité attribuée"
                )
        else:
            return_qty = 0
        item_row = conn.execute(
            "SELECT id, name, sku, size, quantity FROM items WHERE id = ?",
            (pending_row["new_item_id"],),
        ).fetchone()
        if item_row is None:
            raise ValueError("Article introuvable")
        if item_row["quantity"] < pending_row["qty"]:
            raise ValueError("Stock insuffisant pour la dotation")
        received_qty = pending_row["qty"]
        same_item = pending_row["new_item_id"] == dotation_row["item_id"]
        returned_item_row = conn.execute(
            "SELECT name, sku, size FROM items WHERE id = ?",
            (dotation_row["item_id"],),
        ).fetchone()
        return_reason = _row_get(line_row, "return_reason")
        occurred_at = datetime.now()
        replacement_line_old = _format_dotation_replacement_line(
            order_id=order_id,
            item_name=returned_item_row["name"],
            sku=_row_get(returned_item_row, "sku"),
            size=_row_get(returned_item_row, "size"),
            quantity=received_qty,
            reason=return_reason,
            occurred_at=occurred_at,
        )
        replacement_line_new = _format_dotation_replacement_line(
            order_id=order_id,
            item_name=item_row["name"],
            sku=_row_get(item_row, "sku"),
            size=_row_get(item_row, "size"),
            quantity=received_qty,
            reason=return_reason,
            occurred_at=occurred_at,
        )
        if same_item:
            adjusted_return_qty = return_qty if return_expected else lost_offset_qty
            new_quantity = dotation_row["quantity"] + received_qty - adjusted_return_qty
            new_degraded_qty = (
                max(0, degraded_qty - return_qty) if return_expected else degraded_qty
            )
            new_lost_qty = max(0, lost_qty - lost_offset_qty)
            is_lost, is_degraded = _derive_dotation_flags(new_degraded_qty, new_lost_qty)
            combined_notes = _append_dotation_note(dotation_row["notes"], replacement_line_old)
            conn.execute(
                """
                UPDATE dotations
                SET quantity = ?,
                    degraded_qty = ?,
                    lost_qty = ?,
                    is_lost = ?,
                    is_degraded = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    new_quantity,
                    new_degraded_qty,
                    new_lost_qty,
                    is_lost,
                    is_degraded,
                    combined_notes,
                    target_dotation_id,
                ),
            )
            _record_dotation_event(
                conn,
                dotation_id=target_dotation_id,
                event_type="replacement",
                message=replacement_line_old,
                order_id=order_id,
                item_id=dotation_row["item_id"],
                item_name=returned_item_row["name"],
                sku=_row_get(returned_item_row, "sku"),
                size=_row_get(returned_item_row, "size"),
                quantity=received_qty,
                reason=return_reason,
                occurred_at=occurred_at,
            )
        else:
            if return_expected:
                new_quantity = dotation_row["quantity"] - return_qty
                new_degraded_qty = max(0, degraded_qty - return_qty)
                new_lost_qty = lost_qty
                is_lost, is_degraded = _derive_dotation_flags(new_degraded_qty, new_lost_qty)
                updated_notes = _append_dotation_note(dotation_row["notes"], replacement_line_old)
                conn.execute(
                    """
                    UPDATE dotations
                    SET quantity = ?,
                        degraded_qty = ?,
                        lost_qty = ?,
                        is_lost = ?,
                        is_degraded = ?,
                        notes = ?
                    WHERE id = ?
                    """,
                    (
                        new_quantity,
                        new_degraded_qty,
                        new_lost_qty,
                        is_lost,
                        is_degraded,
                        updated_notes,
                        target_dotation_id,
                    ),
                )
                if new_quantity <= 0 and new_lost_qty == 0 and new_degraded_qty == 0:
                    conn.execute("DELETE FROM dotations WHERE id = ?", (target_dotation_id,))
            else:
                updated_notes = _append_dotation_note(dotation_row["notes"], replacement_line_old)
                conn.execute(
                    """
                    UPDATE dotations
                    SET lost_qty = ?,
                        is_lost = ?,
                        is_degraded = ?,
                        notes = ?
                    WHERE id = ?
                    """,
                    (
                        new_lost_qty,
                        is_lost,
                        is_degraded,
                        updated_notes,
                        target_dotation_id,
                    ),
                )
            _record_dotation_event(
                conn,
                dotation_id=target_dotation_id,
                event_type="replacement",
                message=replacement_line_old,
                order_id=order_id,
                item_id=dotation_row["item_id"],
                item_name=returned_item_row["name"],
                sku=_row_get(returned_item_row, "sku"),
                size=_row_get(returned_item_row, "size"),
                quantity=received_qty,
                reason=return_reason,
                occurred_at=occurred_at,
            )
            existing_new = conn.execute(
                """
                SELECT id, notes
                FROM dotations
                WHERE collaborator_id = ? AND item_id = ?
                """,
                (dotation_row["collaborator_id"], pending_row["new_item_id"]),
            ).fetchone()
            if existing_new is None:
                cur_new = conn.execute(
                    """
                    INSERT INTO dotations (
                        collaborator_id,
                        item_id,
                        quantity,
                        notes,
                        perceived_at,
                        is_lost,
                        is_degraded,
                        degraded_qty,
                        lost_qty
                    ) VALUES (?, ?, ?, ?, DATE('now'), 0, 0, 0, 0)
                    """,
                    (
                        dotation_row["collaborator_id"],
                        pending_row["new_item_id"],
                        received_qty,
                        replacement_line_new,
                    ),
                )
                new_dotation_id = cur_new.lastrowid
            else:
                updated_note = _append_dotation_note(existing_new["notes"], replacement_line_new)
                conn.execute(
                    """
                    UPDATE dotations
                    SET quantity = quantity + ?,
                        notes = ?
                    WHERE id = ?
                    """,
                    (received_qty, updated_note, existing_new["id"]),
                )
                new_dotation_id = existing_new["id"]
            _record_dotation_event(
                conn,
                dotation_id=new_dotation_id,
                event_type="replacement",
                message=replacement_line_new,
                order_id=order_id,
                item_id=item_row["id"],
                item_name=item_row["name"],
                sku=_row_get(item_row, "sku"),
                size=_row_get(item_row, "size"),
                quantity=received_qty,
                reason=return_reason,
                occurred_at=occurred_at,
            )
        conn.execute(
            "UPDATE items SET quantity = quantity - ? WHERE id = ?",
            (pending_row["qty"], pending_row["new_item_id"]),
        )
        conn.execute(
            "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
            (pending_row["new_item_id"], -pending_row["qty"], "DOTATION_ASSIGNMENT"),
        )
        if return_expected:
            conn.execute(
                "UPDATE items SET quantity = quantity + ? WHERE id = ?",
                (return_qty, dotation_row["item_id"]),
            )
            conn.execute(
                "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                (dotation_row["item_id"], return_qty, "RETURN_FROM_EMPLOYEE"),
            )
            conn.execute(
                "UPDATE items SET quantity = quantity - ? WHERE id = ?",
                (return_qty, dotation_row["item_id"]),
            )
            conn.execute(
                "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                (dotation_row["item_id"], -return_qty, "RETURN_TO_SUPPLIER"),
            )
            conn.execute(
                """
                INSERT INTO clothing_supplier_returns (
                    site_key,
                    purchase_order_id,
                    purchase_order_line_id,
                    employee_id,
                    employee_item_id,
                    item_id,
                    qty,
                    reason,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_site_key,
                    order_id,
                    pending_row["purchase_order_line_id"],
                    pending_row["employee_id"],
                    target_dotation_id,
                    dotation_row["item_id"],
                    return_qty,
                    _row_get(line_row, "return_reason"),
                    "shipped",
                ),
            )
            if _table_has_column(conn, "purchase_order_items", "return_status"):
                conn.execute(
                    "UPDATE purchase_order_items SET return_status = ? WHERE id = ?",
                    ("shipped", pending_row["purchase_order_line_id"]),
                )
        conn.execute(
            """
            UPDATE pending_clothing_assignments
            SET status = 'validated',
                validated_at = CURRENT_TIMESTAMP,
                validated_by = ?
            WHERE id = ?
            """,
            (validated_by, pending_id),
        )
        _persist_after_commit(conn, "default")
        updated = conn.execute(
            "SELECT * FROM pending_clothing_assignments WHERE id = ?",
            (pending_id,),
        ).fetchone()
        if updated is None:
            raise ValueError("Attribution en attente introuvable")
        return models.PendingClothingAssignment(
            id=updated["id"],
            site_key=updated["site_key"],
            purchase_order_id=updated["purchase_order_id"],
            purchase_order_line_id=updated["purchase_order_line_id"],
            receipt_id=updated["receipt_id"],
            employee_id=updated["employee_id"],
            new_item_id=updated["new_item_id"],
            new_item_sku=_row_get(updated, "new_item_sku"),
            new_item_size=_row_get(updated, "new_item_size"),
            qty=updated["qty"],
            return_employee_item_id=_row_get(updated, "return_employee_item_id"),
            target_dotation_id=_row_get(updated, "target_dotation_id"),
            return_reason=_row_get(updated, "return_reason"),
            status=updated["status"],
            created_at=updated["created_at"],
            validated_at=_row_get(updated, "validated_at"),
            validated_by=_row_get(updated, "validated_by"),
        )


def register_clothing_supplier_return(
    order_id: int,
    payload: models.RegisterClothingSupplierReturnPayload,
) -> models.ClothingSupplierReturn:
    ensure_database_ready()
    normalized_site_key = db.get_current_site_key()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO clothing_supplier_returns (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                employee_id,
                employee_item_id,
                item_id,
                qty,
                reason,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_site_key,
                order_id,
                payload.purchase_order_line_id,
                payload.employee_id,
                payload.employee_item_id,
                payload.item_id,
                payload.qty,
                payload.reason,
                payload.status,
            ),
        )
        if payload.item_id and payload.status in {"shipped", "supplier_received"}:
            conn.execute(
                "UPDATE items SET quantity = quantity - ? WHERE id = ?",
                (payload.qty, payload.item_id),
            )
            conn.execute(
                "INSERT INTO movements (item_id, delta, reason) VALUES (?, ?, ?)",
                (payload.item_id, -payload.qty, "RETURN_TO_SUPPLIER"),
            )
        _persist_after_commit(conn, "default")
        row = conn.execute(
            "SELECT * FROM clothing_supplier_returns WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        if row is None:
            raise ValueError("Retour fournisseur introuvable")
        return models.ClothingSupplierReturn(
            id=row["id"],
            site_key=row["site_key"],
            purchase_order_id=row["purchase_order_id"],
            purchase_order_line_id=_row_get(row, "purchase_order_line_id"),
            employee_id=_row_get(row, "employee_id"),
            employee_item_id=_row_get(row, "employee_item_id"),
            item_id=_row_get(row, "item_id"),
            qty=row["qty"],
            reason=_row_get(row, "reason"),
            status=row["status"],
            created_at=row["created_at"],
        )


def _build_remise_purchase_order_detail(
    conn: sqlite3.Connection,
    order_row: sqlite3.Row,
    *,
    site_key: str | None = None,
    suppliers_map: dict[int, models.Supplier] | None = None,
) -> models.RemisePurchaseOrderDetail:
    has_line_sku = _table_has_column(conn, "remise_purchase_order_items", "sku")
    has_line_unit = _table_has_column(conn, "remise_purchase_order_items", "unit")
    sku_expr = "ri.sku AS sku"
    unit_expr = "COALESCE(NULLIF(TRIM(ri.size), ''), 'Unité') AS unit"
    if has_line_sku:
        sku_expr = "COALESCE(NULLIF(TRIM(rpoi.sku), ''), ri.sku) AS sku"
    if has_line_unit:
        unit_expr = "COALESCE(NULLIF(TRIM(rpoi.unit), ''), NULLIF(TRIM(ri.size), ''), 'Unité') AS unit"
    items_cur = conn.execute(
        f"""
        SELECT rpoi.id,
               rpoi.purchase_order_id,
               rpoi.remise_item_id,
               rpoi.quantity_ordered,
               rpoi.quantity_received,
               ri.name AS item_name,
               {sku_expr},
               {unit_expr}
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
            sku=_row_get(item_row, "sku"),
            unit=_row_get(item_row, "unit"),
        )
        for item_row in items_cur.fetchall()
    ]
    supplier_email = None
    resolved_email = None
    supplier_has_email = False
    supplier_missing_reason = None
    supplier_missing = False
    supplier_id = _row_get(order_row, "supplier_id")
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
        is_archived=bool(_row_get(order_row, "is_archived", 0)),
        archived_at=_row_get(order_row, "archived_at"),
        archived_by=_row_get(order_row, "archived_by"),
        items=items,
    )


def list_remise_purchase_orders(
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[models.RemisePurchaseOrderDetail]:
    ensure_database_ready()
    where_clause = ""
    params: tuple[object, ...] = ()
    if archived_only:
        where_clause = "WHERE COALESCE(po.is_archived, 0) = 1"
    elif not include_archived:
        where_clause = "WHERE COALESCE(po.is_archived, 0) = 0"
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"""
            SELECT po.*, s.name AS supplier_name
            FROM remise_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            {where_clause}
            ORDER BY po.created_at DESC, po.id DESC
            """,
            params,
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
                    name=_row_get(supplier_row, "name", ""),
                    contact_name=_row_get(supplier_row, "contact_name"),
                    phone=_row_get(supplier_row, "phone"),
                    email=_row_get(supplier_row, "email"),
                    address=_row_get(supplier_row, "address"),
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
                        name=_row_get(supplier_row, "name", ""),
                        contact_name=_row_get(supplier_row, "contact_name"),
                        phone=_row_get(supplier_row, "phone"),
                        email=_row_get(supplier_row, "email"),
                        address=_row_get(supplier_row, "address"),
                        modules=modules_map.get(supplier_row["id"]) or ["suppliers"],
                    )
                }
        return _build_remise_purchase_order_detail(
            conn,
            row,
            site_key=db.get_current_site_key(),
            suppliers_map=suppliers_map,
        )


def archive_remise_purchase_order(
    order_id: int,
    *,
    archived_by: int | None = None,
) -> models.RemisePurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT status, is_archived FROM remise_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        if _row_get(row, "is_archived"):
            return get_remise_purchase_order(order_id)
        _assert_purchase_order_archivable(row["status"])
        conn.execute(
            """
            UPDATE remise_purchase_orders
            SET is_archived = 1,
                archived_at = CURRENT_TIMESTAMP,
                archived_by = ?
            WHERE id = ?
            """,
            (archived_by, order_id),
        )
    return get_remise_purchase_order(order_id)


def unarchive_remise_purchase_order(
    order_id: int,
) -> models.RemisePurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM remise_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande introuvable")
        conn.execute(
            """
            UPDATE remise_purchase_orders
            SET is_archived = 0,
                archived_at = NULL,
                archived_by = NULL
            WHERE id = ?
            """,
            (order_id,),
        )
    return get_remise_purchase_order(order_id)


def create_remise_purchase_order(
    payload: models.RemisePurchaseOrderCreate,
    *,
    idempotency_key: str | None = None,
) -> models.RemisePurchaseOrderDetail:
    ensure_database_ready()
    status = _normalize_purchase_order_status(payload.status)
    if payload.supplier_id is None:
        raise ValueError("Fournisseur obligatoire")
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
        has_idempotency_key = _table_has_column(
            conn, "remise_purchase_orders", "idempotency_key"
        )
        effective_idempotency_key = idempotency_key if has_idempotency_key else None
        if effective_idempotency_key:
            existing = conn.execute(
                """
                SELECT id
                FROM remise_purchase_orders
                WHERE idempotency_key = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (effective_idempotency_key,),
            ).fetchone()
            if existing is not None:
                logger.info(
                    "[Remise PO] duplicate create detected idempotency_key=%s order_id=%s",
                    effective_idempotency_key,
                    existing["id"],
                )
                return get_remise_purchase_order(existing["id"])
        try:
            if has_idempotency_key:
                cur = conn.execute(
                    """
                    INSERT INTO remise_purchase_orders (
                        supplier_id,
                        status,
                        note,
                        auto_created,
                        idempotency_key
                    )
                    VALUES (?, ?, ?, 0, ?)
                    """,
                    (payload.supplier_id, status, payload.note, effective_idempotency_key),
                )
            else:
                cur = conn.execute(
                    """
                    INSERT INTO remise_purchase_orders (supplier_id, status, note, auto_created)
                    VALUES (?, ?, ?, 0)
                    """,
                    (payload.supplier_id, status, payload.note),
                )
            order_id = cur.lastrowid
            has_line_sku = _table_has_column(conn, "remise_purchase_order_items", "sku")
            has_line_unit = _table_has_column(conn, "remise_purchase_order_items", "unit")
            for remise_item_id, quantity in aggregated.items():
                item_row = conn.execute(
                    "SELECT sku, size FROM remise_items WHERE id = ?", (remise_item_id,)
                ).fetchone()
                if item_row is None:
                    raise ValueError("Article introuvable")
                columns = [
                    "purchase_order_id",
                    "remise_item_id",
                    "quantity_ordered",
                    "quantity_received",
                ]
                values: list[object] = [order_id, remise_item_id, quantity, 0]
                if has_line_sku:
                    columns.append("sku")
                    values.append(item_row["sku"])
                if has_line_unit:
                    columns.append("unit")
                    values.append(item_row["size"] if item_row["size"] else None)
                conn.execute(
                    f"INSERT INTO remise_purchase_order_items ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )
            conn.commit()
        except sqlite3.IntegrityError:
            if has_idempotency_key and effective_idempotency_key:
                existing = conn.execute(
                    """
                    SELECT id
                    FROM remise_purchase_orders
                    WHERE idempotency_key = ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (effective_idempotency_key,),
                ).fetchone()
                if existing is not None:
                    conn.rollback()
                    logger.info(
                        "[Remise PO] idempotency conflict resolved idempotency_key=%s order_id=%s",
                        effective_idempotency_key,
                        existing["id"],
                    )
                    return get_remise_purchase_order(existing["id"])
            conn.rollback()
            raise
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
    line_increments: dict[int, int] = {}
    item_increments: dict[int, int] = {}
    if payload.lines:
        line_increments = _aggregate_positive_quantities(
            (line.line_id, line.qty) for line in payload.lines
        )
    elif payload.items:
        item_increments = _aggregate_positive_quantities(
            (line.remise_item_id, line.quantity) for line in payload.items
        )
    if not line_increments and not item_increments:
        raise ValueError("Aucune ligne de réception valide")
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT status FROM remise_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande introuvable")
        if order_row["status"] == "CANCELLED":
            raise ValueError("Bon de commande annulé")
        try:
            if line_increments:
                for line_id, increment in line_increments.items():
                    line = conn.execute(
                        """
                        SELECT id, remise_item_id, quantity_ordered, quantity_received
                        FROM remise_purchase_order_items
                        WHERE purchase_order_id = ? AND id = ?
                        """,
                        (order_id, line_id),
                    ).fetchone()
                    if line is None:
                        raise ValueError("Ligne de commande introuvable")
                    remaining = line["quantity_ordered"] - line["quantity_received"]
                    if increment > remaining:
                        raise ValueError("Quantité reçue supérieure au restant")
                    if increment <= 0:
                        continue
                    new_received = line["quantity_received"] + increment
                    conn.execute(
                        "UPDATE remise_purchase_order_items SET quantity_received = ? WHERE id = ?",
                        (new_received, line["id"]),
                    )
                    conn.execute(
                        "UPDATE remise_items SET quantity = quantity + ? WHERE id = ?",
                        (increment, line["remise_item_id"]),
                    )
                    conn.execute(
                        "INSERT INTO remise_movements (item_id, delta, reason) VALUES (?, ?, ?)",
                        (
                            line["remise_item_id"],
                            increment,
                            f"Réception bon de commande remise #{order_id}"
                        ),
                    )
                    _maybe_create_auto_purchase_order(
                        conn, "inventory_remise", line["remise_item_id"]
                    )
            else:
                for remise_item_id, increment in item_increments.items():
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
                    if increment > remaining:
                        raise ValueError("Quantité reçue supérieure au restant")
                    if increment <= 0:
                        continue
                    new_received = line["quantity_received"] + increment
                    conn.execute(
                        "UPDATE remise_purchase_order_items SET quantity_received = ? WHERE id = ?",
                        (new_received, line["id"]),
                    )
                    conn.execute(
                        "UPDATE remise_items SET quantity = quantity + ? WHERE id = ?",
                        (increment, remise_item_id),
                    )
                    conn.execute(
                        "INSERT INTO remise_movements (item_id, delta, reason) VALUES (?, ?, ?)",
                        (remise_item_id, increment, f"Réception bon de commande remise #{order_id}"),
                    )
                    _maybe_create_auto_purchase_order(
                        conn, "inventory_remise", remise_item_id
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


def get_reports_overview(
    module: str,
    *,
    start: date,
    end: date,
    bucket: str | None = None,
    include_dotation: bool = True,
    include_adjustment: bool = True,
) -> models.ReportOverview:
    ensure_database_ready()
    normalized_module = (module or "").strip().lower()
    resolved = _resolve_report_module(normalized_module)
    start_date = _ensure_date(start)
    end_date = _ensure_date(end)
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    selected_bucket = bucket or _auto_report_bucket(start_date, end_date)
    if selected_bucket not in {"day", "week", "month"}:
        raise ValueError("Granularité invalide")

    bucket_dates = _iter_report_buckets(start_date, end_date, selected_bucket)
    bucket_keys = [entry.isoformat() for entry in bucket_dates]
    empty_moves = [
        models.ReportMoveSeriesPoint(t=key, **{"in": 0, "out": 0}) for key in bucket_keys
    ]
    empty_net = [models.ReportNetSeriesPoint(t=key, net=0) for key in bucket_keys]
    empty_low_stock = [
        models.ReportLowStockSeriesPoint(t=key, count=0) for key in bucket_keys
    ]
    empty_orders = [
        models.ReportOrderSeriesPoint(
            t=key, created=0, ordered=0, partial=0, received=0, cancelled=0
        )
        for key in bucket_keys
    ]

    if not resolved or not resolved.items_table or not resolved.movements_table:
        return models.ReportOverview(
            module=normalized_module or module,
            range=models.ReportRange(
                start=start_date.isoformat(),
                end=end_date.isoformat(),
                bucket=selected_bucket,
            ),
            kpis=models.ReportKpis(),
            series=models.ReportSeries(
                moves=empty_moves, net=empty_net, low_stock=empty_low_stock, orders=empty_orders
            ),
            tops=models.ReportTops(),
            data_quality=models.ReportDataQuality(),
        )

    with db.get_stock_connection() as conn:
        if not _table_exists(conn, resolved.items_table) or not _table_exists(
            conn, resolved.movements_table
        ):
            return models.ReportOverview(
                module=normalized_module or module,
                range=models.ReportRange(
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    bucket=selected_bucket,
                ),
                kpis=models.ReportKpis(),
                series=models.ReportSeries(
                    moves=empty_moves,
                    net=empty_net,
                    low_stock=empty_low_stock,
                    orders=empty_orders,
                ),
                tops=models.ReportTops(),
                data_quality=models.ReportDataQuality(),
            )

        movement_reason_filter = ""
        if _table_has_column(conn, resolved.movements_table, "reason"):
            clauses: list[str] = []
            if not include_dotation:
                clauses.append("(reason IS NULL OR lower(reason) NOT LIKE '%dotation%')")
            if not include_adjustment:
                clauses.append("(reason IS NULL OR lower(reason) NOT LIKE '%ajust%')")
            if clauses:
                movement_reason_filter = " AND " + " AND ".join(clauses)

        movement_where = (
            "date(created_at) BETWEEN ? AND ?" + movement_reason_filter
        )
        totals = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END), 0) AS in_qty,
                COALESCE(SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END), 0) AS out_qty
            FROM {resolved.movements_table}
            WHERE {movement_where}
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchone()
        in_qty = int(totals["in_qty"] or 0)
        out_qty = int(totals["out_qty"] or 0)
        net_qty = in_qty - out_qty

        moves_by_bucket: dict[str, dict[str, int]] = {
            key: {"in": 0, "out": 0, "net": 0} for key in bucket_keys
        }
        rows = conn.execute(
            f"""
            SELECT created_at, delta, reason
            FROM {resolved.movements_table}
            WHERE date(created_at) BETWEEN ? AND ?
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        for row in rows:
            reason = row["reason"] if "reason" in row.keys() else None
            if not _should_include_reason(
                reason, include_dotation=include_dotation, include_adjustment=include_adjustment
            ):
                continue
            created_at = _coerce_datetime(row["created_at"])
            bucket_key = _bucket_key(created_at, selected_bucket)
            if bucket_key not in moves_by_bucket:
                moves_by_bucket[bucket_key] = {"in": 0, "out": 0, "net": 0}
            delta = int(row["delta"] or 0)
            if delta > 0:
                moves_by_bucket[bucket_key]["in"] += delta
            elif delta < 0:
                moves_by_bucket[bucket_key]["out"] += abs(delta)
            moves_by_bucket[bucket_key]["net"] += delta

        ordered_move_keys = sorted(moves_by_bucket.keys())
        moves_series = [
            models.ReportMoveSeriesPoint(
                t=key, **{"in": moves_by_bucket[key]["in"], "out": moves_by_bucket[key]["out"]}
            )
            for key in ordered_move_keys
        ]
        net_series = [
            models.ReportNetSeriesPoint(t=key, net=moves_by_bucket[key]["net"])
            for key in ordered_move_keys
        ]

        item_columns = {
            row["name"]
            for row in conn.execute(f"PRAGMA table_info({resolved.items_table})").fetchall()
        }
        sku_column = "sku" if "sku" in item_columns else "barcode" if "barcode" in item_columns else None
        name_column = "name" if "name" in item_columns else None
        sku_select = sku_column if sku_column else "''"
        name_select = name_column if name_column else "''"

        top_out_rows = conn.execute(
            f"""
            SELECT {name_select} AS name, {sku_select} AS sku,
                   SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END) AS qty
            FROM {resolved.movements_table} AS m
            JOIN {resolved.items_table} AS i
              ON i.id = m.{resolved.movement_item_column}
            WHERE {movement_where} AND delta < 0
            GROUP BY i.id, name, sku
            ORDER BY qty DESC
            LIMIT 5
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        top_in_rows = conn.execute(
            f"""
            SELECT {name_select} AS name, {sku_select} AS sku,
                   SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS qty
            FROM {resolved.movements_table} AS m
            JOIN {resolved.items_table} AS i
              ON i.id = m.{resolved.movement_item_column}
            WHERE {movement_where} AND delta > 0
            GROUP BY i.id, name, sku
            ORDER BY qty DESC
            LIMIT 5
            """,
            (start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
        top_out = [
            models.ReportTopItem(
                sku=str(row["sku"] or ""),
                name=str(row["name"] or ""),
                qty=int(row["qty"] or 0),
            )
            for row in top_out_rows
        ]
        top_in = [
            models.ReportTopItem(
                sku=str(row["sku"] or ""),
                name=str(row["name"] or ""),
                qty=int(row["qty"] or 0),
            )
            for row in top_in_rows
        ]

        low_stock_count = 0
        if "low_stock_threshold" in item_columns:
            low_stock_where = ["quantity < low_stock_threshold", "low_stock_threshold > 0"]
            if "track_low_stock" in item_columns:
                low_stock_where.append("track_low_stock = 1")
            low_stock_count = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.items_table}
                    WHERE {" AND ".join(low_stock_where)}
                    """
                ).fetchone()["count"]
                or 0
            )
        low_stock_series = [
            models.ReportLowStockSeriesPoint(t=key, count=low_stock_count)
            for key in bucket_keys
        ]

        orders_series = list(empty_orders)
        open_orders = 0
        if resolved.orders_table and _table_exists(conn, resolved.orders_table):
            open_orders = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.orders_table}
                    WHERE status IN ('PENDING', 'ORDERED', 'PARTIALLY_RECEIVED')
                    """
                ).fetchone()["count"]
                or 0
            )
            orders_map: dict[str, models.ReportOrderSeriesPoint] = {
                key: models.ReportOrderSeriesPoint(
                    t=key, created=0, ordered=0, partial=0, received=0, cancelled=0
                )
                for key in bucket_keys
            }
            order_rows = conn.execute(
                f"""
                SELECT created_at, status
                FROM {resolved.orders_table}
                WHERE date(created_at) BETWEEN ? AND ?
                """,
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
            for row in order_rows:
                created_at = _coerce_datetime(row["created_at"])
                bucket_key = _bucket_key(created_at, selected_bucket)
                if bucket_key not in orders_map:
                    orders_map[bucket_key] = models.ReportOrderSeriesPoint(
                        t=bucket_key, created=0, ordered=0, partial=0, received=0, cancelled=0
                    )
                target = orders_map[bucket_key]
                target.created += 1
                status = str(row["status"] or "").upper()
                if status in {"PENDING", "ORDERED"}:
                    target.ordered += 1
                elif status == "PARTIALLY_RECEIVED":
                    target.partial += 1
                elif status == "RECEIVED":
                    target.received += 1
                elif status == "CANCELLED":
                    target.cancelled += 1
                else:
                    target.ordered += 1
            ordered_order_keys = sorted(orders_map.keys())
            orders_series = [orders_map[key] for key in ordered_order_keys]

        missing_sku = 0
        if sku_column:
            missing_sku = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.items_table}
                    WHERE {sku_column} IS NULL OR TRIM({sku_column}) = ''
                    """
                ).fetchone()["count"]
                or 0
            )
        missing_supplier = 0
        if "supplier_id" in item_columns:
            missing_supplier = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.items_table}
                    WHERE supplier_id IS NULL
                    """
                ).fetchone()["count"]
                or 0
            )
        missing_threshold = 0
        if "low_stock_threshold" in item_columns:
            threshold_where = ["low_stock_threshold IS NULL OR low_stock_threshold <= 0"]
            if "track_low_stock" in item_columns:
                threshold_where.append("track_low_stock = 1")
            missing_threshold = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.items_table}
                    WHERE {" AND ".join(threshold_where)}
                    """
                ).fetchone()["count"]
                or 0
            )

        abnormal_movements = 0
        if _table_has_column(conn, resolved.movements_table, "delta"):
            abnormal_movements = int(
                conn.execute(
                    f"""
                    SELECT COUNT(1) AS count
                    FROM {resolved.movements_table}
                    WHERE delta IS NULL OR delta = 0
                    """
                ).fetchone()["count"]
                or 0
            )

    return models.ReportOverview(
        module=normalized_module,
        range=models.ReportRange(
            start=start_date.isoformat(), end=end_date.isoformat(), bucket=selected_bucket
        ),
        kpis=models.ReportKpis(
            in_qty=in_qty,
            out_qty=out_qty,
            net_qty=net_qty,
            low_stock_count=low_stock_count,
            open_orders=open_orders,
        ),
        series=models.ReportSeries(
            moves=moves_series,
            net=net_series,
            low_stock=low_stock_series,
            orders=orders_series,
        ),
        tops=models.ReportTops(out=top_out, **{"in": top_in}),
        data_quality=models.ReportDataQuality(
            missing_sku=missing_sku,
            missing_supplier=missing_supplier,
            missing_threshold=missing_threshold,
            abnormal_movements=abnormal_movements,
        ),
    )


def purge_reports_stats(module_key: str) -> tuple[str, dict[str, int]]:
    ensure_database_ready()
    normalized_module = (module_key or "").strip().lower()
    resolved = _resolve_report_module(normalized_module)
    if not resolved:
        raise ValueError("Module introuvable")

    tables_to_purge: list[str] = []
    if resolved.movements_table:
        tables_to_purge.append(resolved.movements_table)
    if resolved.orders_table:
        tables_to_purge.extend(_REPORT_ORDER_DEPENDENCIES.get(resolved.orders_table, []))
        tables_to_purge.append(resolved.orders_table)

    deleted: dict[str, int] = {}
    seen: set[str] = set()
    with db.get_stock_connection() as conn:
        try:
            conn.execute("BEGIN")
            for table in tables_to_purge:
                if table in seen:
                    continue
                seen.add(table)
                if not _table_exists(conn, table):
                    deleted[table] = 0
                    continue
                cur = conn.execute(f"DELETE FROM {table}")
                deleted[table] = int(cur.rowcount or 0)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return resolved.module_key, deleted


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


DOTATION_NOTE_MAX_LENGTH = 256
DOTATION_NOTE_MAX_LINES = 3


def clamp_note(note: str, max_len: int = DOTATION_NOTE_MAX_LENGTH) -> str:
    if max_len <= 0:
        return ""
    cleaned = note.strip()
    if len(cleaned) <= max_len:
        return cleaned
    if max_len == 1:
        return "…"
    truncated = cleaned[: max_len - 1].rstrip()
    return f"{truncated}…"


def _append_dotation_note(existing: str | None, note: str) -> str:
    cleaned_note = note.strip()
    if not cleaned_note:
        return clamp_note(existing or "", DOTATION_NOTE_MAX_LENGTH)
    lines = []
    if existing:
        lines.extend([entry.strip() for entry in existing.splitlines() if entry.strip()])
    lines.append(cleaned_note)
    if DOTATION_NOTE_MAX_LINES:
        lines = lines[-DOTATION_NOTE_MAX_LINES :]
    combined = "\n".join(lines)
    return clamp_note(combined, DOTATION_NOTE_MAX_LENGTH)


def _format_dotation_replacement_line(
    *,
    order_id: int,
    item_name: str,
    sku: str | None,
    size: str | None,
    quantity: int,
    reason: str | None,
    occurred_at: datetime,
) -> str:
    safe_name = item_name.strip() if item_name else "—"
    safe_sku = (sku or "—").strip() or "—"
    safe_size = (size or "—").strip() or "—"
    safe_reason = (reason or "—").strip() or "—"
    timestamp = occurred_at.strftime("%d/%m %H:%M")
    line = (
        f"Remplacement BC#{order_id} | {safe_name} {safe_sku} {safe_size} | x{quantity} |"
        f" {safe_reason} | {timestamp} | Remplacé via BC"
    )
    return clamp_note(line, DOTATION_NOTE_MAX_LENGTH)


def _record_dotation_event(
    conn: sqlite3.Connection,
    *,
    dotation_id: int,
    event_type: str,
    message: str,
    order_id: int | None,
    item_id: int | None,
    item_name: str | None,
    sku: str | None,
    size: str | None,
    quantity: int | None,
    reason: str | None,
    occurred_at: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO dotation_events (
            dotation_id,
            event_type,
            order_id,
            item_id,
            item_name,
            sku,
            size,
            quantity,
            reason,
            message,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dotation_id,
            event_type,
            order_id,
            item_id,
            item_name,
            sku,
            size,
            quantity,
            reason,
            message,
            occurred_at.isoformat(),
        ),
    )


def _derive_dotation_flags(degraded_qty: int, lost_qty: int) -> tuple[int, int]:
    return (1 if lost_qty > 0 else 0, 1 if degraded_qty > 0 else 0)


def _validate_dotation_quantities(*, quantity: int, degraded_qty: int, lost_qty: int) -> None:
    if quantity <= 0:
        raise ValueError("La quantité doit être positive")
    if degraded_qty < 0 or lost_qty < 0:
        raise ValueError("Les quantités de perte/dégradation doivent être positives")
    if degraded_qty > quantity or lost_qty > quantity:
        raise ValueError("Les quantités de perte/dégradation dépassent la quantité totale")
    if degraded_qty + lost_qty > quantity:
        raise ValueError("La somme des quantités perdues et dégradées dépasse la quantité totale")


def _consolidate_dotation_rows(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "dotations"):
        return
    duplicates = conn.execute(
        """
        SELECT collaborator_id, item_id, COUNT(*) AS count
        FROM dotations
        GROUP BY collaborator_id, item_id
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    if not duplicates:
        return
    reference_columns: list[tuple[str, str]] = []
    for table, column in (
        ("purchase_order_items", "return_employee_item_id"),
        ("purchase_order_items", "target_dotation_id"),
        ("pending_clothing_assignments", "return_employee_item_id"),
        ("pending_clothing_assignments", "target_dotation_id"),
        ("clothing_supplier_returns", "employee_item_id"),
    ):
        if _table_has_column(conn, table, column):
            reference_columns.append((table, column))
    for row in duplicates:
        rows = conn.execute(
            """
            SELECT id, quantity, notes, degraded_qty, lost_qty, is_lost, is_degraded
            FROM dotations
            WHERE collaborator_id = ? AND item_id = ?
            ORDER BY id
            """,
            (row["collaborator_id"], row["item_id"]),
        ).fetchall()
        if not rows:
            continue
        keep = rows[0]
        keep_id = keep["id"]
        total_quantity = sum(int(entry["quantity"]) for entry in rows)
        total_degraded = sum(
            int(entry["degraded_qty"])
            if entry["degraded_qty"] is not None
            else (int(entry["quantity"]) if entry["is_degraded"] else 0)
            for entry in rows
        )
        total_lost = sum(
            int(entry["lost_qty"])
            if entry["lost_qty"] is not None
            else (int(entry["quantity"]) if entry["is_lost"] else 0)
            for entry in rows
        )
        note = keep["notes"]
        if not note:
            note = next((entry["notes"] for entry in rows if entry["notes"]), None)
        if note is not None:
            note = clamp_note(note, DOTATION_NOTE_MAX_LENGTH)
        is_lost, is_degraded = _derive_dotation_flags(total_degraded, total_lost)
        conn.execute(
            """
            UPDATE dotations
            SET quantity = ?,
                degraded_qty = ?,
                lost_qty = ?,
                is_lost = ?,
                is_degraded = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                total_quantity,
                total_degraded,
                total_lost,
                is_lost,
                is_degraded,
                note,
                keep_id,
            ),
        )
        for entry in rows[1:]:
            for table, column in reference_columns:
                conn.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
                    (keep_id, entry["id"]),
                )
            conn.execute("DELETE FROM dotations WHERE id = ?", (entry["id"],))


def list_dotations(
    *, collaborator_id: Optional[int] = None, item_id: Optional[int] = None
) -> list[models.Dotation]:
    ensure_database_ready()
    query = """
        SELECT
            d.*,
            i.size AS size_variant
        FROM dotations AS d
        LEFT JOIN items AS i ON i.id = d.item_id
    """
    clauses: list[str] = []
    params: list[object] = []
    if collaborator_id is not None:
        clauses.append("d.collaborator_id = ?")
        params.append(collaborator_id)
    if item_id is not None:
        clauses.append("d.item_id = ?")
        params.append(item_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY d.allocated_at DESC"
    with db.get_stock_connection() as conn:
        cur = conn.execute(query, tuple(params))
        rows = cur.fetchall()
        dotations: list[models.Dotation] = []
        for row in rows:
            allocated_at_value = row["allocated_at"]
            allocated_date = _ensure_date(allocated_at_value)
            perceived_at = _ensure_date(row["perceived_at"], fallback=allocated_date)
            degraded_qty = int(_row_get(row, "degraded_qty", 0) or 0)
            lost_qty = int(_row_get(row, "lost_qty", 0) or 0)
            notes = row["notes"]
            if notes is not None:
                notes = clamp_note(notes, DOTATION_NOTE_MAX_LENGTH)
            dotations.append(
                models.Dotation(
                    id=row["id"],
                    collaborator_id=row["collaborator_id"],
                    item_id=row["item_id"],
                    quantity=row["quantity"],
                    notes=notes,
                    perceived_at=perceived_at,
                    is_lost=lost_qty > 0,
                    is_degraded=degraded_qty > 0,
                    degraded_qty=degraded_qty,
                    lost_qty=lost_qty,
                    allocated_at=allocated_at_value,
                    is_obsolete=_is_obsolete(perceived_at),
                    size_variant=_normalize_variant_value(row["size_variant"])
                    if "size_variant" in row.keys()
                    else None,
                )
            )
        return dotations


def list_dotation_events(dotation_id: int) -> list[models.DotationEvent]:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM dotation_events
            WHERE dotation_id = ?
            ORDER BY datetime(created_at) DESC
            """,
            (dotation_id,),
        ).fetchall()
    return [
        models.DotationEvent(
            id=row["id"],
            dotation_id=row["dotation_id"],
            event_type=row["event_type"],
            order_id=row["order_id"],
            item_id=row["item_id"],
            item_name=row["item_name"],
            sku=row["sku"],
            size=row["size"],
            quantity=row["quantity"],
            reason=row["reason"],
            message=row["message"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def list_dotation_beneficiaries() -> list[models.DotationBeneficiary]:
    ensure_database_ready()
    query = """
        SELECT
            d.collaborator_id AS employee_id,
            c.full_name AS display_name,
            COUNT(*) AS assigned_count
        FROM dotations AS d
        JOIN collaborators AS c ON c.id = d.collaborator_id
        GROUP BY d.collaborator_id, c.full_name
        HAVING COUNT(*) > 0
        ORDER BY c.full_name COLLATE NOCASE
    """
    with db.get_stock_connection() as conn:
        rows = conn.execute(query).fetchall()
        return [
            models.DotationBeneficiary(
                employee_id=row["employee_id"],
                display_name=row["display_name"],
                assigned_count=row["assigned_count"],
            )
            for row in rows
        ]


def list_dotation_assignees() -> list[models.DotationAssignee]:
    ensure_database_ready()
    query = """
        SELECT
            d.collaborator_id AS employee_id,
            c.full_name AS display_name,
            COUNT(*) AS assigned_count
        FROM dotations AS d
        JOIN collaborators AS c ON c.id = d.collaborator_id
        GROUP BY d.collaborator_id, c.full_name
        HAVING COUNT(*) > 0
        ORDER BY c.full_name COLLATE NOCASE
    """
    with db.get_stock_connection() as conn:
        rows = conn.execute(query).fetchall()
        return [
            models.DotationAssignee(
                employee_id=row["employee_id"],
                display_name=row["display_name"],
                count=row["assigned_count"],
            )
            for row in rows
        ]


def list_dotation_assigned_items(employee_id: int) -> list[models.DotationAssignedItem]:
    ensure_database_ready()
    query = """
        SELECT
            d.id AS assignment_id,
            d.item_id AS item_id,
            i.sku AS sku,
            i.name AS label,
            i.size AS variant,
            d.quantity AS qty
        FROM dotations AS d
        JOIN items AS i ON i.id = d.item_id
        WHERE d.collaborator_id = ?
        ORDER BY i.name COLLATE NOCASE
    """
    with db.get_stock_connection() as conn:
        rows = conn.execute(query, (employee_id,)).fetchall()
        return [
            models.DotationAssignedItem(
                assignment_id=row["assignment_id"],
                item_id=row["item_id"],
                sku=row["sku"],
                label=row["label"],
                variant=row["variant"],
                qty=row["qty"],
            )
            for row in rows
        ]


def list_dotation_assignee_items(employee_id: int) -> list[models.DotationAssigneeItem]:
    ensure_database_ready()
    query = """
        SELECT
            d.id AS assignment_id,
            d.item_id AS item_id,
            i.sku AS sku,
            i.name AS name,
            i.size AS size_variant,
            d.quantity AS qty,
            d.degraded_qty AS degraded_qty,
            d.lost_qty AS lost_qty
        FROM dotations AS d
        JOIN items AS i ON i.id = d.item_id
        WHERE d.collaborator_id = ?
        ORDER BY i.name COLLATE NOCASE
    """
    with db.get_stock_connection() as conn:
        rows = conn.execute(query, (employee_id,)).fetchall()
        return [
            models.DotationAssigneeItem(
                assignment_id=row["assignment_id"],
                item_id=row["item_id"],
                sku=row["sku"],
                name=row["name"],
                size_variant=_normalize_variant_value(row["size_variant"]),
                qty=row["qty"],
                is_lost=bool(row["lost_qty"]),
                is_degraded=bool(row["degraded_qty"]),
                degraded_qty=int(row["degraded_qty"] or 0),
                lost_qty=int(row["lost_qty"] or 0),
            )
            for row in rows
        ]


def search_global(user: models.User, query: str) -> list[models.GlobalSearchResult]:
    ensure_database_ready()
    search = query.strip()
    if not search:
        return []
    like = f"%{search}%"
    results: list[models.GlobalSearchResult] = []

    if has_module_access(user, "purchase_orders", action="view"):
        with db.get_stock_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT po.id AS order_id,
                       po.status AS status,
                       s.name AS supplier_name
                FROM purchase_orders AS po
                LEFT JOIN suppliers AS s ON s.id = po.supplier_id
                LEFT JOIN purchase_order_items AS poi ON poi.purchase_order_id = po.id
                LEFT JOIN items AS i ON i.id = poi.item_id
                WHERE CAST(po.id AS TEXT) LIKE ?
                   OR s.name LIKE ?
                   OR i.name LIKE ?
                   OR i.sku LIKE ?
                   OR poi.sku LIKE ?
                   OR po.note LIKE ?
                ORDER BY po.created_at DESC
                LIMIT 50
                """,
                (like, like, like, like, like, like),
            ).fetchall()
        for row in rows:
            supplier_label = row["supplier_name"] or "Fournisseur inconnu"
            results.append(
                models.GlobalSearchResult(
                    result_type="BC",
                    entity_id=row["order_id"],
                    label=f"BC #{row['order_id']}",
                    description=f"{supplier_label} · {row['status']}",
                    path="/purchase-orders",
                )
            )

    if has_module_access(user, "inventory_remise", action="view"):
        with db.get_stock_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT po.id AS order_id,
                       po.status AS status,
                       s.name AS supplier_name
                FROM remise_purchase_orders AS po
                LEFT JOIN suppliers AS s ON s.id = po.supplier_id
                LEFT JOIN remise_purchase_order_items AS poi ON poi.purchase_order_id = po.id
                LEFT JOIN remise_items AS i ON i.id = poi.remise_item_id
                WHERE CAST(po.id AS TEXT) LIKE ?
                   OR s.name LIKE ?
                   OR i.name LIKE ?
                   OR i.sku LIKE ?
                   OR poi.sku LIKE ?
                   OR po.note LIKE ?
                ORDER BY po.created_at DESC
                LIMIT 50
                """,
                (like, like, like, like, like, like),
            ).fetchall()
        for row in rows:
            supplier_label = row["supplier_name"] or "Fournisseur inconnu"
            results.append(
                models.GlobalSearchResult(
                    result_type="BC",
                    entity_id=row["order_id"],
                    label=f"BC Remise #{row['order_id']}",
                    description=f"{supplier_label} · {row['status']}",
                    path="/remise-inventory",
                )
            )

    if has_module_access(user, "pharmacy", action="view"):
        with db.get_stock_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT po.id AS order_id,
                       po.status AS status,
                       s.name AS supplier_name
                FROM pharmacy_purchase_orders AS po
                LEFT JOIN suppliers AS s ON s.id = po.supplier_id
                LEFT JOIN pharmacy_purchase_order_items AS poi ON poi.purchase_order_id = po.id
                LEFT JOIN pharmacy_items AS i ON i.id = poi.pharmacy_item_id
                WHERE CAST(po.id AS TEXT) LIKE ?
                   OR s.name LIKE ?
                   OR i.name LIKE ?
                   OR i.barcode LIKE ?
                   OR po.note LIKE ?
                ORDER BY po.created_at DESC
                LIMIT 50
                """,
                (like, like, like, like, like),
            ).fetchall()
        for row in rows:
            supplier_label = row["supplier_name"] or "Fournisseur inconnu"
            results.append(
                models.GlobalSearchResult(
                    result_type="BC",
                    entity_id=row["order_id"],
                    label=f"BC Pharmacie #{row['order_id']}",
                    description=f"{supplier_label} · {row['status']}",
                    path="/pharmacy",
                )
            )

    if has_module_access(user, "dotations", action="view"):
        with db.get_stock_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT d.id AS dotation_id,
                       c.full_name AS collaborator_name,
                       i.name AS item_name,
                       i.sku AS item_sku
                FROM dotations AS d
                JOIN collaborators AS c ON c.id = d.collaborator_id
                JOIN items AS i ON i.id = d.item_id
                WHERE CAST(d.id AS TEXT) LIKE ?
                   OR c.full_name LIKE ?
                   OR i.name LIKE ?
                   OR i.sku LIKE ?
                   OR d.notes LIKE ?
                ORDER BY d.allocated_at DESC
                LIMIT 50
                """,
                (like, like, like, like, like),
            ).fetchall()
        for row in rows:
            label = row["collaborator_name"] or "Collaborateur"
            item_label = row["item_name"] or "Article"
            sku = row["item_sku"] or "SKU"
            results.append(
                models.GlobalSearchResult(
                    result_type="Dotation",
                    entity_id=row["dotation_id"],
                    label=f"Dotation #{row['dotation_id']} · {label}",
                    description=f"{item_label} ({sku})",
                    path="/dotations",
                )
            )

    return results


def get_dotation(dotation_id: int) -> models.Dotation:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                d.*,
                i.size AS size_variant
            FROM dotations AS d
            LEFT JOIN items AS i ON i.id = d.item_id
            WHERE d.id = ?
            """,
            (dotation_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError("Dotation introuvable")
        allocated_at_value = row["allocated_at"]
        allocated_date = _ensure_date(allocated_at_value)
        perceived_at = _ensure_date(row["perceived_at"], fallback=allocated_date)
        degraded_qty = int(_row_get(row, "degraded_qty", 0) or 0)
        lost_qty = int(_row_get(row, "lost_qty", 0) or 0)
        notes = row["notes"]
        if notes is not None:
            notes = clamp_note(notes, DOTATION_NOTE_MAX_LENGTH)
        return models.Dotation(
            id=row["id"],
            collaborator_id=row["collaborator_id"],
            item_id=row["item_id"],
            quantity=row["quantity"],
            notes=notes,
            perceived_at=perceived_at,
            is_lost=lost_qty > 0,
            is_degraded=degraded_qty > 0,
            degraded_qty=degraded_qty,
            lost_qty=lost_qty,
            allocated_at=allocated_at_value,
            is_obsolete=_is_obsolete(perceived_at),
            size_variant=_normalize_variant_value(row["size_variant"])
            if "size_variant" in row.keys()
            else None,
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

        degraded_qty = payload.degraded_qty
        lost_qty = payload.lost_qty
        if payload.is_degraded and degraded_qty == 0:
            degraded_qty = payload.quantity
        if payload.is_lost and lost_qty == 0:
            lost_qty = payload.quantity
        _validate_dotation_quantities(
            quantity=payload.quantity,
            degraded_qty=degraded_qty,
            lost_qty=lost_qty,
        )
        is_lost, is_degraded = _derive_dotation_flags(degraded_qty, lost_qty)

        notes = payload.notes
        if notes is not None:
            notes = clamp_note(notes, DOTATION_NOTE_MAX_LENGTH)
        cur = conn.execute(
            """
            INSERT INTO dotations (
                collaborator_id,
                item_id,
                quantity,
                notes,
                perceived_at,
                is_lost,
                is_degraded,
                degraded_qty,
                lost_qty
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.collaborator_id,
                payload.item_id,
                payload.quantity,
                notes,
                payload.perceived_at.isoformat(),
                is_lost,
                is_degraded,
                degraded_qty,
                lost_qty,
            ),
        )
        occurred_at = datetime.now()
        _record_dotation_event(
            conn,
            dotation_id=cur.lastrowid,
            event_type="CREATION",
            message="Dotation créée.",
            order_id=None,
            item_id=payload.item_id,
            item_name=None,
            sku=None,
            size=None,
            quantity=payload.quantity,
            reason=None,
            occurred_at=occurred_at,
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


def scan_add_dotation(*, employee_id: int, barcode: str, quantity: int = 1) -> models.Dotation:
    normalized = barcode.strip()
    if not normalized:
        raise ValueError("Le code-barres ne peut pas être vide")
    matches = find_items_by_barcode("clothing", normalized)
    if not matches:
        raise ValueError("Aucun article trouvé pour ce code.")
    if len(matches) > 1:
        raise ValueError("Plusieurs articles correspondent à ce code.")
    payload = models.DotationCreate(
        collaborator_id=employee_id,
        item_id=matches[0].id,
        quantity=quantity,
        notes=None,
        perceived_at=date.today(),
        is_lost=False,
        is_degraded=False,
    )
    return create_dotation(payload)


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
        if new_notes is not None:
            new_notes = clamp_note(new_notes, DOTATION_NOTE_MAX_LENGTH)
        new_perceived_at = payload.perceived_at if payload.perceived_at is not None else base_perceived_at
        base_degraded_qty = int(_row_get(row, "degraded_qty", 0) or 0)
        base_lost_qty = int(_row_get(row, "lost_qty", 0) or 0)
        if payload.degraded_qty is not None:
            new_degraded_qty = payload.degraded_qty
        elif payload.is_degraded is not None:
            new_degraded_qty = new_quantity if payload.is_degraded else 0
        else:
            new_degraded_qty = base_degraded_qty
        if payload.lost_qty is not None:
            new_lost_qty = payload.lost_qty
        elif payload.is_lost is not None:
            new_lost_qty = new_quantity if payload.is_lost else 0
        else:
            new_lost_qty = base_lost_qty
        _validate_dotation_quantities(
            quantity=new_quantity, degraded_qty=new_degraded_qty, lost_qty=new_lost_qty
        )
        new_is_lost, new_is_degraded = _derive_dotation_flags(new_degraded_qty, new_lost_qty)

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
                is_degraded = ?,
                degraded_qty = ?,
                lost_qty = ?
            WHERE id = ?
            """,
            (
                new_collaborator_id,
                new_item_id,
                new_quantity,
                new_notes,
                new_perceived_at.isoformat(),
                new_is_lost,
                new_is_degraded,
                new_degraded_qty,
                new_lost_qty,
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
        supplier_ids = sorted(
            {
                supplier_id
                for row in rows
                if (supplier_id := _row_get(row, "supplier_id")) is not None
            }
        )
        suppliers_by_id: dict[int, sqlite3.Row] = {}
        if supplier_ids:
            placeholders = ", ".join("?" for _ in supplier_ids)
            supplier_rows = conn.execute(
                f"SELECT id, name, email FROM suppliers WHERE id IN ({placeholders})",
                supplier_ids,
            ).fetchall()
            suppliers_by_id = {row["id"]: row for row in supplier_rows}
        category_ids = sorted(
            {category_id for row in rows if (category_id := row["category_id"]) is not None}
        )
        sizes_map: dict[int, list[str]] = {}
        if category_ids:
            placeholders = ", ".join("?" for _ in category_ids)
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
        category_sizes_map = {
            category_id: ", ".join(sizes) if sizes else None
            for category_id, sizes in sizes_map.items()
        }
        return [
            models.PharmacyItem(
                id=row["id"],
                name=row["name"],
                dosage=row["dosage"],
                packaging=row["packaging"],
                size_format=row["size_format"] if "size_format" in row.keys() else None,
                barcode=row["barcode"],
                quantity=row["quantity"],
                low_stock_threshold=row["low_stock_threshold"],
                track_low_stock=bool(row["track_low_stock"]) if "track_low_stock" in row.keys() else True,
                expiration_date=row["expiration_date"],
                location=row["location"],
                category_id=row["category_id"],
                category_sizes=(
                    category_sizes_map.get(row["category_id"])
                    if row["category_id"] is not None
                    else None
                ),
                supplier_id=_row_get(row, "supplier_id"),
                supplier_name=(
                    suppliers_by_id.get(_row_get(row, "supplier_id"))["name"]
                    if _row_get(row, "supplier_id") is not None
                    and _row_get(row, "supplier_id") in suppliers_by_id
                    else None
                ),
                supplier_email=(
                    suppliers_by_id.get(_row_get(row, "supplier_id"))["email"]
                    if _row_get(row, "supplier_id") is not None
                    and _row_get(row, "supplier_id") in suppliers_by_id
                    else None
                ),
                extra=_parse_extra_json(_row_get(row, "extra_json")),
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


def _collect_generated_catalog_keys(
    conn: sqlite3.Connection,
    skus: Iterable[str],
    sources: list[tuple[str, str, str, str]],
) -> set[tuple[str, str]]:
    normalized_skus = {
        sku.strip().casefold(): sku.strip()
        for sku in skus
        if sku and sku.strip()
    }
    if not normalized_skus or not sources:
        return set()

    lower_skus = list(normalized_skus.keys())
    placeholders = ",".join(["?"] * len(lower_skus))
    collected: set[tuple[str, str]] = set()

    for module_key, table, sku_column, _ in sources:
        query = f"""
            SELECT {sku_column} AS sku
            FROM {table}
            WHERE LOWER({sku_column}) IN ({placeholders})
        """
        rows = conn.execute(query, lower_skus).fetchall()
        for row in rows:
            sku_value = (row["sku"] or "").strip()
            if not sku_value:
                continue
            collected.add((module_key, sku_value.casefold()))

    return collected


def list_barcode_catalog(
    user: models.User,
    module: str | None = None,
    q: str | None = None,
    exclude_generated: bool = False,
) -> list[models.BarcodeCatalogEntry]:
    ensure_database_ready()

    normalized_module = (module or "all").strip().lower()
    search = (q or "").strip()
    site_key = db.get_current_site_key()

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

    generated_keys: set[tuple[str, str]] = set()
    if exclude_generated:
        assets = barcode_service.list_barcode_assets(site_key=site_key)
        if assets:
            with db.get_stock_connection() as conn:
                generated_keys = _collect_generated_catalog_keys(
                    conn, (asset.sku for asset in assets), accessible_sources
                )

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
                if exclude_generated and (module_key, sku_value.casefold()) in generated_keys:
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
) -> dict[str, tuple[str, str, str]]:
    normalized_skus = {
        sku.strip().casefold(): sku.strip()
        for sku in skus
        if sku and sku.strip()
    }
    if not normalized_skus or not sources:
        return {}

    lower_skus = list(normalized_skus.keys())
    placeholders = ",".join(["?"] * len(lower_skus))
    resolved: dict[str, tuple[str, str, str]] = {}

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
            resolved[key] = (module_key, label, name_value or sku_value)

    return resolved


def _barcode_inventory_module_for_key(module_key: str) -> str | None:
    mapping = {
        "clothing": "default",
        "pharmacy": "pharmacy",
        "inventory_remise": "inventory_remise",
        "vehicle_inventory": "vehicle_inventory",
    }
    return mapping.get(module_key)


def _resolve_barcode_label_metadata(
    conn: sqlite3.Connection,
    skus: Iterable[str],
    sources: list[tuple[str, str, str, str]],
) -> dict[str, tuple[str, str | None, str | None]]:
    normalized_skus = {
        sku.strip().casefold(): sku.strip()
        for sku in skus
        if sku and sku.strip()
    }
    if not normalized_skus or not sources:
        return {}

    lower_skus = list(normalized_skus.keys())
    placeholders = ",".join(["?"] * len(lower_skus))
    resolved: dict[str, tuple[str, str | None, str | None]] = {}

    for module_key, table, sku_column, name_column in sources:
        size_column = "size_format" if module_key == "pharmacy" else "size"
        size_select = (
            f"i.{size_column} AS size"
            if _table_has_column(conn, table, size_column)
            else "NULL AS size"
        )
        category_join = ""
        category_select = "NULL AS category"
        if _table_has_column(conn, table, "category_id"):
            inventory_module = _barcode_inventory_module_for_key(module_key)
            if inventory_module:
                category_table = _get_inventory_config(inventory_module).tables.categories
                category_join = f"LEFT JOIN {category_table} AS c ON c.id = i.category_id"
                category_select = "c.name AS category"

        query = f"""
            SELECT i.{sku_column} AS sku,
                   i.{name_column} AS name,
                   {size_select},
                   {category_select}
            FROM {table} AS i
            {category_join}
            WHERE LOWER(i.{sku_column}) IN ({placeholders})
        """
        rows = conn.execute(query, lower_skus).fetchall()
        for row in rows:
            sku_value = (row["sku"] or "").strip()
            if not sku_value:
                continue
            key = sku_value.casefold()
            if key in resolved:
                continue
            name_value = (row["name"] or "").strip() or sku_value
            category_value = (row["category"] or "").strip() if "category" in row.keys() else ""
            size_value = (row["size"] or "").strip() if "size" in row.keys() else ""
            resolved[key] = (
                name_value,
                category_value or None,
                size_value or None,
            )

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
        module_key, label, item_name = meta
        if search:
            haystack = f"{label} {item_name} {sku_value}".casefold()
            if search not in haystack:
                continue
        entries.append(
            models.BarcodeGeneratedEntry(
                sku=sku_value,
                module=module_key,
                label=label,
                item_name=item_name,
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


def enrich_barcode_assets_with_metadata(
    user: models.User,
    assets: Iterable[barcode_service.BarcodeAsset],
) -> list[barcode_service.BarcodeAsset]:
    assets_list = list(assets)
    if not assets_list:
        return []

    sources = [
        source
        for source in _BARCODE_CATALOG_SOURCES
        if user.role == "admin" or has_module_access(user, source[0], action="view")
    ]
    if not sources:
        return assets_list

    ensure_database_ready()
    with db.get_stock_connection() as conn:
        resolved = _resolve_barcode_label_metadata(conn, (asset.sku for asset in assets_list), sources)

    enriched: list[barcode_service.BarcodeAsset] = []
    for asset in assets_list:
        resolved_key = asset.sku.strip().casefold()
        meta = resolved.get(resolved_key)
        if meta:
            name_value, category_value, size_value = meta
            enriched.append(
                replace(
                    asset,
                    name=name_value,
                    category=category_value,
                    size=size_value,
                )
            )
        else:
            enriched.append(asset)
    return enriched


def get_pharmacy_item(item_id: int) -> models.PharmacyItem:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT * FROM pharmacy_items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("Produit pharmaceutique introuvable")
        category_sizes = None
        if row["category_id"] is not None:
            size_rows = conn.execute(
                """
                SELECT name
                FROM pharmacy_category_sizes
                WHERE category_id = ?
                ORDER BY name COLLATE NOCASE
                """,
                (row["category_id"],),
            ).fetchall()
            category_sizes = ", ".join([size_row["name"] for size_row in size_rows]) or None
        return models.PharmacyItem(
            id=row["id"],
            name=row["name"],
            dosage=row["dosage"],
            packaging=row["packaging"],
            size_format=row["size_format"] if "size_format" in row.keys() else None,
            barcode=row["barcode"],
            quantity=row["quantity"],
            low_stock_threshold=row["low_stock_threshold"],
            track_low_stock=bool(row["track_low_stock"]) if "track_low_stock" in row.keys() else True,
            expiration_date=row["expiration_date"],
            location=row["location"],
            category_id=row["category_id"],
            category_sizes=category_sizes,
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
                    size_format,
                    barcode,
                    quantity,
                    low_stock_threshold,
                    track_low_stock,
                    expiration_date,
                    location,
                    category_id,
                    supplier_id,
                    extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.name,
                    payload.dosage,
                    payload.packaging,
                    payload.size_format,
                    barcode,
                    payload.quantity,
                    payload.low_stock_threshold,
                    int(payload.track_low_stock),
                    expiration_date,
                    payload.location,
                    payload.category_id,
                    supplier_id,
                    _dump_extra_json(extra),
                ),
            )
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Ce code-barres est déjà utilisé") from exc
        _maybe_create_auto_purchase_order(conn, "pharmacy", cur.lastrowid)
        _persist_after_commit(conn, "pharmacy")
        return get_pharmacy_item(cur.lastrowid)


def update_pharmacy_item(item_id: int, payload: models.PharmacyItemUpdate) -> models.PharmacyItem:
    ensure_database_ready()
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    extra_payload = fields.pop("extra", None)
    if "barcode" in fields:
        fields["barcode"] = _normalize_barcode(fields["barcode"])
    if "track_low_stock" in fields:
        fields["track_low_stock"] = int(bool(fields["track_low_stock"]))
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
    should_check_low_stock = any(
        key in fields for key in {"quantity", "low_stock_threshold", "supplier_id", "extra_json"}
    )
    with db.get_stock_connection() as conn:
        cur = conn.execute("SELECT 1 FROM pharmacy_items WHERE id = ?", (item_id,))
        if cur.fetchone() is None:
            raise ValueError("Produit pharmaceutique introuvable")
        try:
            conn.execute(f"UPDATE pharmacy_items SET {assignments} WHERE id = ?", values)
        except sqlite3.IntegrityError as exc:  # pragma: no cover - handled via exception flow
            raise ValueError("Ce code-barres est déjà utilisé") from exc
        if should_check_low_stock:
            _maybe_create_auto_purchase_order(conn, "pharmacy", item_id)
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
        _maybe_create_auto_purchase_order(conn, "pharmacy", item_id)
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
    has_line_sku = _table_has_column(conn, "pharmacy_purchase_order_items", "sku")
    has_line_unit = _table_has_column(conn, "pharmacy_purchase_order_items", "unit")
    sku_expr = "NULLIF(TRIM(pi.barcode), '') AS sku"
    unit_expr = "COALESCE(NULLIF(TRIM(pi.packaging), ''), 'Unité') AS unit"
    if has_line_sku:
        sku_expr = "COALESCE(NULLIF(TRIM(poi.sku), ''), NULLIF(TRIM(pi.barcode), '')) AS sku"
    if has_line_unit:
        unit_expr = "COALESCE(NULLIF(TRIM(poi.unit), ''), NULLIF(TRIM(pi.packaging), ''), 'Unité') AS unit"
    items_cur = conn.execute(
        f"""
        SELECT poi.id,
               poi.purchase_order_id,
               poi.pharmacy_item_id,
               poi.quantity_ordered,
               poi.quantity_received,
               pi.name AS pharmacy_item_name,
               {sku_expr},
               {unit_expr}
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
            sku=_row_get(item_row, "sku"),
            unit=_row_get(item_row, "unit"),
        )
        for item_row in items_cur.fetchall()
    ]
    resolved_email = None
    supplier_has_email = False
    supplier_missing_reason = None
    supplier_id = _row_get(order_row, "supplier_id")
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
        auto_created=bool(_row_get(order_row, "auto_created", 0)),
        is_archived=bool(_row_get(order_row, "is_archived", 0)),
        archived_at=_row_get(order_row, "archived_at"),
        archived_by=_row_get(order_row, "archived_by"),
        items=items,
    )


def list_pharmacy_purchase_orders(
    *,
    include_archived: bool = False,
    archived_only: bool = False,
) -> list[models.PharmacyPurchaseOrderDetail]:
    ensure_database_ready()
    where_clause = ""
    params: tuple[object, ...] = ()
    if archived_only:
        where_clause = "WHERE COALESCE(po.is_archived, 0) = 1"
    elif not include_archived:
        where_clause = "WHERE COALESCE(po.is_archived, 0) = 0"
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            f"""
            SELECT po.*, s.name AS supplier_name, s.email AS supplier_email
            FROM pharmacy_purchase_orders AS po
            LEFT JOIN suppliers AS s ON s.id = po.supplier_id
            {where_clause}
            ORDER BY po.created_at DESC, po.id DESC
            """,
            params,
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


def archive_pharmacy_purchase_order(
    order_id: int,
    *,
    archived_by: int | None = None,
) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT status, is_archived FROM pharmacy_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        if _row_get(row, "is_archived"):
            return get_pharmacy_purchase_order(order_id)
        _assert_purchase_order_archivable(row["status"])
        conn.execute(
            """
            UPDATE pharmacy_purchase_orders
            SET is_archived = 1,
                archived_at = CURRENT_TIMESTAMP,
                archived_by = ?
            WHERE id = ?
            """,
            (archived_by, order_id),
        )
    return get_pharmacy_purchase_order(order_id)


def unarchive_pharmacy_purchase_order(
    order_id: int,
) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM pharmacy_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        conn.execute(
            """
            UPDATE pharmacy_purchase_orders
            SET is_archived = 0,
                archived_at = NULL,
                archived_by = NULL
            WHERE id = ?
            """,
            (order_id,),
        )
    return get_pharmacy_purchase_order(order_id)


def create_pharmacy_purchase_order(
    payload: models.PharmacyPurchaseOrderCreate,
) -> models.PharmacyPurchaseOrderDetail:
    ensure_database_ready()
    status = _normalize_purchase_order_status(payload.status)
    if payload.supplier_id is None:
        raise ValueError("Fournisseur obligatoire")
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
            has_line_sku = _table_has_column(conn, "pharmacy_purchase_order_items", "sku")
            has_line_unit = _table_has_column(conn, "pharmacy_purchase_order_items", "unit")
            for item_id, quantity in aggregated.items():
                item_row = conn.execute(
                    "SELECT barcode, packaging, dosage FROM pharmacy_items WHERE id = ?", (item_id,)
                ).fetchone()
                if item_row is None:
                    raise ValueError("Article pharmaceutique introuvable")
                columns = [
                    "purchase_order_id",
                    "pharmacy_item_id",
                    "quantity_ordered",
                    "quantity_received",
                ]
                values: list[object] = [order_id, item_id, quantity, 0]
                if has_line_sku:
                    columns.append("sku")
                    values.append(item_row["barcode"] if item_row["barcode"] else None)
                if has_line_unit:
                    columns.append("unit")
                    values.append(item_row["packaging"] or item_row["dosage"])
                conn.execute(
                    f"INSERT INTO pharmacy_purchase_order_items ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
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
    line_increments: dict[int, int] = {}
    item_increments: dict[int, int] = {}
    if payload.lines:
        line_increments = _aggregate_positive_quantities(
            (line.line_id, line.qty) for line in payload.lines
        )
    elif payload.items:
        item_increments = _aggregate_positive_quantities(
            (line.pharmacy_item_id, line.quantity) for line in payload.items
        )
    if not line_increments and not item_increments:
        raise ValueError("Aucune ligne de réception valide")
    with db.get_stock_connection() as conn:
        order_row = conn.execute(
            "SELECT status FROM pharmacy_purchase_orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_row is None:
            raise ValueError("Bon de commande pharmacie introuvable")
        if order_row["status"] == "CANCELLED":
            raise ValueError("Bon de commande annulé")
        try:
            if line_increments:
                for line_id, increment in line_increments.items():
                    line = conn.execute(
                        """
                        SELECT id, pharmacy_item_id, quantity_ordered, quantity_received
                        FROM pharmacy_purchase_order_items
                        WHERE purchase_order_id = ? AND id = ?
                        """,
                        (order_id, line_id),
                    ).fetchone()
                    if line is None:
                        raise ValueError("Ligne de commande introuvable")
                    remaining = line["quantity_ordered"] - line["quantity_received"]
                    if increment > remaining:
                        raise ValueError("Quantité reçue supérieure au restant")
                    if increment <= 0:
                        continue
                    new_received = line["quantity_received"] + increment
                    conn.execute(
                        "UPDATE pharmacy_purchase_order_items SET quantity_received = ? WHERE id = ?",
                        (new_received, line["id"]),
                    )
                    conn.execute(
                        "UPDATE pharmacy_items SET quantity = quantity + ? WHERE id = ?",
                        (increment, line["pharmacy_item_id"]),
                    )
                    conn.execute(
                        "INSERT INTO pharmacy_movements (pharmacy_item_id, delta, reason) VALUES (?, ?, ?)",
                        (
                            line["pharmacy_item_id"],
                            increment,
                            f"Réception bon de commande pharmacie #{order_id}"
                        ),
                    )
                    _maybe_create_auto_purchase_order(
                        conn, "pharmacy", line["pharmacy_item_id"]
                    )
            else:
                for item_id, increment in item_increments.items():
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
                    if increment > remaining:
                        raise ValueError("Quantité reçue supérieure au restant")
                    if increment <= 0:
                        continue
                    new_received = line["quantity_received"] + increment
                    conn.execute(
                        "UPDATE pharmacy_purchase_order_items SET quantity_received = ? WHERE id = ?",
                        (new_received, line["id"]),
                    )
                    conn.execute(
                        "UPDATE pharmacy_items SET quantity = quantity + ? WHERE id = ?",
                        (increment, item_id),
                    )
                    conn.execute(
                        "INSERT INTO pharmacy_movements (pharmacy_item_id, delta, reason) VALUES (?, ?, ?)",
                        (item_id, increment, f"Réception bon de commande pharmacie #{order_id}"),
                    )
                    _maybe_create_auto_purchase_order(conn, "pharmacy", item_id)
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
        models.ModuleDefinition(
            key=entry.key,
            label=entry.label,
            category=entry.category,
            is_admin_only=entry.is_admin_only,
            sort_order=entry.sort_order,
        )
        for entry in _AVAILABLE_MODULE_DEFINITIONS
        if not entry.is_admin_only
    ]
    definition_keys = {entry.key for entry in definitions}
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT DISTINCT module FROM module_permissions ORDER BY module COLLATE NOCASE"
        )
        for row in cur.fetchall():
            module_key = normalize_module_key(row["module"])
            if not module_key or module_key in definition_keys:
                continue
            if _is_admin_only_module(module_key):
                continue
            definitions.append(
                models.ModuleDefinition(
                    key=module_key,
                    label=module_key.replace("_", " ").title(),
                    category="Autres",
                    is_admin_only=False,
                    sort_order=999,
                )
            )
            definition_keys.add(module_key)
    return sorted(definitions, key=lambda entry: (entry.category, entry.sort_order, entry.label))


def list_module_permissions() -> list[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions ORDER BY user_id, module COLLATE NOCASE"
        )
        rows = cur.fetchall()
    merged: dict[tuple[int, str], models.ModulePermission] = {}
    for row in rows:
        module_key = normalize_module_key(row["module"])
        if not module_key or _is_admin_only_module(module_key):
            continue
        key = (row["user_id"], module_key)
        existing = merged.get(key)
        if existing:
            existing.can_view = existing.can_view or bool(row["can_view"])
            existing.can_edit = existing.can_edit or bool(row["can_edit"])
            continue
        merged[key] = models.ModulePermission(
            id=row["id"],
            user_id=row["user_id"],
            module=module_key,
            can_view=bool(row["can_view"]),
            can_edit=bool(row["can_edit"]),
        )
    return sorted(merged.values(), key=lambda entry: (entry.user_id, entry.module))


def list_module_permissions_for_user(user_id: int) -> list[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM module_permissions WHERE user_id = ? ORDER BY module COLLATE NOCASE",
            (user_id,),
        )
        rows = cur.fetchall()
    merged: dict[str, models.ModulePermission] = {}
    for row in rows:
        module_key = normalize_module_key(row["module"])
        if not module_key or _is_admin_only_module(module_key):
            continue
        existing = merged.get(module_key)
        if existing:
            existing.can_view = existing.can_view or bool(row["can_view"])
            existing.can_edit = existing.can_edit or bool(row["can_edit"])
            continue
        merged[module_key] = models.ModulePermission(
            id=row["id"],
            user_id=row["user_id"],
            module=module_key,
            can_view=bool(row["can_view"]),
            can_edit=bool(row["can_edit"]),
        )
    return sorted(merged.values(), key=lambda entry: entry.module)


def get_module_permission_for_user(
    user_id: int, module: str
) -> Optional[models.ModulePermission]:
    ensure_database_ready()
    with db.get_users_connection() as conn:
        lookup_keys = _module_lookup_keys(module)
        if not lookup_keys:
            return None
        params = ",".join("?" for _ in lookup_keys)
        cur = conn.execute(
            f"SELECT * FROM module_permissions WHERE user_id = ? AND module IN ({params})",
            (user_id, *lookup_keys),
        )
        rows = cur.fetchall()
        if not rows:
            return None
        module_key = normalize_module_key(module)
        can_view = any(bool(row["can_view"]) for row in rows)
        can_edit = any(bool(row["can_edit"]) for row in rows)
        selected = next((row for row in rows if row["module"] == module_key), rows[0])
        if _is_admin_only_module(module_key):
            return None
        return models.ModulePermission(
            id=selected["id"],
            user_id=selected["user_id"],
            module=module_key,
            can_view=can_view,
            can_edit=can_edit,
        )


def upsert_module_permission(payload: models.ModulePermissionUpsert) -> models.ModulePermission:
    ensure_database_ready()
    if get_user_by_id(payload.user_id) is None:
        raise ValueError("Utilisateur introuvable")
    normalized_module = normalize_module_key(payload.module)
    if not normalized_module:
        raise ValueError("Module introuvable")
    if _is_admin_only_module(normalized_module):
        raise ValueError("Module introuvable")
    with db.get_users_connection() as conn:
        if normalized_module not in _AVAILABLE_MODULE_KEYS:
            cur = conn.execute(
                "SELECT 1 FROM module_permissions WHERE module = ? LIMIT 1",
                (normalized_module,),
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
                normalized_module,
                int(payload.can_view),
                int(payload.can_edit),
            ),
        )
        aliases = _MODULE_CANONICAL_ALIASES.get(normalized_module, ())
        if aliases:
            conn.execute(
                f"DELETE FROM module_permissions WHERE user_id = ? AND module IN ({','.join('?' for _ in aliases)})",
                (payload.user_id, *aliases),
            )
        conn.commit()
    permission = get_module_permission_for_user(payload.user_id, normalized_module)
    if permission is None:
        raise RuntimeError("Échec de l'enregistrement de la permission du module")
    return permission


def delete_module_permission_for_user(user_id: int, module: str) -> None:
    ensure_database_ready()
    lookup_keys = _module_lookup_keys(module)
    if not lookup_keys:
        raise ValueError("Permission de module introuvable")
    with db.get_users_connection() as conn:
        params = ",".join("?" for _ in lookup_keys)
        cur = conn.execute(
            f"DELETE FROM module_permissions WHERE user_id = ? AND module IN ({params})",
            (user_id, *lookup_keys),
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
    normalized_module = normalize_module_key(module)
    required_modules = [normalized_module, *_iter_module_dependencies(normalized_module)]
    for required in required_modules:
        permission = get_module_permission_for_user(user.id, required)
        if permission is None:
            return False
        if required == normalized_module:
            if action == "edit":
                if not permission.can_edit:
                    return False
            elif not permission.can_view:
                return False
        elif not permission.can_view:
            return False
    return True
