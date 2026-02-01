from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services
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
        "stress_level": 5,
    }
    response = client.post("/ari/sessions", json=payload, headers=headers)
    assert response.status_code == 201, response.text


def test_certificateur_can_decide_certification() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("cert_user", "password123", role="certificateur")
    headers = login_headers(client, "cert_user", "password123")
    admin_headers = login_headers(client, "admin", "admin123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        _create_session(admin_headers, collaborator_id=101)
        response = client.post(
            "/ari/certifications/decide",
            json={"collaborator_id": 101, "status": "APPROVED"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "APPROVED"
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_standard_user_cannot_decide_certification() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("basic_user", "password123", role="user")
    headers = login_headers(client, "basic_user", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        response = client.post(
            "/ari/certifications/decide",
            json={"collaborator_id": 55, "status": "APPROVED"},
            headers=headers,
        )
        assert response.status_code == 403
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_pending_certifications_accessible_to_certificateur() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _create_user("cert_pending", "password123", role="certificateur")
    headers = login_headers(client, "cert_pending", "password123")
    admin_headers = login_headers(client, "admin", "admin123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        _create_session(admin_headers, collaborator_id=202)
        response = client.get("/ari/certifications/pending", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert any(entry["collaborator_id"] == 202 for entry in payload)
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")
