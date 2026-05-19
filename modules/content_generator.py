"""Content generator backed by Anthropic Claude with queueing and fallback."""
from __future__ import annotations

import json
import logging
import queue
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class ContentItem:
    """A single piece of content ready to be streamed."""

    category: str
    title: str
    body: str
    duration_seconds: int = 300
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def spoken_text(self) -> str:
        """Text to feed into TTS engine (title + body)."""
        if self.title and self.title.strip().lower() not in self.body.strip().lower():
            return f"{self.title}. {self.body}"
        return self.body


CATEGORY_PROMPTS: dict[str, str] = {
    "MOTIVATIONAL_QUOTES": (
        "Buat satu quote motivasi yang energik dan inspiratif dalam Bahasa Indonesia. "
        "Quote harus orisinal, ringkas (maks 2 kalimat), tidak klise, dan menggugah semangat."
    ),
    "LOFI_FACTS": (
        "Tulis satu fakta menarik yang santai dan bernuansa lo-fi, cocok untuk teman belajar/santai. "
        "Topik bisa sains, sejarah, atau budaya populer. Tulis dalam Bahasa Indonesia, 2-3 kalimat."
    ),
    "STUDY_WITH_ME": (
        "Buat pesan singkat (2-4 kalimat) untuk teman belajar dengan format Pomodoro. "
        "Mulai dengan ajakan mulai fokus, beri tips belajar singkat, akhiri dengan kalimat semangat. "
        "Gunakan Bahasa Indonesia yang hangat."
    ),
    "TRIVIA_QNA": (
        "Buat satu pertanyaan trivia menarik (Bahasa Indonesia) beserta jawaban singkatnya. "
        "Format:\nPERTANYAAN: <pertanyaan>\nJAWABAN: <jawaban>"
    ),
    "MEDITATION_GUIDE": (
        "Buat panduan meditasi singkat (3-5 kalimat) dalam Bahasa Indonesia. "
        "Gunakan nada tenang, ajak menarik napas dalam, dan fokus pada momen saat ini."
    ),
}


DEFAULT_FALLBACK: dict[str, list[dict[str, str]]] = {
    "MOTIVATIONAL_QUOTES": [
        {"title": "Mulai Sekarang", "body": "Tidak ada waktu yang lebih tepat selain hari ini. Ambil satu langkah kecil, dan biarkan momentum mengerjakan sisanya."},
        {"title": "Konsisten", "body": "Hasil besar dibangun dari kebiasaan kecil yang dilakukan setiap hari. Percaya pada proses, percaya pada dirimu."},
        {"title": "Bangkit Lagi", "body": "Jatuh itu manusiawi, bangkit itu pilihan. Pilih untuk bangkit sekali lebih banyak dari jumlah jatuhmu."},
    ],
    "LOFI_FACTS": [
        {"title": "Tahukah Kamu?", "body": "Otak manusia menggunakan sekitar 20% energi tubuh meskipun beratnya hanya 2% dari total massa. Nikmati lo-fi sambil mengisi ulang fokusmu."},
        {"title": "Fakta Santai", "body": "Suara hujan menstimulasi gelombang alfa di otak — itulah kenapa lo-fi + hujan terasa begitu menenangkan."},
    ],
    "STUDY_WITH_ME": [
        {"title": "Pomodoro 25:5", "body": "Yuk fokus 25 menit, lalu istirahat 5 menit. Singkirkan distraksi, atur niatmu, dan mulai. Kamu pasti bisa!"},
    ],
    "TRIVIA_QNA": [
        {"title": "Trivia", "body": "PERTANYAAN: Planet apa yang dijuluki 'Planet Merah'?\nJAWABAN: Mars."},
        {"title": "Trivia", "body": "PERTANYAAN: Siapa penemu lampu pijar modern?\nJAWABAN: Thomas Alva Edison."},
    ],
    "MEDITATION_GUIDE": [
        {"title": "Tenang Sejenak", "body": "Tarik napas perlahan selama empat hitungan. Tahan sebentar. Lepaskan dalam enam hitungan. Rasakan tubuhmu rileks, dan pikiranmu tenang."},
    ],
}


class ContentGenerator:
    """Manage a queue of :class:`ContentItem` produced by Claude or fallback."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.queue: "queue.Queue[ContentItem]" = queue.Queue(
            maxsize=max(1, config.content_queue_size)
        )
        self._stop_event = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._client = self._init_anthropic()
        self._fallback = self._load_fallback()
        self._current_category = self._normalize_category(config.content_category)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_category(self, category: str) -> None:
        normalized = self._normalize_category(category)
        if normalized != self._current_category:
            logger.info("Mengubah kategori konten ke %s", normalized)
            self._current_category = normalized

    def get_next(self, timeout: Optional[float] = None) -> ContentItem:
        """Block until the next content item is ready and return it."""
        return self.queue.get(timeout=timeout)

    def start(self) -> None:
        """Start the background generator worker."""
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._run, name="content-generator", daemon=True
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=5)

    def prefill(self, count: int = 3) -> None:
        """Synchronously generate ``count`` items so the queue is warm."""
        for _ in range(count):
            try:
                item = self._produce_item()
                self.queue.put(item, timeout=5)
            except queue.Full:
                break
            except Exception:
                logger.exception("Gagal pre-fill konten, lanjut.")

    # ------------------------------------------------------------------ #
    # Worker
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._produce_item()
                while not self._stop_event.is_set():
                    try:
                        self.queue.put(item, timeout=1)
                        break
                    except queue.Full:
                        continue
            except Exception:
                logger.exception("Worker konten error, retry 5s.")
                if self._stop_event.wait(5):
                    return

    def _produce_item(self) -> ContentItem:
        category = self._current_category
        prompt = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["MOTIVATIONAL_QUOTES"])

        text = ""
        if self._client is not None:
            try:
                text = self._call_claude(prompt)
            except Exception:
                logger.exception("Gagal menghasilkan konten via Claude, pakai fallback.")
                text = ""

        if not text:
            text = self._fallback_text(category)

        title, body = self._split_title_body(text, category)
        return ContentItem(
            category=category,
            title=title,
            body=body,
            duration_seconds=max(30, self.config.content_interval_seconds),
            metadata={"generated_at": datetime.now(timezone.utc).isoformat()},
        )

    # ------------------------------------------------------------------ #
    # Anthropic helpers
    # ------------------------------------------------------------------ #
    def _init_anthropic(self) -> object | None:
        if not self.config.has_anthropic():
            logger.warning(
                "ANTHROPIC_API_KEY belum di-set, akan memakai konten fallback."
            )
            return None
        try:
            import anthropic  # type: ignore

            return anthropic.Anthropic(api_key=self.config.anthropic_api_key)
        except ImportError:
            logger.warning("Library `anthropic` belum terinstall, pakai fallback.")
            return None
        except Exception:
            logger.exception("Gagal inisialisasi Anthropic client.")
            return None

    def _call_claude(self, prompt: str) -> str:
        if self._client is None:
            return ""
        try:
            response = self._client.messages.create(  # type: ignore[union-attr]
                model=self.config.anthropic_model,
                max_tokens=400,
                temperature=0.9,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )
        except Exception:
            logger.exception("Anthropic API call gagal.")
            return ""

        parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()

    # ------------------------------------------------------------------ #
    # Fallback helpers
    # ------------------------------------------------------------------ #
    def _load_fallback(self) -> dict[str, list[dict[str, str]]]:
        path = self.config.fallback_content_path
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    merged: dict[str, list[dict[str, str]]] = {}
                    for key in self.config.categories():
                        merged[key] = list(DEFAULT_FALLBACK.get(key, []))
                        for entry in data.get(key, []) or []:
                            if isinstance(entry, dict) and "body" in entry:
                                merged[key].append(
                                    {
                                        "title": entry.get("title", ""),
                                        "body": entry["body"],
                                    }
                                )
                    return merged
            except (OSError, json.JSONDecodeError):
                logger.exception("Gagal memuat fallback_content.json")
        return {key: list(items) for key, items in DEFAULT_FALLBACK.items()}

    def _fallback_text(self, category: str) -> str:
        pool = self._fallback.get(category) or self._fallback.get(
            "MOTIVATIONAL_QUOTES", []
        )
        if not pool:
            return "Tetap semangat. Hari ini adalah kesempatan baru."
        choice = random.choice(pool)
        title = choice.get("title", "")
        body = choice.get("body", "")
        if title:
            return f"{title}\n{body}"
        return body

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #
    def _normalize_category(self, category: str) -> str:
        if not category:
            return "MOTIVATIONAL_QUOTES"
        upper = category.upper().strip()
        if upper in self.config.categories():
            return upper
        if upper == "AUTO":
            # Default starting point until scheduler kicks in
            return "MOTIVATIONAL_QUOTES"
        return "MOTIVATIONAL_QUOTES"

    @staticmethod
    def _split_title_body(text: str, category: str) -> tuple[str, str]:
        text = text.strip()
        if not text:
            return category.title(), ""

        # Try to use the first non-empty line as title if short enough
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return category.title(), ""

        # For TRIVIA, keep the formatted lines together as body
        if category == "TRIVIA_QNA":
            return "Trivia", text

        first = lines[0]
        if len(first) <= 60 and len(lines) > 1:
            return first.rstrip(".:"), "\n".join(lines[1:])

        # Otherwise, derive a short title from the first sentence
        sentence = re.split(r"(?<=[.!?])\s", first, maxsplit=1)[0]
        if len(sentence) > 60:
            sentence = sentence[:57].rstrip() + "..."
        return sentence, text
