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


def _create_session(headers: dict[str, str], collaborator_id: int) -> None:
    payload = {
        "collaborator_id": collaborator_id,
        "performed_at": "2024-06-01T12:00:00Z",
        "course_name": "Parcours test",
        "duration_seconds": 600,
        "start_pressure_bar": 300,
        "end_pressure_bar": 200,
        "cylinder_capacity_l": 6.8,
        "stress_level": 5,
    }
    response = client.post("/ari/sessions", json=payload, headers=headers)
    assert response.status_code == 201, response.text


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_certification_expiry_is_calculated() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("ari_admin", "password123", role="admin")
    headers = login_headers(client, "ari_admin", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        ari_services.update_ari_settings(
            models_ari.AriSettingsUpdate(
                feature_enabled=True,
                stress_required=True,
                rpe_enabled=False,
                min_sessions_for_certification=1,
                cert_validity_days=10,
                cert_expiry_warning_days=2,
            ),
            "JLL",
            fallback_site="JLL",
        )
        _create_session(headers, collaborator_id=301)
        response = client.post(
            "/ari/certifications/decide",
            json={"collaborator_id": 301, "status": "APPROVED"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        certified_at = _parse_iso(payload["certified_at"])
        expires_at = _parse_iso(payload["expires_at"])
        delta = expires_at - certified_at
        assert delta.days == 10
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_alert_states_and_reset_flow() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("ari_admin_reset", "password123", role="admin")
    _create_user("ari_basic", "password123", role="user")
    admin_headers = login_headers(client, "ari_admin_reset", "password123")
    user_headers = login_headers(client, "ari_basic", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        ari_services.update_ari_settings(
            models_ari.AriSettingsUpdate(
                feature_enabled=True,
                stress_required=True,
                rpe_enabled=False,
                min_sessions_for_certification=1,
                cert_validity_days=30,
                cert_expiry_warning_days=10,
            ),
            "JLL",
            fallback_site="JLL",
        )
        _create_session(admin_headers, collaborator_id=302)
        conn = db.get_ari_connection("JLL")
        try:
            now = datetime.now(timezone.utc)
            conn.execute(
                """
                UPDATE ari_certifications
                SET certified_at = ?, expires_at = ?
                WHERE collaborator_id = ?
                """,
                (
                    now.isoformat().replace("+00:00", "Z"),
                    (now + timedelta(days=5)).isoformat().replace("+00:00", "Z"),
                    302,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        response = client.get("/ari/certifications/302", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["alert_state"] == "expiring_soon"

        conn = db.get_ari_connection("JLL")
        try:
            now = datetime.now(timezone.utc)
            conn.execute(
                """
                UPDATE ari_certifications
                SET certified_at = ?, expires_at = ?
                WHERE collaborator_id = ?
                """,
                (
                    (now - timedelta(days=40)).isoformat().replace("+00:00", "Z"),
                    (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                    302,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        response = client.get("/ari/certifications/302", headers=admin_headers)
        assert response.status_code == 200, response.text
        assert response.json()["alert_state"] == "expired"

        reset_response = client.post(
            "/ari/certifications/302/reset",
            json={"reason": "Erreur de saisie"},
            headers=admin_headers,
        )
        assert reset_response.status_code == 200, reset_response.text
        reset_payload = reset_response.json()
        assert reset_payload["status"] == "NONE"
        assert reset_payload["certified_at"] is None
        assert reset_payload["expires_at"] is None
        assert reset_payload["reset_at"] is not None
        assert reset_payload["reset_reason"] == "Erreur de saisie"

        forbidden = client.post(
            "/ari/certifications/302/reset",
            json={"reason": "Tentative"},
            headers=user_headers,
        )
        assert forbidden.status_code == 403
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")
