from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from desktop_local_server import (
    DesktopLocalRuntime,
    LocalYouTubeClient,
    YOUTUBE_ANALYTICS_API,
    _Handler,
)


def read_analytics_timeseries(client: LocalYouTubeClient, period_days: int = 28) -> dict[str, Any]:
    """Read official daily YouTube Analytics data without estimating gaps.

    An unavailable Analytics response is represented explicitly as unavailable.
    It is never converted into plausible-looking zeroes because those would be
    indistinguishable from a genuinely quiet channel in the UI.
    """

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
    """Add V2 read-only analytics routes while delegating all stable routes."""

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/v2/analytics/timeseries":
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


class EliteV2LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], runtime: DesktopLocalRuntime) -> None:
        super().__init__(address, EliteV2Handler)
        self.runtime = runtime


def start_elite_v2_local_app_server() -> tuple[EliteV2LocalServer, threading.Thread, str]:
    runtime = DesktopLocalRuntime()
    server = EliteV2LocalServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=server.serve_forever, name="yca-elite-v2-local-app", daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, f"http://{host}:{port}"
