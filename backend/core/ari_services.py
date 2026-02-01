"""Services pour le module ARI (certifications)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import logging
import sqlite3

from backend.core import db, models_ari

logger = logging.getLogger(__name__)


def _normalize_site(site: str | None, fallback: str | None) -> str:
    if site and site.strip():
        return site.strip().upper()
    if fallback:
        return fallback.strip().upper()
    return db.DEFAULT_SITE_KEY


def _format_timestamp(value: datetime | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ensure_settings(conn: sqlite3.Connection, site_id: str) -> None:
    existing = conn.execute(
        "SELECT 1 FROM ari_settings WHERE site_id = ?",
        (site_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO ari_settings (
              site_id,
              feature_enabled,
              stress_required,
              rpe_enabled,
              min_sessions_for_certification,
              created_at,
              updated_at
            )
            VALUES (?, 0, 1, 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (site_id,),
        )
        conn.commit()


def _ensure_ari_db(site_id: str) -> db.sqlite3.Connection:
    conn = db.get_ari_connection(site_id)
    db.init_ari_schema(conn)
    _ensure_settings(conn, site_id)
    return conn


def get_ari_settings(site: str | None, fallback_site: str | None = None) -> models_ari.AriSettings:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        row = conn.execute(
            "SELECT * FROM ari_settings WHERE site_id = ?",
            (site_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return models_ari.AriSettings(
            feature_enabled=False,
            stress_required=True,
            rpe_enabled=False,
            min_sessions_for_certification=1,
        )
    return models_ari.AriSettings(**row)


def update_ari_settings(
    payload: models_ari.AriSettingsUpdate,
    site: str | None,
    fallback_site: str | None = None,
) -> models_ari.AriSettings:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        conn.execute(
            """
            INSERT INTO ari_settings (
              site_id,
              feature_enabled,
              stress_required,
              rpe_enabled,
              min_sessions_for_certification,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(site_id) DO UPDATE SET
              feature_enabled = excluded.feature_enabled,
              stress_required = excluded.stress_required,
              rpe_enabled = excluded.rpe_enabled,
              min_sessions_for_certification = excluded.min_sessions_for_certification,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                site_id,
                int(payload.feature_enabled),
                int(payload.stress_required),
                int(payload.rpe_enabled),
                payload.min_sessions_for_certification,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ari_settings WHERE site_id = ?",
            (site_id,),
        ).fetchone()
    finally:
        conn.close()
    return models_ari.AriSettings(**row)


def _session_from_row(row: dict[str, object]) -> models_ari.AriSession:
    return models_ari.AriSession(**row)


def _compute_ari_air_metrics(payload: models_ari.AriSessionInput) -> dict[str, float]:
    if payload.cylinder_capacity_l <= 0:
        raise ValueError("Capacité bouteille invalide")
    if payload.start_pressure_bar <= 0:
        raise ValueError("Pression de départ invalide")
    if payload.end_pressure_bar < 0:
        raise ValueError("Pression de fin invalide")
    if payload.end_pressure_bar >= payload.start_pressure_bar:
        raise ValueError("La pression de fin doit être inférieure à la pression de départ")
    if payload.duration_seconds <= 0:
        raise ValueError("Durée invalide")
    delta_bar = payload.start_pressure_bar - payload.end_pressure_bar
    if delta_bar <= 0:
        raise ValueError("Delta pression invalide")

    air_consumed_l = payload.cylinder_capacity_l * delta_bar
    duration_min = payload.duration_seconds / 60.0
    air_consumption_lpm = air_consumed_l / duration_min if duration_min > 0 else 0.0
    autonomy_start_min = (
        (payload.cylinder_capacity_l * payload.start_pressure_bar) / air_consumption_lpm
        if air_consumption_lpm > 0
        else 0.0
    )
    autonomy_end_min = (
        (payload.cylinder_capacity_l * payload.end_pressure_bar) / air_consumption_lpm
        if air_consumption_lpm > 0
        else 0.0
    )
    return {
        "air_consumed_bar": int(delta_bar),
        "air_consumed_l": float(air_consumed_l),
        "air_consumption_lpm": float(air_consumption_lpm),
        "autonomy_start_min": float(autonomy_start_min),
        "autonomy_end_min": float(autonomy_end_min),
    }


def list_ari_sessions(
    site: str | None,
    *,
    collaborator_id: int | None = None,
    fallback_site: str | None = None,
) -> list[models_ari.AriSession]:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        if collaborator_id is None:
            rows = conn.execute(
                "SELECT * FROM ari_sessions ORDER BY performed_at DESC, id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM ari_sessions
                WHERE collaborator_id = ?
                ORDER BY performed_at DESC, id DESC
                """,
                (collaborator_id,),
            ).fetchall()
    finally:
        conn.close()
    return [_session_from_row(row) for row in rows]


def get_ari_session(
    session_id: int,
    site: str | None,
    *,
    fallback_site: str | None = None,
) -> models_ari.AriSession:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        row = conn.execute(
            "SELECT * FROM ari_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("Session ARI introuvable")
    return _session_from_row(row)


def _ensure_certification_row(
    conn: sqlite3.Connection,
    collaborator_id: int,
    *,
    status: str = "PENDING",
) -> None:
    existing = conn.execute(
        "SELECT 1 FROM ari_certifications WHERE collaborator_id = ?",
        (collaborator_id,),
    ).fetchone()
    if existing is None:
        conn.execute(
            """
            INSERT INTO ari_certifications (
              collaborator_id,
              status,
              comment,
              decision_at,
              decided_by,
              created_at,
              updated_at
            )
            VALUES (?, ?, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (collaborator_id, status),
        )


def create_ari_session(
    payload: models_ari.AriSessionCreate,
    *,
    created_by: str,
    site: str | None,
    fallback_site: str | None = None,
) -> models_ari.AriSession:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    performed_at = _format_timestamp(payload.performed_at)
    course_name = payload.course_name.strip() if payload.course_name else "Séance ARI"
    metrics = _compute_ari_air_metrics(payload)
    try:
        cur = conn.execute(
            """
            INSERT INTO ari_sessions (
              collaborator_id,
              performed_at,
              course_name,
              duration_seconds,
              start_pressure_bar,
              end_pressure_bar,
              air_consumed_bar,
              cylinder_capacity_l,
              air_consumed_l,
              air_consumption_lpm,
              autonomy_start_min,
              autonomy_end_min,
              stress_level,
              status,
              rpe,
              physio_notes,
              observations,
              bp_sys_pre,
              bp_dia_pre,
              hr_pre,
              spo2_pre,
              bp_sys_post,
              bp_dia_post,
              hr_post,
              spo2_post,
              created_at,
              created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (
                payload.collaborator_id,
                performed_at,
                course_name,
                payload.duration_seconds,
                payload.start_pressure_bar,
                payload.end_pressure_bar,
                metrics["air_consumed_bar"],
                payload.cylinder_capacity_l,
                metrics["air_consumed_l"],
                metrics["air_consumption_lpm"],
                metrics["autonomy_start_min"],
                metrics["autonomy_end_min"],
                payload.stress_level,
                "COMPLETED",
                payload.rpe,
                payload.physio_notes,
                payload.observations,
                payload.bp_sys_pre,
                payload.bp_dia_pre,
                payload.hr_pre,
                payload.spo2_pre,
                payload.bp_sys_post,
                payload.bp_dia_post,
                payload.hr_post,
                payload.spo2_post,
                created_by,
            ),
        )
        _ensure_certification_row(conn, payload.collaborator_id)
        conn.commit()
        session_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT * FROM ari_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    return _session_from_row(row)


def update_ari_session(
    session_id: int,
    payload: models_ari.AriSessionUpdate,
    *,
    site: str | None,
    fallback_site: str | None = None,
) -> models_ari.AriSession:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    performed_at = _format_timestamp(payload.performed_at)
    course_name = payload.course_name.strip() if payload.course_name else "Séance ARI"
    metrics = _compute_ari_air_metrics(payload)
    try:
        existing = conn.execute(
            "SELECT 1 FROM ari_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if existing is None:
            raise LookupError("Session ARI introuvable")
        conn.execute(
            """
            UPDATE ari_sessions
            SET
              collaborator_id = ?,
              performed_at = ?,
              course_name = ?,
              duration_seconds = ?,
              start_pressure_bar = ?,
              end_pressure_bar = ?,
              air_consumed_bar = ?,
              cylinder_capacity_l = ?,
              air_consumed_l = ?,
              air_consumption_lpm = ?,
              autonomy_start_min = ?,
              autonomy_end_min = ?,
              stress_level = ?,
              rpe = ?,
              physio_notes = ?,
              observations = ?,
              bp_sys_pre = ?,
              bp_dia_pre = ?,
              hr_pre = ?,
              spo2_pre = ?,
              bp_sys_post = ?,
              bp_dia_post = ?,
              hr_post = ?,
              spo2_post = ?
            WHERE id = ?
            """,
            (
                payload.collaborator_id,
                performed_at,
                course_name,
                payload.duration_seconds,
                payload.start_pressure_bar,
                payload.end_pressure_bar,
                metrics["air_consumed_bar"],
                payload.cylinder_capacity_l,
                metrics["air_consumed_l"],
                metrics["air_consumption_lpm"],
                metrics["autonomy_start_min"],
                metrics["autonomy_end_min"],
                payload.stress_level,
                payload.rpe,
                payload.physio_notes,
                payload.observations,
                payload.bp_sys_pre,
                payload.bp_dia_pre,
                payload.hr_pre,
                payload.spo2_pre,
                payload.bp_sys_post,
                payload.bp_dia_post,
                payload.hr_post,
                payload.spo2_post,
                session_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM ari_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError("Session ARI introuvable")
    return _session_from_row(row)


def get_ari_certification(
    collaborator_id: int,
    site: str | None,
    *,
    fallback_site: str | None = None,
) -> models_ari.AriCertification:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        _ensure_certification_row(conn, collaborator_id)
        row = conn.execute(
            "SELECT * FROM ari_certifications WHERE collaborator_id = ?",
            (collaborator_id,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    return models_ari.AriCertification(**row)


def list_pending_certifications(
    site: str | None,
    *,
    fallback_site: str | None = None,
) -> list[models_ari.AriCertification]:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        rows = conn.execute(
            "SELECT * FROM ari_certifications WHERE status = 'PENDING' ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [models_ari.AriCertification(**row) for row in rows]


def decide_certification(
    payload: models_ari.AriCertificationDecision,
    *,
    decided_by: str,
    site: str | None,
    fallback_site: str | None = None,
) -> models_ari.AriCertification:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    decision_at = _format_timestamp(datetime.now(timezone.utc))
    try:
        conn.execute(
            """
            INSERT INTO ari_certifications (
              collaborator_id,
              status,
              comment,
              decision_at,
              decided_by,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(collaborator_id) DO UPDATE SET
              status = excluded.status,
              comment = excluded.comment,
              decision_at = excluded.decision_at,
              decided_by = excluded.decided_by,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                payload.collaborator_id,
                payload.status,
                payload.comment,
                decision_at,
                decided_by,
            ),
        )
        session_status = None
        if payload.status == "APPROVED":
            session_status = "CERTIFIED"
        elif payload.status == "REJECTED":
            session_status = "REJECTED"
        if session_status:
            conn.execute(
                "UPDATE ari_sessions SET status = ? WHERE collaborator_id = ?",
                (session_status, payload.collaborator_id),
            )
        row = conn.execute(
            "SELECT * FROM ari_certifications WHERE collaborator_id = ?",
            (payload.collaborator_id,),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()
    return models_ari.AriCertification(**row)


def purge_ari_sessions(
    *,
    site_scope: str,
    older_than_days: int | None,
    before_date: date | None,
    include_certified: bool,
    dry_run: bool,
    site: str | None,
    fallback_site: str | None = None,
) -> tuple[dict[str, int], int]:
    site_scope_normalized = (site_scope or "CURRENT").upper()
    if site_scope_normalized not in {"CURRENT", "ALL"}:
        raise ValueError("Site invalide")
    if site_scope_normalized == "ALL":
        site_ids = list(db.SITE_KEYS)
    else:
        site_ids = [_normalize_site(site, fallback_site)]

    filters: list[str] = []
    params: list[object] = []
    if older_than_days:
        threshold = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        filters.append("performed_at <= ?")
        params.append(_format_timestamp(threshold))
    if before_date:
        threshold = datetime.combine(before_date, time.max, tzinfo=timezone.utc)
        filters.append("performed_at <= ?")
        params.append(_format_timestamp(threshold))
    if not include_certified:
        filters.append("(status IS NULL OR status NOT IN ('CERTIFIED', 'REJECTED'))")

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    results: dict[str, int] = {}

    for site_id in site_ids:
        conn = _ensure_ari_db(site_id)
        try:
            if dry_run:
                row = conn.execute(
                    f"SELECT COUNT(*) AS total FROM ari_sessions {where_clause}",
                    params,
                ).fetchone()
                count = int(row["total"] if row and row["total"] is not None else 0)
            else:
                try:
                    if not conn.in_transaction:
                        conn.execute("BEGIN")
                    cur = conn.execute(
                        f"DELETE FROM ari_sessions {where_clause}",
                        params,
                    )
                    count = int(cur.rowcount or 0)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            results[site_id] = count
        finally:
            conn.close()

    total = sum(results.values())
    logger.info(
        "[ARI] purge sessions dry_run=%s scope=%s total=%s include_certified=%s filters=%s",
        dry_run,
        site_scope_normalized,
        total,
        include_certified,
        {
            "older_than_days": older_than_days,
            "before_date": before_date.isoformat() if before_date else None,
        },
    )
    return results, total


def get_ari_collaborator_stats(
    collaborator_id: int,
    site: str | None,
    *,
    fallback_site: str | None = None,
) -> models_ari.AriCollaboratorStats:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS sessions_count,
              AVG(duration_seconds) AS avg_duration_seconds,
              AVG(air_consumed_bar) AS avg_air_consumed_bar,
              AVG((air_consumed_bar * 60.0) / NULLIF(duration_seconds, 0)) AS avg_air_per_min,
              AVG(stress_level) AS avg_stress_level,
              MAX(performed_at) AS last_session_at
            FROM ari_sessions
            WHERE collaborator_id = ?
            """,
            (collaborator_id,),
        ).fetchone()
        certification = conn.execute(
            "SELECT status, decision_at FROM ari_certifications WHERE collaborator_id = ?",
            (collaborator_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        row = {
            "sessions_count": 0,
            "avg_duration_seconds": None,
            "avg_air_consumed_bar": None,
            "avg_air_per_min": None,
            "avg_stress_level": None,
            "last_session_at": None,
        }
    status = certification["status"] if certification else "PENDING"
    decision_at = certification["decision_at"] if certification else None
    return models_ari.AriCollaboratorStats(
        sessions_count=row["sessions_count"] or 0,
        avg_duration_seconds=row["avg_duration_seconds"],
        avg_air_consumed_bar=row["avg_air_consumed_bar"],
        avg_air_per_min=row["avg_air_per_min"],
        avg_stress_level=row["avg_stress_level"],
        last_session_at=row["last_session_at"],
        certification_status=status,
        certification_decision_at=decision_at,
    )
