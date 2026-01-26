from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _site_headers(site_key: str = "JLL") -> dict[str, str]:
    headers = login_headers(client, "admin", "admin123")
    return {**headers, "X-Site-Key": site_key}


def test_low_stock_report_respects_track_low_stock() -> None:
    site_key = "JLL"
    services.ensure_site_database_ready(site_key)
    headers = _site_headers(site_key)

    included_sku = f"LSR-IN-{uuid4().hex[:6]}"
    excluded_sku = f"LSR-OUT-{uuid4().hex[:6]}"

    with db.get_stock_connection(site_key) as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Gants", included_sku, 2, 5, 1),
        )
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Chaussures", excluded_sku, 1, 4, 0),
        )

    response = client.get("/reports/low-stock", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    returned_skus = {entry["item"]["sku"] for entry in payload}
    assert included_sku in returned_skus
    assert excluded_sku not in returned_skus

    with db.get_stock_connection(site_key) as conn:
        conn.execute("DELETE FROM items WHERE sku IN (?, ?)", (included_sku, excluded_sku))


def test_clothing_stats_excludes_untracked_low_stock() -> None:
    site_key = "JLL"
    services.ensure_site_database_ready(site_key)
    headers = _site_headers(site_key)

    tracked_sku = f"STAT-IN-{uuid4().hex[:6]}"
    untracked_sku = f"STAT-OUT-{uuid4().hex[:6]}"

    baseline_response = client.get("/items/stats", headers=headers)
    assert baseline_response.status_code == 200, baseline_response.text
    baseline = baseline_response.json()["low_stock"]

    with db.get_stock_connection(site_key) as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Parka", tracked_sku, 1, 3, 1),
        )
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Blouson", untracked_sku, 0, 2, 0),
        )

    response = client.get("/items/stats", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["low_stock"] == baseline + 1

    with db.get_stock_connection(site_key) as conn:
        conn.execute("DELETE FROM items WHERE sku IN (?, ?)", (tracked_sku, untracked_sku))


def test_create_update_roundtrip_persists_track_low_stock() -> None:
    site_key = "JLL"
    services.ensure_site_database_ready(site_key)
    headers = _site_headers(site_key)

    sku = f"RT-{uuid4().hex[:6]}"

    create_response = client.post(
        "/items",
        headers=headers,
        json={
            "name": "Veste",
            "sku": sku,
            "quantity": 2,
            "low_stock_threshold": 5,
            "track_low_stock": False,
        },
    )
    assert create_response.status_code == 201, create_response.text
    created = create_response.json()
    assert created["track_low_stock"] is False

    update_response = client.put(
        f"/items/{created['id']}",
        headers=headers,
        json={"track_low_stock": True},
    )
    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["track_low_stock"] is True

    with db.get_stock_connection(site_key) as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (created["id"],))
