from __future__ import annotations

import io

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from backend.api.admin import require_admin
from backend.core.pdf_config_models import PdfConfigMeta, PdfExportConfig
from backend.services.pdf_config import (
    get_pdf_export_config,
    get_pdf_config_meta,
    render_preview_pdf,
    resolve_pdf_config,
    save_pdf_export_config,
)

router = APIRouter()


class PdfPreviewRequest(BaseModel):
    module: str
    preset: str | None = None
    config: PdfExportConfig | None = None


@router.get("/pdf-config", response_model=PdfExportConfig)
def fetch_pdf_config(_: object = Depends(require_admin)) -> PdfExportConfig:
    return get_pdf_export_config()


@router.post("/pdf-config", response_model=PdfExportConfig)
def update_pdf_config(payload: PdfExportConfig, _: object = Depends(require_admin)) -> PdfExportConfig:
    return save_pdf_export_config(payload)


@router.get("/pdf-config/preview")
def preview_pdf_config(
    module: str = Query(...),
    preset: str | None = Query(None),
    _: object = Depends(require_admin),
):
    resolved = resolve_pdf_config(module, preset)
    pdf_bytes = render_preview_pdf(resolved)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf")


@router.post("/pdf-config/preview")
def preview_pdf_config_draft(payload: PdfPreviewRequest, _: object = Depends(require_admin)):
    resolved = resolve_pdf_config(payload.module, payload.preset, config=payload.config)
    pdf_bytes = render_preview_pdf(resolved)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf")


@router.get("/pdf-config/meta", response_model=PdfConfigMeta)
def pdf_config_meta(_: object = Depends(require_admin)) -> PdfConfigMeta:
    return PdfConfigMeta.model_validate(get_pdf_config_meta())
