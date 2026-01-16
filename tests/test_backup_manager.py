from datetime import datetime, timedelta
import sqlite3
from zipfile import ZipFile

import pytest

from backend.services import backup_manager


@pytest.mark.usefixtures("tmp_path")
def test_create_backup_archive_limits_backup_count(monkeypatch, tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    monkeypatch.setattr(backup_manager, "BACKUP_ROOT", backup_root, raising=False)

    stock_db = tmp_path / "stock.db"
    users_db = tmp_path / "users.db"
    for path in (stock_db, users_db):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY)")
    monkeypatch.setattr(backup_manager.db, "STOCK_DB_PATH", stock_db)
    monkeypatch.setattr(backup_manager.db, "USERS_DB_PATH", users_db)
    monkeypatch.setattr(backup_manager.db, "CORE_DB_PATH", tmp_path / "core.db")
    monkeypatch.setattr(backup_manager.db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(backup_manager, "discover_site_keys", lambda: ["JLL"])
    monkeypatch.setattr(backup_manager.db, "get_site_db_path", lambda site_key: stock_db)

    timestamps = [datetime(2024, 1, 1, 12, 0, 0) + timedelta(seconds=i) for i in range(10)]

    class FakeDatetime:
        values = iter(timestamps)

        @classmethod
        def now(cls):
            return next(cls.values)

    monkeypatch.setattr(backup_manager, "datetime", FakeDatetime)

    for _ in range(5):
        backup_manager.create_backup_archive()

    backups = sorted(p.name for p in backup_root.glob("backup-*.zip"))
    assert len(backups) == backup_manager.MAX_BACKUP_FILES

    backup_timestamps = timestamps[::2]
    expected = [
        f"backup-{ts.strftime('%Y%m%d-%H%M%S')}.zip"
        for ts in backup_timestamps[-backup_manager.MAX_BACKUP_FILES :]
    ]
    assert backups == sorted(expected)


def test_backup_archive_includes_multiple_sites(monkeypatch, tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    jll_db = data_dir / "JLL.db"
    gsm_db = data_dir / "GSM.db"
    users_db = data_dir / "users.db"
    core_db = data_dir / "core.db"
    for path in (jll_db, gsm_db, users_db, core_db):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY)")

    monkeypatch.setattr(backup_manager.db, "DATA_DIR", data_dir)
    monkeypatch.setattr(backup_manager.db, "USERS_DB_PATH", users_db)
    monkeypatch.setattr(backup_manager.db, "CORE_DB_PATH", core_db)
    monkeypatch.setattr(backup_manager, "BACKUP_ROOT", backup_root, raising=False)
    monkeypatch.setattr(backup_manager.db, "get_site_db_path", lambda site_key: data_dir / f"{site_key}.db")
    monkeypatch.setattr(backup_manager, "discover_site_keys", lambda: ["JLL", "GSM"])

    archive_path = backup_manager.create_backup_archive()

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "sites/JLL/JLL.db" in names
    assert "sites/GSM/GSM.db" in names


def test_backup_archive_includes_users_db_and_media(monkeypatch, tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    media_root = tmp_path / "media"
    media_root.mkdir()

    users_db = data_dir / "users.db"
    core_db = data_dir / "core.db"
    stock_db = data_dir / "JLL.db"
    for path in (users_db, core_db, stock_db):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY)")

    sample_media = media_root / "sample.txt"
    sample_media.write_text("media")

    monkeypatch.setattr(backup_manager.db, "DATA_DIR", data_dir)
    monkeypatch.setattr(backup_manager.db, "USERS_DB_PATH", users_db)
    monkeypatch.setattr(backup_manager.db, "CORE_DB_PATH", core_db)
    monkeypatch.setattr(backup_manager, "BACKUP_ROOT", backup_root, raising=False)
    monkeypatch.setattr(backup_manager, "MEDIA_ROOT", media_root)
    monkeypatch.setattr(backup_manager, "discover_site_keys", lambda: ["JLL"])
    monkeypatch.setattr(backup_manager.db, "get_site_db_path", lambda site_key: stock_db)

    archive_path = backup_manager.create_backup_archive()

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "global/users.db" in names
    assert "media/sample.txt" in names


def test_backup_restore_includes_barcodes(monkeypatch, tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    source_data = tmp_path / "source_data"
    source_data.mkdir()
    source_media = tmp_path / "source_media"
    source_media.mkdir()
    source_barcodes = tmp_path / "source_assets" / "barcodes"
    source_barcodes.mkdir(parents=True)

    users_db = source_data / "users.db"
    core_db = source_data / "core.db"
    stock_db = source_data / "JLL.db"
    for path in (users_db, core_db, stock_db):
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY)")

    barcode_file = source_barcodes / "test.png"
    barcode_file.write_bytes(b"barcode-content")

    monkeypatch.setattr(backup_manager, "BACKUP_ROOT", backup_root, raising=False)
    monkeypatch.setattr(backup_manager.db, "DATA_DIR", source_data)
    monkeypatch.setattr(backup_manager.db, "USERS_DB_PATH", users_db)
    monkeypatch.setattr(backup_manager.db, "CORE_DB_PATH", core_db)
    monkeypatch.setattr(backup_manager, "MEDIA_ROOT", source_media)
    monkeypatch.setattr(backup_manager, "BARCODE_ASSETS_DIR", source_barcodes)
    monkeypatch.setattr(backup_manager, "discover_site_keys", lambda: ["JLL"])
    monkeypatch.setattr(backup_manager.db, "get_site_db_path", lambda site_key: stock_db)

    archive_path = backup_manager.create_backup_archive()

    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert "assets/barcodes/test.png" in names

    restore_data = tmp_path / "restore_data"
    restore_data.mkdir()
    restore_media = tmp_path / "restore_media"
    restore_media.mkdir()
    restore_barcodes = tmp_path / "restore_assets" / "barcodes"
    restore_barcodes.parent.mkdir(parents=True)

    monkeypatch.setattr(backup_manager.db, "DATA_DIR", restore_data)
    monkeypatch.setattr(backup_manager.db, "USERS_DB_PATH", restore_data / "users.db")
    monkeypatch.setattr(backup_manager.db, "CORE_DB_PATH", restore_data / "core.db")
    monkeypatch.setattr(
        backup_manager.db,
        "get_site_db_path",
        lambda site_key: restore_data / f"{site_key}.db",
    )
    monkeypatch.setattr(backup_manager, "MEDIA_ROOT", restore_media)
    monkeypatch.setattr(backup_manager, "BARCODE_ASSETS_DIR", restore_barcodes)
    monkeypatch.setattr(backup_manager.db, "init_databases", lambda: None)

    backup_manager.restore_backup_from_zip(archive_path)

    restored_file = restore_barcodes / "test.png"
    assert restored_file.exists()
    assert restored_file.read_bytes() == b"barcode-content"
