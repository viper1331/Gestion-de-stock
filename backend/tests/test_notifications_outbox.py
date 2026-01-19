from __future__ import annotations

from backend.core import db, models, services
from backend.services import notifications


def test_on_user_approved_enqueues_email() -> None:
    services.ensure_database_ready()
    with db.get_core_connection() as conn:
        conn.execute("DELETE FROM email_outbox")
        conn.commit()
    user = models.User(
        id=1,
        username="user-demo",
        role="user",
        site_key="default",
        email="user-demo@example.com",
        is_active=True,
        status="active",
        session_version=1,
        display_name="User Demo",
    )
    notifications.on_user_approved(user, modules=["inventory", "reports"])
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT subject, body_text FROM email_outbox WHERE to_email = ?",
            ("user-demo@example.com",),
        ).fetchone()
    assert row is not None
    assert "Compte validé" in row["subject"]
    assert "modules accessibles" in row["body_text"].lower()
