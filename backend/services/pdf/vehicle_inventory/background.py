"""Background rendering utilities for vehicle inventory PDFs."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader

from .style_engine import PdfStyleEngine
from .utils import clamp


class BackgroundInfo:
    def __init__(self, reader: ImageReader, width: float, height: float, orientation: str):
        self.reader = reader
        self.width = width
        self.height = height
        self.orientation = orientation


def _load_image(image_path: Path) -> tuple[Image.Image, str]:
    with Image.open(image_path) as img:
        oriented = ImageOps.exif_transpose(img)
        orientation = "landscape" if oriented.width >= oriented.height else "portrait"
        copy = oriented.copy()
    return copy, orientation


def prepare_background(image_path: Path) -> BackgroundInfo:
    if not image_path.exists():
        raise FileNotFoundError(f"Image introuvable: {image_path}")

    image, orientation = _load_image(image_path)
    image_format = image.format or "PNG"
    buffer = BytesIO()
    image.save(buffer, format=image_format)
    buffer.seek(0)
    reader = ImageReader(buffer)
    return BackgroundInfo(reader=reader, width=image.width, height=image.height, orientation=orientation)


def draw_background(
    canvas,
    background: BackgroundInfo,
    bounds: tuple[float, float, float, float],
    style_engine: PdfStyleEngine,
) -> tuple[float, float, float, float]:
    """Draw the background photo inside the provided bounds with overlay."""

    x, y, width, height = bounds
    scale = min(width / background.width, height / background.height)
    drawn_width = background.width * scale
    drawn_height = background.height * scale

    image_x = x + (width - drawn_width) / 2
    image_y = y + (height - drawn_height) / 2

    canvas.drawImage(
        background.reader,
        image_x,
        image_y,
        width=drawn_width,
        height=drawn_height,
        preserveAspectRatio=True,
        mask="auto",
    )

    canvas.saveState()
    canvas.setFillColor(style_engine.color("overlay"))
    canvas.rect(x, y, width, height, stroke=0, fill=1)
    canvas.restoreState()

    return image_x, image_y, drawn_width, drawn_height
