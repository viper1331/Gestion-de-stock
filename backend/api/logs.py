from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, validator

logger = logging.getLogger("frontend")

router = APIRouter()


class FrontendLogEntry(BaseModel):
    level: Literal["debug", "info", "warning", "error", "critical"] = Field(
        description="Niveau de log envoyé depuis le frontend."
    )
    message: str = Field(description="Message principal à enregistrer dans le journal.")
    context: dict[str, Any] | None = Field(
        default=None, description="Contexte supplémentaire fourni par le frontend."
    )
    user_agent: str | None = Field(
        default=None, description="User agent du navigateur ayant généré l'évènement."
    )
    url: str | None = Field(
        default=None, description="URL active lors de la génération de l'évènement."
    )
    timestamp: datetime | None = Field(
        default=None, description="Horodatage généré côté frontend, si disponible."
    )

    @validator("message")
    def validate_message(cls, value: str) -> str:  # noqa: D417 - message validation
        if not value:
            raise ValueError("Le message de log ne peut pas être vide")
        return value


@router.post("/frontend", status_code=204)
async def store_frontend_log(entry: FrontendLogEntry, request: Request) -> None:
    """Stocke un log envoyé par le frontend dans le fichier dédié."""

    log_context = {
        "client_ip": request.client.host if request.client else None,
        "user_agent": entry.user_agent,
        "context": entry.context,
        "url": entry.url,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
    }

    level_method = getattr(logger, entry.level, logger.info)
    level_method("%s | contexte=%s", entry.message, log_context)
