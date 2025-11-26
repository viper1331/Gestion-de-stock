"""Bubble placement algorithm for vehicle inventory PDFs."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from backend.core import models
from .utils import VehiclePdfOptions, VehicleViewEntry


@dataclass
class BubblePlacement:
    entry: VehicleViewEntry
    x: float
    y: float
    radius: float


class BubbleLayoutEngine:
    """Places bubbles while minimizing collisions."""

    def __init__(self, *, options: VehiclePdfOptions, bubble_radius: float = 24.0):
        self.options = options
        self.bubble_radius = bubble_radius
        self.padding = 4.0

    def place(self, entries: Sequence[VehicleViewEntry], *, width: float, height: float) -> list[BubblePlacement]:
        placed: list[BubblePlacement] = []
        grid_step = max(self.bubble_radius + self.padding, 8)

        for entry in entries:
            anchor_x = (entry.anchor_x or 0.5) * width
            anchor_y = (entry.anchor_y or 0.5) * height
            candidate = self._find_best_position(anchor_x, anchor_y, placed, width, height, grid_step)
            if candidate is None:
                if self.options.table_fallback:
                    break
                candidate = (min(max(anchor_x, self.bubble_radius), width - self.bubble_radius),
                             min(max(anchor_y, self.bubble_radius), height - self.bubble_radius))
            placed.append(BubblePlacement(entry=entry, x=candidate[0], y=candidate[1], radius=self.bubble_radius))
        return placed

    def _find_best_position(
        self,
        anchor_x: float,
        anchor_y: float,
        placed: Iterable[BubblePlacement],
        width: float,
        height: float,
        step: float,
    ) -> tuple[float, float] | None:
        best_score = -math.inf
        best: tuple[float, float] | None = None

        max_radius = max(width, height)
        radius = step
        max_attempts = 80
        attempts = 0
        while radius < max_radius and attempts < max_attempts:
            for angle in self._spiral_angles():
                attempts += 1
                x = anchor_x + radius * math.cos(angle)
                y = anchor_y + radius * math.sin(angle)
                if not self._within_bounds(x, y, width, height):
                    continue
                if self._collides(x, y, placed):
                    continue
                score = self._score(x, y, anchor_x, anchor_y, width, height)
                if score > best_score:
                    best_score = score
                    best = (x, y)
            radius += step
        return best

    def _spiral_angles(self) -> Iterable[float]:
        for k in range(0, 360, 6):
            yield math.radians(k)

    def _within_bounds(self, x: float, y: float, width: float, height: float) -> bool:
        return (
            x > self.bubble_radius and x < width - self.bubble_radius and y > self.bubble_radius and y < height - self.bubble_radius
        )

    def _collides(self, x: float, y: float, placed: Iterable[BubblePlacement]) -> bool:
        for bubble in placed:
            dx = x - bubble.x
            dy = y - bubble.y
            distance = math.hypot(dx, dy)
            if distance < (self.bubble_radius + bubble.radius + self.padding):
                return True
        return False

    def _score(self, x: float, y: float, anchor_x: float, anchor_y: float, width: float, height: float) -> float:
        dist = math.hypot(x - anchor_x, y - anchor_y)
        edge_distance = min(x, y, width - x, height - y)
        center_bias = max(width, height) - dist
        return center_bias + edge_distance * 0.5


def compute_bubble_layout(
    entries: Sequence[VehicleViewEntry], *, width: float, height: float, options: VehiclePdfOptions
) -> list[BubblePlacement]:
    engine = BubbleLayoutEngine(options=options)
    return engine.place(entries, width=width, height=height)
