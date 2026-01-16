"""Utilitaires de sauvegarde pour les bases de données."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, closing
from datetime import datetime
from importlib import metadata
from pathlib import Path
import sqlite3
from shutil import copy2, copytree, make_archive, rmtree
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile, ZipInfo

from backend.core import db
from backend.core.storage import MEDIA_ROOT

MESSAGE_ARCHIVE_ROOT = db.DATA_DIR / "message_archive"
BARCODE_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "barcodes"

logger = logging.getLogger(__name__)

BACKUP_ROOT = Path(__file__).resolve().parent.parent / "backups"
BACKUP_ROOT.mkdir(parents=True, exist_ok=True)

MAX_BACKUP_FILES = 3


def create_backup_archive(
    site_key: str | None = None, retention_count: int | None = None
) -> Path:
    """Crée une archive ZIP contenant toutes les données."""
    return run_backup_all(retention_count=retention_count)


def discover_site_keys() -> list[str]:
    """Retourne la liste exhaustive des sites configurés."""

    registry = getattr(db, "SITES", None)
    if isinstance(registry, dict):
        return sorted({str(key).upper() for key in registry})
    if isinstance(registry, (list, tuple, set, frozenset)):
        return sorted({str(key).upper() for key in registry})

    discovered: set[str] = set()
    try:
        discovered.update(db.list_site_keys())
    except Exception:
        discovered.update(db.SITE_KEYS)

    for folder in (db.DATA_DIR / "sites", db.DATA_DIR):
        if not folder.exists():
            continue
        for entry in folder.glob("*.db"):
            if entry in {db.USERS_DB_PATH, db.CORE_DB_PATH}:
                continue
            if entry == db.STOCK_DB_PATH:
                discovered.add(db.DEFAULT_SITE_KEY)
            else:
                discovered.add(entry.stem.upper())

    if not discovered:
        discovered.update(db.SITE_KEYS)
    return sorted(discovered)


def get_backup_targets() -> dict[str, object]:
    site_keys = discover_site_keys()
    site_dbs: dict[str, list[Path]] = {}
    for site_key in site_keys:
        site_dbs[site_key] = [db.get_site_db_path(site_key)]

    global_dbs = [db.USERS_DB_PATH]
    if db.CORE_DB_PATH.exists():
        global_dbs.append(db.CORE_DB_PATH)

    folders: list[tuple[str, Path]] = [
        ("media", MEDIA_ROOT),
        ("message_archive", MESSAGE_ARCHIVE_ROOT),
        ("assets/barcodes", BARCODE_ASSETS_DIR),
    ]
    for label in ("archives", "exports", "imports"):
        candidate = db.DATA_DIR / label
        if candidate.exists():
            folders.append((label, candidate))

    return {"global_dbs": global_dbs, "site_dbs": site_dbs, "folders": folders}


def _get_app_version() -> str:
    try:
        return metadata.version("GestionStock")
    except metadata.PackageNotFoundError:
        return "unknown"


def _write_manifest(root: Path, targets: dict[str, object]) -> None:
    entries: list[dict[str, object]] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        relative = file_path.relative_to(root).as_posix()
        data = file_path.read_bytes()
        entries.append(
            {
                "path": relative,
                "size": file_path.stat().st_size,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    targets_payload: list[dict[str, str]] = []
    for db_path in targets.get("global_dbs", []):
        targets_payload.append(
            {"type": "database", "path": f"global/{Path(db_path).name}"}
        )
    for site_key, db_paths in targets.get("site_dbs", {}).items():
        for db_path in db_paths:
            targets_payload.append(
                {
                    "type": "database",
                    "path": f"sites/{site_key}/{Path(db_path).name}",
                }
            )
    for label, _folder in targets.get("folders", []):
        targets_payload.append({"type": "folder", "path": str(label)})

    payload = {
        "created_at": datetime.now().isoformat(),
        "app_version": _get_app_version(),
        "targets": targets_payload,
        "files": entries,
    }
    (root / "manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _backup_sqlite_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return
    try:
        with _open_sqlite_readonly(source) as source_conn:
            with closing(sqlite3.connect(destination)) as dest_conn:
                source_conn.backup(dest_conn)
                return
    except (AttributeError, sqlite3.Error):
        pass

    try:
        with closing(sqlite3.connect(source)) as conn:
            conn.execute("VACUUM INTO ?", (str(destination),))
            return
    except sqlite3.Error:
        pass

    with closing(sqlite3.connect(source)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        copy2(source, destination)
        conn.commit()


def run_backup_all(retention_count: int | None = None) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    with TemporaryDirectory() as tmpdir:
        temp_dir = Path(tmpdir)
        targets = get_backup_targets()
        global_dir = temp_dir / "global"
        sites_dir = temp_dir / "sites"
        global_dir.mkdir(parents=True, exist_ok=True)
        sites_dir.mkdir(parents=True, exist_ok=True)

        for db_path in targets["global_dbs"]:
            _backup_sqlite_file(Path(db_path), global_dir / Path(db_path).name)

        for site_key, db_paths in targets["site_dbs"].items():
            site_folder = sites_dir / site_key
            site_folder.mkdir(parents=True, exist_ok=True)
            for db_path in db_paths:
                _backup_sqlite_file(Path(db_path), site_folder / Path(db_path).name)

        for label, folder in targets["folders"]:
            target = temp_dir / label
            if folder.exists():
                copytree(folder, target, dirs_exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)

        _write_manifest(temp_dir, targets)
        base_name = BACKUP_ROOT / f"backup-{timestamp}"
        archive_path = Path(make_archive(str(base_name), "zip", tmpdir))

    _prune_old_backups(
        retention_count if retention_count is not None else MAX_BACKUP_FILES,
        prefix="backup-",
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

        users_candidates = list(temp_dir.rglob("users.db"))
        core_candidates = list(temp_dir.rglob("core.db"))
        sites_root = temp_dir / "sites"
        site_candidates = list(sites_root.glob("*.db"))
        site_folder_candidates = list(sites_root.glob("*/*.db"))
        stock_candidates = list(temp_dir.rglob("stock.db"))
        if not users_candidates:
            raise BackupImportError("Archive incomplète: base utilisateurs manquante")

        users_source = users_candidates[0]
        _verify_sqlite_database(users_source)
        _restore_sqlite_db(users_source, db.USERS_DB_PATH)

        if core_candidates:
            _verify_sqlite_database(core_candidates[0])
            _restore_sqlite_db(core_candidates[0], db.CORE_DB_PATH)

        if site_candidates:
            for site_path in site_candidates:
                site_key = site_path.stem.upper()
                _verify_sqlite_database(site_path)
                _restore_sqlite_db(site_path, db.get_site_db_path(site_key))
        elif site_folder_candidates:
            for site_path in site_folder_candidates:
                site_key = site_path.parent.name.upper()
                _verify_sqlite_database(site_path)
                _restore_sqlite_db(site_path, db.get_site_db_path(site_key))
        elif stock_candidates:
            stock_source = stock_candidates[0]
            _verify_sqlite_database(stock_source)
            _restore_sqlite_db(stock_source, db.get_site_db_path("JLL"))

        for label, destination in get_backup_targets()["folders"]:
            source = temp_dir / label
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    rmtree(destination)
                except FileNotFoundError:
                    pass
                copytree(source, destination, dirs_exist_ok=True)
            else:
                destination.mkdir(parents=True, exist_ok=True)

    db.init_databases()
