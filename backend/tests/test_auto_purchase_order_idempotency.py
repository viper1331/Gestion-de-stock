from __future__ import annotations

from backend.core import db, services


def test_refresh_auto_purchase_orders_is_idempotent() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name) VALUES ('Auto Supplier')"
        ).lastrowid
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Gants', 'AUTO-1', 1, 5, 1, ?)
            """,
            (supplier_id,),
        )
        conn.commit()

    services.refresh_auto_purchase_orders("purchase_orders")
    services.refresh_auto_purchase_orders("purchase_orders")

    with db.get_stock_connection() as conn:
        orders = conn.execute(
            "SELECT id FROM purchase_orders WHERE auto_created = 1"
        ).fetchall()
        assert len(orders) == 1
        lines = conn.execute(
            "SELECT id FROM purchase_order_items WHERE purchase_order_id = ?",
            (orders[0]["id"],),
        ).fetchall()
        assert len(lines) == 1

        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        conn.commit()
