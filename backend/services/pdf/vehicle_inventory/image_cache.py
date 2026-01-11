"""Image preprocessing cache for vehicle inventory PDF exports."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import tempfile
import time

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_DPI = 180
DEFAULT_IMAGE_QUALITY = 80


@dataclass(frozen=True)
class ImagePreprocessResult:
    path: Path
    cache_hit: bool
    elapsed_ms: float


def _cache_dir() -> Path:
    root = Path(tempfile.gettempdir()) / "vehicle_inventory_pdf_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_key(path: Path, *, mtime: float, target_px: tuple[int, int], quality: int) -> str:
    token = f"{path.resolve()}|{mtime:.6f}|{target_px[0]}x{target_px[1]}|q{quality}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()


def target_pixels_for_bounds(width_pt: float, height_pt: float, *, dpi: int = DEFAULT_IMAGE_DPI) -> tuple[int, int]:
    px_width = max(1, int(round((width_pt / 72) * dpi)))
    px_height = max(1, int(round((height_pt / 72) * dpi)))
    return px_width, px_height


def preprocess_image(
    path: Path,
    *,
    target_width_px: int,
    target_height_px: int,
    quality: int = DEFAULT_IMAGE_QUALITY,
) -> ImagePreprocessResult:
    start = time.perf_counter()
    mtime = path.stat().st_mtime
    target_px = (target_width_px, target_height_px)
    cache_path = _cache_dir() / f"{_cache_key(path, mtime=mtime, target_px=target_px, quality=quality)}.jpg"

    if cache_path.exists():
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.debug(
            "[vehicle_inventory_pdf] image cache hit path=%s target=%sx%s quality=%s elapsed_ms=%.2f",
            path,
            target_width_px,
            target_height_px,
            quality,
            elapsed_ms,
        )
        return ImagePreprocessResult(path=cache_path, cache_hit=True, elapsed_ms=elapsed_ms)

    with Image.open(path) as img:
        oriented = ImageOps.exif_transpose(img)
        if oriented.mode in ("RGBA", "LA"):
            background = Image.new("RGB", oriented.size, (255, 255, 255))
            alpha = oriented.split()[-1]
            background.paste(oriented, mask=alpha)
            working = background
        else:
            working = oriented.convert("RGB")

        working.thumbnail(target_px, Image.LANCZOS)
        temp_path = cache_path.with_suffix(".tmp")
        working.save(temp_path, format="JPEG", quality=quality, optimize=True)
        temp_path.replace(cache_path)

    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.debug(
        "[vehicle_inventory_pdf] image cache miss path=%s target=%sx%s quality=%s elapsed_ms=%.2f",
        path,
        target_width_px,
        target_height_px,
        quality,
        elapsed_ms,
    )
    return ImagePreprocessResult(path=cache_path, cache_hit=False, elapsed_ms=elapsed_ms)
