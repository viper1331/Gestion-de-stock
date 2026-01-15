"""Planificateur de sauvegardes automatiques."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.core import db, models
from backend.services.backup_manager import create_backup_archive
from backend.services.backup_settings import load_backup_settings_from_db, save_backup_settings

logger = logging.getLogger(__name__)


@dataclass
class SiteBackupState:
    enabled: bool = False
    interval_minutes: int = 0
    retention_count: int = 0
    last_applied_at: datetime | None = None
    running: bool = False
    task: asyncio.Task[None] | None = None


class BackupScheduler:
    """Gère la planification des sauvegardes automatiques par site."""

    def __init__(self) -> None:
        self._init_state_if_needed()

    def _init_state_if_needed(self) -> None:
        if not hasattr(self, "_lock") or self._lock is None:
            self._lock = asyncio.Lock()
        if not hasattr(self, "_update_mutex") or self._update_mutex is None:
            self._update_mutex = asyncio.Lock()
        if not hasattr(self, "_states") or self._states is None:
            self._states = {}
        if not hasattr(self, "_settings") or self._settings is None:
            self._settings = {}
        if not hasattr(self, "_tasks") or self._tasks is None:
            self._tasks = {}
        if not hasattr(self, "_stop_events") or self._stop_events is None:
            self._stop_events = {}
        if not hasattr(self, "_update_events") or self._update_events is None:
            self._update_events = {}
        if not hasattr(self, "_next_run") or self._next_run is None:
            self._next_run = {}
        if not hasattr(self, "_last_run") or self._last_run is None:
            self._last_run = {}
        if not hasattr(self, "_started"):
            self._started = False
        if not hasattr(self, "_runtime_loop"):
            self._runtime_loop = None

    async def start(self) -> None:
        """Démarre les planificateurs pour chaque site."""
        self._init_state_if_needed()
        self._runtime_loop = asyncio.get_running_loop()
        self._started = True
        await self.reload_from_db()
        logger.info("Planificateur de sauvegardes initialisé")

    async def stop(self) -> None:
        """Arrête toutes les planifications."""
        self._init_state_if_needed()
        async with self._lock:
            site_keys = list(self._states.keys())
        for site_key in site_keys:
            await self._stop_site_task(site_key)
        self._started = False
        self._runtime_loop = None
        logger.info("Planificateur de sauvegardes arrêté")

    async def reload_from_db(self) -> None:
        """Recharge la configuration depuis les bases sites."""
        self._init_state_if_needed()
        for site_key in db.list_site_keys():
            settings = load_backup_settings_from_db(site_key)
            async with self._lock:
                self._settings[site_key] = settings
            try:
                await self._apply_settings(site_key, settings, source="reload")
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
        self._init_state_if_needed()
        async with self._update_mutex:
            save_backup_settings(site_key, settings)
            await self._apply_settings(site_key, settings, source="update")

    async def get_status(self, site_key: str) -> models.BackupSettingsStatus:
        """Retourne l'état courant de la planification."""
        self._init_state_if_needed()
        async with self._lock:
            state = self._states.get(site_key)
            if state is None:
                settings = load_backup_settings_from_db(site_key)
                state = SiteBackupState(
                    enabled=settings.enabled,
                    interval_minutes=settings.interval_minutes,
                    retention_count=settings.retention_count,
                    last_applied_at=datetime.now(),
                )
                self._states[site_key] = state
            next_run = self._next_run.get(site_key)
            last_run = self._last_run.get(site_key)
        return models.BackupSettingsStatus(
            enabled=state.enabled,
            interval_minutes=state.interval_minutes,
            retention_count=state.retention_count,
            next_run=next_run,
            last_run=last_run,
        )

    async def get_job_count(self, site_key: str) -> int:
        self._init_state_if_needed()
        await self._ensure_task(site_key)
        async with self._lock:
            task = self._tasks.get(site_key)
            if task is None or task.done():
                return 0
            try:
                task_loop = task.get_loop()
            except RuntimeError:
                return 0
            if task_loop.is_closed():
                return 0
            return 1

    async def _ensure_task(self, site_key: str) -> None:
        self._init_state_if_needed()
        async with self._lock:
            settings = self._settings.get(site_key)
        if settings is None:
            settings = load_backup_settings_from_db(site_key)
            async with self._lock:
                self._settings[site_key] = settings
        async with self._lock:
            state = self._states.get(site_key)
            if state is None:
                state = SiteBackupState()
                self._states[site_key] = state
            state.enabled = settings.enabled
            state.interval_minutes = settings.interval_minutes
            state.retention_count = settings.retention_count
            task = self._tasks.get(site_key)
        if not settings.enabled:
            if task and not task.done():
                await self._stop_site_task(site_key)
            return
        if task and not task.done():
            try:
                task_loop = task.get_loop()
            except RuntimeError:
                task_loop = None
            if task_loop is not None and not task_loop.is_closed():
                return
        await self._stop_site_task(site_key)
        async with self._lock:
            if not settings.enabled:
                return
            stop_event = asyncio.Event()
            update_event = asyncio.Event()
            self._stop_events[site_key] = stop_event
            self._update_events[site_key] = update_event
            self._next_run[site_key] = None
            task = asyncio.create_task(
                self._run_site(site_key, stop_event, update_event)
            )
            self._tasks[site_key] = task
            state = self._states.setdefault(site_key, SiteBackupState())
            state.task = task
            state.running = True

    async def _apply_settings(
        self,
        site_key: str,
        settings: models.BackupSettings,
        *,
        source: str | None = None,
    ) -> None:
        self._init_state_if_needed()
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
            state = self._states.get(site_key)
            if state is None:
                state = SiteBackupState()
                self._states[site_key] = state
            changed = (
                state.enabled != settings.enabled
                or state.interval_minutes != settings.interval_minutes
                or state.retention_count != settings.retention_count
            )
            state.enabled = settings.enabled
            state.interval_minutes = settings.interval_minutes
            state.retention_count = settings.retention_count
            state.last_applied_at = datetime.now()
            self._next_run[site_key] = None
            if state.running and site_key in self._update_events:
                self._update_events[site_key].set()
        if changed:
            logger.info("Réglages de sauvegarde mis à jour pour %s", site_key)
            if source:
                logger.debug(
                    "Source des réglages de sauvegarde pour %s: %s",
                    site_key,
                    source,
                )
        if self._started:
            if settings.enabled:
                await self._ensure_site_task(site_key)
            else:
                await self._stop_site_task(site_key)

    async def _stop_site_task(self, site_key: str) -> None:
        self._init_state_if_needed()
        async with self._lock:
            state = self._states.get(site_key)
            task = self._tasks.get(site_key) or (state.task if state else None)
            stop_event = self._stop_events.get(site_key)
            update_event = self._update_events.get(site_key)
            if task is None:
                return
            task_loop = task.get_loop()
        current_loop: asyncio.AbstractEventLoop | None = None
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is not None and task_loop is current_loop:
            if stop_event:
                stop_event.set()
            if update_event:
                update_event.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("Annulation absorbée pour la tâche %s", site_key)
            except Exception:  # pragma: no cover - journalisation d'erreur
                logger.debug("Erreur absorbée lors de l'arrêt de la tâche %s", site_key)
        else:
            task.cancel()
        async with self._lock:
            state = self._states.get(site_key)
            if state and state.task is task:
                state.task = None
                state.running = False
            if self._tasks.get(site_key) is task:
                self._tasks.pop(site_key, None)
            self._stop_events.pop(site_key, None)
            self._update_events.pop(site_key, None)
            self._next_run.pop(site_key, None)
        logger.info("Tâche de sauvegarde arrêtée pour %s", site_key)

    async def _ensure_site_task(self, site_key: str) -> None:
        self._init_state_if_needed()
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._runtime_loop is not None and current_loop is not self._runtime_loop:
            logger.debug(
                "Boucle différente détectée pour %s; création de tâche ignorée",
                site_key,
            )
            return
        async with self._lock:
            state = self._states.get(site_key)
            if state is None or not state.enabled:
                return
            task = state.task
        if task is not None and not task.done():
            if task.get_loop() is current_loop:
                return
        await self._stop_site_task(site_key)
        stop_event = asyncio.Event()
        update_event = asyncio.Event()
        async with self._lock:
            self._stop_events[site_key] = stop_event
            self._update_events[site_key] = update_event
            task = asyncio.create_task(
                self._run_site(site_key, stop_event, update_event)
            )
            self._tasks[site_key] = task
            state = self._states.setdefault(site_key, SiteBackupState())
            state.task = task
            state.running = True
        logger.info("Tâche de sauvegarde démarrée pour %s", site_key)

    async def _run_site(
        self, site_key: str, stop_event: asyncio.Event, update_event: asyncio.Event
    ) -> None:
        try:
            while True:
                if stop_event.is_set():
                    break
                async with self._lock:
                    state = self._states.get(site_key)
                    next_run = self._next_run.get(site_key)
                    last_run = self._last_run.get(site_key)
                if state is None or not state.enabled:
                    await self._wait_for_update(stop_event, update_event)
                    continue

                now = datetime.now()
                if next_run is None or next_run <= now:
                    reference = last_run or now
                    next_run = reference + timedelta(minutes=state.interval_minutes)
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
            async with self._lock:
                state = self._states.get(site_key)
                if state and state.task is asyncio.current_task():
                    state.task = None
                    state.running = False
                if self._tasks.get(site_key) is asyncio.current_task():
                    self._tasks.pop(site_key, None)

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
            state = self._states.get(site_key)
        if state is None:
            return
        try:
            archive_path = create_backup_archive(
                site_key=site_key, retention_count=state.retention_count
            )
            logger.info("Sauvegarde automatique créée pour %s: %s", site_key, archive_path.name)
        except Exception:  # pragma: no cover - journalisation d'erreur
            logger.exception("Échec de la sauvegarde automatique pour %s", site_key)


backup_scheduler = BackupScheduler()
