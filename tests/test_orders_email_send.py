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
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM remise_purchase_order_items")
        conn.execute("DELETE FROM remise_purchase_orders")
        conn.execute("DELETE FROM remise_items")
        conn.execute("DELETE FROM supplier_modules")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username LIKE 'email_send_%'")
        conn.commit()


def _create_user(
    username: str, password: str, *, role: str, email: str | None = None
) -> str:
    services.ensure_database_ready()
    resolved_email = email or f"{username}@example.com"
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            "DELETE FROM users WHERE email_normalized = ?",
            (resolved_email.lower(),),
        )
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, ?, 1, 'active')
            """,
            (username, resolved_email, resolved_email.lower(), security.hash_password(password), role),
        )
        conn.commit()
    return resolved_email


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def _create_supplier(headers: dict[str, str], *, name: str, email: str | None, module: str) -> int:
    payload = {
        "name": name,
        "email": email,
        "contact_name": None,
        "phone": None,
        "address": None,
        "modules": [module],
    }
    response = client.post("/suppliers/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_remise_item() -> int:
    with db.get_stock_connection() as conn:
        item_id = conn.execute(
            "INSERT INTO remise_items (name, sku, quantity) VALUES (?, ?, ?)",
            ("Gants", "REM-EMAIL-1", 2),
        ).lastrowid
        conn.commit()
        return int(item_id)


def _create_pharmacy_item() -> int:
    with db.get_stock_connection() as conn:
        item_id = conn.execute(
            "INSERT INTO pharmacy_items (name, quantity, low_stock_threshold) VALUES (?, ?, ?)",
            ("Test Pharma", 1, 3),
        ).lastrowid
        conn.commit()
        return int(item_id)


def test_send_remise_order_uses_supplier_email() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Remise",
        email="remise@test.fr",
        module="inventory_remise",
    )
    remise_item_id = _create_remise_item()

    response = client.post(
        "/remise-inventory/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"remise_item_id": remise_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-remise"
        response = client.post(
            f"/remise-inventory/orders/{order_id}/send-to-supplier",
            headers=headers,
            json={},
        )

    assert response.status_code == 200, response.text
    assert send_email.call_args.args[0] == "remise@test.fr"


def test_send_pharmacy_order_uses_supplier_email() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Pharma",
        email="pharma@test.fr",
        module="pharmacy",
    )
    pharmacy_item_id = _create_pharmacy_item()

    response = client.post(
        "/pharmacy/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"pharmacy_item_id": pharmacy_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    with patch("backend.core.services.email_sender.send_email") as send_email:
        send_email.return_value = "msg-pharma"
        response = client.post(
            f"/pharmacy/orders/{order_id}/send-to-supplier",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert send_email.call_args.args[0] == "pharma@test.fr"


def test_send_order_supplier_deleted_returns_error() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Supprimé",
        email="deleted@test.fr",
        module="inventory_remise",
    )
    remise_item_id = _create_remise_item()

    response = client.post(
        "/remise-inventory/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"remise_item_id": remise_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    response = client.delete(f"/suppliers/{supplier_id}", headers=headers)
    assert response.status_code == 204, response.text

    response = client.post(
        f"/remise-inventory/orders/{order_id}/send-to-supplier",
        headers=headers,
        json={},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Fournisseur introuvable sur le site actif."


def test_send_order_supplier_missing_email_returns_error() -> None:
    _reset_tables()
    _create_user("email_send_admin", "password", role="admin")
    headers = _login_headers("email_send_admin", "password")

    supplier_id = _create_supplier(
        headers,
        name="Fournisseur Sans Email",
        email="",
        module="pharmacy",
    )
    pharmacy_item_id = _create_pharmacy_item()

    response = client.post(
        "/pharmacy/orders/",
        json={
            "supplier_id": supplier_id,
            "status": "PENDING",
            "note": None,
            "items": [{"pharmacy_item_id": pharmacy_item_id, "quantity_ordered": 1}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    order_id = response.json()["id"]

    response = client.post(
        f"/pharmacy/orders/{order_id}/send-to-supplier",
        headers=headers,
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Email fournisseur manquant. Ajoutez un email au fournisseur pour activer l'envoi."
    )
