"""FFmpeg RTMP stream manager with watchdog & exponential backoff."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, Optional

from config import Config

logger = logging.getLogger(__name__)


class StreamManager:
    """Manage an FFmpeg process that streams raw video + audio to RTMP.

    The manager exposes :py:attr:`video_stdin` and :py:attr:`audio_stdin` as
    pipes that callers can write raw frames / PCM samples to.  When the
    FFmpeg process dies (e.g. network drop), the manager will respawn it
    with exponential backoff up to ``max_reconnect_attempts``.
    """

    def __init__(self, config: Config, dry_run: bool = False) -> None:
        self.config = config
        self.dry_run = dry_run

        self.process: Optional[subprocess.Popen[bytes]] = None
        self._video_pipe_r: Optional[int] = None
        self._video_pipe_w: Optional[int] = None
        self._audio_pipe_r: Optional[int] = None
        self._audio_pipe_w: Optional[int] = None

        self._stop_event = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._reconnect_attempts = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """Start the FFmpeg process and the watchdog thread."""
        if self.dry_run:
            logger.info("[dry-run] StreamManager.start skipped (no FFmpeg).")
            return

        if not self.config.rtmp_endpoint:
            raise RuntimeError(
                "YOUTUBE_STREAM_KEY belum di-set. Tidak bisa memulai streaming."
            )

        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "FFmpeg tidak ditemukan di PATH. Install FFmpeg terlebih dahulu."
            )

        with self._lock:
            self._spawn_ffmpeg()

        self._stop_event.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="ffmpeg-watchdog", daemon=True
        )
        self._watchdog_thread.start()

    def stop(self) -> None:
        """Stop the watchdog and terminate the FFmpeg process gracefully."""
        self._stop_event.set()
        with self._lock:
            self._terminate_ffmpeg()
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=5)
        logger.info("StreamManager stopped.")

    # ------------------------------------------------------------------ #
    # Writing payloads to FFmpeg
    # ------------------------------------------------------------------ #
    def write_video_frame(self, frame_bytes: bytes) -> bool:
        """Write a raw BGR/RGB frame to FFmpeg's video stdin."""
        if self.dry_run:
            return True
        try:
            with self._lock:
                if self._video_pipe_w is None:
                    return False
                os.write(self._video_pipe_w, frame_bytes)
            return True
        except (BrokenPipeError, OSError) as exc:
            logger.warning("Gagal menulis video frame ke FFmpeg: %s", exc)
            return False

    def write_audio_chunk(self, audio_bytes: bytes) -> bool:
        """Write a chunk of PCM s16le stereo audio (44.1 kHz) to FFmpeg."""
        if self.dry_run:
            return True
        try:
            with self._lock:
                if self._audio_pipe_w is None:
                    return False
                os.write(self._audio_pipe_w, audio_bytes)
            return True
        except (BrokenPipeError, OSError) as exc:
            logger.warning("Gagal menulis audio chunk ke FFmpeg: %s", exc)
            return False

    def is_alive(self) -> bool:
        with self._lock:
            return self.process is not None and self.process.poll() is None

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _build_command(self) -> list[str]:
        cfg = self.config
        width, height = cfg.width, cfg.height
        fps = cfg.video_fps

        video_pipe = f"pipe:{self._video_pipe_r}"
        audio_pipe = f"pipe:{self._audio_pipe_r}"

        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-re",
            # Video input from custom FD
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "rgb24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", video_pipe,
            # Audio input from custom FD
            "-f", "s16le",
            "-ar", "44100",
            "-ac", "2",
            "-i", audio_pipe,
            # Video encoding
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-g", str(fps * 2),
            "-keyint_min", str(fps),
            "-b:v", cfg.video_bitrate,
            "-maxrate", cfg.video_bitrate,
            "-bufsize", cfg.video_bitrate,
            # Audio encoding
            "-c:a", "aac",
            "-b:a", cfg.audio_bitrate,
            "-ar", "44100",
            # Output
            "-f", "flv",
            cfg.rtmp_endpoint,
        ]

    def _spawn_ffmpeg(self) -> None:
        self._video_pipe_r, self._video_pipe_w = os.pipe()
        self._audio_pipe_r, self._audio_pipe_w = os.pipe()

        cmd = self._build_command()
        logger.info(
            "Menjalankan FFmpeg ke %s/<HIDDEN_STREAM_KEY>",
            self.config.rtmp_url.rstrip("/"),
        )
        logger.debug("FFmpeg command: %s", " ".join(cmd))

        # On Windows, pass_fds is not supported. Use stdin=PIPE workaround
        # would lose the second input stream — for Windows we degrade
        # gracefully to a single muxed FD by closing audio pipe and falling
        # back to silent track in main loop. For typical Linux deployment
        # pass_fds works as expected.
        pass_fds: tuple[int, ...] = (self._video_pipe_r, self._audio_pipe_r)
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                pass_fds=pass_fds,
                close_fds=True,
            )
        except (ValueError, OSError) as exc:
            logger.warning(
                "pass_fds unsupported (%s). Falling back to muxed stdin pipe.", exc
            )
            os.close(self._video_pipe_r)
            os.close(self._audio_pipe_r)
            self._video_pipe_r = None
            self._audio_pipe_r = None
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

        # Parent does not need the read ends of the pipes.
        if self._video_pipe_r is not None:
            os.close(self._video_pipe_r)
            self._video_pipe_r = None
        if self._audio_pipe_r is not None:
            os.close(self._audio_pipe_r)
            self._audio_pipe_r = None

        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(self.process.stderr,),
            name="ffmpeg-stderr",
            daemon=True,
        )
        self._stderr_thread.start()

    def _drain_stderr(self, stderr: Optional[IO[bytes]]) -> None:
        if stderr is None:
            return
        try:
            for raw_line in iter(stderr.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                lower = line.lower()
                if any(token in lower for token in ("error", "failed", "fatal")):
                    logger.error("[ffmpeg] %s", line)
                elif "warning" in lower:
                    logger.warning("[ffmpeg] %s", line)
                else:
                    logger.debug("[ffmpeg] %s", line)
        except (ValueError, OSError):
            pass

    def _terminate_ffmpeg(self) -> None:
        for fd_name in ("_video_pipe_w", "_audio_pipe_w"):
            fd = getattr(self, fd_name)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                setattr(self, fd_name, None)

        if self.process is not None:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("FFmpeg tidak berhenti, memaksa kill.")
                    self.process.kill()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Gagal menghentikan FFmpeg")
            finally:
                self.process = None

    def _watchdog_loop(self) -> None:
        delay = self.config.watchdog_restart_delay_seconds
        while not self._stop_event.is_set():
            if self._stop_event.wait(delay):
                return

            with self._lock:
                alive = self.process is not None and self.process.poll() is None

            if alive:
                self._reconnect_attempts = 0
                continue

            self._reconnect_attempts += 1
            if self._reconnect_attempts > self.config.max_reconnect_attempts:
                logger.critical(
                    "FFmpeg gagal restart setelah %d percobaan. Menyerah.",
                    self._reconnect_attempts,
                )
                return

            backoff = min(300, 2 ** min(self._reconnect_attempts, 8))
            logger.warning(
                "FFmpeg mati. Restart percobaan #%d (backoff %ds)...",
                self._reconnect_attempts,
                backoff,
            )
            if self._stop_event.wait(backoff):
                return
            try:
                with self._lock:
                    self._terminate_ffmpeg()
                    self._spawn_ffmpeg()
                logger.info("FFmpeg berhasil restart.")
            except Exception:
                logger.exception("Gagal restart FFmpeg, akan coba lagi.")

    # ------------------------------------------------------------------ #
    # Self test
    # ------------------------------------------------------------------ #
    @staticmethod
    def probe_ffmpeg() -> bool:
        """Return True if ffmpeg binary is available."""
        path = shutil.which("ffmpeg")
        if not path:
            return False
        try:
            result = subprocess.run(
                [path, "-version"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False
