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
import threading

logger = logging.getLogger(__name__)

JOB_TTL = timedelta(minutes=30)


@dataclass
class PdfExportJob:
    job_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    filename: str | None = None
    result_path: Path | None = None
    pdf_bytes: bytes | None = None
    content_type: str | None = None
    error: str | None = None
    progress_step: str | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    progress_percent: float | None = None
    cancel_requested: bool = False


class PdfExportCancelled(Exception):
    """Raised when a PDF export job is cancelled."""


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
    job = PdfExportJob(job_id=job_id, status="queued", created_at=now, updated_at=now, filename=filename)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> PdfExportJob | None:
    _cleanup_jobs()
    return _jobs.get(job_id)


def _update_job(
    job: PdfExportJob,
    *,
    status: str | None = None,
    error: str | None = None,
    result_path: Path | None = None,
    pdf_bytes: bytes | None = None,
    content_type: str | None = None,
    progress_step: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
) -> None:
    job.status = status or job.status
    job.error = error
    job.result_path = result_path or job.result_path
    if pdf_bytes is not None:
        job.pdf_bytes = pdf_bytes
    if content_type is not None:
        job.content_type = content_type
    if progress_step is not None:
        job.progress_step = progress_step
    if progress_current is not None:
        job.progress_current = progress_current
    if progress_total is not None:
        job.progress_total = progress_total
    if job.progress_total and job.progress_current is not None:
        job.progress_percent = (job.progress_current / job.progress_total) * 100
    job.updated_at = _now()


def request_cancel(job: PdfExportJob) -> None:
    job.cancel_requested = True
    if job.status == "queued":
        _update_job(job, status="cancelled", error="Export annulé.")
    else:
        _update_job(job)


def update_progress(job: PdfExportJob, *, step: str, current: int | None = None, total: int | None = None) -> None:
    _update_job(job, progress_step=step, progress_current=current, progress_total=total)


def mark_error(job: PdfExportJob, message: str) -> None:
    _update_job(job, status="error", error=message)


def ensure_not_cancelled(job: PdfExportJob) -> None:
    if job.cancel_requested:
        raise PdfExportCancelled("Export annulé.")


def _persist_result(job: PdfExportJob, pdf_bytes: bytes, *, store_bytes: bool, write_file: bool) -> None:
    result_path = None
    if write_file:
        result_path = _jobs_dir() / f"{job.job_id}.pdf"
        try:
            result_path.write_bytes(pdf_bytes)
        except OSError as exc:
            logger.exception("[vehicle_inventory_pdf] export write failed job_id=%s", job.job_id)
            _update_job(job, status="error", error=str(exc))
            return
    job.finished_at = _now()
    _update_job(
        job,
        status="done",
        result_path=result_path,
        pdf_bytes=pdf_bytes if store_bytes else None,
        content_type="application/pdf",
    )
    if result_path:
        logger.info(
            "[vehicle_inventory_pdf] export completed job_id=%s size_bytes=%s",
            job.job_id,
            result_path.stat().st_size,
        )
    else:
        logger.info(
            "[vehicle_inventory_pdf] export completed job_id=%s size_bytes=%s",
            job.job_id,
            len(pdf_bytes),
        )


async def run_job(job: PdfExportJob, worker: Callable[[], bytes]) -> None:
    if job.cancel_requested:
        _update_job(job, status="cancelled", error="Export annulé.")
        return
    job.started_at = _now()
    _update_job(job, status="processing")
    try:
        pdf_bytes = await asyncio.to_thread(worker)
        if job.cancel_requested:
            _update_job(job, status="cancelled", error="Export annulé.")
            return
    except PdfExportCancelled:
        _update_job(job, status="cancelled", error="Export annulé.")
        return
    except Exception as exc:  # noqa: BLE001 - log and persist error
        logger.exception("[vehicle_inventory_pdf] export failed job_id=%s", job.job_id)
        _update_job(job, status="error", error=str(exc))
        return

    _persist_result(job, pdf_bytes, store_bytes=False, write_file=True)


def run_job_sync(job: PdfExportJob, worker: Callable[[], bytes]) -> None:
    if job.cancel_requested:
        _update_job(job, status="cancelled", error="Export annulé.")
        return
    job.started_at = _now()
    _update_job(job, status="processing")
    try:
        pdf_bytes = worker()
        if job.cancel_requested:
            _update_job(job, status="cancelled", error="Export annulé.")
            return
    except PdfExportCancelled:
        _update_job(job, status="cancelled", error="Export annulé.")
        return
    except Exception as exc:  # noqa: BLE001 - log and persist error
        logger.exception("[vehicle_inventory_pdf] export failed job_id=%s", job.job_id)
        _update_job(job, status="error", error=str(exc))
        return
    _persist_result(job, pdf_bytes, store_bytes=True, write_file=False)


def launch_job(job: PdfExportJob, worker: Callable[[], bytes]) -> None:
    def _runner() -> None:
        asyncio.run(run_job(job, worker))

    threading.Thread(target=_runner, daemon=True).start()
