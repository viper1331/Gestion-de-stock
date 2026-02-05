"""Services pour le module ARI (certifications)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import math
import logging
import sqlite3

from backend.core import db, models_ari

logger = logging.getLogger(__name__)

DEFAULT_CERT_VALIDITY_DAYS = 365
DEFAULT_CERT_WARNING_DAYS = 30


def _format_date_bound(value: date, *, end: bool) -> str:
    target_time = time.max if end else time.min
    dt = datetime.combine(value, target_time, tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _with_alias(column: str, alias: str | None) -> str:
    if alias:
        return f"{alias}.{column}"
    return column


def _build_sessions_filters(
    *,
    date_from: date | None,
    date_to: date | None,
    collaborator_id: int | None,
    course: str | None,
    status: str | None,
    query: str | None,
    alias: str | None = None,
) -> tuple[str, list[object]]:
    filters: list[str] = []
    params: list[object] = []
    if collaborator_id is not None:
        filters.append(f"{_with_alias('collaborator_id', alias)} = ?")
        params.append(collaborator_id)
    if date_from is not None:
        filters.append(f"{_with_alias('performed_at', alias)} >= ?")
        params.append(_format_date_bound(date_from, end=False))
    if date_to is not None:
        filters.append(f"{_with_alias('performed_at', alias)} <= ?")
        params.append(_format_date_bound(date_to, end=True))
    if course:
        filters.append(f"{_with_alias('course_name', alias)} = ?")
        params.append(course)
    if status:
        filters.append(f"{_with_alias('status', alias)} = ?")
        params.append(status)
    if query:
        query_like = f"%{query.lower()}%"
        filters.append(
            f"(LOWER({_with_alias('course_name', alias)}) LIKE ? OR LOWER({_with_alias('status', alias)}) LIKE ?)"
        )
        params.extend([query_like, query_like])
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    return where_clause, params


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


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _compute_alert_state(
    *,
    certified_at: str | None,
    expires_at: str | None,
    warning_days: int,
) -> tuple[str, int | None]:
    if not certified_at or not expires_at:
        return "none", None
    expires_dt = _parse_timestamp(expires_at)
    if expires_dt is None:
        return "none", None
    now = datetime.now(timezone.utc)
    delta = expires_dt - now
    days_until = math.ceil(delta.total_seconds() / 86400)
    if expires_dt < now:
        return "expired", days_until
    if expires_dt <= now + timedelta(days=warning_days):
        return "expiring_soon", days_until
    return "valid", days_until


def _get_cert_settings(conn: sqlite3.Connection, site_id: str) -> tuple[int, int]:
    row = conn.execute(
        "SELECT cert_validity_days, cert_expiry_warning_days FROM ari_settings WHERE site_id = ?",
        (site_id,),
    ).fetchone()
    if not row:
        return DEFAULT_CERT_VALIDITY_DAYS, DEFAULT_CERT_WARNING_DAYS
    validity = int(row["cert_validity_days"] or DEFAULT_CERT_VALIDITY_DAYS)
    warning = int(row["cert_expiry_warning_days"] or DEFAULT_CERT_WARNING_DAYS)
    if warning >= validity:
        warning = max(0, validity - 1)
    return validity, warning


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
              cert_validity_days,
              cert_expiry_warning_days,
              created_at,
              updated_at
            )
            VALUES (?, 0, 1, 0, 1, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (site_id, DEFAULT_CERT_VALIDITY_DAYS, DEFAULT_CERT_WARNING_DAYS),
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
            cert_validity_days=DEFAULT_CERT_VALIDITY_DAYS,
            cert_expiry_warning_days=DEFAULT_CERT_WARNING_DAYS,
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
              cert_validity_days,
              cert_expiry_warning_days,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(site_id) DO UPDATE SET
              feature_enabled = excluded.feature_enabled,
              stress_required = excluded.stress_required,
              rpe_enabled = excluded.rpe_enabled,
              min_sessions_for_certification = excluded.min_sessions_for_certification,
              cert_validity_days = excluded.cert_validity_days,
              cert_expiry_warning_days = excluded.cert_expiry_warning_days,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                site_id,
                int(payload.feature_enabled),
                int(payload.stress_required),
                int(payload.rpe_enabled),
                payload.min_sessions_for_certification,
                payload.cert_validity_days,
                payload.cert_expiry_warning_days,
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
    date_from: date | None = None,
    date_to: date | None = None,
    course: str | None = None,
    status: str | None = None,
    query: str | None = None,
    sort: str | None = None,
    fallback_site: str | None = None,
) -> list[models_ari.AriSession]:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        where_clause, params = _build_sessions_filters(
            date_from=date_from,
            date_to=date_to,
            collaborator_id=collaborator_id,
            course=course,
            status=status,
            query=query,
        )
        sort_mapping = {
            "date_asc": "performed_at ASC, id ASC",
            "date_desc": "performed_at DESC, id DESC",
            "duration_asc": "duration_seconds ASC",
            "duration_desc": "duration_seconds DESC",
            "air_asc": "air_consumption_lpm ASC",
            "air_desc": "air_consumption_lpm DESC",
            "status_asc": "status ASC",
            "status_desc": "status DESC",
        }
        order_by = sort_mapping.get(sort or "date_desc", "performed_at DESC, id DESC")
        rows = conn.execute(
            f"SELECT * FROM ari_sessions {where_clause} ORDER BY {order_by}",
            params,
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
              certified_at,
              expires_at,
              certified_by_user_id,
              notes,
              reset_at,
              reset_by_user_id,
              reset_reason,
              created_at,
              updated_at
            )
            VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
        _, warning_days = _get_cert_settings(conn, site_id)
        conn.commit()
    finally:
        conn.close()
    alert_state, days_until_expiry = _compute_alert_state(
        certified_at=row.get("certified_at"),
        expires_at=row.get("expires_at"),
        warning_days=warning_days,
    )
    payload = dict(row)
    payload["alert_state"] = alert_state
    payload["days_until_expiry"] = days_until_expiry
    return models_ari.AriCertification(**payload)


def list_ari_certifications(
    site: str | None,
    *,
    query: str | None = None,
    fallback_site: str | None = None,
) -> list[models_ari.AriCertification]:
    from backend.core import services

    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        certification_rows = conn.execute("SELECT * FROM ari_certifications").fetchall()
        _, warning_days = _get_cert_settings(conn, site_id)
    finally:
        conn.close()

    certifications_by_collaborator = {
        row["collaborator_id"]: dict(row) for row in certification_rows
    }
    normalized_query = query.strip().lower() if query else ""
    collaborators = services.list_collaborators(site_id)
    results: list[models_ari.AriCertification] = []
    for collaborator in collaborators:
        if normalized_query:
            haystack = f"{collaborator.full_name} {collaborator.department or ''} {collaborator.id}".lower()
            if normalized_query not in haystack:
                continue
        row = certifications_by_collaborator.get(collaborator.id)
        if row is None:
            row = {
                "collaborator_id": collaborator.id,
                "status": "NONE",
                "comment": None,
                "decision_at": None,
                "decided_by": None,
                "certified_at": None,
                "expires_at": None,
                "certified_by_user_id": None,
                "notes": None,
                "reset_at": None,
                "reset_by_user_id": None,
                "reset_reason": None,
                "created_at": None,
                "updated_at": None,
            }
        alert_state, days_until_expiry = _compute_alert_state(
            certified_at=row.get("certified_at"),
            expires_at=row.get("expires_at"),
            warning_days=warning_days,
        )
        row["alert_state"] = alert_state
        row["days_until_expiry"] = days_until_expiry
        results.append(models_ari.AriCertification(**row))
    return results


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
        _, warning_days = _get_cert_settings(conn, site_id)
    finally:
        conn.close()
    results: list[models_ari.AriCertification] = []
    for row in rows:
        payload = dict(row)
        alert_state, days_until_expiry = _compute_alert_state(
            certified_at=payload.get("certified_at"),
            expires_at=payload.get("expires_at"),
            warning_days=warning_days,
        )
        payload["alert_state"] = alert_state
        payload["days_until_expiry"] = days_until_expiry
        results.append(models_ari.AriCertification(**payload))
    return results


def decide_certification(
    payload: models_ari.AriCertificationDecision,
    *,
    decided_by: str,
    decided_by_id: int,
    site: str | None,
    fallback_site: str | None = None,
) -> models_ari.AriCertification:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    decision_time = datetime.now(timezone.utc)
    decision_at = _format_timestamp(decision_time)
    validity_days, warning_days = _get_cert_settings(conn, site_id)
    certified_at = None
    expires_at = None
    certified_by_user_id = None
    if payload.status == "APPROVED":
        certified_at = decision_at
        expires_at = _format_timestamp(decision_time + timedelta(days=validity_days))
        certified_by_user_id = decided_by_id
    try:
        conn.execute(
            """
            INSERT INTO ari_certifications (
              collaborator_id,
              status,
              comment,
              decision_at,
              decided_by,
              certified_at,
              expires_at,
              certified_by_user_id,
              reset_at,
              reset_by_user_id,
              reset_reason,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(collaborator_id) DO UPDATE SET
              status = excluded.status,
              comment = excluded.comment,
              decision_at = excluded.decision_at,
              decided_by = excluded.decided_by,
              certified_at = excluded.certified_at,
              expires_at = excluded.expires_at,
              certified_by_user_id = excluded.certified_by_user_id,
              reset_at = NULL,
              reset_by_user_id = NULL,
              reset_reason = NULL,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                payload.collaborator_id,
                payload.status,
                payload.comment,
                decision_at,
                decided_by,
                certified_at,
                expires_at,
                certified_by_user_id,
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
    alert_state, days_until_expiry = _compute_alert_state(
        certified_at=row.get("certified_at"),
        expires_at=row.get("expires_at"),
        warning_days=warning_days,
    )
    payload_out = dict(row)
    payload_out["alert_state"] = alert_state
    payload_out["days_until_expiry"] = days_until_expiry
    return models_ari.AriCertification(**payload_out)


def reset_ari_certification(
    collaborator_id: int,
    *,
    reason: str,
    reset_by_user_id: int,
    site: str | None,
    fallback_site: str | None = None,
) -> models_ari.AriCertification:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    reset_at = _format_timestamp(datetime.now(timezone.utc))
    try:
        existing = conn.execute(
            "SELECT * FROM ari_certifications WHERE collaborator_id = ?",
            (collaborator_id,),
        ).fetchone()
        if existing is None:
            raise LookupError("Certification ARI introuvable")
        conn.execute(
            """
            UPDATE ari_certifications
            SET
              status = 'NONE',
              comment = NULL,
              decision_at = NULL,
              decided_by = NULL,
              certified_at = NULL,
              expires_at = NULL,
              certified_by_user_id = NULL,
              notes = NULL,
              reset_at = ?,
              reset_by_user_id = ?,
              reset_reason = ?,
              updated_at = CURRENT_TIMESTAMP
            WHERE collaborator_id = ?
            """,
            (reset_at, reset_by_user_id, reason.strip(), collaborator_id),
        )
        conn.execute(
            """
            INSERT INTO ari_audit_log (actor_user_id, action, entity_type, entity_id, details_json, created_at)
            VALUES (?, 'CERT_RESET', 'ari_certification', ?, NULL, CURRENT_TIMESTAMP)
            """,
            (str(reset_by_user_id), str(collaborator_id)),
        )
        row = conn.execute(
            "SELECT * FROM ari_certifications WHERE collaborator_id = ?",
            (collaborator_id,),
        ).fetchone()
        validity_days, warning_days = _get_cert_settings(conn, site_id)
        conn.commit()
    finally:
        conn.close()
    alert_state, days_until_expiry = _compute_alert_state(
        certified_at=row.get("certified_at"),
        expires_at=row.get("expires_at"),
        warning_days=warning_days,
    )
    payload_out = dict(row)
    payload_out["alert_state"] = alert_state
    payload_out["days_until_expiry"] = days_until_expiry
    return models_ari.AriCertification(**payload_out)


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
    status = certification["status"] if certification else "NONE"
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


def get_ari_stats_overview(
    site: str | None,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    fallback_site: str | None = None,
) -> dict[str, object]:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        where_clause, params = _build_sessions_filters(
            date_from=date_from,
            date_to=date_to,
            collaborator_id=None,
            course=None,
            status=None,
            query=None,
        )
        row = conn.execute(
            f"""
            SELECT
              COUNT(*) AS total_sessions,
              COUNT(DISTINCT collaborator_id) AS distinct_collaborators,
              AVG(duration_seconds) / 60.0 AS avg_duration_min,
              AVG(air_consumption_lpm) AS avg_air_lpm,
              SUM(CASE WHEN status = 'CERTIFIED' THEN 1 ELSE 0 END) AS validated_count,
              SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
              SUM(CASE WHEN status NOT IN ('CERTIFIED', 'REJECTED') THEN 1 ELSE 0 END) AS pending_count
            FROM ari_sessions
            {where_clause}
            """,
            params,
        ).fetchone()
        top_sessions = conn.execute(
            f"""
            SELECT
              id AS session_id,
              collaborator_id,
              performed_at,
              air_consumption_lpm AS air_lpm,
              duration_seconds
            FROM ari_sessions
            {where_clause}
            ORDER BY air_consumption_lpm DESC, performed_at DESC, id DESC
            LIMIT 5
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    overview = {
        "total_sessions": int(row["total_sessions"] or 0),
        "distinct_collaborators": int(row["distinct_collaborators"] or 0),
        "avg_duration_min": row["avg_duration_min"],
        "avg_air_lpm": row["avg_air_lpm"],
        "validated_count": int(row["validated_count"] or 0),
        "rejected_count": int(row["rejected_count"] or 0),
        "pending_count": int(row["pending_count"] or 0),
        "top_sessions_by_air": [
            {
                "session_id": entry["session_id"],
                "collaborator_id": entry["collaborator_id"],
                "performed_at": entry["performed_at"],
                "air_lpm": entry["air_lpm"],
                "duration_min": entry["duration_seconds"] / 60.0 if entry["duration_seconds"] else None,
            }
            for entry in top_sessions
        ],
    }
    return overview


def get_ari_stats_by_collaborator(
    site: str | None,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str | None = None,
    fallback_site: str | None = None,
) -> list[dict[str, object]]:
    site_id = _normalize_site(site, fallback_site)
    conn = _ensure_ari_db(site_id)
    try:
        where_clause, params = _build_sessions_filters(
            date_from=date_from,
            date_to=date_to,
            collaborator_id=None,
            course=None,
            status=None,
            query=None,
            alias="s",
        )
        sort_mapping = {
            "sessions_asc": "sessions_count ASC",
            "sessions_desc": "sessions_count DESC",
            "duration_asc": "avg_duration_min ASC",
            "duration_desc": "avg_duration_min DESC",
            "air_asc": "avg_air_lpm ASC",
            "air_desc": "avg_air_lpm DESC",
            "max_air_asc": "max_air_lpm ASC",
            "max_air_desc": "max_air_lpm DESC",
            "last_asc": "last_session_at ASC",
            "last_desc": "last_session_at DESC",
        }
        order_by = sort_mapping.get(sort or "sessions_desc", "sessions_count DESC")
        rows = conn.execute(
            f"""
            SELECT
              s.collaborator_id,
              COUNT(*) AS sessions_count,
              AVG(s.duration_seconds) / 60.0 AS avg_duration_min,
              AVG(s.air_consumption_lpm) AS avg_air_lpm,
              MAX(s.air_consumption_lpm) AS max_air_lpm,
              MAX(s.performed_at) AS last_session_at,
              COALESCE(c.status, 'NONE') AS certification_status
            FROM ari_sessions AS s
            LEFT JOIN ari_certifications AS c ON c.collaborator_id = s.collaborator_id
            {where_clause}
            GROUP BY s.collaborator_id
            ORDER BY {order_by}
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    def _normalize_status(value: str | None) -> str:
        if value == "APPROVED":
            return "certified"
        if value in {"REJECTED"}:
            return "mixed"
        return "pending"

    return [
        {
            "collaborator_id": row["collaborator_id"],
            "sessions_count": int(row["sessions_count"] or 0),
            "avg_duration_min": row["avg_duration_min"],
            "avg_air_lpm": row["avg_air_lpm"],
            "max_air_lpm": row["max_air_lpm"],
            "last_session_at": row["last_session_at"],
            "status": _normalize_status(row["certification_status"]),
        }
        for row in rows
    ]
