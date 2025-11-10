from datetime import datetime, timedelta

import pytest

from backend.services import backup_manager


@pytest.mark.usefixtures("tmp_path")
def test_create_backup_archive_limits_backup_count(monkeypatch, tmp_path):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    monkeypatch.setattr(backup_manager, "BACKUP_ROOT", backup_root, raising=False)

    stock_db = tmp_path / "stock.db"
    users_db = tmp_path / "users.db"
    stock_db.write_text("stock")
    users_db.write_text("users")
    monkeypatch.setattr(backup_manager.db, "STOCK_DB_PATH", stock_db)
    monkeypatch.setattr(backup_manager.db, "USERS_DB_PATH", users_db)

    timestamps = [datetime(2024, 1, 1, 12, 0, 0) + timedelta(seconds=i) for i in range(5)]

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

    expected = [
        f"backup-{ts.strftime('%Y%m%d-%H%M%S')}.zip" for ts in timestamps[-backup_manager.MAX_BACKUP_FILES :]
    ]
    assert backups == sorted(expected)
