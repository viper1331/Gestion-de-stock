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

BUBBLE_PADDING = 12
BUBBLE_RADIUS = 12
BUBBLE_SHADOW_OFFSET = 4
ARROW_OFFSET_RANGE = (40, 120)
MIN_BUBBLE_MARGIN = 10


@dataclass
class BubbleMetrics:
    width: float = 220
    height: float = 78
    padding: float = 14


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
    max_y = bounds_y + bounds_h - height - MIN_BUBBLE_MARGIN

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


def _build_anchor(entry: VehicleViewEntry, bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, width, height = bounds
    anchor_ratio_x = clamp_ratio(entry.anchor_x if entry.anchor_x is not None else entry.bubble_x)
    anchor_ratio_y = clamp_ratio(entry.anchor_y if entry.anchor_y is not None else entry.bubble_y)

    if anchor_ratio_x is None or anchor_ratio_y is None:
        anchor_ratio_x = anchor_ratio_y = 0.5

    # Invert the Y ratio because the PDF coordinate system starts from the
    # bottom while the stored ratios are expressed from the top of the image.
    anchor_ratio_y = 1 - anchor_ratio_y

    anchor_x = ratio_to_coordinate(anchor_ratio_x, x, width)
    anchor_y = ratio_to_coordinate(anchor_ratio_y, y, height)
    return anchor_x, anchor_y


def _choose_side(anchor_x: float, anchor_y: float, image_bounds: tuple[float, float, float, float]) -> str:
    img_x, img_y, img_w, img_h = image_bounds
    distances = {
        "left": anchor_x - img_x,
        "right": img_x + img_w - anchor_x,
        "bottom": anchor_y - img_y,
        "top": img_y + img_h - anchor_y,
    }
    return min(distances, key=distances.get)


def _place_vertical(
    items: list[tuple[VehicleViewEntry, float, float]],
    *,
    base_x: float,
    container_bounds: tuple[float, float, float, float],
    metrics: BubbleMetrics,
    pointer_mode: bool,
) -> list[BubblePlacement]:
    placements: list[BubblePlacement] = []
    panel_x, panel_y, panel_w, panel_h = container_bounds
    min_y = panel_y + MIN_BUBBLE_MARGIN
    max_y = panel_y + panel_h - metrics.height - MIN_BUBBLE_MARGIN
    base_x = clamp(base_x, panel_x + MIN_BUBBLE_MARGIN, panel_x + panel_w - metrics.width - MIN_BUBBLE_MARGIN)
    items.sort(key=lambda item: item[2])
    current_y = None

    for entry, anchor_x, anchor_y in items:
        target_y = clamp(anchor_y - metrics.height / 2, min_y, max_y)
        if current_y is not None and target_y < current_y + metrics.height + MIN_BUBBLE_MARGIN:
            target_y = current_y + metrics.height + MIN_BUBBLE_MARGIN
            target_y = clamp(target_y, min_y, max_y)

        geometry = BubbleGeometry(x=base_x, y=target_y, width=metrics.width, height=metrics.height)
        placements.append(
            BubblePlacement(
                entry=entry,
                geometry=geometry,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                pointer_mode_enabled=pointer_mode,
            )
        )
        current_y = geometry.y

    return placements


def _place_horizontal(
    items: list[tuple[VehicleViewEntry, float, float]],
    *,
    base_y: float,
    container_bounds: tuple[float, float, float, float],
    metrics: BubbleMetrics,
    pointer_mode: bool,
) -> list[BubblePlacement]:
    placements: list[BubblePlacement] = []
    panel_x, panel_y, panel_w, panel_h = container_bounds
    min_x = panel_x + MIN_BUBBLE_MARGIN
    max_x = panel_x + panel_w - metrics.width - MIN_BUBBLE_MARGIN
    base_y = clamp(base_y, panel_y + MIN_BUBBLE_MARGIN, panel_y + panel_h - metrics.height - MIN_BUBBLE_MARGIN)
    items.sort(key=lambda item: item[1])
    current_x = None

    for entry, anchor_x, anchor_y in items:
        target_x = clamp(anchor_x - metrics.width / 2, min_x, max_x)
        if current_x is not None and target_x < current_x + metrics.width + MIN_BUBBLE_MARGIN:
            target_x = current_x + metrics.width + MIN_BUBBLE_MARGIN
            target_x = clamp(target_x, min_x, max_x)

        geometry = BubbleGeometry(x=target_x, y=base_y, width=metrics.width, height=metrics.height)
        placements.append(
            BubblePlacement(
                entry=entry,
                geometry=geometry,
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                pointer_mode_enabled=pointer_mode,
            )
        )
        current_x = geometry.x

    return placements


def layout_bubbles(
    entries: Sequence[VehicleViewEntry],
    image_bounds: tuple[float, float, float, float],
    panel_bounds: tuple[float, float, float, float] | None = None,
    metrics: BubbleMetrics | None = None,
    *,
    pointer_mode: bool = True,
) -> list[BubblePlacement]:
    metrics = metrics or BubbleMetrics(width=180, height=70) if pointer_mode else metrics or BubbleMetrics()
    panel_bounds = panel_bounds or image_bounds

    placements: list[BubblePlacement] = []

    if pointer_mode:
        anchored_entries = [
            (entry, *_build_anchor(entry, image_bounds))
            for entry in entries
        ]
        anchored_entries.sort(key=lambda item: (-item[2], item[1]))

        for entry, anchor_x, anchor_y in anchored_entries:
            geometry = find_best_bubble_position(
                (anchor_x, anchor_y),
                (metrics.width, metrics.height),
                [placement.geometry for placement in placements],
                panel_bounds,
            )
            placements.append(
                BubblePlacement(
                    entry=entry,
                    geometry=geometry,
                    anchor_x=anchor_x,
                    anchor_y=anchor_y,
                    pointer_mode_enabled=True,
                )
            )

        for _ in range(len(placements)):
            adjusted = False
            for idx, placement in enumerate(placements):
                others = [p.geometry for j, p in enumerate(placements) if j != idx]
                if any(_rects_overlap(placement.geometry, other) for other in others):
                    new_geometry = find_best_bubble_position(
                        (placement.anchor_x, placement.anchor_y),
                        (metrics.width, metrics.height),
                        others,
                        panel_bounds,
                    )
                    placements[idx] = BubblePlacement(
                        entry=placement.entry,
                        geometry=new_geometry,
                        anchor_x=placement.anchor_x,
                        anchor_y=placement.anchor_y,
                        pointer_mode_enabled=True,
                    )
                    adjusted = True
            if not adjusted:
                break
        return placements

    left: list[tuple[VehicleViewEntry, float, float]] = []
    right: list[tuple[VehicleViewEntry, float, float]] = []
    top: list[tuple[VehicleViewEntry, float, float]] = []
    bottom: list[tuple[VehicleViewEntry, float, float]] = []

    img_x, img_y, img_w, img_h = image_bounds
    card_gap = 26

    for entry in entries:
        anchor_x, anchor_y = _build_anchor(entry, image_bounds)
        side = _choose_side(anchor_x, anchor_y, image_bounds)
        if side == "left":
            left.append((entry, anchor_x, anchor_y))
        elif side == "right":
            right.append((entry, anchor_x, anchor_y))
        elif side == "top":
            top.append((entry, anchor_x, anchor_y))
        else:
            bottom.append((entry, anchor_x, anchor_y))

    placements.extend(
        _place_vertical(
            left,
            base_x=img_x - metrics.width - card_gap,
            container_bounds=panel_bounds,
            metrics=metrics,
            pointer_mode=pointer_mode,
        )
    )
    placements.extend(
        _place_vertical(
            right,
            base_x=img_x + img_w + card_gap,
            container_bounds=panel_bounds,
            metrics=metrics,
            pointer_mode=pointer_mode,
        )
    )
    placements.extend(
        _place_horizontal(
            top,
            base_y=img_y + img_h + card_gap,
            container_bounds=panel_bounds,
            metrics=metrics,
            pointer_mode=pointer_mode,
        )
    )
    placements.extend(
        _place_horizontal(
            bottom,
            base_y=img_y - metrics.height - card_gap,
            container_bounds=panel_bounds,
            metrics=metrics,
            pointer_mode=pointer_mode,
        )
    )

    return placements


def draw_point(canvas, x: float, y: float, style_engine: PdfStyleEngine) -> None:
    canvas.saveState()
    canvas.setFillColor(style_engine.color("point_fill"))
    canvas.setStrokeColor(style_engine.color("bubble_border"))
    canvas.setLineWidth(3)
    canvas.circle(x, y, 7, stroke=1, fill=1)
    canvas.restoreState()


def _arrow_start(bubble: BubblePlacement) -> tuple[float, float]:
    bx, by, bw, bh = bubble.geometry.rect
    if bubble.anchor_x >= bx + bw:
        return bx + bw, by + 8
    if bubble.anchor_x <= bx:
        return bx, by + 8
    if bubble.anchor_y >= by + bh:
        return bx + bw / 2, by + bh
    return bx + bw / 2, by


def draw_arrow(canvas, bubble: BubblePlacement, style_engine: PdfStyleEngine) -> None:
    start_x, start_y = _arrow_start(bubble)
    canvas.saveState()
    canvas.setLineCap(1)

    canvas.setStrokeColor(style_engine.color("muted"))
    canvas.setLineWidth(5)
    canvas.setStrokeAlpha(0.45)
    canvas.line(start_x, start_y, bubble.anchor_x, bubble.anchor_y)

    canvas.setStrokeColor(style_engine.color("accent"))
    canvas.setLineWidth(3)
    canvas.setStrokeAlpha(0.95)
    canvas.line(start_x, start_y, bubble.anchor_x, bubble.anchor_y)
    canvas.restoreState()


def _draw_icon(canvas, reader: ImageReader, bubble: BubblePlacement) -> float:
    bx, by, _, _ = bubble.geometry.rect
    size = 40
    padding = 16
    ix = bx + padding
    iy = by + (bubble.geometry.height - size) / 2
    path = canvas.beginPath()
    path.roundRect(ix, iy, size, size, radius=6)
    canvas.saveState()
    canvas.clipPath(path, stroke=0)
    canvas.drawImage(
        reader,
        ix,
        iy,
        width=size,
        height=size,
        mask="auto",
        preserveAspectRatio=True,
    )
    canvas.restoreState()
    return size + padding + 6


def draw_single_bubble(canvas, bubble: BubblePlacement, style_engine: PdfStyleEngine, metrics: BubbleMetrics | None = None) -> None:
    metrics = metrics or BubbleMetrics()
    bx, by, bw, bh = bubble.geometry.rect
    canvas.saveState()
    canvas.setFillColor(style_engine.color("shadow"))
    canvas.setStrokeColor(style_engine.color("shadow"))
    canvas.roundRect(bx + BUBBLE_SHADOW_OFFSET, by - BUBBLE_SHADOW_OFFSET, bw, bh, radius=BUBBLE_RADIUS, stroke=0, fill=1)

    canvas.setFillColor(style_engine.color("bubble"))
    canvas.setStrokeColor(style_engine.color("bubble_border"))
    canvas.roundRect(bx, by, bw, bh, radius=BUBBLE_RADIUS, stroke=0, fill=1)

    icon_reader = _crop_icon(bubble.entry.icon_path)
    text_x = bx + metrics.padding
    if icon_reader:
        text_x += _draw_icon(canvas, icon_reader, bubble)

    name_font_family, _ = style_engine.font("title")
    name_size = 13
    qty_font = style_engine.font("small")

    canvas.setFillColor(style_engine.color("text"))
    canvas.setFont(name_font_family, name_size)
    canvas.drawString(text_x, by + bh - 22, bubble.entry.name[:64])

    canvas.setFillColor(style_engine.color("muted"))
    canvas.setFont(*qty_font)
    canvas.drawString(text_x, by + 16, f"Qte : {bubble.entry.quantity}")
    canvas.restoreState()


def draw_bubbles(
    canvas,
    entries: Sequence[VehicleViewEntry],
    image_bounds: tuple[float, float, float, float],
    panel_bounds: tuple[float, float, float, float],
    style_engine: PdfStyleEngine,
    metrics: BubbleMetrics | None = None,
    *,
    pointer_mode: bool = True,
) -> list[BubblePlacement]:
    metrics = metrics or BubbleMetrics()
    placements = layout_bubbles(entries, image_bounds, panel_bounds, metrics, pointer_mode=pointer_mode)
    for placement in placements:
        draw_single_bubble(canvas, placement, style_engine, metrics)
        if placement.pointer_mode_enabled:
            draw_arrow(canvas, placement, style_engine)
            draw_point(canvas, placement.anchor_x, placement.anchor_y, style_engine)
    return placements
