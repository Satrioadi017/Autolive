"""Minimal YouTube Data API v3 helper.

Supports both API-key-only flows (read-only data like live chat & broadcast
metadata) and OAuth2 flows (when a ``client_secret.json`` is present) so the
bot can create new live broadcasts and update their title/description.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional

from config import Config

logger = logging.getLogger(__name__)


class YouTubeAPIClient:
    """Wrapper around ``googleapiclient`` with graceful no-op behaviour."""

    SCOPES = ["https://www.googleapis.com/auth/youtube"]

    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.Lock()
        self._service = None
        self._authed_service = None
        self._oauth_credentials_path = config.project_root / "client_secret.json"
        self._oauth_token_path = config.project_root / "youtube_token.json"
        self._live_chat_id: Optional[str] = None
        self._last_chat_page_token: Optional[str] = None
        self._init_api_key_client()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def update_broadcast_metadata(
        self, title: str, description: str, broadcast_id: Optional[str] = None
    ) -> bool:
        """Update title/description of a live broadcast (requires OAuth)."""
        service = self._get_authed_service()
        if service is None:
            return False
        broadcast_id = broadcast_id or self.config.youtube_broadcast_id
        if not broadcast_id:
            broadcast_id = self.get_active_broadcast_id()
        if not broadcast_id:
            logger.warning("Tidak ada broadcast_id untuk update metadata.")
            return False
        try:
            service.liveBroadcasts().update(  # type: ignore[union-attr]
                part="snippet",
                body={
                    "id": broadcast_id,
                    "snippet": {
                        "title": title[:100],
                        "description": description[:4900],
                    },
                },
            ).execute()
            logger.info("Broadcast metadata diperbarui: %s", title)
            return True
        except Exception:
            logger.exception("Gagal update broadcast metadata")
            return False

    def get_active_broadcast_id(self) -> Optional[str]:
        service = self._get_authed_service()
        if service is None:
            return None
        try:
            response = service.liveBroadcasts().list(  # type: ignore[union-attr]
                part="id,snippet",
                broadcastStatus="active",
                broadcastType="all",
                maxResults=1,
            ).execute()
            items = response.get("items", [])
            if items:
                return items[0]["id"]
        except Exception:
            logger.exception("Gagal mengambil broadcast aktif")
        return None

    def create_broadcast(self, title: str, description: str) -> Optional[str]:
        """Create a new YouTube live broadcast. Returns broadcast id."""
        service = self._get_authed_service()
        if service is None:
            return None
        try:
            start_time = time.strftime(
                "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 60)
            )
            response = service.liveBroadcasts().insert(  # type: ignore[union-attr]
                part="snippet,status,contentDetails",
                body={
                    "snippet": {
                        "title": title[:100],
                        "description": description[:4900],
                        "scheduledStartTime": start_time,
                    },
                    "status": {
                        "privacyStatus": "public",
                        "selfDeclaredMadeForKids": False,
                    },
                    "contentDetails": {
                        "enableAutoStart": True,
                        "enableAutoStop": False,
                    },
                },
            ).execute()
            broadcast_id = response.get("id")
            logger.info("Broadcast baru dibuat: %s", broadcast_id)
            return broadcast_id
        except Exception:
            logger.exception("Gagal membuat broadcast baru")
            return None

    def channel_stats(self) -> dict[str, Any]:
        """Return subscriber + view count for the configured API key channel."""
        service = self._service
        if service is None:
            return {}
        try:
            response = service.channels().list(  # type: ignore[union-attr]
                part="statistics", mine=False, forUsername=None, id=None
            ).execute()
            items = response.get("items", [])
            if items:
                return items[0].get("statistics", {})
        except Exception:
            logger.debug("channel_stats gagal (kemungkinan butuh channelId)", exc_info=True)
        return {}

    def get_subscriber_count(self, channel_id: Optional[str] = None) -> Optional[int]:
        service = self._service
        if service is None:
            return None
        try:
            params: dict[str, Any] = {"part": "statistics"}
            if channel_id:
                params["id"] = channel_id
            else:
                params["mine"] = True
                service = self._get_authed_service() or service
            response = service.channels().list(**params).execute()  # type: ignore[union-attr]
            items = response.get("items", [])
            if not items:
                return None
            stats = items[0].get("statistics", {})
            value = stats.get("subscriberCount")
            return int(value) if value is not None else None
        except Exception:
            logger.debug("get_subscriber_count gagal", exc_info=True)
            return None

    def read_live_chat(self, broadcast_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Return latest live chat messages since last poll."""
        service = self._service
        if service is None:
            return []
        if self._live_chat_id is None:
            self._live_chat_id = self._resolve_live_chat_id(
                broadcast_id or self.config.youtube_broadcast_id
            )
        if not self._live_chat_id:
            return []
        try:
            params: dict[str, Any] = {
                "liveChatId": self._live_chat_id,
                "part": "id,snippet,authorDetails",
                "maxResults": 200,
            }
            if self._last_chat_page_token:
                params["pageToken"] = self._last_chat_page_token
            response = service.liveChatMessages().list(**params).execute()  # type: ignore[union-attr]
            self._last_chat_page_token = response.get("nextPageToken")
            return response.get("items", [])
        except Exception:
            logger.debug("read_live_chat gagal", exc_info=True)
            return []

    @staticmethod
    def filter_chat_messages(
        messages: list[dict[str, Any]], keywords: list[str]
    ) -> list[dict[str, Any]]:
        normalized = [k.lower() for k in keywords if k]
        out: list[dict[str, Any]] = []
        for msg in messages:
            text = (
                msg.get("snippet", {})
                .get("displayMessage", "")
                .lower()
            )
            if any(k in text for k in normalized):
                out.append(msg)
        return out

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _init_api_key_client(self) -> None:
        if not self.config.has_youtube_api():
            logger.info("YOUTUBE_API_KEY belum di-set, fitur API dinonaktifkan.")
            return
        try:
            from googleapiclient.discovery import build  # type: ignore

            self._service = build(
                "youtube",
                "v3",
                developerKey=self.config.youtube_api_key,
                cache_discovery=False,
            )
        except ImportError:
            logger.warning("google-api-python-client tidak terinstall.")
        except Exception:
            logger.exception("Gagal membuat YouTube API client (API key).")

    def _get_authed_service(self) -> object | None:
        with self._lock:
            if self._authed_service is not None:
                return self._authed_service
            try:
                from google.auth.transport.requests import Request  # type: ignore
                from google.oauth2.credentials import Credentials  # type: ignore
                from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
                from googleapiclient.discovery import build  # type: ignore
            except ImportError:
                logger.info(
                    "Library OAuth Google tidak lengkap, fitur write API dinonaktifkan."
                )
                return None

            creds: Optional[Credentials] = None
            if self._oauth_token_path.exists():
                try:
                    creds = Credentials.from_authorized_user_file(
                        str(self._oauth_token_path), self.SCOPES
                    )
                except Exception:
                    logger.exception("Gagal memuat token OAuth")

            if creds and creds.valid:
                pass
            elif creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    logger.exception("Gagal refresh OAuth token")
                    creds = None
            else:
                if not self._oauth_credentials_path.exists():
                    logger.info(
                        "client_secret.json belum ada — write API dinonaktifkan."
                    )
                    return None
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self._oauth_credentials_path), self.SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                except Exception:
                    logger.exception("OAuth flow gagal")
                    return None

            if not creds:
                return None
            try:
                with self._oauth_token_path.open("w", encoding="utf-8") as fh:
                    fh.write(creds.to_json())
            except OSError:
                logger.exception("Gagal menyimpan token OAuth")

            try:
                self._authed_service = build(
                    "youtube", "v3", credentials=creds, cache_discovery=False
                )
            except Exception:
                logger.exception("Gagal membuat YouTube API service OAuth.")
                return None
            return self._authed_service

    def _resolve_live_chat_id(self, broadcast_id: Optional[str]) -> Optional[str]:
        service = self._service
        if service is None or not broadcast_id:
            return None
        try:
            response = service.liveBroadcasts().list(  # type: ignore[union-attr]
                part="snippet", id=broadcast_id, maxResults=1
            ).execute()
            items = response.get("items", [])
            if items:
                return items[0].get("snippet", {}).get("liveChatId")
        except Exception:
            logger.debug("Gagal resolve liveChatId", exc_info=True)
        return None
