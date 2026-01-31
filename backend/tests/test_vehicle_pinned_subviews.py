from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _create_user(username: str, password: str, role: str = "user") -> int:
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
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        assert row is not None
        return int(row["id"])


def _grant_module_permission(user_id: int, module: str, *, can_view: bool, can_edit: bool) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            "DELETE FROM module_permissions WHERE user_id = ? AND module = ?",
            (user_id, module),
        )
        conn.execute(
            "INSERT INTO module_permissions (user_id, module, can_view, can_edit) VALUES (?, ?, ?, ?)",
            (user_id, module, int(can_view), int(can_edit)),
        )
        conn.commit()


def _create_vehicle(headers: dict[str, str]) -> int:
    payload = {
        "name": f"Véhicule test {uuid4().hex[:6]}",
        "vehicle_type": "incendie",
        "sizes": ["Cabine", "Cabine - Casier 1", "Cabine - Casier 2"],
    }
    response = client.post("/vehicle-inventory/categories/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_vehicle_pinned_subviews_permission_denied() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    user_id = _create_user("pinned_user", "password123", role="user")
    _grant_module_permission(user_id, "vehicle_inventory", can_view=True, can_edit=False)
    user_headers = login_headers(client, "pinned_user", "password123")

    denied = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/pinned-subviews",
        json={"subview_id": "Cabine - Casier 1"},
        headers=user_headers,
    )
    assert denied.status_code == 403, denied.text


def test_vehicle_pinned_subviews_invalid_id_rejected() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    response = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/pinned-subviews",
        json={"subview_id": "Coffre - B"},
        headers=admin_headers,
    )
    assert response.status_code == 400, response.text


def test_vehicle_pinned_subviews_idempotent_add() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    response = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/pinned-subviews",
        json={"subview_id": "Cabine - Casier 1"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/pinned-subviews",
        json={"subview_id": "Cabine - Casier 1"},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["pinned"] == ["CABINE - CASIER 1"]
