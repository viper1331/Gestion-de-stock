"""Gestion centralisée de la configuration système dynamique."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5151",
    "http://127.0.0.1:5151",
]

CONFIG_PATH = Path(__file__).resolve().parent.parent / "system_config.json"


class SystemConfig(BaseModel):
    """Configuration technique du système exposée à l'administration."""

    model_config = ConfigDict(extra="allow")

    backend_url: HttpUrl | None = Field(
        "http://localhost:8000",
        description="URL historique (compatibilité) du backend",
    )
    backend_url_lan: HttpUrl | None = Field(
        None, description="URL backend à utiliser sur le réseau local"
    )
    backend_url_public: HttpUrl | None = Field(
        None, description="URL backend à utiliser depuis Internet"
    )
    frontend_url: HttpUrl = Field("http://localhost:5151", description="URL publique ou locale du frontend")
    backend_host: str = Field("0.0.0.0", description="Hôte d'écoute du backend")
    backend_port: int = Field(8000, ge=1, le=65535, description="Port d'écoute du backend")
    frontend_host: str = Field("0.0.0.0", description="Hôte d'écoute du frontend")
    frontend_port: int = Field(5151, ge=1, le=65535, description="Port d'écoute du frontend")
    cors_origins: list[str] = Field(default_factory=lambda: list(DEFAULT_CORS_ORIGINS))
    network_mode: Literal["auto", "lan", "public"] = Field(
        "auto", description="Mode de sélection de l'URL backend"
    )
    extra: dict[str, str] = Field(default_factory=dict, description="Réglages additionnels")

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fields(cls, value: dict) -> dict:
        data = dict(value or {})

        legacy_public = data.get("backend_public_url") or data.get("backend_url")
        data.setdefault("backend_url_public", legacy_public)

        if not data.get("backend_url_lan"):
            if data.get("network_mode") in {"lan"}:  # Ancien mode
                data["backend_url_lan"] = data.get("backend_url") or legacy_public

        mode = data.get("network_mode")
        if mode == "internet":
            data["network_mode"] = "public"
        elif mode not in {"lan", "public", "auto"}:
            data["network_mode"] = "auto"

        if not data.get("backend_url"):
            for candidate in (
                data.get("backend_url_public"),
                data.get("backend_url_lan"),
                "http://localhost:8000",
            ):
                if candidate:
                    data["backend_url"] = candidate
                    break

        return data

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _coerce_origins(cls, value: Iterable[str] | str | None) -> list[str]:
        if value is None:
            return list(DEFAULT_CORS_ORIGINS)
        if isinstance(value, str):
            value = [value]
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            origin = str(raw).strip()
            if not origin:
                continue
            if origin in seen:
                continue
            cleaned.append(origin)
            seen.add(origin)
        return cleaned or list(DEFAULT_CORS_ORIGINS)


_SYSTEM_CONFIG: SystemConfig | None = None


def _load_from_disk() -> SystemConfig:
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return SystemConfig(**raw)
        except Exception:
            # Un fichier corrompu est réinitialisé avec les valeurs par défaut.
            pass
    config = SystemConfig()
    save_config(config)
    return config


def get_config() -> SystemConfig:
    """Retourne la configuration courante."""

    global _SYSTEM_CONFIG
    if _SYSTEM_CONFIG is None:
        _SYSTEM_CONFIG = _load_from_disk()
    return _SYSTEM_CONFIG


def save_config(config: SystemConfig) -> SystemConfig:
    """Persiste la configuration sur disque et la met en cache."""

    global _SYSTEM_CONFIG
    CONFIG_PATH.write_text(config.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    _SYSTEM_CONFIG = config
    return _SYSTEM_CONFIG


def get_env_cors_origins() -> list[str]:
    raw = os.getenv("BACKEND_CORS_ORIGINS", "")
    if not raw:
        return []
    origins = [origin.strip() for origin in raw.split(",")]
    return [origin for origin in origins if origin]


def get_effective_cors_origins(config: SystemConfig | None = None) -> list[str]:
    """Construit la liste des origines autorisées en tenant compte de l'environnement."""

    env_origins = get_env_cors_origins()
    if env_origins:
        return env_origins

    config = config or get_config()
    merged = list(DEFAULT_CORS_ORIGINS)
    for origin in config.cors_origins:
        if origin not in merged:
            merged.append(origin)
    return merged


def rebuild_cors_middleware(app: FastAPI, allow_origins: list[str] | None = None) -> list[str]:
    """Réinstalle le middleware CORS avec les origines souhaitées."""

    origins = allow_origins or get_effective_cors_origins()
    app.user_middleware = [mw for mw in app.user_middleware if mw.cls is not CORSMiddleware]
    app.user_middleware.insert(
        0,
        Middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    )
    # Rebuild the application middleware stack so the updated CORS settings take
    # effect immediately.
    app.middleware_stack = app.build_middleware_stack()
    return origins
