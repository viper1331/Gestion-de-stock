from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _create_vehicle(headers: dict[str, str]) -> int:
    payload = {
        "name": f"Véhicule photo {uuid4().hex[:6]}",
        "vehicle_type": "incendie",
        "sizes": ["Cabine", "Coffre"],
    }
    response = client.post("/vehicle-inventory/categories/", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def test_vehicle_general_inventory_photo_crud() -> None:
    services.ensure_database_ready()
    admin_headers = login_headers(client, "admin", "admin123")
    vehicle_id = _create_vehicle(admin_headers)

    initial = client.get(
        f"/vehicles/{vehicle_id}/general-inventory/photo?side=left", headers=admin_headers
    )
    assert initial.status_code == 200, initial.text
    assert initial.json()["photo_url"] is None
    assert initial.json()["side"] == "left"

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDATx\xda"
        b"c\xfc\xff\x9f\xa1\x1e\x00\x07\x82\x02\x7f=\x07\xd0\xdd\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    uploaded = client.post(
        f"/vehicles/{vehicle_id}/general-inventory/photo?side=left",
        files={"file": ("photo.png", BytesIO(png), "image/png")},
        headers=admin_headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    upload_payload = uploaded.json()
    assert upload_payload["vehicle_id"] == vehicle_id
    assert upload_payload["side"] == "left"
    assert upload_payload["photo_url"].startswith("/media/")

    fetched = client.get(
        f"/vehicles/{vehicle_id}/general-inventory/photo?side=left", headers=admin_headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["photo_url"] == upload_payload["photo_url"]

    right_upload = client.post(
        f"/vehicles/{vehicle_id}/general-inventory/photo?side=right",
        files={"file": ("photo-right.png", BytesIO(png), "image/png")},
        headers=admin_headers,
    )
    assert right_upload.status_code == 200, right_upload.text
    assert right_upload.json()["side"] == "right"
    assert right_upload.json()["photo_url"].startswith("/media/")

    deleted = client.delete(
        f"/vehicles/{vehicle_id}/general-inventory/photo?side=left", headers=admin_headers
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["side"] == "left"
    assert deleted.json()["photo_url"] is None

    right_still_there = client.get(
        f"/vehicles/{vehicle_id}/general-inventory/photo?side=right", headers=admin_headers
    )
    assert right_still_there.status_code == 200, right_still_there.text
    assert right_still_there.json()["photo_url"] == right_upload.json()["photo_url"]
