"""Utilitaires de sauvegarde pour les bases de données."""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, closing
from datetime import datetime
from pathlib import Path
import sqlite3
from shutil import copy2, copytree, make_archive, rmtree
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZipInfo

from backend.core import db
from backend.core.storage import MEDIA_ROOT

logger = logging.getLogger(__name__)

BACKUP_ROOT = Path(__file__).resolve().parent.parent / "backups"
BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

MAX_BACKUP_FILES = 3


def create_backup_archive(
    site_key: str | None = None, retention_count: int | None = None
) -> Path:
    """Crée une archive ZIP contenant les bases de données."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    normalized_site = site_key.upper() if site_key else None
    with TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        users_path = temp_dir / "users.db"
        copy2(db.USERS_DB_PATH, users_path)
        if db.CORE_DB_PATH.exists():
            core_path = temp_dir / "core.db"
            copy2(db.CORE_DB_PATH, core_path)
        sites_dir = temp_dir / "sites"
        sites_dir.mkdir(parents=True, exist_ok=True)
        if normalized_site:
            site_paths = {normalized_site: db.get_site_db_path(normalized_site)}
        else:
            site_paths = db.list_site_db_paths()
        for site_key_value, site_path in site_paths.items():
            if site_path.exists():
                copy2(site_path, sites_dir / f"{site_key_value}.db")
        if normalized_site:
            stock_source = site_paths.get(normalized_site, db.STOCK_DB_PATH)
        else:
            stock_source = site_paths.get("JLL", db.STOCK_DB_PATH)
        if stock_source.exists():
            copy2(stock_source, temp_dir / "stock.db")
        media_target = temp_dir / "media"
        if MEDIA_ROOT.exists():
            copytree(MEDIA_ROOT, media_target, dirs_exist_ok=True)
        prefix = f"backup-{normalized_site}-" if normalized_site else "backup-"
        base_name = BACKUP_ROOT / f"{prefix}{timestamp}"
        archive_path = Path(make_archive(str(base_name), "zip", tmpdir))
    _prune_old_backups(
        retention_count if retention_count is not None else MAX_BACKUP_FILES,
        prefix=f"backup-{normalized_site}-" if normalized_site else "backup-",
    )
    return archive_path


def _prune_old_backups(max_count: int, *, prefix: str = "backup-") -> None:
    """Supprime les anciennes sauvegardes en excès."""

    if max_count <= 0:
        return

    try:
        backups = sorted(
            BACKUP_ROOT.glob(f"{prefix}*.zip"),
            key=lambda path: (path.name, path.stat().st_mtime),
            reverse=True,
        )
    except OSError as exc:  # pragma: no cover - cas inattendu
        logger.warning("Impossible d'énumérer les sauvegardes existantes: %s", exc)
        return

    for outdated in backups[max_count:]:
        try:
            outdated.unlink()
        except OSError as exc:  # pragma: no cover - journalisation d'erreur
            logger.warning("Impossible de supprimer l'ancienne sauvegarde %s: %s", outdated.name, exc)


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
    else:
        source_uri = path.resolve().as_uri()
        uri = f"{source_uri}?mode=ro&immutable=1"

    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.execute("PRAGMA query_only = 1")
        yield conn


def _verify_sqlite_database(path: Path) -> None:
    """Ensure the extracted SQLite database is structurally valid."""

    with _open_sqlite_readonly(path) as conn:
        cur = conn.execute("PRAGMA quick_check")
        result = cur.fetchone()
        if not result or result[0] != "ok":
            raise BackupImportError("Archive corrompue: base de données invalide")


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
    # the tests.  Nesting the context managers ensures the destination
    # connection is closed before the read-only source connection, releasing the
    # handle on the extracted file as soon as the function exits.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _open_sqlite_readonly(source) as source_conn:
        # ``sqlite3.Connection`` implements the context manager protocol but does
        # not automatically close the database when leaving the ``with`` block.
        # ``closing`` guarantees that the destination handle is released before
        # the read-only source connection, which is required on Windows to allow
        # temporary files to be deleted reliably after the restoration tests.
        with closing(sqlite3.connect(destination)) as dest_conn:
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
        core_candidates = list(temp_dir.rglob("core.db"))
        site_candidates = list((temp_dir / "sites").glob("*.db"))
        if not stock_candidates or not users_candidates:
            raise BackupImportError("Archive incomplète: bases manquantes")

        stock_source = stock_candidates[0]
        users_source = users_candidates[0]
        media_source = temp_dir / "media"

        _verify_sqlite_database(stock_source)
        _verify_sqlite_database(users_source)

        if core_candidates:
            _verify_sqlite_database(core_candidates[0])
            _restore_sqlite_db(core_candidates[0], db.CORE_DB_PATH)
        if site_candidates:
            for site_path in site_candidates:
                site_key = site_path.stem.upper()
                if site_key not in db.SITE_KEYS:
                    continue
                _verify_sqlite_database(site_path)
                _restore_sqlite_db(site_path, db.get_site_db_path(site_key))
        else:
            _restore_sqlite_db(stock_source, db.get_site_db_path("JLL"))
        _restore_sqlite_db(users_source, db.USERS_DB_PATH)

        if media_source.exists():
            try:
                rmtree(MEDIA_ROOT)
            except FileNotFoundError:
                pass
            copytree(media_source, MEDIA_ROOT, dirs_exist_ok=True)
        else:
            MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

    db.init_databases()
