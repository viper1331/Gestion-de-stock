from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
import pyotp
import urllib.parse

from backend.app import app
from backend.core import db, security, services, two_factor_crypto

client = TestClient(app)


def _login_headers(username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": username, "password": password, "remember_me": False},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    if payload.get("status") == "totp_enroll_required":
        parsed = urllib.parse.urlparse(payload["otpauth_uri"])
        secret = urllib.parse.parse_qs(parsed.query)["secret"][0]
        code = pyotp.TOTP(secret).now()
        confirm = client.post(
            "/auth/totp/enroll/confirm",
            json={"challenge_token": payload["challenge_token"], "code": code},
        )
        assert confirm.status_code == 200, confirm.text
        token = confirm.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    if payload.get("status") == "2fa_required" and payload.get("method") == "totp":
        with db.get_users_connection() as conn:
            row = conn.execute(
                "SELECT two_factor_secret_enc FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        assert row and row["two_factor_secret_enc"], "Missing 2FA secret for user"
        secret = two_factor_crypto.decrypt_secret(str(row["two_factor_secret_enc"]))
        code = pyotp.TOTP(secret).now()
        verify = client.post(
            "/auth/totp/verify",
            json={"challenge_token": payload["challenge_id"], "code": code},
        )
        assert verify.status_code == 200, verify.text
        token = verify.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    raise AssertionError(f"Unexpected login response: {payload}")


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


def _grant_module_permission(user_id: int, module: str, *, can_view: bool, can_edit: bool) -> None:
    with db.get_users_connection() as conn:
        conn.execute(
            "DELETE FROM module_permissions WHERE user_id = ? AND module = ?",
            (user_id, module),
        )
        conn.execute(
            "INSERT INTO module_permissions (user_id, module, can_view, can_edit) VALUES (?, ?, ?, ?)",
            (user_id, module, int(can_view), int(can_edit)),
        )
        conn.commit()


def test_link_categories_seeded() -> None:
    services.ensure_database_ready()
    headers = _login_headers("admin", "admin123")

    vehicle_resp = client.get(
        "/link-categories", params={"module": "vehicle_qr"}, headers=headers
    )
    assert vehicle_resp.status_code == 200, vehicle_resp.text
    vehicle_keys = {entry["key"] for entry in vehicle_resp.json()}
    assert {"onedrive", "documentation", "tutoriel"}.issubset(vehicle_keys)

    pharmacy_resp = client.get(
        "/link-categories", params={"module": "pharmacy"}, headers=headers
    )
    assert pharmacy_resp.status_code == 200, pharmacy_resp.text
    pharmacy_keys = {entry["key"] for entry in pharmacy_resp.json()}
    assert {"documentation", "tutoriel", "supplier"}.issubset(pharmacy_keys)


def test_link_category_crud_admin_vs_user() -> None:
    services.ensure_database_ready()
    headers = _login_headers("admin", "admin123")
    key = f"fds_{uuid4().hex[:8]}"
    payload = {
        "module": "vehicle_qr",
        "key": key,
        "label": "FDS",
        "placeholder": "https://...",
        "help_text": "Fiche de sécurité",
        "is_required": True,
        "sort_order": 30,
        "is_active": True,
    }

    created = client.post("/link-categories", json=payload, headers=headers)
    assert created.status_code == 201, created.text
    created_id = created.json()["id"]

    updated = client.put(
        f"/link-categories/{created_id}",
        json={"label": "FDS mise à jour", "sort_order": 35},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["label"] == "FDS mise à jour"

    deleted = client.delete(f"/link-categories/{created_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text

    list_resp = client.get(
        "/link-categories", params={"module": "vehicle_qr"}, headers=headers
    )
    assert list_resp.status_code == 200, list_resp.text
    matches = [entry for entry in list_resp.json() if entry["id"] == created_id]
    assert matches and matches[0]["is_active"] is False

    user_id = _create_user("link_user", "password123", role="user")
    _grant_module_permission(user_id, "vehicle_qrcodes", can_view=True, can_edit=True)
    user_headers = _login_headers("link_user", "password123")
    denied = client.post("/link-categories", json=payload, headers=user_headers)
    assert denied.status_code == 403, denied.text


def test_save_and_get_item_links_validation() -> None:
    services.ensure_database_ready()
    headers = _login_headers("admin", "admin123")

    vehicle_category = client.post(
        "/vehicle-inventory/categories/",
        json={"name": f"Véhicule test {uuid4().hex[:6]}", "vehicle_type": "incendie"},
        headers=headers,
    )
    assert vehicle_category.status_code == 201, vehicle_category.text
    vehicle_category_id = vehicle_category.json()["id"]

    pharmacy_item = client.post(
        "/pharmacy/",
        json={
            "name": "Antidouleur",
            "dosage": "500mg",
            "packaging": "Boîte",
            "quantity": 10,
        },
        headers=headers,
    )
    assert pharmacy_item.status_code == 201, pharmacy_item.text
    pharmacy_item_id = pharmacy_item.json()["id"]

    vehicle_item = client.post(
        "/vehicle-inventory/",
        json={
            "name": "Extincteur",
            "sku": f"veh-{uuid4().hex[:6]}",
            "category_id": vehicle_category_id,
            "quantity": 1,
            "pharmacy_item_id": pharmacy_item_id,
        },
        headers=headers,
    )
    assert vehicle_item.status_code == 201, vehicle_item.text
    vehicle_item_id = vehicle_item.json()["id"]

    vehicle_links = client.get(
        f"/vehicle-qr/items/{vehicle_item_id}/links", headers=headers
    )
    assert vehicle_links.status_code == 200, vehicle_links.text
    assert vehicle_links.json()

    save_vehicle = client.put(
        f"/vehicle-qr/items/{vehicle_item_id}/links",
        json={
            "links": [
                {"category_key": "onedrive", "url": "https://example.com/file"},
                {"category_key": "documentation", "url": "https://example.com/doc"},
            ]
        },
        headers=headers,
    )
    assert save_vehicle.status_code == 200, save_vehicle.text
    saved = {entry["category_key"]: entry["url"] for entry in save_vehicle.json()}
    assert saved["onedrive"] == "https://example.com/file"

    unknown_key = client.put(
        f"/vehicle-qr/items/{vehicle_item_id}/links",
        json={"links": [{"category_key": "unknown", "url": "https://example.com"}]},
        headers=headers,
    )
    assert unknown_key.status_code == 400, unknown_key.text

    required_key = f"req_{uuid4().hex[:6]}"
    required_category = client.post(
        "/link-categories",
        json={
            "module": "vehicle_qr",
            "key": required_key,
            "label": "Lien requis",
            "is_required": True,
            "sort_order": 99,
            "is_active": True,
        },
        headers=headers,
    )
    assert required_category.status_code == 201, required_category.text
    required_id = required_category.json()["id"]
    try:
        missing_required = client.put(
            f"/vehicle-qr/items/{vehicle_item_id}/links",
            json={"links": []},
            headers=headers,
        )
        assert missing_required.status_code == 400, missing_required.text
    finally:
        client.put(
            f"/link-categories/{required_id}",
            json={"is_active": False},
            headers=headers,
        )

    pharmacy_links = client.put(
        f"/pharmacy/items/{pharmacy_item_id}/links",
        json={
            "links": [
                {"category_key": "documentation", "url": "https://example.com/pharma-doc"},
                {"category_key": "supplier", "url": "https://example.com/supplier"},
            ]
        },
        headers=headers,
    )
    assert pharmacy_links.status_code == 200, pharmacy_links.text
    pharmacy_saved = {entry["category_key"]: entry["url"] for entry in pharmacy_links.json()}
    assert pharmacy_saved["supplier"] == "https://example.com/supplier"
