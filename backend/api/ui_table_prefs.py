"""Routes pour la personnalisation des tableaux UI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from backend.api.auth import get_current_user
from backend.core import db, models, services, sites

router = APIRouter()

_TABLE_PREFS_KEYS = {"pharmacy.items", "clothing.items", "remise.items"}


def _validate_table_key(table_key: str) -> str:
    normalized = table_key.strip()
    if normalized not in _TABLE_PREFS_KEYS:
        raise HTTPException(status_code=400, detail="table_key invalide")
    return normalized


def _resolve_site_key(request: Request) -> str:
    header_site_key = request.headers.get("X-Site-Key")
    if header_site_key:
        try:
            return sites.normalize_site_key(header_site_key) or db.get_current_site_key()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return db.get_current_site_key()


@router.get("/table-prefs/{table_key}", response_model=models.TablePrefsResponse | None)
def get_table_prefs(
    table_key: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
) -> models.TablePrefsResponse | None:
    normalized_key = _validate_table_key(table_key)
    site_key = _resolve_site_key(request)
    prefs = services.get_table_prefs(current_user.id, site_key, normalized_key)
    if not prefs:
        return None
    return models.TablePrefsResponse(table_key=normalized_key, prefs=prefs)


@router.put("/table-prefs/{table_key}", response_model=models.TablePrefsResponse)
def set_table_prefs(
    payload: models.TablePrefsPayload,
    table_key: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
) -> models.TablePrefsResponse:
    normalized_key = _validate_table_key(table_key)
    site_key = _resolve_site_key(request)
    try:
        prefs = services.set_table_prefs(current_user.id, site_key, normalized_key, payload.prefs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return models.TablePrefsResponse(table_key=normalized_key, prefs=prefs)


@router.delete("/table-prefs/{table_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table_prefs(
    table_key: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
) -> None:
    normalized_key = _validate_table_key(table_key)
    site_key = _resolve_site_key(request)
    services.delete_table_prefs(current_user.id, site_key, normalized_key)
    return None
