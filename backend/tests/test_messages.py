from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend.core import db, security, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _create_user(username: str, password: str, role: str = "user") -> None:
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


def _login_headers(username: str, password: str) -> dict[str, str]:
    return login_headers(client, username, password)


@pytest.fixture(autouse=True)
def _clean_message_tables() -> None:
    services.ensure_database_ready()
    with db.get_users_connection() as conn:
        conn.execute("DELETE FROM message_recipients")
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM users WHERE username != 'admin'")
        conn.commit()
    yield


def test_user_can_send_message_to_another_user() -> None:
    _create_user("alice", "password123")
    _create_user("bob", "password123")

    sender_headers = _login_headers("alice", "password123")
    recipient_headers = _login_headers("bob", "password123")

    response = client.post(
        "/messages/send",
        headers=sender_headers,
        json={
            "category": "Info",
            "content": "Bonjour Bob",
            "recipients": ["bob"],
            "broadcast": False,
        },
    )

    assert response.status_code == 201
    message_id = response.json()["message_id"]

    inbox_bob = client.get("/messages/inbox", headers=recipient_headers)
    assert inbox_bob.status_code == 200
    bob_message_ids = {entry["id"] for entry in inbox_bob.json()}
    assert message_id in bob_message_ids

    inbox_alice = client.get("/messages/inbox", headers=sender_headers)
    assert inbox_alice.status_code == 200
    alice_message_ids = {entry["id"] for entry in inbox_alice.json()}
    assert message_id not in alice_message_ids


def test_broadcast_reaches_all_active_users() -> None:
    _create_user("alice", "password123")
    _create_user("bob", "password123")

    sender_headers = _login_headers("alice", "password123")
    response = client.post(
        "/messages/send",
        headers=sender_headers,
        json={
            "category": "Alerte",
            "content": "Message de diffusion",
            "recipients": [],
            "broadcast": True,
        },
    )

    assert response.status_code == 201
    recipients_count = response.json()["recipients_count"]
    assert recipients_count >= 2

    inbox_alice = client.get("/messages/inbox", headers=sender_headers)
    assert inbox_alice.status_code == 200
    inbox_bob = client.get("/messages/inbox", headers=_login_headers("bob", "password123"))
    assert inbox_bob.status_code == 200
    assert inbox_alice.json()
    assert inbox_bob.json()


def test_user_cannot_archive_message_for_someone_else() -> None:
    _create_user("alice", "password123")
    _create_user("bob", "password123")
    _create_user("charlie", "password123")

    sender_headers = _login_headers("alice", "password123")
    response = client.post(
        "/messages/send",
        headers=sender_headers,
        json={
            "category": "Info",
            "content": "Message privé",
            "recipients": ["bob"],
            "broadcast": False,
        },
    )
    message_id = response.json()["message_id"]

    archive_response = client.post(
        f"/messages/{message_id}/archive",
        headers=_login_headers("charlie", "password123"),
    )
    assert archive_response.status_code == 403

    read_response = client.post(
        f"/messages/{message_id}/read",
        headers=_login_headers("bob", "password123"),
    )
    assert read_response.status_code == 200


def test_message_is_archived_to_disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive_root = tmp_path / "message_archive"
    monkeypatch.setattr(services, "MESSAGE_ARCHIVE_ROOT", archive_root)

    _create_user("alice", "password123")
    _create_user("bob", "password123")

    sender_headers = _login_headers("alice", "password123")
    response = client.post(
        "/messages/send",
        headers=sender_headers,
        json={
            "category": "Maintenance",
            "content": "Test archive",
            "recipients": ["bob"],
            "broadcast": False,
        },
    )
    assert response.status_code == 201
    message_id = response.json()["message_id"]

    month_folder = datetime.now(timezone.utc).strftime("%Y-%m")
    archive_path = archive_root / month_folder / "messages.jsonl"
    assert archive_path.exists()
    lines = archive_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert payload["id"] == message_id
    assert payload["content"] == "Test archive"
