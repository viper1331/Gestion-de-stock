"""Routes d'authentification."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from backend.core import models, security, services

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> models.User:
    try:
        payload = security.decode_token(token)
    except Exception as exc:  # pragma: no cover - FastAPI gère la réponse
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Jeton invalide") from exc
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Charge utile du jeton invalide")
    user = services.get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    return user


@router.post("/login", response_model=models.Token)
async def login(credentials: models.LoginRequest) -> models.Token:
    user = services.authenticate(credentials.username, credentials.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides")
    token_data = {"role": user.role}
    access_token = security.create_access_token(user.username, token_data)
    refresh_token = security.create_refresh_token(user.username, token_data)
    return models.Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=models.Token)
async def refresh(request: models.RefreshRequest) -> models.Token:
    try:
        payload = security.decode_token(request.refresh_token)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Jeton invalide") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Type de jeton invalide")
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Charge utile du jeton invalide")
    user = services.get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    token_data = {"role": user.role}
    access_token = security.create_access_token(user.username, token_data)
    refresh_token = security.create_refresh_token(user.username, token_data)
    return models.Token(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=models.User)
async def me(current_user: models.User = Depends(get_current_user)) -> models.User:
    return current_user
