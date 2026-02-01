"""Routes pour la gestion des sessions ARI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from backend.api.auth import get_current_user
from backend.core import ari_services, models, models_ari, services
from backend.services import system_settings

router = APIRouter()

MODULE_KEY = "ari"


def _require_feature_enabled() -> None:
    if system_settings.get_feature_ari_enabled():
        return
    raise HTTPException(status_code=404, detail="Module indisponible")


def _resolve_site(user: models.User, ari_site: str | None) -> str | None:
    if ari_site and ari_site.strip():
        return ari_site.strip()
    return user.site_key


def _require_ari_read(user: models.User) -> None:
    if user.role in {"admin", "certificateur"}:
        return
    if services.has_module_access(user, MODULE_KEY, action="view"):
        return
    raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _require_ari_edit(user: models.User) -> None:
    if user.role == "admin":
        return
    if services.has_module_access(user, MODULE_KEY, action="edit"):
        return
    raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _require_ari_certify(user: models.User) -> None:
    if user.role in {"admin", "certificateur"}:
        return
    raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


def _require_admin(user: models.User) -> None:
    if user.role == "admin":
        return
    raise HTTPException(status_code=403, detail="Autorisations insuffisantes")


@router.get("/settings", response_model=models_ari.AriSettings)
async def get_ari_settings(
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriSettings:
    _require_feature_enabled()
    _require_ari_read(user)
    return ari_services.get_ari_settings(_resolve_site(user, ari_site), user.site_key)


@router.put("/settings", response_model=models_ari.AriSettings)
async def update_ari_settings(
    payload: models_ari.AriSettingsUpdate,
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriSettings:
    _require_feature_enabled()
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Autorisations insuffisantes")
    return ari_services.update_ari_settings(payload, _resolve_site(user, ari_site), user.site_key)


@router.get("/sessions", response_model=list[models_ari.AriSession])
async def list_ari_sessions(
    collaborator_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> list[models_ari.AriSession]:
    _require_feature_enabled()
    _require_ari_read(user)
    return ari_services.list_ari_sessions(
        _resolve_site(user, ari_site),
        collaborator_id=collaborator_id,
        fallback_site=user.site_key,
    )


@router.post("/sessions", response_model=models_ari.AriSession, status_code=201)
async def create_ari_session(
    payload: models_ari.AriSessionCreate,
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriSession:
    _require_feature_enabled()
    _require_ari_edit(user)
    try:
        return ari_services.create_ari_session(
            payload,
            created_by=user.username,
            site=_resolve_site(user, ari_site),
            fallback_site=user.site_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/sessions/{session_id}", response_model=models_ari.AriSession)
async def update_ari_session(
    session_id: int,
    payload: models_ari.AriSessionUpdate,
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriSession:
    _require_feature_enabled()
    _require_ari_edit(user)
    try:
        return ari_services.update_ari_session(
            session_id,
            payload,
            site=_resolve_site(user, ari_site),
            fallback_site=user.site_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=models_ari.AriSession)
async def get_ari_session(
    session_id: int,
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriSession:
    _require_feature_enabled()
    _require_ari_read(user)
    try:
        return ari_services.get_ari_session(
            session_id,
            _resolve_site(user, ari_site),
            fallback_site=user.site_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/stats/collaborator/{collaborator_id}", response_model=models_ari.AriCollaboratorStats)
async def get_ari_collaborator_stats(
    collaborator_id: int,
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriCollaboratorStats:
    _require_feature_enabled()
    _require_ari_read(user)
    return ari_services.get_ari_collaborator_stats(
        collaborator_id,
        _resolve_site(user, ari_site),
        fallback_site=user.site_key,
    )


@router.get("/certifications", response_model=models_ari.AriCertification)
async def get_ari_certification(
    collaborator_id: int = Query(...),
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriCertification:
    _require_feature_enabled()
    _require_ari_certify(user)
    return ari_services.get_ari_certification(
        collaborator_id,
        _resolve_site(user, ari_site),
        fallback_site=user.site_key,
    )


@router.get("/certifications/pending", response_model=list[models_ari.AriCertification])
async def list_pending_certifications(
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> list[models_ari.AriCertification]:
    _require_feature_enabled()
    _require_ari_certify(user)
    return ari_services.list_pending_certifications(
        _resolve_site(user, ari_site),
        fallback_site=user.site_key,
    )


@router.post("/certifications/decide", response_model=models_ari.AriCertification)
async def decide_ari_certification(
    payload: models_ari.AriCertificationDecision,
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriCertification:
    _require_feature_enabled()
    _require_ari_certify(user)
    return ari_services.decide_certification(
        payload,
        decided_by=user.username,
        site=_resolve_site(user, ari_site),
        fallback_site=user.site_key,
    )


@router.post("/admin/purge-sessions", response_model=models_ari.AriPurgeResponse)
async def purge_ari_sessions(
    payload: models_ari.AriPurgeRequest,
    user: models.User = Depends(get_current_user),
    ari_site: str | None = Header(default=None, alias="X-ARI-SITE"),
) -> models_ari.AriPurgeResponse:
    _require_feature_enabled()
    _require_admin(user)
    try:
        by_site, total = ari_services.purge_ari_sessions(
            site_scope=payload.site,
            older_than_days=payload.older_than_days,
            before_date=payload.before_date,
            include_certified=payload.include_certified,
            dry_run=payload.dry_run,
            site=_resolve_site(user, ari_site),
            fallback_site=user.site_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return models_ari.AriPurgeResponse(
        ok=True,
        dry_run=payload.dry_run,
        total=total,
        by_site=by_site,
    )
