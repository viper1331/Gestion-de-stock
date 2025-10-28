"""Service pour la génération des codes-barres."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

try:  # pragma: no cover - dépendance optionnelle en environnement de test
    import barcode as _barcode_lib
    from barcode.writer import ImageWriter
except ModuleNotFoundError:  # pragma: no cover - dépendance optionnelle en environnement de test
    _barcode_lib = None
    ImageWriter = None  # type: ignore[assignment]

WRITER_OPTIONS = {
    "module_width": 0.2,
    "module_height": 15.0,
    "font_size": 12,
    "text_distance": 1,
    "quiet_zone": 1.0,
}

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "barcodes"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _barcode_path(sku: str) -> Path:
    safe = sku.replace("/", "-")
    return ASSETS_DIR / f"{safe}.png"


def generate_barcode_png(sku: str) -> Optional[Path]:
    path = _barcode_path(sku)

    if _barcode_lib and ImageWriter:
        try:
            barcode_class = _barcode_lib.get_barcode_class("code128")
            code = barcode_class(sku, writer=ImageWriter())

            filename = path.with_suffix("")
            generated_path = code.save(str(filename), options=WRITER_OPTIONS)
            return Path(generated_path)
        except Exception:
            if path.exists():
                path.unlink()

    return _generate_placeholder_barcode(path, sku)


def _generate_placeholder_barcode(path: Path, sku: str) -> Optional[Path]:
    """Fallback minimaliste pour générer un visuel lorsqu'aucune librairie n'est disponible."""

    try:
        width, height = 400, 200
        image = Image.new("RGB", (width, height), color="white")
        draw = ImageDraw.Draw(image)

        pattern = "".join(f"{ord(ch):08b}" for ch in sku) or "1" * 12
        left_margin, right_margin = 40, 40
        top_margin, bottom_margin = 30, 130
        available_width = width - left_margin - right_margin
        bar_width = max(1, available_width // len(pattern))

        for index, bit in enumerate(pattern):
            x0 = left_margin + index * bar_width
            if x0 >= width - right_margin:
                break
            if bit == "1":
                x1 = min(x0 + bar_width - 1, width - right_margin)
                draw.rectangle([(x0, top_margin), (x1, bottom_margin)], fill="black")

        font = ImageFont.load_default()
        text_bbox = draw.textbbox((0, 0), sku, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        text_x = (width - text_width) // 2
        text_y = bottom_margin + (height - bottom_margin - text_height) // 2
        draw.text((text_x, text_y), sku, fill="black", font=font)

        image.save(path)
    except Exception:
        if path.exists():
            path.unlink()
        return None

    return path


def delete_barcode_png(sku: str) -> None:
    path = _barcode_path(sku)
    if path.exists():
        path.unlink()
