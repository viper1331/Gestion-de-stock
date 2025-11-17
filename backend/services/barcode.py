"""Service pour la génération des codes-barres."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:  # pragma: no cover - dépendance optionnelle en environnement de test
    import barcode as _barcode_lib
    from barcode.charsets import code128 as _code128_charset
    from barcode.codex import Code128, check_code
    from barcode.writer import ImageWriter
except ModuleNotFoundError:  # pragma: no cover - dépendance optionnelle en environnement de test
    _barcode_lib = None
    ImageWriter = None  # type: ignore[assignment]
else:
    class Code128B(Code128):
        """Version restreinte du Code 128 forçant le jeu de caractères B."""

        name = "Code 128 B"

        def __init__(self, code: str, writer=None) -> None:
            self.code = code
            self.writer = writer or self.default_writer()
            self._charset = "B"
            self._buffer = ""
            check_code(self.code, self.name, set(_code128_charset.B.keys()))

        def _maybe_switch_charset(self, pos: int):  # pragma: no cover - logique simple
            return []

        def _convert(self, char: str):  # pragma: no cover - délégué à la bibliothèque
            try:
                return _code128_charset.B[char]
            except KeyError:  # pragma: no cover - cohérent avec check_code
                raise RuntimeError(
                    f"Character {char} could not be converted in charset B."
                ) from None

WRITER_OPTIONS = {
    "module_width": 0.2,
    "module_height": 15.0,
    "font_size": 12,
    "text_distance": 1,
    "quiet_zone": 1.0,
}

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "barcodes"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

PDF_PAGE_WIDTH_CM = 21.0
PDF_PAGE_HEIGHT_CM = 29.7
PDF_DPI = 300
PDF_COLUMNS = 3
PDF_ROWS = 8
PDF_MARGIN_CM = 0.8
PDF_CELL_PADDING_CM = 0.3


@dataclass(frozen=True)
class BarcodeAsset:
    """Représentation d'un fichier de code-barres généré."""

    sku: str
    filename: str
    path: Path
    modified_at: datetime


def _barcode_path(sku: str) -> Path:
    safe = sku.replace("/", "-")
    return ASSETS_DIR / f"{safe}.png"


def generate_barcode_png(sku: str) -> Optional[Path]:
    path = _barcode_path(sku)

    if not (_barcode_lib and ImageWriter):
        if os.getenv("ALLOW_PLACEHOLDER_BARCODE") == "1":
            logger.warning(
                "Bibliothèque python-barcode absente : utilisation du placeholder pour %s.",
                sku,
            )
            return _generate_placeholder_barcode(path, sku)

        raise RuntimeError(
            "La librairie 'python-barcode' est requise pour générer les codes-barres Code128."
        )

    try:
        code = Code128B(sku, writer=ImageWriter())

        filename = path.with_suffix("")
        generated_path = code.save(str(filename), options=WRITER_OPTIONS)
        return Path(generated_path)
    except Exception as exc:
        logger.exception(
            "Erreur lors de la génération du code-barres Code128 pour %s.", sku
        )
        if path.exists():
            path.unlink()
        raise RuntimeError(
            "Échec de la génération du code-barres Code128."
        ) from exc


def _generate_placeholder_barcode(path: Path, sku: str) -> Optional[Path]:
    """Fallback visuel non normé, réservé au développement.

    Cette fonction ne produit **pas** de code-barres Code 128 valide et ne doit
    être utilisée que lorsque `ALLOW_PLACEHOLDER_BARCODE=1` est défini dans
    l'environnement pour des tests manuels ou du prototypage local.
    """

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


def list_barcode_assets() -> List[BarcodeAsset]:
    """Retourne la liste des fichiers de codes-barres disponibles."""

    assets: List[BarcodeAsset] = []
    base_dir = ASSETS_DIR.resolve()

    candidates = sorted(
        (path for path in base_dir.glob("*.png") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for file_path in candidates:
        try:
            stat = file_path.stat()
        except FileNotFoundError:
            continue
        assets.append(
            BarcodeAsset(
                sku=file_path.stem,
                filename=file_path.name,
                path=file_path,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )

    return assets


def get_barcode_asset(filename: str) -> Optional[Path]:
    """Récupère le chemin d'un fichier de code-barres en s'assurant qu'il est sûr."""

    if not filename.lower().endswith(".png"):
        return None

    candidate = Path(filename)
    if candidate.name != filename:
        return None

    try:
        resolved = (ASSETS_DIR / candidate.name).resolve(strict=False)
    except FileNotFoundError:
        return None

    base_dir = ASSETS_DIR.resolve()
    if resolved.parent != base_dir:
        return None

    if not resolved.exists() or not resolved.is_file():
        return None

    return resolved


def generate_barcode_pdf(
    assets: Optional[Iterable[BarcodeAsset]] = None,
) -> Optional[BytesIO]:
    """Crée un PDF A4 avec une grille de codes-barres.

    Args:
        assets: Optionnellement une collection d'assets déjà filtrés.
            Si omis, tous les fichiers disponibles seront utilisés.
    """

    if assets is None:
        assets_list = list_barcode_assets()
    else:
        assets_list = list(assets)

    if not assets_list:
        return None

    px_per_cm = PDF_DPI / 2.54
    page_width_px = int(round(PDF_PAGE_WIDTH_CM * px_per_cm))
    page_height_px = int(round(PDF_PAGE_HEIGHT_CM * px_per_cm))
    margin_px = int(round(PDF_MARGIN_CM * px_per_cm))
    cell_padding_px = int(round(PDF_CELL_PADDING_CM * px_per_cm))

    usable_width = page_width_px - 2 * margin_px
    usable_height = page_height_px - 2 * margin_px
    if usable_width <= 0 or usable_height <= 0:
        return None

    cell_width = usable_width // PDF_COLUMNS
    cell_height = usable_height // PDF_ROWS
    if cell_width <= 0 or cell_height <= 0:
        return None

    cells_per_page = PDF_COLUMNS * PDF_ROWS
    pages: list[Image.Image] = []

    for start in range(0, len(assets_list), cells_per_page):
        page = Image.new("RGB", (page_width_px, page_height_px), color="white")
        chunk = assets_list[start : start + cells_per_page]

        for index, asset in enumerate(chunk):
            try:
                with Image.open(asset.path) as original:
                    barcode_image = original.convert("RGB")
            except Exception:
                continue

            row = index // PDF_COLUMNS
            column = index % PDF_COLUMNS

            x0 = margin_px + column * cell_width
            y0 = margin_px + row * cell_height
            available_width = max(1, cell_width - 2 * cell_padding_px)
            available_height = max(1, cell_height - 2 * cell_padding_px)

            resized = ImageOps.contain(barcode_image, (available_width, available_height))
            barcode_image.close()
            paste_x = x0 + (cell_width - resized.width) // 2
            paste_y = y0 + (cell_height - resized.height) // 2

            page.paste(resized, (paste_x, paste_y))
            resized.close()

        pages.append(page)

    if not pages:
        return None

    buffer = BytesIO()
    first_page, *other_pages = pages
    try:
        first_page.save(buffer, format="PDF", resolution=PDF_DPI, save_all=bool(other_pages), append_images=other_pages)
        buffer.seek(0)
    finally:
        for page in pages:
            page.close()
    return buffer
