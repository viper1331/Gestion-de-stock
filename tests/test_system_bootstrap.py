from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core import db, services
from backend.core.system_config import rebuild_cors_middleware
from backend.tests.auth_helpers import login_headers


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def _site_db_path(site_key: str) -> Path:
        return tmp_path / f"{site_key}.db"

    monkeypatch.setattr(db, "get_site_db_path", lambda site_key: _site_db_path(site_key))
    services._db_initialized = False
    from backend.app import app

    rebuild_cors_middleware(app, ["http://example.com"])
    services.ensure_site_database_ready("GSM")
    with TestClient(app) as client_instance:
        yield client_instance


def _admin_auth_headers(client: TestClient) -> dict[str, str]:
    return login_headers(client, "admin", "admin123")


def test_cors_preflight_allows_login(client: TestClient) -> None:
    response = client.options(
        "/auth/login",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code in {200, 204}
    assert response.headers.get("access-control-allow-origin") == "http://example.com"


def test_public_system_config_is_available(client: TestClient) -> None:
    response = client.get("/system/public-config")
    assert response.status_code == 200
    payload = response.json()
    assert "backend_url" in payload
    assert "backend_url_public" in payload
    assert "frontend_url" in payload


def test_private_system_config_requires_auth(client: TestClient) -> None:
    response = client.get("/system/config")
    assert response.status_code == 401


def test_site_migrations_create_required_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    site_db_path = tmp_path / "GSM.db"
    monkeypatch.setattr(db, "get_site_db_path", lambda site_key: site_db_path)

    services.ensure_site_database_ready("GSM")

    conn = sqlite3.connect(site_db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('link_categories')"
        )
        names = {row[0] for row in cursor.fetchall()}
    finally:
        conn.close()

    assert {"link_categories"} <= names


def test_core_init_creates_backup_settings_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "USERS_DB_PATH", data_dir / "users.db")
    monkeypatch.setattr(db, "CORE_DB_PATH", data_dir / "core.db")
    services._db_initialized = False

    services.ensure_database_ready()

    with db.get_core_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_settings'"
        )
        assert cursor.fetchone() is not None


def test_backup_settings_and_link_categories_endpoints(client: TestClient) -> None:
    headers = {**_admin_auth_headers(client), "X-Site-Key": "GSM"}

    response = client.put(
        "/admin/backup/settings",
        headers=headers,
        json={"enabled": True, "interval_minutes": 60, "retention_count": 3},
    )
    assert response.status_code == 200

    response = client.post(
        "/link-categories",
        headers=headers,
        json={
            "module": "vehicle_qr",
            "key": "test-link",
            "label": "Test link",
            "placeholder": "https://example.com",
            "help_text": None,
            "is_required": False,
            "sort_order": 99,
            "is_active": True,
        },
    )
    assert response.status_code == 201
