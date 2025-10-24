"""Service pour la génération des codes-barres."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "barcodes"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _barcode_path(sku: str) -> Path:
    safe = sku.replace("/", "-")
    return ASSETS_DIR / f"{safe}.png"


def generate_barcode_png(sku: str) -> Optional[Path]:
    path = _barcode_path(sku)
    img = Image.new("RGB", (400, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([(20, 20), (380, 120)], outline="black", width=3)
    draw.text((40, 140), sku, fill="black")
    img.save(path)
    return path


def delete_barcode_png(sku: str) -> None:
    path = _barcode_path(sku)
    if path.exists():
        path.unlink()
