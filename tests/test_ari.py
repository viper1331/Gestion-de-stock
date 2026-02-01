from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.core import db, models, services
from backend.services import system_settings
from backend.tests.auth_helpers import login_headers

client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    services.ensure_database_ready()
    return login_headers(client, "admin", "admin123")


TEST_SITE = "ST_ELOIS"


def _create_collaborator() -> models.Collaborator:
    return services.create_collaborator(
        models.CollaboratorCreate(full_name="ARI Metrics", department="Ops", email=None, phone=None)
    )


def _with_feature_flag(enabled: bool):
    previous = system_settings.get_feature_ari_enabled()
    system_settings.set_feature_ari_enabled(enabled, "admin")
    return previous


def test_ari_session_consumption_calculation() -> None:
    services.ensure_database_ready()
    previous = _with_feature_flag(True)
    try:
        headers = {**_admin_headers(), "X-ARI-SITE": TEST_SITE}
        collaborator = _create_collaborator()
        payload = {
            "collaborator_id": collaborator.id,
            "performed_at": datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat(),
            "course_name": "Parcours test",
            "duration_seconds": 600,
            "start_pressure_bar": 300,
            "end_pressure_bar": 150,
            "cylinder_capacity_l": 6.8,
            "stress_level": 5,
        }
        response = client.post("/ari/sessions", json=payload, headers=headers)
        assert response.status_code == 201, response.text
        session = response.json()
        air_consumed_l = 6.8 * (300 - 150)
        lpm = air_consumed_l / 10
        assert session["air_consumed_l"] == pytest.approx(air_consumed_l)
        assert session["air_consumption_lpm"] == pytest.approx(lpm)
        assert session["autonomy_start_min"] == pytest.approx((6.8 * 300) / lpm)
        assert session["autonomy_end_min"] == pytest.approx((6.8 * 150) / lpm)
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


@pytest.mark.parametrize(
    "start_pressure,end_pressure",
    [(200, 200), (150, 200)],
)
def test_ari_session_rejects_invalid_pressures(
    start_pressure: int, end_pressure: int
) -> None:
    services.ensure_database_ready()
    previous = _with_feature_flag(True)
    try:
        headers = {**_admin_headers(), "X-ARI-SITE": TEST_SITE}
        collaborator = _create_collaborator()
        payload = {
            "collaborator_id": collaborator.id,
            "performed_at": datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat(),
            "course_name": "Parcours test",
            "duration_seconds": 600,
            "start_pressure_bar": start_pressure,
            "end_pressure_bar": end_pressure,
            "cylinder_capacity_l": 6.8,
            "stress_level": 5,
        }
        response = client.post("/ari/sessions", json=payload, headers=headers)
        assert response.status_code == 400, response.text
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_session_rejects_zero_duration() -> None:
    services.ensure_database_ready()
    previous = _with_feature_flag(True)
    try:
        headers = {**_admin_headers(), "X-ARI-SITE": TEST_SITE}
        collaborator = _create_collaborator()
        payload = {
            "collaborator_id": collaborator.id,
            "performed_at": datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc).isoformat(),
            "course_name": "Parcours test",
            "duration_seconds": 0,
            "start_pressure_bar": 300,
            "end_pressure_bar": 150,
            "cylinder_capacity_l": 6.8,
            "stress_level": 5,
        }
        response = client.post("/ari/sessions", json=payload, headers=headers)
        assert response.status_code == 400, response.text
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_existing_sessions_do_not_crash_list() -> None:
    services.ensure_database_ready()
    previous = _with_feature_flag(True)
    try:
        legacy_site = "CENTRAL_ENTITY"
        headers = {**_admin_headers(), "X-ARI-SITE": legacy_site}
        conn = db.get_ari_connection(legacy_site)
        try:
            conn.execute(
                """
                INSERT INTO ari_sessions (
                  collaborator_id,
                  performed_at,
                  course_name,
                  duration_seconds,
                  start_pressure_bar,
                  end_pressure_bar,
                  air_consumed_bar,
                  stress_level,
                  status,
                  created_at,
                  created_by
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    99,
                    datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "Legacy",
                    600,
                    300,
                    200,
                    100,
                    5,
                    "COMPLETED",
                    datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "tester",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        response = client.get("/ari/sessions", headers=headers)
        assert response.status_code == 200, response.text
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")


def test_ari_purge_deletes_sessions_with_air_fields() -> None:
    services.ensure_database_ready()
    previous = _with_feature_flag(True)
    try:
        headers = {**_admin_headers(), "X-ARI-SITE": TEST_SITE}
        collaborator = _create_collaborator()
        payload = {
            "collaborator_id": collaborator.id,
            "performed_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
            "course_name": "Parcours purge",
            "duration_seconds": 600,
            "start_pressure_bar": 300,
            "end_pressure_bar": 150,
            "cylinder_capacity_l": 6.8,
            "stress_level": 5,
        }
        response = client.post("/ari/sessions", json=payload, headers=headers)
        assert response.status_code == 201, response.text

        purge_response = client.post(
            "/ari/admin/purge-sessions",
            json={"older_than_days": 1, "dry_run": False},
            headers=headers,
        )
        assert purge_response.status_code == 200, purge_response.text
        assert purge_response.json()["total"] >= 1
    finally:
        system_settings.set_feature_ari_enabled(previous, "admin")
