from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _create_user(
    username: str,
    password: str,
    role: str = "user",
    with_permissions: bool = True,
    module: str = "clothing",
    can_edit: bool = True,
) -> None:
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
        user_id = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()["id"]
        conn.execute(
            "DELETE FROM module_permissions WHERE user_id = ? AND module = ?",
            (user_id, module),
        )
        if with_permissions:
            conn.execute(
                "INSERT INTO module_permissions (user_id, module, can_view, can_edit) VALUES (?, ?, 1, ?)",
                (user_id, module, 1 if can_edit else 0),
            )
        conn.commit()


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def test_user_layout_roundtrip() -> None:
    _create_user("layout-user", "layout-pass")
    headers = _login_headers("layout-user", "layout-pass")

    payload: dict[str, Any] = {
        "layout": {
            "lg": [
                {"i": "inventory-main", "x": 0, "y": 0, "w": 12, "h": 8},
                {"i": "inventory-orders", "x": 0, "y": 8, "w": 12, "h": 6},
            ]
        },
        "hiddenBlocks": ["inventory-orders"],
    }

    response = client.put(
        "/user-layouts/module:clothing:inventory", json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pageKey"] == "module:clothing:inventory"
    assert data["layout"]["lg"][0]["i"] == "inventory-main"
    assert data["hiddenBlocks"] == ["inventory-orders"]

    get_response = client.get(
        "/user-layouts/module:clothing:inventory", headers=headers
    )
    assert get_response.status_code == 200, get_response.text
    get_data = get_response.json()
    assert get_data["hiddenBlocks"] == ["inventory-orders"]
    assert get_data["layout"]["lg"][1]["i"] == "inventory-orders"


def test_pharmacy_layout_roundtrip() -> None:
    _create_user("pharmacy-layout-user", "layout-pass", module="pharmacy")
    headers = _login_headers("pharmacy-layout-user", "layout-pass")

    payload: dict[str, Any] = {
        "layout": {
            "lg": [
                {"i": "pharmacy-header", "x": 0, "y": 0, "w": 12, "h": 4},
                {"i": "pharmacy-items", "x": 0, "y": 4, "w": 12, "h": 12},
                {"i": "pharmacy-movements", "x": 0, "y": 16, "w": 12, "h": 6},
            ]
        },
        "hiddenBlocks": ["pharmacy-movements"],
    }

    response = client.put(
        "/user-layouts/module:pharmacy:inventory", json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["pageKey"] == "module:pharmacy:inventory"
    assert data["layout"]["lg"][0]["i"] == "pharmacy-header"
    assert data["hiddenBlocks"] == ["pharmacy-movements"]

    get_response = client.get(
        "/user-layouts/module:pharmacy:inventory", headers=headers
    )
    assert get_response.status_code == 200, get_response.text
    get_data = get_response.json()
    assert get_data["hiddenBlocks"] == ["pharmacy-movements"]
    assert get_data["layout"]["lg"][1]["i"] == "pharmacy-items"


def test_unknown_block_is_rejected() -> None:
    _create_user("layout-user-2", "layout-pass")
    headers = _login_headers("layout-user-2", "layout-pass")

    payload = {
        "layout": {"lg": [{"i": "unknown-block", "x": 0, "y": 0, "w": 4, "h": 4}]},
        "hiddenBlocks": [],
    }

    response = client.put(
        "/user-layouts/module:clothing:inventory", json=payload, headers=headers
    )
    assert response.status_code == 400, response.text


def test_layout_normalization_clamps_values() -> None:
    _create_user("layout-user-3", "layout-pass")
    headers = _login_headers("layout-user-3", "layout-pass")

    payload = {
        "layout": {
            "lg": [
                {
                    "i": "inventory-main",
                    "x": -3,
                    "y": -5,
                    "w": 50,
                    "h": 0,
                }
            ]
        },
        "hiddenBlocks": [],
    }

    response = client.put(
        "/user-layouts/module:clothing:inventory", json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    item = data["layout"]["lg"][0]
    assert item["x"] == 0
    assert item["y"] == 0
    assert item["w"] == 12
    assert item["h"] == 1


def test_layout_strips_blocks_without_permissions() -> None:
    _create_user("layout-user-4", "layout-pass", with_permissions=False)
    headers = _login_headers("layout-user-4", "layout-pass")

    payload = {
        "layout": {
            "lg": [
                {"i": "inventory-main", "x": 0, "y": 0, "w": 12, "h": 8},
                {"i": "inventory-orders", "x": 0, "y": 8, "w": 12, "h": 6},
            ]
        },
        "hiddenBlocks": ["inventory-main"],
    }

    response = client.put(
        "/user-layouts/module:clothing:inventory", json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["layout"]["lg"] == []
    assert data["hiddenBlocks"] == []


def test_pharmacy_layout_strips_blocks_without_permissions() -> None:
    _create_user(
        "pharmacy-layout-user-2", "layout-pass", with_permissions=False, module="pharmacy"
    )
    headers = _login_headers("pharmacy-layout-user-2", "layout-pass")

    payload = {
        "layout": {
            "lg": [
                {"i": "pharmacy-header", "x": 0, "y": 0, "w": 12, "h": 4},
                {"i": "pharmacy-items", "x": 0, "y": 4, "w": 12, "h": 12},
            ]
        },
        "hiddenBlocks": ["pharmacy-items"],
    }

    response = client.put(
        "/user-layouts/module:pharmacy:inventory", json=payload, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["layout"]["lg"] == []
    assert data["hiddenBlocks"] == []


def test_user_layouts_are_site_scoped() -> None:
    _create_user(
        "layout-site-user",
        "layout-pass",
        role="admin",
        with_permissions=False,
        module="pharmacy",
    )
    headers = _login_headers("layout-site-user", "layout-pass")

    payload = {
        "layout": {
            "lg": [{"i": "pharmacy-header", "x": 0, "y": 0, "w": 12, "h": 4}]
        },
        "hiddenBlocks": [],
    }

    response = client.put(
        "/user-layouts/module:pharmacy:inventory",
        json=payload,
        headers={**headers, "X-Site-Key": "JLL"},
    )
    assert response.status_code == 200, response.text

    other_site_response = client.get(
        "/user-layouts/module:pharmacy:inventory",
        headers={**headers, "X-Site-Key": "GSM"},
    )
    assert other_site_response.status_code == 200, other_site_response.text
    other_site_data = other_site_response.json()
    assert other_site_data["layout"] == {}
