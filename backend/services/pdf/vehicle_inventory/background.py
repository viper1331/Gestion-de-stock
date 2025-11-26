"""Background rendering utilities for vehicle inventory PDFs."""
from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader

from .style import PdfStyleEngine


def draw_background(
    canvas,
    image_path: Path,
    bounds: tuple[float, float, float, float],
    style_engine: PdfStyleEngine,
) -> tuple[float, float, float, float]:
    """Draw the background photo inside the provided bounds with a dark overlay."""

    if not image_path.exists():
        raise FileNotFoundError(f"Image introuvable: {image_path}")

    x, y, width, height = bounds
    with Image.open(image_path) as img:
        image_width, image_height = img.size
    image_ratio = image_width / image_height
    target_ratio = width / height

    if image_ratio > target_ratio:
        drawn_height = height
        drawn_width = drawn_height * image_ratio
    else:
        drawn_width = width
        drawn_height = drawn_width / image_ratio

    image_x = x + (width - drawn_width) / 2
    image_y = y + (height - drawn_height) / 2

    reader = ImageReader(str(image_path))
    canvas.drawImage(
        reader,
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
