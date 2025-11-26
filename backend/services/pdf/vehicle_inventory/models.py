"""Data models for the vehicle inventory PDF renderer."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from pydantic import BaseModel


class VehiclePdfOptions(BaseModel):
    """Options provided by the frontend to customize the PDF output."""

    pointer_mode_enabled: bool = False
    hide_edit_buttons: bool = False
    theme: str = "default"
    include_footer: bool = True
    include_header: bool = True
    table_fallback: bool = False


@dataclass
class VehicleViewEntry:
    key: str
    name: str
    reference: str
    quantity: int
    components: list[str]
    category_id: int | None
    category_name: str | None
    view_name: str
    bubble_x: float | None
    bubble_y: float | None
    anchor_x: float | None
    anchor_y: float | None
    icon_path: Path | None


@dataclass
class VehicleView:
    category_id: int | None
    category_name: str
    view_name: str
    background_path: Path | None
    background_photo_id: int | None
    entries: list[VehicleViewEntry]
    pointer_mode: bool
    hide_edit_buttons: bool
    has_positions: bool


@dataclass
class BubbleGeometry:
    x: float
    y: float
    width: float
    height: float

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.width, self.height


@dataclass
class BubblePlacement:
    entry: VehicleViewEntry
    geometry: BubbleGeometry
    anchor_x: float
    anchor_y: float
    pointer_mode_enabled: bool


@dataclass
class PageMetadata:
    kind: str
    view: VehicleView
    pointer_options: VehiclePdfOptions
    entries: Sequence[VehicleViewEntry] | None = None
    orientation: str = "landscape"


@dataclass
class DocumentPlan:
    pages: list[PageMetadata] = field(default_factory=list)
    generated_at: datetime | None = None

    def __iter__(self):
        return iter(self.pages)

    def __len__(self):
        return len(self.pages)

    def add(self, page: PageMetadata) -> None:
        self.pages.append(page)
