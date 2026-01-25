import sys
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app
from backend.core import db, security, services
from backend.services import system_settings
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _reset_tables() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_suggestion_lines")
        conn.execute("DELETE FROM purchase_suggestions")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM pharmacy_purchase_order_items")
        conn.execute("DELETE FROM pharmacy_purchase_orders")
        conn.execute("DELETE FROM remise_purchase_order_items")
        conn.execute("DELETE FROM remise_purchase_orders")
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute("DELETE FROM remise_items")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username IN ('suggest_admin', 'suggest_user')")
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
        row = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        assert row is not None
        return int(row["id"])


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def _grant_module_permission(user_id: int, module: str, *, can_view: bool, can_edit: bool) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO module_permissions (user_id, module, can_view, can_edit)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, module, int(can_view), int(can_edit)),
        )
        conn.commit()


def test_refresh_idempotent_grouping() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_a = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur A')"
        ).lastrowid
        supplier_b = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur B')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Gants', 'CL-01', 2, 5, 1, ?)
            """,
            (supplier_a,),
        )
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Casque', 'CL-02', 1, 4, 1, ?)
            """,
            (supplier_b,),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, supplier_id, track_low_stock)
            VALUES ('Batterie', 'RM-01', 0, 3, ?, 1)
            """,
            (supplier_a,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing", "inventory_remise"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        rows = conn.execute(
            "SELECT module_key, supplier_id, site_key FROM purchase_suggestions WHERE status = 'draft'"
        ).fetchall()
        assert len(rows) == 3

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing", "inventory_remise"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM purchase_suggestions WHERE status = 'draft'"
        ).fetchall()
        lines = conn.execute("SELECT id FROM purchase_suggestion_lines").fetchall()
        assert len(rows) == 3
        assert len(lines) == 3


def test_auto_reorder_groups_multiple_items_into_one_po_per_supplier() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur Unique')"
        ).lastrowid
        item_a = conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Blouson', 'CL-10', 1, 5, 1, ?)
            """,
            (supplier_id,),
        ).lastrowid
        item_b = conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Pantalon', 'CL-11', 0, 3, 1, ?)
            """,
            (supplier_id,),
        ).lastrowid
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        suggestions = conn.execute(
            """
            SELECT id, supplier_id
            FROM purchase_suggestions
            WHERE module_key = 'clothing' AND status = 'draft'
            """
        ).fetchall()
        assert len(suggestions) == 1
        assert suggestions[0]["supplier_id"] == supplier_id

        lines = conn.execute(
            """
            SELECT item_id, qty_suggested
            FROM purchase_suggestion_lines
            WHERE suggestion_id = ?
            """,
            (suggestions[0]["id"],),
        ).fetchall()
        assert len(lines) == 2
        qty_by_item = {row["item_id"]: row["qty_suggested"] for row in lines}
        assert qty_by_item[item_a] == 4
        assert qty_by_item[item_b] == 3


def test_auto_reorder_creates_one_po_per_supplier() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_a = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur A')"
        ).lastrowid
        supplier_b = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur B')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, supplier_id, track_low_stock)
            VALUES ('Pompe', 'RM-10', 1, 5, ?, 1)
            """,
            (supplier_a,),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, supplier_id, track_low_stock)
            VALUES ('Lampe', 'RM-11', 2, 6, ?, 1)
            """,
            (supplier_b,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["inventory_remise"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        suggestions = conn.execute(
            """
            SELECT supplier_id
            FROM purchase_suggestions
            WHERE module_key = 'inventory_remise' AND status = 'draft'
            """
        ).fetchall()
        assert len(suggestions) == 2
        supplier_ids = {row["supplier_id"] for row in suggestions}
        assert supplier_ids == {supplier_a, supplier_b}


def test_convert_suggestion_creates_purchase_order() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Fournisseur Convert')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Veste', 'CL-03', 1, 5, 1, ?)
            """,
            (supplier_id,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    suggestion_id = response.json()[0]["id"]

    with db.get_stock_connection() as conn:
        line_id = conn.execute(
            "SELECT id FROM purchase_suggestion_lines WHERE suggestion_id = ?",
            (suggestion_id,),
        ).fetchone()["id"]

    response = client.patch(
        f"/purchasing/suggestions/{suggestion_id}",
        json={"lines": [{"id": line_id, "qty_final": 7}]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = client.post(
        f"/purchasing/suggestions/{suggestion_id}/convert",
        headers=headers,
    )
    assert response.status_code == 200, response.text

    with db.get_stock_connection() as conn:
        status_row = conn.execute(
            "SELECT status FROM purchase_suggestions WHERE id = ?",
            (suggestion_id,),
        ).fetchone()
        assert status_row["status"] == "converted"
        order_row = conn.execute(
            "SELECT id FROM purchase_orders WHERE supplier_id = ?",
            (supplier_id,),
        ).fetchone()
        assert order_row is not None
        item_row = conn.execute(
            """
            SELECT quantity_ordered
            FROM purchase_order_items
            WHERE purchase_order_id = ?
            """,
            (order_row["id"],),
        ).fetchone()
        assert item_row["quantity_ordered"] == 7


def test_permissions_filter_modules() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    user_id = _create_user("suggest_user", "password", role="user")
    _grant_module_permission(user_id, "purchase_suggestions", can_view=True, can_edit=False)
    _grant_module_permission(user_id, "pharmacy", can_view=True, can_edit=False)
    admin_headers = _login_headers("suggest_admin", "password")
    user_headers = _login_headers("suggest_user", "password")

    with db.get_stock_connection() as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES ('Chemise', 'CL-04', 1, 4, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold)
            VALUES ('Bandage', 1, 5)
            """
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing", "pharmacy"]},
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text

    response = client.get("/purchasing/suggestions", headers=user_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data
    assert all(entry["module_key"] == "pharmacy" for entry in data)

    response = client.get("/purchasing/suggestions", params={"module": "clothing"}, headers=user_headers)
    assert response.status_code == 403, response.text


def test_suggestion_variant_labels() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, size, quantity, low_stock_threshold, track_low_stock)
            VALUES ('T-shirt', 'CL-05', 'M', 1, 5, 1)
            """
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, dosage, packaging, quantity, low_stock_threshold)
            VALUES ('Paracétamol', '500mg', 'Boîte 100', 2, 6)
            """
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES ('Lampe', 'RM-02', 0, 4, 1)
            """
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing", "pharmacy", "inventory_remise"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    response = client.get("/purchasing/suggestions", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    suggestions_by_module = {entry["module_key"]: entry for entry in data}
    assert suggestions_by_module["clothing"]["lines"][0]["variant_label"] == "M"
    assert (
        suggestions_by_module["pharmacy"]["lines"][0]["variant_label"]
        == "500mg • Boîte 100"
    )
    assert suggestions_by_module["inventory_remise"]["lines"][0]["variant_label"] is None


def test_pharmacy_expiry_soon_suggestions() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")
    system_settings.set_setting_json(
        system_settings.PURCHASE_SUGGESTION_SETTINGS_KEY,
        {"expiry_soon_days": 10},
        "suggest_admin",
    )

    soon_date = (date.today() + timedelta(days=7)).isoformat()
    expired_date = (date.today() - timedelta(days=1)).isoformat()
    combo_date = (date.today() + timedelta(days=5)).isoformat()

    with db.get_stock_connection() as conn:
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, expiration_date)
            VALUES ('Gaze', 50, 5, ?)
            """,
            (soon_date,),
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, expiration_date)
            VALUES ('Bandage périmé', 50, 5, ?)
            """,
            (expired_date,),
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, expiration_date)
            VALUES ('Compresses', 1, 5, ?)
            """,
            (combo_date,),
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["pharmacy"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    lines = [line for suggestion in response.json() for line in suggestion["lines"]]
    gaze = next(line for line in lines if line["label"] == "Gaze")
    assert gaze["reason_codes"] == ["EXPIRY_SOON"]
    assert gaze["expiry_days_left"] == 7
    assert all(line["label"] != "Bandage périmé" for line in lines)

    compresses = next(line for line in lines if line["label"] == "Compresses")
    assert set(compresses["reason_codes"]) == {"LOW_STOCK", "EXPIRY_SOON"}
    assert compresses["expiry_days_left"] == 5


def test_module_without_expiry_field_does_not_break() -> None:
    _reset_tables()
    _create_user("suggest_admin", "password", role="admin")
    headers = _login_headers("suggest_admin", "password")

    with db.get_stock_connection() as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES ('Veste hiver', 'CL-88', 1, 5, 1)
            """
        )
        conn.commit()

    response = client.post(
        "/purchasing/suggestions/refresh",
        json={"module_keys": ["clothing"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    lines = [line for suggestion in response.json() for line in suggestion["lines"]]
    assert len(lines) == 1
    assert lines[0]["reason_codes"] == ["LOW_STOCK"]
    assert lines[0]["expiry_date"] is None
