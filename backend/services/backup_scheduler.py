"""Planificateur de sauvegardes automatiques."""
from __future__ import annotations

import asyncio
import logging
from configparser import ConfigParser
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from backend.core import models
from backend.services.backup_manager import create_backup_archive

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.ini"


class BackupScheduler:
    """Gère la planification des sauvegardes automatiques."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._schedule_event = asyncio.Event()
        self._schedule = models.BackupSchedule(enabled=False, days=[], time="02:00")
        self._day_numbers: set[int] = set()
        self._next_run: datetime | None = None
        self._last_run: datetime | None = None

    async def start(self) -> None:
        """Démarre la boucle de planification."""
        await self.reload_from_config()
        async with self._lock:
            if self._task and not self._task.done():
                return
            self._stop_event = asyncio.Event()
            self._schedule_event = asyncio.Event()
            self._task = asyncio.create_task(self._run())
            logger.info("Planificateur de sauvegardes initialisé")

    async def stop(self) -> None:
        """Arrête la boucle de planification."""
        async with self._lock:
            task = self._task
            if not task:
                return
            self._stop_event.set()
            self._schedule_event.set()
        await task
        async with self._lock:
            self._task = None
            logger.info("Planificateur de sauvegardes arrêté")

    async def reload_from_config(self) -> None:
        """Recharge la configuration depuis ``config.ini``."""
        parser = ConfigParser()
        parser.read(_CONFIG_PATH, encoding="utf-8")
        enabled = parser.getboolean("backup", "enabled", fallback=False)
        days_value = parser.get("backup", "days", fallback="")
        time_value = parser.get("backup", "time", fallback="02:00")
        raw_days = [part.strip() for part in days_value.split(",") if part.strip()]
        try:
            schedule = models.BackupSchedule(enabled=enabled, days=raw_days, time=time_value)
        except ValidationError as exc:
            logger.warning("Configuration de sauvegarde invalide, désactivation: %s", exc)
            schedule = models.BackupSchedule(enabled=False, days=[], time="02:00")
        await self._apply_schedule(schedule)

    async def update_schedule(self, schedule: models.BackupSchedule) -> None:
        """Enregistre et applique une nouvelle configuration."""
        self._write_schedule(schedule)
        await self._apply_schedule(schedule)

    async def get_status(self) -> models.BackupScheduleStatus:
        """Retourne l'état courant de la planification."""
        async with self._lock:
            schedule = self._schedule
            next_run = self._next_run
            last_run = self._last_run
        return models.BackupScheduleStatus(
            enabled=schedule.enabled,
            days=list(schedule.days),
            time=schedule.time,
            next_run=next_run,
            last_run=last_run,
        )

    async def _apply_schedule(self, schedule: models.BackupSchedule) -> None:
        async with self._lock:
            self._schedule = schedule
            self._day_numbers = {models.BACKUP_WEEKDAY_INDEX[day] for day in schedule.days}
            self._next_run = None
        self._schedule_event.set()

    def _write_schedule(self, schedule: models.BackupSchedule) -> None:
        parser = ConfigParser()
        parser.read(_CONFIG_PATH, encoding="utf-8")
        if not parser.has_section("backup"):
            parser.add_section("backup")
        parser.set("backup", "enabled", "true" if schedule.enabled else "false")
        parser.set("backup", "days", ",".join(schedule.days))
        parser.set("backup", "time", schedule.time)
        with _CONFIG_PATH.open("w", encoding="utf-8") as configfile:
            parser.write(configfile)

    async def _run(self) -> None:
        while True:
            if self._stop_event.is_set():
                break

            async with self._lock:
                schedule = self._schedule
                day_numbers = set(self._day_numbers)
                next_run = self._next_run

            if not schedule.enabled or not day_numbers:
                await self._wait_for_update()
                continue

            now = datetime.now()
            if next_run is None or next_run <= now:
                next_run = self._calculate_next_run(now, day_numbers, schedule.time)
                async with self._lock:
                    self._next_run = next_run

            if next_run is None:
                await self._wait_for_update()
                continue

            delay = max(0.0, (next_run - datetime.now()).total_seconds())
            sleep_task = asyncio.create_task(asyncio.sleep(delay))
            update_task = asyncio.create_task(self._schedule_event.wait())
            stop_task = asyncio.create_task(self._stop_event.wait())

            done, pending = await asyncio.wait(
                {sleep_task, update_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()

            if stop_task in done:
                break

            if update_task in done:
                self._schedule_event.clear()
                continue

            if sleep_task in done:
                await self._execute_backup()
                async with self._lock:
                    self._last_run = datetime.now()
                    self._next_run = None

        logger.info("Fin de la tâche de planification des sauvegardes")

    async def _wait_for_update(self) -> None:
        update_task = asyncio.create_task(self._schedule_event.wait())
        stop_task = asyncio.create_task(self._stop_event.wait())
        done, pending = await asyncio.wait(
            {update_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        if update_task in done:
            self._schedule_event.clear()

    async def _execute_backup(self) -> None:
        try:
            archive_path = create_backup_archive()
            logger.info("Sauvegarde automatique créée: %s", archive_path.name)
        except Exception:  # pragma: no cover - journalisation d'erreur
            logger.exception("Échec de la sauvegarde automatique")

    def _calculate_next_run(
        self, reference: datetime, day_numbers: set[int], time_value: str
    ) -> datetime | None:
        if not day_numbers:
            return None
        try:
            hour, minute = [int(part) for part in time_value.split(":", 1)]
        except ValueError:
            logger.error("Heure de sauvegarde invalide: %s", time_value)
            return None

        target_time = reference.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if reference.weekday() in day_numbers and target_time > reference:
            return target_time

        for offset in range(1, 8):
            candidate = reference + timedelta(days=offset)
            candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate.weekday() in day_numbers:
                return candidate
        return None


backup_scheduler = BackupScheduler()
