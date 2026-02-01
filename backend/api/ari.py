"""Routes ARI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.api.auth import get_current_user
from backend.core import db, models, models_ari, services, sites

router = APIRouter(prefix="/ari", tags=["ARI"])


def _resolve_ari_site(user: models.User, request: Request) -> str:
    if user.role == "certificateur":
        header_site = request.headers.get("X-ARI-SITE")
        if not header_site:
            raise HTTPException(status_code=400, detail="X-ARI-SITE requis")
        try:
            return sites.normalize_site_key(header_site) or db.DEFAULT_SITE_KEY
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return db.get_current_site_key()


def _can_read(user: models.User) -> bool:
    return user.role in {"admin", "certificateur"} or services.has_module_access(user, "ari")


def _can_write(user: models.User) -> bool:
    return user.role == "admin" or services.has_module_access(user, "ari", action="edit")


def _can_certify(user: models.User) -> bool:
    return user.role in {"admin", "certificateur"}


def _can_settings(user: models.User) -> bool:
    return user.role == "admin"


@router.get("/settings", response_model=models_ari.AriSettings)
async def get_ari_settings(
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models_ari.AriSettings:
    if not _can_read(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_get_settings(site_slug)


@router.put("/settings", response_model=models_ari.AriSettings)
async def update_ari_settings(
    payload: models_ari.AriSettingsUpdate,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models_ari.AriSettings:
    if not _can_settings(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_update_settings(site_slug, payload, updated_by=user.username)


@router.post("/sessions", response_model=models_ari.AriSession, status_code=status.HTTP_201_CREATED)
async def create_ari_session(
    payload: models_ari.AriSessionCreate,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models_ari.AriSession:
    if not _can_write(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    try:
        return services.ari_create_session(site_slug, payload, created_by=user.username)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions", response_model=list[models_ari.AriSession])
async def list_ari_sessions(
    collaborator_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> list[models_ari.AriSession]:
    if not _can_read(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_list_sessions(site_slug, collaborator_id)


@router.get("/stats/collaborator/{collaborator_id}", response_model=models_ari.AriCollaboratorStats)
async def get_ari_collaborator_stats(
    collaborator_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models_ari.AriCollaboratorStats:
    if not _can_read(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_get_collaborator_stats(site_slug, collaborator_id)


@router.get("/stats/site")
async def get_ari_site_stats(
    request: Request,
    user: models.User = Depends(get_current_user),
) -> dict[str, object]:
    if not _can_read(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_get_site_stats(site_slug)


@router.get("/certifications", response_model=models_ari.AriCertification)
async def get_ari_certification(
    collaborator_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models_ari.AriCertification:
    if not _can_read(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_get_certification(site_slug, collaborator_id)


@router.get("/certifications/pending", response_model=list[models_ari.AriCertification])
async def list_ari_pending(
    request: Request,
    user: models.User = Depends(get_current_user),
) -> list[models_ari.AriCertification]:
    if not (_can_read(user) and _can_certify(user)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_list_pending(site_slug)


@router.post("/certifications/decide", response_model=models_ari.AriCertification)
async def decide_ari_certification(
    payload: models_ari.AriCertificationDecision,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> models_ari.AriCertification:
    if not _can_certify(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    return services.ari_decide_certification(site_slug, payload, decided_by=user.username)


@router.get("/collaborators/{collaborator_id}/export.pdf")
async def export_ari_collaborator_pdf(
    collaborator_id: int,
    request: Request,
    user: models.User = Depends(get_current_user),
) -> Response:
    if not _can_read(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Autorisations insuffisantes")
    site_slug = _resolve_ari_site(user, request)
    content = services.ari_export_collaborator_pdf(site_slug, collaborator_id)
    headers = {"Content-Disposition": f"attachment; filename=ari_{collaborator_id}.pdf"}
    return Response(content, media_type="application/pdf", headers=headers)
