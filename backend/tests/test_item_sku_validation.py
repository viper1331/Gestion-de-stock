import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def setup_module(_: object) -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        conn.commit()


def _login_headers() -> dict[str, str]:
    return login_headers(client, "admin", "admin123")


def _create_supplier(headers: dict[str, str]) -> int:
    response = client.post(
        "/suppliers/",
        json={"name": f"Supplier-{uuid4().hex[:6]}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_create_item_allows_missing_supplier_when_sku_provided() -> None:
    headers = _login_headers()
    response = client.post(
        "/items/",
        json={
            "name": "Article test",
            "sku": f"SKU-{uuid4().hex[:8]}",
            "quantity": 1,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["supplier_id"] is None


def test_update_item_requires_name_when_sku_changes() -> None:
    headers = _login_headers()
    supplier_id = _create_supplier(headers)
    create_response = client.post(
        "/items/",
        json={
            "name": "Article test",
            "sku": f"SKU-{uuid4().hex[:8]}",
            "quantity": 3,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert create_response.status_code == 201, create_response.text
    item_id = create_response.json()["id"]

    update_response = client.put(
        f"/items/{item_id}",
        json={
            "sku": f"SKU-{uuid4().hex[:8]}",
            "quantity": 2,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert update_response.status_code == 400, update_response.text
    assert update_response.json()["detail"] == "Nom obligatoire"


def test_create_item_with_sku_and_required_fields_succeeds() -> None:
    headers = _login_headers()
    supplier_id = _create_supplier(headers)
    response = client.post(
        "/items/",
        json={
            "name": "Article valide",
            "sku": f"SKU-{uuid4().hex[:8]}",
            "quantity": 0,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
