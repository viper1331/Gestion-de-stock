"""HTML renderer for vehicle inventory PDFs."""
from __future__ import annotations

import base64
import html
import mimetypes
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm

from backend.core import models
from .image_cache import DEFAULT_IMAGE_DPI, DEFAULT_IMAGE_QUALITY, preprocess_image, target_pixels_for_bounds
from .models import VehiclePdfOptions, VehicleView, VehicleViewEntry
from .utils import build_vehicle_entries, clamp, format_date

import logging

logger = logging.getLogger(__name__)

VEHICLE_TYPE_LABELS = {
    "incendie": "Incendie",
    "secours_a_personne": "Secours à personne",
}


def render_vehicle_inventory_pdf_html_sync(
    *,
    categories: Iterable[models.Category],
    items: Iterable[models.Item],
    generated_at: datetime,
    pointer_targets: dict[str, models.PointerTarget] | None,
    options: VehiclePdfOptions,
    media_root: Path | None = None,
) -> bytes:
    start_time = time.perf_counter()
    views = build_vehicle_entries(
        categories=categories,
        items=items,
        pointer_targets=pointer_targets,
        media_root=media_root,
    )
    if not views:
        raise ValueError("Aucune page générée pour l'inventaire véhicule")

    build_start = time.perf_counter()
    html_content = _build_html(
        views=views,
        pointer_targets=pointer_targets or {},
        generated_at=generated_at,
        options=options,
    )
    build_end = time.perf_counter()
    pdf_bytes = _render_html_to_pdf(html_content)
    total_time = time.perf_counter()
    logger.info(
        "[vehicle_inventory_pdf] html_build_ms=%.2f html_render_ms=%.2f total_ms=%.2f size_bytes=%s",
        (build_end - build_start) * 1000,
        (total_time - build_end) * 1000,
        (total_time - start_time) * 1000,
        len(pdf_bytes),
    )
    return pdf_bytes


def render_vehicle_inventory_pdf_html(
    *,
    categories: Iterable[models.Category],
    items: Iterable[models.Item],
    generated_at: datetime,
    pointer_targets: dict[str, models.PointerTarget] | None,
    options: VehiclePdfOptions,
    media_root: Path | None = None,
) -> bytes:
    return render_vehicle_inventory_pdf_html_sync(
        categories=categories,
        items=items,
        generated_at=generated_at,
        pointer_targets=pointer_targets,
        options=options,
        media_root=media_root,
    )


def _build_html(
    *,
    views: list[VehicleView],
    pointer_targets: dict[str, models.PointerTarget],
    generated_at: datetime,
    options: VehiclePdfOptions,
) -> str:
    date_label = format_date(generated_at)
    total_pages = len(views)
    pages_markup: list[str] = []

    for index, view in enumerate(views, start=1):
        pointer_enabled = _resolve_pointer_mode(view, options)
        background_style = _background_style(view.background_path)
        vehicle_name = view.category_name or "Véhicule"
        vehicle_type = VEHICLE_TYPE_LABELS.get(view.vehicle_type or "")
        vehicle_meta = vehicle_type or ""

        markers = [
            _render_marker(entry, pointer_targets.get(entry.key), pointer_enabled)
            for entry in view.entries
        ]
        markers_markup = "\n".join(markers)
        empty_placeholder = (
            '<div class="board-empty">Glissez un équipement sur la photo pour enregistrer son emplacement.</div>'
            if not view.entries
            else ""
        )
        pages_markup.append(
            f"""
            <section class="page">
              <header class="page-header">
                <div>
                  <div class="module-title">Inventaire véhicules</div>
                  <div class="view-title">{html.escape(view.view_name)}</div>
                </div>
                <div class="vehicle-summary">
                  <div class="vehicle-name">{html.escape(vehicle_name)}</div>
                  {'<div class="vehicle-type">' + html.escape(vehicle_meta) + '</div>' if vehicle_meta else ''}
                </div>
              </header>
              <div class="board-wrapper">
                <div class="board" style="{background_style}">
                  <div class="board-overlay"></div>
                  {markers_markup}
                  {empty_placeholder}
                </div>
              </div>
              <footer class="page-footer">
                <span>Généré le {date_label} — Page {index}/{total_pages} — {html.escape(vehicle_name)}{(' — ' + html.escape(vehicle_meta)) if vehicle_meta else ''}</span>
              </footer>
            </section>
            """
        )

    font_face = _font_face_css()
    pages_html = "\n".join(pages_markup)
    return f"""
    <!doctype html>
    <html lang="fr">
      <head>
        <meta charset="utf-8" />
        <style>
          {font_face}
          @page {{
            size: A4 landscape;
            margin: 12mm;
          }}
          * {{
            box-sizing: border-box;
          }}
          html, body {{
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            font-family: "Inter", system-ui, sans-serif;
            color: #0f172a;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }}
          body {{
            background: #ffffff;
          }}
          .page {{
            width: 100%;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            gap: 12px;
            page-break-after: always;
          }}
          .page:last-child {{
            page-break-after: auto;
          }}
          .page-header {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 16px;
          }}
          .module-title {{
            font-size: 18px;
            font-weight: 600;
            color: #0f172a;
          }}
          .view-title {{
            margin-top: 4px;
            font-size: 13px;
            font-weight: 500;
            color: #64748b;
          }}
          .vehicle-summary {{
            text-align: right;
            font-size: 13px;
            font-weight: 600;
            color: #0f172a;
          }}
          .vehicle-type {{
            margin-top: 2px;
            font-size: 11px;
            font-weight: 500;
            color: #64748b;
          }}
          .board-wrapper {{
            flex: 1;
            display: flex;
          }}
          .board {{
            position: relative;
            flex: 1;
            border-radius: 18px;
            border: 1px solid #e2e8f0;
            background-color: #f1f5f9;
            overflow: hidden;
            min-height: 320px;
          }}
          .board-overlay {{
            position: absolute;
            inset: 0;
            background: linear-gradient(135deg, rgba(15,23,42,0.05), rgba(15,23,42,0.0) 45%, rgba(255,255,255,0.12));
            pointer-events: none;
          }}
          .board-empty {{
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            font-size: 13px;
            font-weight: 500;
            color: #475569;
            padding: 16px;
          }}
          .marker {{
            position: absolute;
            transform: translate(-50%, -50%);
            z-index: 3;
          }}
          .marker-card {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.9);
            font-size: 12px;
            font-weight: 500;
            color: #334155;
            box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.15), 0 2px 4px -2px rgba(15, 23, 42, 0.12);
            backdrop-filter: blur(4px);
            white-space: nowrap;
          }}
          .marker-card.pointer {{
            background: rgba(255, 255, 255, 0.95);
          }}
          .marker-image {{
            width: 40px;
            height: 40px;
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 0.6);
            object-fit: cover;
            box-shadow: 0 2px 4px rgba(15, 23, 42, 0.1);
          }}
          .marker-placeholder {{
            width: 40px;
            height: 40px;
            border-radius: 6px;
            border: 1px solid #e2e8f0;
            background: #f1f5f9;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 9px;
            font-weight: 600;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #64748b;
          }}
          .marker-name {{
            font-size: 12px;
            font-weight: 600;
            color: #334155;
          }}
          .marker-qty {{
            font-size: 10px;
            color: #64748b;
          }}
          .marker-lot {{
            margin-top: 4px;
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 2px 8px;
            font-size: 9px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            background: #dbeafe;
            color: #1d4ed8;
          }}
          .pointer-layer {{
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            z-index: 1;
            pointer-events: none;
          }}
          .pointer-point {{
            position: absolute;
            width: 10px;
            height: 10px;
            border-radius: 999px;
            border: 2px solid #ffffff;
            background: #3b82f6;
            box-shadow: 0 4px 6px rgba(15, 23, 42, 0.2);
            transform: translate(-50%, -50%);
            z-index: 2;
          }}
          .page-footer {{
            font-size: 10px;
            color: #64748b;
            text-align: right;
          }}
        </style>
      </head>
      <body>
        {pages_html}
      </body>
    </html>
    """


def _render_marker(
    entry: VehicleViewEntry,
    pointer_target: models.PointerTarget | None,
    pointer_mode_enabled: bool,
) -> str:
    card_x = clamp(entry.bubble_x if entry.bubble_x is not None else 0.5, 0, 1)
    card_y = clamp(entry.bubble_y if entry.bubble_y is not None else 0.5, 0, 1)
    anchor_x = clamp(pointer_target.x if pointer_target else card_x, 0, 1)
    anchor_y = clamp(pointer_target.y if pointer_target else card_y, 0, 1)
    has_pointer = pointer_mode_enabled and pointer_target is not None
    marker_id = re.sub(r"[^a-zA-Z0-9_-]", "-", entry.key)
    image_url = _encode_data_url(entry.icon_path)
    image_markup = (
        f'<img class="marker-image" src="{image_url}" alt="{html.escape(entry.name)}" />'
        if image_url
        else '<div class="marker-placeholder">N/A</div>'
    )
    lot_markup = (
        f'<div class="marker-lot">{html.escape(entry.lot_label)}</div>' if entry.lot_label else ""
    )
    pointer_svg = ""
    pointer_point = ""
    if has_pointer:
        pointer_svg = f"""
        <svg class="pointer-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <marker id="arrow-{marker_id}" viewBox="0 0 12 12" refX="6" refY="6" markerWidth="4" markerHeight="4" orient="auto">
              <path d="M0,0 L12,6 L0,12 Z" fill="rgba(59,130,246,0.85)" />
            </marker>
          </defs>
          <line
            x1="{card_x * 100:.2f}" y1="{card_y * 100:.2f}"
            x2="{anchor_x * 100:.2f}" y2="{anchor_y * 100:.2f}"
            stroke="rgba(255,255,255,0.85)" stroke-width="2.5" stroke-linecap="round"
          />
          <line
            x1="{card_x * 100:.2f}" y1="{card_y * 100:.2f}"
            x2="{anchor_x * 100:.2f}" y2="{anchor_y * 100:.2f}"
            stroke="rgba(59,130,246,0.85)" stroke-width="1.5" stroke-linecap="round"
            marker-end="url(#arrow-{marker_id})"
          />
        </svg>
        """
        pointer_point = (
            f'<span class="pointer-point" style="left: {anchor_x * 100:.2f}%; top: {anchor_y * 100:.2f}%;"></span>'
        )

    return f"""
      {pointer_svg}
      {pointer_point}
      <div class="marker" style="left: {card_x * 100:.2f}%; top: {card_y * 100:.2f}%;">
        <div class="marker-card{' pointer' if pointer_mode_enabled else ''}">
          {image_markup}
          <div>
            <div class="marker-name">{html.escape(entry.name)}</div>
            <div class="marker-qty">Qté : {entry.quantity}</div>
            {lot_markup}
          </div>
        </div>
      </div>
    """


def _background_style(background_path: Path | None) -> str:
    image_url = _encode_data_url(background_path, target_px=_background_target_px()) if background_path else None
    if image_url:
        return (
            f"background-image: url('{image_url}');"
            "background-size: contain;"
            "background-position: center;"
            "background-repeat: no-repeat;"
            "background-color: rgba(148,163,184,0.08);"
        )
    return (
        "background-image: "
        "linear-gradient(135deg, rgba(148,163,184,0.15) 25%, transparent 25%), "
        "linear-gradient(-135deg, rgba(148,163,184,0.15) 25%, transparent 25%), "
        "linear-gradient(135deg, transparent 75%, rgba(148,163,184,0.15) 75%), "
        "linear-gradient(-135deg, transparent 75%, rgba(148,163,184,0.15) 75%);"
        "background-size: 32px 32px;"
        "background-position: 0 0, 16px 0, 16px -16px, 0px 16px;"
        "background-color: rgba(148,163,184,0.08);"
    )


def _background_target_px() -> tuple[int, int]:
    page_width, page_height = landscape(A4)
    content_width = page_width - 2 * (12 * mm)
    content_height = page_height - 2 * (12 * mm)
    return target_pixels_for_bounds(content_width, content_height, dpi=DEFAULT_IMAGE_DPI)


def _encode_data_url(path: Path | None, *, target_px: tuple[int, int] | None = None) -> str | None:
    if not path or not path.exists():
        return None
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "application/octet-stream"
    source_path = path
    if target_px is not None:
        processed = preprocess_image(
            path,
            target_width_px=target_px[0],
            target_height_px=target_px[1],
            quality=DEFAULT_IMAGE_QUALITY,
        )
        source_path = processed.path
        mime_type = "image/jpeg"
    encoded = base64.b64encode(source_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _font_face_css() -> str:
    regular_font = Path("frontend/public/fonts/Inter-Regular.ttf")
    bold_font = Path("frontend/public/fonts/Inter-Bold.ttf")
    sources: list[str] = []
    if regular_font.exists():
        sources.append(
            f"@font-face {{ font-family: 'Inter'; src: url('{regular_font.resolve().as_uri()}'); font-weight: 400; }}"
        )
    if bold_font.exists():
        sources.append(
            f"@font-face {{ font-family: 'Inter'; src: url('{bold_font.resolve().as_uri()}'); font-weight: 600; }}"
        )
    return "\n".join(sources)


def _resolve_pointer_mode(view: VehicleView, options: VehiclePdfOptions) -> bool:
    if options.pointer_mode_by_view and view.view_name in options.pointer_mode_by_view:
        return bool(options.pointer_mode_by_view[view.view_name])
    return options.pointer_mode_enabled or view.pointer_mode


def _render_html_to_pdf(html_content: str) -> bytes:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - handled by caller
        raise RuntimeError("Playwright est requis pour générer le PDF HTML.") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")
        pdf_bytes = page.pdf(format="A4", landscape=True, print_background=True)
        browser.close()
    return pdf_bytes
