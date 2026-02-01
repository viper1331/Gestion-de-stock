from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services
from backend.services import system_settings
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _create_user(username: str, password: str, role: str = "user") -> None:
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


def test_admin_settings_requires_admin() -> None:
    _create_user("settings_user", "password123", role="user")
    headers = login_headers(client, "settings_user", "password123")

    response = client.get("/admin/settings", headers=headers)
    assert response.status_code == 403

    response = client.patch("/admin/settings", json={"feature_ari_enabled": True}, headers=headers)
    assert response.status_code == 403


def test_admin_settings_can_read_and_patch() -> None:
    services.ensure_database_ready()
    headers = login_headers(client, "admin", "admin123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        update = client.patch("/admin/settings", json={"feature_ari_enabled": True}, headers=headers)
        assert update.status_code == 200
        assert update.json()["feature_ari_enabled"] is True

        read_back = client.get("/admin/settings", headers=headers)
        assert read_back.status_code == 200
        assert read_back.json()["feature_ari_enabled"] is True
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_endpoints_return_404_when_disabled() -> None:
    services.ensure_database_ready()
    headers = login_headers(client, "admin", "admin123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(False, "admin")
        response = client.get("/ari/sessions", headers=headers)
        assert response.status_code == 404
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")
