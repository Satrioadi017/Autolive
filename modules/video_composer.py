"""Video frame composer.

Produces raw RGB frames (1280x720 by default) that can be piped to FFmpeg.
Backgrounds support: gradient (animated), slideshow (with fade), or looped
MP4 video (via OpenCV if available).
"""
from __future__ import annotations

import colorsys
import logging
import math
import random
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np
from PIL import Image

from config import Config

logger = logging.getLogger(__name__)


class _VideoBackground:
    """Iterate over frames of a looping MP4 background."""

    def __init__(self, path: Path, width: int, height: int) -> None:
        self.path = path
        self.width = width
        self.height = height
        self._cap = None
        try:
            import cv2  # type: ignore

            self._cv2 = cv2
            self._cap = cv2.VideoCapture(str(path))
            if not self._cap.isOpened():
                raise RuntimeError(f"Tidak bisa membuka video background: {path}")
        except ImportError:
            logger.warning("opencv-python tidak tersedia, video background dimatikan.")
            self._cap = None
            self._cv2 = None

    def next_frame(self) -> Image.Image:
        if self._cap is None or self._cv2 is None:
            return Image.new("RGB", (self.width, self.height), (12, 12, 24))
        ok, frame = self._cap.read()
        if not ok:
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        if not ok or frame is None:
            return Image.new("RGB", (self.width, self.height), (12, 12, 24))
        frame = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame)
        if img.size != (self.width, self.height):
            img = img.resize((self.width, self.height), Image.LANCZOS)
        return img

    def close(self) -> None:
        try:
            if self._cap is not None:
                self._cap.release()
        except Exception:  # pragma: no cover
            pass


class _Slideshow:
    """Crossfade between static images on a fixed interval."""

    def __init__(
        self,
        images: list[Path],
        width: int,
        height: int,
        transition_seconds: float = 2.0,
        hold_seconds: float = 8.0,
    ) -> None:
        self.width = width
        self.height = height
        self.transition_seconds = max(0.1, transition_seconds)
        self.hold_seconds = max(0.5, hold_seconds)
        self._images: list[Image.Image] = []
        for path in images:
            try:
                img = Image.open(path).convert("RGB")
                img = img.resize((width, height), Image.LANCZOS)
                self._images.append(img)
            except Exception:
                logger.exception("Gagal memuat slideshow image %s", path)
        if not self._images:
            self._images = [Image.new("RGB", (width, height), (24, 24, 36))]

    def frame_at(self, t: float) -> Image.Image:
        cycle = self.hold_seconds + self.transition_seconds
        total = cycle * len(self._images)
        if total <= 0:
            return self._images[0]
        offset = t % total
        idx = int(offset // cycle)
        within = offset - idx * cycle
        current = self._images[idx % len(self._images)]
        if within < self.hold_seconds:
            return current
        # transition
        next_img = self._images[(idx + 1) % len(self._images)]
        alpha = (within - self.hold_seconds) / self.transition_seconds
        return Image.blend(current, next_img, alpha)


class VideoComposer:
    """Compose video frames with a dynamic background + overlay callback."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.width = config.width
        self.height = config.height
        self.fps = max(1, config.video_fps)
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._gradient_seed = random.random() * math.tau
        self._video_bg: Optional[_VideoBackground] = None
        self._slideshow: Optional[_Slideshow] = None
        self._init_background()

    def _init_background(self) -> None:
        kind = self.config.background_type
        if kind == "video":
            path = (
                Path(self.config.background_video_path)
                if self.config.background_video_path
                else None
            )
            if path and path.exists():
                self._video_bg = _VideoBackground(path, self.width, self.height)
            else:
                logger.warning("Background video tidak ditemukan, fallback ke gradient.")
        elif kind == "slideshow":
            images = sorted(
                p
                for p in self.config.backgrounds_dir.glob("*")
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            )
            if images:
                self._slideshow = _Slideshow(
                    images,
                    self.width,
                    self.height,
                    transition_seconds=self.config.slideshow_transition_seconds,
                )
            else:
                logger.warning(
                    "Tidak ada gambar di %s, fallback ke gradient.",
                    self.config.backgrounds_dir,
                )

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #
    def background_frame(self, t: Optional[float] = None) -> Image.Image:
        """Return a background frame for the given time offset (seconds)."""
        if t is None:
            t = time.time() - self._start_time
        if self._video_bg is not None:
            return self._video_bg.next_frame()
        if self._slideshow is not None:
            return self._slideshow.frame_at(t)
        return self._gradient_frame(t)

    def compose_frame(
        self,
        overlay_callback: Optional[Callable[[Image.Image], Image.Image]] = None,
        t: Optional[float] = None,
    ) -> Image.Image:
        bg = self.background_frame(t)
        if overlay_callback is not None:
            try:
                bg = overlay_callback(bg)
            except Exception:
                logger.exception("Overlay callback gagal, skip overlay frame.")
        return bg

    def frame_to_bytes(self, image: Image.Image) -> bytes:
        if image.mode != "RGB":
            image = image.convert("RGB")
        return image.tobytes()

    def frame_iterator(
        self,
        overlay_callback: Optional[Callable[[Image.Image], Image.Image]] = None,
        max_frames: Optional[int] = None,
    ) -> Iterable[Image.Image]:
        count = 0
        while max_frames is None or count < max_frames:
            yield self.compose_frame(overlay_callback)
            count += 1

    def close(self) -> None:
        if self._video_bg is not None:
            self._video_bg.close()
            self._video_bg = None

    # ------------------------------------------------------------------ #
    # Gradient background generator
    # ------------------------------------------------------------------ #
    def _gradient_frame(self, t: float) -> Image.Image:
        hue1 = (math.sin(t * 0.02 + self._gradient_seed) * 0.5 + 0.5) % 1.0
        hue2 = (math.sin(t * 0.025 + self._gradient_seed + 1.3) * 0.5 + 0.5) % 1.0
        rgb1 = colorsys.hsv_to_rgb(hue1, 0.55, 0.35)
        rgb2 = colorsys.hsv_to_rgb(hue2, 0.65, 0.6)
        c1 = np.array([int(v * 255) for v in rgb1], dtype=np.float32)
        c2 = np.array([int(v * 255) for v in rgb2], dtype=np.float32)
        gradient = np.linspace(0.0, 1.0, self.height, dtype=np.float32).reshape(-1, 1, 1)
        frame = (1.0 - gradient) * c1 + gradient * c2
        frame = np.tile(frame, (1, self.width, 1)).astype(np.uint8)
        return Image.fromarray(frame, mode="RGB")
