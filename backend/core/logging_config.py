from __future__ import annotations

import logging
import logging.config
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_DIR = PROJECT_ROOT / "backend" / "logs"


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


LOG_DIR = Path(os.getenv("LOG_DIR", str(DEFAULT_LOG_DIR))).expanduser()
LOG_MAX_BYTES = _get_env_int("LOG_MAX_BYTES", 3_072_000)
LOG_BACKUP_COUNT = _get_env_int("LOG_BACKUP_COUNT", 10)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

LOG_DIR.mkdir(parents=True, exist_ok=True)


def _extract_log_base_name(filename: str) -> str | None:
    if ".log" not in filename:
        return None
    prefix, _suffix = filename.split(".log", 1)
    return f"{prefix}.log"


def list_log_files(log_dir: Path = LOG_DIR) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    if not log_dir.exists():
        return files
    for path in sorted(log_dir.glob("*.log*"), key=lambda entry: entry.name):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime),
            }
        )
    return files


def purge_rotated_logs(
    log_dir: Path = LOG_DIR,
    backup_count: int = LOG_BACKUP_COUNT,
    logger: logging.Logger | None = None,
) -> list[Path]:
    if logger is None:
        logger = logging.getLogger(__name__)
    if not log_dir.exists():
        return []
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in log_dir.glob("*.log*"):
        base_name = _extract_log_base_name(path.name)
        if base_name:
            grouped[base_name].append(path)

    deleted: list[Path] = []
    keep_count = 1 + backup_count
    for entries in grouped.values():
        ordered = sorted(entries, key=lambda entry: entry.stat().st_mtime, reverse=True)
        for path in ordered[keep_count:]:
            try:
                path.unlink()
                deleted.append(path)
            except PermissionError:
                logger.warning("Log file locked; skipping deletion: %s", path)
    return deleted


def configure_logging() -> None:
    """Configure application-wide logging with rotating file handlers."""

    logging.captureWarnings(True)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": LOG_LEVEL,
                "formatter": "verbose",
            },
            "app_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": LOG_LEVEL,
                "formatter": "verbose",
                "filename": str(LOG_DIR / "app.log"),
                "maxBytes": LOG_MAX_BYTES,
                "backupCount": LOG_BACKUP_COUNT,
                "encoding": "utf-8",
                "delay": True,
            },
            "access_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": LOG_LEVEL,
                "formatter": "verbose",
                "filename": str(LOG_DIR / "access.log"),
                "maxBytes": LOG_MAX_BYTES,
                "backupCount": LOG_BACKUP_COUNT,
                "encoding": "utf-8",
                "delay": True,
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": LOG_LEVEL,
                "formatter": "verbose",
                "filename": str(LOG_DIR / "error.log"),
                "maxBytes": LOG_MAX_BYTES,
                "backupCount": LOG_BACKUP_COUNT,
                "encoding": "utf-8",
                "delay": True,
            },
        },
        "loggers": {
            "": {
                "handlers": ["console", "app_file"],
                "level": LOG_LEVEL,
            },
            "uvicorn": {
                "handlers": ["console", "error_file"],
                "level": LOG_LEVEL,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console", "error_file"],
                "level": LOG_LEVEL,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console", "access_file"],
                "level": LOG_LEVEL,
                "propagate": False,
            },
            "frontend": {
                "handlers": ["app_file"],
                "level": LOG_LEVEL,
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(logging_config)


__all__ = [
    "configure_logging",
    "LOG_BACKUP_COUNT",
    "LOG_DIR",
    "LOG_LEVEL",
    "LOG_MAX_BYTES",
    "list_log_files",
    "purge_rotated_logs",
]
