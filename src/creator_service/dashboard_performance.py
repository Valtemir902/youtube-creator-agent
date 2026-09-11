from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import FastAPI
from fastapi.routing import APIRoute


@dataclass
class _CacheEntry:
    value: Any
    stored_at: float


class DashboardReadCache:
    """Small per-process stale-while-revalidate cache for expensive dashboard reads.

    The dashboard read endpoints ultimately call synchronous Google clients.  Running
    those coroutine endpoints directly on the ASGI event loop makes unrelated tabs
    wait behind them.  This cache executes cold reads in worker threads, deduplicates
    identical in-flight requests and serves a recent stale value while refreshing it.
    """

    def __init__(self) -> None:
        self._entries: dict[tuple[Any, ...], _CacheEntry] = {}
        self._locks: dict[tuple[Any, ...], asyncio.Lock] = {}
        self._refreshing: set[tuple[Any, ...]] = set()

    @staticmethod
    def _tenant_id(kwargs: dict[str, Any]) -> str:
        tenant = kwargs.get("tenant")
        return str(getattr(tenant, "tenant_id", "") or "")

    @staticmethod
    def _freeze(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (tuple, list)):
            return tuple(DashboardReadCache._freeze(item) for item in value)
        if isinstance(value, dict):
            return tuple(sorted((str(k), DashboardReadCache._freeze(v)) for k, v in value.items()))
        tenant_id = getattr(value, "tenant_id", None)
        if tenant_id is not None:
            return ("tenant", str(tenant_id))
        return repr(value)

    def key_for(self, path: str, kwargs: dict[str, Any]) -> tuple[Any, ...]:
        clean = {
            key: value
            for key, value in kwargs.items()
            if key not in {"request", "background_tasks", "authorization"}
        }
        return (path, tuple(sorted((key, self._freeze(value)) for key, value in clean.items())))

    async def _invoke(self, fn: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
        # Read handlers are async wrappers around synchronous google-api-python-client
        # calls. Running the complete handler in a worker thread prevents those calls
        # from freezing the main ASGI event loop.
        if inspect.iscoroutinefunction(fn):
            def runner() -> Any:
                return asyncio.run(fn(**kwargs))
            return await asyncio.to_thread(runner)
        return await asyncio.to_thread(fn, **kwargs)

    async def _refresh(
        self,
        key: tuple[Any, ...],
        fn: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> None:
        if key in self._refreshing:
            return
        self._refreshing.add(key)
        try:
            value = await self._invoke(fn, kwargs)
            self._entries[key] = _CacheEntry(value=value, stored_at=time.monotonic())
        except Exception:
            # A failed background refresh must not erase the last known-good value.
            pass
        finally:
            self._refreshing.discard(key)

    async def get(
        self,
        *,
        key: tuple[Any, ...],
        fn: Callable[..., Any],
        kwargs: dict[str, Any],
        ttl_seconds: float,
        stale_seconds: float,
    ) -> Any:
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is not None:
            age = now - entry.stored_at
            if age <= ttl_seconds:
                return entry.value
            if age <= stale_seconds:
                asyncio.create_task(self._refresh(key, fn, dict(kwargs)))
                return entry.value

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            entry = self._entries.get(key)
            if entry is not None and time.monotonic() - entry.stored_at <= ttl_seconds:
                return entry.value
            value = await self._invoke(fn, kwargs)
            self._entries[key] = _CacheEntry(value=value, stored_at=time.monotonic())
            return value

    def invalidate_tenant(self, tenant_id: str) -> None:
        tenant_id = str(tenant_id or "")
        if not tenant_id:
            return
        doomed = [key for key in self._entries if ("tenant", tenant_id) in repr(key)]
        for key in doomed:
            self._entries.pop(key, None)


_READ_POLICIES: dict[str, tuple[float, float]] = {
    "/api/dashboard/status": (20.0, 90.0),
    "/api/dashboard/capabilities": (120.0, 600.0),
    "/api/dashboard/channel": (45.0, 300.0),
    "/api/dashboard/channels": (60.0, 300.0),
    "/api/dashboard/channel/identity": (180.0, 900.0),
    "/api/dashboard/playlists": (90.0, 600.0),
    "/api/dashboard/videos": (45.0, 300.0),
    "/api/dashboard/video/{video_id}": (30.0, 180.0),
    "/api/dashboard/evidence": (90.0, 600.0),
    "/api/dashboard/audit": (90.0, 600.0),
    "/api/dashboard/free/channel": (90.0, 600.0),
    "/api/dashboard/free/channel/trend": (180.0, 1200.0),
    "/api/dashboard/free/channel/publication-strategy": (180.0, 1200.0),
    "/api/dashboard/free/video/{video_id}": (90.0, 600.0),
    "/api/dashboard/free/video/{video_id}/optimization": (90.0, 600.0),
    "/api/dashboard/free/video/{video_id}/retention": (180.0, 1200.0),
    "/api/dashboard/free/video/{video_id}/reach": (300.0, 1800.0),
    "/api/dashboard/free/video/{video_id}/performance": (120.0, 900.0),
    "/api/dashboard/free/video/{video_id}/category": (300.0, 1800.0),
    "/api/dashboard/free/catalog-opportunities": (180.0, 1200.0),
    "/api/dashboard/free/action-plan": (120.0, 900.0),
}


def _replace_call(route: APIRoute, replacement: Callable[..., Awaitable[Any]]) -> None:
    replacement.__signature__ = inspect.signature(route.endpoint)  # type: ignore[attr-defined]
    route.endpoint = replacement
    route.dependant.call = replacement


def install_dashboard_performance(app: FastAPI) -> None:
    """Install non-invasive acceleration around the existing dashboard API.

    No YouTube write contract is changed.  Successful dashboard mutations merely
    invalidate cached read snapshots so subsequent readback remains trustworthy.
    """
    if getattr(app.state, "dashboard_performance_installed", False):
        return

    cache = DashboardReadCache()

    for route in list(app.router.routes):
        if not isinstance(route, APIRoute):
            continue
        methods = set(route.methods or ())
        policy = _READ_POLICIES.get(route.path)
        if policy is not None and "GET" in methods:
            original = route.endpoint
            ttl, stale = policy
            path = route.path

            async def cached_call(
                *args: Any,
                __original: Callable[..., Any] = original,
                __ttl: float = ttl,
                __stale: float = stale,
                __path: str = path,
                **kwargs: Any,
            ) -> Any:
                # FastAPI's existing dependant passes named values according to the
                # preserved original signature. Positional values are only expected
                # in direct unit tests, where binding restores the same kwargs.
                if args:
                    bound = inspect.signature(__original).bind_partial(*args, **kwargs)
                    kwargs = dict(bound.arguments)
                key = cache.key_for(__path, kwargs)
                return await cache.get(
                    key=key,
                    fn=__original,
                    kwargs=kwargs,
                    ttl_seconds=__ttl,
                    stale_seconds=__stale,
                )

            cached_call.__name__ = f"cached_{getattr(original, '__name__', 'dashboard_read')}"
            _replace_call(route, cached_call)
            continue

        if route.path.startswith("/api/dashboard/") and methods.intersection({"POST", "PUT", "PATCH", "DELETE"}):
            original = route.endpoint

            async def mutating_call(
                *args: Any,
                __original: Callable[..., Any] = original,
                **kwargs: Any,
            ) -> Any:
                result = await __original(*args, **kwargs)
                tenant = kwargs.get("tenant")
                cache.invalidate_tenant(str(getattr(tenant, "tenant_id", "") or ""))
                return result

            mutating_call.__name__ = f"invalidate_{getattr(original, '__name__', 'dashboard_write')}"
            _replace_call(route, mutating_call)

    app.state.dashboard_read_cache = cache
    app.state.dashboard_performance_installed = True
