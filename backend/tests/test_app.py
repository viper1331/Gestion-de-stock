from pathlib import Path
import sys

import io
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
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM pharmacy_movements")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM dotations")
        conn.execute("DELETE FROM collaborators")
        conn.execute("DELETE FROM suppliers")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM vehicle_movements")
        conn.execute("DELETE FROM vehicle_items")
        conn.execute("DELETE FROM vehicle_photos")
        conn.execute("DELETE FROM vehicle_view_settings")
        conn.execute("DELETE FROM vehicle_category_sizes")
        conn.execute("DELETE FROM vehicle_categories")
        conn.execute("DELETE FROM remise_movements")
        conn.execute("DELETE FROM remise_items")
        conn.execute("DELETE FROM remise_category_sizes")
        conn.execute("DELETE FROM remise_categories")
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM category_sizes")
        conn.execute("DELETE FROM categories")
        conn.execute("DELETE FROM pharmacy_category_sizes")
        conn.execute("DELETE FROM pharmacy_categories")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username != 'admin'")
        conn.commit()


def _create_user(username: str, password: str, role: str = "user") -> int:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "INSERT INTO users (username, password, role, is_active) VALUES (?, ?, ?, 1)",
            (username, security.hash_password(password), role),
        )
        conn.commit()
        cur = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row["id"])


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


def test_low_stock_triggers_auto_purchase_order() -> None:
    login = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123", "remember_me": False},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    supplier_resp = client.post(
        "/suppliers/",
        json={"name": f"Supplier-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert supplier_resp.status_code == 201, supplier_resp.text
    supplier_id = supplier_resp.json()["id"]

    sku = f"SKU-{uuid4().hex[:8]}"
    create_item_resp = client.post(
        "/items/",
        json={
            "name": "Gants",
            "sku": sku,
            "quantity": 5,
            "low_stock_threshold": 10,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert create_item_resp.status_code == 201, create_item_resp.text
    item_id = create_item_resp.json()["id"]

    movement = client.post(
        f"/items/{item_id}/movements",
        json={"delta": -4, "reason": "Utilisation"},
        headers=headers,
    )
    assert movement.status_code == 204, movement.text

    with db.get_stock_connection() as conn:
        rows = conn.execute(
            """
            SELECT po.id, po.auto_created, po.status, poi.quantity_ordered
            FROM purchase_orders AS po
            JOIN purchase_order_items AS poi ON poi.purchase_order_id = po.id
            WHERE poi.item_id = ?
            """,
            (item_id,),
        ).fetchall()
    assert len(rows) == 1
    auto_po = rows[0]
    assert auto_po["auto_created"] == 1
    assert auto_po["status"].upper() == "PENDING"
    assert auto_po["quantity_ordered"] == 9

    second_movement = client.post(
        f"/items/{item_id}/movements",
        json={"delta": -1, "reason": "Utilisation"},
        headers=headers,
    )
    assert second_movement.status_code == 204, second_movement.text

    with db.get_stock_connection() as conn:
        rows_after = conn.execute(
            """
            SELECT po.id, poi.quantity_ordered
            FROM purchase_orders AS po
            JOIN purchase_order_items AS poi ON poi.purchase_order_id = po.id
            WHERE poi.item_id = ?
            """,
            (item_id,),
        ).fetchall()
    assert len(rows_after) == 1
    order_id = rows_after[0]["id"]
    assert rows_after[0]["quantity_ordered"] == 10

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items WHERE purchase_order_id = ?", (order_id,))
        conn.execute("DELETE FROM purchase_orders WHERE id = ?", (order_id,))
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        conn.commit()


def test_no_auto_purchase_order_without_supplier() -> None:
    login = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123", "remember_me": False},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    sku = f"SKU-{uuid4().hex[:8]}"
    create_item_resp = client.post(
        "/items/",
        json={
            "name": "Masques",
            "sku": sku,
            "quantity": 2,
            "low_stock_threshold": 5,
        },
        headers=headers,
    )
    assert create_item_resp.status_code == 201, create_item_resp.text
    item_id = create_item_resp.json()["id"]

    movement = client.post(
        f"/items/{item_id}/movements",
        json={"delta": -4, "reason": "Utilisation"},
        headers=headers,
    )
    assert movement.status_code == 204, movement.text

    with db.get_stock_connection() as conn:
        rows = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM purchase_order_items AS poi
            JOIN purchase_orders AS po ON po.id = poi.purchase_order_id
            WHERE poi.item_id = ?
        """,
            (item_id,),
        ).fetchone()
    assert rows["cnt"] == 0

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.commit()


def test_manual_purchase_order_flow() -> None:
    headers = _login_headers("admin", "admin123")

    supplier_resp = client.post(
        "/suppliers/",
        json={"name": f"Supplier-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert supplier_resp.status_code == 201, supplier_resp.text
    supplier_id = supplier_resp.json()["id"]

    item_resp = client.post(
        "/items/",
        json={
            "name": "Casque",
            "sku": f"SKU-{uuid4().hex[:6]}",
            "quantity": 2,
            "low_stock_threshold": 1,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    item_id = item_resp.json()["id"]

    order_resp = client.post(
        "/purchase-orders/",
        json={
            "supplier_id": supplier_id,
            "status": "ORDERED",
            "note": "Test commande",
            "items": [{"item_id": item_id, "quantity_ordered": 5}],
        },
        headers=headers,
    )
    assert order_resp.status_code == 201, order_resp.text
    order_data = order_resp.json()
    order_id = order_data["id"]
    assert order_data["items"][0]["quantity_ordered"] == 5
    assert order_data["items"][0]["quantity_received"] == 0

    receive_resp = client.post(
        f"/purchase-orders/{order_id}/receive",
        json={"items": [{"item_id": item_id, "quantity": 3}]},
        headers=headers,
    )
    assert receive_resp.status_code == 200, receive_resp.text
    receive_data = receive_resp.json()
    assert receive_data["status"] == "PARTIALLY_RECEIVED"
    assert receive_data["items"][0]["quantity_received"] == 3

    final_resp = client.post(
        f"/purchase-orders/{order_id}/receive",
        json={"items": [{"item_id": item_id, "quantity": 5}]},
        headers=headers,
    )
    assert final_resp.status_code == 200, final_resp.text
    final_data = final_resp.json()
    assert final_data["status"] == "RECEIVED"
    assert final_data["items"][0]["quantity_received"] == 5

    inventory_item = services.get_item(item_id)
    assert inventory_item.quantity == 7

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items WHERE purchase_order_id = ?", (order_id,))
        conn.execute("DELETE FROM purchase_orders WHERE id = ?", (order_id,))
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.execute("DELETE FROM suppliers WHERE id = ?", (supplier_id,))
        conn.commit()


def test_pharmacy_purchase_order_flow() -> None:
    headers = _login_headers("admin", "admin123")

    item_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Paracétamol",
            "dosage": "500mg",
            "packaging": "Boîte",
            "quantity": 10,
            "low_stock_threshold": 4,
            "expiration_date": None,
            "location": "Pharma",
        },
        headers=headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    pharmacy_item_id = item_resp.json()["id"]

    order_resp = client.post(
        "/pharmacy/orders/",
        json={
            "status": "ORDERED",
            "note": "Réapprovisionnement",
            "items": [
                {"pharmacy_item_id": pharmacy_item_id, "quantity_ordered": 12}
            ],
        },
        headers=headers,
    )
    assert order_resp.status_code == 201, order_resp.text
    order_id = order_resp.json()["id"]

    receive_resp = client.post(
        f"/pharmacy/orders/{order_id}/receive",
        json={
            "items": [
                {"pharmacy_item_id": pharmacy_item_id, "quantity": 12}
            ]
        },
        headers=headers,
    )
    assert receive_resp.status_code == 200, receive_resp.text
    data = receive_resp.json()
    assert data["status"] == "RECEIVED"
    assert data["items"][0]["quantity_received"] == 12

    pharmacy_item = services.get_pharmacy_item(pharmacy_item_id)
    assert pharmacy_item.quantity == 22

    with db.get_stock_connection() as conn:
        conn.execute(
            "DELETE FROM pharmacy_purchase_order_items WHERE purchase_order_id = ?",
            (order_id,),
        )
        conn.execute(
            "DELETE FROM pharmacy_purchase_orders WHERE id = ?",
            (order_id,),
        )
        conn.execute("DELETE FROM pharmacy_items WHERE id = ?", (pharmacy_item_id,))
        conn.commit()

def test_module_permissions_control_supplier_access() -> None:
    services.ensure_database_ready()
    worker_id = _create_user("worker", "worker1234", role="user")
    admin_headers = _login_headers("admin", "admin123")
    worker_headers = _login_headers("worker", "worker1234")

    blocked = client.get("/suppliers/", headers=worker_headers)
    assert blocked.status_code == 403

    grant_view = client.put(
        "/permissions/modules",
        json={
            "user_id": worker_id,
            "module": "suppliers",
            "can_view": True,
            "can_edit": False,
        },
        headers=admin_headers,
    )
    assert grant_view.status_code == 200, grant_view.text

    grant_clothing = client.put(
        "/permissions/modules",
        json={
            "user_id": worker_id,
            "module": "clothing",
            "can_view": True,
            "can_edit": False,
        },
        headers=admin_headers,
    )
    assert grant_clothing.status_code == 200, grant_clothing.text

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
        json={
            "user_id": worker_id,
            "module": "suppliers",
            "can_view": True,
            "can_edit": True,
        },
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
    assert data["modules"] == ["suppliers"]


def test_supplier_module_filtering() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    apparel_resp = client.post(
        "/suppliers/",
        json={"name": f"Apparel-{uuid4().hex[:6]}"},
        headers=admin_headers,
    )
    assert apparel_resp.status_code == 201, apparel_resp.text
    apparel_data = apparel_resp.json()

    pharmacy_resp = client.post(
        "/suppliers/",
        json={"name": f"Pharma-{uuid4().hex[:6]}", "modules": ["pharmacy"]},
        headers=admin_headers,
    )
    assert pharmacy_resp.status_code == 201, pharmacy_resp.text
    pharmacy_data = pharmacy_resp.json()

    listing = client.get("/suppliers/", headers=admin_headers)
    assert listing.status_code == 200
    names = {entry["name"] for entry in listing.json()}
    assert apparel_data["name"] in names
    assert pharmacy_data["name"] in names

    apparel_only = client.get("/suppliers/?module=suppliers", headers=admin_headers)
    assert apparel_only.status_code == 200
    apparel_names = {entry["name"] for entry in apparel_only.json()}
    assert apparel_data["name"] in apparel_names
    assert pharmacy_data["name"] not in apparel_names

    pharmacy_only = client.get("/suppliers/?module=pharmacy", headers=admin_headers)
    assert pharmacy_only.status_code == 200
    pharmacy_names = {entry["name"] for entry in pharmacy_only.json()}
    assert pharmacy_data["name"] in pharmacy_names
    assert apparel_data["name"] not in pharmacy_names

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM suppliers WHERE id IN (?, ?)", (apparel_data["id"], pharmacy_data["id"]))
        conn.commit()


def test_available_modules_listing_requires_admin() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    response = client.get("/permissions/modules/available", headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert any(entry["key"] == "suppliers" for entry in data)

    username = f"user-{uuid4().hex[:6]}"
    _create_user(username, "Testpass123", role="user")
    worker_headers = _login_headers(username, "Testpass123")
    forbidden = client.get("/permissions/modules/available", headers=worker_headers)
    assert forbidden.status_code == 403


def test_admin_user_management_flow() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    username = f"user-{uuid4().hex[:6]}"

    create = client.post(
        "/users/",
        json={"username": username, "password": "Testpass123", "role": "user"},
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    user_id = create.json()["id"]

    listing = client.get("/users/", headers=admin_headers)
    assert listing.status_code == 200
    assert any(entry["username"] == username for entry in listing.json())

    promote = client.put(
        f"/users/{user_id}",
        json={"role": "admin", "is_active": False},
        headers=admin_headers,
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["role"] == "admin"
    assert promote.json()["is_active"] is False

    reset = client.put(
        f"/users/{user_id}",
        json={"password": "Newpass123", "is_active": True},
        headers=admin_headers,
    )
    assert reset.status_code == 200, reset.text

    headers_new = _login_headers(username, "Newpass123")
    assert "Authorization" in headers_new

    delete = client.delete(f"/users/{user_id}", headers=admin_headers)
    assert delete.status_code == 204, delete.text


def test_admin_cannot_create_duplicate_user() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    username = f"dup-{uuid4().hex[:6]}"

    first = client.post(
        "/users/",
        json={"username": username, "password": "Testpass123", "role": "user"},
        headers=admin_headers,
    )
    assert first.status_code == 201, first.text
    user_id = first.json()["id"]

    duplicate = client.post(
        "/users/",
        json={"username": username, "password": "Another123", "role": "user"},
        headers=admin_headers,
    )
    assert duplicate.status_code == 400

    cleanup = client.delete(f"/users/{user_id}", headers=admin_headers)
    assert cleanup.status_code == 204, cleanup.text


def test_non_admin_cannot_manage_users() -> None:
    services.ensure_database_ready()
    username = f"worker-{uuid4().hex[:6]}"
    _create_user(username, "Workerpass123", role="user")
    worker_headers = _login_headers(username, "Workerpass123")

    forbidden_list = client.get("/users/", headers=worker_headers)
    assert forbidden_list.status_code == 403

    forbidden_create = client.post(
        "/users/",
        json={"username": "blocked", "password": "Blocked123", "role": "user"},
        headers=worker_headers,
    )
    assert forbidden_create.status_code == 403

    admin_headers = _login_headers("admin", "admin123")
    listing = client.get("/users/", headers=admin_headers)
    worker_entry = next(entry for entry in listing.json() if entry["username"] == username)
    remove_worker = client.delete(f"/users/{worker_entry['id']}", headers=admin_headers)
    assert remove_worker.status_code == 204


def test_cannot_modify_default_admin_protection() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    listing = client.get("/users/", headers=admin_headers)
    assert listing.status_code == 200
    admin_entry = next(entry for entry in listing.json() if entry["username"] == "admin")

    downgrade = client.put(
        f"/users/{admin_entry['id']}",
        json={"role": "user"},
        headers=admin_headers,
    )
    assert downgrade.status_code == 400

    deactivate = client.put(
        f"/users/{admin_entry['id']}",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert deactivate.status_code == 400

    delete_admin = client.delete(f"/users/{admin_entry['id']}", headers=admin_headers)
    assert delete_admin.status_code == 400


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
    dotation_data = dotation.json()
    assert dotation_data["is_lost"] is False
    assert dotation_data["is_degraded"] is False
    assert dotation_data["is_obsolete"] is False
    assert dotation_data["perceived_at"]

    after_allocation = services.get_item(item_id)
    assert after_allocation.quantity == initial_quantity - 2

    movements_after_allocation = client.get(
        f"/items/{item_id}/movements", headers=admin_headers
    )
    assert movements_after_allocation.status_code == 200, movements_after_allocation.text
    history = movements_after_allocation.json()
    assert history
    assert history[0]["delta"] == -2
    assert history[0]["reason"] == "Dotation - Alice"

    listed = client.get(
        f"/dotations/dotations?collaborator_id={collaborator_id}", headers=admin_headers
    )
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert len(listed_payload) == 1
    assert listed_payload[0]["is_obsolete"] is False

    delete = client.delete(
        f"/dotations/dotations/{dotation_id}?restock=1",
        headers=admin_headers,
    )
    assert delete.status_code == 204, delete.text

    after_restock = services.get_item(item_id)
    assert after_restock.quantity == initial_quantity

    movements_after_restock = client.get(
        f"/items/{item_id}/movements", headers=admin_headers
    )
    assert movements_after_restock.status_code == 200, movements_after_restock.text
    restock_history = movements_after_restock.json()
    assert {entry["reason"] for entry in restock_history} >= {
        "Dotation - Alice",
        "Retour dotation - Alice",
    }


def test_update_dotation_adjusts_stock_and_movements() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    first_item = client.post(
        "/items/",
        json={"name": "Radio", "sku": f"SKU-{uuid4().hex[:6]}", "quantity": 6},
        headers=admin_headers,
    )
    assert first_item.status_code == 201, first_item.text
    first_item_id = first_item.json()["id"]
    second_item = client.post(
        "/items/",
        json={"name": "Lampe", "sku": f"SKU-{uuid4().hex[:6]}", "quantity": 4},
        headers=admin_headers,
    )
    assert second_item.status_code == 201, second_item.text
    second_item_id = second_item.json()["id"]

    collaborator = client.post(
        "/dotations/collaborators",
        json={"full_name": "Bob", "department": "OPS"},
        headers=admin_headers,
    )
    assert collaborator.status_code == 201, collaborator.text
    collaborator_id = collaborator.json()["id"]

    created = client.post(
        "/dotations/dotations",
        json={"collaborator_id": collaborator_id, "item_id": first_item_id, "quantity": 2},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    dotation_id = created.json()["id"]

    update_quantity = client.put(
        f"/dotations/dotations/{dotation_id}",
        json={"quantity": 3, "notes": "Ajout d'accessoires"},
        headers=admin_headers,
    )
    assert update_quantity.status_code == 200, update_quantity.text
    updated_payload = update_quantity.json()
    assert updated_payload["quantity"] == 3
    assert updated_payload["notes"] == "Ajout d'accessoires"

    first_item_movements = client.get(
        f"/items/{first_item_id}/movements", headers=admin_headers
    )
    assert first_item_movements.status_code == 200, first_item_movements.text
    first_history = first_item_movements.json()
    assert any(entry["reason"] == "Ajustement dotation - Bob" for entry in first_history)

    transfer_update = client.put(
        f"/dotations/dotations/{dotation_id}",
        json={"item_id": second_item_id, "quantity": 1, "is_lost": True},
        headers=admin_headers,
    )
    assert transfer_update.status_code == 200, transfer_update.text
    transfer_body = transfer_update.json()
    assert transfer_body["item_id"] == second_item_id
    assert transfer_body["quantity"] == 1
    assert transfer_body["is_lost"] is True

    first_after_transfer = services.get_item(first_item_id)
    second_after_transfer = services.get_item(second_item_id)
    assert first_after_transfer.quantity == 6
    assert second_after_transfer.quantity == 3

    second_item_movements = client.get(
        f"/items/{second_item_id}/movements", headers=admin_headers
    )
    assert second_item_movements.status_code == 200, second_item_movements.text
    second_history = second_item_movements.json()
    assert any(entry["reason"] == "Ajustement dotation - Bob" for entry in second_history)


def test_dotation_obsolete_and_alerts() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    item_sku = f"SKU-{uuid4().hex[:6]}"

    created_item = client.post(
        "/items/",
        json={"name": "Casque", "sku": item_sku, "quantity": 3},
        headers=admin_headers,
    )
    assert created_item.status_code == 201, created_item.text
    item_id = created_item.json()["id"]

    collaborator = client.post(
        "/dotations/collaborators",
        json={"full_name": "Bob"},
        headers=admin_headers,
    )
    assert collaborator.status_code == 201, collaborator.text
    collaborator_id = collaborator.json()["id"]

    perceived_at = "2020-01-01"
    dotation = client.post(
        "/dotations/dotations",
        json={
            "collaborator_id": collaborator_id,
            "item_id": item_id,
            "quantity": 1,
            "perceived_at": perceived_at,
            "is_lost": True,
            "is_degraded": False,
        },
        headers=admin_headers,
    )
    assert dotation.status_code == 201, dotation.text
    dotation_body = dotation.json()
    assert dotation_body["is_lost"] is True
    assert dotation_body["is_degraded"] is False
    assert dotation_body["perceived_at"] == perceived_at
    assert dotation_body["is_obsolete"] is True

    listing = client.get("/dotations/dotations", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    records = listing.json()
    created = next(entry for entry in records if entry["id"] == dotation_body["id"])
    assert created["is_obsolete"] is True
    assert created["is_lost"] is True


def test_pharmacy_crud_cycle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    create = client.post(
        "/pharmacy/",
        json={
            "name": "Doliprane",
            "dosage": "500mg",
            "packaging": "Boîte de 10",
            "barcode": "3400934058479",
            "quantity": 10,
            "low_stock_threshold": 6,
            "expiration_date": "2025-12-31",
            "location": "Armoire A",
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    pharmacy_id = create.json()["id"]
    assert create.json()["packaging"] == "Boîte de 10"
    assert create.json()["barcode"] == "3400934058479"
    assert create.json()["low_stock_threshold"] == 6

    update = client.put(
        f"/pharmacy/{pharmacy_id}",
        json={"quantity": 7},
        headers=admin_headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["quantity"] == 7
    assert update.json()["packaging"] == "Boîte de 10"
    assert update.json()["barcode"] == "3400934058479"
    assert update.json()["low_stock_threshold"] == 6

    listing = client.get("/pharmacy/", headers=admin_headers)
    assert listing.status_code == 200
    assert any(
        entry["id"] == pharmacy_id
        and entry["packaging"] == "Boîte de 10"
        and entry["low_stock_threshold"] == 6
        for entry in listing.json()
    )

    delete = client.delete(f"/pharmacy/{pharmacy_id}", headers=admin_headers)
    assert delete.status_code == 204

    missing = client.get(f"/pharmacy/{pharmacy_id}", headers=admin_headers)
    assert missing.status_code == 404


def test_pharmacy_barcode_uniqueness_validation() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    barcode_value = f"34009{uuid4().hex[:6]}"
    first = client.post(
        "/pharmacy/",
        json={
            "name": "Paracétamol",
            "dosage": "500mg",
            "packaging": "Boîte de 16",
            "barcode": barcode_value,
            "quantity": 12,
            "expiration_date": "2026-01-15",
            "location": "Armoire B",
        },
        headers=admin_headers,
    )
    assert first.status_code == 201, first.text

    duplicate = client.post(
        "/pharmacy/",
        json={
            "name": "Ibuprofène",
            "dosage": "400mg",
            "packaging": "Boîte de 12",
            "barcode": barcode_value,
            "quantity": 8,
        },
        headers=admin_headers,
    )
    assert duplicate.status_code == 400, duplicate.text

    unique = client.post(
        "/pharmacy/",
        json={
            "name": "Arnica",
            "dosage": "Crème",
            "packaging": "Tube",
            "barcode": f"34009{uuid4().hex[:6]}",
            "quantity": 3,
        },
        headers=admin_headers,
    )
    assert unique.status_code == 201, unique.text
    other_id = unique.json()["id"]

    conflict = client.put(
        f"/pharmacy/{other_id}",
        json={"barcode": barcode_value},
        headers=admin_headers,
    )
    assert conflict.status_code == 400, conflict.text


def test_pharmacy_movement_management() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    create = client.post(
        "/pharmacy/",
        json={
            "name": "Solution hydroalcoolique",
            "quantity": 10,
        },
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    item_id = create.json()["id"]

    movement = client.post(
        f"/pharmacy/{item_id}/movements",
        json={"delta": -3, "reason": "Inventaire"},
        headers=admin_headers,
    )
    assert movement.status_code == 204, movement.text

    updated = services.get_pharmacy_item(item_id)
    assert updated.quantity == 7

    history = client.get(f"/pharmacy/{item_id}/movements", headers=admin_headers)
    assert history.status_code == 200, history.text
    entries = history.json()
    assert entries and entries[0]["delta"] == -3
    assert entries[0]["reason"] == "Inventaire"

    missing = client.post(
        "/pharmacy/999999/movements",
        json={"delta": 1},
        headers=admin_headers,
    )
    assert missing.status_code == 404


def test_pharmacy_category_crud() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    create = client.post(
        "/pharmacy/categories/",
        json={"name": "Antibiotiques", "sizes": ["10mg", "20mg", "10mg"]},
        headers=admin_headers,
    )
    assert create.status_code == 201, create.text
    category_id = create.json()["id"]
    assert create.json()["sizes"] == ["10MG", "20MG"]

    listing = client.get("/pharmacy/categories/", headers=admin_headers)
    assert listing.status_code == 200
    categories = {entry["id"]: entry for entry in listing.json()}
    assert categories[category_id]["sizes"] == ["10MG", "20MG"]

    update = client.put(
        f"/pharmacy/categories/{category_id}",
        json={"sizes": ["100mg", "50mg"]},
        headers=admin_headers,
    )
    assert update.status_code == 200, update.text
    assert sorted(update.json()["sizes"], key=str.lower) == sorted(["50MG", "100MG"], key=str.lower)

    delete = client.delete(f"/pharmacy/categories/{category_id}", headers=admin_headers)
    assert delete.status_code == 204, delete.text

    remaining = client.get("/pharmacy/categories/", headers=admin_headers)
    remaining_ids = {entry["id"] for entry in remaining.json()}
    assert category_id not in remaining_ids


def test_create_category_with_sizes() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    category_name = f"Cat-{uuid4().hex[:6]}"

    response = client.post(
        "/categories/",
        json={"name": category_name, "sizes": [" XS", "S", "M", "m"]},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == category_name
    expected_sizes = sorted(["XS", "S", "M"], key=str.lower)
    assert data["sizes"] == expected_sizes

    listing = client.get("/categories/", headers=admin_headers)
    assert listing.status_code == 200
    categories = listing.json()
    assert any(entry["name"] == category_name and entry["sizes"] == expected_sizes for entry in categories)


def test_update_category_sizes() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    category_name = f"Cat-{uuid4().hex[:6]}"

    created = client.post(
        "/categories/",
        json={"name": category_name, "sizes": ["38", "39"]},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]

    update = client.put(
        f"/categories/{category_id}",
        json={"sizes": ["39", "40", " 40 ", "41", ""]},
        headers=admin_headers,
    )
    assert update.status_code == 200, update.text
    updated = update.json()
    assert updated["id"] == category_id
    assert updated["sizes"] == sorted(["39", "40", "41"], key=str.lower)

    listing = client.get("/categories/", headers=admin_headers)
    assert listing.status_code == 200
    categories = {entry["id"]: entry for entry in listing.json()}
    assert categories[category_id]["sizes"] == sorted(["39", "40", "41"], key=str.lower)


def test_vehicle_inventory_crud_cycle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Remise-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_sku = f"REM-{uuid4().hex[:6]}"
    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot remis",
            "sku": remise_sku,
            "quantity": 5,
            "low_stock_threshold": 1,
            "category_id": remise_category_id,
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item_id = remise_item_resp.json()["id"]

    category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Parc-{uuid4().hex[:6]}", "sizes": ["UTILITAIRE", "SUV"]},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    created_category = category_resp.json()
    assert created_category["image_url"] is None
    category_id = created_category["id"]

    upload_resp = client.post(
        f"/vehicle-inventory/categories/{category_id}/image",
        headers=admin_headers,
        files={"file": ("vehicule.png", b"demo", "image/png")},
    )
    assert upload_resp.status_code == 200, upload_resp.text
    category_with_image = upload_resp.json()
    assert category_with_image["id"] == category_id
    assert category_with_image["image_url"].startswith("/media/")

    remove_image_resp = client.delete(
        f"/vehicle-inventory/categories/{category_id}/image",
        headers=admin_headers,
    )
    assert remove_image_resp.status_code == 200, remove_image_resp.text
    category_without_image = remove_image_resp.json()
    assert category_without_image["image_url"] is None

    sku = f"VEH-{uuid4().hex[:6]}"
    create_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Camion atelier",
            "sku": sku,
            "quantity": 2,
            "low_stock_threshold": 1,
            "category_id": category_id,
            "size": "UTILITAIRE",
            "remise_item_id": remise_item_id,
        },
        headers=admin_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    item_id = create_resp.json()["id"]
    assert create_resp.json()["remise_item_id"] == remise_item_id
    remise_after_create = services.get_remise_item(remise_item_id)
    assert remise_after_create.quantity == 3

    movement_resp = client.post(
        f"/vehicle-inventory/{item_id}/movements",
        json={"delta": 1, "reason": "Maintenance"},
        headers=admin_headers,
    )
    assert movement_resp.status_code == 204, movement_resp.text

    listing = client.get("/vehicle-inventory/", headers=admin_headers)
    assert listing.status_code == 200
    assert any(entry["id"] == item_id and entry["quantity"] == 3 for entry in listing.json())

    history = client.get(f"/vehicle-inventory/{item_id}/movements", headers=admin_headers)
    assert history.status_code == 200
    history_entries = history.json()
    assert history_entries and history_entries[0]["delta"] == 1
    remise_after_movement = services.get_remise_item(remise_item_id)
    assert remise_after_movement.quantity == 3

    delete_resp = client.delete(f"/vehicle-inventory/{item_id}", headers=admin_headers)
    assert delete_resp.status_code == 204

    category_delete = client.delete(
        f"/vehicle-inventory/categories/{category_id}", headers=admin_headers
    )
    assert category_delete.status_code == 204


def test_vehicle_inventory_updates_adjust_remise_stock() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Depot-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_a_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot A",
            "sku": f"REM-A-{uuid4().hex[:6]}",
            "quantity": 10,
            "low_stock_threshold": 1,
            "category_id": remise_category_id,
        },
        headers=admin_headers,
    )
    assert remise_a_resp.status_code == 201, remise_a_resp.text
    remise_a_id = remise_a_resp.json()["id"]

    remise_b_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot B",
            "sku": f"REM-B-{uuid4().hex[:6]}",
            "quantity": 5,
            "low_stock_threshold": 1,
            "category_id": remise_category_id,
        },
        headers=admin_headers,
    )
    assert remise_b_resp.status_code == 201, remise_b_resp.text
    remise_b_id = remise_b_resp.json()["id"]

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Vehicules-{uuid4().hex[:6]}", "sizes": ["FOURGON"]},
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    vehicle_item_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Camion 1",
            "sku": f"VEH-{uuid4().hex[:6]}",
            "quantity": 2,
            "low_stock_threshold": 1,
            "category_id": vehicle_category_id,
            "remise_item_id": remise_a_id,
        },
        headers=admin_headers,
    )
    assert vehicle_item_resp.status_code == 201, vehicle_item_resp.text
    vehicle_item_id = vehicle_item_resp.json()["id"]

    remise_a_after_create = services.get_remise_item(remise_a_id)
    assert remise_a_after_create.quantity == 8

    increase_resp = client.put(
        f"/vehicle-inventory/{vehicle_item_id}",
        json={"quantity": 5},
        headers=admin_headers,
    )
    assert increase_resp.status_code == 200, increase_resp.text
    remise_a_after_increase = services.get_remise_item(remise_a_id)
    assert remise_a_after_increase.quantity == 5

    decrease_resp = client.put(
        f"/vehicle-inventory/{vehicle_item_id}",
        json={"quantity": 1},
        headers=admin_headers,
    )
    assert decrease_resp.status_code == 200, decrease_resp.text
    remise_a_after_decrease = services.get_remise_item(remise_a_id)
    assert remise_a_after_decrease.quantity == 9

    for item in services.list_vehicle_items():
        if item.remise_item_id == remise_b_id and item.id != vehicle_item_id:
            delete_existing = client.delete(
                f"/vehicle-inventory/{item.id}",
                headers=admin_headers,
            )
            assert delete_existing.status_code == 204

    reassign_resp = client.put(
        f"/vehicle-inventory/{vehicle_item_id}",
        json={"remise_item_id": remise_b_id},
        headers=admin_headers,
    )
    assert reassign_resp.status_code == 200, reassign_resp.text
    remise_a_final = services.get_remise_item(remise_a_id)
    remise_b_final = services.get_remise_item(remise_b_id)
    assert remise_a_final.quantity == 10
    assert remise_b_final.quantity == 4

    delete_vehicle_resp = client.delete(
        f"/vehicle-inventory/{vehicle_item_id}",
        headers=admin_headers,
    )
    assert delete_vehicle_resp.status_code == 204

    cleanup_vehicle_category = client.delete(
        f"/vehicle-inventory/categories/{vehicle_category_id}",
        headers=admin_headers,
    )
    assert cleanup_vehicle_category.status_code == 204

    cleanup_remise_a = client.delete(
        f"/remise-inventory/{remise_a_id}",
        headers=admin_headers,
    )
    assert cleanup_remise_a.status_code == 204

    cleanup_remise_b = client.delete(
        f"/remise-inventory/{remise_b_id}",
        headers=admin_headers,
    )
    assert cleanup_remise_b.status_code == 204

    cleanup_remise_category = client.delete(
        f"/remise-inventory/categories/{remise_category_id}",
        headers=admin_headers,
    )
    assert cleanup_remise_category.status_code == 204


def test_vehicle_inventory_allows_multiple_assignments_from_remise_stock() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Stock-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Pack de cônes",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 2,
            "low_stock_threshold": 0,
            "category_id": remise_category_id,
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item = remise_item_resp.json()
    remise_item_id = remise_item["id"]

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Véhicule-{uuid4().hex[:6]}", "sizes": []},
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    payload = {
        "name": remise_item["name"],
        "sku": remise_item["sku"],
        "quantity": 1,
        "category_id": vehicle_category_id,
        "size": "VUE PRINCIPALE",
        "position_x": 0.1,
        "position_y": 0.2,
        "remise_item_id": remise_item_id,
    }

    first_assign = client.post(
        "/vehicle-inventory/",
        json=payload,
        headers=admin_headers,
    )
    assert first_assign.status_code == 201, first_assign.text

    remise_after_first = services.get_remise_item(remise_item_id)
    assert remise_after_first.quantity == 1

    second_assign = client.post(
        "/vehicle-inventory/",
        json=payload,
        headers=admin_headers,
    )
    assert second_assign.status_code == 201, second_assign.text

    remise_after_second = services.get_remise_item(remise_item_id)
    assert remise_after_second.quantity == 0

    items_listing = client.get("/vehicle-inventory/", headers=admin_headers)
    assert items_listing.status_code == 200
    data = items_listing.json()
    assigned = [entry for entry in data if entry["category_id"] == vehicle_category_id]
    available = [entry for entry in data if entry["category_id"] is None]
    assert len(assigned) == 2
    assert any(entry["remise_item_id"] == remise_item_id for entry in available)
    template_entry = next(entry for entry in available if entry["remise_item_id"] == remise_item_id)
    assert template_entry["remise_quantity"] == 0

    exhausted_assign = client.post(
        "/vehicle-inventory/",
        json=payload,
        headers=admin_headers,
    )
    assert exhausted_assign.status_code == 400
    assert "Stock insuffisant" in exhausted_assign.json()["detail"]

    cleanup_vehicle = client.delete(
        f"/vehicle-inventory/categories/{vehicle_category_id}",
        headers=admin_headers,
    )
    assert cleanup_vehicle.status_code == 204
    cleanup_remise_item = client.delete(
        f"/remise-inventory/{remise_item_id}",
        headers=admin_headers,
    )
    assert cleanup_remise_item.status_code == 204
    cleanup_remise_category = client.delete(
        f"/remise-inventory/categories/{remise_category_id}",
        headers=admin_headers,
    )
    assert cleanup_remise_category.status_code == 204
def test_vehicle_view_background_configuration() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Fourgon-{uuid4().hex[:6]}", "sizes": ["CABINE"]},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    category_id = category_resp.json()["id"]

    photo = services.add_vehicle_photo(io.BytesIO(b"bg"), "fond.png")

    assign_resp = client.put(
        f"/vehicle-inventory/categories/{category_id}/views/background",
        json={"name": "cabine", "photo_id": photo.id},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assigned = assign_resp.json()
    assert assigned["background_photo_id"] == photo.id
    assert assigned["name"] == "CABINE"
    assert assigned["background_url"]

    categories = client.get("/vehicle-inventory/categories/", headers=admin_headers)
    assert categories.status_code == 200
    category_data = next(entry for entry in categories.json() if entry["id"] == category_id)
    view_configs = category_data["view_configs"]
    assert view_configs and view_configs[0]["background_photo_id"] == photo.id

    clear_resp = client.put(
        f"/vehicle-inventory/categories/{category_id}/views/background",
        json={"name": "CABINE", "photo_id": None},
        headers=admin_headers,
    )
    assert clear_resp.status_code == 200, clear_resp.text
    assert clear_resp.json()["background_photo_id"] is None

    refreshed = client.get("/vehicle-inventory/categories/", headers=admin_headers)
    refreshed_category = next(
        entry for entry in refreshed.json() if entry["id"] == category_id
    )
    refreshed_view = refreshed_category["view_configs"][0]
    assert refreshed_view["background_photo_id"] is None

    default_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Simple-{uuid4().hex[:6]}", "sizes": []},
        headers=admin_headers,
    )
    assert default_category_resp.status_code == 201, default_category_resp.text
    default_category_id = default_category_resp.json()["id"]

    default_photo = services.add_vehicle_photo(io.BytesIO(b"default"), "default.png")

    default_assign = client.put(
        f"/vehicle-inventory/categories/{default_category_id}/views/background",
        json={"name": "Vue principale", "photo_id": default_photo.id},
        headers=admin_headers,
    )
    assert default_assign.status_code == 200, default_assign.text
    default_data = default_assign.json()
    assert default_data["name"] == "VUE PRINCIPALE"
    assert default_data["background_photo_id"] == default_photo.id

    default_category = client.get(
        "/vehicle-inventory/categories/", headers=admin_headers
    ).json()
    default_entry = next(entry for entry in default_category if entry["id"] == default_category_id)
    default_config = default_entry["view_configs"][0]
    assert default_config["name"] == "VUE PRINCIPALE"
    assert default_config["background_photo_id"] == default_photo.id

    cleanup_resp = client.delete(
        f"/vehicle-inventory/categories/{category_id}", headers=admin_headers
    )
    assert cleanup_resp.status_code == 204
    cleanup_default = client.delete(
        f"/vehicle-inventory/categories/{default_category_id}", headers=admin_headers
    )
    assert cleanup_default.status_code == 204


def test_remise_inventory_crud_cycle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Remise-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    category_id = category_resp.json()["id"]

    sku = f"REM-{uuid4().hex[:6]}"
    create_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot remis",
            "sku": sku,
            "quantity": 5,
            "low_stock_threshold": 0,
            "category_id": category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    item_id = create_resp.json()["id"]

    movement_resp = client.post(
        f"/remise-inventory/{item_id}/movements",
        json={"delta": -2, "reason": "Sortie"},
        headers=admin_headers,
    )
    assert movement_resp.status_code == 204, movement_resp.text

    listing = client.get("/remise-inventory/", headers=admin_headers)
    assert listing.status_code == 200
    assert any(entry["id"] == item_id and entry["quantity"] == 3 for entry in listing.json())

    history = client.get(f"/remise-inventory/{item_id}/movements", headers=admin_headers)
    assert history.status_code == 200
    entries = history.json()
    assert entries and entries[0]["delta"] == -2

    delete_resp = client.delete(f"/remise-inventory/{item_id}", headers=admin_headers)
    assert delete_resp.status_code == 204

    category_delete = client.delete(
        f"/remise-inventory/categories/{category_id}", headers=admin_headers
    )
    assert category_delete.status_code == 204
