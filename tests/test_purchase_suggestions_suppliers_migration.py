from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import db, services


def test_purchase_suggestions_migrate_legacy_suppliers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    monkeypatch.setattr(db, "USERS_DB_PATH", data_dir / "users.db")
    monkeypatch.setattr(db, "CORE_DB_PATH", data_dir / "core.db")
    monkeypatch.setattr(db, "get_site_db_path", lambda site_key: tmp_path / f"{site_key}.db")
    monkeypatch.setattr(db, "list_site_keys", lambda: ["JLL", "GSM"])

    services._db_initialized = False
    services._SUPPLIER_MIGRATED_SITES.clear()
    services.ensure_database_ready()

    with db.get_stock_connection("JLL") as conn:
        supplier_id = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES ('Legacy Supplier', 'legacy@test.fr')"
        ).lastrowid
        conn.commit()

    with db.get_stock_connection("GSM") as conn:
        conn.execute(
            """
            INSERT INTO items (name, sku, quantity, low_stock_threshold, track_low_stock, supplier_id)
            VALUES ('Item GSM', 'GSM-01', 0, 5, 1, ?)
            """,
            (supplier_id,),
        )
        conn.commit()

    services.refresh_purchase_suggestions(site_key="GSM", module_keys=["clothing"])
    suggestions = services.list_purchase_suggestions(site_key="GSM", status="draft")

    assert suggestions, "Expected at least one suggestion for GSM site"
    suggestion = suggestions[0]
    assert suggestion.supplier_status == "ok"
    assert suggestion.supplier_email == "legacy@test.fr"
    assert suggestion.supplier_display == "Legacy Supplier"
