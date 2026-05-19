"""Audio engine: TTS + background music mixer.

Generates spoken audio for a given :class:`~modules.content_generator.ContentItem`
using edge-tts (preferred) or gTTS as a fallback, mixes it with looping
background music from ``assets/music`` and exposes the resulting PCM data
to the stream pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import random
import tempfile
import threading
from pathlib import Path
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


class AudioEngine:
    """Generate mixed TTS + background music audio chunks."""

    SAMPLE_RATE = 44100
    CHANNELS = 2
    SAMPLE_WIDTH = 2  # 16-bit PCM

    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._music_files = self._discover_music()
        self._pydub = self._try_import_pydub()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def synthesize_tts(self, text: str, output_path: Path) -> bool:
        """Synthesize TTS audio for ``text`` to ``output_path`` (MP3)."""
        if not text.strip():
            return False
        provider = self.config.tts_provider
        if provider == "edge-tts":
            if self._synthesize_edge(text, output_path):
                return True
            logger.warning("edge-tts gagal, jatuhkan ke gTTS.")
        return self._synthesize_gtts(text, output_path)

    def build_mixed_audio(
        self,
        text: str,
        duration_seconds: int,
        output_path: Path,
    ) -> Optional[Path]:
        """Synthesize TTS + mix with background music. Returns output path."""
        if self._pydub is None:
            logger.warning("pydub tidak tersedia, hanya menyimpan TTS murni.")
            mp3_path = output_path.with_suffix(".mp3")
            if self.synthesize_tts(text, mp3_path):
                return mp3_path
            return None

        AudioSegment = self._pydub.AudioSegment  # type: ignore[attr-defined]

        with tempfile.TemporaryDirectory() as tmpdir:
            tts_path = Path(tmpdir) / "tts.mp3"
            if not self.synthesize_tts(text, tts_path):
                logger.warning("Tidak ada TTS, buat track musik saja.")
                tts_segment = AudioSegment.silent(duration=duration_seconds * 1000)
            else:
                try:
                    tts_segment = AudioSegment.from_file(tts_path)
                except Exception:
                    logger.exception("Gagal memuat TTS audio %s", tts_path)
                    tts_segment = AudioSegment.silent(duration=duration_seconds * 1000)

            # Adjust TTS volume relative to 0dB
            tts_segment = tts_segment + self._gain_db(self.config.tts_volume)

            music_segment = self._build_music_segment(
                AudioSegment, duration_seconds * 1000
            )

            target_ms = max(int(duration_seconds * 1000), len(tts_segment) + 1000)
            if len(music_segment) < target_ms:
                loops = (target_ms // max(1, len(music_segment))) + 1
                music_segment = (music_segment * loops)[:target_ms]
            else:
                music_segment = music_segment[:target_ms]

            mixed = music_segment.overlay(tts_segment)
            mixed = (
                mixed.set_frame_rate(self.SAMPLE_RATE)
                .set_channels(self.CHANNELS)
                .set_sample_width(self.SAMPLE_WIDTH)
            )

            output_path = output_path.with_suffix(".wav")
            try:
                mixed.export(output_path, format="wav")
            except Exception:
                logger.exception("Gagal export mixed audio")
                return None
            return output_path

    def pcm_bytes_from_wav(self, wav_path: Path) -> bytes:
        """Return raw little-endian s16 stereo PCM bytes from a WAV file."""
        if self._pydub is None:
            return b""
        AudioSegment = self._pydub.AudioSegment  # type: ignore[attr-defined]
        try:
            segment = AudioSegment.from_file(wav_path)
        except Exception:
            logger.exception("Gagal membaca WAV %s", wav_path)
            return b""
        segment = (
            segment.set_frame_rate(self.SAMPLE_RATE)
            .set_channels(self.CHANNELS)
            .set_sample_width(self.SAMPLE_WIDTH)
        )
        return segment.raw_data

    def silence_pcm(self, duration_seconds: float) -> bytes:
        """Return PCM bytes for ``duration_seconds`` of stereo silence."""
        total_samples = int(self.SAMPLE_RATE * max(0.0, duration_seconds))
        return b"\x00" * (total_samples * self.SAMPLE_WIDTH * self.CHANNELS)

    # ------------------------------------------------------------------ #
    # TTS implementations
    # ------------------------------------------------------------------ #
    def _synthesize_edge(self, text: str, output_path: Path) -> bool:
        try:
            import edge_tts  # type: ignore
        except ImportError:
            logger.debug("edge-tts not installed.")
            return False

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, self.config.tts_voice)
            await communicate.save(str(output_path))

        try:
            asyncio.run(_run())
        except RuntimeError:
            # Already inside event loop (rare): use new loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()
        except Exception:
            logger.exception("edge-tts gagal")
            return False
        return output_path.exists() and output_path.stat().st_size > 0

    def _synthesize_gtts(self, text: str, output_path: Path) -> bool:
        try:
            from gtts import gTTS  # type: ignore
        except ImportError:
            logger.warning("gTTS tidak terinstall, skip TTS.")
            return False
        try:
            tts = gTTS(text=text, lang=self.config.content_language or "id")
            tts.save(str(output_path))
        except Exception:
            logger.exception("gTTS gagal")
            return False
        return output_path.exists() and output_path.stat().st_size > 0

    # ------------------------------------------------------------------ #
    # Music helpers
    # ------------------------------------------------------------------ #
    def _discover_music(self) -> list[Path]:
        if not self.config.music_dir.exists():
            return []
        return sorted(
            p
            for p in self.config.music_dir.glob("*")
            if p.suffix.lower() in {".mp3", ".wav", ".ogg", ".m4a"}
        )

    def refresh_music(self) -> None:
        with self._lock:
            self._music_files = self._discover_music()

    def _build_music_segment(self, AudioSegment, duration_ms: int):  # type: ignore[no-untyped-def]
        """Return a music AudioSegment of at least ``duration_ms`` length."""
        if not self._music_files:
            return AudioSegment.silent(duration=duration_ms)
        path = random.choice(self._music_files)
        try:
            segment = AudioSegment.from_file(path)
        except Exception:
            logger.exception("Gagal memuat musik %s", path)
            return AudioSegment.silent(duration=duration_ms)
        segment = segment + self._gain_db(self.config.music_volume)
        if len(segment) < duration_ms:
            loops = (duration_ms // max(1, len(segment))) + 1
            segment = segment * loops
        return segment[:duration_ms]

    @staticmethod
    def _gain_db(volume: float) -> float:
        """Convert a linear 0..1 volume to a relative dB gain."""
        if volume <= 0:
            return -120.0
        # Reference: volume=1.0 -> +0dB, lower -> attenuate
        import math

        return 20.0 * math.log10(max(0.0001, min(1.0, volume)))

    def _try_import_pydub(self) -> object | None:
        try:
            import pydub  # type: ignore

            return pydub
        except ImportError:
            logger.warning("pydub tidak terinstall, fitur audio terbatas.")
            return None
