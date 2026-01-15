"""API endpoints for PDF Studio module registry."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.admin import require_admin
from backend.core.pdf_registry import pdf_studio_module_entries


router = APIRouter()


class PdfStudioModuleItem(BaseModel):
    key: str
    label: str


@router.get("/pdf-studio/modules", response_model=list[PdfStudioModuleItem])
def list_pdf_studio_modules(_: object = Depends(require_admin)) -> list[PdfStudioModuleItem]:
    return [PdfStudioModuleItem(**entry) for entry in pdf_studio_module_entries()]
