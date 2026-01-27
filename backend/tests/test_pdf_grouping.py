from __future__ import annotations

from datetime import datetime
import zlib
from base64 import a85decode

from backend.core import models, services
from backend.core.pdf_config_models import PdfConfigOverrides, PdfGroupingConfig, PdfModuleConfig
from backend.core.system_config import get_config
from backend.services import pdf_config


def _with_pdf_exports(config):
    system_config = get_config()
    original = system_config.pdf_exports
    system_config.pdf_exports = config
    return original


def _extract_pdf_stream_text(pdf_bytes: bytes) -> bytes:
    chunks: list[bytes] = []
    cursor = 0
    while True:
        start = pdf_bytes.find(b"stream", cursor)
        if start == -1:
            break
        start = pdf_bytes.find(b"\n", start)
        if start == -1:
            break
        start += 1
        end = pdf_bytes.find(b"endstream", start)
        if end == -1:
            break
        stream = pdf_bytes[start:end].strip()
        decoded = stream
        try:
            decoded = a85decode(stream, adobe=True)
        except Exception:
            try:
                decoded = a85decode(stream, adobe=False)
            except Exception:
                decoded = stream
        try:
            chunks.append(zlib.decompress(decoded))
        except zlib.error:
            chunks.append(decoded)
        cursor = end + len(b"endstream")
    return b"".join(chunks)


def test_purchase_order_pdf_includes_expected_headers() -> None:
    order = models.PurchaseOrderDetail(
        id=42,
        supplier_id=None,
        status="PENDING",
        created_at=datetime.now(),
        note=None,
        auto_created=False,
        supplier_name="Test Supplier",
        items=[
            models.PurchaseOrderItem(
                id=1,
                purchase_order_id=42,
                item_id=10,
                quantity_ordered=4,
                quantity_received=2,
                item_name="Gants",
                sku="SKU-001",
                unit="Boîte",
            ),
            models.PurchaseOrderItem(
                id=2,
                purchase_order_id=42,
                item_id=11,
                quantity_ordered=3,
                quantity_received=1,
                item_name="Masques",
                sku="SKU-002",
                unit="Unité",
            ),
        ],
    )
    pdf_bytes = services.generate_purchase_order_pdf(order)
    content = _extract_pdf_stream_text(pdf_bytes)
    assert b"SKU" in content
    assert b"D\\351signation" in content or b"D\xc3\xa9signation" in content
    assert b"Quantit\\351" in content or b"Quantit\xc3\xa9" in content
    assert b"Taille/Variante" in content
    assert b"Unit\\351" not in content and b"Unit\xc3\xa9" not in content
    assert b"R\\351ceptionn\\351" not in content and b"R\xc3\xa9ceptionn\xc3\xa9" not in content


def test_remise_inventory_pdf_includes_group_headers() -> None:
    export_config = pdf_config._build_default_export_config()
    export_config.modules["remise_inventory"] = PdfModuleConfig(
        override_global=True,
        config=PdfConfigOverrides(
            grouping=PdfGroupingConfig(enabled=True, keys=["size"]),
        ),
    )
    original = _with_pdf_exports(export_config)
    try:
        items = [
            models.Item(
                id=1,
                name="Compresse",
                sku="SKU-1",
                category_id=1,
                size="XL",
                quantity=10,
                low_stock_threshold=2,
                track_low_stock=True,
            )
        ]
        pdf_bytes = services._render_remise_inventory_pdf(
            items=items,
            category_map={1: "Consommables"},
            module_title="Inventaire remises",
        )
    finally:
        get_config().pdf_exports = original
    content = _extract_pdf_stream_text(pdf_bytes)
    assert b"TAILLE / VARIANTE : XL" in content
