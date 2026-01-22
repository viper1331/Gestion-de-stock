import logging
import pytest
from uuid import uuid4

from backend.core import db, models, services


@pytest.fixture()
def temp_backend_db(tmp_path, monkeypatch):
    stock_db = tmp_path / "stock.db"
    users_db = tmp_path / "users.db"
    monkeypatch.setattr(db, "STOCK_DB_PATH", stock_db)
    monkeypatch.setattr(db, "USERS_DB_PATH", users_db)
    monkeypatch.setattr(services, "_restore_inventory_snapshots", lambda: None)
    services._db_initialized = False
    services.ensure_database_ready()
    yield
    services._db_initialized = False


def _create_vehicle_context():
    category = services.create_vehicle_category(
        models.CategoryCreate(name="VSAV", sizes=["CABINE"])
    )
    remise_item = services.create_remise_item(
        models.ItemCreate(
            name="Valise d'intervention",
            sku=f"REM-{uuid4().hex[:6]}",
            category_id=None,
            size=None,
            quantity=5,
            low_stock_threshold=0,
            track_low_stock=True,
        )
    )
    return category, remise_item


def test_assign_from_remise_persists_target_view(temp_backend_db):
    category, remise_item = _create_vehicle_context()
    assignment = models.VehicleAssignmentFromRemise(
        remise_item_id=remise_item.id,
        category_id=category.id,
        vehicle_type=None,
        target_view="CABINE",
        position=models.PointerTarget(x=0.4, y=0.6),
        quantity=1,
    )

    created = services.assign_vehicle_item_from_remise(assignment)

    assert created.size == "CABINE"
    reloaded = services.get_vehicle_item(created.id)
    assert reloaded.size == "CABINE"
    items = services.list_vehicle_items()
    assert any(item.id == created.id and item.size == "CABINE" for item in items)


def test_assign_from_remise_rejects_missing_view(temp_backend_db):
    category, remise_item = _create_vehicle_context()

    with pytest.raises(ValueError):
        services.assign_vehicle_item_from_remise(
            models.VehicleAssignmentFromRemise(
                remise_item_id=remise_item.id,
                category_id=category.id,
                vehicle_type=None,
                target_view="   ",
                position=models.PointerTarget(x=0.1, y=0.2),
                quantity=1,
            )
        )


def test_sync_skips_remise_item_without_sku(temp_backend_db, caplog):
    with db.get_stock_connection() as conn:
        conn.execute(
            "INSERT INTO remise_items (name, sku) VALUES (?, ?)",
            ("Sans SKU", ""),
        )
        remise_row = conn.execute(
            "SELECT id FROM remise_items WHERE name = ?",
            ("Sans SKU",),
        ).fetchone()
        assert remise_row is not None
        remise_item_id = remise_row["id"]

        with caplog.at_level(logging.WARNING):
            services._sync_vehicle_inventory_with_remise(conn)

        synced = conn.execute(
            "SELECT 1 FROM vehicle_items WHERE remise_item_id = ?",
            (remise_item_id,),
        ).fetchone()

    assert synced is None
    assert any(
        "[SYNC] skipping remise item without sku" in record.message
        for record in caplog.records
    )
