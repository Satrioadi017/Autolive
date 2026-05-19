"""Health monitor: track FFmpeg, CPU, RAM, internet & rotate logs."""
from __future__ import annotations

import json
import logging
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class HealthSnapshot:
    timestamp: str
    ffmpeg_alive: bool
    cpu_percent: float
    ram_percent: float
    internet_ok: bool
    log_file_size_mb: float
    notes: str = ""


class HealthMonitor:
    """Background thread that periodically inspects the runtime."""

    def __init__(
        self,
        config: Config,
        is_stream_alive: Callable[[], bool],
        restart_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        self.config = config
        self._is_stream_alive = is_stream_alive
        self._restart_callback = restart_callback
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_report_hour: Optional[int] = None
        self._psutil = self._try_import_psutil()
        self._consecutive_failures = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="health-monitor", daemon=True
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
        while not self._stop_event.is_set():
            try:
                snapshot = self._collect_snapshot()
                self._evaluate(snapshot)
                self._maybe_save_hourly(snapshot)
            except Exception:
                logger.exception("HealthMonitor tick error")
            if self._stop_event.wait(self.config.health_check_interval_seconds):
                return

    def _collect_snapshot(self) -> HealthSnapshot:
        cpu, ram = self._cpu_ram()
        log_size_mb = self._log_size_mb()
        internet_ok = self._check_internet()
        ffmpeg_alive = False
        try:
            ffmpeg_alive = bool(self._is_stream_alive())
        except Exception:
            logger.exception("is_stream_alive callback gagal")
        return HealthSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            ffmpeg_alive=ffmpeg_alive,
            cpu_percent=cpu,
            ram_percent=ram,
            internet_ok=internet_ok,
            log_file_size_mb=log_size_mb,
        )

    def _evaluate(self, snap: HealthSnapshot) -> None:
        logger.debug("Health snapshot: %s", asdict(snap))

        # CPU / RAM alerts
        if snap.cpu_percent and snap.cpu_percent > self.config.cpu_alert_threshold:
            logger.warning("CPU tinggi: %.1f%%", snap.cpu_percent)
            self._notify_telegram(
                f"CPU usage tinggi: {snap.cpu_percent:.1f}% pada {snap.timestamp}"
            )
        if snap.ram_percent and snap.ram_percent > self.config.ram_alert_threshold:
            logger.warning("RAM tinggi: %.1f%%", snap.ram_percent)
            self._notify_telegram(
                f"RAM usage tinggi: {snap.ram_percent:.1f}% pada {snap.timestamp}"
            )

        if not snap.internet_ok:
            logger.warning("Internet check gagal (ping 8.8.8.8)")

        if snap.log_file_size_mb > self.config.log_rotate_size_mb:
            self._rotate_log_file()

        # Restart pipeline jika FFmpeg mati selama beberapa siklus berturut-turut
        if not snap.ffmpeg_alive:
            self._consecutive_failures += 1
            logger.warning(
                "FFmpeg tidak aktif (siklus #%d).", self._consecutive_failures
            )
            if self._consecutive_failures >= 2 and self._restart_callback is not None:
                logger.error("FFmpeg mati 2 siklus, memicu restart pipeline.")
                try:
                    self._restart_callback()
                except Exception:
                    logger.exception("restart_callback gagal")
                self._consecutive_failures = 0
        else:
            self._consecutive_failures = 0

    def _maybe_save_hourly(self, snap: HealthSnapshot) -> None:
        hour = datetime.now(timezone.utc).hour
        if self._last_report_hour == hour:
            return
        self._last_report_hour = hour
        report_path = self.config.logs_dir / "health.json"
        existing: list[dict[str, object]] = []
        if report_path.exists():
            try:
                with report_path.open("r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if not isinstance(existing, list):
                    existing = []
            except (OSError, json.JSONDecodeError):
                existing = []
        existing.append(asdict(snap))
        # Keep most recent 168 entries (1 week worth at 1 per hour)
        existing = existing[-168:]
        try:
            with report_path.open("w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
        except OSError:
            logger.exception("Gagal menulis health.json")

    # ------------------------------------------------------------------ #
    # Probes
    # ------------------------------------------------------------------ #
    def _cpu_ram(self) -> tuple[float, float]:
        if self._psutil is None:
            return 0.0, 0.0
        try:
            cpu = float(self._psutil.cpu_percent(interval=None))  # type: ignore[attr-defined]
            ram = float(self._psutil.virtual_memory().percent)  # type: ignore[attr-defined]
            return cpu, ram
        except Exception:
            logger.exception("psutil gagal mengukur CPU/RAM")
            return 0.0, 0.0

    @staticmethod
    def _check_internet() -> bool:
        # Prefer TCP probe to avoid sudo on ICMP ping
        try:
            with socket.create_connection(("8.8.8.8", 53), timeout=3):
                return True
        except OSError:
            pass
        # Fall back to ICMP ping
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _log_size_mb(self) -> float:
        path = self.config.project_root / self.config.log_file
        if not path.exists():
            return 0.0
        try:
            return path.stat().st_size / (1024 * 1024)
        except OSError:
            return 0.0

    def _rotate_log_file(self) -> None:
        path = self.config.project_root / self.config.log_file
        if not path.exists():
            return
        try:
            rotated = path.with_suffix(
                f".{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.log"
            )
            path.rename(rotated)
            logger.info("Log file dirotasi ke %s", rotated)
        except OSError:
            logger.exception("Gagal merotasi log file")

    def _notify_telegram(self, message: str) -> None:
        if not self.config.has_telegram():
            return
        try:
            import requests  # type: ignore

            url = (
                f"https://api.telegram.org/bot{self.config.telegram_bot_token}"
                "/sendMessage"
            )
            requests.post(
                url,
                json={
                    "chat_id": self.config.telegram_chat_id,
                    "text": f"[Autolive] {message}",
                },
                timeout=5,
            )
        except Exception:
            logger.exception("Telegram notify gagal")

    def _try_import_psutil(self) -> object | None:
        try:
            import psutil  # type: ignore

            return psutil
        except ImportError:
            logger.warning("psutil tidak terinstall, CPU/RAM monitoring dinonaktifkan.")
            return None
