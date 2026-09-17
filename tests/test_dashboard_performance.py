from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from creator_service.dashboard_performance import DashboardReadCache, install_dashboard_performance
from creator_service.security import Tenant


def test_dashboard_read_cache_deduplicates_concurrent_cold_reads():
    async def scenario():
        cache = DashboardReadCache(cold_timeout_seconds=1)
        calls = {"n": 0}

        async def producer(*, tenant):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return {"tenant": tenant.tenant_id}

        kwargs = {"tenant": Tenant("tenant-one")}
        key = cache.key_for("/api/dashboard/channel", kwargs)
        first, second = await asyncio.gather(
            cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=10, stale_seconds=20),
            cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=10, stale_seconds=20),
        )
        assert first == {"tenant": "tenant-one"}
        assert second == first
        assert calls["n"] == 1

    asyncio.run(scenario())


def test_dashboard_read_cache_is_tenant_isolated():
    cache = DashboardReadCache()
    one = cache.key_for("/api/dashboard/channel", {"tenant": Tenant("tenant-one")})
    two = cache.key_for("/api/dashboard/channel", {"tenant": Tenant("tenant-two")})
    assert one != two


def test_dashboard_read_cache_serves_stale_and_refreshes_in_background():
    async def scenario():
        cache = DashboardReadCache(cold_timeout_seconds=1)
        calls = {"n": 0}
        release = asyncio.Event()

        async def producer(*, tenant):
            calls["n"] += 1
            if calls["n"] > 1:
                await release.wait()
            return {"version": calls["n"], "tenant": tenant.tenant_id}

        kwargs = {"tenant": Tenant("tenant-stale")}
        key = cache.key_for("/api/dashboard/channel", kwargs)
        first = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=0, stale_seconds=10)
        assert first["version"] == 1
        stale = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=0, stale_seconds=10)
        assert stale["version"] == 1
        await asyncio.sleep(0.02)
        assert calls["n"] == 2
        release.set()
        await asyncio.sleep(0.02)
        refreshed = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=10, stale_seconds=20)
        assert refreshed["version"] == 2

    asyncio.run(scenario())


def test_dashboard_read_cache_times_out_without_blocking_forever():
    async def scenario():
        cache = DashboardReadCache(cold_timeout_seconds=0.03)

        async def producer(*, tenant):
            await asyncio.sleep(5)
            return {"tenant": tenant.tenant_id}

        kwargs = {"tenant": Tenant("tenant-timeout")}
        key = cache.key_for("/api/dashboard/channel", kwargs)
        started = time.monotonic()
        with pytest.raises(HTTPException) as error:
            await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=1, stale_seconds=2)
        elapsed = time.monotonic() - started
        assert error.value.status_code == 504
        assert elapsed < 0.5

    asyncio.run(scenario())


def test_dashboard_read_cache_uses_last_known_good_after_refresh_timeout():
    async def scenario():
        # Keep this budget short enough to exercise timeout/fallback behavior but
        # long enough for CI runner thread scheduling on the first successful read.
        cache = DashboardReadCache(cold_timeout_seconds=0.2, fallback_seconds=60)
        calls = {"n": 0}

        async def producer(*, tenant):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"value": "good"}
            await asyncio.sleep(5)
            return {"value": "late"}

        kwargs = {"tenant": Tenant("tenant-fallback")}
        key = cache.key_for("/api/dashboard/playlists", kwargs)
        first = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=0, stale_seconds=0)
        assert first == {"value": "good"}
        fallback = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=0, stale_seconds=0)
        assert fallback == {"value": "good"}

    asyncio.run(scenario())


def test_install_dashboard_performance_wraps_dashboard_get_routes():
    app = FastAPI()

    @app.get("/api/dashboard/channel")
    async def channel(tenant=None):
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"ok": True}

    install_dashboard_performance(app)
    dashboard = next(route for route in app.routes if getattr(route, "path", None) == "/api/dashboard/channel")
    health_route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    assert getattr(dashboard.endpoint, "__name__", "") == "cached_endpoint"
    assert getattr(health_route.endpoint, "__name__", "") == "health"


def test_install_dashboard_performance_keeps_post_routes_uncached():
    app = FastAPI()

    @app.post("/api/dashboard/video/abc/metadata/preview")
    async def preview():
        return {"ok": True}

    install_dashboard_performance(app)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/dashboard/video/abc/metadata/preview"
    )
    assert getattr(route.endpoint, "__name__", "") == "preview"
