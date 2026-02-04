from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, models, security, services
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
        "types": ["incendie", "secours_a_personne"],
        "sizes": ["Cabine"],
    }
    response = client.post("/vehicle-inventory/categories/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _seed_remise_item(name: str, sku: str, quantity: int = 2) -> int:
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM remise_items WHERE sku = ?", (sku,))
        cur = conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, 0, 1)
            """,
            (name, sku, quantity),
        )
        conn.commit()
        return int(cur.lastrowid)


def _seed_pharmacy_item(name: str, sku: str, quantity: int = 2) -> int:
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pharmacy_items WHERE barcode = ?", (sku,))
        cur = conn.execute(
            """
            INSERT INTO pharmacy_items (name, barcode, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, 0, 1)
            """,
            (name, sku, quantity),
        )
        conn.commit()
        return int(cur.lastrowid)


def test_vehicle_library_endpoint_multi_types_sources() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    remise_sku = f"REM-{uuid4().hex[:6]}"
    pharmacy_sku = f"PHA-{uuid4().hex[:6]}"
    _seed_remise_item("Tuyau remise", remise_sku, quantity=2)
    _seed_pharmacy_item("Bandage", pharmacy_sku, quantity=3)

    response = client.get(
        f"/vehicles/{vehicle_id}/library",
        params={"include_lots": False},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert set(payload["sources"]) == {"remise", "pharmacy"}
    skus = {entry["sku"] for entry in payload["items"]}
    assert {remise_sku, pharmacy_sku}.issubset(skus)
    assert payload["counts"]["items"] == len(payload["items"])


def test_vehicle_library_endpoint_include_lots() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    remise_item_id = _seed_remise_item("Tuyau lot", f"REM-L-{uuid4().hex[:6]}")
    pharmacy_item_id = _seed_pharmacy_item("Bandage lot", f"PHA-L-{uuid4().hex[:6]}")

    remise_lot = services.create_remise_lot(
        models.RemiseLotCreate(name=f"Lot remise {uuid4().hex[:6]}")
    )
    services.add_remise_lot_item(
        remise_lot.id,
        models.RemiseLotItemBase(remise_item_id=remise_item_id, quantity=1),
    )

    pharmacy_lot = services.create_pharmacy_lot(
        models.PharmacyLotCreate(name=f"Lot pharmacie {uuid4().hex[:6]}")
    )
    services.add_pharmacy_lot_item(
        pharmacy_lot.id,
        models.PharmacyLotItemBase(pharmacy_item_id=pharmacy_item_id, quantity=1),
    )

    response = client.get(
        f"/vehicles/{vehicle_id}/library",
        params={"include_lots": True},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    origins = {entry["origin"] for entry in payload["lots"]}
    assert {"remise", "pharmacy"}.issubset(origins)
    lot_ids = {entry["lot_id"] for entry in payload["lots"]}
    assert {remise_lot.id, pharmacy_lot.id}.issubset(lot_ids)
    assert payload["counts"]["lots"] == len(payload["lots"])


def test_vehicle_library_endpoint_search_filters_items_and_lots() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    matching_sku = f"REM-SEARCH-{uuid4().hex[:6]}"
    _seed_remise_item("Recherche", matching_sku)
    _seed_remise_item("Autre", f"REM-OTHER-{uuid4().hex[:6]}")

    lot_item_sku = f"LOT-SKU-{uuid4().hex[:6]}"
    lot_item_id = _seed_remise_item("Lot item", lot_item_sku)
    lot = services.create_remise_lot(models.RemiseLotCreate(name=f"Lot {uuid4().hex[:6]}"))
    services.add_remise_lot_item(
        lot.id,
        models.RemiseLotItemBase(remise_item_id=lot_item_id, quantity=1),
    )

    item_response = client.get(
        f"/vehicles/{vehicle_id}/library",
        params={"q": matching_sku, "include_lots": False},
        headers=admin_headers,
    )
    assert item_response.status_code == 200, item_response.text
    item_payload = item_response.json()
    assert all(entry["sku"] == matching_sku for entry in item_payload["items"])

    lot_response = client.get(
        f"/vehicles/{vehicle_id}/library",
        params={"q": lot_item_sku, "include_lots": True},
        headers=admin_headers,
    )
    assert lot_response.status_code == 200, lot_response.text
    lot_payload = lot_response.json()
    assert any(entry["lot_id"] == lot.id for entry in lot_payload["lots"])
    assert all(
        entry["lot_id"] == lot.id for entry in lot_payload["lots"]
    ), "La recherche devrait filtrer les lots par SKU."


def test_vehicle_library_endpoint_requires_permission() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    user_id = _create_user("library_viewer", "password123", role="user")
    _grant_module_permission(user_id, "vehicle_inventory", can_view=False, can_edit=False)
    user_headers = login_headers(client, "library_viewer", "password123")

    response = client.get(
        f"/vehicles/{vehicle_id}/library",
        params={"include_lots": True},
        headers=user_headers,
    )
    assert response.status_code == 403, response.text
