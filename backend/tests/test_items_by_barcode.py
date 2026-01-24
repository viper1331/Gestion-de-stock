from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, models, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _create_admin_user(username: str, password: str) -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, 'admin', 1, 'active')
            """,
            (username, username, username.lower(), security.hash_password(password)),
        )
        conn.commit()


def _auth_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def test_items_by_barcode_found() -> None:
    username = "barcode_admin"
    password = "password"
    _create_admin_user(username, password)
    headers = _auth_headers(username, password)

    sku = f"BC-{uuid4().hex[:8]}"
    services.create_item(models.ItemCreate(name="Gants nitrile", sku=sku, quantity=5))

    response = client.get(
        "/items/by-barcode",
        params={"module": "clothing", "barcode": f"{sku[:3]} {sku[3:]}".lower()},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["name"] == "Gants nitrile"


def test_items_by_barcode_missing() -> None:
    username = "barcode_admin_missing"
    password = "password"
    _create_admin_user(username, password)
    headers = _auth_headers(username, password)

    response = client.get(
        "/items/by-barcode",
        params={"module": "clothing", "barcode": f"UNKNOWN-{uuid4().hex[:6]}"},
        headers=headers,
    )

    assert response.status_code == 404, response.text


def test_items_by_barcode_conflict() -> None:
    username = "barcode_admin_conflict"
    password = "password"
    _create_admin_user(username, password)
    headers = _auth_headers(username, password)

    base = f"DUP{uuid4().hex[:6]}".upper()
    sku_with_space = f"{base[:3]} {base[3:]}"
    services.create_item(models.ItemCreate(name="Masque A", sku=sku_with_space, quantity=1))
    services.create_item(models.ItemCreate(name="Masque B", sku=base, quantity=2))

    response = client.get(
        "/items/by-barcode",
        params={"module": "clothing", "barcode": base},
        headers=headers,
    )

    assert response.status_code == 409, response.text
    payload = response.json()
    assert len(payload["matches"]) == 2
