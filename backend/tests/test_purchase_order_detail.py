from __future__ import annotations

from backend.core import db, models, services


def test_purchase_order_detail_includes_sku_and_unit() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        item_cur = conn.execute(
            """
            INSERT INTO items (name, sku, size, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Gants nitrile", "SKU-UNIT", "XL", 0, 0, 0),
        )
        order_cur = conn.execute(
            """
            INSERT INTO purchase_orders (supplier_id, status, note, auto_created, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (None, "PENDING", None, 0),
        )
        order_id = order_cur.lastrowid
        item_id = item_cur.lastrowid
        conn.execute(
            """
            INSERT INTO purchase_order_items (purchase_order_id, item_id, quantity_ordered, quantity_received)
            VALUES (?, ?, ?, ?)
            """,
            (order_id, item_id, 5, 0),
        )
        conn.commit()

    order = services.get_purchase_order(order_id)
    assert order.items
    assert order.items[0].sku == "SKU-UNIT"
    assert order.items[0].unit == "XL"


def test_purchase_order_detail_includes_nonconformities_list() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_orders")
        order_cur = conn.execute(
            """
            INSERT INTO purchase_orders (supplier_id, status, note, auto_created, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (None, "PENDING", None, 0),
        )
        order_id = order_cur.lastrowid
        conn.commit()

    order = services.get_purchase_order(order_id)
    assert isinstance(order.nonconformities, list)
    assert order.nonconformities == []
