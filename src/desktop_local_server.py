from __future__ import annotations

import json
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from desktop_native_runtime import DesktopNativeCache
from local_ai.companion import ensure_config

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
READ_TIMEOUT_SECONDS = 8
LOCAL_CACHE_MAX_AGE_SECONDS = 5 * 60


def app_data_dir() -> Path:
    root = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(root) / "YouTubeCreatorAgent" / "DesktopLocal"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    return Path(frozen_root) if frozen_root else _repo_root()


def dashboard_html_path() -> Path:
    return _resource_root() / "src" / "creator_service" / "web" / "dashboard.html"


def credentials_path() -> Path:
    path = app_data_dir() / "youtube-token.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _client_secret_candidates() -> list[Path]:
    candidates = [
        app_data_dir() / "client_secret.json",
        _repo_root() / "config" / "client_secret.json",
    ]
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        candidates.extend(
            [
                exe.parent / "config" / "client_secret.json",
                exe.parent.parent / "config" / "client_secret.json",
                exe.parent.parent.parent / "config" / "client_secret.json",
            ]
        )
    env_path = (os.getenv("YCA_GOOGLE_CLIENT_SECRET") or "").strip()
    if env_path:
        candidates.insert(0, Path(env_path).expanduser())
    return candidates


def client_secret_path() -> Path | None:
    for candidate in _client_secret_candidates():
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def load_credentials(*, allow_interactive: bool = False) -> Credentials | None:
    token = credentials_path()
    creds: Credentials | None = None
    if token.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token), YOUTUBE_SCOPES)
        except Exception:
            creds = None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token.write_text(creds.to_json(), encoding="utf-8")
        except Exception:
            creds = None
    if creds and creds.valid:
        return creds
    if not allow_interactive:
        return None
    secret = client_secret_path()
    if secret is None:
        raise RuntimeError(
            "client_secret.json não encontrado. Coloque-o em config/ ou em "
            f"{app_data_dir()} antes de conectar o YouTube."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), YOUTUBE_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, authorization_prompt_message="")
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


class LocalYouTubeClient:
    def __init__(self) -> None:
        creds = load_credentials(allow_interactive=False)
        if creds is None:
            raise RuntimeError("YouTube não conectado neste computador.")
        self.session = AuthorizedSession(creds)

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=READ_TIMEOUT_SECONDS)
        if response.status_code == 401:
            raise RuntimeError("Autorização do YouTube expirou. Reconecte o canal.")
        try:
            payload = response.json()
        except Exception as exc:
            raise RuntimeError(f"Resposta inválida da API do YouTube: HTTP {response.status_code}") from exc
        if not response.ok:
            message = (
                ((payload.get("error") or {}).get("message"))
                if isinstance(payload, dict)
                else None
            ) or f"YouTube API HTTP {response.status_code}"
            raise RuntimeError(str(message))
        return payload

    def channel_identity(self) -> dict[str, Any]:
        payload = self._get(
            f"{YOUTUBE_API}/channels",
            {"part": "snippet,statistics,contentDetails", "mine": "true"},
        )
        items = payload.get("items") or []
        if not items:
            raise RuntimeError("Nenhum canal foi retornado pela conta conectada.")
        item = items[0]
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        thumbnails = snippet.get("thumbnails") or {}
        thumb = (thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")
        return {
            "id": item.get("id"),
            "title": snippet.get("title") or "Canal YouTube",
            "description": snippet.get("description") or "",
            "thumbnail": thumb or "",
            "country": snippet.get("country") or "Global",
            "default_language": snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage") or "",
            "subscribers": int(stats.get("subscriberCount") or 0),
            "views": int(stats.get("viewCount") or 0),
            "video_count": int(stats.get("videoCount") or 0),
            "uploads_playlist_id": ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads"),
        }

    def channel_overview(self, period_days: int = 28) -> dict[str, Any]:
        identity = self.channel_identity()
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=max(1, min(int(period_days), 365)))
        views_period = 0
        watch_hours = 0.0
        try:
            analytics = self._get(
                YOUTUBE_ANALYTICS_API,
                {
                    "ids": "channel==MINE",
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                    "metrics": "views,estimatedMinutesWatched",
                },
            )
            rows = analytics.get("rows") or []
            if rows:
                views_period = int(rows[0][0] or 0)
                watch_hours = round(float(rows[0][1] or 0) / 60.0, 2)
        except Exception:
            pass
        return {
            "channel_id": identity["id"],
            "channel_title": identity["title"],
            "subscribers": identity["subscribers"],
            "total_views": identity["views"],
            "video_count": identity["video_count"],
            "total_analytics_views": views_period,
            "watch_time_hours": watch_hours,
            "default_language": identity["default_language"] or "Não definido",
            "country": identity["country"],
            "search_share": 0.0,
            "shorts_share_of_recent_views": 0.0,
            "long_share_of_recent_views": 0.0,
            "topic_terms": [],
            "desktop_local": True,
        }

    def playlists(self) -> list[dict[str, Any]]:
        payload = self._get(
            f"{YOUTUBE_API}/playlists",
            {"part": "snippet,contentDetails,status", "mine": "true", "maxResults": 50},
        )
        rows: list[dict[str, Any]] = []
        for item in payload.get("items") or []:
            snippet = item.get("snippet") or {}
            thumbs = snippet.get("thumbnails") or {}
            thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
            rows.append(
                {
                    "id": item.get("id"),
                    "title": snippet.get("title") or "Sem título",
                    "description": snippet.get("description") or "",
                    "thumbnail": thumb or "",
                    "count": int((item.get("contentDetails") or {}).get("itemCount") or 0),
                    "privacy_status": (item.get("status") or {}).get("privacyStatus") or "private",
                }
            )
        return rows

    def videos(self, limit: int = 30) -> list[dict[str, Any]]:
        identity = self.channel_identity()
        uploads = identity.get("uploads_playlist_id")
        if not uploads:
            return []
        playlist_payload = self._get(
            f"{YOUTUBE_API}/playlistItems",
            {
                "part": "contentDetails,snippet",
                "playlistId": uploads,
                "maxResults": max(1, min(int(limit), 50)),
            },
        )
        ids = [
            str((item.get("contentDetails") or {}).get("videoId") or "")
            for item in playlist_payload.get("items") or []
        ]
        ids = [item for item in ids if item]
        if not ids:
            return []
        payload = self._get(
            f"{YOUTUBE_API}/videos",
            {"part": "snippet,statistics,status,contentDetails", "id": ",".join(ids)},
        )
        by_id = {str(item.get("id")): item for item in payload.get("items") or []}
        rows: list[dict[str, Any]] = []
        for video_id in ids:
            item = by_id.get(video_id)
            if not item:
                continue
            snippet = item.get("snippet") or {}
            stats = item.get("statistics") or {}
            thumbs = snippet.get("thumbnails") or {}
            thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
            rows.append(
                {
                    "id": video_id,
                    "title": snippet.get("title") or "Sem título",
                    "description": snippet.get("description") or "",
                    "tags": snippet.get("tags") or [],
                    "thumbnail": thumb or "",
                    "views": int(stats.get("viewCount") or 0),
                    "likes": int(stats.get("likeCount") or 0),
                    "comments": int(stats.get("commentCount") or 0),
                    "privacy_status": (item.get("status") or {}).get("privacyStatus") or "",
                    "memory": {"protected": False},
                }
            )
        return rows

    def video_details(self, video_id: str) -> dict[str, Any]:
        payload = self._get(
            f"{YOUTUBE_API}/videos",
            {"part": "snippet,statistics,status,contentDetails", "id": video_id},
        )
        items = payload.get("items") or []
        if not items:
            raise RuntimeError("Vídeo não encontrado no canal conectado.")
        item = items[0]
        return {
            "id": video_id,
            "snippet": item.get("snippet") or {},
            "statistics": item.get("statistics") or {},
            "status": item.get("status") or {},
            "contentDetails": item.get("contentDetails") or {},
            "memory": {"protected": False},
            "recent_actions": [],
        }

    def live_broadcasts(self) -> list[dict[str, Any]]:
        try:
            payload = self._get(
                f"{YOUTUBE_API}/liveBroadcasts",
                {
                    "part": "snippet,status",
                    "broadcastStatus": "all",
                    "broadcastType": "all",
                    "mine": "true",
                    "maxResults": 25,
                },
            )
        except Exception:
            return []
        rows = []
        for item in payload.get("items") or []:
            rows.append(
                {
                    "id": item.get("id"),
                    "title": (item.get("snippet") or {}).get("title") or "Live",
                    "life_cycle_status": (item.get("status") or {}).get("lifeCycleStatus") or "",
                }
            )
        return rows


class DesktopLocalRuntime:
    def __init__(self) -> None:
        self.root = app_data_dir()
        self.cache = DesktopNativeCache(self.root / "facts-cache-v2.json")
        self._auth_lock = threading.Lock()
        self._auth_in_progress = False
        self._auth_error: str | None = None

    def cached_read(self, key: str, loader) -> Any:
        hit = self.cache.get(key, max_age_seconds=LOCAL_CACHE_MAX_AGE_SECONDS)
        if hit is not None:
            return hit.data
        value = loader()
        self.cache.put(key, value)
        return value

    def force_read(self, key: str, loader) -> Any:
        value = loader()
        self.cache.put(key, value)
        return value

    def connected(self) -> bool:
        return load_credentials(allow_interactive=False) is not None

    def begin_auth(self) -> None:
        with self._auth_lock:
            if self._auth_in_progress:
                return
            self._auth_in_progress = True
            self._auth_error = None

        def worker() -> None:
            try:
                load_credentials(allow_interactive=True)
            except Exception as exc:
                self._auth_error = str(exc)[:500]
            finally:
                self._auth_in_progress = False

        threading.Thread(target=worker, name="yca-local-youtube-oauth", daemon=True).start()

    def auth_status(self) -> dict[str, Any]:
        return {
            "connected": self.connected(),
            "in_progress": self._auth_in_progress,
            "error": self._auth_error,
        }

    def disconnect(self) -> None:
        try:
            credentials_path().unlink(missing_ok=True)
        finally:
            self._auth_error = None


class _Handler(BaseHTTPRequestHandler):
    server_version = "YCA-DesktopLocal/1"

    @property
    def runtime(self) -> DesktopLocalRuntime:
        return self.server.runtime  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-YCA-Desktop-Mode", "local-first")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _html(self, status: int, html: str) -> None:
        self._send(status, html.encode("utf-8"), "text/html; charset=utf-8")

    def _error(self, exc: Exception) -> None:
        self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"detail": str(exc)[:500], "desktop_local": True})

    @staticmethod
    def _query(parsed, name: str, default: str = "") -> str:
        return (parse_qs(parsed.query).get(name) or [default])[0]

    def _dashboard_html(self) -> str:
        path = dashboard_html_path()
        html = path.read_text(encoding="utf-8")
        local_patch = r"""
<script>
window.addEventListener('DOMContentLoaded',()=>{
  document.title='YouTube Creator Agent Elite · Local';
  const online=document.getElementById('onlineText'); if(online) online.textContent='Local';
  const logout=document.getElementById('logout');
  if(logout){
    logout.textContent='Desconectar YouTube';
    logout.onclick=async()=>{await fetch('/api/local/youtube/disconnect',{method:'POST'});location.reload()};
  }
});
</script>
"""
        return html.replace("</body>", local_patch + "</body>")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in {"/", "/dashboard"}:
                self._html(HTTPStatus.OK, self._dashboard_html())
                return
            if path == "/health":
                self._json(HTTPStatus.OK, {"ok": True, "mode": "desktop_local_first", "youtube_connected": self.runtime.connected()})
                return
            if path == "/local/youtube/connecting":
                self._html(
                    HTTPStatus.OK,
                    """<!doctype html><meta charset='utf-8'><title>Conectando YouTube</title>
                    <style>body{background:#070b14;color:#f5faff;font:16px system-ui;display:grid;place-items:center;min-height:100vh}main{max-width:560px;padding:30px;border:1px solid #1d3550;border-radius:18px;background:#101a2b}small{color:#8ca0b8}</style>
                    <main><h2>Conectando o YouTube</h2><p>Conclua a autorização na janela do Google que foi aberta.</p><small>Esta autorização é local neste computador. Nenhuma sessão da VPS é necessária.</small></main>
                    <script>setInterval(async()=>{try{const r=await fetch('/api/local/youtube/auth-status');const d=await r.json();if(d.connected)location.href='/dashboard';if(d.error)document.querySelector('p').textContent=d.error}catch{}},900)</script>""",
                )
                return
            if path == "/api/local/youtube/auth-status":
                self._json(HTTPStatus.OK, self.runtime.auth_status())
                return
            if path == "/api/dashboard/status":
                config = ensure_config()
                self._json(
                    HTTPStatus.OK,
                    {
                        "youtube_connected": self.runtime.connected(),
                        "chatgpt_native_ready": True,
                        "external_ai_configured": False,
                        "ai_provider": "ollama",
                        "ai_model": config.get("model") or "",
                        "desktop_local": True,
                        "processing_location": "this_computer",
                    },
                )
                return
            if path == "/api/dashboard/capabilities":
                self._json(
                    HTTPStatus.OK,
                    {
                        "desktop_local_first": True,
                        "native_python_engine": True,
                        "local_ai": True,
                        "youtube_data_api": True,
                        "youtube_analytics_api": True,
                        "local_sqlite_memory": True,
                        "cloud_session_required": False,
                        "passive_external_ai": False,
                    },
                )
                return
            if not self.runtime.connected() and path.startswith("/api/dashboard/"):
                raise RuntimeError("YouTube não conectado. Use Configurações > adicionar canal para autorizar este computador.")
            client = LocalYouTubeClient()
            force = self._query(parsed, "refresh", "0") == "1"
            if path == "/api/dashboard/channel/identity":
                key = "/api/dashboard/channel/identity"
                loader = client.channel_identity
                data = self.runtime.force_read(key, loader) if force else self.runtime.cached_read(key, loader)
                self._json(HTTPStatus.OK, data)
                return
            if path == "/api/dashboard/channel":
                period = int(self._query(parsed, "period_days", "28") or 28)
                key = f"/api/dashboard/channel?period_days={period}"
                loader = lambda: client.channel_overview(period)
                data = self.runtime.force_read(key, loader) if force else self.runtime.cached_read(key, loader)
                self._json(HTTPStatus.OK, data)
                return
            if path == "/api/dashboard/channels":
                identity = client.channel_identity()
                self._json(HTTPStatus.OK, {"channels": [{"id": identity["id"], "title": identity["title"], "active": True}]})
                return
            if path == "/api/dashboard/playlists":
                key = "/api/dashboard/playlists"
                data = self.runtime.force_read(key, client.playlists) if force else self.runtime.cached_read(key, client.playlists)
                self._json(HTTPStatus.OK, {"playlists": data})
                return
            if path == "/api/dashboard/videos":
                limit = max(1, min(int(self._query(parsed, "limit", "30") or 30), 50))
                key = f"/api/dashboard/videos?limit={limit}"
                loader = lambda: client.videos(limit)
                data = self.runtime.force_read(key, loader) if force else self.runtime.cached_read(key, loader)
                self._json(HTTPStatus.OK, {"videos": data})
                return
            if path.startswith("/api/dashboard/video/"):
                video_id = path.rsplit("/", 1)[-1]
                self._json(HTTPStatus.OK, client.video_details(video_id))
                return
            if path == "/api/dashboard/live":
                self._json(HTTPStatus.OK, {"broadcasts": client.live_broadcasts()})
                return
            self._json(HTTPStatus.NOT_FOUND, {"detail": "Rota local ainda não implementada.", "desktop_local": True})
        except Exception as exc:
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/dashboard/channels/connect":
                self.runtime.begin_auth()
                self._json(HTTPStatus.OK, {"authorization_url": "/local/youtube/connecting", "desktop_local": True})
                return
            if path == "/api/local/youtube/disconnect":
                self.runtime.disconnect()
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if path == "/onboarding/logout":
                self._json(HTTPStatus.OK, {"ok": True, "desktop_local": True})
                return
            if path.startswith("/api/dashboard/"):
                self._json(
                    HTTPStatus.NOT_IMPLEMENTED,
                    {
                        "detail": "Esta ação de escrita ainda não foi liberada no modo local. A migração local mantém escrita bloqueada até o fluxo preview → confirmação → apply estar coberto por testes.",
                        "desktop_local": True,
                    },
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"detail": "not found"})
        except Exception as exc:
            self._error(exc)

    def do_PUT(self) -> None:  # noqa: N802
        self._json(
            HTTPStatus.NOT_IMPLEMENTED,
            {"detail": "Escrita local temporariamente bloqueada até validação preview/apply.", "desktop_local": True},
        )

    def do_DELETE(self) -> None:  # noqa: N802
        self._json(
            HTTPStatus.NOT_IMPLEMENTED,
            {"detail": "Escrita local temporariamente bloqueada até validação preview/apply.", "desktop_local": True},
        )


class DesktopLocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], runtime: DesktopLocalRuntime) -> None:
        super().__init__(address, _Handler)
        self.runtime = runtime


def start_local_app_server() -> tuple[DesktopLocalServer, threading.Thread, str]:
    runtime = DesktopLocalRuntime()
    server = DesktopLocalServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=server.serve_forever, name="yca-desktop-local-app", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"
