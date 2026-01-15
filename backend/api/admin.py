from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.auth import get_current_user
from backend.core import db, models, services
from backend.core.logging_config import (
    LOG_BACKUP_COUNT,
    LOG_DIR,
    LOG_MAX_BYTES,
    list_log_files,
    purge_rotated_logs,
)
from backend.services.debug_service import load_debug_config, save_debug_config
from backend.services.backup_scheduler import backup_scheduler
from backend.services.backup_settings import MAX_BACKUP_INTERVAL_MINUTES

router = APIRouter()


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


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return user


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
    await backup_scheduler.update_settings(site_key, settings)
    return await backup_scheduler.get_status(site_key)
