from pathlib import Path
import sys

from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, security, services

client = TestClient(app)


def setup_module(_: object) -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM categories")
        conn.commit()


def test_seed_admin_recreates_missing_user() -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = 'admin'")
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
            ("demo", security.hash_password("demo1234"), "user"),
        )
        conn.commit()

    services.seed_default_admin()
    admin = services.authenticate("admin", "admin123")
    assert admin is not None
    assert admin.role == "admin"


def test_seed_admin_repairs_invalid_state() -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = 'admin'")
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 0)",
            ("admin", "notahash", "user"),
        )
        conn.commit()

    services.seed_default_admin()
    admin = services.authenticate("admin", "admin123")
    assert admin is not None
    assert admin.role == "admin"
    assert admin.is_active is True


def test_healthcheck() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_returns_tokens() -> None:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123", "remember_me": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_record_movement_updates_quantity() -> None:
    login = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123", "remember_me": False},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sku = f"SKU-{uuid4().hex[:8]}"
    create = client.post(
        "/items/",
        json={
            "name": "Test Item",
            "sku": sku,
            "quantity": 5,
            "low_stock_threshold": 1,
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    item_id = create.json()["id"]

    movement = client.post(
        f"/items/{item_id}/movements",
        json={"delta": -2, "reason": "vente"},
        headers=headers,
    )
    assert movement.status_code == 204, movement.text

    updated = services.get_item(item_id)
    assert updated.quantity == 3
    history = services.fetch_movements(item_id)
    assert history and history[0].delta == -2


def test_record_movement_unknown_item_returns_404() -> None:
    login = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123", "remember_me": False},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/items/99999/movements",
        json={"delta": 1},
        headers=headers,
    )
    assert response.status_code == 404
