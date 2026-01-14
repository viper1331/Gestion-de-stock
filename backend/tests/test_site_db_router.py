from __future__ import annotations

from pathlib import Path

from backend.core import db, security, services, sites


def _create_user(username: str, role: str = "user") -> None:
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
            (username, security.hash_password("pass"), role),
        )
        conn.commit()


def _init_test_dbs(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    snapshot_dir = data_dir / "inventory_snapshots"
    snapshot_dir.mkdir()
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "STOCK_DB_PATH", data_dir / "stock.db")
    monkeypatch.setattr(db, "USERS_DB_PATH", data_dir / "users.db")
    monkeypatch.setattr(db, "CORE_DB_PATH", data_dir / "core.db")
    monkeypatch.setattr(services, "_MIGRATION_LOCK_PATH", data_dir / "schema_migration.lock")
    monkeypatch.setattr(services, "_INVENTORY_SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(services, "_db_initialized", False)
    services.ensure_database_ready()


def test_site_selection_follows_assignment_and_override(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("worker", role="user")
    _create_user("admin-site", role="admin")

    sites.set_user_site_assignment("worker", "GSM")
    sites.set_user_site_assignment("admin-site", "JLL")
    sites.set_user_site_override("admin-site", "ST_ELOIS")

    worker = services.get_user("worker")
    admin = services.get_user("admin-site")

    assert worker is not None
    assert admin is not None

    resolved_worker = sites.resolve_site_key(worker, header_site_key=None)
    assert resolved_worker == "GSM"

    resolved_admin_override = sites.resolve_site_key(admin, header_site_key=None)
    assert resolved_admin_override == "ST_ELOIS"

    resolved_admin_header = sites.resolve_site_key(admin, header_site_key="CENTRAL_ENTITY")
    assert resolved_admin_header == "CENTRAL_ENTITY"


def test_non_admin_header_is_ignored(tmp_path, monkeypatch) -> None:
    _init_test_dbs(tmp_path, monkeypatch)
    _create_user("user-site", role="user")
    sites.set_user_site_assignment("user-site", "JLL")
    user = services.get_user("user-site")
    assert user is not None

    resolved = sites.resolve_site_key(user, header_site_key="GSM")
    assert resolved == "JLL"
