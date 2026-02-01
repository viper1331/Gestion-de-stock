from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import ari_services, db, models_ari, security, services
from backend.services import system_settings
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _create_user(username: str, password: str, role: str) -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, ?, 1, 'active')
            """,
            (username, username, username.lower(), security.hash_password(password), role),
        )
        conn.commit()


def _reset_ari_tables(site: str) -> None:
    conn = db.get_ari_connection(site)
    try:
        db.init_ari_schema(conn)
        conn.execute("DELETE FROM ari_sessions")
        conn.execute("DELETE FROM ari_certifications")
        conn.commit()
    finally:
        conn.close()


def _create_session(site: str, collaborator_id: int, performed_at: datetime, status: str = "COMPLETED") -> None:
    payload = models_ari.AriSessionCreate(
        collaborator_id=collaborator_id,
        performed_at=performed_at,
        course_name="Parcours test",
        duration_seconds=600,
        start_pressure_bar=300,
        end_pressure_bar=200,
        stress_level=5,
    )
    session = ari_services.create_ari_session(
        payload,
        created_by="tester",
        site=site,
        fallback_site=site,
    )
    if status != "COMPLETED":
        conn = db.get_ari_connection(site)
        try:
            conn.execute(
                "UPDATE ari_sessions SET status = ? WHERE id = ?",
                (status, session.id),
            )
            conn.commit()
        finally:
            conn.close()


def test_ari_purge_forbidden_for_non_admin() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("ari_viewer", "password123", role="user")
    headers = login_headers(client, "ari_viewer", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        response = client.post(
            "/ari/admin/purge-sessions",
            json={"older_than_days": 1, "dry_run": True},
            headers=headers,
        )
        assert response.status_code == 403
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_purge_dry_run_only_counts() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("ari_admin_dry", "password123", role="admin")
    headers = login_headers(client, "ari_admin_dry", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        _create_session("JLL", 101, datetime.now(timezone.utc) - timedelta(days=10))
        response = client.post(
            "/ari/admin/purge-sessions",
            json={"older_than_days": 1, "dry_run": True},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        assert payload["dry_run"] is True
        assert payload["total"] == 1
        assert payload["by_site"]["JLL"] == 1
        conn = db.get_ari_connection("JLL")
        try:
            remaining = conn.execute("SELECT COUNT(*) AS total FROM ari_sessions").fetchone()
            assert remaining["total"] == 1
        finally:
            conn.close()
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_purge_deletes_non_certified_by_default() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("ari_admin_purge", "password123", role="admin")
    headers = login_headers(client, "ari_admin_purge", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        performed_at = datetime.now(timezone.utc) - timedelta(days=5)
        _create_session("JLL", 201, performed_at, status="COMPLETED")
        _create_session("JLL", 202, performed_at, status="CERTIFIED")
        response = client.post(
            "/ari/admin/purge-sessions",
            json={"older_than_days": 1, "dry_run": False},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 1
        conn = db.get_ari_connection("JLL")
        try:
            remaining = conn.execute("SELECT status FROM ari_sessions ORDER BY id").fetchall()
            assert len(remaining) == 1
            assert remaining[0]["status"] == "CERTIFIED"
        finally:
            conn.close()
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_purge_include_certified_true() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("ari_admin_full", "password123", role="admin")
    headers = login_headers(client, "ari_admin_full", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        performed_at = datetime.now(timezone.utc) - timedelta(days=5)
        _create_session("JLL", 301, performed_at, status="COMPLETED")
        _create_session("JLL", 302, performed_at, status="CERTIFIED")
        response = client.post(
            "/ari/admin/purge-sessions",
            json={"older_than_days": 1, "include_certified": True, "dry_run": False},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 2
        conn = db.get_ari_connection("JLL")
        try:
            remaining = conn.execute("SELECT COUNT(*) AS total FROM ari_sessions").fetchone()
            assert remaining["total"] == 0
        finally:
            conn.close()
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_purge_site_scoped() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _reset_ari_tables("GSM")
    _create_user("ari_admin_site", "password123", role="admin")
    headers = login_headers(client, "ari_admin_site", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        performed_at = datetime.now(timezone.utc) - timedelta(days=3)
        _create_session("JLL", 401, performed_at, status="COMPLETED")
        _create_session("GSM", 402, performed_at, status="COMPLETED")
        response = client.post(
            "/ari/admin/purge-sessions",
            json={"older_than_days": 1, "dry_run": True},
            headers={**headers, "X-ARI-SITE": "GSM"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 1
        assert payload["by_site"]["GSM"] == 1
        assert "JLL" not in payload["by_site"]
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")
