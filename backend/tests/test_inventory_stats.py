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


def test_clothing_stats_permissions() -> None:
    user_id = _create_user("stats-viewer", "stats123")
    headers = login_headers(client, "stats-viewer", "stats123")

    blocked = client.get("/items/stats", headers=headers)
    assert blocked.status_code == 403

    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module="clothing",
            can_view=True,
            can_edit=False,
        )
    )

    allowed = client.get("/items/stats", headers=headers)
    assert allowed.status_code == 200, allowed.text
    payload = allowed.json()
    assert set(payload.keys()) == {
        "references",
        "total_stock",
        "low_stock",
        "purchase_orders_open",
        "stockouts",
    }

    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()


def test_clothing_stats_site_scoping() -> None:
    services.ensure_database_ready()
    services.ensure_site_database_ready("JLL")
    services.ensure_site_database_ready("GSM")

    admin_headers = login_headers(client, "admin", "admin123")
    jll_headers = {**admin_headers, "X-Site-Key": "JLL"}
    gsm_headers = {**admin_headers, "X-Site-Key": "GSM"}

    jll_sku_a = f"JLL-{uuid4().hex[:6]}"
    jll_sku_b = f"JLL-{uuid4().hex[:6]}"
    jll_sku_c = f"JLL-{uuid4().hex[:6]}"
    gsm_sku = f"GSM-{uuid4().hex[:6]}"

    with db.get_stock_connection("JLL") as conn:
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
    with db.get_stock_connection("GSM") as conn:
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")

    with db.get_stock_connection("JLL") as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Gants", jll_sku_a, 2, 3, 1),
        )
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Veste", jll_sku_b, 0, 1, 1),
        )
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Casquette", jll_sku_c, 0, 1, 0),
        )
        conn.execute(
            "INSERT INTO purchase_orders (status) VALUES ('PENDING'), ('RECEIVED')"
        )

    with db.get_stock_connection("GSM") as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Chaussures", gsm_sku, 10, 5, 1),
        )

    try:
        jll_response = client.get("/items/stats", headers=jll_headers)
        assert jll_response.status_code == 200, jll_response.text
        jll_stats = jll_response.json()
        assert jll_stats["references"] == 3
        assert jll_stats["total_stock"] == 2
        assert jll_stats["low_stock"] == 2
        assert jll_stats["stockouts"] == 1
        assert jll_stats["purchase_orders_open"] == 1

        gsm_response = client.get("/items/stats", headers=gsm_headers)
        assert gsm_response.status_code == 200, gsm_response.text
        gsm_stats = gsm_response.json()
        assert gsm_stats["references"] == 1
        assert gsm_stats["total_stock"] == 10
        assert gsm_stats["low_stock"] == 0
        assert gsm_stats["stockouts"] == 0
        assert gsm_stats["purchase_orders_open"] == 0
    finally:
        with db.get_stock_connection("JLL") as conn:
            conn.execute("DELETE FROM purchase_orders")
            conn.execute(
                "DELETE FROM items WHERE sku IN (?, ?, ?)",
                (jll_sku_a, jll_sku_b, jll_sku_c),
            )
        with db.get_stock_connection("GSM") as conn:
            conn.execute("DELETE FROM items WHERE sku = ?", (gsm_sku,))


def test_remise_stats_payload() -> None:
    services.ensure_database_ready()
    services.ensure_site_database_ready("JLL")
    admin_headers = login_headers(client, "admin", "admin123")
    headers = {**admin_headers, "X-Site-Key": "JLL"}

    sku = f"REM-{uuid4().hex[:6]}"
    with db.get_stock_connection("JLL") as conn:
        conn.execute("DELETE FROM remise_purchase_orders")
        conn.execute("DELETE FROM remise_items")
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Casque", sku, 1, 2, 1),
        )
        conn.execute(
            "INSERT INTO remise_purchase_orders (status) VALUES ('ORDERED')"
        )

    try:
        response = client.get("/remise-inventory/stats", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["references"] == 1
        assert payload["total_stock"] == 1
        assert payload["low_stock"] == 1
        assert payload["stockouts"] == 0
        assert payload["purchase_orders_open"] == 1
    finally:
        with db.get_stock_connection("JLL") as conn:
            conn.execute("DELETE FROM remise_purchase_orders")
            conn.execute("DELETE FROM remise_items WHERE sku = ?", (sku,))


def test_remise_stats_excludes_untracked_alerts() -> None:
    services.ensure_database_ready()
    services.ensure_site_database_ready("JLL")
    admin_headers = login_headers(client, "admin", "admin123")
    headers = {**admin_headers, "X-Site-Key": "JLL"}

    tracked_stockout_sku = f"REM-{uuid4().hex[:6]}"
    untracked_stockout_sku = f"REM-{uuid4().hex[:6]}"
    untracked_low_sku = f"REM-{uuid4().hex[:6]}"
    tracked_low_sku = f"REM-{uuid4().hex[:6]}"

    with db.get_stock_connection("JLL") as conn:
        conn.execute("DELETE FROM remise_items")
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Gants", tracked_stockout_sku, 0, 2, 1),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Casque", untracked_stockout_sku, 0, 2, 0),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Bottes", untracked_low_sku, 1, 3, 0),
        )
        conn.execute(
            """
            INSERT INTO remise_items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Gilet", tracked_low_sku, 1, 3, 1),
        )

    try:
        response = client.get("/remise-inventory/stats", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["references"] == 4
        assert payload["total_stock"] == 2
        assert payload["low_stock"] == 2
        assert payload["stockouts"] == 1
    finally:
        with db.get_stock_connection("JLL") as conn:
            conn.execute(
                "DELETE FROM remise_items WHERE sku IN (?, ?, ?, ?)",
                (
                    tracked_stockout_sku,
                    untracked_stockout_sku,
                    untracked_low_sku,
                    tracked_low_sku,
                ),
            )


def test_pharmacy_stats_excludes_untracked_alerts() -> None:
    services.ensure_database_ready()
    services.ensure_site_database_ready("JLL")
    token = db.set_current_site("JLL")

    tracked_stockout_name = f"Pharma-{uuid4().hex[:6]}"
    untracked_stockout_name = f"Pharma-{uuid4().hex[:6]}"
    untracked_low_name = f"Pharma-{uuid4().hex[:6]}"
    tracked_low_name = f"Pharma-{uuid4().hex[:6]}"

    with db.get_stock_connection("JLL") as conn:
        conn.execute("DELETE FROM pharmacy_items")
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?)
            """,
            (tracked_stockout_name, 0, 2, 1),
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?)
            """,
            (untracked_stockout_name, 0, 2, 0),
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?)
            """,
            (untracked_low_name, 1, 3, 0),
        )
        conn.execute(
            """
            INSERT INTO pharmacy_items (name, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?)
            """,
            (tracked_low_name, 1, 3, 1),
        )

    try:
        stats = services.get_inventory_stats("pharmacy")
        assert stats.references == 4
        assert stats.total_stock == 2
        assert stats.low_stock == 2
        assert stats.stockouts == 1
    finally:
        with db.get_stock_connection("JLL") as conn:
            conn.execute(
                "DELETE FROM pharmacy_items WHERE name IN (?, ?, ?, ?)",
                (
                    tracked_stockout_name,
                    untracked_stockout_name,
                    untracked_low_name,
                    tracked_low_name,
                ),
            )
        db.reset_current_site(token)
