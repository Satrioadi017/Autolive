"""Entry point for the YouTube 24/7 Auto Live Streaming Bot."""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import Config, load_config, setup_logging
from modules.audio_engine import AudioEngine
from modules.content_generator import ContentGenerator, ContentItem
from modules.health_monitor import HealthMonitor
from modules.overlay_renderer import OverlayRenderer
from modules.scheduler import ContentScheduler, ScheduleSlot
from modules.stream_manager import StreamManager
from modules.video_composer import VideoComposer
from modules.youtube_api import YouTubeAPIClient

logger = logging.getLogger("autolive")


class AutoLiveApp:
    """Top-level orchestrator that wires every subsystem together."""

    def __init__(self, config: Config, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run
        self._stop_event = threading.Event()
        self._restart_event = threading.Event()

        self.scheduler = ContentScheduler(config)
        self.content = ContentGenerator(config)
        self.audio = AudioEngine(config)
        self.video = VideoComposer(config)
        self.overlay = OverlayRenderer(config)
        self.youtube = YouTubeAPIClient(config)
        self.stream = StreamManager(config, dry_run=dry_run)
        self.health = HealthMonitor(
            config,
            is_stream_alive=lambda: self.dry_run or self.stream.is_alive(),
            restart_callback=self._request_restart,
        )

        self._last_metadata_update = 0.0
        self._last_subs_update = 0.0
        self._last_chat_poll = 0.0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def run(self) -> int:
        logger.info("=== Autolive 24/7 Bot booting ===")
        if self.config.has_youtube_api():
            stats = self.youtube.get_subscriber_count()
            if stats is not None:
                self.overlay.set_subscriber_count(stats)

        self.scheduler.add_listener(self._on_schedule_change)
        self.scheduler.start()
        # Apply initial scheduler category so content matches the slot
        if self.config.content_category.upper() == "AUTO":
            self._on_schedule_change(self.scheduler.current_slot())

        self.content.start()
        self.content.prefill(3)

        self.health.start()

        try:
            self.stream.start()
        except Exception as exc:
            logger.error("Tidak bisa memulai stream: %s", exc)
            if not self.dry_run:
                self._shutdown()
                return 2

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("Interrupt diterima.")
        except Exception:
            logger.exception("Loop utama crash")
        finally:
            self._shutdown()
        return 0

    def stop(self) -> None:
        logger.info("Stop signal diterima.")
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def _main_loop(self) -> None:
        fps = max(1, self.config.video_fps)
        frame_period = 1.0 / fps

        while not self._stop_event.is_set():
            if self._restart_event.is_set():
                logger.warning("Restart pipeline diminta health monitor.")
                self._restart_pipeline()
                self._restart_event.clear()

            try:
                item = self.content.get_next(timeout=10)
            except Exception:
                logger.warning("Queue konten kosong, generate sinkron darurat.")
                item = self.content._produce_item()  # type: ignore[attr-defined]

            logger.info(
                "Memutar konten kategori=%s judul=%s",
                item.category,
                item.title[:60],
            )
            self.overlay.set_content(item.title, item.body)
            self._maybe_update_broadcast_metadata(item)
            self._maybe_update_subscriber_count()

            audio_path = self._prepare_audio(item)
            duration_seconds = self._resolve_duration(item, audio_path)
            total_frames = max(1, int(duration_seconds * fps))

            self._stream_segment(item, audio_path, total_frames, frame_period)

    def _stream_segment(
        self,
        item: ContentItem,
        audio_path: Optional[Path],
        total_frames: int,
        frame_period: float,
    ) -> None:
        fps = max(1, self.config.video_fps)

        audio_thread: Optional[threading.Thread] = None
        if audio_path is not None and not self.dry_run:
            audio_thread = threading.Thread(
                target=self._stream_audio,
                args=(audio_path,),
                name="audio-pump",
                daemon=True,
            )
            audio_thread.start()

        start_ts = time.time()
        for frame_idx in range(total_frames):
            if self._stop_event.is_set() or self._restart_event.is_set():
                break
            progress = (frame_idx + 1) / total_frames
            self.overlay.set_progress(progress)
            frame = self.video.compose_frame(self.overlay.render)
            frame_bytes = self.video.frame_to_bytes(frame)
            if self.dry_run:
                if frame_idx == 0:
                    logger.debug("[dry-run] Frame %d siap (%d bytes).", frame_idx, len(frame_bytes))
            else:
                ok = self.stream.write_video_frame(frame_bytes)
                if not ok:
                    logger.warning("Pipe video ditutup, tunggu watchdog restart...")
                    time.sleep(1)
                    break
            elapsed = time.time() - start_ts
            target = (frame_idx + 1) * frame_period
            sleep_for = target - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)

        if audio_thread is not None:
            audio_thread.join(timeout=5)

    def _stream_audio(self, audio_path: Path) -> None:
        try:
            pcm = self.audio.pcm_bytes_from_wav(audio_path)
        except Exception:
            logger.exception("Tidak bisa decode audio")
            return
        if not pcm:
            return
        # Stream audio in ~100ms chunks
        chunk_size = int(
            self.audio.SAMPLE_RATE * self.audio.SAMPLE_WIDTH * self.audio.CHANNELS * 0.1
        )
        for offset in range(0, len(pcm), chunk_size):
            if self._stop_event.is_set() or self._restart_event.is_set():
                return
            chunk = pcm[offset : offset + chunk_size]
            if not self.stream.write_audio_chunk(chunk):
                return
            time.sleep(0.09)

    def _prepare_audio(self, item: ContentItem) -> Optional[Path]:
        try:
            tmpdir = Path(tempfile.gettempdir()) / "autolive"
            tmpdir.mkdir(parents=True, exist_ok=True)
            out_path = tmpdir / f"content_{int(time.time())}.wav"
            return self.audio.build_mixed_audio(
                item.spoken_text, item.duration_seconds, out_path
            )
        except Exception:
            logger.exception("Gagal menyiapkan audio untuk konten")
            return None

    def _resolve_duration(
        self, item: ContentItem, audio_path: Optional[Path]
    ) -> int:
        if audio_path is not None and audio_path.exists():
            try:
                import wave

                with wave.open(str(audio_path), "rb") as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate() or self.audio.SAMPLE_RATE
                    duration = int(frames / max(1, rate))
                    return max(item.duration_seconds, duration)
            except Exception:
                logger.debug("Tidak bisa menghitung durasi WAV", exc_info=True)
        return item.duration_seconds

    # ------------------------------------------------------------------ #
    # Scheduler / metadata / chat helpers
    # ------------------------------------------------------------------ #
    def _on_schedule_change(self, slot: ScheduleSlot) -> None:
        if self.config.content_category.upper() != "AUTO":
            return
        category = (
            slot.secondary_category
            if slot.secondary_category and time.time() % 600 < 300
            else slot.primary_category
        )
        self.content.set_category(category)

    def _maybe_update_broadcast_metadata(self, item: ContentItem) -> None:
        now = time.time()
        if now - self._last_metadata_update < 1800:  # every 30 min
            return
        self._last_metadata_update = now
        if not self.config.has_youtube_api():
            return
        title = f"🔴 {self.config.youtube_channel_name} • {item.title}"
        description = (
            f"Stream 24/7 otomatis. Konten saat ini: {item.title}\n\n"
            f"{item.body}\n\n"
            f"Dijadwalkan oleh Autolive Bot."
        )
        self.youtube.update_broadcast_metadata(title, description)

    def _maybe_update_subscriber_count(self) -> None:
        now = time.time()
        if now - self._last_subs_update < 600:  # every 10 min
            return
        self._last_subs_update = now
        if not self.config.show_subscriber_counter:
            return
        count = self.youtube.get_subscriber_count()
        if count is not None:
            self.overlay.set_subscriber_count(count)

    def _request_restart(self) -> None:
        self._restart_event.set()

    def _restart_pipeline(self) -> None:
        try:
            self.stream.stop()
        except Exception:
            logger.exception("Gagal menghentikan stream saat restart")
        try:
            self.stream.start()
        except Exception:
            logger.exception("Gagal memulai ulang stream")

    def _shutdown(self) -> None:
        logger.info("Memulai shutdown bersih...")
        for component in (self.health, self.scheduler, self.content):
            try:
                component.stop()
            except Exception:
                logger.exception("Komponen gagal di-stop")
        try:
            self.stream.stop()
        except Exception:
            logger.exception("StreamManager gagal di-stop")
        try:
            self.video.close()
        except Exception:
            pass
        logger.info("Shutdown selesai.")


# ---------------------------------------------------------------------- #
# Modes
# ---------------------------------------------------------------------- #
def run_test_content(config: Config, count: int = 3) -> int:
    """Generate a few sample content items and print them. No streaming."""
    logger.info("Mode --test-content aktif. Menghasilkan %d sampel konten.", count)
    generator = ContentGenerator(config)
    scheduler = ContentScheduler(config)
    slot = scheduler.current_slot()
    if config.content_category.upper() == "AUTO":
        generator.set_category(slot.primary_category)

    samples: list[dict[str, str]] = []
    for idx in range(count):
        try:
            item = generator._produce_item()  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Gagal menghasilkan konten")
            continue
        sample = {
            "index": str(idx + 1),
            "category": item.category,
            "title": item.title,
            "body": item.body,
            "created_at": datetime.fromtimestamp(
                item.created_at, tz=timezone.utc
            ).isoformat(),
        }
        samples.append(sample)
        print("=" * 60)
        print(f"[{idx + 1}/{count}] Kategori: {item.category}")
        print(f"Judul   : {item.title}")
        print("Body    :")
        print(item.body)
    out_path = config.logs_dir / "test_content_samples.json"
    try:
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(samples, fh, indent=2, ensure_ascii=False)
        logger.info("Sampel konten disimpan ke %s", out_path)
    except OSError:
        logger.exception("Gagal menyimpan sampel konten")
    return 0


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="YouTube 24/7 Auto Live Streaming Bot"
    )
    parser.add_argument(
        "--env",
        default=None,
        help="Path ke file .env (default: ./.env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Jalankan tanpa benar-benar mengirim ke YouTube (tanpa FFmpeg).",
    )
    parser.add_argument(
        "--test-content",
        action="store_true",
        help="Preview beberapa item konten lalu keluar (tanpa streaming).",
    )
    parser.add_argument(
        "--test-content-count",
        type=int,
        default=3,
        help="Jumlah konten yang dihasilkan saat --test-content (default: 3).",
    )
    return parser.parse_args(argv)


def install_signal_handlers(app: AutoLiveApp) -> None:
    def _handler(signum: int, _frame: object) -> None:
        logger.info("Menerima signal %s, shutdown...", signum)
        app.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Some platforms / threads disallow signal handlers
            pass


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = load_config(args.env)
    setup_logging(config)
    logger.info("Config dimuat. dry_run=%s test_content=%s", args.dry_run, args.test_content)

    if args.test_content:
        return run_test_content(config, count=max(1, args.test_content_count))

    app = AutoLiveApp(config, dry_run=args.dry_run)
    install_signal_handlers(app)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
