import io
import sys
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core import models
from backend.core import services
from backend.services.pdf.vehicle_inventory import (
    PdfStyleEngine,
    VehiclePdfOptions,
    render_vehicle_inventory_pdf,
)
from backend.services.pdf.vehicle_inventory import bubbles, layout
from backend.services.pdf.vehicle_inventory.utils import build_vehicle_entries


@pytest.fixture()
def sample_image(tmp_path: Path) -> Path:
    path = tmp_path / "photo.png"
    img = Image.new("RGB", (800, 600), color=(200, 200, 220))
    img.save(path)
    return path


@pytest.fixture()
def portrait_image(tmp_path: Path) -> Path:
    path = tmp_path / "portrait.png"
    img = Image.new("RGB", (600, 900), color=(120, 140, 180))
    img.save(path)
    return path


def make_category(cat_id: int, image: Path | None = None, view_name: str = "Vue"):
    view = models.VehicleViewConfig(name=view_name)
    return models.Category(id=cat_id, name=f"Cat {cat_id}", image_url=str(image) if image else None, view_configs=[view])


def make_item(item_id: int, cat_id: int, x: float | None = 0.5, y: float | None = 0.5, size: str | None = "Vue"):
    return models.Item(
        id=item_id,
        name=f"Item {item_id}",
        sku=f"REF{item_id}",
        category_id=cat_id,
        size=size,
        quantity=1,
        position_x=x,
        position_y=y,
        lot_id=None,
        lot_name=None,
        low_stock_threshold=0,
        track_low_stock=True,
    )


def test_pdf_exports_without_error(sample_image, tmp_path):
    category = make_category(1, image=sample_image)
    item = make_item(1, 1)
    options = VehiclePdfOptions(pointer_mode_enabled=True, theme="premium")
    pdf_bytes = render_vehicle_inventory_pdf(
        categories=[category],
        items=[item],
        generated_at=datetime.utcnow(),
        pointer_targets=None,
        options=options,
        media_root=tmp_path,
    )
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert len(pdf_bytes) > 1000


def test_pdf_includes_background(sample_image, tmp_path):
    category = make_category(1, image=sample_image)
    item = make_item(1, 1)
    options = VehiclePdfOptions(pointer_mode_enabled=False)
    pdf_bytes = render_vehicle_inventory_pdf(
        categories=[category],
        items=[item],
        generated_at=datetime.utcnow(),
        pointer_targets=None,
        options=options,
        media_root=tmp_path,
    )
    assert len(pdf_bytes) > 500


def test_pointer_mode_on_draws_arrows(sample_image, tmp_path):
    category = make_category(1, image=sample_image)
    item = make_item(1, 1)
    entries = build_vehicle_entries(categories=[category], items=[item], pointer_targets=None, media_root=tmp_path)
    placements = bubbles.layout_bubbles(entries[0].entries, (0, 0, 400, 300), pointer_mode=True)
    assert any(p.pointer_mode_enabled for p in placements)
    # bubble should be offset upward relative to anchor
    placement = placements[0]
    assert placement.geometry.y + placement.geometry.height / 2 >= placement.anchor_y


def test_pointer_mode_off_no_arrows(sample_image, tmp_path):
    category = make_category(1, image=sample_image)
    item = make_item(1, 1)
    entries = build_vehicle_entries(categories=[category], items=[item], pointer_targets=None, media_root=tmp_path)
    placements = bubbles.layout_bubbles(entries[0].entries, (0, 0, 400, 300), pointer_mode=False)
    assert all(not p.pointer_mode_enabled for p in placements)


def test_bubbles_do_not_overlap(sample_image, tmp_path):
    category = make_category(1, image=sample_image)
    items = [make_item(i, 1, x=0.2 * i, y=0.2 * i) for i in range(1, 5)]
    entries = build_vehicle_entries(categories=[category], items=items, pointer_targets=None, media_root=tmp_path)
    placements = bubbles.layout_bubbles(entries[0].entries, (0, 0, 400, 300), pointer_mode=True)
    for i, a in enumerate(placements):
        for b in placements[i + 1 :]:
            ax, ay, aw, ah = a.geometry.rect
            bx, by, bw, bh = b.geometry.rect
            assert not (ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by)


def test_orientation_respected(portrait_image, tmp_path):
    category = make_category(1, image=portrait_image)
    item = make_item(1, 1)
    options = VehiclePdfOptions(pointer_mode_enabled=True)
    plan = layout.build_plan(
        categories=[category],
        items=[item],
        generated_at=datetime.utcnow(),
        pointer_targets=None,
        options=options,
        media_root=tmp_path,
    )
    assert plan.pages[0].orientation == "portrait"


def test_view_without_items_skipped(tmp_path):
    category = make_category(1, image=None)
    options = VehiclePdfOptions(pointer_mode_enabled=False)
    with pytest.raises(ValueError):
        layout.build_plan(
            categories=[category],
            items=[],
            generated_at=datetime.utcnow(),
            pointer_targets=None,
            options=options,
            media_root=tmp_path,
        )


def test_lot_rendering(sample_image, tmp_path):
    category = make_category(1, image=sample_image)
    item1 = make_item(1, 1)
    item2 = make_item(2, 1)
    item1.lot_id = 5
    item1.lot_name = "Lot Z"
    item2.lot_id = 5
    item2.lot_name = "Lot Z"
    entries = build_vehicle_entries(categories=[category], items=[item1, item2], pointer_targets=None, media_root=tmp_path)
    assert entries[0].entries[0].quantity == 2
    assert "Lot" in entries[0].entries[0].name


def test_generate_pdf_filters_selected_categories(monkeypatch):
    categories = [make_category(1), make_category(2)]
    items = [make_item(1, 1), make_item(2, 2), make_item(3, 2)]
    captured: dict[str, object] = {}

    monkeypatch.setattr(services, "ensure_database_ready", lambda: None)
    monkeypatch.setattr(services, "list_vehicle_categories", lambda: categories)
    monkeypatch.setattr(services, "list_vehicle_items", lambda: items)

    def fake_render_vehicle_inventory_pdf(*, categories, items, **kwargs):
        captured["categories"] = categories
        captured["items"] = items
        return b"pdf"

    monkeypatch.setattr(services, "render_vehicle_inventory_pdf", fake_render_vehicle_inventory_pdf)

    options = VehiclePdfOptions(category_ids=[2])
    pdf_bytes = services.generate_vehicle_inventory_pdf(pointer_targets=None, options=options)

    assert pdf_bytes == b"pdf"
    assert [category.id for category in captured["categories"]] == [2]
    assert {item.id for item in captured["items"]} == {2, 3}


def test_theme_premium():
    style = PdfStyleEngine(theme="premium")
    assert style.color("background") != style._palette["background"]


def test_table_fallback(sample_image, tmp_path):
    category = make_category(1, image=sample_image)
    item = make_item(1, 1)
    options = VehiclePdfOptions(pointer_mode_enabled=True, table_fallback=True)
    plan = layout.build_plan(
        categories=[category],
        items=[item],
        generated_at=datetime.utcnow(),
        pointer_targets=None,
        options=options,
        media_root=tmp_path,
    )
    assert plan.pages[0].kind == "table"
