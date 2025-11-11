from datetime import datetime, timezone

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
