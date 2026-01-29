from __future__ import annotations

from backend.core import db, models, services


def test_purchase_order_idempotency_key_reuses_existing_order() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM suppliers")
        item_cur = conn.execute(
            """
            INSERT INTO items (name, sku, size, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Gilet", "SKU-IDEMP", "M", 0, 0, 0),
        )
        supplier_cur = conn.execute(
            """
            INSERT INTO suppliers (name, email)
            VALUES (?, ?)
            """,
            ("Supplier Idem", None),
        )
        item_id = int(item_cur.lastrowid)
        supplier_id = int(supplier_cur.lastrowid)
        conn.commit()

    payload = models.PurchaseOrderCreate(
        supplier_id=supplier_id,
        status="ORDERED",
        note=None,
        items=[
            models.PurchaseOrderItemInput(
                item_id=item_id,
                quantity_ordered=2,
            )
        ],
    )
    idempotency_key = "idem-key-001"

    first_order = services.create_purchase_order(
        payload, idempotency_key=idempotency_key, created_by=1
    )
    second_order = services.create_purchase_order(
        payload, idempotency_key=idempotency_key, created_by=1
    )

    assert first_order.id == second_order.id

    with db.get_stock_connection() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS total FROM purchase_orders WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        assert rows["total"] == 1
