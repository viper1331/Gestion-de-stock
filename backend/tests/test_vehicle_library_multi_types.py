from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


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


def test_vehicle_library_multi_types_union() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    remise_sku = f"REM-{uuid4().hex[:6]}"
    pharmacy_sku = f"PHA-{uuid4().hex[:6]}"
    shared_sku = f"SHR-{uuid4().hex[:6]}"

    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM remise_items WHERE sku IN (?, ?)", (remise_sku, shared_sku))
        conn.execute(
            "DELETE FROM pharmacy_items WHERE barcode IN (?, ?)",
            (pharmacy_sku, shared_sku),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, 0, 1)
            """,
            ("Tuyau remise", remise_sku, 2),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, 0, 1)
            """,
            ("Matériel partagé", shared_sku, 4),
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, barcode, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, 0, 1)
            """,
            ("Bandage", pharmacy_sku, 3),
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, barcode, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, 0, 1)
            """,
            ("Matériel partagé", shared_sku, 5),
        )
        conn.commit()

    response = client.get(
        "/vehicle-inventory/library",
        params={"vehicle_id": vehicle_id},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    skus = {entry["sku"] for entry in payload}
    assert {remise_sku, pharmacy_sku, shared_sku}.issubset(skus)

    shared_entries = [entry for entry in payload if entry["sku"] == shared_sku]
    assert len(shared_entries) == 1
    shared = shared_entries[0]
    assert set(shared["sources"]) == {"remise", "pharmacy"}
    assert shared["available_qty"]["remise"] == 4
    assert shared["available_qty"]["pharmacy"] == 5
