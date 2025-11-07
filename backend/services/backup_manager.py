"""Utilitaires de sauvegarde pour les bases de données."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from shutil import copy2, make_archive
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZipInfo

from backend.core import db

BACKUP_ROOT = Path(__file__).resolve().parent.parent / "backups"
BACKUP_ROOT.mkdir(parents=True, exist_ok=True)


def create_backup_archive() -> Path:
    """Crée une archive ZIP contenant les bases de données."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        stock_path = temp_dir / "stock.db"
        users_path = temp_dir / "users.db"
        copy2(db.STOCK_DB_PATH, stock_path)
        copy2(db.USERS_DB_PATH, users_path)
        base_name = BACKUP_ROOT / f"backup-{timestamp}"
        archive_path = Path(make_archive(str(base_name), "zip", tmpdir))
    return archive_path


class BackupImportError(Exception):
    """Exception levée lorsqu'une restauration échoue."""


def _ensure_safe_member(member: ZipInfo) -> None:
    filename = Path(member.filename)
    if filename.is_absolute() or ".." in filename.parts:
        raise BackupImportError("Archive invalide: chemin non autorisé")


def _restore_sqlite_db(source: Path, destination: Path) -> None:
    """Restore a SQLite database using the backup API.

    On Windows an open SQLite database file cannot be replaced directly on disk.
    Using the native backup API copies the content while keeping the target file
    open only for the duration of the backup, preventing ``PermissionError``
    when the application holds background connections. The target database is
    truncated automatically before the copy.

    The uploaded SQLite files come from temporary directories created during the
    tests.  On Windows these temporary files may stay locked for a short period
    if their URI representation is not normalized before connecting.  We build
    an explicit ``file:`` URI using a POSIX path so that SQLite never keeps an
    additional handle on the original file, allowing ``TemporaryDirectory`` to
    clean it up reliably on Windows.
    """

    source_uri = source.resolve().as_posix()
    with sqlite3.connect(f"file:{source_uri}?mode=ro&immutable=1", uri=True) as source_conn:
        with sqlite3.connect(destination) as dest_conn:
            source_conn.backup(dest_conn)


def restore_backup_from_zip(archive_path: Path) -> None:
    """Restaure les bases à partir d'une archive ZIP."""
    if not archive_path.exists():
        raise BackupImportError("Archive introuvable")

    with TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        try:
            with ZipFile(archive_path) as archive:
                for member in archive.infolist():
                    _ensure_safe_member(member)
                archive.extractall(temp_dir)
        except (BadZipFile, RuntimeError) as exc:
            raise BackupImportError("Archive de sauvegarde corrompue") from exc

        stock_candidates = list(temp_dir.rglob("stock.db"))
        users_candidates = list(temp_dir.rglob("users.db"))
        if not stock_candidates or not users_candidates:
            raise BackupImportError("Archive incomplète: bases manquantes")

        stock_source = stock_candidates[0]
        users_source = users_candidates[0]

        _restore_sqlite_db(stock_source, db.STOCK_DB_PATH)
        _restore_sqlite_db(users_source, db.USERS_DB_PATH)

    db.init_databases()
