"""Async job management for vehicle inventory PDF exports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import tempfile
import uuid
from typing import Callable, Iterable

import asyncio

logger = logging.getLogger(__name__)

JOB_TTL = timedelta(minutes=30)


@dataclass
class PdfExportJob:
    job_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    filename: str | None = None
    result_path: Path | None = None
    error: str | None = None


_jobs: dict[str, PdfExportJob] = {}


def _jobs_dir() -> Path:
    root = Path(tempfile.gettempdir()) / "vehicle_inventory_pdf_jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_jobs() -> None:
    cutoff = _now() - JOB_TTL
    for job_id in list(_jobs):
        job = _jobs[job_id]
        if job.updated_at < cutoff:
            if job.result_path and job.result_path.exists():
                try:
                    job.result_path.unlink()
                except OSError:
                    pass
            _jobs.pop(job_id, None)


def create_job(filename: str | None = None) -> PdfExportJob:
    _cleanup_jobs()
    job_id = uuid.uuid4().hex
    now = _now()
    job = PdfExportJob(job_id=job_id, status="pending", created_at=now, updated_at=now, filename=filename)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> PdfExportJob | None:
    _cleanup_jobs()
    return _jobs.get(job_id)


def _update_job(job: PdfExportJob, *, status: str | None = None, error: str | None = None, result_path: Path | None = None) -> None:
    job.status = status or job.status
    job.error = error
    job.result_path = result_path or job.result_path
    job.updated_at = _now()


async def run_job(job: PdfExportJob, worker: Callable[[], bytes]) -> None:
    _update_job(job, status="running")
    try:
        pdf_bytes = await asyncio.to_thread(worker)
    except Exception as exc:  # noqa: BLE001 - log and persist error
        logger.exception("[vehicle_inventory_pdf] export failed job_id=%s", job.job_id)
        _update_job(job, status="failed", error=str(exc))
        return

    result_path = _jobs_dir() / f"{job.job_id}.pdf"
    try:
        result_path.write_bytes(pdf_bytes)
    except OSError as exc:
        logger.exception("[vehicle_inventory_pdf] export write failed job_id=%s", job.job_id)
        _update_job(job, status="failed", error=str(exc))
        return
    _update_job(job, status="completed", result_path=result_path)
    logger.info("[vehicle_inventory_pdf] export completed job_id=%s size_bytes=%s", job.job_id, result_path.stat().st_size)


def launch_job(job: PdfExportJob, worker: Callable[[], bytes]) -> None:
    asyncio.create_task(run_job(job, worker))
