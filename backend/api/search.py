"""Routes pour la recherche globale."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/search", response_model=list[models.GlobalSearchResult])
async def global_search(
    q: str = Query(..., min_length=1, description="Texte de recherche"),
    user: models.User = Depends(get_current_user),
) -> list[models.GlobalSearchResult]:
    return services.search_global(user, q)
