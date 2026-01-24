import asyncio
import time
from contextlib import closing
import json
import sqlite3
import sys
import zipfile

import io
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, models, security, services
from backend.core.storage import MEDIA_ROOT
from backend.tests.auth_helpers import login_headers
from backend.services import barcode as barcode_service, update_service
from backend.services.backup_manager import create_backup_archive, restore_backup_from_zip
from backend.services.backup_scheduler import backup_scheduler

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
        conn.execute("DELETE FROM pharmacy_lot_items")
        conn.execute("DELETE FROM pharmacy_lots")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM custom_field_definitions")
        conn.execute("DELETE FROM vehicle_movements")
        conn.execute("DELETE FROM vehicle_pharmacy_lot_assignments")
        conn.execute("DELETE FROM vehicle_items")
        conn.execute("DELETE FROM vehicle_applied_lots")
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
        conn.execute("DELETE FROM message_rate_limits")
        conn.execute("DELETE FROM message_recipients")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM users WHERE username != 'admin'")
        conn.commit()


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
        cur = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row["id"])


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def _configure_barcode_assets(
    monkeypatch: Any, tmp_path: Path, site_key: str | None = None
) -> Path:
    assets_root = tmp_path / "assets"
    monkeypatch.setattr(barcode_service, "ASSETS_ROOT", assets_root)
    return barcode_service.get_site_assets_dir(site_key or db.DEFAULT_SITE_KEY)


_TRANSPARENT_PIXEL = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\xda"
    b"c\xfc\xff\x9f\xa1\x1e\x00\x07\x82\x02\x7f=\x07\xd0\xdd\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_seed_admin_recreates_missing_user() -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = 'admin'")
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, ?, 1, 'active')
            """,
            ("demo", "demo", "demo", security.hash_password("demo1234"), "user"),
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
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, ?, 0, 'disabled')
            """,
            ("admin", "admin", "admin", "notahash", "user"),
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
    assert data["status"] == "totp_enroll_required"
    assert data.get("challenge_token")
    assert data.get("otpauth_uri")


def test_record_movement_updates_quantity() -> None:
    headers = _login_headers("admin", "admin123")

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
    headers = _login_headers("admin", "admin123")

    response = client.post(
        "/items/99999/movements",
        json={"delta": 1},
        headers=headers,
    )
    assert response.status_code == 404


def test_low_stock_triggers_auto_purchase_order() -> None:
    headers = _login_headers("admin", "admin123")

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
    headers = _login_headers("admin", "admin123")

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
    line_id = order_data["items"][0]["id"]
    assert order_data["items"][0]["quantity_ordered"] == 5
    assert order_data["items"][0]["quantity_received"] == 0

    receive_resp = client.post(
        f"/purchase-orders/{order_id}/receive",
        json={"lines": [{"line_id": line_id, "qty": 3}]},
        headers=headers,
    )
    assert receive_resp.status_code == 200, receive_resp.text
    receive_data = receive_resp.json()
    assert receive_data["status"] == "PARTIALLY_RECEIVED"
    assert receive_data["items"][0]["quantity_received"] == 3

    final_resp = client.post(
        f"/purchase-orders/{order_id}/receive",
        json={"lines": [{"line_id": line_id, "qty": 2}]},
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
    order_data = order_resp.json()
    order_id = order_data["id"]
    line_id = order_data["items"][0]["id"]

    receive_resp = client.post(
        f"/pharmacy/orders/{order_id}/receive",
        json={
            "lines": [
                {"line_id": line_id, "qty": 12}
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
    assert any(entry["key"] == "barcode" for entry in data)

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


def test_barcode_listing_and_assets(monkeypatch: Any, tmp_path: Path) -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    assets_dir = _configure_barcode_assets(monkeypatch, tmp_path)

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items")
        conn.commit()

    services.create_item(models.ItemCreate(name="Article Alpha", sku="SKU-ALPHA"))
    services.create_item(models.ItemCreate(name="Article Beta", sku="SKU-BETA"))

    generated = barcode_service.generate_barcode_png("SKU-ALPHA", site_key=db.DEFAULT_SITE_KEY)
    assert generated is not None and generated.exists()
    assert generated.stat().st_size > 0

    generated_two = barcode_service.generate_barcode_png("SKU-BETA", site_key=db.DEFAULT_SITE_KEY)
    assert generated_two is not None and generated_two.exists()
    assert generated_two.stat().st_size > 0

    listing = client.get("/barcode", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert {entry["sku"] for entry in data} == {"SKU-ALPHA", "SKU-BETA"}
    assert all(entry["filename"].endswith(".png") for entry in data)
    assert all("modified_at" in entry for entry in data)
    assert all(entry["module"] == "clothing" for entry in data)
    assert all("asset_path" in entry for entry in data)

    first_filename = data[0]["filename"]
    asset = client.get(f"/barcode/assets/{first_filename}", headers=admin_headers)
    assert asset.status_code == 200, asset.text
    assert asset.headers["content-type"] == "image/png"

    missing = client.get("/barcode/assets/inconnu.png", headers=admin_headers)
    assert missing.status_code == 404


def test_barcode_assets_scoped_by_site(monkeypatch: Any, tmp_path: Path) -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    assets_root = tmp_path / "assets"
    monkeypatch.setattr(barcode_service, "ASSETS_ROOT", assets_root)

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items")
        conn.commit()

    services.create_item(models.ItemCreate(name="Article Partagé", sku="SKU-SHARED"))
    services.create_item(models.ItemCreate(name="Article GSM", sku="SKU-GSM"))
    gsm_token = db.set_current_site("GSM")
    try:
        with db.get_stock_connection() as conn:
            conn.execute("DELETE FROM items")
            conn.commit()
        services.create_item(models.ItemCreate(name="Article Partagé", sku="SKU-SHARED"))
        services.create_item(models.ItemCreate(name="Article GSM", sku="SKU-GSM"))
    finally:
        db.reset_current_site(gsm_token)

    jll_response = client.post("/barcode/generate/SKU-SHARED", headers=admin_headers)
    assert jll_response.status_code == 200, jll_response.text

    gsm_headers = {**admin_headers, "X-Site-Key": "GSM"}
    gsm_response = client.post("/barcode/generate/SKU-SHARED", headers=gsm_headers)
    assert gsm_response.status_code == 200, gsm_response.text

    gsm_unique = client.post("/barcode/generate/SKU-GSM", headers=gsm_headers)
    assert gsm_unique.status_code == 200, gsm_unique.text

    jll_dir = assets_root / "sites" / "JLL" / "barcodes"
    gsm_dir = assets_root / "sites" / "GSM" / "barcodes"

    assert (jll_dir / "SKU-SHARED.png").exists()
    assert (gsm_dir / "SKU-SHARED.png").exists()
    assert (gsm_dir / "SKU-GSM.png").exists()
    assert not (jll_dir / "SKU-GSM.png").exists()

    jll_listing = client.get("/barcode", headers=admin_headers)
    assert jll_listing.status_code == 200, jll_listing.text
    jll_skus = {entry["sku"] for entry in jll_listing.json()}
    assert "SKU-GSM" not in jll_skus

    gsm_listing = client.get("/barcode", headers=gsm_headers)
    assert gsm_listing.status_code == 200, gsm_listing.text
    gsm_skus = {entry["sku"] for entry in gsm_listing.json()}
    assert "SKU-GSM" in gsm_skus


def test_barcode_generation_requires_dependency(
    monkeypatch: Any, tmp_path: Path
) -> None:
    services.ensure_database_ready()
    assets_dir = _configure_barcode_assets(monkeypatch, tmp_path)
    monkeypatch.delenv("ALLOW_PLACEHOLDER_BARCODE", raising=False)
    monkeypatch.setattr(barcode_service, "_barcode_lib", None)
    monkeypatch.setattr(barcode_service, "ImageWriter", None)

    with pytest.raises(RuntimeError) as excinfo:
        barcode_service.generate_barcode_png("SKU-MISSING", site_key=db.DEFAULT_SITE_KEY)

    assert "python-barcode" in str(excinfo.value)
    assert list(assets_dir.glob("*.png")) == []


def test_barcode_generation_does_not_fallback_to_placeholder(
    monkeypatch: Any, tmp_path: Path
) -> None:
    services.ensure_database_ready()
    assets_dir = _configure_barcode_assets(monkeypatch, tmp_path)
    monkeypatch.setenv("ALLOW_PLACEHOLDER_BARCODE", "1")
    monkeypatch.setattr(barcode_service, "_barcode_lib", None)
    monkeypatch.setattr(barcode_service, "ImageWriter", None)

    with pytest.raises(RuntimeError) as excinfo:
        barcode_service.generate_barcode_png("SKU-ABSENT", site_key=db.DEFAULT_SITE_KEY)

    assert "python-barcode" in str(excinfo.value)
    assert list(assets_dir.glob("*.png")) == []


def test_barcode_listing_requires_permission() -> None:
    services.ensure_database_ready()
    user_id = _create_user("noview", "noview123", role="user")
    assert user_id > 0

    admin_headers = _login_headers("admin", "admin123")
    headers = _login_headers("noview", "noview123")
    response = client.get("/barcode", headers=headers)
    assert response.status_code == 403


def test_barcode_listing_respects_module_permissions(
    monkeypatch: Any, tmp_path: Path
) -> None:
    services.ensure_database_ready()
    user_id = _create_user("limited-visual", "limited123", role="user")

    _configure_barcode_assets(monkeypatch, tmp_path)

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM remise_items")
        conn.commit()

    services.create_item(models.ItemCreate(name="Veste", sku="HAB-010"))
    services.create_remise_item(models.ItemCreate(name="Caisse", sku="REM-200"))

    assert (
        barcode_service.generate_barcode_png("HAB-010", site_key=db.DEFAULT_SITE_KEY)
        is not None
    )
    assert (
        barcode_service.generate_barcode_png("REM-200", site_key=db.DEFAULT_SITE_KEY)
        is not None
    )
    assert (
        barcode_service.generate_barcode_png("OTHER-999", site_key=db.DEFAULT_SITE_KEY)
        is not None
    )

    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="barcode",
            can_view=True,
            can_edit=False,
        )
    )
    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="inventory_remise",
            can_view=True,
            can_edit=False,
        )
    )

    user_headers = _login_headers("limited-visual", "limited123")

    listing = client.get("/barcode", headers=user_headers)
    assert listing.status_code == 200, listing.text
    payload = listing.json()

    assert [entry["sku"] for entry in payload] == ["REM-200"]


def test_generated_barcode_listing_filters_by_module_and_permissions(
    monkeypatch: Any, tmp_path: Path
) -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")
    user_id = _create_user("barcode-limited", "limited123", role="user")

    _configure_barcode_assets(monkeypatch, tmp_path)

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM remise_items")
        conn.commit()

    services.create_item(models.ItemCreate(name="Veste", sku="HAB-100"))
    services.create_pharmacy_item(
        models.PharmacyItemCreate(name="Doliprane", barcode="PHA-100", quantity=5)
    )
    services.create_remise_item(models.ItemCreate(name="Caisse", sku="REM-100"))

    assert (
        barcode_service.generate_barcode_png("HAB-100", site_key=db.DEFAULT_SITE_KEY)
        is not None
    )
    assert (
        barcode_service.generate_barcode_png("PHA-100", site_key=db.DEFAULT_SITE_KEY)
        is not None
    )
    assert (
        barcode_service.generate_barcode_png("REM-100", site_key=db.DEFAULT_SITE_KEY)
        is not None
    )

    filtered = client.get("/barcode?module=pharmacy", headers=admin_headers)
    assert filtered.status_code == 200, filtered.text
    payload = filtered.json()
    assert [entry["sku"] for entry in payload] == ["PHA-100"]
    assert all(entry["module"] == "pharmacy" for entry in payload)

    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="barcode",
            can_view=True,
            can_edit=False,
        )
    )
    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="pharmacy",
            can_view=True,
            can_edit=False,
        )
    )

    user_headers = _login_headers("barcode-limited", "limited123")

    unauthorized = client.get("/barcode?module=clothing", headers=user_headers)
    assert unauthorized.status_code == 403, unauthorized.text

    allowed = client.get("/barcode", headers=user_headers)
    assert allowed.status_code == 200, allowed.text
    allowed_payload = allowed.json()
    assert [entry["sku"] for entry in allowed_payload] == ["PHA-100"]


def test_existing_barcodes_listing(monkeypatch: Any, tmp_path: Path) -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    assets_dir = _configure_barcode_assets(monkeypatch, tmp_path)

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM remise_items")
        conn.commit()

    services.create_item(models.ItemCreate(name="Pantalon", sku="HAB-001"))
    services.create_remise_item(models.ItemCreate(name="Trousse", sku="REM-001"))
    services.create_pharmacy_item(
        models.PharmacyItemCreate(name="Doliprane", barcode="3400934058479", quantity=10)
    )

    (assets_dir / "HAB-001.png").write_bytes(_TRANSPARENT_PIXEL)

    response = client.get("/barcode/existing", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == [
        {"sku": "3400934058479"},
        {"sku": "REM-001"},
    ]


def test_existing_barcodes_listing_respects_module_permissions(
    monkeypatch: Any, tmp_path: Path
) -> None:
    services.ensure_database_ready()
    user_id = _create_user("limited-barcode", "limited123", role="user")

    _configure_barcode_assets(monkeypatch, tmp_path)

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM items")
        conn.commit()

    services.create_item(models.ItemCreate(name="Veste", sku="HAB-010"))
    services.create_pharmacy_item(
        models.PharmacyItemCreate(name="Paracetamol", barcode="3400934058486", quantity=5)
    )

    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="barcode",
            can_view=True,
            can_edit=False,
        )
    )
    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="pharmacy",
            can_view=True,
            can_edit=False,
        )
    )

    user_headers = _login_headers("limited-barcode", "limited123")

    response = client.get("/barcode/existing", headers=user_headers)
    assert response.status_code == 200, response.text
    assert response.json() == [{"sku": "3400934058486"}]


def test_barcode_catalog_listing_filters_and_search() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM remise_items")
        conn.execute("DELETE FROM vehicle_items")
        conn.execute("DELETE FROM pharmacy_items")
        conn.commit()

    clothing = services.create_item(models.ItemCreate(name="Veste", sku="HAB-010"))
    remise = services.create_remise_item(models.ItemCreate(name="Caisse", sku="REM-200"))
    pharmacy = services.create_pharmacy_item(
        models.PharmacyItemCreate(name="Doliprane", barcode="PHA-001", quantity=5)
    )

    response = client.get("/barcodes/catalog", headers=admin_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    entry_map = {(entry["module"], entry["sku"]): entry for entry in payload}

    assert entry_map[("clothing", "HAB-010")]["label"] == "Veste (HAB-010)"
    assert entry_map[("clothing", "HAB-010")]["item_id"] == clothing.id
    assert entry_map[("inventory_remise", "REM-200")]["name"] == "Caisse"
    assert entry_map[("inventory_remise", "REM-200")]["item_id"] == remise.id
    assert entry_map[("pharmacy", "PHA-001")]["label"] == "Doliprane (PHA-001)"
    assert entry_map[("pharmacy", "PHA-001")]["item_id"] == pharmacy.id

    module_filtered = client.get("/barcodes/catalog?module=pharmacy", headers=admin_headers)
    assert module_filtered.status_code == 200, module_filtered.text
    assert {entry["module"] for entry in module_filtered.json()} == {"pharmacy"}

    unknown_module = client.get(
        "/barcodes/catalog?module=unknown-module", headers=admin_headers
    )
    assert unknown_module.status_code == 200, unknown_module.text
    assert unknown_module.json() == []

    search_by_name = client.get("/barcodes/catalog?q=Ves", headers=admin_headers)
    assert search_by_name.status_code == 200, search_by_name.text
    assert {entry["sku"] for entry in search_by_name.json()} == {"HAB-010"}

    search_by_sku = client.get("/barcodes/catalog?q=REM-200", headers=admin_headers)
    assert search_by_sku.status_code == 200, search_by_sku.text
    assert {entry["sku"] for entry in search_by_sku.json()} == {"REM-200"}


def test_barcode_catalog_respects_module_permissions() -> None:
    services.ensure_database_ready()
    user_id = _create_user("catalog-user", "catalog123", role="user")

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM pharmacy_items")
        conn.commit()

    services.create_item(models.ItemCreate(name="Gants", sku="HAB-999"))
    services.create_pharmacy_item(
        models.PharmacyItemCreate(name="Paracetamol", barcode="PHA-777", quantity=3)
    )

    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="barcode",
            can_view=True,
            can_edit=False,
        )
    )
    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="clothing",
            can_view=True,
            can_edit=False,
        )
    )

    user_headers = _login_headers("catalog-user", "catalog123")

    response = client.get("/barcodes/catalog", headers=user_headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert {entry["module"] for entry in payload} == {"clothing"}

    filtered = client.get("/barcodes/catalog?module=pharmacy", headers=user_headers)
    assert filtered.status_code == 200, filtered.text
    assert filtered.json() == []


def test_existing_barcodes_listing_requires_permission() -> None:
    services.ensure_database_ready()
    user_id = _create_user("noviewexisting", "noview123", role="user")
    assert user_id > 0

    headers = _login_headers("noviewexisting", "noview123")
    response = client.get("/barcode/existing", headers=headers)
    assert response.status_code == 403


def test_barcode_pdf_export(monkeypatch: Any, tmp_path: Path) -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    assets_dir = _configure_barcode_assets(monkeypatch, tmp_path)

    for index in range(5):
        image = Image.new("RGB", (400, 200), color="white")
        image.save(assets_dir / f"SKU-{index}.png")

    response = client.get("/barcode/export/pdf", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert len(response.content) > 100


def test_barcode_pdf_export_requires_permission(monkeypatch: Any, tmp_path: Path) -> None:
    services.ensure_database_ready()
    user_id = _create_user("noviewpdf", "noview123", role="user")
    assert user_id > 0

    assets_dir = _configure_barcode_assets(monkeypatch, tmp_path)

    image = Image.new("RGB", (400, 200), color="white")
    image.save(assets_dir / "SKU-ONLY.png")

    headers = _login_headers("noviewpdf", "noview123")
    response = client.get("/barcode/export/pdf", headers=headers)
    assert response.status_code == 403

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


def test_pharmacy_lot_allocation_cycle() -> None:
    admin_headers = _login_headers("admin", "admin123")

    create_item = client.post(
        "/pharmacy/",
        json={
            "name": "Soluté de glucose",
            "dosage": "5%",
            "packaging": "500 mL",
            "barcode": "PHA-LOT-001",
            "quantity": 10,
            "low_stock_threshold": 2,
            "expiration_date": None,
            "location": "Pharma A",
            "category_id": None,
        },
        headers=admin_headers,
    )
    assert create_item.status_code == 201, create_item.text
    pharmacy_item_id = create_item.json()["id"]

    lot_resp = client.post(
        "/pharmacy/lots/",
        json={"name": f"Lot-PHA-{uuid4().hex[:6]}", "description": "Trousse d'urgence"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    assign_resp = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": pharmacy_item_id, "quantity": 4},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text
    lot_item_id = assign_resp.json()["id"]

    lots_listing = client.get("/pharmacy/lots/", headers=admin_headers)
    assert lots_listing.status_code == 200, lots_listing.text
    lot_entry = next(entry for entry in lots_listing.json() if entry["id"] == lot_id)
    assert lot_entry["item_count"] == 1
    assert lot_entry["total_quantity"] == 4

    with_items = client.get("/pharmacy/lots/with-items", headers=admin_headers)
    assert with_items.status_code == 200, with_items.text
    payload = with_items.json()
    target_lot = next(entry for entry in payload if entry["id"] == lot_id)
    assert target_lot["items"]
    assert target_lot["items"][0]["pharmacy_item_id"] == pharmacy_item_id
    assert target_lot["items"][0]["quantity"] == 4

    update_resp = client.put(
        f"/pharmacy/lots/{lot_id}/items/{lot_item_id}",
        json={"quantity": 6},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["quantity"] == 6

    overflow = client.put(
        f"/pharmacy/lots/{lot_id}/items/{lot_item_id}",
        json={"quantity": 20},
        headers=admin_headers,
    )
    assert overflow.status_code == 400

    cleanup_item = client.delete(
        f"/pharmacy/lots/{lot_id}/items/{lot_item_id}", headers=admin_headers
    )
    assert cleanup_item.status_code == 204

    cleanup_lot = client.delete(f"/pharmacy/lots/{lot_id}", headers=admin_headers)
    assert cleanup_lot.status_code == 204

    client.delete(f"/pharmacy/{pharmacy_item_id}", headers=admin_headers)


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

    categories_list_resp = client.get(
        "/vehicle-inventory/categories/",
        headers=admin_headers,
    )
    assert categories_list_resp.status_code == 200, categories_list_resp.text
    categories_list = categories_list_resp.json()
    listed_category = next((entry for entry in categories_list if entry["id"] == category_id), None)
    assert listed_category is not None
    assert listed_category["image_url"].startswith("/media/")

    remove_image_resp = client.delete(
        f"/vehicle-inventory/categories/{category_id}/image",
        headers=admin_headers,
    )
    assert remove_image_resp.status_code == 200, remove_image_resp.text
    category_without_image = remove_image_resp.json()
    assert category_without_image["image_url"] is None

    categories_without_image_resp = client.get(
        "/vehicle-inventory/categories/",
        headers=admin_headers,
    )
    assert categories_without_image_resp.status_code == 200, categories_without_image_resp.text
    categories_without_image = categories_without_image_resp.json()
    listed_without_image = next(
        (entry for entry in categories_without_image if entry["id"] == category_id),
        None,
    )
    assert listed_without_image is not None
    assert listed_without_image["image_url"] is None

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


def test_vehicle_lot_can_be_unassigned_via_endpoint() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Depot-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Dévidoir incendie",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 6,
            "low_stock_threshold": 1,
            "category_id": remise_category_id,
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item_id = remise_item_resp.json()["id"]

    lot_resp = client.post(
        "/remise-inventory/lots/",
        json={"name": f"Lot-{uuid4().hex[:6]}", "description": "Kit véhicule"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    add_lot_item = client.post(
        f"/remise-inventory/lots/{lot_id}/items",
        json={"remise_item_id": remise_item_id, "quantity": 2},
        headers=admin_headers,
    )
    assert add_lot_item.status_code == 201, add_lot_item.text

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Véhicule-{uuid4().hex[:6]}", "sizes": ["VUE PRINCIPALE"]},
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    assign_lot_item = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Dévidoir",
            "sku": f"VEH-{uuid4().hex[:6]}",
            "quantity": 2,
            "category_id": vehicle_category_id,
            "size": "VUE PRINCIPALE",
            "remise_item_id": remise_item_id,
            "lot_id": lot_id,
        },
        headers=admin_headers,
    )
    assert assign_lot_item.status_code == 201, assign_lot_item.text

    remise_after_assign = services.get_remise_item(remise_item_id)
    assert remise_after_assign.quantity == 4

    unassign_resp = client.post(
        f"/vehicle-inventory/lots/{lot_id}/unassign",
        json={"category_id": vehicle_category_id},
        headers=admin_headers,
    )
    assert unassign_resp.status_code == 204, unassign_resp.text

    remise_after_unassign = services.get_remise_item(remise_item_id)
    assert remise_after_unassign.quantity == 6

    remaining_lot_items = [
        entry
        for entry in services.list_vehicle_items()
        if entry.lot_id == lot_id and entry.category_id == vehicle_category_id
    ]
    assert not remaining_lot_items

    cleanup_vehicle = client.delete(
        f"/vehicle-inventory/categories/{vehicle_category_id}",
        headers=admin_headers,
    )
    assert cleanup_vehicle.status_code == 204


def test_incendie_lot_assignment_structure_regression() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Depot-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot incendie",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 2,
            "category_id": remise_category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item_id = remise_item_resp.json()["id"]

    lot_resp = client.post(
        "/remise-inventory/lots/",
        json={"name": f"Lot-{uuid4().hex[:6]}", "description": "Lot incendie"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    add_lot_item = client.post(
        f"/remise-inventory/lots/{lot_id}/items",
        json={"remise_item_id": remise_item_id, "quantity": 1},
        headers=admin_headers,
    )
    assert add_lot_item.status_code == 201, add_lot_item.text

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={
            "name": f"Véhicule-{uuid4().hex[:6]}",
            "sizes": ["VUE PRINCIPALE"],
            "vehicle_type": "incendie",
        },
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    assign_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Lot incendie",
            "sku": f"VEH-{uuid4().hex[:6]}",
            "quantity": 1,
            "category_id": vehicle_category_id,
            "size": "VUE PRINCIPALE",
            "remise_item_id": remise_item_id,
            "lot_id": lot_id,
        },
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text

    vehicle_items_resp = client.get("/vehicle-inventory/", headers=admin_headers)
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    entry = next(
        item
        for item in vehicle_items_resp.json()
        if item["category_id"] == vehicle_category_id and item["lot_id"] == lot_id
    )
    assert entry["lot_name"]
    assert entry["is_in_lot"] is True
    assert entry["applied_lot_assignment_id"] is None
    assert entry["applied_lot_source"] is None

    cleanup_lot = client.delete(f"/remise-inventory/lots/{lot_id}", headers=admin_headers)
    assert cleanup_lot.status_code == 204

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


def test_incendie_lot_assignment_non_regression() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Depot-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot incendie",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 3,
            "category_id": remise_category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item_id = remise_item_resp.json()["id"]

    lot_resp = client.post(
        "/remise-inventory/lots/",
        json={"name": f"Lot-{uuid4().hex[:6]}", "description": "Lot incendie"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    add_lot_item = client.post(
        f"/remise-inventory/lots/{lot_id}/items",
        json={"remise_item_id": remise_item_id, "quantity": 1},
        headers=admin_headers,
    )
    assert add_lot_item.status_code == 201, add_lot_item.text

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={
            "name": f"Véhicule-{uuid4().hex[:6]}",
            "sizes": ["VUE PRINCIPALE"],
            "vehicle_type": "incendie",
        },
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    assign_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Lot incendie",
            "sku": f"VEH-{uuid4().hex[:6]}",
            "quantity": 1,
            "category_id": vehicle_category_id,
            "size": "VUE PRINCIPALE",
            "remise_item_id": remise_item_id,
            "lot_id": lot_id,
        },
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text

    vehicle_items_resp = client.get("/vehicle-inventory/", headers=admin_headers)
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    entry = next(
        item
        for item in vehicle_items_resp.json()
        if item["category_id"] == vehicle_category_id and item["lot_id"] == lot_id
    )
    assert entry["is_in_lot"] is True
    assert entry["applied_lot_assignment_id"] is None
    assert entry["applied_lot_source"] is None

    cleanup_lot = client.delete(f"/remise-inventory/lots/{lot_id}", headers=admin_headers)
    assert cleanup_lot.status_code == 204

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


def test_vehicle_inventory_restack_when_removed_from_vehicle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Depot-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Sac de secours",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 3,
            "low_stock_threshold": 0,
            "category_id": remise_category_id,
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item_id = remise_item_resp.json()["id"]

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Vehicule-{uuid4().hex[:6]}", "sizes": ["CABINE"]},
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    assign_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Sac de secours",
            "sku": "REM-STACK",
            "quantity": 1,
            "category_id": vehicle_category_id,
            "size": "CABINE",
            "position_x": 0.2,
            "position_y": 0.3,
            "remise_item_id": remise_item_id,
        },
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text
    vehicle_item_id = assign_resp.json()["id"]

    before_remove = services.list_vehicle_items()
    template_candidates = [
        entry
        for entry in before_remove
        if entry.remise_item_id == remise_item_id and entry.category_id is None
    ]
    assert len(template_candidates) == 1
    template_id = template_candidates[0].id
    assert any(entry.id == vehicle_item_id for entry in before_remove)

    remove_resp = client.put(
        f"/vehicle-inventory/{vehicle_item_id}",
        json={
            "category_id": None,
            "size": None,
            "position_x": None,
            "position_y": None,
            "quantity": 0,
        },
        headers=admin_headers,
    )
    assert remove_resp.status_code == 200, remove_resp.text
    removed_payload = remove_resp.json()
    assert removed_payload["id"] == template_id
    assert removed_payload["category_id"] is None

    after_remove = services.list_vehicle_items()
    matching_entries = [
        entry for entry in after_remove if entry.remise_item_id == remise_item_id
    ]
    assert matching_entries and matching_entries[0].id == template_id
    assert matching_entries[0].category_id is None

    remise_after_remove = services.get_remise_item(remise_item_id)
    assert remise_after_remove.quantity == 3

    cleanup_template = client.delete(
        f"/vehicle-inventory/{template_id}",
        headers=admin_headers,
    )
    assert cleanup_template.status_code == 204

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


def test_vehicle_inventory_pdf_export() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Zone-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Sac secours",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 4,
            "low_stock_threshold": 1,
            "category_id": remise_category_id,
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item_id = remise_item_resp.json()["id"]

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Lot-{uuid4().hex[:6]}", "sizes": ["CABINE"]},
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    photo = services.add_vehicle_photo(io.BytesIO(_TRANSPARENT_PIXEL), "fond.png")
    services.update_vehicle_view_background(
        vehicle_category_id,
        models.VehicleViewBackgroundUpdate(name="cabine", photo_id=photo.id),
    )

    assign_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Sac secours",
            "sku": f"VEH-{uuid4().hex[:6]}",
            "quantity": 2,
            "low_stock_threshold": 0,
            "category_id": vehicle_category_id,
            "size": "cabine",
            "remise_item_id": remise_item_id,
        },
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text
    item_id = assign_resp.json()["id"]

    item_image = io.BytesIO()
    Image.new("RGB", (120, 80), color="red").save(item_image, format="PNG")
    item_image.seek(0)
    upload_resp = client.post(
        f"/vehicle-inventory/{item_id}/image",
        files={"file": ("materiel.png", item_image, "image/png")},
        headers=admin_headers,
    )
    assert upload_resp.status_code == 200, upload_resp.text

    export_resp = client.get("/vehicle-inventory/export/pdf", headers=admin_headers)
    assert export_resp.status_code == 200, export_resp.text
    export_payload = export_resp.json()
    job_id = export_payload["job_id"]
    assert job_id

    payload = b""
    for _ in range(50):
        status_resp = client.get(f"/vehicle-inventory/export/pdf/jobs/{job_id}", headers=admin_headers)
        assert status_resp.status_code == 200, status_resp.text
        status_payload = status_resp.json()
        if status_payload["status"] == "done":
            download_resp = client.get(
                f"/vehicle-inventory/export/pdf/jobs/{job_id}/download",
                headers=admin_headers,
            )
            assert download_resp.status_code == 200, download_resp.text
            payload = download_resp.content
            break
        if status_payload["status"] in {"error", "cancelled"}:
            pytest.fail(status_payload.get("error", "Export PDF échoué."))
        time.sleep(0.1)
    assert payload.startswith(b"%PDF")
    assert len(payload) > 200


def test_remise_inventory_pdf_export() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": "Remise test", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    category_id = category_resp.json()["id"]

    item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Matériel test",
            "sku": "REM-TEST",
            "quantity": 3,
            "low_stock_threshold": 1,
            "category_id": category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text

    export_resp = client.get("/remise-inventory/export/pdf", headers=admin_headers)
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.headers["content-type"] == "application/pdf"
    payload = export_resp.content
    assert payload.startswith(b"%PDF")
    assert len(payload) > 200


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


def test_remise_lot_allocation_cycle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Remise-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    category_id = category_resp.json()["id"]

    item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot test",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 10,
            "category_id": category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    item_id = item_resp.json()["id"]

    lot_resp = client.post(
        "/remise-inventory/lots/",
        json={"name": f"Lot-{uuid4().hex[:6]}", "description": "Test lot"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    assign_resp = client.post(
        f"/remise-inventory/lots/{lot_id}/items",
        json={"remise_item_id": item_id, "quantity": 4},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text
    assigned = assign_resp.json()
    assert assigned["quantity"] == 4

    lot_items_resp = client.get(
        f"/remise-inventory/lots/{lot_id}/items", headers=admin_headers
    )
    assert lot_items_resp.status_code == 200, lot_items_resp.text
    lot_items = lot_items_resp.json()
    assert lot_items and lot_items[0]["available_quantity"] == 10

    lots_listing = client.get("/remise-inventory/lots/", headers=admin_headers)
    assert lots_listing.status_code == 200, lots_listing.text
    lot_entry = next(entry for entry in lots_listing.json() if entry["id"] == lot_id)
    assert lot_entry["item_count"] == 1
    assert lot_entry["total_quantity"] == 4

    over_alloc = client.put(
        f"/remise-inventory/lots/{lot_id}/items/{assigned['id']}",
        json={"quantity": 11},
        headers=admin_headers,
    )
    assert over_alloc.status_code == 404
    assert "Stock insuffisant" in over_alloc.json()["detail"]

    update_resp = client.put(
        f"/remise-inventory/lots/{lot_id}/items/{assigned['id']}",
        json={"quantity": 2},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200, update_resp.text
    updated = update_resp.json()
    assert updated["quantity"] == 2
    assert updated["available_quantity"] == 10

    removal_resp = client.delete(
        f"/remise-inventory/lots/{lot_id}/items/{assigned['id']}",
        headers=admin_headers,
    )
    assert removal_resp.status_code == 204, removal_resp.text
    restored_item = services.get_remise_item(item_id)
    assert restored_item.quantity == 10

    delete_lot_resp = client.delete(
        f"/remise-inventory/lots/{lot_id}", headers=admin_headers
    )
    assert delete_lot_resp.status_code == 204, delete_lot_resp.text

    cleanup_item = client.delete(
        f"/remise-inventory/{item_id}", headers=admin_headers
    )
    assert cleanup_item.status_code == 204, cleanup_item.text
    cleanup_category = client.delete(
        f"/remise-inventory/categories/{category_id}", headers=admin_headers
    )
    assert cleanup_category.status_code == 204, cleanup_category.text


def test_vehicle_items_detached_when_lot_deleted() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Véhicule-{uuid4().hex[:6]}"},
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Remise-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    category_id = category_resp.json()["id"]

    item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot véhicule",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 8,
            "category_id": category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    remise_item_id = item_resp.json()["id"]

    lot_resp = client.post(
        "/remise-inventory/lots/",
        json={"name": f"Lot-{uuid4().hex[:6]}", "description": "Lot à supprimer"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    assign_resp = client.post(
        f"/remise-inventory/lots/{lot_id}/items",
        json={"remise_item_id": remise_item_id, "quantity": 3},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text

    vehicle_item_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Affectation lot",
            "sku": f"VEH-{uuid4().hex[:6]}",
            "category_id": vehicle_category_id,
            "size": "vue_exterieure",
            "quantity": 3,
            "remise_item_id": remise_item_id,
            "lot_id": lot_id,
        },
        headers=admin_headers,
    )
    assert vehicle_item_resp.status_code == 201, vehicle_item_resp.text
    vehicle_item_id = vehicle_item_resp.json()["id"]
    assert vehicle_item_resp.json()["lot_id"] == lot_id

    delete_resp = client.delete(
        f"/remise-inventory/lots/{lot_id}", headers=admin_headers
    )
    assert delete_resp.status_code == 204, delete_resp.text

    vehicle_items_resp = client.get("/vehicle-inventory/", headers=admin_headers)
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    updated_entry = next(
        (entry for entry in vehicle_items_resp.json() if entry["id"] == vehicle_item_id),
        None,
    )
    assert updated_entry is not None
    assert updated_entry["lot_id"] is None


def test_pharmacy_items_available_in_vehicle_library() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    category_resp = client.post(
        "/pharmacy/categories/",
        json={"name": f"Pharma-{uuid4().hex[:6]}"},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    category_id = category_resp.json()["id"]

    item_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Template pharmacie véhicule",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "category_id": category_id,
            "quantity": 4,
            "dosage": "500mg",
            "packaging": "Boîte",
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    pharmacy_item_id = item_resp.json()["id"]

    vehicle_items_resp = client.get(
        "/vehicle-inventory/library",
        params={"vehicle_type": "secours_a_personne"},
        headers=admin_headers,
    )
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    library_entries = [
        entry
        for entry in vehicle_items_resp.json()
        if entry["pharmacy_item_id"] == pharmacy_item_id
    ]

    assert library_entries, "Le matériel de pharmacie devrait être visible dans la bibliothèque."
    assert library_entries[0]["vehicle_type"] == "secours_a_personne"
    assert library_entries[0]["category_id"] is None


def test_pharmacy_lots_available_in_vehicle_library() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    item_a_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Lot VSAV Item A",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "quantity": 5,
        },
        headers=admin_headers,
    )
    assert item_a_resp.status_code == 201, item_a_resp.text
    item_a_id = item_a_resp.json()["id"]

    item_b_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Lot VSAV Item B",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "quantity": 6,
        },
        headers=admin_headers,
    )
    assert item_b_resp.status_code == 201, item_b_resp.text
    item_b_id = item_b_resp.json()["id"]

    lot_resp = client.post(
        "/pharmacy/lots/",
        json={"name": f"Lot VSAV-{uuid4().hex[:6]}", "description": "Kit VSAV"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    add_item_a_resp = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": item_a_id, "quantity": 2},
        headers=admin_headers,
    )
    assert add_item_a_resp.status_code == 201, add_item_a_resp.text

    add_item_b_resp = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": item_b_id, "quantity": 3},
        headers=admin_headers,
    )
    assert add_item_b_resp.status_code == 201, add_item_b_resp.text

    library_resp = client.get(
        "/vehicle-inventory/library/lots",
        params={"vehicle_type": "secours_a_personne"},
        headers=admin_headers,
    )
    assert library_resp.status_code == 200, library_resp.text
    lot_entry = next(
        (entry for entry in library_resp.json() if entry["id"] == lot_id),
        None,
    )
    assert lot_entry is not None, "Le lot pharmacie devrait être visible dans la bibliothèque."
    assert lot_entry["item_count"] == 2
    assert {item["pharmacy_item_id"] for item in lot_entry["items"]} == {
        item_a_id,
        item_b_id,
    }


def test_apply_pharmacy_lot_to_vehicle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    vehicle_resp = client.post(
        "/vehicle-inventory/categories/",
        json={
            "name": f"VSAV-{uuid4().hex[:6]}",
            "sizes": ["VUE PRINCIPALE"],
            "vehicle_type": "secours_a_personne",
        },
        headers=admin_headers,
    )
    assert vehicle_resp.status_code == 201, vehicle_resp.text
    vehicle_id = vehicle_resp.json()["id"]

    item_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Lot apply item",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "quantity": 4,
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    pharmacy_item_id = item_resp.json()["id"]

    second_item_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Lot apply item second",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "quantity": 3,
        },
        headers=admin_headers,
    )
    assert second_item_resp.status_code == 201, second_item_resp.text
    pharmacy_item_id_second = second_item_resp.json()["id"]

    lot_resp = client.post(
        "/pharmacy/lots/",
        json={"name": f"Lot apply-{uuid4().hex[:6]}", "description": "Kit apply"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    add_item_resp = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": pharmacy_item_id, "quantity": 2},
        headers=admin_headers,
    )
    assert add_item_resp.status_code == 201, add_item_resp.text

    add_item_resp_second = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": pharmacy_item_id_second, "quantity": 1},
        headers=admin_headers,
    )
    assert add_item_resp_second.status_code == 201, add_item_resp_second.text

    drop_position = {"x": 0.22, "y": 0.37}
    apply_resp = client.post(
        "/vehicle-inventory/apply-pharmacy-lot",
        json={
            "vehicle_id": vehicle_id,
            "lot_id": lot_id,
            "target_view": "VUE PRINCIPALE",
            "drop_position": drop_position,
        },
        headers=admin_headers,
    )
    assert apply_resp.status_code == 200, apply_resp.text
    apply_payload = apply_resp.json()
    assert apply_payload["created_count"] == 2
    assert len(apply_payload["created_item_ids"]) == apply_payload["created_count"]

    vehicle_items_resp = client.get("/vehicle-inventory/", headers=admin_headers)
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    vehicle_items = [
        entry
        for entry in vehicle_items_resp.json()
        if entry["category_id"] == vehicle_id
        and entry["pharmacy_item_id"] in {pharmacy_item_id, pharmacy_item_id_second}
    ]
    assert vehicle_items
    assert {entry["pharmacy_item_id"] for entry in vehicle_items} == {
        pharmacy_item_id,
        pharmacy_item_id_second,
    }
    for entry in vehicle_items:
        assert entry["position_x"] is not None
        assert entry["position_y"] is not None
        assert entry["lot_id"] is None
        assert entry["applied_lot_source"] == "pharmacy"
        assert entry["applied_lot_assignment_id"] is not None
    avg_x = sum(entry["position_x"] for entry in vehicle_items) / len(vehicle_items)
    avg_y = sum(entry["position_y"] for entry in vehicle_items) / len(vehicle_items)
    assert abs(avg_x - drop_position["x"]) < 0.02
    assert abs(avg_y - drop_position["y"]) < 0.02

    applied_lots_resp = client.get(
        "/vehicle-inventory/applied-lots",
        params={"vehicle_id": vehicle_id},
        headers=admin_headers,
    )
    assert applied_lots_resp.status_code == 200, applied_lots_resp.text
    applied_lots = applied_lots_resp.json()
    assert len(applied_lots) == 1
    applied_lot = applied_lots[0]
    assert applied_lot["pharmacy_lot_id"] == lot_id
    assert applied_lot["lot_name"] is not None
    assert applied_lot["position_x"] == pytest.approx(drop_position["x"])
    assert applied_lot["position_y"] == pytest.approx(drop_position["y"])

    pharmacy_items_resp = client.get("/pharmacy/", headers=admin_headers)
    assert pharmacy_items_resp.status_code == 200, pharmacy_items_resp.text
    pharmacy_item = next(
        (entry for entry in pharmacy_items_resp.json() if entry["id"] == pharmacy_item_id),
        None,
    )
    assert pharmacy_item is not None
    assert pharmacy_item["quantity"] == 2
    second_pharmacy_item = next(
        (entry for entry in pharmacy_items_resp.json() if entry["id"] == pharmacy_item_id_second),
        None,
    )
    assert second_pharmacy_item is not None
    assert second_pharmacy_item["quantity"] == 2

    duplicate_apply_resp = client.post(
        "/vehicle-inventory/apply-pharmacy-lot",
        json={
            "vehicle_id": vehicle_id,
            "lot_id": lot_id,
            "target_view": "VUE PRINCIPALE",
        },
        headers=admin_headers,
    )
    assert duplicate_apply_resp.status_code == 400, duplicate_apply_resp.text


def test_vehicle_applied_lot_update_and_delete() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    vehicle_resp = client.post(
        "/vehicle-inventory/categories/",
        json={
            "name": f"VSAV-{uuid4().hex[:6]}",
            "sizes": ["VUE PRINCIPALE"],
            "vehicle_type": "secours_a_personne",
        },
        headers=admin_headers,
    )
    assert vehicle_resp.status_code == 201, vehicle_resp.text
    vehicle_id = vehicle_resp.json()["id"]

    item_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Lot apply item delete",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "quantity": 5,
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    pharmacy_item_id = item_resp.json()["id"]

    lot_resp = client.post(
        "/pharmacy/lots/",
        json={"name": f"Lot apply-del-{uuid4().hex[:6]}", "description": "Kit apply delete"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    add_item_resp = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": pharmacy_item_id, "quantity": 3},
        headers=admin_headers,
    )
    assert add_item_resp.status_code == 201, add_item_resp.text

    apply_resp = client.post(
        "/vehicle-inventory/apply-pharmacy-lot",
        json={
            "vehicle_id": vehicle_id,
            "lot_id": lot_id,
            "target_view": "VUE PRINCIPALE",
            "drop_position": {"x": 0.3, "y": 0.4},
        },
        headers=admin_headers,
    )
    assert apply_resp.status_code == 200, apply_resp.text

    applied_lots_resp = client.get(
        "/vehicle-inventory/applied-lots",
        params={"vehicle_id": vehicle_id},
        headers=admin_headers,
    )
    assert applied_lots_resp.status_code == 200, applied_lots_resp.text
    applied_lot = applied_lots_resp.json()[0]
    assignment_id = applied_lot["id"]

    patch_resp = client.patch(
        f"/vehicle-inventory/applied-lots/{assignment_id}",
        json={"position_x": 0.12, "position_y": 0.34},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    updated = patch_resp.json()
    assert updated["position_x"] == pytest.approx(0.12)
    assert updated["position_y"] == pytest.approx(0.34)

    delete_resp = client.delete(
        f"/vehicle-inventory/applied-lots/{assignment_id}",
        headers=admin_headers,
    )
    assert delete_resp.status_code == 200, delete_resp.text
    delete_payload = delete_resp.json()
    assert delete_payload["deleted_assignment_id"] == assignment_id
    assert delete_payload["deleted_items_count"] == 1
    assert delete_payload["deleted_item_ids"]

    remaining_applied = client.get(
        "/vehicle-inventory/applied-lots",
        params={"vehicle_id": vehicle_id},
        headers=admin_headers,
    )
    assert remaining_applied.status_code == 200, remaining_applied.text
    assert remaining_applied.json() == []

    vehicle_items_resp = client.get("/vehicle-inventory/", headers=admin_headers)
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    assert all(
        entry["applied_lot_assignment_id"] != assignment_id
        for entry in vehicle_items_resp.json()
    )

    pharmacy_item_resp = client.get(f"/pharmacy/{pharmacy_item_id}", headers=admin_headers)
    assert pharmacy_item_resp.status_code == 200, pharmacy_item_resp.text
    assert pharmacy_item_resp.json()["quantity"] == 5


def test_pharmacy_lot_can_be_applied_and_removed() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    vehicle_resp = client.post(
        "/vehicle-inventory/categories/",
        json={
            "name": f"VSAV-{uuid4().hex[:6]}",
            "sizes": ["VUE PRINCIPALE"],
            "vehicle_type": "secours_a_personne",
        },
        headers=admin_headers,
    )
    assert vehicle_resp.status_code == 201, vehicle_resp.text
    vehicle_id = vehicle_resp.json()["id"]

    item_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Lot apply remove",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "quantity": 4,
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    pharmacy_item_id = item_resp.json()["id"]

    second_item_resp = client.post(
        "/pharmacy/",
        json={
            "name": "Lot apply remove 2",
            "barcode": f"PHARM-{uuid4().hex[:6]}",
            "quantity": 6,
        },
        headers=admin_headers,
    )
    assert second_item_resp.status_code == 201, second_item_resp.text
    second_pharmacy_item_id = second_item_resp.json()["id"]

    lot_resp = client.post(
        "/pharmacy/lots/",
        json={"name": f"Lot-apply-rem-{uuid4().hex[:6]}", "description": "Lot apply remove"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    add_item_resp = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": pharmacy_item_id, "quantity": 2},
        headers=admin_headers,
    )
    assert add_item_resp.status_code == 201, add_item_resp.text

    add_item_resp = client.post(
        f"/pharmacy/lots/{lot_id}/items",
        json={"pharmacy_item_id": second_pharmacy_item_id, "quantity": 1},
        headers=admin_headers,
    )
    assert add_item_resp.status_code == 201, add_item_resp.text

    apply_resp = client.post(
        "/vehicle-inventory/apply-pharmacy-lot",
        json={
            "vehicle_id": vehicle_id,
            "lot_id": lot_id,
            "target_view": "VUE PRINCIPALE",
        },
        headers=admin_headers,
    )
    assert apply_resp.status_code == 200, apply_resp.text

    library_resp = client.get(
        "/vehicle-inventory/library/lots",
        params={"vehicle_type": "secours_a_personne", "vehicle_id": vehicle_id},
        headers=admin_headers,
    )
    assert library_resp.status_code == 200, library_resp.text
    assert all(entry["id"] != lot_id for entry in library_resp.json())

    applied_lots_resp = client.get(
        "/vehicle-inventory/applied-lots",
        params={"vehicle_id": vehicle_id},
        headers=admin_headers,
    )
    assert applied_lots_resp.status_code == 200, applied_lots_resp.text
    applied_lot_id = applied_lots_resp.json()[0]["id"]

    vehicle_items_resp = client.get("/vehicle-inventory/", headers=admin_headers)
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    applied_items = [
        entry
        for entry in vehicle_items_resp.json()
        if entry["applied_lot_assignment_id"] == applied_lot_id
    ]
    assert len(applied_items) == 2

    delete_resp = client.delete(
        f"/vehicle-inventory/applied-lots/{applied_lot_id}",
        headers=admin_headers,
    )
    assert delete_resp.status_code == 200, delete_resp.text
    delete_payload = delete_resp.json()
    assert delete_payload["deleted_assignment_id"] == applied_lot_id
    assert delete_payload["deleted_items_count"] == 2
    assert len(delete_payload["deleted_item_ids"]) == 2

    library_after = client.get(
        "/vehicle-inventory/library/lots",
        params={"vehicle_type": "secours_a_personne", "vehicle_id": vehicle_id},
        headers=admin_headers,
    )
    assert library_after.status_code == 200, library_after.text
    assert any(entry["id"] == lot_id for entry in library_after.json())

    vehicle_items_resp = client.get("/vehicle-inventory/", headers=admin_headers)
    assert vehicle_items_resp.status_code == 200, vehicle_items_resp.text
    assert all(
        entry["applied_lot_assignment_id"] != applied_lot_id
        for entry in vehicle_items_resp.json()
    )

    pharmacy_item_resp = client.get(f"/pharmacy/{pharmacy_item_id}", headers=admin_headers)
    assert pharmacy_item_resp.status_code == 200, pharmacy_item_resp.text
    assert pharmacy_item_resp.json()["quantity"] == 4

    second_item_check = client.get(f"/pharmacy/{second_pharmacy_item_id}", headers=admin_headers)
    assert second_item_check.status_code == 200, second_item_check.text
    assert second_item_check.json()["quantity"] == 6


def test_vehicle_qr_visibility_toggle() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    remise_category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Remise-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert remise_category_resp.status_code == 201, remise_category_resp.text
    remise_category_id = remise_category_resp.json()["id"]

    remise_item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot masquable",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 2,
            "category_id": remise_category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert remise_item_resp.status_code == 201, remise_item_resp.text
    remise_item_id = remise_item_resp.json()["id"]

    vehicle_category_resp = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Vehicule-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert vehicle_category_resp.status_code == 201, vehicle_category_resp.text
    vehicle_category_id = vehicle_category_resp.json()["id"]

    vehicle_item_resp = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Camion masquable",
            "sku": f"VEH-{uuid4().hex[:6]}",
            "quantity": 1,
            "category_id": vehicle_category_id,
            "remise_item_id": remise_item_id,
        },
        headers=admin_headers,
    )
    assert vehicle_item_resp.status_code == 201, vehicle_item_resp.text
    vehicle_item = vehicle_item_resp.json()
    vehicle_item_id = vehicle_item["id"]
    assert vehicle_item["show_in_qr"] is True
    qr_token = vehicle_item["qr_token"]
    assert qr_token

    public_resp = client.get(f"/vehicle-inventory/public/{qr_token}")
    assert public_resp.status_code == 200, public_resp.text

    hide_resp = client.put(
        f"/vehicle-inventory/{vehicle_item_id}",
        json={"show_in_qr": False},
        headers=admin_headers,
    )
    assert hide_resp.status_code == 200, hide_resp.text
    assert hide_resp.json()["show_in_qr"] is False

    hidden_public_resp = client.get(f"/vehicle-inventory/public/{qr_token}")
    assert hidden_public_resp.status_code == 404
    assert "masqué" in hidden_public_resp.json()["detail"].lower()

    show_resp = client.put(
        f"/vehicle-inventory/{vehicle_item_id}",
        json={"show_in_qr": True},
        headers=admin_headers,
    )
    assert show_resp.status_code == 200, show_resp.text
    assert show_resp.json()["show_in_qr"] is True

    visible_public_resp = client.get(f"/vehicle-inventory/public/{qr_token}")
    assert visible_public_resp.status_code == 200, visible_public_resp.text


def test_remise_lot_listing_with_items() -> None:
    services.ensure_database_ready()
    admin_headers = _login_headers("admin", "admin123")

    category_resp = client.post(
        "/remise-inventory/categories/",
        json={"name": f"Remise-{uuid4().hex[:6]}", "sizes": ["STANDARD"]},
        headers=admin_headers,
    )
    assert category_resp.status_code == 201, category_resp.text
    category_id = category_resp.json()["id"]

    item_resp = client.post(
        "/remise-inventory/",
        json={
            "name": "Lot visu",
            "sku": f"REM-{uuid4().hex[:6]}",
            "quantity": 10,
            "category_id": category_id,
            "size": "STANDARD",
        },
        headers=admin_headers,
    )
    assert item_resp.status_code == 201, item_resp.text
    item_id = item_resp.json()["id"]

    lot_resp = client.post(
        "/remise-inventory/lots/",
        json={"name": f"Lot-{uuid4().hex[:6]}", "description": "Détails visibles"},
        headers=admin_headers,
    )
    assert lot_resp.status_code == 201, lot_resp.text
    lot_id = lot_resp.json()["id"]

    assign_resp = client.post(
        f"/remise-inventory/lots/{lot_id}/items",
        json={"remise_item_id": item_id, "quantity": 3},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 201, assign_resp.text

    listing_resp = client.get("/remise-inventory/lots/with-items", headers=admin_headers)
    assert listing_resp.status_code == 200, listing_resp.text
    payload = listing_resp.json()
    lot_entry = next(entry for entry in payload if entry["id"] == lot_id)
    assert lot_entry["item_count"] == 1
    assert lot_entry["total_quantity"] == 3
    assert lot_entry["items"]
    assert lot_entry["items"][0]["remise_item_id"] == item_id
    assert lot_entry["items"][0]["quantity"] == 3
    assert lot_entry["items"][0]["available_quantity"] == 10

    client.delete(f"/remise-inventory/lots/{lot_id}", headers=admin_headers)
    client.delete(f"/remise-inventory/{item_id}", headers=admin_headers)
    client.delete(f"/remise-inventory/categories/{category_id}", headers=admin_headers)


def test_backup_settings_roundtrip_and_isolation() -> None:
    headers = _login_headers("admin", "admin123")
    gsm_headers = {**headers, "X-Site-Key": "GSM"}
    try:
        response = client.put(
            "/admin/backup/settings",
            json={"enabled": True, "interval_minutes": 7, "retention_count": 3},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        response = client.put(
            "/admin/backup/settings",
            json={"enabled": True, "interval_minutes": 11, "retention_count": 2},
            headers=gsm_headers,
        )
        assert response.status_code == 200, response.text

        asyncio.run(backup_scheduler.reload_from_db())

        fetched = client.get("/admin/backup/settings", headers=headers)
        assert fetched.status_code == 200, fetched.text
        data = fetched.json()
        assert data["enabled"] is True
        assert data["interval_minutes"] == 11

        fetched_gsm = client.get("/admin/backup/settings", headers=gsm_headers)
        assert fetched_gsm.status_code == 200, fetched_gsm.text
        data_gsm = fetched_gsm.json()
        assert data_gsm["enabled"] is True
        assert data_gsm["interval_minutes"] == 11

        assert asyncio.run(backup_scheduler.get_job_count("JLL")) == 1

        response = client.put(
            "/admin/backup/settings",
            json={"enabled": True, "interval_minutes": 9, "retention_count": 3},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert asyncio.run(backup_scheduler.get_job_count("JLL")) == 1

        response = client.put(
            "/admin/backup/settings",
            json={"enabled": False, "interval_minutes": 9, "retention_count": 3},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert asyncio.run(backup_scheduler.get_job_count("JLL")) == 0
    finally:
        reset_payload = {"enabled": False, "interval_minutes": 60, "retention_count": 3}
        reset = client.put("/admin/backup/settings", json=reset_payload, headers=headers)
        assert reset.status_code == 200, reset.text
        reset_gsm = client.put("/admin/backup/settings", json=reset_payload, headers=gsm_headers)
        assert reset_gsm.status_code == 200, reset_gsm.text


def test_backup_settings_recovers_missing_table(monkeypatch: pytest.MonkeyPatch) -> None:
    headers = _login_headers("admin", "admin123")
    with db.get_core_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS backup_settings")

    monkeypatch.setattr(services, "_db_initialized", False)
    services.ensure_database_ready()

    response = client.put(
        "/admin/backup/settings",
        json={"enabled": True, "interval_minutes": 15, "retention_count": 2},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    fetched = client.get("/admin/backup/settings", headers=headers)
    assert fetched.status_code == 200, fetched.text
    data = fetched.json()
    assert data["enabled"] is True
    assert data["interval_minutes"] == 15


def test_backup_settings_requires_admin() -> None:
    username = f"backup-user-{uuid4().hex[:6]}"
    _create_user(username, "Password123!", role="user")
    headers = _login_headers(username, "Password123!")
    response = client.get("/admin/backup/settings", headers=headers)
    assert response.status_code == 403


def test_backup_settings_update_requires_admin() -> None:
    username = f"backup-update-user-{uuid4().hex[:6]}"
    _create_user(username, "Password123!", role="user")
    headers = _login_headers(username, "Password123!")
    response = client.put(
        "/admin/backup/settings",
        json={"enabled": True, "interval_minutes": 8, "retention_count": 2},
        headers=headers,
    )
    assert response.status_code == 403


def test_backup_settings_persist_after_restart() -> None:
    headers = _login_headers("admin", "admin123")
    payload = {"enabled": True, "interval_minutes": 12, "retention_count": 2}
    response = client.put("/admin/backup/settings", json=payload, headers=headers)
    assert response.status_code == 200, response.text

    from backend.services.backup_scheduler import BackupScheduler

    scheduler = BackupScheduler()
    try:
        asyncio.run(scheduler.start())
        assert asyncio.run(scheduler.get_job_count("JLL")) == 1
        fetched = client.get("/admin/backup/settings", headers=headers)
        assert fetched.status_code == 200, fetched.text
        data = fetched.json()
        assert data["enabled"] is True
        assert data["interval_minutes"] == 12
    finally:
        asyncio.run(scheduler.stop())
        reset_payload = {"enabled": False, "interval_minutes": 60, "retention_count": 3}
        reset = client.put("/admin/backup/settings", json=reset_payload, headers=headers)
        assert reset.status_code == 200, reset.text


def test_backup_export_requires_admin() -> None:
    username = f"backup-export-user-{uuid4().hex[:6]}"
    _create_user(username, "Password123!", role="user")
    headers = _login_headers(username, "Password123!")
    response = client.get("/backup/", headers=headers)
    assert response.status_code == 403


def test_backup_import_requires_admin() -> None:
    username = f"import-user-{uuid4().hex[:6]}"
    _create_user(username, "Password123!", role="user")
    headers = _login_headers(username, "Password123!")
    with TemporaryDirectory() as tmpdir:
        archive_path = Path(tmpdir) / "backup.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("stock.db", b"dummy")
            archive.writestr("users.db", b"dummy")
        with archive_path.open("rb") as stream:
            response = client.post(
                "/backup/import",
                headers=headers,
                files={"file": ("backup.zip", stream, "application/zip")},
            )
    assert response.status_code == 403


def test_backup_import_restores_user_database() -> None:
    headers = _login_headers("admin", "admin123")
    restored_username = f"restored-{uuid4().hex[:6]}"

    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        stock_copy = tmp_path / "stock.db"
        users_copy = tmp_path / "users.db"
        copy2(db.STOCK_DB_PATH, stock_copy)
        copy2(db.USERS_DB_PATH, users_copy)

        with closing(sqlite3.connect(users_copy)) as conn:
            conn.execute("DELETE FROM users WHERE username = ?", (restored_username,))
            conn.execute(
                """
                INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
                VALUES (?, ?, ?, ?, ?, 1, 'active')
                """,
                (
                    restored_username,
                    restored_username,
                    restored_username.lower(),
                    security.hash_password("demo-pass"),
                    "user",
                ),
            )
            conn.commit()

        archive_path = tmp_path / "backup.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.write(stock_copy, arcname="stock.db")
            archive.write(users_copy, arcname="users.db")

        with db.get_users_connection() as conn:
            conn.execute("DELETE FROM users WHERE username = ?", (restored_username,))
            conn.commit()

        with archive_path.open("rb") as stream:
            response = client.post(
                "/backup/import",
                headers=headers,
                files={"file": ("backup.zip", stream, "application/zip")},
            )
        assert response.status_code == 204, response.text

    with db.get_users_connection() as conn:
        cur = conn.execute("SELECT username FROM users WHERE username = ?", (restored_username,))
        restored = cur.fetchone()
        conn.execute("DELETE FROM users WHERE username = ?", (restored_username,))
        conn.commit()

    assert restored is not None


def test_backup_archive_preserves_media_files() -> None:
    media_root = MEDIA_ROOT
    sample_dir = media_root / f"backup-test-{uuid4().hex[:6]}"
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_file = sample_dir / "sample.txt"
    archive_path: Path | None = None
    try:
        original_content = "media-backup-content"
        sample_file.write_text(original_content)

        archive_path = create_backup_archive()

        sample_file.write_text("overwritten")
        restore_backup_from_zip(archive_path)

        assert sample_file.read_text() == original_content
    finally:
        sample_file.unlink(missing_ok=True)
        try:
            sample_dir.rmdir()
        except OSError:
            pass
        if archive_path:
            archive_path.unlink(missing_ok=True)


def test_updates_status_requires_admin() -> None:
    username = f"user-{uuid4().hex[:6]}"
    password = "secretpass"
    _create_user(username, password, role="user")
    headers = _login_headers(username, password)
    response = client.get("/updates/status", headers=headers)
    assert response.status_code == 403


def test_updates_status_returns_payload(monkeypatch: Any) -> None:
    async def fake_status() -> update_service.UpdateStatusData:
        return update_service.UpdateStatusData(
            repository="owner/repo",
            branch="main",
            current_commit="abc123",
            latest_pull_request=update_service.PullRequestData(
                number=7,
                title="Correctif critique",
                url="https://example.com/pr/7",
                merged_at=None,
                head_sha="deadbeef",
            ),
            last_deployed_pull=7,
            last_deployed_sha="deadbeef",
            last_deployed_at=None,
            previous_deployed_pull=None,
            previous_deployed_sha=None,
            previous_deployed_at=None,
            pending_update=False,
            can_revert=False,
        )

    monkeypatch.setattr(update_service, "get_status", fake_status)
    headers = _login_headers("admin", "admin123")
    response = client.get("/updates/status", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["repository"] == "owner/repo"
    assert payload["latest_pull_request"]["number"] == 7
    assert payload["pending_update"] is False


def test_updates_availability_for_regular_user(monkeypatch: Any) -> None:
    async def fake_status() -> update_service.UpdateStatusData:
        return update_service.UpdateStatusData(
            repository="owner/repo",
            branch="develop",
            current_commit="abc123",
            latest_pull_request=None,
            last_deployed_pull=5,
            last_deployed_sha="abc123",
            last_deployed_at=None,
            previous_deployed_pull=None,
            previous_deployed_sha=None,
            previous_deployed_at=None,
            pending_update=True,
            can_revert=False,
        )

    monkeypatch.setattr(update_service, "get_status", fake_status)

    username = f"user-{uuid4().hex[:6]}"
    password = "secretpass"
    _create_user(username, password, role="user")
    headers = _login_headers(username, password)
    response = client.get("/updates/availability", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["pending_update"] is True
    assert payload["branch"] == "develop"


def test_apply_update_returns_result(monkeypatch: Any) -> None:
    async def fake_apply() -> tuple[bool, update_service.UpdateStatusData]:
        status = update_service.UpdateStatusData(
            repository="owner/repo",
            branch="main",
            current_commit="cafebabe",
            latest_pull_request=update_service.PullRequestData(
                number=8,
                title="Nouvelle fonctionnalité",
                url="https://example.com/pr/8",
                merged_at=None,
                head_sha="abcdef01",
            ),
            last_deployed_pull=8,
            last_deployed_sha="abcdef01",
            last_deployed_at=None,
            previous_deployed_pull=7,
            previous_deployed_sha="deadbeef",
            previous_deployed_at=None,
            pending_update=False,
            can_revert=True,
        )
        return True, status

    monkeypatch.setattr(update_service, "apply_latest_update", fake_apply)
    headers = _login_headers("admin", "admin123")
    response = client.post("/updates/apply", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] is True
    assert payload["status"]["branch"] == "main"


def test_revert_update_returns_result(monkeypatch: Any) -> None:
    async def fake_revert() -> tuple[bool, update_service.UpdateStatusData]:
        status = update_service.UpdateStatusData(
            repository="owner/repo",
            branch="main",
            current_commit="deadbeef",
            latest_pull_request=None,
            last_deployed_pull=6,
            last_deployed_sha="deadbeef",
            last_deployed_at=None,
            previous_deployed_pull=7,
            previous_deployed_sha="cafebabe",
            previous_deployed_at=None,
            pending_update=True,
            can_revert=True,
        )
        return True, status

    monkeypatch.setattr(update_service, "revert_last_update", fake_revert)
    headers = _login_headers("admin", "admin123")
    response = client.post("/updates/revert", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] is True
    assert payload["status"]["last_deployed_sha"] == "deadbeef"


def test_apply_latest_update_returns_false_when_no_pull(monkeypatch: Any) -> None:
    settings = update_service.UpdateSettings(owner="owner", repository="repo", branch="main")
    state = update_service.UpdateState()

    monkeypatch.setattr(update_service, "_get_settings", lambda: settings)
    monkeypatch.setattr(update_service, "_load_state", lambda: state)

    async def fake_fetch(_: update_service.UpdateSettings) -> update_service.PullRequestData | None:
        return None

    monkeypatch.setattr(update_service, "_fetch_latest_merged_pull", fake_fetch)
    monkeypatch.setattr(update_service, "_current_commit", lambda: "cafebabe")

    updated, status = asyncio.run(update_service.apply_latest_update())

    assert updated is False
    assert status.latest_pull_request is None
    assert status.pending_update is False


def test_update_settings_fallback_to_git(monkeypatch: Any) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_BRANCH", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def fake_run_git_command(*args: str) -> str:
        if args == ("config", "--get", "remote.origin.url"):
            return "git@github.com:MyOrg/MyRepo.git"
        if args == ("rev-parse", "--abbrev-ref", "HEAD"):
            return "release"
        raise AssertionError(f"Commande inattendue: {args}")

    monkeypatch.setattr(update_service, "_run_git_command", fake_run_git_command)

    settings = update_service._get_settings()

    assert settings.slug == "MyOrg/MyRepo"
    assert settings.branch == "release"
    assert settings.token is None


def test_update_settings_invalid_remote(monkeypatch: Any) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_BRANCH", raising=False)

    def fake_run_git_command(*args: str) -> str:
        if args == ("config", "--get", "remote.origin.url"):
            return "invalid-remote"
        raise update_service.UpdateExecutionError("unexpected command")

    monkeypatch.setattr(update_service, "_run_git_command", fake_run_git_command)

    with pytest.raises(update_service.UpdateConfigurationError):
        update_service._get_settings()


def test_vehicle_types_crud_admin() -> None:
    headers = _login_headers("admin", "admin123")
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM vehicle_types WHERE code = ?", ("vsav",))
        conn.commit()
    create_resp = client.post(
        "/admin/vehicle-types",
        json={"code": "vsav", "label": "VSAV"},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["code"] == "vsav"
    list_resp = client.get("/admin/vehicle-types", headers=headers)
    assert list_resp.status_code == 200, list_resp.text
    assert any(entry["code"] == "vsav" for entry in list_resp.json())
    update_resp = client.patch(
        f"/admin/vehicle-types/{created['id']}",
        json={"label": "VSAV (Secours)"},
        headers=headers,
    )
    assert update_resp.status_code == 200, update_resp.text
    delete_resp = client.delete(f"/admin/vehicle-types/{created['id']}", headers=headers)
    assert delete_resp.status_code == 204, delete_resp.text
    refreshed = client.get("/admin/vehicle-types", headers=headers).json()
    entry = next(entry for entry in refreshed if entry["id"] == created["id"])
    assert entry["is_active"] is False


def test_custom_fields_validation() -> None:
    headers = _login_headers("admin", "admin123")
    field_resp = client.post(
        "/admin/custom-fields",
        json={
            "scope": "remise_items",
            "key": "custom_note",
            "label": "Note personnalisée",
            "field_type": "text",
            "required": True,
            "sort_order": 1,
        },
        headers=headers,
    )
    assert field_resp.status_code == 201, field_resp.text
    create_resp = client.post(
        "/remise-inventory/",
        json={"name": "Test extra", "sku": "REM-EXTRA-1", "extra": {"custom_note": "Ok"}},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    assert create_resp.json()["extra"]["custom_note"] == "Ok"
    invalid_resp = client.post(
        "/remise-inventory/",
        json={"name": "Test extra bad", "sku": "REM-EXTRA-2", "extra": {"custom_note": 12}},
        headers=headers,
    )
    assert invalid_resp.status_code == 400, invalid_resp.text


def test_admin_settings_permissions() -> None:
    _create_user("settings_user", "password123")
    headers = _login_headers("settings_user", "password123")
    response = client.get("/admin/vehicle-types", headers=headers)
    assert response.status_code == 403


def test_sent_message_read_counts() -> None:
    _create_user("sender_user", "password123")
    _create_user("recipient_one", "password123")
    _create_user("recipient_two", "password123")
    headers = _login_headers("sender_user", "password123")

    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM message_rate_limits")
        conn.execute("DELETE FROM message_recipients")
        conn.execute("DELETE FROM messages")
        conn.commit()

    response = client.post(
        "/messages/send",
        json={
            "category": "Info",
            "content": "Message avec accusé",
            "recipients": ["recipient_one", "recipient_two"],
            "broadcast": False,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    message_id = response.json()["message_id"]

    recipient_headers = _login_headers("recipient_one", "password123")
    read_response = client.post(f"/messages/{message_id}/read", headers=recipient_headers)
    assert read_response.status_code == 200, read_response.text

    sent_response = client.get("/messages/sent", headers=headers)
    assert sent_response.status_code == 200, sent_response.text
    sent_entry = next(entry for entry in sent_response.json() if entry["id"] == message_id)
    assert sent_entry["recipients_total"] == 2
    assert sent_entry["recipients_read"] == 1


def test_message_read_idempotent() -> None:
    _create_user("sender_idempotent", "password123")
    _create_user("recipient_idempotent", "password123")
    headers = _login_headers("sender_idempotent", "password123")

    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM message_rate_limits")
        conn.execute("DELETE FROM message_recipients")
        conn.execute("DELETE FROM messages")
        conn.commit()

    response = client.post(
        "/messages/send",
        json={
            "category": "Info",
            "content": "Idempotent read",
            "recipients": ["recipient_idempotent"],
            "broadcast": False,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    message_id = response.json()["message_id"]

    recipient_headers = _login_headers("recipient_idempotent", "password123")
    first_read = client.post(f"/messages/{message_id}/read", headers=recipient_headers)
    assert first_read.status_code == 200, first_read.text
    with db.get_users_connection() as conn:
        first_row = conn.execute(
            """
            SELECT read_at
            FROM message_recipients
            WHERE message_id = ? AND recipient_username = ?
            """,
            (message_id, "recipient_idempotent"),
        ).fetchone()
    assert first_row is not None
    first_read_at = first_row["read_at"]
    assert first_read_at is not None

    second_read = client.post(f"/messages/{message_id}/read", headers=recipient_headers)
    assert second_read.status_code == 200, second_read.text
    with db.get_users_connection() as conn:
        second_row = conn.execute(
            """
            SELECT read_at
            FROM message_recipients
            WHERE message_id = ? AND recipient_username = ?
            """,
            (message_id, "recipient_idempotent"),
        ).fetchone()
    assert second_row is not None
    assert second_row["read_at"] == first_read_at


def test_message_broadcast_read_counts() -> None:
    _create_user("broadcast_sender", "password123")
    _create_user("broadcast_recipient", "password123")
    headers = _login_headers("broadcast_sender", "password123")

    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM message_rate_limits")
        conn.execute("DELETE FROM message_recipients")
        conn.execute("DELETE FROM messages")
        conn.commit()

    response = client.post(
        "/messages/send",
        json={
            "category": "Info",
            "content": "Broadcast read",
            "recipients": [],
            "broadcast": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    message_id = response.json()["message_id"]

    recipient_headers = _login_headers("broadcast_recipient", "password123")
    read_response = client.post(f"/messages/{message_id}/read", headers=recipient_headers)
    assert read_response.status_code == 200, read_response.text

    with db.get_users_connection() as conn:
        total_row = conn.execute(
            "SELECT COUNT(*) AS total FROM message_recipients WHERE message_id = ?",
            (message_id,),
        ).fetchone()
    assert total_row is not None
    expected_total = int(total_row["total"])

    sent_response = client.get("/messages/sent", headers=headers)
    assert sent_response.status_code == 200, sent_response.text
    sent_entry = next(entry for entry in sent_response.json() if entry["id"] == message_id)
    assert sent_entry["recipients_total"] == expected_total
    assert sent_entry["recipients_read"] == 1


def test_message_rate_limit_429() -> None:
    _create_user("recipient_user", "password123")
    headers = _login_headers("admin", "admin123")

    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM message_rate_limits")
        conn.execute("DELETE FROM message_recipients")
        conn.execute("DELETE FROM messages")
        conn.commit()

    payload = {
        "category": "Info",
        "content": "Message test",
        "recipients": ["recipient_user"],
        "broadcast": False,
    }

    for _ in range(5):
        response = client.post("/messages/send", json=payload, headers=headers)
        assert response.status_code == 201, response.text

    response = client.post("/messages/send", json=payload, headers=headers)
    assert response.status_code == 429, response.text
    assert response.json()["detail"] == "Trop de messages envoyés. Réessayez dans quelques secondes."


def test_message_broadcast_archive_jsonl() -> None:
    _create_user("broadcast_recipient", "password123")
    headers = _login_headers("admin", "admin123")

    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM message_rate_limits")
        conn.commit()

    archive_month = datetime.now(timezone.utc).strftime("%Y-%m")
    archive_path = services.MESSAGE_ARCHIVE_ROOT / archive_month / "messages.jsonl"
    before_lines: list[str] = []
    if archive_path.exists():
        before_lines = archive_path.read_text(encoding="utf-8").splitlines()

    response = client.post(
        "/messages/send",
        json={
            "category": "Info",
            "content": "Broadcast test",
            "recipients": [],
            "broadcast": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    message_id = response.json()["message_id"]

    assert archive_path.exists()
    after_lines = archive_path.read_text(encoding="utf-8").splitlines()
    assert len(after_lines) >= len(before_lines) + 1
    entries = [json.loads(line) for line in after_lines]
    entry = next(item for item in entries if item["id"] == message_id)
    assert "broadcast_recipient" in entry["recipients"]
