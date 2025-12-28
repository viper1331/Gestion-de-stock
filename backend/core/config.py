"""Configuration statique du backend."""
from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t"}
_FALSE_VALUES = {"0", "false", "no", "off", "n", "f"}


def _get_env_flag(name: str, default: bool = False) -> bool:
    """Retourne une valeur booléenne à partir d'une variable d'environnement."""

    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def _get_env_choice(name: str, choices: set[str], default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    return normalized if normalized in choices else default


@dataclass(frozen=True)
class Settings:
    """Paramètres globaux lus depuis l'environnement."""

    INVENTORY_DEBUG: bool = False
    PDF_RENDERER: str = "auto"


settings = Settings(
    INVENTORY_DEBUG=_get_env_flag("INVENTORY_DEBUG", default=False),
    PDF_RENDERER=_get_env_choice("PDF_RENDERER", {"auto", "html", "reportlab"}, "auto"),
)
