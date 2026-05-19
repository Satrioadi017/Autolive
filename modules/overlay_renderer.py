"""Overlay renderer: draws header, footer, live indicator & main content."""
from __future__ import annotations

import logging
import textwrap
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from config import Config

logger = logging.getLogger(__name__)


class OverlayRenderer:
    """Compose UI overlays onto a background frame using Pillow."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.width = config.width
        self.height = config.height
        self._timezone = self._resolve_timezone(config.timezone)
        self._fonts = self._load_fonts()

        self.channel_name: str = config.youtube_channel_name
        self.current_title: str = ""
        self.current_body: str = ""
        self.subscriber_count: Optional[int] = None
        self.progress: float = 0.0  # 0..1

    # ------------------------------------------------------------------ #
    # State setters (thread-safe writes are not strictly required since
    # render is single-threaded, but kept simple intentionally)
    # ------------------------------------------------------------------ #
    def set_content(self, title: str, body: str) -> None:
        self.current_title = title or ""
        self.current_body = body or ""

    def set_progress(self, progress: float) -> None:
        self.progress = max(0.0, min(1.0, progress))

    def set_subscriber_count(self, count: Optional[int]) -> None:
        self.subscriber_count = count

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #
    def render(self, frame: Image.Image) -> Image.Image:
        if frame.mode != "RGB":
            frame = frame.convert("RGB")
        canvas = frame.copy()
        draw = ImageDraw.Draw(canvas, "RGBA")
        try:
            self._draw_header(draw)
            self._draw_main_content(draw)
            self._draw_footer(draw)
            if self.config.show_live_indicator:
                self._draw_live_indicator(draw)
            if self.config.show_progress_bar:
                self._draw_progress_bar(draw)
            if self.config.show_subscriber_counter and self.subscriber_count is not None:
                self._draw_subscriber_counter(draw)
        except Exception:
            logger.exception("Gagal merender overlay (frame tetap dipakai).")
        return canvas

    # ------------------------------------------------------------------ #
    # Overlay components
    # ------------------------------------------------------------------ #
    def _draw_header(self, draw: ImageDraw.ImageDraw) -> None:
        h = max(48, int(self.height * 0.08))
        draw.rectangle(
            (0, 0, self.width, h),
            fill=(0, 0, 0, 160),
        )
        font = self._fonts["header"]
        text = self.channel_name or "Auto Live"
        draw.text((24, h // 2), text, font=font, fill=(255, 255, 255, 255), anchor="lm")

    def _draw_footer(self, draw: ImageDraw.ImageDraw) -> None:
        h = max(40, int(self.height * 0.07))
        y0 = self.height - h
        draw.rectangle((0, y0, self.width, self.height), fill=(0, 0, 0, 160))
        now = datetime.now(tz=self._timezone)
        timestamp = now.strftime("%A, %d %B %Y - %H:%M:%S WIB")
        draw.text(
            (24, y0 + h // 2),
            timestamp,
            font=self._fonts["footer"],
            fill=(230, 230, 230, 255),
            anchor="lm",
        )
        draw.text(
            (self.width - 24, y0 + h // 2),
            "LIVE 24/7",
            font=self._fonts["footer_bold"],
            fill=(255, 215, 100, 255),
            anchor="rm",
        )

    def _draw_main_content(self, draw: ImageDraw.ImageDraw) -> None:
        title_font = self._fonts["title"]
        body_font = self._fonts["body"]

        # Constrain text area so it doesn't overlap header/footer
        top = int(self.height * 0.18)
        bottom = int(self.height * 0.82)
        usable_height = bottom - top
        center_x = self.width // 2

        title = (self.current_title or "").strip()
        body = (self.current_body or "").strip()

        # Word-wrap body to fit width
        max_chars = max(20, int(self.width / 22))
        wrapped_body = self._wrap_text(body, max_chars)

        # Compute total text block height
        line_height_title = title_font.size + 16
        line_height_body = body_font.size + 10
        title_lines = self._wrap_text(title, max(20, int(self.width / 28))) if title else []
        total_h = (
            len(title_lines) * line_height_title
            + (24 if title_lines and wrapped_body else 0)
            + len(wrapped_body) * line_height_body
        )
        y = top + max(0, (usable_height - total_h) // 2)

        for line in title_lines:
            draw.text(
                (center_x, y),
                line,
                font=title_font,
                fill=(255, 255, 255, 255),
                anchor="ma",
                stroke_width=2,
                stroke_fill=(0, 0, 0, 200),
            )
            y += line_height_title
        if title_lines and wrapped_body:
            y += 16
        for line in wrapped_body:
            draw.text(
                (center_x, y),
                line,
                font=body_font,
                fill=(245, 245, 245, 240),
                anchor="ma",
                stroke_width=1,
                stroke_fill=(0, 0, 0, 180),
            )
            y += line_height_body

    def _draw_live_indicator(self, draw: ImageDraw.ImageDraw) -> None:
        # Blink at ~1Hz
        blink = (time.time() % 1.0) < 0.5
        dot_color = (235, 30, 30, 255) if blink else (130, 30, 30, 180)
        x = self.width - 160
        y = max(48, int(self.height * 0.08)) // 2
        draw.ellipse((x, y - 10, x + 20, y + 10), fill=dot_color)
        draw.text(
            (x + 30, y),
            "LIVE",
            font=self._fonts["live"],
            fill=(255, 255, 255, 255),
            anchor="lm",
        )

    def _draw_progress_bar(self, draw: ImageDraw.ImageDraw) -> None:
        margin = 32
        h = 8
        y = self.height - max(40, int(self.height * 0.07)) - h - 6
        x0 = margin
        x1 = self.width - margin
        draw.rectangle((x0, y, x1, y + h), fill=(60, 60, 60, 180))
        bar_w = int((x1 - x0) * self.progress)
        if bar_w > 0:
            draw.rectangle((x0, y, x0 + bar_w, y + h), fill=(255, 215, 100, 220))

    def _draw_subscriber_counter(self, draw: ImageDraw.ImageDraw) -> None:
        text = f"Subs: {self.subscriber_count:,}"
        draw.text(
            (self.width - 24, int(self.height * 0.13)),
            text,
            font=self._fonts["body"],
            fill=(255, 255, 255, 220),
            anchor="ra",
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        if not text:
            return []
        lines: list[str] = []
        for paragraph in text.splitlines():
            if not paragraph.strip():
                lines.append("")
                continue
            wrapped = textwrap.wrap(
                paragraph, width=max_chars, break_long_words=False, break_on_hyphens=False
            )
            lines.extend(wrapped or [paragraph])
        return lines

    def _resolve_timezone(self, tz_name: str) -> timezone:
        try:
            from zoneinfo import ZoneInfo  # type: ignore

            return ZoneInfo(tz_name)  # type: ignore[return-value]
        except Exception:
            # Fall back to fixed UTC+7
            return timezone(timedelta(hours=7))

    def _load_fonts(self) -> dict[str, ImageFont.ImageFont]:
        font_path: Optional[Path] = None
        if self.config.overlay_font:
            candidate = Path(self.config.overlay_font)
            if candidate.exists():
                font_path = candidate
        if font_path is None:
            for candidate in self.config.fonts_dir.glob("*.ttf"):
                font_path = candidate
                break
        if font_path is None:
            # Try a few common system fonts before falling back to default
            for system_candidate in (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "C:/Windows/Fonts/arial.ttf",
            ):
                if Path(system_candidate).exists():
                    font_path = Path(system_candidate)
                    break

        def _font(size: int) -> ImageFont.ImageFont:
            try:
                if font_path is not None:
                    return ImageFont.truetype(str(font_path), size)
            except Exception:
                logger.exception("Gagal memuat font %s", font_path)
            return ImageFont.load_default()

        return {
            "header": _font(28),
            "footer": _font(20),
            "footer_bold": _font(22),
            "title": _font(56),
            "body": _font(34),
            "live": _font(22),
        }
