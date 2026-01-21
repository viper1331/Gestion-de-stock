"""Gestion basique des connexions SQLite."""
from __future__ import annotations

import contextvars
import logging
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import ContextManager

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
USERS_DB_PATH = DATA_DIR / "users.db"
STOCK_DB_PATH = DATA_DIR / "stock.db"
CORE_DB_PATH = DATA_DIR / "core.db"

SITE_KEYS = ("JLL", "GSM", "ST_ELOIS", "CENTRAL_ENTITY")
DEFAULT_SITE_KEY = "JLL"
SITE_DISPLAY_NAMES = {
    "JLL": "JLL",
    "GSM": "GSM",
    "ST_ELOIS": "Saint-Élois",
    "CENTRAL_ENTITY": "Entité centrale",
}

logger = logging.getLogger(__name__)

DATA_DIR.mkdir(parents=True, exist_ok=True)
logger.info("[DB] pid=%s STOCK_DB_PATH=%s", os.getpid(), STOCK_DB_PATH.resolve())

_site_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "site_key", default=None
)

_db_lock = RLock()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


@contextmanager
def _managed_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection that is always closed on exit."""

    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


def get_users_connection() -> ContextManager[sqlite3.Connection]:
    return _managed_connection(USERS_DB_PATH)


def get_core_connection() -> ContextManager[sqlite3.Connection]:
    return _managed_connection(CORE_DB_PATH)


def set_current_site(site_key: str | None) -> contextvars.Token[str | None]:
    return _site_context.set(site_key)


def reset_current_site(token: contextvars.Token[str | None]) -> None:
    _site_context.reset(token)


def get_current_site_key() -> str:
    return _site_context.get() or DEFAULT_SITE_KEY


def _resolve_jll_db_path() -> Path:
    env_path = os.environ.get("JLL_DB_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return STOCK_DB_PATH


def get_default_site_db_paths() -> dict[str, Path]:
    return {
        "JLL": _resolve_jll_db_path(),
        "GSM": DATA_DIR / "GSM.db",
        "ST_ELOIS": DATA_DIR / "ST_ELOIS.db",
        "CENTRAL_ENTITY": DATA_DIR / "CENTRAL_ENTITY.db",
    }


def _discover_site_db_paths() -> dict[str, Path]:
    candidates: dict[str, Path] = {}
    default_paths = get_default_site_db_paths()
    for site_key, path in default_paths.items():
        if path.exists():
            candidates[site_key] = path
    search_dirs = [DATA_DIR, DATA_DIR / "sites"]
    for folder in search_dirs:
        if not folder.exists():
            continue
        for entry in folder.glob("*.db"):
            site_key = entry.stem.upper()
            if site_key in SITE_KEYS:
                candidates[site_key] = entry
    return candidates


def get_site_db_path(site_key: str) -> Path:
    site_key = site_key.upper()
    default_paths = get_default_site_db_paths()
    try:
        with get_core_connection() as conn:
            row = conn.execute(
                "SELECT db_path FROM sites WHERE site_key = ?",
                (site_key,),
            ).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row and row["db_path"]:
        return Path(row["db_path"])
    return default_paths.get(site_key, default_paths[DEFAULT_SITE_KEY])


def get_stock_connection(site_key: str | None = None) -> ContextManager[sqlite3.Connection]:
    resolved_key = (site_key or get_current_site_key()).upper()
    return _managed_connection(get_site_db_path(resolved_key))


def get_stock_db_path(site_key: str | None = None) -> Path:
    resolved_key = (site_key or get_current_site_key()).upper()
    return get_site_db_path(resolved_key)


def list_site_keys() -> list[str]:
    try:
        with get_core_connection() as conn:
            rows = conn.execute(
                "SELECT site_key FROM sites WHERE is_active = 1 ORDER BY site_key"
            ).fetchall()
        if rows:
            return [row["site_key"] for row in rows]
    except sqlite3.OperationalError:
        pass
    return list(SITE_KEYS)


def list_site_db_paths() -> dict[str, Path]:
    return {site_key: get_site_db_path(site_key) for site_key in list_site_keys()}


def init_databases() -> None:
    with _db_lock:
        with get_users_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT,
                    email_normalized TEXT UNIQUE,
                    password TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active',
                    session_version INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP,
                    approved_by INTEGER,
                    rejected_at TIMESTAMP,
                    rejected_by INTEGER,
                    notify_on_approval INTEGER NOT NULL DEFAULT 0,
                    otp_email_enabled INTEGER NOT NULL DEFAULT 0,
                    site_key TEXT NOT NULL DEFAULT 'JLL',
                    admin_active_site_key TEXT,
                    display_name TEXT
                );
                CREATE TABLE IF NOT EXISTS user_trusted_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT,
                    UNIQUE(username, device_id)
                );
                CREATE INDEX IF NOT EXISTS idx_user_trusted_devices_lookup
                ON user_trusted_devices(username, device_id);
                CREATE TABLE IF NOT EXISTS two_factor_rate_limits (
                    username TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    window_start_ts INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (username, ip_address)
                );
                CREATE TABLE IF NOT EXISTS two_factor_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    purpose TEXT NOT NULL DEFAULT 'verify',
                    secret_enc TEXT,
                    created_at_ts INTEGER NOT NULL,
                    expires_at_ts INTEGER NOT NULL,
                    used_at_ts INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    locked_until_ts INTEGER
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_username TEXT NOT NULL,
                    sender_role TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT NULL,
                    request_ip TEXT NULL,
                    user_agent TEXT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_prt_user_id
                ON password_reset_tokens(user_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_prt_token_hash
                ON password_reset_tokens(token_hash);
                CREATE INDEX IF NOT EXISTS idx_prt_expires_at
                ON password_reset_tokens(expires_at);
                CREATE TABLE IF NOT EXISTS password_reset_rate_limits (
                    email_normalized TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    window_start_ts INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY (email_normalized, ip_address)
                );
                CREATE TABLE IF NOT EXISTS message_recipients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    recipient_username TEXT NOT NULL,
                    is_read INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    read_at TIMESTAMP,
                    archived_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS message_rate_limits (
                    sender_username TEXT PRIMARY KEY,
                    window_start_ts INTEGER NOT NULL,
                    count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_created_at
                ON messages(created_at);
                CREATE INDEX IF NOT EXISTS idx_message_recipients_recipient
                ON message_recipients(recipient_username, is_archived);
                CREATE INDEX IF NOT EXISTS idx_message_recipients_message
                ON message_recipients(message_id);
                CREATE TABLE IF NOT EXISTS module_permissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    module TEXT NOT NULL,
                    can_view INTEGER NOT NULL DEFAULT 0,
                    can_edit INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(user_id, module)
                );
                CREATE TABLE IF NOT EXISTS user_homepage_config (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                );
                CREATE TABLE IF NOT EXISTS user_layouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    layout_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, page_id)
                );
                CREATE TABLE IF NOT EXISTS user_page_layouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    page_key TEXT NOT NULL,
                    layout_json TEXT NOT NULL,
                    hidden_blocks_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, page_key)
                );
                CREATE TABLE IF NOT EXISTS ui_menu_prefs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_key TEXT NOT NULL,
                    username TEXT NOT NULL,
                    menu_key TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(site_key, username, menu_key)
                );
                CREATE TABLE IF NOT EXISTS user_table_prefs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    site_key TEXT NOT NULL,
                    table_key TEXT NOT NULL,
                    prefs_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, site_key, table_key)
                );
                """
            )
            _ensure_user_site_columns(conn)
            _ensure_user_account_columns(conn)
            _ensure_user_session_columns(conn)
            _ensure_two_factor_columns(conn)
            _ensure_two_factor_challenge_columns(conn)
        _init_core_database()
        _sync_user_site_preferences()
        for site_key in SITE_KEYS:
            site_path = get_site_db_path(site_key)
            site_path.parent.mkdir(parents=True, exist_ok=True)
            with _managed_connection(site_path) as conn:
                _init_stock_schema(conn)


def _init_core_database() -> None:
    with get_core_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sites (
                site_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                db_path TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS user_site_assignments (
                username TEXT PRIMARY KEY,
                site_key TEXT NOT NULL REFERENCES sites(site_key)
            );
            CREATE TABLE IF NOT EXISTS user_site_overrides (
                username TEXT PRIMARY KEY,
                site_key TEXT REFERENCES sites(site_key),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_page_layouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                page_key TEXT NOT NULL,
                layout_json TEXT NOT NULL,
                hidden_blocks_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(username, page_key)
            );
            CREATE TABLE IF NOT EXISTS backup_settings (
                site_key TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                retention_count INTEGER NOT NULL DEFAULT 3,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS otp_email_challenges (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                code_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_sent_at TEXT NOT NULL,
                request_ip TEXT,
                user_agent TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_otp_user_id
            ON otp_email_challenges(user_id);
            CREATE INDEX IF NOT EXISTS idx_otp_code_hash
            ON otp_email_challenges(code_hash);
            CREATE INDEX IF NOT EXISTS idx_otp_expires_at
            ON otp_email_challenges(expires_at);
            CREATE TABLE IF NOT EXISTS email_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                to_email TEXT NOT NULL,
                subject TEXT NOT NULL,
                body_text TEXT NOT NULL,
                body_html TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                send_attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                priority INTEGER NOT NULL DEFAULT 5
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_sent_at
            ON email_outbox(sent_at);
            CREATE INDEX IF NOT EXISTS idx_outbox_priority
            ON email_outbox(priority);
            CREATE TABLE IF NOT EXISTS otp_email_rate_limits (
                key TEXT PRIMARY KEY,
                window_start TEXT NOT NULL,
                count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            );
            CREATE TABLE IF NOT EXISTS purchase_order_email_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                site_key TEXT NOT NULL,
                module_key TEXT NOT NULL,
                purchase_order_id INTEGER NOT NULL,
                purchase_order_number TEXT,
                supplier_id INTEGER,
                supplier_email TEXT NOT NULL,
                user_id INTEGER,
                user_email TEXT,
                status TEXT NOT NULL CHECK(status IN ('sent','failed')),
                message_id TEXT,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS purchase_order_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                site_key TEXT NOT NULL,
                module_key TEXT NOT NULL,
                action TEXT NOT NULL,
                purchase_order_id INTEGER NOT NULL,
                supplier_id INTEGER,
                supplier_name TEXT,
                supplier_email TEXT,
                recipient_email TEXT,
                user_id INTEGER,
                user_email TEXT,
                status TEXT NOT NULL CHECK(status IN ('ok','error')),
                message TEXT
            );
            """
        )
        default_paths = get_default_site_db_paths()
        for site_key in SITE_KEYS:
            conn.execute(
                """
                INSERT INTO sites (site_key, display_name, db_path, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(site_key) DO UPDATE SET
                  display_name = excluded.display_name,
                  db_path = excluded.db_path,
                  is_active = 1
                """,
                (
                    site_key,
                    SITE_DISPLAY_NAMES.get(site_key, site_key),
                    str(default_paths[site_key]),
                ),
            )
        discovered_paths = _discover_site_db_paths()
        for site_key, path in discovered_paths.items():
            conn.execute(
                """
                UPDATE sites
                SET db_path = ?, is_active = 1
                WHERE site_key = ?
                """,
                (str(path), site_key),
            )
        _migrate_user_layouts_to_core(conn)
        _backfill_user_site_assignments(conn)
        conn.commit()


def _migrate_user_layouts_to_core(core_conn: sqlite3.Connection) -> None:
    row = core_conn.execute("SELECT COUNT(*) AS count FROM user_page_layouts").fetchone()
    if row and row["count"]:
        return
    try:
        with get_users_connection() as users_conn:
            existing_rows = users_conn.execute(
                """
                SELECT username, page_key, layout_json, hidden_blocks_json, updated_at
                FROM user_page_layouts
                """
            ).fetchall()
    except sqlite3.OperationalError:
        return
    if not existing_rows:
        return
    core_conn.executemany(
        """
        INSERT INTO user_page_layouts (username, page_key, layout_json, hidden_blocks_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username, page_key) DO UPDATE SET
          layout_json = excluded.layout_json,
          hidden_blocks_json = excluded.hidden_blocks_json,
          updated_at = excluded.updated_at
        """,
        [
            (
                row["username"],
                row["page_key"],
                row["layout_json"],
                row["hidden_blocks_json"],
                row["updated_at"],
            )
            for row in existing_rows
        ],
    )
    core_conn.commit()


def _backfill_user_site_assignments(core_conn: sqlite3.Connection) -> None:
    try:
        with get_users_connection() as users_conn:
            user_rows = users_conn.execute("SELECT username FROM users").fetchall()
    except sqlite3.OperationalError:
        return
    if not user_rows:
        return
    core_conn.executemany(
        """
        INSERT OR IGNORE INTO user_site_assignments (username, site_key)
        VALUES (?, ?)
        """,
        [(row["username"], DEFAULT_SITE_KEY) for row in user_rows],
    )


def _ensure_user_site_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "site_key" not in columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN site_key TEXT NOT NULL DEFAULT 'JLL'"
        )
    if "admin_active_site_key" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN admin_active_site_key TEXT")


def _ensure_user_account_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}

    def _add_column(column_name: str, ddl: str) -> None:
        if column_name in columns:
            return
        logger.info("[DB] Ajout de la colonne users.%s", column_name)
        conn.execute(f"ALTER TABLE users ADD COLUMN {ddl}")
        columns.add(column_name)

    with conn:
        _add_column("email", "email TEXT")
        _add_column("email_normalized", "email_normalized TEXT")
        _add_column("status", "status TEXT")
        _add_column("display_name", "display_name TEXT")
        _add_column("created_at", "created_at TEXT")
        _add_column("approved_at", "approved_at TEXT")
        _add_column("approved_by", "approved_by INTEGER")
        _add_column("rejected_at", "rejected_at TEXT")
        _add_column("rejected_by", "rejected_by INTEGER")
        _add_column("notify_on_approval", "notify_on_approval INTEGER NOT NULL DEFAULT 0")
        _add_column("otp_email_enabled", "otp_email_enabled INTEGER NOT NULL DEFAULT 0")

        conn.execute(
            """
            UPDATE users
            SET email = NULL
            WHERE email IS NOT NULL AND TRIM(email) = ''
            """
        )
        conn.execute(
            """
            UPDATE users
            SET email_normalized = LOWER(TRIM(email))
            WHERE email IS NOT NULL AND TRIM(email) != ''
              AND (email_normalized IS NULL OR TRIM(email_normalized) = '')
            """
        )
        conn.execute(
            """
            UPDATE users
            SET status = 'active'
            WHERE status IS NULL OR TRIM(status) = ''
            """
        )
        conn.execute(
            """
            UPDATE users
            SET created_at = datetime('now')
            WHERE created_at IS NULL OR TRIM(created_at) = ''
            """
        )
        conn.execute(
            """
            UPDATE users
            SET display_name = username
            WHERE display_name IS NULL OR TRIM(display_name) = ''
            """
        )
        conn.execute(
            """
            UPDATE users
            SET notify_on_approval = 0
            WHERE notify_on_approval IS NULL
            """
        )
        conn.execute(
            """
            UPDATE users
            SET otp_email_enabled = 0
            WHERE otp_email_enabled IS NULL
            """
        )
        conn.execute(
            """
            UPDATE users
            SET status = 'disabled'
            WHERE is_active = 0 AND status = 'active'
            """
        )
        conn.execute(
            """
            UPDATE users
            SET is_active = CASE WHEN status = 'active' THEN 1 ELSE 0 END
            WHERE status IS NOT NULL
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_email_normalized ON users(email_normalized)"
        )


def _ensure_user_session_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "session_version" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        """
        UPDATE users
        SET session_version = 1
        WHERE session_version IS NULL
        """
    )


def _ensure_two_factor_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "two_factor_enabled" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN two_factor_enabled INTEGER NOT NULL DEFAULT 0")
    if "two_factor_secret_enc" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN two_factor_secret_enc TEXT")
    if "two_factor_confirmed_at" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN two_factor_confirmed_at TEXT")
    if "two_factor_recovery_hashes" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN two_factor_recovery_hashes TEXT")
    if "two_factor_last_used_at" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN two_factor_last_used_at TEXT")
    if "two_factor_required" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN two_factor_required INTEGER NOT NULL DEFAULT 0")


def _ensure_two_factor_challenge_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(two_factor_challenges)").fetchall()
    }
    if "purpose" not in columns:
        conn.execute(
            "ALTER TABLE two_factor_challenges ADD COLUMN purpose TEXT NOT NULL DEFAULT 'verify'"
        )
    if "secret_enc" not in columns:
        conn.execute("ALTER TABLE two_factor_challenges ADD COLUMN secret_enc TEXT")


def _sync_user_site_preferences() -> None:
    try:
        with get_users_connection() as users_conn, get_core_connection() as core_conn:
            users = users_conn.execute(
                "SELECT id, username FROM users"
            ).fetchall()
            if not users:
                return
            assignments = core_conn.execute(
                "SELECT username, site_key FROM user_site_assignments"
            ).fetchall()
            overrides = core_conn.execute(
                "SELECT username, site_key FROM user_site_overrides"
            ).fetchall()
    except sqlite3.OperationalError:
        return

    assignment_map = {row["username"]: row["site_key"] for row in assignments}
    override_map = {row["username"]: row["site_key"] for row in overrides}

    with get_users_connection() as users_conn:
        for row in users:
            username = row["username"]
            assignment = assignment_map.get(username)
            override = override_map.get(username)
            if assignment:
                users_conn.execute(
                    "UPDATE users SET site_key = ? WHERE username = ?",
                    (assignment, username),
                )
            else:
                users_conn.execute(
                    "UPDATE users SET site_key = COALESCE(site_key, ?) WHERE username = ?",
                    (DEFAULT_SITE_KEY, username),
                )
            if override is not None:
                users_conn.execute(
                    "UPDATE users SET admin_active_site_key = ? WHERE username = ?",
                    (override, username),
                )


def _init_stock_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS category_sizes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                    name TEXT NOT NULL COLLATE NOCASE,
                    UNIQUE(category_id, name)
                );
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    sku TEXT UNIQUE NOT NULL,
                    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                    size TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    low_stock_threshold INTEGER NOT NULL DEFAULT 0,
                    track_low_stock INTEGER NOT NULL DEFAULT 0,
                    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    delta INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS suppliers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    contact_name TEXT,
                    phone TEXT,
                    email TEXT,
                    address TEXT,
                    UNIQUE(name)
                );
                CREATE TABLE IF NOT EXISTS supplier_modules (
                    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
                    module TEXT NOT NULL,
                    PRIMARY KEY (supplier_id, module)
                );
                CREATE TABLE IF NOT EXISTS purchase_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    note TEXT,
                    auto_created INTEGER NOT NULL DEFAULT 0,
                    last_sent_at TEXT,
                    last_sent_to TEXT,
                    last_sent_by TEXT
                );
                CREATE TABLE IF NOT EXISTS purchase_order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    quantity_ordered INTEGER NOT NULL,
                    quantity_received INTEGER NOT NULL DEFAULT 0
                );
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
                CREATE TABLE IF NOT EXISTS ui_menu_prefs (
                    username TEXT NOT NULL,
                    menu_key TEXT NOT NULL,
                    order_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (username, menu_key)
                );
                CREATE TABLE IF NOT EXISTS backup_settings (
                    site_key TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    interval_minutes INTEGER NOT NULL DEFAULT 60,
                    retention_count INTEGER NOT NULL DEFAULT 3,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS collaborators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL COLLATE NOCASE,
                    department TEXT,
                    email TEXT,
                    phone TEXT
                );
                CREATE TABLE IF NOT EXISTS dotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collaborator_id INTEGER NOT NULL REFERENCES collaborators(id) ON DELETE CASCADE,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL,
                    notes TEXT,
                    perceived_at DATE DEFAULT CURRENT_DATE,
                    is_lost INTEGER NOT NULL DEFAULT 0,
                    is_degraded INTEGER NOT NULL DEFAULT 0,
                    allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                CREATE TABLE IF NOT EXISTS pharmacy_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE,
                    dosage TEXT,
                    packaging TEXT,
                    barcode TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    low_stock_threshold INTEGER NOT NULL DEFAULT 5,
                    expiration_date DATE,
                    location TEXT,
                    category_id INTEGER REFERENCES pharmacy_categories(id) ON DELETE SET NULL,
                    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL
                );
                CREATE TABLE IF NOT EXISTS pharmacy_movements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
                    delta INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS pharmacy_purchase_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    note TEXT
                );
                CREATE TABLE IF NOT EXISTS pharmacy_purchase_order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_order_id INTEGER NOT NULL REFERENCES pharmacy_purchase_orders(id) ON DELETE CASCADE,
                    pharmacy_item_id INTEGER NOT NULL REFERENCES pharmacy_items(id) ON DELETE CASCADE,
                    quantity_ordered INTEGER NOT NULL,
                    quantity_received INTEGER NOT NULL DEFAULT 0
                );
                """
    )
