from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def setup_module(_: object) -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM items")
        conn.execute("DELETE FROM purchase_orders")
        conn.commit()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM module_permissions")
        conn.execute("DELETE FROM users WHERE username != 'admin'")
        conn.commit()


def _create_user(username: str, password: str, role: str = "user") -> int:
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


def _grant_module(user_id: int, module: str) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            """
            INSERT INTO module_permissions (user_id, module, can_view, can_edit)
            VALUES (?, ?, 1, 0)
            """,
            (user_id, module),
        )
        conn.commit()


def _login(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


def test_reports_overview_requires_permissions() -> None:
    _create_user("reporter", "secret123")
    headers = _login("reporter", "secret123")
    response = client.get(
        "/reports/overview",
        params={"module": "clothing", "start": "2024-01-01", "end": "2024-01-02"},
        headers=headers,
    )
    assert response.status_code == 403


def test_reports_overview_empty_module() -> None:
    user_id = _create_user("viewer", "secret123")
    _grant_module(user_id, "vehicle_inventory")
    headers = _login("viewer", "secret123")
    response = client.get(
        "/reports/overview",
        params={
            "module": "vehicle_inventory",
            "start": "2024-01-01",
            "end": "2024-01-02",
            "bucket": "day",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["in_qty"] == 0
    assert payload["kpis"]["out_qty"] == 0
    assert payload["series"]["moves"]
    assert payload["tops"]["out"] == []


def test_reports_overview_aggregation() -> None:
    user_id = _create_user("analyst", "secret123")
    _grant_module(user_id, "clothing")
    headers = _login("analyst", "secret123")
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM movements")
        conn.execute("DELETE FROM items")
        item_id = conn.execute(
            """
            INSERT INTO items (name, sku, size, quantity, low_stock_threshold, track_low_stock)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("Gants", "SKU-1", "M", 5, 2, 1),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO movements (item_id, delta, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (item_id, 10, "Appro", "2024-01-01 08:00:00"),
        )
        conn.execute(
            """
            INSERT INTO movements (item_id, delta, reason, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (item_id, -6, "Sortie", "2024-01-02 08:00:00"),
        )
        conn.commit()

    response = client.get(
        "/reports/overview",
        params={
            "module": "clothing",
            "start": "2024-01-01",
            "end": "2024-01-02",
            "bucket": "day",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["in_qty"] == 10
    assert payload["kpis"]["out_qty"] == 6
    assert payload["kpis"]["net_qty"] == 4
    series_map = {entry["t"]: entry for entry in payload["series"]["moves"]}
    assert series_map["2024-01-01"]["in"] == 10
    assert series_map["2024-01-02"]["out"] == 6
    assert payload["tops"]["out"][0]["qty"] == 6
