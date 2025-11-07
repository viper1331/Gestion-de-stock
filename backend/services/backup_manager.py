"""Utilitaires de sauvegarde pour les bases de données."""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
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


@contextmanager
def _open_sqlite_readonly(path: Path) -> Iterator[sqlite3.Connection]:
    """Return a context-managed SQLite connection opened in read-only mode."""

    if os.name == "nt":  # Windows cannot reliably use immutable URIs
        # ``sqlite3`` expects Windows paths to be prefixed with ``/`` when
        # using the URI form.  Opening the database in read-only mode avoids
        # SQLite grabbing a persistent write handle which prevents temporary
        # directories from being cleaned up after the tests on Windows.
        source_path = path.resolve().as_posix()
        uri = f"file:/{source_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        source_uri = path.resolve().as_uri()
        immutable_uri = f"{source_uri}?mode=ro&immutable=1"
        conn = sqlite3.connect(immutable_uri, uri=True)

    try:
        conn.execute("PRAGMA query_only = 1")
        yield conn
    finally:
        conn.close()


def _restore_sqlite_db(source: Path, destination: Path) -> None:
    """Restore a SQLite database using the backup API.

    On Windows an open SQLite database file cannot be replaced directly on disk.
    Using the native backup API copies the content while keeping the target file
    open only for the duration of the backup, preventing ``PermissionError``
    when the application holds background connections. The target database is
    truncated automatically before the copy.

    The uploaded SQLite files come from temporary directories created during the
    tests.  Opening them in read-only mode differs slightly between platforms:
    on Windows we have to use a regular connection and enable ``PRAGMA
    query_only`` to avoid the driver keeping a write handle, while on POSIX
    systems we rely on the immutable URI variant to prevent SQLite from holding
    onto the source file beyond the backup call.
    """

    # ``sqlite3.Connection.backup`` keeps references between the source and
    # destination connections for the duration of the call.  On Windows the
    # operating system can keep the source database locked until every related
    # handle is closed, which breaks removal of the temporary directory used by
    # the tests.  Managing both connections with an ``ExitStack`` guarantees
    # that the destination connection is closed before the read-only source
    # connection, releasing the handle on the extracted file as soon as the
    # function exits.
    with ExitStack() as stack:
        source_conn = stack.enter_context(_open_sqlite_readonly(source))
        dest_conn = stack.enter_context(sqlite3.connect(destination))
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
