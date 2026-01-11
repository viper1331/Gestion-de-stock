from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

LOG_MAX_BYTES = 3_072_000
LOG_BACKUP_COUNT = 10

ROOT_DIR = Path(__file__).resolve().parents[1]

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("purge-logs")


def _extract_log_base_name(filename: str) -> str | None:
    if ".log" not in filename:
        return None
    prefix, _suffix = filename.split(".log", 1)
    return f"{prefix}.log"


def collect_log_files() -> list[Path]:
    files: list[Path] = []
    backend_logs_dir = ROOT_DIR / "backend" / "logs"
    if backend_logs_dir.exists():
        files.extend(backend_logs_dir.glob("*.log*"))
    files.extend(ROOT_DIR.glob("backend.log*"))
    files.extend(ROOT_DIR.glob("frontend.log*"))
    return [path for path in files if path.is_file()]


def purge_rotated_logs(files: list[Path]) -> list[Path]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        base_name = _extract_log_base_name(path.name)
        if base_name:
            grouped[base_name].append(path)

    deleted: list[Path] = []
    keep_count = 1 + LOG_BACKUP_COUNT
    for entries in grouped.values():
        ordered = sorted(entries, key=lambda entry: entry.stat().st_mtime, reverse=True)
        for path in ordered[keep_count:]:
            try:
                path.unlink()
                deleted.append(path)
            except PermissionError:
                logger.warning("Log file locked; skipping deletion: %s", path)
    return deleted


def main() -> None:
    files = collect_log_files()
    if not files:
        logger.info("No log files found to purge.")
        return
    deleted = purge_rotated_logs(files)
    logger.info(
        "Purged %s log files (max %s bytes, keep %s rotations).",
        len(deleted),
        LOG_MAX_BYTES,
        LOG_BACKUP_COUNT,
    )


if __name__ == "__main__":
    main()
