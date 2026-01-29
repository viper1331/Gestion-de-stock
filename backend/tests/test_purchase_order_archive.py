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


def _create_item(*, name: str, sku: str) -> int:
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO items (name, sku, size, quantity)
            VALUES (?, ?, ?, 0)
            """,
            (name, sku, "T"),
        )
        conn.commit()
        return cur.lastrowid


def _create_collaborator(*, full_name: str) -> int:
    with db.get_stock_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO collaborators (full_name)
            VALUES (?)
            """,
            (full_name,),
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


def test_archive_blocks_nonconformity_replacement_in_progress() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_nonconformities")
        conn.execute("DELETE FROM purchase_order_receipts")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.commit()
        item_id = _create_item(name="Veste", sku="HAB-ARCH-1")
        order_id = _create_purchase_order(status="RECEIVED")
        line_cur = conn.execute(
            """
            INSERT INTO purchase_order_items (
                purchase_order_id,
                item_id,
                quantity_ordered,
                quantity_received,
                return_status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, item_id, 1, 1, "none"),
        )
        line_id = line_cur.lastrowid
        receipt_cur = conn.execute(
            """
            INSERT INTO purchase_order_receipts (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                module,
                received_qty,
                conformity_status,
                nonconformity_reason,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2024-01-01 08:00:00')
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                "clothing",
                1,
                "non_conforme",
                "Endommagé",
                "tester",
            ),
        )
        receipt_id = receipt_cur.lastrowid
        conn.execute(
            """
            INSERT INTO purchase_order_nonconformities (
                site_key,
                module,
                purchase_order_id,
                purchase_order_line_id,
                receipt_id,
                status,
                reason,
                requested_replacement
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                db.get_current_site_key(),
                "clothing",
                order_id,
                line_id,
                receipt_id,
                "open",
                "Endommagé",
            ),
        )
        conn.commit()

    with pytest.raises(ValueError, match="remplacement"):
        services.archive_purchase_order(order_id, archived_by=1)


def test_archive_allows_closed_replacement_with_conformity_and_assignment() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM purchase_order_nonconformities")
        conn.execute("DELETE FROM purchase_order_receipts")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.commit()
        item_id = _create_item(name="Gants", sku="HAB-ARCH-2")
        order_id = _create_purchase_order(status="RECEIVED")
        line_cur = conn.execute(
            """
            INSERT INTO purchase_order_items (
                purchase_order_id,
                item_id,
                quantity_ordered,
                quantity_received,
                return_status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, item_id, 1, 1, "none"),
        )
        line_id = line_cur.lastrowid
        non_conforme_cur = conn.execute(
            """
            INSERT INTO purchase_order_receipts (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                module,
                received_qty,
                conformity_status,
                nonconformity_reason,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2024-01-01 08:00:00')
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                "clothing",
                1,
                "non_conforme",
                "Endommagé",
                "tester",
            ),
        )
        non_conforme_id = non_conforme_cur.lastrowid
        conn.execute(
            """
            INSERT INTO purchase_order_receipts (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                module,
                received_qty,
                conformity_status,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, '2024-01-02 10:00:00')
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                "clothing",
                1,
                "conforme",
                "tester",
            ),
        )
        conn.execute(
            """
            INSERT INTO purchase_order_nonconformities (
                site_key,
                module,
                purchase_order_id,
                purchase_order_line_id,
                receipt_id,
                status,
                reason,
                requested_replacement
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                db.get_current_site_key(),
                "clothing",
                order_id,
                line_id,
                non_conforme_id,
                "closed",
                "Endommagé",
            ),
        )
        conn.execute(
            """
            UPDATE purchase_orders
            SET replacement_closed_at = '2024-01-02 11:00:00',
                replacement_closed_by = 'tester'
            WHERE id = ?
            """,
            (order_id,),
        )
        conn.commit()

    archived = services.archive_purchase_order(order_id, archived_by=1)
    assert archived.is_archived is True


def test_archive_allows_received_supplier_return_after_shipped_history() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM clothing_supplier_returns")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM items")
        conn.commit()
        item_id = _create_item(name="Pantalon", sku="HAB-ARCH-4")
        order_id = _create_purchase_order(status="RECEIVED")
        line_cur = conn.execute(
            """
            INSERT INTO purchase_order_items (
                purchase_order_id,
                item_id,
                quantity_ordered,
                quantity_received,
                return_status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, item_id, 1, 1, "shipped"),
        )
        line_id = line_cur.lastrowid
        conn.execute(
            """
            INSERT INTO clothing_supplier_returns (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                qty,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                1,
                "shipped",
                "2024-01-01 10:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO clothing_supplier_returns (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                qty,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                1,
                "supplier_received",
                "2024-01-02 10:00:00",
            ),
        )
        conn.commit()

    archived = services.archive_purchase_order(order_id, archived_by=1)
    assert archived.is_archived is True


def test_archive_allows_closed_replacement_with_validated_assignment_and_stale_status() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM pending_clothing_assignments")
        conn.execute("DELETE FROM purchase_order_nonconformities")
        conn.execute("DELETE FROM purchase_order_receipts")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM collaborators")
        conn.execute("DELETE FROM items")
        conn.commit()
        item_id = _create_item(name="Parka", sku="HAB-ARCH-3")
        collaborator_id = _create_collaborator(full_name="Alex Pilot")
        order_id = _create_purchase_order(status="PARTIALLY_RECEIVED")
        line_cur = conn.execute(
            """
            INSERT INTO purchase_order_items (
                purchase_order_id,
                item_id,
                quantity_ordered,
                quantity_received,
                return_status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (order_id, item_id, 1, 1, "none"),
        )
        line_id = line_cur.lastrowid
        non_conforme_cur = conn.execute(
            """
            INSERT INTO purchase_order_receipts (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                module,
                received_qty,
                conformity_status,
                nonconformity_reason,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2024-01-01 08:00:00')
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                "clothing",
                1,
                "non_conforme",
                "Défaut",
                "tester",
            ),
        )
        non_conforme_id = non_conforme_cur.lastrowid
        conforme_cur = conn.execute(
            """
            INSERT INTO purchase_order_receipts (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                module,
                received_qty,
                conformity_status,
                created_by,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, '2024-01-02 10:00:00')
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                "clothing",
                1,
                "conforme",
                "tester",
            ),
        )
        conforme_id = conforme_cur.lastrowid
        conn.execute(
            """
            INSERT INTO purchase_order_nonconformities (
                site_key,
                module,
                purchase_order_id,
                purchase_order_line_id,
                receipt_id,
                status,
                reason,
                requested_replacement
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                db.get_current_site_key(),
                "clothing",
                order_id,
                line_id,
                non_conforme_id,
                "closed",
                "Défaut",
            ),
        )
        conn.execute(
            """
            UPDATE purchase_orders
            SET replacement_closed_at = '2024-01-02 11:00:00',
                replacement_closed_by = 'tester'
            WHERE id = ?
            """,
            (order_id,),
        )
        conn.execute(
            """
            INSERT INTO pending_clothing_assignments (
                site_key,
                purchase_order_id,
                purchase_order_line_id,
                receipt_id,
                employee_id,
                new_item_id,
                new_item_sku,
                new_item_size,
                qty,
                return_employee_item_id,
                target_dotation_id,
                return_reason,
                status,
                validated_at,
                validated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                db.get_current_site_key(),
                order_id,
                line_id,
                conforme_id,
                collaborator_id,
                item_id,
                "HAB-ARCH-3",
                "T",
                1,
                None,
                None,
                None,
                "validated",
                "tester",
            ),
        )
        conn.commit()

    archived = services.archive_purchase_order(order_id, archived_by=1)
    assert archived.is_archived is True
