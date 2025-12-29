"""Routes de messagerie interne."""
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.auth import get_current_user
from backend.core import models, services

router = APIRouter()


@router.get("/recipients", response_model=list[models.MessageRecipientInfo])
async def list_recipients(
    current_user: models.User = Depends(get_current_user),
) -> list[models.MessageRecipientInfo]:
    return services.list_message_recipients(current_user)


@router.post("/send", response_model=models.MessageSendResponse, status_code=status.HTTP_201_CREATED)
async def send_message(
    payload: models.MessageSendRequest,
    current_user: models.User = Depends(get_current_user),
) -> models.MessageSendResponse:
    try:
        return services.send_message(payload, current_user)
    except services.MessageRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/inbox", response_model=list[models.InboxMessage])
async def list_inbox(
    limit: int = Query(50, ge=1, le=200),
    include_archived: bool = False,
    current_user: models.User = Depends(get_current_user),
) -> list[models.InboxMessage]:
    return services.list_inbox_messages(
        current_user,
        limit=limit,
        include_archived=include_archived,
    )


@router.post("/{message_id}/read", status_code=status.HTTP_200_OK)
async def mark_read(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    try:
        services.mark_message_read(message_id, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"status": "ok"}


@router.post("/{message_id}/archive", status_code=status.HTTP_200_OK)
async def mark_archived(
    message_id: int,
    current_user: models.User = Depends(get_current_user),
) -> dict[str, str]:
    try:
        services.archive_message(message_id, current_user)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return {"status": "ok"}
