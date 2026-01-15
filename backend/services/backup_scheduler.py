"""Planificateur de sauvegardes automatiques."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from backend.core import db, models
from backend.services.backup_manager import create_backup_archive
from backend.services.backup_settings import load_backup_settings_from_db, save_backup_settings

logger = logging.getLogger(__name__)


class BackupScheduler:
    """Gère la planification des sauvegardes automatiques par site."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._update_mutex = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self._update_events: dict[str, asyncio.Event] = {}
        self._settings: dict[str, models.BackupSettings] = {}
        self._next_run: dict[str, datetime | None] = {}
        self._last_run: dict[str, datetime | None] = {}

    async def start(self) -> None:
        """Démarre les planificateurs pour chaque site."""
        await self.reload_from_db()
        logger.info("Planificateur de sauvegardes initialisé")

    async def stop(self) -> None:
        """Arrête toutes les planifications."""
        async with self._lock:
            site_keys = list(self._tasks.keys())
        for site_key in site_keys:
            await self._stop_site_task(site_key)
        logger.info("Planificateur de sauvegardes arrêté")

    async def reload_from_db(self) -> None:
        """Recharge la configuration depuis les bases sites."""
        for site_key in db.list_site_keys():
            settings = load_backup_settings_from_db(site_key)
            try:
                await self._apply_settings(site_key, settings)
            except asyncio.CancelledError:
                logger.debug(
                    "Annulation ignorée lors du rechargement des réglages pour %s", site_key
                )
            except Exception:  # pragma: no cover - journalisation d'erreur
                logger.exception(
                    "Erreur lors du rechargement des réglages de sauvegarde pour %s",
                    site_key,
                )

    async def update_settings(self, site_key: str, settings: models.BackupSettings) -> None:
        """Enregistre et applique une nouvelle configuration."""
        async with self._update_mutex:
            save_backup_settings(site_key, settings)
            await self._apply_settings(site_key, settings)

    async def get_status(self, site_key: str) -> models.BackupSettingsStatus:
        """Retourne l'état courant de la planification."""
        async with self._lock:
            settings = self._settings.get(site_key)
            if settings is None:
                settings = load_backup_settings_from_db(site_key)
                self._settings[site_key] = settings
            next_run = self._next_run.get(site_key)
            last_run = self._last_run.get(site_key)
        return models.BackupSettingsStatus(
            enabled=settings.enabled,
            interval_minutes=settings.interval_minutes,
            retention_count=settings.retention_count,
            next_run=next_run,
            last_run=last_run,
        )

    async def get_job_count(self, site_key: str) -> int:
        async with self._lock:
            task = self._tasks.get(site_key)
            if task and not task.done():
                return 1
            return 0

    async def _apply_settings(self, site_key: str, settings: models.BackupSettings) -> None:
        try:
            await self._stop_site_task(site_key)
        except asyncio.CancelledError:
            logger.debug(
                "Annulation ignorée lors de l'arrêt de la tâche de %s", site_key
            )
        except Exception:  # pragma: no cover - journalisation d'erreur
            logger.exception("Erreur lors de l'arrêt de la tâche de %s", site_key)
        async with self._lock:
            self._settings[site_key] = settings
            self._next_run[site_key] = None
            if not settings.enabled:
                self._update_events.pop(site_key, None)
                self._stop_events.pop(site_key, None)
                return
            stop_event = asyncio.Event()
            update_event = asyncio.Event()
            self._stop_events[site_key] = stop_event
            self._update_events[site_key] = update_event
            self._tasks[site_key] = asyncio.create_task(
                self._run_site(site_key, stop_event, update_event)
            )
        logger.debug("Planificateur mis à jour pour le site %s", site_key)

    async def _stop_site_task(self, site_key: str) -> None:
        async with self._lock:
            task = self._tasks.get(site_key)
            stop_event = self._stop_events.get(site_key)
            update_event = self._update_events.get(site_key)
            if task is None:
                return
            if stop_event:
                stop_event.set()
            if update_event:
                update_event.set()
        should_await = False
        try:
            current_loop = asyncio.get_running_loop()
            task_loop = task.get_loop()
            if task_loop.is_closed() or task_loop is not current_loop:
                task.cancel()
            else:
                task.cancel()
                should_await = True
        except RuntimeError:
            task.cancel()
        if should_await:
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("Annulation absorbée pour la tâche %s", site_key)
            except Exception:  # pragma: no cover - journalisation d'erreur
                logger.debug("Erreur absorbée lors de l'arrêt de la tâche %s", site_key)
        async with self._lock:
            if self._tasks.get(site_key) is task:
                self._tasks.pop(site_key, None)
            self._stop_events.pop(site_key, None)
            self._update_events.pop(site_key, None)
            self._next_run.pop(site_key, None)

    async def _run_site(
        self, site_key: str, stop_event: asyncio.Event, update_event: asyncio.Event
    ) -> None:
        try:
            while True:
                if stop_event.is_set():
                    break
                async with self._lock:
                    settings = self._settings.get(site_key)
                    next_run = self._next_run.get(site_key)
                    last_run = self._last_run.get(site_key)
                if settings is None or not settings.enabled:
                    await self._wait_for_update(stop_event, update_event)
                    continue

                now = datetime.now()
                if next_run is None or next_run <= now:
                    reference = last_run or now
                    next_run = reference + timedelta(minutes=settings.interval_minutes)
                    async with self._lock:
                        self._next_run[site_key] = next_run

                delay = max(0.0, (next_run - datetime.now()).total_seconds())
                sleep_task = asyncio.create_task(asyncio.sleep(delay))
                update_task = asyncio.create_task(update_event.wait())
                stop_task = asyncio.create_task(stop_event.wait())

                try:
                    done, pending = await asyncio.wait(
                        {sleep_task, update_task, stop_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError:
                    for task in (sleep_task, update_task, stop_task):
                        task.cancel()
                    raise
                for task in pending:
                    task.cancel()

                if stop_task in done:
                    break

                if update_task in done:
                    update_event.clear()
                    continue

                if sleep_task in done:
                    await self._execute_backup(site_key)
                    async with self._lock:
                        self._last_run[site_key] = datetime.now()
                        self._next_run[site_key] = None
        except asyncio.CancelledError:
            logger.debug("Annulation absorbée pour la tâche de %s", site_key)
        finally:
            stop_event.set()
            update_event.set()
            logger.debug(
                "Fin de la tâche de planification des sauvegardes pour %s", site_key
            )

    async def _wait_for_update(
        self, stop_event: asyncio.Event, update_event: asyncio.Event
    ) -> None:
        update_task = asyncio.create_task(update_event.wait())
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {update_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if update_task in done:
            update_event.clear()

    async def _execute_backup(self, site_key: str) -> None:
        async with self._lock:
            settings = self._settings.get(site_key)
        if settings is None:
            return
        try:
            archive_path = create_backup_archive(
                site_key=site_key, retention_count=settings.retention_count
            )
            logger.info("Sauvegarde automatique créée pour %s: %s", site_key, archive_path.name)
        except Exception:  # pragma: no cover - journalisation d'erreur
            logger.exception("Échec de la sauvegarde automatique pour %s", site_key)


backup_scheduler = BackupScheduler()
