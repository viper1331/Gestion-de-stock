"""Bubble rendering and placement for vehicle inventory PDFs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from PIL import Image
from reportlab.lib.utils import ImageReader

from .style import PdfStyleEngine
from .utils import VehicleViewEntry

BUBBLE_WIDTH = 128  # points
BUBBLE_HEIGHT = 70  # points
BUBBLE_PADDING = 8
POINT_RADIUS = 4


@dataclass
class BubblePlacement:
    entry: VehicleViewEntry
    x: float
    y: float
    anchor_x: float
    anchor_y: float

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return self.x, self.y, BUBBLE_WIDTH, BUBBLE_HEIGHT


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _clamp_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return _clamp(value, 0.0, 1.0)


def _initial_positions(
    entries: Sequence[VehicleViewEntry],
    bounds: tuple[float, float, float, float],
    *,
    pointer_mode: bool,
) -> list[BubblePlacement]:
    x, y, width, height = bounds
    placements: list[BubblePlacement] = []
    for entry in entries:
        anchor_ratio_x = _clamp_ratio(entry.anchor_x if entry.anchor_x is not None else entry.bubble_x)
        anchor_ratio_y = _clamp_ratio(entry.anchor_y if entry.anchor_y is not None else entry.bubble_y)
        bubble_ratio_x = _clamp_ratio(entry.bubble_x if pointer_mode else anchor_ratio_x)
        bubble_ratio_y = _clamp_ratio(entry.bubble_y if pointer_mode else anchor_ratio_y)
        if anchor_ratio_x is None or anchor_ratio_y is None or bubble_ratio_x is None or bubble_ratio_y is None:
            anchor_ratio_x = anchor_ratio_y = 0.5
        anchor_x = x + anchor_ratio_x * width
        anchor_y = y + anchor_ratio_y * height
        bubble_x = x + bubble_ratio_x * width - BUBBLE_WIDTH / 2
        bubble_y = y + bubble_ratio_y * height - BUBBLE_HEIGHT / 2
        placements.append(
            BubblePlacement(
                entry=entry,
                x=bubble_x,
                y=bubble_y,
                anchor_x=x + anchor_ratio_x * width,
                anchor_y=y + anchor_ratio_y * height,
            )
        )
    return placements


def _rects_overlap(a: BubblePlacement, b: BubblePlacement) -> bool:
    ax, ay, aw, ah = a.rect
    bx, by, bw, bh = b.rect
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def resolve_collisions(
    placements: list[BubblePlacement],
    bounds: tuple[float, float, float, float],
) -> list[BubblePlacement]:
    x, y, width, height = bounds
    max_x = x + width - BUBBLE_WIDTH - BUBBLE_PADDING
    min_x = x + BUBBLE_PADDING
    max_y = y + height - BUBBLE_HEIGHT - BUBBLE_PADDING
    min_y = y + BUBBLE_PADDING

    ordered = sorted(placements, key=lambda p: p.anchor_y)
    placed: list[BubblePlacement] = []
    for placement in ordered:
        px = _clamp(placement.x, min_x, max_x)
        py = _clamp(placement.y, min_y, max_y)
        candidate = BubblePlacement(
            entry=placement.entry,
            x=px,
            y=py,
            anchor_x=placement.anchor_x,
            anchor_y=placement.anchor_y,
        )

        step = BUBBLE_HEIGHT + BUBBLE_PADDING
        attempts = 0
        while any(_rects_overlap(candidate, other) for other in placed) and attempts < 40:
            attempts += 1
            candidate = BubblePlacement(
                entry=candidate.entry,
                x=candidate.x,
                y=_clamp(candidate.y + step, min_y, max_y),
                anchor_x=candidate.anchor_x,
                anchor_y=candidate.anchor_y,
            )
            if candidate.y >= max_y:
                candidate = BubblePlacement(
                    entry=candidate.entry,
                    x=candidate.x,
                    y=_clamp(py - step * attempts, min_y, max_y),
                    anchor_x=candidate.anchor_x,
                    anchor_y=candidate.anchor_y,
                )
        placed.append(candidate)
    return placed


def _crop_icon(icon_path: Path) -> ImageReader | None:
    if not icon_path.exists():
        return None
    with Image.open(icon_path) as img:
        size = min(img.size)
        offset_x = (img.width - size) // 2
        offset_y = (img.height - size) // 2
        square = img.crop((offset_x, offset_y, offset_x + size, offset_y + size))
        return ImageReader(square)


def draw_point(canvas, x: float, y: float, style_engine: PdfStyleEngine) -> None:
    canvas.saveState()
    canvas.setFillColor(style_engine.color("point_fill"))
    canvas.setStrokeColor(style_engine.color("accent"))
    canvas.setLineWidth(3)
    canvas.circle(x, y, POINT_RADIUS, stroke=1, fill=1)
    canvas.restoreState()


def draw_arrow(canvas, bubble: BubblePlacement, style_engine: PdfStyleEngine) -> None:
    bx, by, bw, bh = bubble.rect
    center_x = bx + bw / 2
    center_y = by + bh / 2
    canvas.saveState()
    canvas.setStrokeColor(style_engine.color("accent"))
    canvas.setLineWidth(3)
    canvas.line(center_x, center_y, bubble.anchor_x, bubble.anchor_y)
    canvas.restoreState()


def _draw_icon(canvas, reader: ImageReader, bubble: BubblePlacement) -> None:
    bx, by, _, _ = bubble.rect
    size = 30
    padding = 10
    canvas.drawImage(
        reader,
        bx + padding,
        by + (BUBBLE_HEIGHT - size) / 2,
        width=size,
        height=size,
        mask="auto",
        preserveAspectRatio=True,
    )


def draw_single_bubble(canvas, bubble: BubblePlacement, style_engine: PdfStyleEngine) -> None:
    bx, by, bw, bh = bubble.rect
    canvas.saveState()
    canvas.setFillColor(style_engine.color("shadow"))
    canvas.setStrokeColor(style_engine.color("shadow"))
    canvas.roundRect(bx - 1, by - 1, bw + 2, bh + 2, radius=6, stroke=0, fill=1)

    canvas.setFillColor(style_engine.color("bubble"))
    canvas.setStrokeColor(style_engine.color("bubble_border"))
    canvas.roundRect(bx, by, bw, bh, radius=6, stroke=1, fill=1)

    icon_reader = _crop_icon(bubble.entry.icon_path) if bubble.entry.icon_path else None
    text_x = bx + 12
    if icon_reader:
        _draw_icon(canvas, icon_reader, bubble)
        text_x += 42

    name_font = style_engine.font("body")
    qty_font = style_engine.font("small")
    canvas.setFillColor(style_engine.color("text"))
    canvas.setFont(*name_font)
    canvas.drawString(text_x, by + bh - 18, bubble.entry.name[:32])

    canvas.setFillColor(style_engine.color("muted"))
    canvas.setFont(*qty_font)
    canvas.drawString(text_x, by + 18, bubble.entry.reference[:36])

    badge_padding_x = 10
    badge_width = 32
    badge_height = 18
    canvas.setFillColor(style_engine.color("accent"))
    canvas.setStrokeColor(style_engine.color("accent"))
    canvas.roundRect(
        bx + bw - badge_width - badge_padding_x,
        by + bh - badge_height - 10,
        badge_width,
        badge_height,
        radius=4,
        stroke=0,
        fill=1,
    )
    canvas.setFillColor(style_engine.color("badge_text"))
    canvas.setFont(*qty_font)
    canvas.drawCentredString(
        bx + bw - badge_width / 2 - badge_padding_x,
        by + bh - badge_height + 2 - 10,
        str(bubble.entry.quantity),
    )
    canvas.restoreState()


def draw_bubbles(
    canvas,
    entries: Sequence[VehicleViewEntry],
    image_bounds: tuple[float, float, float, float],
    pointer_mode: bool,
    style_engine: PdfStyleEngine,
) -> None:
    placements = _initial_positions(entries, image_bounds, pointer_mode=pointer_mode)
    placements = resolve_collisions(placements, image_bounds)

    for placement in placements:
        draw_single_bubble(canvas, placement, style_engine)
        if pointer_mode:
            draw_arrow(canvas, placement, style_engine)
            draw_point(canvas, placement.anchor_x, placement.anchor_y, style_engine)
