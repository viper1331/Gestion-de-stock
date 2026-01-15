"""Chargement minimaliste des variables depuis le fichier .env."""
from __future__ import annotations

import os
from pathlib import Path
import threading

_loaded = False
_lock = threading.Lock()


def load_env() -> None:
    """Charge les variables du fichier .env à la racine du dépôt si présent."""
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if not env_path.exists():
            _loaded = True
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)
        _loaded = True
