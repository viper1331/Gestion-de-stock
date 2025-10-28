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
        conn.execute("DELETE FROM dotations")
        conn.execute("DELETE FROM collaborators")
        conn.execute("DELETE FROM suppliers")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM categories")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username != 'admin'")
        conn.commit()


def _create_user(username: str, password: str, role: str = "user") -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
            (username, security.hash_password(password), role),
        )
        conn.commit()


def _login_headers(username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


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


def test_module_permissions_control_supplier_access() -> None:
    services.ensure_database_ready()
    _create_user("worker", "worker1234", role="user")
    admin_headers = _login_headers("admin", "admin123")
    worker_headers = _login_headers("worker", "worker1234")

    blocked = client.get("/suppliers/", headers=worker_headers)
    assert blocked.status_code == 403

    grant_view = client.put(
        "/permissions/modules",
        json={"role": "user", "module": "suppliers", "can_view": True, "can_edit": False},
        headers=admin_headers,
    )
    assert grant_view.status_code == 200, grant_view.text

    empty_list = client.get("/suppliers/", headers=worker_headers)
    assert empty_list.status_code == 200
    assert empty_list.json() == []

    deny_edit = client.post(
        "/suppliers/",
        json={"name": "Supplier-Forbidden"},
        headers=worker_headers,
    )
    assert deny_edit.status_code == 403

    grant_edit = client.put(
        "/permissions/modules",
        json={"role": "user", "module": "suppliers", "can_view": True, "can_edit": True},
        headers=admin_headers,
    )
    assert grant_edit.status_code == 200

    supplier_name = f"Supplier-{uuid4().hex[:6]}"
    created = client.post(
        "/suppliers/",
        json={"name": supplier_name, "contact_name": "Jane"},
        headers=worker_headers,
    )
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["name"] == supplier_name


def test_dotation_flow_updates_stock() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    item_sku = f"SKU-{uuid4().hex[:6]}"
    created_item = client.post(
        "/items/",
        json={"name": "Kit médical", "sku": item_sku, "quantity": 5},
        headers=admin_headers,
    )
    assert created_item.status_code == 201, created_item.text
    item_id = created_item.json()["id"]
    initial_quantity = services.get_item(item_id).quantity

    collaborator = client.post(
        "/dotations/collaborators",
        json={"full_name": "Alice", "department": "OPS"},
        headers=admin_headers,
    )
    assert collaborator.status_code == 201, collaborator.text
    collaborator_id = collaborator.json()["id"]

    dotation = client.post(
        "/dotations/dotations",
        json={"collaborator_id": collaborator_id, "item_id": item_id, "quantity": 2},
        headers=admin_headers,
    )
    assert dotation.status_code == 201, dotation.text
    dotation_id = dotation.json()["id"]

    after_allocation = services.get_item(item_id)
    assert after_allocation.quantity == initial_quantity - 2

    listed = client.get(
        f"/dotations/dotations?collaborator_id={collaborator_id}", headers=admin_headers
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    delete = client.delete(
        f"/dotations/dotations/{dotation_id}?restock=1",
        headers=admin_headers,
    )
    assert delete.status_code == 204, delete.text

    after_restock = services.get_item(item_id)
    assert after_restock.quantity == initial_quantity


def test_pharmacy_crud_cycle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    create = client.post(
        "/pharmacy/",
        json={
            "name": "Doliprane",
            "dosage": "500mg",
            "quantity": 10,
            "expiration_date": "2025-12-31",
            "location": "Armoire A",
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    pharmacy_id = create.json()["id"]

    update = client.put(
        f"/pharmacy/{pharmacy_id}",
        json={"quantity": 7},
        headers=admin_headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["quantity"] == 7

    listing = client.get("/pharmacy/", headers=admin_headers)
    assert listing.status_code == 200
    assert any(entry["id"] == pharmacy_id for entry in listing.json())

    delete = client.delete(f"/pharmacy/{pharmacy_id}", headers=admin_headers)
    assert delete.status_code == 204

    missing = client.get(f"/pharmacy/{pharmacy_id}", headers=admin_headers)
    assert missing.status_code == 404
