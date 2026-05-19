"""Time-based content scheduler (WIB by default).

Resolves the active content category for the current hour and emits an
event whenever the schedule slot changes.  Designed to run inside a
background thread alongside the content generator.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

from config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScheduleSlot:
    name: str
    start_hour: int
    end_hour: int  # exclusive
    primary_category: str
    secondary_category: Optional[str] = None
    mood: str = "default"

    def covers(self, hour: int) -> bool:
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        # Wrap around midnight
        return hour >= self.start_hour or hour < self.end_hour


DEFAULT_SCHEDULE: tuple[ScheduleSlot, ...] = (
    ScheduleSlot(
        name="morning_energy",
        start_hour=6,
        end_hour=12,
        primary_category="MOTIVATIONAL_QUOTES",
        mood="energik",
    ),
    ScheduleSlot(
        name="afternoon_focus",
        start_hour=12,
        end_hour=18,
        primary_category="STUDY_WITH_ME",
        secondary_category="TRIVIA_QNA",
        mood="fokus",
    ),
    ScheduleSlot(
        name="evening_chill",
        start_hour=18,
        end_hour=22,
        primary_category="LOFI_FACTS",
        mood="santai",
    ),
    ScheduleSlot(
        name="night_calm",
        start_hour=22,
        end_hour=6,
        primary_category="MEDITATION_GUIDE",
        mood="lo-fi calm",
    ),
)


class ContentScheduler:
    """Resolve the current schedule slot and notify subscribers on change."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.slots: tuple[ScheduleSlot, ...] = DEFAULT_SCHEDULE
        self._tz = self._resolve_timezone(config.timezone)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listeners: list[Callable[[ScheduleSlot], None]] = []
        self._current_slot: Optional[ScheduleSlot] = None
        self._toggle = False  # for slots with secondary categories

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #
    def add_listener(self, callback: Callable[[ScheduleSlot], None]) -> None:
        with self._lock:
            self._listeners.append(callback)

    def current_slot(self) -> ScheduleSlot:
        hour = datetime.now(tz=self._tz).hour
        for slot in self.slots:
            if slot.covers(hour):
                return slot
        return self.slots[0]

    def current_category(self) -> str:
        """Return the active category, alternating if secondary is set."""
        slot = self.current_slot()
        if slot.secondary_category is None:
            return slot.primary_category
        with self._lock:
            category = (
                slot.secondary_category if self._toggle else slot.primary_category
            )
            self._toggle = not self._toggle
        return category

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="content-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        # Emit initial slot once so listeners can sync
        self._maybe_emit(self.current_slot())
        while not self._stop_event.is_set():
            try:
                slot = self.current_slot()
                self._maybe_emit(slot)
            except Exception:
                logger.exception("Scheduler tick error")
            # Check every 30s — granular enough for hourly slots
            if self._stop_event.wait(30):
                return

    def _maybe_emit(self, slot: ScheduleSlot) -> None:
        with self._lock:
            if self._current_slot is not None and self._current_slot.name == slot.name:
                return
            self._current_slot = slot
            listeners = list(self._listeners)
        logger.info(
            "Schedule slot aktif: %s (kategori utama %s, mood=%s)",
            slot.name,
            slot.primary_category,
            slot.mood,
        )
        for listener in listeners:
            try:
                listener(slot)
            except Exception:
                logger.exception("Listener scheduler gagal")

    def _resolve_timezone(self, tz_name: str) -> timezone:
        try:
            from zoneinfo import ZoneInfo  # type: ignore

            return ZoneInfo(tz_name)  # type: ignore[return-value]
        except Exception:
            return timezone(timedelta(hours=7))
