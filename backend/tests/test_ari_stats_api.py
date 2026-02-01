from fastapi.testclient import TestClient
import pytest

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


def _reset_collaborators(site: str) -> None:
    with db.get_stock_connection(site) as conn:
        conn.execute("DELETE FROM collaborators")
        conn.execute("INSERT INTO collaborators (full_name) VALUES ('Alpha One')")
        conn.execute("INSERT INTO collaborators (full_name) VALUES ('Beta Two')")
        conn.commit()


def _create_session(headers: dict[str, str], collaborator_id: int, performed_at: str) -> int:
    payload = {
        "collaborator_id": collaborator_id,
        "performed_at": performed_at,
        "course_name": "Parcours test",
        "duration_seconds": 600 if collaborator_id == 1 else 300,
        "start_pressure_bar": 300,
        "end_pressure_bar": 200 if collaborator_id == 1 else 250,
        "cylinder_capacity_l": 6.8,
        "stress_level": 5,
    }
    response = client.post("/ari/sessions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_ari_stats_overview_and_by_collaborator() -> None:
    services.ensure_database_ready()
    _reset_ari_tables("JLL")
    _reset_collaborators("JLL")
    _create_user("stats_admin", "password123", role="admin")
    headers = login_headers(client, "stats_admin", "password123")
    previous = system_settings.get_feature_ari_enabled()
    try:
        system_settings.set_feature_ari_enabled(True, "admin")
        session_1 = _create_session(headers, collaborator_id=1, performed_at="2024-06-10T12:00:00Z")
        session_2 = _create_session(headers, collaborator_id=2, performed_at="2024-06-11T12:00:00Z")
        _create_session(headers, collaborator_id=1, performed_at="2024-01-01T12:00:00Z")
        with db.get_ari_connection("JLL") as conn:
            conn.execute("UPDATE ari_sessions SET status = 'CERTIFIED' WHERE id = ?", (session_1,))
            conn.execute("UPDATE ari_sessions SET status = 'REJECTED' WHERE id = ?", (session_2,))
            conn.commit()

        overview = client.get(
            "/ari/stats/overview?from=2024-06-01&to=2024-06-30",
            headers=headers,
        )
        assert overview.status_code == 200, overview.text
        payload = overview.json()
        assert payload["total_sessions"] == 2
        assert payload["distinct_collaborators"] == 2
        assert payload["validated_count"] == 1
        assert payload["rejected_count"] == 1
        assert payload["pending_count"] == 0
        assert payload["avg_duration_min"] == pytest.approx(7.5, rel=1e-3)
        assert payload["avg_air_lpm"] == pytest.approx(68.0, rel=1e-3)
        top_names = {entry["collaborator_name"] for entry in payload["top_sessions_by_air"]}
        assert {"Alpha One", "Beta Two"}.issubset(top_names)

        by_collaborator = client.get(
            "/ari/stats/by-collaborator?from=2024-06-01&to=2024-06-30&q=Alpha",
            headers=headers,
        )
        assert by_collaborator.status_code == 200, by_collaborator.text
        rows = by_collaborator.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["collaborator_name"] == "Alpha One"
        assert rows[0]["sessions_count"] == 1
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")
