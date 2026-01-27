from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, models, security, services
from backend.tests.auth_helpers import login_headers


client = TestClient(app)


def _reset_stock_tables() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM clothing_supplier_returns")
        conn.execute("DELETE FROM pending_clothing_assignments")
        conn.execute("DELETE FROM purchase_order_nonconformities")
        conn.execute("DELETE FROM purchase_order_receipts")
        conn.execute("DELETE FROM purchase_order_items")
        conn.execute("DELETE FROM purchase_orders")
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM dotations")
        conn.execute("DELETE FROM collaborators")
        conn.execute("DELETE FROM items")
        conn.commit()


def _create_item(conn: sqlite3.Connection, *, name: str, sku: str, size: str | None = None) -> int:
    cur = conn.execute(
        """
        INSERT INTO items (name, sku, size, quantity, low_stock_threshold, track_low_stock)
        VALUES (?, ?, ?, 0, 0, 0)
        """,
        (name, sku, size),
    )
    return int(cur.lastrowid)


def _create_collaborator(conn: sqlite3.Connection, *, full_name: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO collaborators (full_name)
        VALUES (?)
        """,
        (full_name,),
    )
    return int(cur.lastrowid)


def _create_dotation(
    conn: sqlite3.Connection,
    *,
    collaborator_id: int,
    item_id: int,
    quantity: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO dotations (collaborator_id, item_id, quantity, notes)
        VALUES (?, ?, ?, ?)
        """,
        (collaborator_id, item_id, quantity, "Dotation initiale"),
    )
    return int(cur.lastrowid)


def _create_admin_user(username: str, password: str) -> None:
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.execute(
            """
            INSERT INTO users (username, email, email_normalized, password, role, is_active, status)
            VALUES (?, ?, ?, ?, 'admin', 1, 'active')
            """,
            (username, username, username.lower(), security.hash_password(password)),
        )
        conn.commit()


def test_dotation_assignees_and_items() -> None:
    _reset_stock_tables()
    _create_admin_user("dotations_admin", "secret")
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Polos", sku="HAB-POLOS", size="S")
        collaborator_id = _create_collaborator(conn, full_name="CANGEMI SEBASTIEN")
        _create_collaborator(conn, full_name="Alice Martin")
        dotation_id = _create_dotation(
            conn, collaborator_id=collaborator_id, item_id=item_id, quantity=2
        )
        conn.commit()
    headers = login_headers(client, "dotations_admin", "secret")
    response = client.get("/dotations/assignees?module=clothing", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["assignees"] == [
        {
            "employee_id": collaborator_id,
            "display_name": "CANGEMI SEBASTIEN",
            "count": 1,
        }
    ]
    items_response = client.get(
        f"/dotations/assignees/{collaborator_id}/items?module=clothing",
        headers=headers,
    )
    assert items_response.status_code == 200
    items_payload = items_response.json()
    assert items_payload["items"] == [
        {
            "assignment_id": dotation_id,
            "item_id": item_id,
            "sku": "HAB-POLOS",
            "name": "Polos",
            "size_variant": "S",
            "qty": 2,
        }
    ]


def test_po_line_replacement_requires_beneficiary() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Parka", sku="HAB-001")
        conn.commit()
    with pytest.raises(ValueError, match="bénéficiaire"):
        services.create_purchase_order(
            models.PurchaseOrderCreate(
                supplier_id=None,
                status="ORDERED",
                note=None,
                items=[
                    models.PurchaseOrderItemInput(
                        item_id=item_id,
                        quantity_ordered=1,
                        line_type="replacement",
                    )
                ],
            )
        )


def test_receive_conforme_creates_stock_in_and_pending() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        new_item_id = _create_item(conn, name="Veste", sku="HAB-002")
        old_item_id = _create_item(conn, name="Veste ancienne", sku="HAB-003")
        collaborator_id = _create_collaborator(conn, full_name="Alice Martin")
        conn.execute("UPDATE items SET quantity = 2 WHERE id = ?", (old_item_id,))
        dotation_id = _create_dotation(
            conn, collaborator_id=collaborator_id, item_id=old_item_id, quantity=1
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=new_item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    return_employee_item_id=dotation_id,
                    return_qty=1,
                )
            ],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        item_row = conn.execute("SELECT quantity FROM items WHERE id = ?", (new_item_id,)).fetchone()
        assert item_row is not None
        assert item_row["quantity"] == 1
        receipt_row = conn.execute(
            "SELECT conformity_status FROM purchase_order_receipts WHERE purchase_order_id = ?",
            (order.id,),
        ).fetchone()
        assert receipt_row is not None
        assert receipt_row["conformity_status"] == "conforme"
        pending_row = conn.execute(
            "SELECT status, return_employee_item_id FROM pending_clothing_assignments WHERE purchase_order_id = ?",
            (order.id,),
        ).fetchone()
        assert pending_row is not None
        assert pending_row["status"] == "pending"
        assert pending_row["return_employee_item_id"] == dotation_id


def test_receive_non_conforme_creates_receipt_no_stock_in() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Gants", sku="HAB-004")
        order_cur = conn.execute(
            """
            INSERT INTO purchase_orders (supplier_id, status, note, auto_created, created_at)
            VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
            """,
            (None, "ORDERED", None),
        )
        conn.execute(
            """
            INSERT INTO purchase_order_items (purchase_order_id, item_id, quantity_ordered, quantity_received)
            VALUES (?, ?, ?, 0)
            """,
            (order_cur.lastrowid, item_id, 2),
        )
        conn.commit()
        order_id = int(order_cur.lastrowid)
        line_id = conn.execute(
            "SELECT id FROM purchase_order_items WHERE purchase_order_id = ?",
            (order_id,),
        ).fetchone()["id"]
    services.receive_purchase_order_line(
        order_id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=line_id,
            received_qty=1,
            conformity_status="non_conforme",
            nonconformity_reason="Endommagé",
            nonconformity_action="replacement",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        item_row = conn.execute("SELECT quantity FROM items WHERE id = ?", (item_id,)).fetchone()
        assert item_row is not None
        assert item_row["quantity"] == 0
        movement_row = conn.execute("SELECT COUNT(*) AS count FROM movements").fetchone()
        assert movement_row["count"] == 0
        receipt_row = conn.execute(
            "SELECT conformity_status FROM purchase_order_receipts WHERE purchase_order_id = ?",
            (order_id,),
        ).fetchone()
        assert receipt_row is not None
        assert receipt_row["conformity_status"] == "non_conforme"


def test_request_replacement_creates_nonconformity() -> None:
    _reset_stock_tables()
    _create_admin_user("admin_replacement", "password")
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Pantalon", sku="HAB-011")
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[models.PurchaseOrderItemInput(item_id=item_id, quantity_ordered=1)],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="non_conforme",
            nonconformity_reason="Déchiré",
            nonconformity_action="replacement",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        receipt_row = conn.execute(
            "SELECT id, purchase_order_line_id FROM purchase_order_receipts WHERE purchase_order_id = ?",
            (order.id,),
        ).fetchone()
        assert receipt_row is not None
    headers = login_headers(client, "admin_replacement", "password")
    response = client.post(
        f"/purchase-orders/{order.id}/request-replacement",
        json={"line_id": receipt_row["purchase_order_line_id"], "receipt_id": receipt_row["id"]},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    with db.get_stock_connection() as conn:
        row = conn.execute(
            """
            SELECT status, requested_replacement
            FROM purchase_order_nonconformities
            WHERE id = ?
            """,
            (payload["nonconformity_id"],),
        ).fetchone()
        assert row is not None
        assert row["requested_replacement"] == 1
        assert row["status"] == "replacement_requested"


def test_request_replacement_rejects_conforme_receipt() -> None:
    _reset_stock_tables()
    _create_admin_user("admin_replacement_conforme", "password")
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Gilet", sku="HAB-012")
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[models.PurchaseOrderItemInput(item_id=item_id, quantity_ordered=1)],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        receipt_row = conn.execute(
            "SELECT id, purchase_order_line_id FROM purchase_order_receipts WHERE purchase_order_id = ?",
            (order.id,),
        ).fetchone()
        assert receipt_row is not None
    headers = login_headers(client, "admin_replacement_conforme", "password")
    response = client.post(
        f"/purchase-orders/{order.id}/request-replacement",
        json={"line_id": receipt_row["purchase_order_line_id"], "receipt_id": receipt_row["id"]},
        headers=headers,
    )
    assert response.status_code == 409
    with db.get_stock_connection() as conn:
        count_row = conn.execute(
            "SELECT COUNT(*) AS count FROM purchase_order_nonconformities"
        ).fetchone()
        assert count_row is not None
        assert count_row["count"] == 0


def test_request_replacement_is_idempotent() -> None:
    _reset_stock_tables()
    _create_admin_user("admin_replacement_idempotent", "password")
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Pull", sku="HAB-013")
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[models.PurchaseOrderItemInput(item_id=item_id, quantity_ordered=1)],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="non_conforme",
            nonconformity_reason="Couture défectueuse",
            nonconformity_action="replacement",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        receipt_row = conn.execute(
            "SELECT id, purchase_order_line_id FROM purchase_order_receipts WHERE purchase_order_id = ?",
            (order.id,),
        ).fetchone()
        assert receipt_row is not None
    headers = login_headers(client, "admin_replacement_idempotent", "password")
    payload = {"line_id": receipt_row["purchase_order_line_id"], "receipt_id": receipt_row["id"]}
    first_response = client.post(
        f"/purchase-orders/{order.id}/request-replacement",
        json=payload,
        headers=headers,
    )
    assert first_response.status_code == 200
    second_response = client.post(
        f"/purchase-orders/{order.id}/request-replacement",
        json=payload,
        headers=headers,
    )
    assert second_response.status_code == 200
    with db.get_stock_connection() as conn:
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM purchase_order_nonconformities
            WHERE purchase_order_id = ?
            """,
            (order.id,),
        ).fetchone()
        assert count_row is not None
        assert count_row["count"] == 1


def test_validate_pending_assigns_new_unassigns_old_and_creates_return_movements_in_order() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        new_item_id = _create_item(conn, name="Veste", sku="HAB-005")
        old_item_id = _create_item(conn, name="Veste ancienne", sku="HAB-006")
        collaborator_id = _create_collaborator(conn, full_name="Jean Dupont")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (old_item_id,))
        dotation_id = _create_dotation(
            conn, collaborator_id=collaborator_id, item_id=old_item_id, quantity=1
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=new_item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    return_employee_item_id=dotation_id,
                    return_qty=1,
                )
            ],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    order = services.get_purchase_order(order.id)
    pending_id = order.pending_assignments[0].id
    services.validate_pending_assignment(order.id, pending_id, validated_by="tester")
    with db.get_stock_connection() as conn:
        new_dotation = conn.execute(
            "SELECT item_id FROM dotations WHERE collaborator_id = ?",
            (collaborator_id,),
        ).fetchone()
        assert new_dotation is not None
        assert new_dotation["item_id"] == new_item_id
        old_dotation = conn.execute(
            "SELECT 1 FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert old_dotation is None
        movement_rows = conn.execute(
            "SELECT delta, reason FROM movements WHERE item_id = ? ORDER BY id",
            (old_item_id,),
        ).fetchall()
        assert len(movement_rows) >= 2
        delta_in, reason_in = movement_rows[-2]
        delta_out, reason_out = movement_rows[-1]
        assert reason_in == "RETURN_FROM_EMPLOYEE"
        assert delta_in > 0
        assert reason_out == "RETURN_TO_SUPPLIER"
        assert delta_out < 0
        line_row = conn.execute(
            "SELECT return_status FROM purchase_order_items WHERE id = ?",
            (order.items[0].id,),
        ).fetchone()
        assert line_row is not None
        assert line_row["return_status"] == "shipped"


def test_validate_pending_decrements_returned_dotation_quantity() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        new_item_id = _create_item(conn, name="Casque neuf", sku="HAB-009")
        old_item_id = _create_item(conn, name="Casque F1", sku="HAB-010")
        collaborator_id = _create_collaborator(conn, full_name="Alice Martin")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (old_item_id,))
        dotation_id = _create_dotation(
            conn, collaborator_id=collaborator_id, item_id=old_item_id, quantity=3
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=new_item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    return_employee_item_id=dotation_id,
                    return_qty=1,
                )
            ],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    order = services.get_purchase_order(order.id)
    pending_id = order.pending_assignments[0].id
    services.validate_pending_assignment(order.id, pending_id, validated_by="tester")
    with db.get_stock_connection() as conn:
        updated_dotation = conn.execute(
            "SELECT quantity FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert updated_dotation is not None
        assert updated_dotation["quantity"] == 2
        new_dotation = conn.execute(
            """
            SELECT quantity
            FROM dotations
            WHERE collaborator_id = ? AND item_id = ?
            """,
            (collaborator_id, new_item_id),
        ).fetchone()
        assert new_dotation is not None
        assert new_dotation["quantity"] == 1


def test_validate_pending_fails_when_return_qty_exceeds_dotation() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        new_item_id = _create_item(conn, name="Parka", sku="HAB-011")
        old_item_id = _create_item(conn, name="Parka ancienne", sku="HAB-012")
        collaborator_id = _create_collaborator(conn, full_name="Louis Pasteur")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (old_item_id,))
        dotation_id = _create_dotation(
            conn, collaborator_id=collaborator_id, item_id=old_item_id, quantity=1
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=new_item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    return_employee_item_id=dotation_id,
                    return_qty=2,
                )
            ],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    order = services.get_purchase_order(order.id)
    pending_id = order.pending_assignments[0].id
    with pytest.raises(services.PendingAssignmentConflictError, match="Quantité à retirer"):
        services.validate_pending_assignment(order.id, pending_id, validated_by="tester")


def test_validate_fails_if_return_item_not_assigned() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        new_item_id = _create_item(conn, name="Veste", sku="HAB-007")
        old_item_id = _create_item(conn, name="Veste ancienne", sku="HAB-008")
        collaborator_id = _create_collaborator(conn, full_name="Marie Curie")
        other_collaborator_id = _create_collaborator(conn, full_name="Paul Durand")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (old_item_id,))
        dotation_id = _create_dotation(
            conn, collaborator_id=collaborator_id, item_id=old_item_id, quantity=1
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=None,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=new_item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    return_employee_item_id=dotation_id,
                    return_qty=1,
                )
            ],
        )
    )
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        conn.execute(
            "UPDATE dotations SET collaborator_id = ? WHERE id = ?",
            (other_collaborator_id, dotation_id),
        )
        conn.commit()
    _create_admin_user("admin_po", "password")
    headers = login_headers(client, "admin_po", "password")
    order = services.get_purchase_order(order.id)
    pending_id = order.pending_assignments[0].id
    response = client.post(
        f"/clothing/purchase-orders/{order.id}/pending-assignments/{pending_id}/validate",
        headers=headers,
    )
    assert response.status_code == 409
