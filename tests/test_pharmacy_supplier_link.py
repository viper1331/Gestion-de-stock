import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _reset_tables() -> None:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM purchase_order_email_log")
        conn.execute("DELETE FROM purchase_order_audit_log")
        conn.commit()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_suggestion_lines")
        conn.execute("DELETE FROM purchase_suggestions")
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM supplier_modules")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username = 'pharmacy_admin'")
        conn.commit()


def _create_user(username: str, password: str, *, role: str) -> None:
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


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def _create_supplier(headers: dict[str, str], *, name: str, email: str, module: str) -> int:
    response = client.post(
        "/suppliers/",
        json={
            "name": name,
            "email": email,
            "contact_name": None,
            "phone": None,
            "address": None,
            "modules": [module],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_pharmacy_supplier_linked_to_suggestions_and_send() -> None:
    _reset_tables()
    _create_user("pharmacy_admin", "password", role="admin")
    headers = _login_headers("pharmacy_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Pharma Fournisseur",
        email="pharma@test.fr",
        module="pharmacy",
    )

    response = client.post(
        "/pharmacy/",
        json={
            "name": "Produit Pharma",
            "quantity": 1,
            "low_stock_threshold": 5,
            "supplier_id": supplier_id,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    pharmacy_item_id = response.json()["id"]

    response = client.get(f"/pharmacy/{pharmacy_item_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["supplier_id"] == supplier_id

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["pharmacy"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    suggestion = response.json()[0]
    assert suggestion["supplier_id"] == supplier_id

    response = client.post(
        f"/purchasing/suggestions/{suggestion['id']}/convert",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    order_id = response.json()["purchase_order_id"]

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-pharma"
        response = client.post(
            f"/pharmacy/orders/{order_id}/send-to-supplier",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert send_email.call_args.args[0] == "pharma@test.fr"

    response = client.delete(f"/suppliers/{supplier_id}", headers=headers)
    assert response.status_code == 204, response.text

    response = client.post(
        f"/pharmacy/orders/{order_id}/send-to-supplier",
        headers=headers,
    )
    assert response.status_code == 409
