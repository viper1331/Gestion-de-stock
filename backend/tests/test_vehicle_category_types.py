from __future__ import annotations

from backend.core import db, models, services


def test_vehicle_category_types_roundtrip() -> None:
    services.ensure_database_ready()
    created = services.create_vehicle_category(
        models.CategoryCreate(
            name="Véhicule multi-type",
            sizes=[],
            types=["incendie", "secours_a_personne"],
        )
    )
    assert created.types == ["incendie", "secours_a_personne"]
    assert created.vehicle_type == "incendie"

    updated = services.update_vehicle_category(
        created.id,
        models.CategoryUpdate(types=["secours_a_personne", "incendie"]),
    )
    assert updated.types == ["secours_a_personne", "incendie"]
    assert updated.vehicle_type == "secours_a_personne"


def test_vehicle_category_legacy_type_fallback() -> None:
    services.ensure_database_ready()
    with db.get_stock_connection() as conn:
        conn.execute(
            """
            INSERT INTO vehicle_categories (name, vehicle_type, extra_json)
            VALUES (?, ?, ?)
            """,
            ("Véhicule legacy", "incendie", "{}"),
        )
    categories = services.list_vehicle_categories()
    legacy = next(category for category in categories if category.name == "Véhicule legacy")
    assert legacy.types == ["incendie"]
