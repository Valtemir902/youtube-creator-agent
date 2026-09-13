from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from desktop_local_server import (
    DesktopLocalRuntime,
    LocalYouTubeClient,
    YOUTUBE_ANALYTICS_API,
    _Handler,
)
from elite_v2_write_gateway import ApprovalError, SafeWriteGateway, WriteState
from elite_v2_youtube_writes import ManualWriteSessionGate, YouTubeVideoMetadataAdapter


def read_analytics_timeseries(client: LocalYouTubeClient, period_days: int = 28) -> dict[str, Any]:
    """Read official daily YouTube Analytics data without estimating gaps."""

    days = max(7, min(int(period_days), 365))
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    try:
        payload = client._get(  # noqa: SLF001 - same local control plane, read-only endpoint
            YOUTUBE_ANALYTICS_API,
            {
                "ids": "channel==MINE",
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "metrics": "views,estimatedMinutesWatched,subscribersGained,subscribersLost",
                "dimensions": "day",
                "sort": "day",
            },
        )
    except Exception as exc:
        return {
            "available": False,
            "source": "youtube_analytics_api",
            "estimated": False,
            "period_days": days,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "rows": [],
            "error": str(exc)[:500],
        }

    rows: list[dict[str, Any]] = []
    for raw in payload.get("rows") or []:
        if len(raw) < 5:
            continue
        gained = int(raw[3] or 0)
        lost = int(raw[4] or 0)
        rows.append(
            {
                "date": str(raw[0]),
                "views": int(raw[1] or 0),
                "watch_time_hours": round(float(raw[2] or 0) / 60.0, 3),
                "subscribers_gained": gained,
                "subscribers_lost": lost,
                "subscribers_net": gained - lost,
            }
        )

    return {
        "available": True,
        "source": "youtube_analytics_api",
        "estimated": False,
        "period_days": days,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "rows": rows,
        "row_count": len(rows),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


class EliteV2Handler(_Handler):
    """Add V2 routes while delegating the stable local-first control plane."""

    @property
    def write_gateway(self) -> SafeWriteGateway:
        return self.server.write_gateway  # type: ignore[attr-defined]

    @property
    def write_gate(self) -> ManualWriteSessionGate:
        return self.server.write_gate  # type: ignore[attr-defined]

    @property
    def approval_tokens(self) -> dict[str, str]:
        return self.server.approval_tokens  # type: ignore[attr-defined]

    def _read_json_body(self, *, max_bytes: int = 1_000_000) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length") or 0)
        if size < 0 or size > max_bytes:
            raise ValueError("payload JSON excede o limite local")
        raw = self.rfile.read(size) if size else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError("payload JSON inválido") from exc
        if not isinstance(payload, dict):
            raise ValueError("payload deve ser um objeto JSON")
        return payload

    def _require_connected(self) -> None:
        if not self.runtime.connected():
            raise RuntimeError("YouTube não conectado neste computador.")

    def _refresh_video_list_cache(self, client: LocalYouTubeClient) -> None:
        self.runtime.force_read("/api/dashboard/videos?limit=30", lambda: client.videos(30))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/v2/write-mode":
            self._json(
                HTTPStatus.OK,
                {
                    "enabled": self.write_gate.enabled,
                    "confirmation_required": ManualWriteSessionGate.CONFIRMATION,
                    "session_only": True,
                    "youtube_write_performed": False,
                },
            )
            return
        if path != "/api/v2/analytics/timeseries":
            super().do_GET()
            return
        try:
            if not self.runtime.connected():
                self._json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "available": False,
                        "source": "youtube_analytics_api",
                        "estimated": False,
                        "rows": [],
                        "detail": "YouTube não conectado neste computador.",
                        "desktop_local": True,
                    },
                )
                return
            days = max(7, min(int(self._query(parsed, "period_days", "28") or 28), 365))
            force = self._query(parsed, "refresh", "0") == "1"
            key = f"/api/v2/analytics/timeseries?period_days={days}"
            loader = lambda: read_analytics_timeseries(LocalYouTubeClient(), days)
            data = self.runtime.force_read(key, loader) if force else self.runtime.cached_read(key, loader)
            self._json(HTTPStatus.OK, data)
        except Exception as exc:
            self._error(exc)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/v2/write-mode":
                payload = self._read_json_body(max_bytes=10_000)
                enabled = bool(payload.get("enabled"))
                state = self.write_gate.set_enabled(enabled, confirmation=payload.get("confirmation"))
                self._json(
                    HTTPStatus.OK,
                    {
                        "enabled": state,
                        "session_only": True,
                        "youtube_write_performed": False,
                    },
                )
                return

            if path == "/api/dashboard/metadata/preview":
                self._require_connected()
                payload = self._read_json_body()
                video_id = str(payload.get("video_id") or "").strip()
                if not video_id:
                    raise ValueError("video_id é obrigatório")
                client = LocalYouTubeClient()
                current = YouTubeVideoMetadataAdapter(client).current_metadata(video_id)
                proposed = {
                    "title": current["title"] if payload.get("title") is None else str(payload.get("title")),
                    "description": current["description"] if payload.get("description") is None else str(payload.get("description")),
                    "tags": current["tags"] if payload.get("tags") is None else list(payload.get("tags") or []),
                }
                proposal, token = self.write_gateway.preview(
                    idempotency_key=f"metadata:{video_id}:{uuid4()}",
                    target_kind="video",
                    target_id=video_id,
                    operation="update",
                    current=current,
                    proposed=proposed,
                    reversible=True,
                )
                self.approval_tokens[proposal.proposal_id] = token
                changed = {key: key in proposal.diff for key in ("title", "description", "tags")}
                self._json(
                    HTTPStatus.OK,
                    {
                        "action_id": proposal.proposal_id,
                        "current": current,
                        "proposed": proposed,
                        "changed": changed,
                        "state": proposal.state.value,
                        "write_mode_enabled": self.write_gate.enabled,
                        "youtube_write_performed": False,
                    },
                )
                return

            if path.startswith("/api/dashboard/metadata/apply/"):
                self._require_connected()
                if not self.write_gate.enabled:
                    self._json(
                        HTTPStatus.LOCKED,
                        {
                            "detail": "Gerenciamento manual está bloqueado nesta sessão. Ative-o em Configurações antes de aplicar.",
                            "write_mode_enabled": False,
                            "youtube_write_performed": False,
                        },
                    )
                    return
                payload = self._read_json_body(max_bytes=10_000)
                if payload.get("confirmed") is not True:
                    raise ApprovalError("confirmação explícita ausente")
                action_id = path.rsplit("/", 1)[-1]
                proposal = self.write_gateway.get(action_id)
                if proposal.state is WriteState.AWAITING_APPROVAL:
                    token = self.approval_tokens.pop(action_id, None)
                    if not token:
                        raise ApprovalError("token local de aprovação expirou")
                    self.write_gateway.approve(action_id, token)
                client = LocalYouTubeClient()
                adapter = YouTubeVideoMetadataAdapter(client)
                result = self.write_gateway.apply(action_id, adapter)
                self._refresh_video_list_cache(client)
                self._json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "state": result.state.value,
                        "readback_verified": result.state is WriteState.VERIFIED,
                        "rollback_preview": {
                            "action_id": result.proposal_id,
                            "current": result.proposed,
                            "restore": result.current,
                        }
                        if result.reversible
                        else None,
                        "youtube_write_actions_executed": adapter.writes_performed,
                    },
                )
                return

            if path.startswith("/api/dashboard/metadata/rollback/"):
                self._require_connected()
                if not self.write_gate.enabled:
                    self._json(HTTPStatus.LOCKED, {"detail": "Gerenciamento manual está bloqueado nesta sessão."})
                    return
                payload = self._read_json_body(max_bytes=10_000)
                if payload.get("confirmed") is not True:
                    raise ApprovalError("confirmação explícita ausente")
                action_id = path.rsplit("/", 1)[-1]
                client = LocalYouTubeClient()
                adapter = YouTubeVideoMetadataAdapter(client)
                result = self.write_gateway.rollback(action_id, adapter)
                self._refresh_video_list_cache(client)
                self._json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "state": result.state.value,
                        "youtube_write_actions_executed": adapter.writes_performed,
                    },
                )
                return

            super().do_POST()
        except PermissionError as exc:
            self._json(HTTPStatus.FORBIDDEN, {"detail": str(exc), "youtube_write_performed": False})
        except (ApprovalError, ValueError, KeyError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"detail": str(exc), "youtube_write_performed": False})
        except Exception as exc:
            self._error(exc)


class EliteV2LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], runtime: DesktopLocalRuntime) -> None:
        super().__init__(address, EliteV2Handler)
        self.runtime = runtime
        self.write_gateway = SafeWriteGateway()
        self.write_gate = ManualWriteSessionGate()
        self.approval_tokens: dict[str, str] = {}


def start_elite_v2_local_app_server() -> tuple[EliteV2LocalServer, threading.Thread, str]:
    runtime = DesktopLocalRuntime()
    server = EliteV2LocalServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=server.serve_forever, name="yca-elite-v2-local-app", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"
