from datetime import datetime
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.auth import get_current_user
from backend.core import db, models, services
from backend.core.system_config import get_config, save_config
from backend.core.logging_config import (
    LOG_BACKUP_COUNT,
    LOG_DIR,
    LOG_MAX_BYTES,
    list_log_files,
    purge_rotated_logs,
)
from backend.services.debug_service import load_debug_config, save_debug_config
from backend.services.backup_scheduler import backup_scheduler
from backend.services import notifications
from backend.services.backup_settings import MAX_BACKUP_INTERVAL_MINUTES
from backend.services import system_settings

router = APIRouter()
logger = logging.getLogger(__name__)


class LogFileEntry(BaseModel):
    name: str
    size: int
    mtime: datetime


class LogStatusResponse(BaseModel):
    log_dir: str
    max_bytes: int
    backup_count: int
    total_size: int
    files: list[LogFileEntry]


class SmtpSettingsResponse(BaseModel):
    host: str | None
    port: int
    username: str | None
    from_email: str
    use_tls: bool
    use_ssl: bool
    timeout_seconds: int
    dev_sink: bool
    smtp_password_set: bool


class SmtpSettingsUpdate(BaseModel):
    host: str | None = None
    port: int
    username: str | None = None
    from_email: str
    use_tls: bool
    use_ssl: bool
    timeout_seconds: int
    dev_sink: bool
    password: str | None = None
    clear_password: bool | None = None


class SmtpTestRequest(BaseModel):
    to_email: str


class EmailTestRequest(BaseModel):
    to_email: str
    subject: str
    body: str


class OtpEmailSettingsPayload(BaseModel):
    ttl_minutes: int
    code_length: int
    max_attempts: int
    resend_cooldown_seconds: int
    rate_limit_per_hour: int
    allow_insecure_dev: bool


class PurchaseSuggestionSettingsPayload(BaseModel):
    expiry_soon_days: int


class ReportPurgeRequest(BaseModel):
    module_key: str


class ReportPurgeResponse(BaseModel):
    ok: bool
    module_key: str
    deleted: dict[str, int]


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return user


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _validate_smtp_payload(payload: SmtpSettingsUpdate) -> None:
    host = _normalize_optional_text(payload.host)
    if not payload.dev_sink and not host:
        raise HTTPException(status_code=400, detail="Hôte SMTP requis")
    if payload.port < 1 or payload.port > 65535:
        raise HTTPException(status_code=400, detail="Port SMTP invalide")
    if payload.use_tls and payload.use_ssl:
        raise HTTPException(status_code=400, detail="TLS et SSL ne peuvent pas être activés ensemble")
    if payload.timeout_seconds <= 0:
        raise HTTPException(status_code=400, detail="Timeout SMTP invalide")


def _validate_otp_payload(payload: OtpEmailSettingsPayload) -> None:
    if payload.ttl_minutes < 3 or payload.ttl_minutes > 60:
        raise HTTPException(status_code=400, detail="TTL OTP invalide (3-60 minutes)")
    if payload.code_length < 4 or payload.code_length > 10:
        raise HTTPException(status_code=400, detail="Longueur du code invalide (4-10)")
    if payload.max_attempts < 3 or payload.max_attempts > 10:
        raise HTTPException(status_code=400, detail="Tentatives max invalides (3-10)")
    if payload.resend_cooldown_seconds < 10 or payload.resend_cooldown_seconds > 300:
        raise HTTPException(status_code=400, detail="Cooldown invalide (10-300 secondes)")
    if payload.rate_limit_per_hour < 1 or payload.rate_limit_per_hour > 60:
        raise HTTPException(status_code=400, detail="Rate limit invalide (1-60 par heure)")


def _validate_purchase_suggestion_payload(payload: PurchaseSuggestionSettingsPayload) -> None:
    if payload.expiry_soon_days < 0 or payload.expiry_soon_days > 365:
        raise HTTPException(
            status_code=400,
            detail="Délai de péremption invalide (0-365 jours)",
        )


@router.get("/debug-config", response_model=models.DebugConfig)
def get_debug_config(user: models.User = Depends(require_admin)):
    return load_debug_config()


@router.put("/debug-config", response_model=models.DebugConfig)
def update_debug_config(cfg: models.DebugConfig, user: models.User = Depends(require_admin)):
    save_debug_config(cfg.model_dump())
    return cfg


@router.get("/vehicle-types", response_model=list[models.VehicleTypeEntry])
def list_vehicle_types(user: models.User = Depends(require_admin)):
    return services.list_vehicle_types()


@router.post("/vehicle-types", response_model=models.VehicleTypeEntry, status_code=201)
def create_vehicle_type(
    payload: models.VehicleTypeCreate, user: models.User = Depends(require_admin)
):
    try:
        return services.create_vehicle_type(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/vehicle-types/{vehicle_type_id}", response_model=models.VehicleTypeEntry)
def update_vehicle_type(
    vehicle_type_id: int,
    payload: models.VehicleTypeUpdate,
    user: models.User = Depends(require_admin),
):
    try:
        return services.update_vehicle_type(vehicle_type_id, payload)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.delete("/vehicle-types/{vehicle_type_id}", status_code=204)
def delete_vehicle_type(vehicle_type_id: int, user: models.User = Depends(require_admin)):
    try:
        services.delete_vehicle_type(vehicle_type_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/custom-fields", response_model=list[models.CustomFieldDefinition])
def list_custom_fields(
    scope: str | None = None, user: models.User = Depends(require_admin)
):
    try:
        return services.list_custom_field_definitions(scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/custom-fields", response_model=models.CustomFieldDefinition, status_code=201)
def create_custom_field(
    payload: models.CustomFieldDefinitionCreate, user: models.User = Depends(require_admin)
):
    try:
        return services.create_custom_field_definition(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/custom-fields/{custom_field_id}", response_model=models.CustomFieldDefinition)
def update_custom_field(
    custom_field_id: int,
    payload: models.CustomFieldDefinitionUpdate,
    user: models.User = Depends(require_admin),
):
    try:
        return services.update_custom_field_definition(custom_field_id, payload)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "introuvable" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.delete("/custom-fields/{custom_field_id}", status_code=204)
def delete_custom_field(custom_field_id: int, user: models.User = Depends(require_admin)):
    try:
        services.delete_custom_field_definition(custom_field_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/logs/status", response_model=LogStatusResponse)
def get_logs_status(user: models.User = Depends(require_admin)):
    files = list_log_files(LOG_DIR)
    total_size = sum(entry["size"] for entry in files)
    return LogStatusResponse(
        log_dir=str(LOG_DIR),
        max_bytes=LOG_MAX_BYTES,
        backup_count=LOG_BACKUP_COUNT,
        total_size=total_size,
        files=[
            LogFileEntry(
                name=entry["name"],
                size=entry["size"],
                mtime=entry["mtime"],
            )
            for entry in files
        ],
    )


@router.post("/logs/purge", response_model=LogStatusResponse)
def purge_logs(user: models.User = Depends(require_admin)):
    purge_rotated_logs(LOG_DIR, LOG_BACKUP_COUNT)
    return get_logs_status(user)


@router.post("/reports/purge", response_model=ReportPurgeResponse)
def purge_reports(payload: ReportPurgeRequest, user: models.User = Depends(require_admin)):
    try:
        module_key, deleted = services.purge_reports_stats(payload.module_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReportPurgeResponse(ok=True, module_key=module_key, deleted=deleted)


@router.get("/security/settings", response_model=models.SecuritySettings)
def get_security_settings(user: models.User = Depends(require_admin)) -> models.SecuritySettings:
    config = get_config()
    return models.SecuritySettings(
        require_totp_for_login=config.security.require_totp_for_login,
        idle_logout_minutes=config.security.idle_logout_minutes,
        logout_on_close=config.security.logout_on_close,
    )


@router.put("/security/settings", response_model=models.SecuritySettings)
def update_security_settings(
    payload: models.SecuritySettings, user: models.User = Depends(require_admin)
) -> models.SecuritySettings:
    config = get_config()
    config.security.require_totp_for_login = payload.require_totp_for_login
    config.security.idle_logout_minutes = payload.idle_logout_minutes
    config.security.logout_on_close = payload.logout_on_close
    save_config(config)
    return payload


@router.get("/email/smtp-settings", response_model=SmtpSettingsResponse)
def get_smtp_settings(user: models.User = Depends(require_admin)) -> SmtpSettingsResponse:
    config, password_set = system_settings.get_email_smtp_config_state()
    return SmtpSettingsResponse(
        host=config.host,
        port=config.port,
        username=config.username,
        from_email=config.from_email,
        use_tls=config.use_tls,
        use_ssl=config.use_ssl,
        timeout_seconds=config.timeout_seconds,
        dev_sink=config.dev_sink,
        smtp_password_set=password_set,
    )


@router.put("/email/smtp-settings", response_model=SmtpSettingsResponse)
def update_smtp_settings(
    payload: SmtpSettingsUpdate, user: models.User = Depends(require_admin)
) -> SmtpSettingsResponse:
    _validate_smtp_payload(payload)
    current = system_settings.get_setting_json(system_settings.SMTP_SETTINGS_KEY) or {}
    password_enc = current.get("password_enc")
    if payload.clear_password:
        password_enc = None
    if payload.password not in (None, ""):
        password_enc = system_settings.encrypt_smtp_password(payload.password)
    value: dict[str, object] = {
        "host": _normalize_optional_text(payload.host),
        "port": payload.port,
        "username": _normalize_optional_text(payload.username),
        "from_email": payload.from_email.strip(),
        "use_tls": payload.use_tls,
        "use_ssl": payload.use_ssl,
        "timeout_seconds": payload.timeout_seconds,
        "dev_sink": payload.dev_sink,
    }
    if password_enc:
        value["password_enc"] = password_enc
    system_settings.set_setting_json(system_settings.SMTP_SETTINGS_KEY, value, user.username)
    config, password_set = system_settings.get_email_smtp_config_state()
    return SmtpSettingsResponse(
        host=config.host,
        port=config.port,
        username=config.username,
        from_email=config.from_email,
        use_tls=config.use_tls,
        use_ssl=config.use_ssl,
        timeout_seconds=config.timeout_seconds,
        dev_sink=config.dev_sink,
        smtp_password_set=password_set,
    )


@router.post("/email/smtp-test")
def test_smtp_settings(payload: SmtpTestRequest, user: models.User = Depends(require_admin)):
    result = _enqueue_test_email(
        payload.to_email.strip(),
        "Test SMTP StockOps",
        "Ceci est un e-mail de test StockOps.",
        send_now=False,
    )
    if result.get("dev_sink"):
        return {"status": "skipped", "to_email": payload.to_email.strip(), "dev_sink": True}
    return result


@router.post("/email/test")
def test_email_delivery(
    payload: EmailTestRequest,
    send_now: bool = False,
    user: models.User = Depends(require_admin),
):
    return _enqueue_test_email(
        payload.to_email.strip(),
        payload.subject.strip(),
        payload.body,
        send_now=send_now,
    )


def _enqueue_test_email(
    to_email: str,
    subject: str,
    body: str,
    *,
    send_now: bool,
) -> dict[str, object]:
    config = system_settings.get_email_smtp_config()
    if not config.dev_sink and not config.host:
        raise HTTPException(status_code=400, detail="SMTP non configuré")
    email_id = notifications.enqueue_email(
        to_email=to_email,
        subject=subject,
        body_text=body,
        purpose="smtp_test",
        meta={"endpoint": "admin_email_test"},
    )
    response: dict[str, object] = {"status": "queued", "to_email": to_email}
    if config.dev_sink:
        response["dev_sink"] = True
    if not send_now:
        return response
    notifications.run_outbox_once()
    with db.get_core_connection() as conn:
        row = conn.execute(
            "SELECT sent_at, last_error FROM email_outbox WHERE id = ?",
            (email_id,),
        ).fetchone()
    if row and row["sent_at"]:
        return {"status": "sent", "to_email": to_email, "dev_sink": config.dev_sink}
    error = str(row["last_error"]) if row and row["last_error"] else "unknown"
    return {
        "status": "queued_but_failed",
        "to_email": to_email,
        "error": error,
        "dev_sink": config.dev_sink,
    }


@router.get("/email/otp-settings", response_model=OtpEmailSettingsPayload)
def get_otp_email_settings(user: models.User = Depends(require_admin)) -> OtpEmailSettingsPayload:
    config = system_settings.get_email_otp_config()
    return OtpEmailSettingsPayload(
        ttl_minutes=config.ttl_minutes,
        code_length=config.code_length,
        max_attempts=config.max_attempts,
        resend_cooldown_seconds=config.resend_cooldown_seconds,
        rate_limit_per_hour=config.rate_limit_per_hour,
        allow_insecure_dev=config.allow_insecure_dev,
    )


@router.put("/email/otp-settings", response_model=OtpEmailSettingsPayload)
def update_otp_email_settings(
    payload: OtpEmailSettingsPayload, user: models.User = Depends(require_admin)
) -> OtpEmailSettingsPayload:
    _validate_otp_payload(payload)
    system_settings.set_setting_json(
        system_settings.OTP_EMAIL_SETTINGS_KEY,
        payload.model_dump(),
        user.username,
    )
    return payload


@router.get("/purchase-suggestions/settings", response_model=PurchaseSuggestionSettingsPayload)
def get_purchase_suggestion_settings(
    user: models.User = Depends(require_admin),
) -> PurchaseSuggestionSettingsPayload:
    config = system_settings.get_purchase_suggestion_settings()
    return PurchaseSuggestionSettingsPayload(expiry_soon_days=config.expiry_soon_days)


@router.put("/purchase-suggestions/settings", response_model=PurchaseSuggestionSettingsPayload)
def update_purchase_suggestion_settings(
    payload: PurchaseSuggestionSettingsPayload,
    user: models.User = Depends(require_admin),
) -> PurchaseSuggestionSettingsPayload:
    _validate_purchase_suggestion_payload(payload)
    system_settings.set_setting_json(
        system_settings.PURCHASE_SUGGESTION_SETTINGS_KEY,
        payload.model_dump(),
        user.username,
    )
    return payload


@router.get("/qol-settings", response_model=models.QolSettings)
def get_qol_settings(user: models.User = Depends(require_admin)) -> models.QolSettings:
    settings = system_settings.get_qol_settings()
    return models.QolSettings(
        timezone=settings.timezone,
        date_format=settings.date_format,
        auto_archive_days=settings.auto_archive_days,
        note_preview_length=settings.note_preview_length,
    )


@router.put("/qol-settings", response_model=models.QolSettings)
def update_qol_settings(
    payload: models.QolSettings, user: models.User = Depends(require_admin)
) -> models.QolSettings:
    settings = system_settings.set_qol_settings(payload.model_dump(), user.username)
    return models.QolSettings(
        timezone=settings.timezone,
        date_format=settings.date_format,
        auto_archive_days=settings.auto_archive_days,
        note_preview_length=settings.note_preview_length,
    )


@router.get("/backup/settings", response_model=models.BackupSettingsStatus)
async def get_backup_settings(user: models.User = Depends(require_admin)):
    site_key = db.get_current_site_key()
    return await backup_scheduler.get_status(site_key)


@router.put("/backup/settings", response_model=models.BackupSettingsStatus)
async def update_backup_settings(
    settings: models.BackupSettings, user: models.User = Depends(require_admin)
):
    if settings.interval_minutes > MAX_BACKUP_INTERVAL_MINUTES:
        raise HTTPException(
            status_code=400,
            detail=f"Intervalle maximum autorisé: {MAX_BACKUP_INTERVAL_MINUTES} minutes",
        )
    site_key = db.get_current_site_key()
    try:
        await backup_scheduler.update_settings(site_key, settings)
    except asyncio.CancelledError:
        logger.debug(
            "Annulation absorbée lors de la mise à jour de la planification pour %s",
            site_key,
        )
    except Exception as exc:  # pragma: no cover - gestion d'erreur HTTP
        logger.exception(
            "Échec de la mise à jour de la planification des sauvegardes pour %s",
            site_key,
        )
        raise HTTPException(
            status_code=500,
            detail="Impossible d'appliquer la planification des sauvegardes",
        ) from exc
    return await backup_scheduler.get_status(site_key)
