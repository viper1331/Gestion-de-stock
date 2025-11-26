"""Bubble rendering and placement for vehicle inventory PDFs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image
from reportlab.lib.utils import ImageReader

from .models import BubbleGeometry, BubblePlacement, VehicleViewEntry
from .style_engine import PdfStyleEngine
from .utils import clamp, clamp_ratio, ratio_to_coordinate

BUBBLE_PADDING = 10
BUBBLE_RADIUS = 12
BUBBLE_SHADOW_OFFSET = 1.5
ARROW_OFFSET_RANGE = (40, 120)
MIN_BUBBLE_MARGIN = 6


@dataclass
class BubbleMetrics:
    width: float = 180
    height: float = 86
    padding: float = 10


def _crop_icon(icon_path: Path) -> ImageReader | None:
    if not icon_path or not icon_path.exists():
        return None
    with Image.open(icon_path) as img:
        size = min(img.size)
        offset_x = (img.width - size) // 2
        offset_y = (img.height - size) // 2
        square = img.crop((offset_x, offset_y, offset_x + size, offset_y + size))
        return ImageReader(square)


def find_best_bubble_position(
    bubble_center: tuple[float, float],
    bubble_size: tuple[float, float],
    existing_bubbles: Sequence[BubbleGeometry],
    image_bounds: tuple[float, float, float, float],
) -> BubbleGeometry:
    """Place a bubble intelligently above the anchor without overlapping others."""

    target_x, target_y = bubble_center
    width, height = bubble_size
    bounds_x, bounds_y, bounds_w, bounds_h = image_bounds

    preferred_y = clamp(
        target_y + ARROW_OFFSET_RANGE[0],
        bounds_y + MIN_BUBBLE_MARGIN,
        bounds_y + bounds_h - height - MIN_BUBBLE_MARGIN,
    )
    max_y = clamp(
        target_y + ARROW_OFFSET_RANGE[1],
        bounds_y + MIN_BUBBLE_MARGIN,
        bounds_y + bounds_h - height - MIN_BUBBLE_MARGIN,
    )

    x = clamp(target_x - width / 2, bounds_x + MIN_BUBBLE_MARGIN, bounds_x + bounds_w - width - MIN_BUBBLE_MARGIN)
    step = height + MIN_BUBBLE_MARGIN
    offsets = [0]
    current = step
    while current <= (bounds_h + height):
        offsets.extend([current, -current])
        current += step

    horizontal_offsets = [
        0,
        width + MIN_BUBBLE_MARGIN,
        -(width + MIN_BUBBLE_MARGIN),
        2 * (width + MIN_BUBBLE_MARGIN),
        -2 * (width + MIN_BUBBLE_MARGIN),
    ]
    for delta in offsets:
        candidate_y = clamp(preferred_y + delta, bounds_y + MIN_BUBBLE_MARGIN, max_y)
        for h_delta in horizontal_offsets:
            candidate_x = clamp(x + h_delta, bounds_x + MIN_BUBBLE_MARGIN, bounds_x + bounds_w - width - MIN_BUBBLE_MARGIN)
            candidate = BubbleGeometry(x=candidate_x, y=candidate_y, width=width, height=height)
            if not any(_rects_overlap(candidate, other) for other in existing_bubbles):
                return candidate

    return BubbleGeometry(x=x, y=preferred_y, width=width, height=height)


def _rects_overlap(a: BubbleGeometry, b: BubbleGeometry) -> bool:
    ax, ay, aw, ah = a.rect
    bx, by, bw, bh = b.rect
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def _build_geometry(entry: VehicleViewEntry, bounds: tuple[float, float, float, float], metrics: BubbleMetrics) -> tuple[BubbleGeometry, tuple[float, float]]:
    x, y, width, height = bounds
    anchor_ratio_x = clamp_ratio(entry.anchor_x if entry.anchor_x is not None else entry.bubble_x)
    anchor_ratio_y = clamp_ratio(entry.anchor_y if entry.anchor_y is not None else entry.bubble_y)
    bubble_ratio_x = clamp_ratio(entry.bubble_x)
    bubble_ratio_y = clamp_ratio(entry.bubble_y)

    if anchor_ratio_x is None or anchor_ratio_y is None:
        anchor_ratio_x = anchor_ratio_y = 0.5
    if bubble_ratio_x is None or bubble_ratio_y is None:
        bubble_ratio_x = anchor_ratio_x
        bubble_ratio_y = anchor_ratio_y

    anchor_x = ratio_to_coordinate(anchor_ratio_x, x, width)
    anchor_y = ratio_to_coordinate(anchor_ratio_y, y, height)
    bubble_center_x = ratio_to_coordinate(bubble_ratio_x, x, width)
    bubble_center_y = ratio_to_coordinate(bubble_ratio_y, y, height)

    geometry = BubbleGeometry(
        x=bubble_center_x - metrics.width / 2,
        y=bubble_center_y - metrics.height / 2,
        width=metrics.width,
        height=metrics.height,
    )
    return geometry, (anchor_x, anchor_y)


def layout_bubbles(
    entries: Sequence[VehicleViewEntry],
    image_bounds: tuple[float, float, float, float],
    pointer_mode: bool,
    metrics: BubbleMetrics | None = None,
) -> list[BubblePlacement]:
    metrics = metrics or BubbleMetrics()
    placements: list[BubblePlacement] = []
    geometries: list[BubbleGeometry] = []

    for entry in entries:
        geometry, (anchor_x, anchor_y) = _build_geometry(entry, image_bounds, metrics)
        if pointer_mode:
            geometry = find_best_bubble_position((anchor_x, anchor_y + metrics.height / 4), (metrics.width, metrics.height), geometries, image_bounds)
        placements.append(
            BubblePlacement(
                entry=entry,
                geometry=geometry,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                pointer_mode_enabled=pointer_mode,
            )
        )
        geometries.append(geometry)

    return placements


def draw_point(canvas, x: float, y: float, style_engine: PdfStyleEngine) -> None:
    canvas.saveState()
    canvas.setFillColor(style_engine.color("point_fill"))
    canvas.setStrokeColor(style_engine.color("bubble_border"))
    canvas.setLineWidth(3)
    canvas.circle(x, y, 7, stroke=1, fill=1)
    canvas.restoreState()


def draw_arrow(canvas, bubble: BubblePlacement, style_engine: PdfStyleEngine) -> None:
    bx, by, bw, bh = bubble.geometry.rect
    center_x = bx + bw / 2
    center_y = by + bh / 2
    canvas.saveState()
    canvas.setStrokeColor(style_engine.color("accent"))
    canvas.setLineWidth(3)
    canvas.setLineCap(1)
    canvas.setStrokeAlpha(0.85)
    canvas.line(center_x, center_y, bubble.anchor_x, bubble.anchor_y)
    canvas.restoreState()


def _draw_icon(canvas, reader: ImageReader, bubble: BubblePlacement) -> float:
    bx, by, _, _ = bubble.geometry.rect
    size = 34
    padding = 12
    canvas.drawImage(
        reader,
        bx + padding,
        by + (bubble.geometry.height - size) / 2,
        width=size,
        height=size,
        mask="auto",
        preserveAspectRatio=True,
    )
    return size + padding + 4


def draw_single_bubble(canvas, bubble: BubblePlacement, style_engine: PdfStyleEngine, metrics: BubbleMetrics | None = None) -> None:
    metrics = metrics or BubbleMetrics()
    bx, by, bw, bh = bubble.geometry.rect
    canvas.saveState()
    canvas.setFillColor(style_engine.color("shadow"))
    canvas.setStrokeColor(style_engine.color("shadow"))
    canvas.roundRect(bx + BUBBLE_SHADOW_OFFSET, by - BUBBLE_SHADOW_OFFSET, bw, bh, radius=BUBBLE_RADIUS, stroke=0, fill=1)

    canvas.setFillColor(style_engine.color("bubble"))
    canvas.setStrokeColor(style_engine.color("bubble_border"))
    canvas.roundRect(bx, by, bw, bh, radius=BUBBLE_RADIUS, stroke=1, fill=1)

    icon_reader = _crop_icon(bubble.entry.icon_path)
    text_x = bx + metrics.padding
    if icon_reader:
        text_x += _draw_icon(canvas, icon_reader, bubble)

    name_font = style_engine.font("body")
    qty_font = style_engine.font("small")
    canvas.setFillColor(style_engine.color("text"))
    canvas.setFont(*name_font)
    canvas.drawString(text_x, by + bh - 18, bubble.entry.name[:48])

    canvas.setFillColor(style_engine.color("muted"))
    canvas.setFont(*qty_font)
    canvas.drawString(text_x, by + 18, bubble.entry.reference[:48])

    badge_width = 36
    badge_height = 18
    canvas.setFillColor(style_engine.color("accent"))
    canvas.setStrokeColor(style_engine.color("accent"))
    canvas.roundRect(
        bx + bw - badge_width - metrics.padding,
        by + bh - badge_height - metrics.padding,
        badge_width,
        badge_height,
        radius=6,
        stroke=0,
        fill=1,
    )
    canvas.setFillColor(style_engine.color("badge_text"))
    canvas.setFont(*qty_font)
    canvas.drawCentredString(
        bx + bw - badge_width / 2 - metrics.padding,
        by + bh - badge_height / 2 - metrics.padding / 2,
        str(bubble.entry.quantity),
    )
    canvas.restoreState()


def draw_bubbles(
    canvas,
    entries: Sequence[VehicleViewEntry],
    image_bounds: tuple[float, float, float, float],
    pointer_mode: bool,
    style_engine: PdfStyleEngine,
    metrics: BubbleMetrics | None = None,
) -> list[BubblePlacement]:
    metrics = metrics or BubbleMetrics()
    placements = layout_bubbles(entries, image_bounds, pointer_mode, metrics)
    for placement in placements:
        draw_single_bubble(canvas, placement, style_engine, metrics)
        if placement.pointer_mode_enabled:
            draw_arrow(canvas, placement, style_engine)
            draw_point(canvas, placement.anchor_x, placement.anchor_y, style_engine)
    return placements
