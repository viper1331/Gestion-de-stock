import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from backend.app import app

client = TestClient(app)


def _login_headers() -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123", "remember_me": False},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_user_layout_save_and_load() -> None:
    headers = _login_headers()
    payload = {
        "version": 1,
        "page_key": "module:clothing:inventory",
        "layouts": {
            "lg": [{"i": "inventory-main", "x": -2, "y": -1, "w": 20, "h": 2}],
            "md": [],
            "sm": [],
            "xs": [],
        },
        "hidden_blocks": ["inventory-orders"],
    }
    response = client.put("/user-layouts/module:clothing:inventory", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["page_key"] == "module:clothing:inventory"
    assert data["hidden_blocks"] == ["inventory-orders"]
    assert data["layouts"]["lg"][0]["x"] == 0
    assert data["layouts"]["lg"][0]["y"] == 0
    assert data["layouts"]["lg"][0]["w"] == 12

    get_response = client.get("/user-layouts/module:clothing:inventory", headers=headers)
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["hidden_blocks"] == ["inventory-orders"]


def test_user_layout_rejects_unknown_blocks() -> None:
    headers = _login_headers()
    payload = {
        "version": 1,
        "page_key": "module:clothing:inventory",
        "layouts": {
            "lg": [{"i": "unknown-block", "x": 0, "y": 0, "w": 6, "h": 4}],
            "md": [],
            "sm": [],
            "xs": [],
        },
        "hidden_blocks": [],
    }
    response = client.put("/user-layouts/module:clothing:inventory", json=payload, headers=headers)
    assert response.status_code == 400, response.text
