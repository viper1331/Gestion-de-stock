from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import app
from backend.core import db, models, security, services


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


def _login_headers(username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("access_token"), payload
    token = payload["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _grant_module_permission(user_id: int, module: str, *, can_view: bool) -> None:
    services.upsert_module_permission(
        models.ModulePermissionUpsert(
            user_id=user_id,
            module=module,
            can_view=can_view,
            can_edit=False,
        )
    )


def test_stock_inventory_pdf_export_requires_permission() -> None:
    user_id = _create_user("stock-pdf", "stockpass")
    _grant_module_permission(user_id, "clothing", can_view=True)
    headers = _login_headers("stock-pdf", "stockpass")
    response = client.get("/stock/pdf/export", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_stock_inventory_pdf_export_denies_without_permission() -> None:
    _create_user("stock-pdf-no", "stockpass")
    headers = _login_headers("stock-pdf-no", "stockpass")
    response = client.get("/stock/pdf/export", headers=headers)
    assert response.status_code == 403


def test_pharmacy_inventory_pdf_export_requires_permission() -> None:
    user_id = _create_user("pharmacy-pdf", "pharmpass")
    _grant_module_permission(user_id, "pharmacy", can_view=True)
    headers = _login_headers("pharmacy-pdf", "pharmpass")
    response = client.get("/pharmacy/pdf/export", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_pharmacy_inventory_pdf_export_denies_without_permission() -> None:
    _create_user("pharmacy-pdf-no", "pharmpass")
    headers = _login_headers("pharmacy-pdf-no", "pharmpass")
    response = client.get("/pharmacy/pdf/export", headers=headers)
    assert response.status_code == 403
