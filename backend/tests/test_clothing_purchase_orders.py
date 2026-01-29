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
        conn.execute("DELETE FROM supplier_modules")
        conn.execute("DELETE FROM suppliers")
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


def _create_supplier(conn: sqlite3.Connection, *, name: str = "Supplier") -> int:
    cur = conn.execute(
        """
        INSERT INTO suppliers (name, email)
        VALUES (?, ?)
        """,
        (name, None),
    )
    return int(cur.lastrowid)


def _create_dotation(
    conn: sqlite3.Connection,
    *,
    collaborator_id: int,
    item_id: int,
    quantity: int,
    degraded_qty: int = 0,
    lost_qty: int = 0,
) -> int:
    is_lost = int(lost_qty > 0)
    is_degraded = int(degraded_qty > 0)
    cur = conn.execute(
        """
        INSERT INTO dotations (
            collaborator_id,
            item_id,
            quantity,
            notes,
            is_lost,
            is_degraded,
            degraded_qty,
            lost_qty
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            collaborator_id,
            item_id,
            quantity,
            "Dotation initiale",
            is_lost,
            is_degraded,
            degraded_qty,
            lost_qty,
        ),
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
            "is_lost": False,
            "is_degraded": False,
            "degraded_qty": 0,
            "lost_qty": 0,
        }
    ]


def test_po_line_replacement_requires_beneficiary() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Parka", sku="HAB-001")
        supplier_id = _create_supplier(conn, name="Supplier-Parka")
        conn.commit()
    with pytest.raises(ValueError, match="bénéficiaire"):
        services.create_purchase_order(
            models.PurchaseOrderCreate(
                supplier_id=supplier_id,
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
        supplier_id = _create_supplier(conn, name="Supplier-Veste")
        conn.execute("UPDATE items SET quantity = 2 WHERE id = ?", (old_item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=old_item_id,
            quantity=1,
            lost_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
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
                    target_dotation_id=dotation_id,
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
            """
            SELECT status, return_employee_item_id, target_dotation_id
            FROM pending_clothing_assignments
            WHERE purchase_order_id = ?
            """,
            (order.id,),
        ).fetchone()
        assert pending_row is not None
        assert pending_row["status"] == "pending"
        assert pending_row["target_dotation_id"] == dotation_id


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


def test_non_conforme_blocks_pending_assignment_validation() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        new_item_id = _create_item(conn, name="Pantalon", sku="HAB-013")
        old_item_id = _create_item(conn, name="Pantalon ancien", sku="HAB-014")
        collaborator_id = _create_collaborator(conn, full_name="Claire Durand")
        supplier_id = _create_supplier(conn, name="Supplier-Pantalon")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (old_item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=old_item_id,
            quantity=1,
            lost_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=new_item_id,
                    quantity_ordered=2,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    target_dotation_id=dotation_id,
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
    services.receive_purchase_order_line(
        order.id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=order.items[0].id,
            received_qty=1,
            conformity_status="non_conforme",
            nonconformity_reason="Erreur taille",
        ),
        created_by="tester",
    )
    order = services.get_purchase_order(order.id)
    assert order.pending_assignments
    with db.get_stock_connection() as conn:
        item_row = conn.execute("SELECT quantity FROM items WHERE id = ?", (new_item_id,)).fetchone()
        assert item_row is not None
        assert item_row["quantity"] == 1
    with pytest.raises(
        services.PendingAssignmentConflictError,
        match="Réception non conforme : attribution impossible",
    ):
        services.validate_pending_assignment(
            order.id, order.pending_assignments[0].id, validated_by="tester"
        )
    with db.get_stock_connection() as conn:
        dotation_row = conn.execute(
            "SELECT lost_qty, degraded_qty FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert dotation_row is not None
        assert dotation_row["lost_qty"] == 1
        assert dotation_row["degraded_qty"] == 0


def test_receipt_summaries_include_conforme_and_non_conforme() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Chemise", sku="HAB-015")
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
            (order_cur.lastrowid, item_id, 3),
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
            received_qty=2,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    services.receive_purchase_order_line(
        order_id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=line_id,
            received_qty=1,
            conformity_status="non_conforme",
            nonconformity_reason="Manquant",
        ),
        created_by="tester",
    )


def test_close_replacement_requires_sent_request() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Veste", sku="HAB-016")
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
            (order_cur.lastrowid, item_id, 1),
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
            nonconformity_reason="Abîmé",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        receipt_row = conn.execute(
            """
            SELECT id
            FROM purchase_order_receipts
            WHERE purchase_order_id = ? AND purchase_order_line_id = ?
            """,
            (order_id, line_id),
        ).fetchone()
        assert receipt_row is not None
        receipt_id = int(receipt_row["id"])
    services.request_purchase_order_replacement(
        order_id,
        models.PurchaseOrderReplacementRequest(line_id=line_id, receipt_id=receipt_id),
        requested_by="tester",
    )
    with pytest.raises(ValueError, match="doit être envoyée"):
        services.close_purchase_order_replacement(order_id, closed_by="tester")


def test_close_replacement_unlocks_reception() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Chaussure", sku="HAB-017")
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
            (order_cur.lastrowid, item_id, 1),
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
            nonconformity_reason="Défaut",
        ),
        created_by="tester",
    )
    with db.get_stock_connection() as conn:
        receipt_row = conn.execute(
            """
            SELECT id
            FROM purchase_order_receipts
            WHERE purchase_order_id = ? AND purchase_order_line_id = ?
            """,
            (order_id, line_id),
        ).fetchone()
        assert receipt_row is not None
        receipt_id = int(receipt_row["id"])
    services.request_purchase_order_replacement(
        order_id,
        models.PurchaseOrderReplacementRequest(line_id=line_id, receipt_id=receipt_id),
        requested_by="tester",
    )
    with db.get_stock_connection() as conn:
        conn.execute(
            "UPDATE purchase_orders SET replacement_sent_at = CURRENT_TIMESTAMP WHERE id = ?",
            (order_id,),
        )
        conn.commit()
    order = services.close_purchase_order_replacement(order_id, closed_by="tester")
    assert order.replacement_closed_at is not None
    assert order.replacement_closed_by == "tester"
    services.receive_purchase_order_line(
        order_id,
        models.PurchaseOrderReceiveLinePayload(
            purchase_order_line_id=line_id,
            received_qty=1,
            conformity_status="conforme",
        ),
        created_by="tester",
    )
    order = services.get_purchase_order(order_id)
    assert order.items
    line = order.items[0]
    assert line.received_conforme_qty == 1
    assert line.received_non_conforme_qty == 1


def test_validate_pending_repairs_dotation_without_creating_new_card() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Veste", sku="HAB-005")
        collaborator_id = _create_collaborator(conn, full_name="Jean Dupont")
        supplier_id = _create_supplier(conn, name="Supplier-Veste-2")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=1,
            degraded_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    target_dotation_id=dotation_id,
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
            "SELECT quantity, degraded_qty, lost_qty FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert updated_dotation is not None
        assert updated_dotation["quantity"] == 1
        assert updated_dotation["degraded_qty"] == 0
        assert updated_dotation["lost_qty"] == 0
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM dotations
            WHERE collaborator_id = ? AND item_id = ?
            """,
            (collaborator_id, item_id),
        ).fetchone()
        assert count_row["count"] == 1
        movement_rows = conn.execute(
            "SELECT delta, reason FROM movements WHERE item_id = ? ORDER BY id",
            (item_id,),
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


def test_supplier_return_received_updates_return_status_in_detail() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Veste", sku="HAB-050")
        collaborator_id = _create_collaborator(conn, full_name="Maya Durand")
        supplier_id = _create_supplier(conn, name="Supplier-Veste")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=1,
            degraded_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Dégradation",
                    target_dotation_id=dotation_id,
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
    services.register_clothing_supplier_return(
        order.id,
        models.RegisterClothingSupplierReturnPayload(
            purchase_order_line_id=order.items[0].id,
            item_id=item_id,
            qty=1,
            status="supplier_received",
        ),
    )
    refreshed = services.get_purchase_order(order.id)
    assert refreshed.items[0].return_status == "supplier_received"


def test_validate_pending_repairs_single_unit_in_aggregated_dotation() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Casque F1", sku="HAB-010")
        collaborator_id = _create_collaborator(conn, full_name="Alice Martin")
        supplier_id = _create_supplier(conn, name="Supplier-Casque")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=2,
            degraded_qty=2,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    target_dotation_id=dotation_id,
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
            "SELECT quantity, degraded_qty, lost_qty FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert updated_dotation is not None
        assert updated_dotation["quantity"] == 2
        assert updated_dotation["degraded_qty"] == 1
        assert updated_dotation["lost_qty"] == 0
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM dotations
            WHERE collaborator_id = ? AND item_id = ?
            """,
            (collaborator_id, item_id),
        ).fetchone()
        assert count_row["count"] == 1


def test_validate_pending_decrements_returned_dotation_quantity() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Polo", sku="HAB-021")
        collaborator_id = _create_collaborator(conn, full_name="Claire Petit")
        supplier_id = _create_supplier(conn, name="Supplier-Polo")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=2,
            degraded_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Dégradation",
                    target_dotation_id=dotation_id,
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
            "SELECT quantity, degraded_qty, lost_qty FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert updated_dotation is not None
        assert updated_dotation["quantity"] == 2
        assert updated_dotation["degraded_qty"] == 0
        assert updated_dotation["lost_qty"] == 0


def test_validate_pending_merges_into_existing_ras_dotation() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Blouson", sku="HAB-023")
        collaborator_id = _create_collaborator(conn, full_name="Marc Leroy")
        supplier_id = _create_supplier(conn, name="Supplier-Blouson")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=2,
            degraded_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Dégradation",
                    target_dotation_id=dotation_id,
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
        ras_dotation = conn.execute(
            """
            SELECT quantity, notes
            FROM dotations
            WHERE id = ?
            """,
            (dotation_id,),
        ).fetchone()
        assert ras_dotation is not None
        assert ras_dotation["quantity"] == 2
        assert "Remplacement BC" in (ras_dotation["notes"] or "")
        assert "Remplacé via BC" in (ras_dotation["notes"] or "")
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM dotations
            WHERE collaborator_id = ? AND item_id = ?
            """,
            (collaborator_id, item_id),
        ).fetchone()
        assert count_row["count"] == 1


def test_validate_pending_rejects_return_without_degradation() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Sweat", sku="HAB-025")
        collaborator_id = _create_collaborator(conn, full_name="Nina Roche")
        supplier_id = _create_supplier(conn, name="Supplier-Sweat")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=2,
            degraded_qty=0,
        )
        conn.commit()
    with pytest.raises(
        ValueError, match="dotation sélectionnée doit être en perte ou dégradation"
    ):
        services.create_purchase_order(
            models.PurchaseOrderCreate(
                supplier_id=supplier_id,
                status="ORDERED",
                note=None,
                items=[
                    models.PurchaseOrderItemInput(
                        item_id=item_id,
                        quantity_ordered=1,
                        line_type="replacement",
                        beneficiary_employee_id=collaborator_id,
                        return_expected=True,
                        return_reason="Dégradation",
                        target_dotation_id=dotation_id,
                        return_qty=1,
                    )
                ],
            )
        )


def test_validate_pending_fails_when_target_is_not_lost_or_degraded() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Gilet", sku="HAB-016")
        collaborator_id = _create_collaborator(conn, full_name="Jean Valjean")
        supplier_id = _create_supplier(conn, name="Supplier-Gilet")
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=1,
            lost_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    target_dotation_id=dotation_id,
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
            "UPDATE dotations SET lost_qty = 0, degraded_qty = 0, is_lost = 0, is_degraded = 0 WHERE id = ?",
            (dotation_id,),
        )
        conn.commit()
    order = services.get_purchase_order(order.id)
    pending_id = order.pending_assignments[0].id
    with pytest.raises(
        services.PendingAssignmentConflictError, match="dotation ciblée doit être en PERTE"
    ):
        services.validate_pending_assignment(order.id, pending_id, validated_by="tester")


def test_validate_pending_fails_when_return_qty_exceeds_dotation() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Parka", sku="HAB-011")
        collaborator_id = _create_collaborator(conn, full_name="Louis Pasteur")
        supplier_id = _create_supplier(conn, name="Supplier-Parka-2")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=2,
            degraded_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    target_dotation_id=dotation_id,
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
    with pytest.raises(
        services.PendingAssignmentConflictError, match="Quantité retour > quantité dégradée"
    ):
        services.validate_pending_assignment(order.id, pending_id, validated_by="tester")


def test_validate_pending_loss_does_not_return_supplier() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Manteau", sku="HAB-030")
        collaborator_id = _create_collaborator(conn, full_name="Lucie Bernard")
        supplier_id = _create_supplier(conn, name="Supplier-Manteau")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=1,
            lost_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Perte",
                    target_dotation_id=dotation_id,
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
            "SELECT quantity, lost_qty FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert updated_dotation is not None
        assert updated_dotation["quantity"] == 1
        assert updated_dotation["lost_qty"] == 0
        movement_rows = conn.execute(
            "SELECT reason FROM movements WHERE item_id = ?",
            (item_id,),
        ).fetchall()
        reasons = [row["reason"] for row in movement_rows]
        assert "RETURN_TO_SUPPLIER" not in reasons
        assert "RETURN_FROM_EMPLOYEE" not in reasons
        returns = conn.execute("SELECT COUNT(*) AS count FROM clothing_supplier_returns").fetchone()
        assert returns["count"] == 0


def test_validate_pending_allows_repeat_replacement() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Polo", sku="HAB-040")
        collaborator_id = _create_collaborator(conn, full_name="Sonia Marchand")
        supplier_id = _create_supplier(conn, name="Supplier-Polo-Repeat")
        conn.execute("UPDATE items SET quantity = 2 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=2,
            degraded_qty=2,
        )
        conn.commit()
    for _ in range(2):
        order = services.create_purchase_order(
            models.PurchaseOrderCreate(
                supplier_id=supplier_id,
                status="ORDERED",
                note=None,
                items=[
                    models.PurchaseOrderItemInput(
                        item_id=item_id,
                        quantity_ordered=1,
                        line_type="replacement",
                        beneficiary_employee_id=collaborator_id,
                        return_expected=True,
                        return_reason="Dégradation",
                        target_dotation_id=dotation_id,
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
            "SELECT quantity, degraded_qty, lost_qty, notes FROM dotations WHERE id = ?",
            (dotation_id,),
        ).fetchone()
        assert updated_dotation is not None
        assert updated_dotation["quantity"] == 2
        assert updated_dotation["degraded_qty"] == 0
        assert updated_dotation["lost_qty"] == 0
        assert (updated_dotation["notes"] or "").count("Remplacement BC") == 2
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM dotations
            WHERE collaborator_id = ? AND item_id = ?
            """,
            (collaborator_id, item_id),
        ).fetchone()
        assert count_row["count"] == 1


def test_validate_fails_if_return_item_not_assigned() -> None:
    _reset_stock_tables()
    with db.get_stock_connection() as conn:
        item_id = _create_item(conn, name="Veste", sku="HAB-007")
        collaborator_id = _create_collaborator(conn, full_name="Marie Curie")
        other_collaborator_id = _create_collaborator(conn, full_name="Paul Durand")
        supplier_id = _create_supplier(conn, name="Supplier-Veste-3")
        conn.execute("UPDATE items SET quantity = 1 WHERE id = ?", (item_id,))
        dotation_id = _create_dotation(
            conn,
            collaborator_id=collaborator_id,
            item_id=item_id,
            quantity=1,
            lost_qty=1,
        )
        conn.commit()
    order = services.create_purchase_order(
        models.PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="ORDERED",
            note=None,
            items=[
                models.PurchaseOrderItemInput(
                    item_id=item_id,
                    quantity_ordered=1,
                    line_type="replacement",
                    beneficiary_employee_id=collaborator_id,
                    return_expected=True,
                    return_reason="Vétusté",
                    target_dotation_id=dotation_id,
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
