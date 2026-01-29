from datetime import datetime, timezone

from pathlib import Path

from backend.core.pdf_config_models import PdfConfig
from backend.services import barcode as barcode_service


def _create_asset(tmp_path, name: str) -> barcode_service.BarcodeAsset:
    image_path = tmp_path / f"{name}.png"
    # Crée une petite image PNG valide pour alimenter la génération de PDF.
    barcode_service.Image.new("RGB", (120, 40), color="white").save(image_path)
    return barcode_service.BarcodeAsset(
        sku=name,
        filename=image_path.name,
        path=image_path,
        modified_at=datetime.now(timezone.utc),
    )


def test_generate_barcode_pdf_uses_provided_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(barcode_service, "ASSETS_DIR", tmp_path)

    allowed_asset = _create_asset(tmp_path, "allowed")
    _create_asset(tmp_path, "forbidden")

    def _unexpected_call():  # pragma: no cover - defensive programming
        raise AssertionError("list_barcode_assets ne doit pas être appelée lorsque des assets sont fournis")

    monkeypatch.setattr(barcode_service, "list_barcode_assets", _unexpected_call)

    pdf_buffer = barcode_service.generate_barcode_pdf(assets=[allowed_asset])

    assert pdf_buffer is not None
    assert pdf_buffer.getbuffer().nbytes > 0


def test_generate_barcode_pdf_returns_none_with_no_accessible_assets(monkeypatch):
    monkeypatch.setattr(barcode_service, "list_barcode_assets", lambda: [])

    assert barcode_service.generate_barcode_pdf(assets=[]) is None


def test_build_label_text_uses_name_and_sku():
    asset = barcode_service.BarcodeAsset(
        sku="SKU-001",
        filename="sku-001.png",
        path=Path("sku-001.png"),
        modified_at=datetime.now(timezone.utc),
        name="Nom article",
        category="Catégorie",
        size="XL",
    )

    name, sku, extra = barcode_service._build_label_text(asset)

    assert name == "Nom article"
    assert sku == "SKU-001"
    assert extra == "Catégorie / XL"


def test_barcode_font_sizes_respect_minimums():
    config = PdfConfig()
    config.advanced.barcode_title_font_size = 6
    config.advanced.barcode_label_font_size = 6
    config.advanced.barcode_meta_font_size = 4

    title_size, label_size, meta_size = barcode_service._resolve_barcode_font_sizes(config)

    assert title_size >= 10
    assert label_size >= 9
    assert meta_size >= 8
