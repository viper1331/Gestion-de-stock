from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.core import models, services
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    services.ensure_database_ready()
    return login_headers(client, "admin", "admin123")


def _create_user(username: str, role: str) -> None:
    services.create_user(
        models.UserCreate(
            username=username,
            password="Password123!",
            role=role,
            site_key="JLL",
        )
    )


def _create_collaborator() -> models.Collaborator:
    return services.create_collaborator(
        models.CollaboratorCreate(full_name="ARI Perms", department=None, email=None, phone=None)
    )


def test_ari_permission_denied_for_standard_user() -> None:
    services.ensure_database_ready()
    _create_user("user-ari@example.com", "user")
    headers = login_headers(client, "user-ari@example.com", "Password123!")
    response = client.get("/ari/settings", headers=headers)
    assert response.status_code == 403, response.text


def test_ari_certificateur_permissions() -> None:
    services.ensure_database_ready()
    _create_user("cert-ari@example.com", "certificateur")
    collaborator = _create_collaborator()
    admin_headers = _admin_headers()
    client.post(
        "/ari/sessions",
        json={
            "collaborator_id": collaborator.id,
            "performed_at": "2024-01-05T08:30:00+00:00",
            "course_name": "Parcours test",
            "duration_seconds": 600,
            "start_pressure_bar": 300,
            "end_pressure_bar": 200,
            "stress_level": 4,
        },
        headers=admin_headers,
    )

    cert_headers = login_headers(client, "cert-ari@example.com", "Password123!")
    response = client.get("/ari/settings", headers=cert_headers)
    assert response.status_code == 400, response.text

    cert_headers_with_site = {**cert_headers, "X-ARI-SITE": "JLL"}
    response = client.get("/ari/settings", headers=cert_headers_with_site)
    assert response.status_code == 200, response.text

    response = client.post(
        "/ari/certifications/decide",
        json={"collaborator_id": collaborator.id, "status": "APPROVED"},
        headers=cert_headers_with_site,
    )
    assert response.status_code == 200, response.text

    response = client.put(
        "/ari/settings",
        json={
            "feature_enabled": True,
            "stress_required": True,
            "rpe_enabled": False,
            "min_sessions_for_certification": 2,
        },
        headers=cert_headers_with_site,
    )
    assert response.status_code == 403, response.text
