from datetime import datetime, timezone

import pytest

from backend.core import db, models, services


def _reset_ari_tables() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute("DELETE FROM ari_measurements")
        conn.execute("DELETE FROM ari_sessions")
        conn.commit()


def test_create_ari_session_manual_persists_snapshot() -> None:
    _reset_ari_tables()
    payload = models.AriSessionCreate(
        performed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        physio=models.AriPhysioInput(
            source="manual",
            pre=models.AriPhysioPoint(bp_sys=130, bp_dia=80, hr=90, spo2=98),
            post=models.AriPhysioPoint(bp_sys=140, bp_dia=90, hr=110, spo2=95),
        ),
    )

    session = services.create_ari_session(payload, created_by="tester")

    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT * FROM ari_sessions WHERE id = ?",
            (session.id,),
        ).fetchone()
        assert row is not None
        assert row["bp_sys_pre"] == 130
        assert row["bp_dia_pre"] == 80
        assert row["hr_pre"] == 90
        assert row["spo2_pre"] == 98
        assert row["bp_sys_post"] == 140
        assert row["bp_dia_post"] == 90
        assert row["hr_post"] == 110
        assert row["spo2_post"] == 95
        measurements = conn.execute(
            "SELECT COUNT(*) AS total FROM ari_measurements WHERE session_id = ?",
            (session.id,),
        ).fetchone()
        assert measurements["total"] == 8


def test_create_ari_session_sensor_payload() -> None:
    _reset_ari_tables()
    payload = models.AriSessionCreate(
        performed_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        physio=models.AriPhysioInput(
            source="sensor",
            device_id="device-123",
            payload_json={"raw": "payload"},
            pre=models.AriPhysioPoint(bp_sys=120, bp_dia=70, hr=80, spo2=99),
        ),
    )

    session = services.create_ari_session(payload, created_by="sensor-user")

    with db.get_stock_connection() as conn:
        row = conn.execute(
            "SELECT payload_json FROM ari_measurements WHERE session_id = ? LIMIT 1",
            (session.id,),
        ).fetchone()
        assert row is not None
        assert "payload" in row["payload_json"]


def test_validate_bp_sys_greater_than_bp_dia() -> None:
    with pytest.raises(ValueError):
        models.AriPhysioPoint(bp_sys=80, bp_dia=90)


def test_ari_stats_averages() -> None:
    _reset_ari_tables()
    services.create_ari_session(
        models.AriSessionCreate(
            performed_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
            physio=models.AriPhysioInput(
                source="manual",
                pre=models.AriPhysioPoint(hr=80, spo2=97, bp_sys=120, bp_dia=70),
                post=models.AriPhysioPoint(hr=90, spo2=95, bp_sys=130, bp_dia=80),
            ),
        ),
        created_by="tester",
    )
    services.create_ari_session(
        models.AriSessionCreate(
            performed_at=datetime(2024, 3, 2, tzinfo=timezone.utc),
            physio=models.AriPhysioInput(
                source="manual",
                pre=models.AriPhysioPoint(hr=100, spo2=99, bp_sys=140, bp_dia=85),
                post=models.AriPhysioPoint(hr=110, spo2=96, bp_sys=150, bp_dia=90),
            ),
        ),
        created_by="tester",
    )

    stats = services.get_ari_stats()

    assert stats.avg_hr_pre == 90
    assert stats.avg_hr_post == 100
    assert stats.avg_spo2_pre == 98
    assert stats.avg_spo2_post == 95.5
    assert stats.avg_bp_sys_pre == 130
    assert stats.avg_bp_dia_pre == 77.5
    assert stats.delta_hr_avg == 10
