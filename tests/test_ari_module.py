from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import models, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    services.ensure_database_ready()
    return login_headers(client, "admin", "admin123")


def _create_collaborator() -> models.Collaborator:
    return services.create_collaborator(
        models.CollaboratorCreate(
            full_name="Collab ARI",
            department="Ops",
            email=None,
            phone=None,
        )
    )


def test_ari_session_flow() -> None:
    headers = _admin_headers()
    collaborator = _create_collaborator()
    payload = {
        "collaborator_id": collaborator.id,
        "performed_at": datetime(2024, 1, 5, 8, 30, tzinfo=timezone.utc).isoformat(),
        "course_name": "Parcours test",
        "duration_seconds": 600,
        "start_pressure_bar": 300,
        "end_pressure_bar": 200,
        "stress_level": 4,
        "rpe": 5,
        "physio_notes": "RAS",
        "observations": "OK",
    }
    response = client.post("/ari/sessions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["air_consumed_bar"] == 100

    list_response = client.get(
        f"/ari/sessions?collaborator_id={collaborator.id}",
        headers=headers,
    )
    assert list_response.status_code == 200, list_response.text
    sessions = list_response.json()
    assert any(entry["id"] == session["id"] for entry in sessions)

    stats_response = client.get(
        f"/ari/stats/collaborator/{collaborator.id}",
        headers=headers,
    )
    assert stats_response.status_code == 200, stats_response.text
    stats = stats_response.json()
    assert stats["sessions_count"] == 1
    assert stats["avg_air_per_min"] == 10

    cert_response = client.get(
        f"/ari/certifications?collaborator_id={collaborator.id}",
        headers=headers,
    )
    assert cert_response.status_code == 200, cert_response.text
    assert cert_response.json()["status"] == "PENDING"

    decision_response = client.post(
        "/ari/certifications/decide",
        json={"collaborator_id": collaborator.id, "status": "APPROVED"},
        headers=headers,
    )
    assert decision_response.status_code == 200, decision_response.text
    assert decision_response.json()["status"] == "APPROVED"

    reject_response = client.post(
        "/ari/certifications/decide",
        json={"collaborator_id": collaborator.id, "status": "REJECTED"},
        headers=headers,
    )
    assert reject_response.status_code == 422, reject_response.text
