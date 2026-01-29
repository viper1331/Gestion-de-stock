"""Service pour la génération des codes-barres.

La génération repose sur `python-barcode` et `Pillow` pour produire des
images Code 128 B scannables. Sans ces dépendances, l'API lève une erreur
explicite plutôt que de revenir silencieusement à un rendu factice.
"""
from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

from backend.core import db
from backend.core.pdf_config_models import PdfConfig

try:  # pragma: no cover - dépendances requises pour la génération réelle
    import barcode as _barcode_lib
    from barcode.charsets import code128 as _code128_charset
    from barcode.codex import Code128, check_code
    from barcode.writer import ImageWriter
except ModuleNotFoundError:  # pragma: no cover - géré dans generate_barcode_png
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
    "write_text": False,
}

logger = logging.getLogger(__name__)

logger.debug(
    "Barcode module loaded from %s (_barcode_lib=%s, ImageWriter=%s)",
    sys.executable,
    bool(_barcode_lib),
    bool(ImageWriter),
)

ASSETS_ROOT = Path(__file__).resolve().parent.parent / "assets"
ASSETS_DIR = ASSETS_ROOT / "barcodes"

PDF_PAGE_WIDTH_CM = 21.0
PDF_PAGE_HEIGHT_CM = 29.7
PDF_DPI = 300
PDF_COLUMNS = 3
PDF_ROWS = 8
PDF_MARGIN_CM = 1.0
PDF_CELL_PADDING_CM = 0.4
PDF_MIN_CELL_WIDTH_CM = 7.0
PDF_MIN_CELL_HEIGHT_CM = 3.5
PDF_QUIET_ZONE_CM = 0.25
PDF_TEXT_GAP_CM = 0.2
PDF_TITLE_FONT_SIZE_PT = 10
PDF_LABEL_FONT_SIZE_PT = 9
PDF_META_FONT_SIZE_PT = 8


@dataclass(frozen=True)
class BarcodeAsset:
    """Représentation d'un fichier de code-barres généré."""

    sku: str
    filename: str
    path: Path
    modified_at: datetime
    name: str | None = None
    category: str | None = None
    variant: str | None = None
    size: str | None = None


def _resolve_barcode_font_sizes(config: PdfConfig | None) -> tuple[int, int, int]:
    if not config:
        return PDF_TITLE_FONT_SIZE_PT, PDF_LABEL_FONT_SIZE_PT, PDF_META_FONT_SIZE_PT
    advanced = config.advanced
    title_size = max(PDF_TITLE_FONT_SIZE_PT, int(advanced.barcode_title_font_size))
    label_size = max(PDF_LABEL_FONT_SIZE_PT, int(advanced.barcode_label_font_size))
    meta_size = max(PDF_META_FONT_SIZE_PT, int(advanced.barcode_meta_font_size))
    return title_size, label_size, meta_size


def _pt_to_px(value: float) -> int:
    return int(round(value * PDF_DPI / 72))


def _load_font(font_names: list[str], size_px: int) -> ImageFont.ImageFont:
    for font_name in font_names:
        try:
            return ImageFont.truetype(font_name, size=size_px)
        except OSError:
            continue
    return ImageFont.load_default()


def _font_line_height(font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox("Ag")
    return max(1, bbox[3] - bbox[1])


def _truncate_with_ellipsis(
    text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, max_width: int
) -> str:
    ellipsis = "…"
    if draw.textlength(text, font=font) <= max_width:
        return text
    trimmed = text
    while trimmed and draw.textlength(f"{trimmed}{ellipsis}", font=font) > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}{ellipsis}" if trimmed else ellipsis


def _wrap_text(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    max_width: int,
    *,
    max_lines: int | None = None,
    ellipsis: bool = False,
) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    truncated = False

    for index, word in enumerate(words):
        candidate = word if not current else f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)
            current = word
        else:
            for char in word:
                next_piece = f"{current}{char}"
                if draw.textlength(next_piece, font=font) <= max_width:
                    current = next_piece
                else:
                    lines.append(current)
                    current = char

        if max_lines and len(lines) >= max_lines:
            truncated = True
            current = ""
            break

        if index == len(words) - 1 and current:
            lines.append(current)
            current = ""

    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)

    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    if truncated and ellipsis and lines:
        lines[-1] = _truncate_with_ellipsis(lines[-1], draw, font, max_width)

    return lines


def _build_label_text(asset: BarcodeAsset) -> tuple[str, str, str | None]:
    name = (asset.name or "").strip() or asset.sku
    sku = asset.sku
    extras = [value for value in [asset.category, asset.variant, asset.size] if value]
    extra_line = " / ".join(extras) if extras else None
    return name, sku, extra_line


def _legacy_assets_dir() -> Path:
    return ASSETS_DIR


def _site_assets_root() -> Path:
    return ASSETS_ROOT / "sites"


def _migrate_legacy_assets(site_key: str, site_dir: Path) -> None:
    """Migre les fichiers historiques vers le site par défaut.

    Stratégie : les anciens fichiers "globaux" ne sont déplacés automatiquement
    que pour le site par défaut. Les autres sites ne lisent jamais ce répertoire
    afin d'éviter tout partage involontaire entre sites.
    """

    if site_key != db.DEFAULT_SITE_KEY:
        return

    legacy_dir = _legacy_assets_dir()
    if not legacy_dir.exists():
        return

    legacy_files = [path for path in legacy_dir.glob("*.png") if path.is_file()]
    if not legacy_files:
        return

    moved = 0
    for file_path in legacy_files:
        target = site_dir / file_path.name
        if target.exists():
            continue
        try:
            shutil.move(str(file_path), str(target))
            moved += 1
        except OSError:
            logger.warning(
                "[BARCODE] Impossible de migrer %s vers %s.", file_path, target
            )

    if moved:
        logger.info(
            "[BARCODE] %s code(s)-barres migré(s) depuis %s vers %s pour le site %s.",
            moved,
            legacy_dir,
            site_dir,
            site_key,
        )


def get_site_assets_dir(site_key: str | None = None) -> Path:
    resolved_key = (site_key or db.get_current_site_key()).upper()
    site_dir = _site_assets_root() / resolved_key / "barcodes"
    site_dir.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_assets(resolved_key, site_dir)
    return site_dir


def _barcode_path(sku: str, site_key: str | None = None) -> Path:
    safe = sku.replace("/", "-")
    return get_site_assets_dir(site_key) / f"{safe}.png"


def generate_barcode_png(sku: str, site_key: str | None = None) -> Optional[Path]:
    path = _barcode_path(sku, site_key)

    if not (_barcode_lib and ImageWriter):
        raise RuntimeError(
            "La librairie 'python-barcode' est requise pour générer les codes-barres Code128."
        )

    try:
        code = Code128B(sku, writer=ImageWriter())

        filename = path.with_suffix("")
        generated_path = code.save(str(filename), options=WRITER_OPTIONS)
        generated = Path(generated_path)
        _append_barcode_caption(generated, sku)
        return generated
    except Exception as exc:
        logger.exception(
            "Erreur lors de la génération du code-barres Code128 pour %s.", sku
        )
        if path.exists():
            path.unlink()
        raise RuntimeError(
            "Échec de la génération du code-barres Code128."
        ) from exc


def _append_barcode_caption(path: Path, sku: str) -> None:
    try:
        original = Image.open(path)
    except OSError:
        return

    barcode_image: Image.Image | None = None
    try:
        barcode_image = original.convert("RGB")
        original.close()

        try:
            font = ImageFont.truetype("DejaVuSansMono.ttf", size=16)
        except OSError:
            font = ImageFont.load_default()

        draw = ImageDraw.Draw(barcode_image)
        text_bbox = draw.textbbox((0, 0), sku, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]

        padding_top = 8
        padding_bottom = 10
        new_height = barcode_image.height + padding_top + text_height + padding_bottom
        canvas = Image.new("RGB", (barcode_image.width, new_height), color="white")
        canvas.paste(barcode_image, (0, 0))

        text_x = max((barcode_image.width - text_width) // 2, 0)
        text_y = barcode_image.height + padding_top
        caption_draw = ImageDraw.Draw(canvas)
        caption_draw.text((text_x, text_y), sku, fill="black", font=font)

        canvas.save(path)
    finally:
        if barcode_image is not None:
            barcode_image.close()


def _generate_placeholder_barcode(path: Path, sku: str) -> Optional[Path]:
    """Fallback visuel non normé, réservé au développement.

    Cette fonction ne produit **pas** de code-barres Code 128 valide et n'est
    plus appelée automatiquement. Elle reste disponible pour des usages
    manuels ou du prototypage local explicite.
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


def delete_barcode_png(sku: str, site_key: str | None = None) -> None:
    path = _barcode_path(sku, site_key)
    if path.exists():
        path.unlink()


def _list_assets_in_dir(base_dir: Path) -> List[BarcodeAsset]:
    assets: List[BarcodeAsset] = []
    base_dir = base_dir.resolve()

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


def list_barcode_assets(site_key: str | None = None) -> List[BarcodeAsset]:
    """Retourne la liste des fichiers de codes-barres disponibles."""

    resolved_key = (site_key or db.get_current_site_key()).upper()
    site_dir = get_site_assets_dir(resolved_key)
    assets = _list_assets_in_dir(site_dir)

    legacy_dir = _legacy_assets_dir()
    if resolved_key == db.DEFAULT_SITE_KEY and legacy_dir.exists():
        existing = {asset.filename for asset in assets}
        for asset in _list_assets_in_dir(legacy_dir):
            if asset.filename in existing:
                continue
            assets.append(asset)

    return sorted(assets, key=lambda asset: asset.modified_at, reverse=True)


def _resolve_asset_path(base_dir: Path, filename: str) -> Optional[Path]:
    try:
        resolved = (base_dir / filename).resolve(strict=False)
    except FileNotFoundError:
        return None

    if resolved.parent != base_dir.resolve():
        return None

    if not resolved.exists() or not resolved.is_file():
        return None

    return resolved


def get_barcode_asset(filename: str, site_key: str | None = None) -> Optional[Path]:
    """Récupère le chemin d'un fichier de code-barres en s'assurant qu'il est sûr."""

    if not filename.lower().endswith(".png"):
        return None

    candidate = Path(filename)
    if candidate.name != filename:
        return None

    resolved_key = (site_key or db.get_current_site_key()).upper()
    site_dir = get_site_assets_dir(resolved_key)
    resolved = _resolve_asset_path(site_dir, candidate.name)
    if resolved:
        return resolved

    if resolved_key == db.DEFAULT_SITE_KEY:
        legacy_dir = _legacy_assets_dir()
        if legacy_dir.exists():
            return _resolve_asset_path(legacy_dir, candidate.name)

    return None


def generate_barcode_pdf(
    assets: Optional[Iterable[BarcodeAsset]] = None,
    *,
    config: PdfConfig | None = None,
    site_key: str | None = None,
) -> Optional[BytesIO]:
    """Crée un PDF A4 avec une grille de codes-barres.

    Args:
        assets: Optionnellement une collection d'assets déjà filtrés.
            Si omis, tous les fichiers disponibles seront utilisés.
    """

    if assets is None:
        assets_list = list_barcode_assets(site_key=site_key)
    else:
        assets_list = list(assets)

    if not assets_list:
        return None

    if config:
        width_cm, height_cm = _resolve_page_size_cm(config)
        margin_cm = (
            max(
                config.format.margins.left_mm,
                config.format.margins.right_mm,
                config.format.margins.top_mm,
                config.format.margins.bottom_mm,
            )
            / 10
        )
    else:
        width_cm, height_cm = PDF_PAGE_WIDTH_CM, PDF_PAGE_HEIGHT_CM
        margin_cm = PDF_MARGIN_CM

    px_per_cm = PDF_DPI / 2.54
    page_width_px = int(round(width_cm * px_per_cm))
    page_height_px = int(round(height_cm * px_per_cm))
    margin_px = int(round(margin_cm * px_per_cm))
    cell_padding_px = int(round(PDF_CELL_PADDING_CM * px_per_cm))

    usable_width = page_width_px - 2 * margin_px
    usable_height = page_height_px - 2 * margin_px
    if usable_width <= 0 or usable_height <= 0:
        return None

    min_cell_width_px = int(round(PDF_MIN_CELL_WIDTH_CM * px_per_cm))
    min_cell_height_px = int(round(PDF_MIN_CELL_HEIGHT_CM * px_per_cm))
    columns = PDF_COLUMNS if usable_width // PDF_COLUMNS >= min_cell_width_px else 2
    rows = max(1, usable_height // max(1, min_cell_height_px))

    cell_width = usable_width // columns
    cell_height = usable_height // rows
    if cell_width <= 0 or cell_height <= 0:
        return None

    quiet_zone_px = int(round(PDF_QUIET_ZONE_CM * px_per_cm))
    text_gap_px = int(round(PDF_TEXT_GAP_CM * px_per_cm))
    title_size_pt, label_size_pt, meta_size_pt = _resolve_barcode_font_sizes(config)
    title_font_px = _pt_to_px(title_size_pt)
    label_font_px = _pt_to_px(label_size_pt)
    meta_font_px = _pt_to_px(meta_size_pt)

    title_font = _load_font(["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"], title_font_px)
    label_font = _load_font(["DejaVuSansMono.ttf", "DejaVuSans.ttf"], label_font_px)
    meta_font = _load_font(["DejaVuSans.ttf", "DejaVuSansMono.ttf"], meta_font_px)

    title_line_height = _font_line_height(title_font)
    label_line_height = _font_line_height(label_font)
    meta_line_height = _font_line_height(meta_font)
    title_gap = max(2, int(title_line_height * 0.2))
    label_gap = max(2, int(label_line_height * 0.2))
    meta_gap = max(2, int(meta_line_height * 0.2))

    cells_per_page = columns * rows
    pages: list[Image.Image] = []

    for start in range(0, len(assets_list), cells_per_page):
        page = Image.new("RGB", (page_width_px, page_height_px), color="white")
        page_draw = ImageDraw.Draw(page)
        chunk = assets_list[start : start + cells_per_page]

        for index, asset in enumerate(chunk):
            try:
                with Image.open(asset.path) as original:
                    barcode_image = original.convert("RGB")
            except Exception:
                continue

            row = index // columns
            column = index % columns

            x0 = margin_px + column * cell_width
            y0 = margin_px + row * cell_height
            available_width = max(1, cell_width - 2 * cell_padding_px)
            available_height = max(1, cell_height - 2 * cell_padding_px)

            name_text, sku_text, extra_text = _build_label_text(asset)
            max_text_width = max(1, available_width - 2 * quiet_zone_px)
            name_lines = _wrap_text(
                name_text,
                page_draw,
                title_font,
                max_text_width,
                max_lines=2,
                ellipsis=True,
            )
            sku_lines = _wrap_text(
                sku_text,
                page_draw,
                label_font,
                max_text_width,
                max_lines=None,
            )
            extra_lines = (
                _wrap_text(
                    extra_text,
                    page_draw,
                    meta_font,
                    max_text_width,
                    max_lines=1,
                    ellipsis=True,
                )
                if extra_text
                else []
            )

            text_height = 0
            if name_lines:
                text_height += len(name_lines) * title_line_height + (len(name_lines) - 1) * title_gap
            if sku_lines:
                text_height += len(sku_lines) * label_line_height + (len(sku_lines) - 1) * label_gap
                if name_lines:
                    text_height += label_gap
            if extra_lines:
                text_height += len(extra_lines) * meta_line_height + (len(extra_lines) - 1) * meta_gap
                if name_lines or sku_lines:
                    text_height += meta_gap

            barcode_area_height = max(1, available_height - text_height - text_gap_px)
            barcode_area_width = max(1, available_width - 2 * quiet_zone_px)

            resized = ImageOps.contain(
                barcode_image,
                (barcode_area_width, max(1, barcode_area_height - 2 * quiet_zone_px)),
            )
            barcode_image.close()
            paste_x = x0 + cell_padding_px + quiet_zone_px + (barcode_area_width - resized.width) // 2
            paste_y = (
                y0
                + cell_padding_px
                + quiet_zone_px
                + (barcode_area_height - 2 * quiet_zone_px - resized.height) // 2
            )

            page.paste(resized, (paste_x, paste_y))
            resized.close()

            text_start_y = y0 + cell_padding_px + barcode_area_height + text_gap_px
            current_y = text_start_y

            for line in name_lines:
                text_width = page_draw.textlength(line, font=title_font)
                text_x = x0 + (cell_width - text_width) // 2
                page_draw.text((text_x, current_y), line, fill="black", font=title_font)
                current_y += title_line_height + title_gap

            if name_lines and sku_lines:
                current_y += label_gap

            for line in sku_lines:
                text_width = page_draw.textlength(line, font=label_font)
                text_x = x0 + (cell_width - text_width) // 2
                page_draw.text((text_x, current_y), line, fill="black", font=label_font)
                current_y += label_line_height + label_gap

            if (name_lines or sku_lines) and extra_lines:
                current_y += meta_gap

            for line in extra_lines:
                text_width = page_draw.textlength(line, font=meta_font)
                text_x = x0 + (cell_width - text_width) // 2
                page_draw.text((text_x, current_y), line, fill="black", font=meta_font)
                current_y += meta_line_height + meta_gap

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


def _resolve_page_size_cm(config: PdfConfig) -> tuple[float, float]:
    size_map = {
        "A3": (29.7, 42.0),
        "A4": (21.0, 29.7),
        "A5": (14.8, 21.0),
        "Letter": (21.59, 27.94),
    }
    width_cm, height_cm = size_map.get(config.format.size, (PDF_PAGE_WIDTH_CM, PDF_PAGE_HEIGHT_CM))
    if config.format.orientation == "landscape":
        return height_cm, width_cm
    return width_cm, height_cm
