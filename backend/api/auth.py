"""Routes d'authentification."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer

from backend.core import (
    db,
    models,
    security,
    services,
    two_factor,
    two_factor_crypto,
)

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
logger = logging.getLogger(__name__)


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


def _build_token_for_user(user: models.User) -> models.Token:
    token_data = {"role": user.role}
    access_token = security.create_access_token(user.username, token_data)
    refresh_token = security.create_refresh_token(user.username, token_data)
    return models.Token(access_token=access_token, refresh_token=refresh_token)


def _build_token_with_user(user: models.User) -> models.TokenWithUser:
    token = _build_token_for_user(user)
    return models.TokenWithUser(
        access_token=token.access_token,
        refresh_token=token.refresh_token,
        user=_build_login_user_summary(user),
    )


def _build_login_user_summary(user: models.User) -> models.LoginUserSummary:
    return models.LoginUserSummary(
        username=user.username,
        role=user.role,
        site_key=user.site_key,
    )


def _ensure_user_active(user: models.User) -> None:
    if user.status == "active":
        return
    if user.status == "pending":
        detail = "Compte en attente de validation administrateur."
    elif user.status == "rejected":
        detail = "Compte refusé. Contactez un administrateur."
    else:
        detail = "Compte désactivé."
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _get_two_factor_row(username: str) -> dict[str, object]:
    with db.get_users_connection() as conn:
        row = conn.execute(
            """
            SELECT two_factor_enabled, two_factor_secret_enc, two_factor_recovery_hashes, two_factor_confirmed_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()
    if not row:
        return {}
    return dict(row)


def _allow_secret_plaintext() -> bool:
    env_value = (os.getenv("APP_ENV") or os.getenv("ENV") or "").strip().lower()
    return env_value == "dev"


@router.post(
    "/login",
    response_model=models.TotpRequiredResponse | models.TotpEnrollRequiredResponse,
)
async def login(
    credentials: models.LoginRequest,
) -> models.TotpRequiredResponse | models.TotpEnrollRequiredResponse:
    user, needs_email_upgrade = services.authenticate_with_identifier(
        credentials.identifier,
        credentials.password,
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides")
    _ensure_user_active(user)
    two_factor_row = _get_two_factor_row(user.username)
    if bool(two_factor_row.get("two_factor_enabled")):
        challenge_token = two_factor.create_challenge(user.username, purpose="verify")
        return models.TotpRequiredResponse(
            challenge_token=challenge_token,
            user=_build_login_user_summary(user),
            needs_email_upgrade=needs_email_upgrade or None,
        )
    secret = two_factor.generate_totp_secret()
    secret_enc = two_factor_crypto.encrypt_secret(secret)
    challenge_token = two_factor.create_challenge(
        user.username,
        purpose="enroll",
        secret_enc=secret_enc,
    )
    return models.TotpEnrollRequiredResponse(
        challenge_token=challenge_token,
        otpauth_uri=two_factor.build_otpauth_uri(user.username, secret),
        secret_masked=two_factor.mask_secret(secret),
        secret_plain_if_allowed=secret if _allow_secret_plaintext() else None,
        user=_build_login_user_summary(user),
        needs_email_upgrade=needs_email_upgrade or None,
    )


@router.post("/register", response_model=models.RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: models.RegisterRequest) -> models.RegisterResponse:
    try:
        services.register_user(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return models.RegisterResponse(message="Demande envoyée, en attente de validation.")


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
    return _build_token_for_user(user)


@router.get("/me", response_model=models.User)
async def me(current_user: models.User = Depends(get_current_user)) -> models.User:
    return current_user


@router.get("/2fa/status", response_model=models.TwoFactorStatus)
async def two_factor_status(current_user: models.User = Depends(get_current_user)) -> models.TwoFactorStatus:
    row = _get_two_factor_row(current_user.username)
    return models.TwoFactorStatus(
        enabled=bool(row.get("two_factor_enabled")),
        confirmed_at=row.get("two_factor_confirmed_at"),
    )


@router.post("/2fa/setup/start", response_model=models.TwoFactorSetupStartResponse)
async def two_factor_setup_start(
    current_user: models.User = Depends(get_current_user),
) -> models.TwoFactorSetupStartResponse:
    row = _get_two_factor_row(current_user.username)
    if bool(row.get("two_factor_enabled")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA déjà activée")
    secret = two_factor.generate_totp_secret()
    encrypted = two_factor_crypto.encrypt_secret(secret)
    with db.get_users_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET two_factor_secret_enc = ?, two_factor_enabled = 0, two_factor_confirmed_at = NULL,
                two_factor_recovery_hashes = NULL
            WHERE username = ?
            """,
            (encrypted, current_user.username),
        )
    return models.TwoFactorSetupStartResponse(
        otpauth_uri=two_factor.build_otpauth_uri(current_user.username, secret),
        secret_masked=two_factor.mask_secret(secret),
    )


@router.post("/2fa/setup/confirm", response_model=models.TwoFactorSetupConfirmResponse)
async def two_factor_setup_confirm(
    payload: models.TwoFactorSetupConfirmRequest,
    current_user: models.User = Depends(get_current_user),
) -> models.TwoFactorSetupConfirmResponse:
    row = _get_two_factor_row(current_user.username)
    secret_enc = row.get("two_factor_secret_enc")
    if not secret_enc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA non initialisée")
    if bool(row.get("two_factor_enabled")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA déjà activée")
    secret = two_factor_crypto.decrypt_secret(str(secret_enc))
    if not two_factor.verify_totp(secret, payload.code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code 2FA invalide")
    recovery_codes = two_factor.generate_recovery_codes()
    recovery_hashes = two_factor.serialize_recovery_hashes(
        two_factor.hash_recovery_codes(recovery_codes)
    )
    now = datetime.now(timezone.utc).isoformat()
    with db.get_users_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET two_factor_enabled = 1,
                two_factor_confirmed_at = ?,
                two_factor_recovery_hashes = ?,
                two_factor_last_used_at = NULL
            WHERE username = ?
            """,
            (now, recovery_hashes, current_user.username),
        )
    logger.info("2FA enabled for %s", current_user.username)
    return models.TwoFactorSetupConfirmResponse(enabled=True, recovery_codes=recovery_codes)


@router.post("/2fa/verify", response_model=models.Token)
async def two_factor_verify(
    payload: models.TwoFactorVerifyRequest,
    request: Request,
    response: Response,
) -> models.Token:
    try:
        challenge = two_factor.load_challenge(payload.challenge_id)
    except two_factor.ChallengeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    if challenge.get("purpose") not in {"verify", None}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge invalide")
    username = str(challenge.get("username"))
    ip_address = request.client.host if request.client else "unknown"
    try:
        two_factor.check_rate_limit(username, ip_address)
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    row = _get_two_factor_row(username)
    if not bool(row.get("two_factor_enabled")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA non active")
    secret_enc = row.get("two_factor_secret_enc")
    if not secret_enc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA non configurée")
    secret = two_factor_crypto.decrypt_secret(str(secret_enc))
    if not two_factor.verify_totp(secret, payload.code):
        two_factor.register_rate_limit_failure(username, ip_address)
        try:
            two_factor.register_challenge_failure(payload.challenge_id)
        except two_factor.RateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Trop de tentatives",
            ) from exc
        logger.warning("2FA failed for %s", username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code 2FA invalide")
    two_factor.clear_rate_limit(username, ip_address)
    two_factor.consume_challenge(payload.challenge_id)
    with db.get_users_connection() as conn:
        conn.execute(
            "UPDATE users SET two_factor_last_used_at = ? WHERE username = ?",
            (datetime.now(timezone.utc).isoformat(), username),
        )
    user = services.get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    logger.info("2FA success for %s", username)
    return _build_token_for_user(user)


@router.post("/totp/verify", response_model=models.TokenWithUser)
async def totp_verify(
    payload: models.TotpVerifyRequest,
    request: Request,
) -> models.TokenWithUser:
    try:
        challenge = two_factor.load_challenge(payload.challenge_token)
    except two_factor.ChallengeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    if challenge.get("purpose") != "verify":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge invalide")
    username = str(challenge.get("username"))
    ip_address = request.client.host if request.client else "unknown"
    try:
        two_factor.check_rate_limit(username, ip_address)
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    row = _get_two_factor_row(username)
    if not bool(row.get("two_factor_enabled")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA non active")
    secret_enc = row.get("two_factor_secret_enc")
    if not secret_enc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA non configurée")
    secret = two_factor_crypto.decrypt_secret(str(secret_enc))
    if not two_factor.verify_totp(secret, payload.code):
        two_factor.register_rate_limit_failure(username, ip_address)
        try:
            two_factor.register_challenge_failure(payload.challenge_token)
        except two_factor.RateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Trop de tentatives",
            ) from exc
        logger.warning("2FA failed for %s", username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code 2FA invalide")
    two_factor.clear_rate_limit(username, ip_address)
    two_factor.consume_challenge(payload.challenge_token)
    with db.get_users_connection() as conn:
        conn.execute(
            "UPDATE users SET two_factor_last_used_at = ? WHERE username = ?",
            (datetime.now(timezone.utc).isoformat(), username),
        )
    user = services.get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    logger.info("2FA success for %s", username)
    return _build_token_with_user(user)


@router.post("/totp/enroll/confirm", response_model=models.TokenWithUser)
async def totp_enroll_confirm(
    payload: models.TotpEnrollConfirmRequest,
    request: Request,
) -> models.TokenWithUser:
    try:
        challenge = two_factor.load_challenge(payload.challenge_token)
    except two_factor.ChallengeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    if challenge.get("purpose") != "enroll":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Challenge invalide")
    username = str(challenge.get("username"))
    row = _get_two_factor_row(username)
    if bool(row.get("two_factor_enabled")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA déjà activée")
    ip_address = request.client.host if request.client else "unknown"
    try:
        two_factor.check_rate_limit(username, ip_address)
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    secret_enc = challenge.get("secret_enc")
    if not secret_enc:
        secret = two_factor.generate_totp_secret()
        secret_enc = two_factor_crypto.encrypt_secret(secret)
        two_factor.set_challenge_secret(payload.challenge_token, secret_enc)
    else:
        secret = two_factor_crypto.decrypt_secret(str(secret_enc))
    if not two_factor.verify_totp(secret, payload.code):
        two_factor.register_rate_limit_failure(username, ip_address)
        try:
            two_factor.register_challenge_failure(payload.challenge_token)
        except two_factor.RateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Trop de tentatives",
            ) from exc
        logger.warning("2FA enroll failed for %s", username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code 2FA invalide")
    now = datetime.now(timezone.utc).isoformat()
    with db.get_users_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET two_factor_enabled = 1,
                two_factor_secret_enc = ?,
                two_factor_confirmed_at = ?,
                two_factor_last_used_at = NULL
            WHERE username = ?
            """,
            (secret_enc, now, username),
        )
    two_factor.clear_rate_limit(username, ip_address)
    two_factor.consume_challenge(payload.challenge_token)
    user = services.get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    logger.info("2FA enabled for %s", username)
    return _build_token_with_user(user)


@router.post("/2fa/recovery", response_model=models.Token)
async def two_factor_recovery(
    payload: models.TwoFactorRecoveryRequest,
    request: Request,
    response: Response,
) -> models.Token:
    try:
        challenge = two_factor.load_challenge(payload.challenge_id)
    except two_factor.ChallengeError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    username = str(challenge.get("username"))
    ip_address = request.client.host if request.client else "unknown"
    try:
        two_factor.check_rate_limit(username, ip_address)
    except two_factor.RateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de tentatives") from exc
    row = _get_two_factor_row(username)
    if not bool(row.get("two_factor_enabled")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="2FA non active")
    recovery_hashes = two_factor.parse_recovery_hashes(
        row.get("two_factor_recovery_hashes") if row else None
    )
    matched, remaining = two_factor.verify_recovery_code(recovery_hashes, payload.recovery_code)
    if not matched:
        two_factor.register_rate_limit_failure(username, ip_address)
        try:
            two_factor.register_challenge_failure(payload.challenge_id)
        except two_factor.RateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Trop de tentatives",
            ) from exc
        logger.warning("2FA failed for %s", username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code de récupération invalide")
    two_factor.clear_rate_limit(username, ip_address)
    two_factor.consume_challenge(payload.challenge_id)
    with db.get_users_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET two_factor_recovery_hashes = ?, two_factor_last_used_at = ?
            WHERE username = ?
            """,
            (
                two_factor.serialize_recovery_hashes(remaining),
                datetime.now(timezone.utc).isoformat(),
                username,
            ),
        )
    user = services.get_user(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable")
    logger.info("2FA success for %s", username)
    return _build_token_for_user(user)


@router.post("/2fa/disable")
async def two_factor_disable(
    payload: models.TwoFactorDisableRequest,
    current_user: models.User = Depends(get_current_user),
) -> dict[str, bool]:
    verified_user = services.authenticate(current_user.username, payload.password)
    if not verified_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mot de passe invalide")
    row = _get_two_factor_row(current_user.username)
    secret_enc = row.get("two_factor_secret_enc")
    recovery_hashes = two_factor.parse_recovery_hashes(
        row.get("two_factor_recovery_hashes") if row else None
    )
    totp_ok = False
    if secret_enc:
        secret = two_factor_crypto.decrypt_secret(str(secret_enc))
        totp_ok = two_factor.verify_totp(secret, payload.code)
    if not totp_ok:
        matched, _ = two_factor.verify_recovery_code(recovery_hashes, payload.code)
        if not matched:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code 2FA invalide")
    with db.get_users_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET two_factor_enabled = 0,
                two_factor_secret_enc = NULL,
                two_factor_confirmed_at = NULL,
                two_factor_recovery_hashes = NULL,
                two_factor_last_used_at = NULL
            WHERE username = ?
            """,
            (current_user.username,),
        )
    two_factor.clear_trusted_devices(current_user.username)
    logger.info("2FA disabled for %s", current_user.username)
    return {"disabled": True}
