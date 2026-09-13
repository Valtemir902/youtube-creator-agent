from __future__ import annotations

import threading
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from desktop_local_server import DesktopLocalRuntime, LocalYouTubeClient
from elite_v2_analytics import EliteV2Handler
from elite_v2_seo import analyze_metadata_facts, build_seo_context
from elite_v2_write_gateway import SafeWriteGateway
from elite_v2_youtube_writes import ManualWriteSessionGate


class EliteV2ProductHandler(EliteV2Handler):
    """Product-level V2 routes layered over the stable local-first API."""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v2/activity":
            limit = max(1, min(int(self._query(parsed, "limit", "100") or 100), 500))
            events = list(reversed(self.write_gateway.audit[-limit:]))
            self._json(
                HTTPStatus.OK,
                {
                    "events": events,
                    "event_count": len(events),
                    "source": "local_write_gateway_audit",
                    "youtube_write_performed": False,
                },
            )
            return
        if not path.startswith("/api/v2/seo/video/"):
            super().do_GET()
            return
        try:
            if not self.runtime.connected():
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "available": False,
                        "source": "youtube_data_api_metadata",
                        "estimated": False,
                        "detail": "YouTube não conectado neste computador.",
                    },
                )
                return
            video_id = unquote(path.rsplit("/", 1)[-1]).strip()
            if not video_id:
                raise ValueError("video_id é obrigatório")
            details = LocalYouTubeClient().video_details(video_id)
            snippet = details.get("snippet") or {}
            video = {
                "title": snippet.get("title") or "",
                "description": snippet.get("description") or "",
                "tags": snippet.get("tags") or [],
            }
            facts = analyze_metadata_facts(video)
            context = build_seo_context(video)
            self._json(
                HTTPStatus.OK,
                {
                    "available": True,
                    "video_id": video_id,
                    "analysis": facts,
                    "context": context,
                    "youtube_write_performed": False,
                },
            )
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"detail": str(exc), "youtube_write_performed": False})
        except Exception as exc:
            self._error(exc)


class EliteV2ProductServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], runtime: DesktopLocalRuntime) -> None:
        super().__init__(address, EliteV2ProductHandler)
        self.runtime = runtime
        self.write_gateway = SafeWriteGateway()
        self.write_gate = ManualWriteSessionGate()
        self.approval_tokens: dict[str, str] = {}


def start_elite_v2_product_server() -> tuple[EliteV2ProductServer, threading.Thread, str]:
    runtime = DesktopLocalRuntime()
    server = EliteV2ProductServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=server.serve_forever, name="yca-elite-v2-product", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"
