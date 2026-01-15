from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
import pyotp
import urllib.parse

from backend.app import app
from backend.core import db, security, services, two_factor_crypto

client = TestClient(app)


def _create_user(
    username: str,
    password: str,
    role: str = "user",
    with_permissions: bool = True,
) -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
            (username, security.hash_password(password), role),
        )
        user_id = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()["id"]
        conn.execute(
            "DELETE FROM module_permissions WHERE user_id = ? AND module = ?",
            (user_id, "clothing"),
        )
        if with_permissions:
            conn.execute(
                "INSERT INTO module_permissions (user_id, module, can_view, can_edit) VALUES (?, ?, 1, 1)",
                (user_id, "clothing"),
            )
        conn.commit()


def _login_headers(username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    if payload.get("status") == "totp_enroll_required":
        parsed = urllib.parse.urlparse(payload["otpauth_uri"])
        secret = urllib.parse.parse_qs(parsed.query)["secret"][0]
        code = pyotp.TOTP(secret).now()
        confirm = client.post(
            "/auth/totp/enroll/confirm",
            json={"challenge_token": payload["challenge_token"], "code": code},
        )
        assert confirm.status_code == 200, confirm.text
        token = confirm.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    if payload.get("status") == "totp_required":
        with db.get_users_connection() as conn:
            row = conn.execute(
                "SELECT two_factor_secret_enc FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        assert row and row["two_factor_secret_enc"], "Missing 2FA secret for user"
        secret = two_factor_crypto.decrypt_secret(str(row["two_factor_secret_enc"]))
        code = pyotp.TOTP(secret).now()
        verify = client.post(
            "/auth/totp/verify",
            json={"challenge_token": payload["challenge_token"], "code": code},
        )
        assert verify.status_code == 200, verify.text
        token = verify.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    raise AssertionError(f"Unexpected login response: {payload}")


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
