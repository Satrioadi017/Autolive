"""Centralized configuration loader for the YouTube 24/7 Auto Live Streaming Bot.

This module loads environment variables from a ``.env`` file (when present)
and exposes a strongly-typed :class:`Config` dataclass that the rest of the
application can import.  All tunables described in ``.env.example`` are
mirrored here so the rest of the codebase never has to touch ``os.environ``
directly.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is in requirements.txt
    def load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False


PROJECT_ROOT: Path = Path(__file__).resolve().parent


def _env(name: str, default: str = "") -> str:
    """Return a stripped environment variable or ``default``."""
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name, "").lower()
    if value == "":
        return default
    return value in {"1", "true", "yes", "on", "y"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name, str(default))
    try:
        return float(raw)
    except ValueError:
        return default


def _parse_resolution(value: str, default: Tuple[int, int] = (1280, 720)) -> Tuple[int, int]:
    try:
        width_str, height_str = value.lower().split("x", 1)
        return int(width_str), int(height_str)
    except (ValueError, AttributeError):
        return default


@dataclass
class Config:
    """Strongly-typed application configuration."""

    # YouTube
    youtube_stream_key: str = ""
    youtube_api_key: str = ""
    youtube_channel_name: str = "Auto Live Channel"
    youtube_broadcast_id: str = ""
    rtmp_url: str = "rtmp://a.rtmp.youtube.com/live2"

    # AI
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Stream
    video_resolution: Tuple[int, int] = (1280, 720)
    video_fps: int = 30
    video_bitrate: str = "2500k"
    audio_bitrate: str = "128k"

    # Content
    content_category: str = "AUTO"
    content_interval_seconds: int = 300
    content_language: str = "id"
    content_queue_size: int = 10

    # Audio
    tts_voice: str = "id-ID-ArdiNeural"
    tts_provider: str = "edge-tts"
    music_volume: float = 0.2
    tts_volume: float = 0.8

    # Background / Overlay
    background_type: str = "gradient"
    background_video_path: str = ""
    slideshow_transition_seconds: float = 2.0
    overlay_font: str = ""
    show_live_indicator: bool = True
    show_subscriber_counter: bool = False
    show_progress_bar: bool = True

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Health Monitor
    health_check_interval_seconds: int = 60
    cpu_alert_threshold: int = 85
    ram_alert_threshold: int = 80
    log_rotate_size_mb: int = 100

    # Reconnect
    max_reconnect_attempts: int = 10
    watchdog_restart_delay_seconds: int = 30

    # Misc
    timezone: str = "Asia/Jakarta"
    log_level: str = "INFO"
    log_file: str = "logs/stream.log"

    # Derived paths (filled in __post_init__)
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    assets_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "assets")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")

    def __post_init__(self) -> None:
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        (self.assets_dir / "backgrounds").mkdir(parents=True, exist_ok=True)
        (self.assets_dir / "music").mkdir(parents=True, exist_ok=True)
        (self.assets_dir / "fonts").mkdir(parents=True, exist_ok=True)
        (self.assets_dir / "overlays").mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def width(self) -> int:
        return self.video_resolution[0]

    @property
    def height(self) -> int:
        return self.video_resolution[1]

    @property
    def music_dir(self) -> Path:
        return self.assets_dir / "music"

    @property
    def backgrounds_dir(self) -> Path:
        return self.assets_dir / "backgrounds"

    @property
    def fonts_dir(self) -> Path:
        return self.assets_dir / "fonts"

    @property
    def overlays_dir(self) -> Path:
        return self.assets_dir / "overlays"

    @property
    def fallback_content_path(self) -> Path:
        return self.assets_dir / "fallback_content.json"

    @property
    def rtmp_endpoint(self) -> str:
        if not self.youtube_stream_key:
            return ""
        return f"{self.rtmp_url.rstrip('/')}/{self.youtube_stream_key}"

    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    def has_youtube_api(self) -> bool:
        return bool(self.youtube_api_key)

    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    def categories(self) -> Tuple[str, ...]:
        return (
            "MOTIVATIONAL_QUOTES",
            "LOFI_FACTS",
            "STUDY_WITH_ME",
            "TRIVIA_QNA",
            "MEDITATION_GUIDE",
        )


def load_config(env_file: str | os.PathLike[str] | None = None) -> Config:
    """Load ``.env`` (if present) and return a populated :class:`Config`."""
    dotenv_path = Path(env_file) if env_file else PROJECT_ROOT / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path, override=False)

    config = Config(
        youtube_stream_key=_env("YOUTUBE_STREAM_KEY"),
        youtube_api_key=_env("YOUTUBE_API_KEY"),
        youtube_channel_name=_env("YOUTUBE_CHANNEL_NAME", "Auto Live Channel"),
        youtube_broadcast_id=_env("YOUTUBE_BROADCAST_ID"),
        rtmp_url=_env("RTMP_URL", "rtmp://a.rtmp.youtube.com/live2"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        video_resolution=_parse_resolution(_env("VIDEO_RESOLUTION", "1280x720")),
        video_fps=_env_int("VIDEO_FPS", 30),
        video_bitrate=_env("VIDEO_BITRATE", "2500k"),
        audio_bitrate=_env("AUDIO_BITRATE", "128k"),
        content_category=_env("CONTENT_CATEGORY", "AUTO").upper(),
        content_interval_seconds=_env_int("CONTENT_INTERVAL_SECONDS", 300),
        content_language=_env("CONTENT_LANGUAGE", "id"),
        content_queue_size=_env_int("CONTENT_QUEUE_SIZE", 10),
        tts_voice=_env("TTS_VOICE", "id-ID-ArdiNeural"),
        tts_provider=_env("TTS_PROVIDER", "edge-tts").lower(),
        music_volume=_env_float("MUSIC_VOLUME", 0.2),
        tts_volume=_env_float("TTS_VOLUME", 0.8),
        background_type=_env("BACKGROUND_TYPE", "gradient").lower(),
        background_video_path=_env("BACKGROUND_VIDEO_PATH"),
        slideshow_transition_seconds=_env_float("SLIDESHOW_TRANSITION_SECONDS", 2.0),
        overlay_font=_env("OVERLAY_FONT"),
        show_live_indicator=_env_bool("SHOW_LIVE_INDICATOR", True),
        show_subscriber_counter=_env_bool("SHOW_SUBSCRIBER_COUNTER", False),
        show_progress_bar=_env_bool("SHOW_PROGRESS_BAR", True),
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        health_check_interval_seconds=_env_int("HEALTH_CHECK_INTERVAL_SECONDS", 60),
        cpu_alert_threshold=_env_int("CPU_ALERT_THRESHOLD", 85),
        ram_alert_threshold=_env_int("RAM_ALERT_THRESHOLD", 80),
        log_rotate_size_mb=_env_int("LOG_ROTATE_SIZE_MB", 100),
        max_reconnect_attempts=_env_int("MAX_RECONNECT_ATTEMPTS", 10),
        watchdog_restart_delay_seconds=_env_int("WATCHDOG_RESTART_DELAY_SECONDS", 30),
        timezone=_env("TIMEZONE", "Asia/Jakarta"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        log_file=_env("LOG_FILE", "logs/stream.log"),
    )
    return config


def setup_logging(config: Config) -> logging.Logger:
    """Configure root logger with both console and rotating file handlers."""
    from logging.handlers import RotatingFileHandler

    log_path = config.project_root / config.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.log_level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    max_bytes = max(1, config.log_rotate_size_mb) * 1024 * 1024
    file_handler = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return root_logger
