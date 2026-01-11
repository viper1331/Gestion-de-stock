"""Background rendering utilities for vehicle inventory PDFs."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader

from .image_cache import DEFAULT_IMAGE_DPI, DEFAULT_IMAGE_QUALITY, preprocess_image, target_pixels_for_bounds
from .style_engine import PdfStyleEngine


class BackgroundInfo:
    def __init__(
        self,
        reader: ImageReader,
        width: float,
        height: float,
        orientation: str,
        *,
        source_path: Path | None = None,
    ):
        self.reader = reader
        self.width = width
        self.height = height
        self.orientation = orientation
        self.source_path = source_path


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
    return BackgroundInfo(
        reader=reader,
        width=image.width,
        height=image.height,
        orientation=orientation,
        source_path=image_path,
    )


def prepare_background_for_bounds(
    image_path: Path,
    *,
    bounds: tuple[float, float, float, float],
    dpi: int = DEFAULT_IMAGE_DPI,
    quality: int = DEFAULT_IMAGE_QUALITY,
) -> BackgroundInfo:
    if not image_path.exists():
        raise FileNotFoundError(f"Image introuvable: {image_path}")

    image, orientation = _load_image(image_path)
    target_width_px, target_height_px = target_pixels_for_bounds(bounds[2], bounds[3], dpi=dpi)
    processed = preprocess_image(
        image_path,
        target_width_px=target_width_px,
        target_height_px=target_height_px,
        quality=quality,
    )
    reader = ImageReader(str(processed.path))
    return BackgroundInfo(
        reader=reader,
        width=image.width,
        height=image.height,
        orientation=orientation,
        source_path=image_path,
    )


def draw_background(
    canvas,
    background: BackgroundInfo,
    bounds: tuple[float, float, float, float],
    style_engine: PdfStyleEngine,
) -> tuple[float, float, float, float]:
    """Draw the compartment photo centered in a 16:9 frame without overlay."""

    x, y, width, height = bounds
    target_ratio = 16 / 9

    target_width = width
    target_height = target_width / target_ratio
    if target_height > height:
        target_height = height
        target_width = target_height * target_ratio

    frame_x = x + (width - target_width) / 2
    frame_y = y + (height - target_height) / 2

    scale = min(target_width / background.width, target_height / background.height)
    drawn_width = background.width * scale
    drawn_height = background.height * scale

    image_x = frame_x + (target_width - drawn_width) / 2
    image_y = frame_y + (target_height - drawn_height) / 2

    reader = background.reader
    if background.source_path:
        target_width_px, target_height_px = target_pixels_for_bounds(drawn_width, drawn_height, dpi=DEFAULT_IMAGE_DPI)
        processed = preprocess_image(
            background.source_path,
            target_width_px=target_width_px,
            target_height_px=target_height_px,
            quality=DEFAULT_IMAGE_QUALITY,
        )
        reader = ImageReader(str(processed.path))

    canvas.drawImage(
        reader,
        image_x,
        image_y,
        width=drawn_width,
        height=drawn_height,
        preserveAspectRatio=True,
        mask="auto",
    )

    return image_x, image_y, drawn_width, drawn_height
