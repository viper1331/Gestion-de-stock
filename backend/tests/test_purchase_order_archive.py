from __future__ import annotations

import pytest

from backend.core import db, services


def _create_purchase_order(*, status: str) -> int:
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO purchase_orders (supplier_id, status, note, auto_created, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (None, status, None, 0),
        )
        conn.commit()
        return cur.lastrowid


def test_archive_requires_received_status() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.commit()
    order_id = _create_purchase_order(status="ORDERED")

    with pytest.raises(ValueError, match="reçus"):
        services.archive_purchase_order(order_id, archived_by=1)


def test_archive_listing_and_unarchive_flow() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.commit()

    received_id = _create_purchase_order(status="RECEIVED")
    pending_id = _create_purchase_order(status="PENDING")

    archived = services.archive_purchase_order(received_id, archived_by=1)
    assert archived.is_archived is True

    active_orders = services.list_purchase_orders()
    assert {order.id for order in active_orders} == {pending_id}

    all_orders = services.list_purchase_orders(include_archived=True)
    assert {order.id for order in all_orders} == {received_id, pending_id}

    archived_only = services.list_purchase_orders(archived_only=True)
    assert {order.id for order in archived_only} == {received_id}

    restored = services.unarchive_purchase_order(received_id)
    assert restored.is_archived is False

    active_after_restore = services.list_purchase_orders()
    assert {order.id for order in active_after_restore} == {received_id, pending_id}
