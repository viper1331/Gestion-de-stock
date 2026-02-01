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


def test_vehicle_subview_pins_permission_denied() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    user_id = _create_user("subview_pin_user", "password123", role="user")
    _grant_module_permission(user_id, "vehicle_inventory", can_view=True, can_edit=False)
    user_headers = login_headers(client, "subview_pin_user", "password123")

    denied = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins",
        json={"subview_id": "Cabine - Casier 1", "x_pct": 0.4, "y_pct": 0.6},
        headers=user_headers,
    )
    assert denied.status_code == 403, denied.text


def test_vehicle_subview_pins_crud_and_clamp() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    created = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins",
        json={"subview_id": "Cabine - Casier 1", "x_pct": 1.8, "y_pct": -0.2},
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["x_pct"] == 1.0
    assert payload["y_pct"] == 0.0

    listing = client.get(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins",
        headers=admin_headers,
    )
    assert listing.status_code == 200, listing.text
    pins = listing.json()["pins"]
    assert len(pins) == 1
    pin_id = pins[0]["id"]

    updated = client.patch(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins/{pin_id}",
        json={"x_pct": -0.4, "y_pct": 2.3},
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    updated_payload = updated.json()
    assert updated_payload["x_pct"] == 0.0
    assert updated_payload["y_pct"] == 1.0

    removed = client.delete(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins/{pin_id}",
        headers=admin_headers,
    )
    assert removed.status_code == 204, removed.text

    listing_after = client.get(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins",
        headers=admin_headers,
    )
    assert listing_after.status_code == 200, listing_after.text
    assert listing_after.json()["pins"] == []


def test_vehicle_subview_pins_duplicate_rejected() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    response = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins",
        json={"subview_id": "Cabine - Casier 1", "x_pct": 0.4, "y_pct": 0.6},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    duplicate = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins",
        json={"subview_id": "Cabine - Casier 1", "x_pct": 0.2, "y_pct": 0.1},
        headers=admin_headers,
    )
    assert duplicate.status_code == 409, duplicate.text


def test_vehicle_subview_pins_scoped_by_site() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    created = client.post(
        f"/vehicles/{vehicle_id}/views/CABINE/subview-pins",
        json={"subview_id": "Cabine - Casier 1", "x_pct": 0.45, "y_pct": 0.5},
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text

    gsm_headers = {**admin_headers, "X-Site-Key": "GSM"}
    gsm_vehicle_id = _create_vehicle(gsm_headers)
    gsm_listing = client.get(
        f"/vehicles/{gsm_vehicle_id}/views/CABINE/subview-pins",
        headers=gsm_headers,
    )
    assert gsm_listing.status_code == 200, gsm_listing.text
    assert gsm_listing.json()["pins"] == []
