import asyncio
import time
from dataclasses import dataclass

from creator_service.dashboard_performance import DashboardReadCache


@dataclass
class Tenant:
    tenant_id: str


def test_dashboard_read_cache_reuses_fresh_value_and_invalidates_per_tenant():
    async def scenario():
        cache = DashboardReadCache()
        calls = {"n": 0}

        async def producer(*, tenant):
            calls["n"] += 1
            await asyncio.sleep(0.01)
            return {"value": calls["n"], "tenant": tenant.tenant_id}

        kwargs = {"tenant": Tenant("tenant-a")}
        key = cache.key_for("/api/dashboard/channel", kwargs)
        first = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=60, stale_seconds=120)
        second = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=60, stale_seconds=120)
        assert first == second == {"value": 1, "tenant": "tenant-a"}
        assert calls["n"] == 1

        cache.invalidate_tenant("tenant-a")
        third = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=60, stale_seconds=120)
        assert third["value"] == 2
        assert calls["n"] == 2

    asyncio.run(scenario())


def test_dashboard_read_cache_deduplicates_simultaneous_cold_reads():
    async def scenario():
        cache = DashboardReadCache()
        calls = {"n": 0}

        async def producer(*, tenant):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return {"ok": True, "tenant": tenant.tenant_id}

        kwargs = {"tenant": Tenant("tenant-b")}
        key = cache.key_for("/api/dashboard/videos", kwargs)
        values = await asyncio.gather(*[
            cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=30, stale_seconds=60)
            for _ in range(5)
        ])
        assert calls["n"] == 1
        assert values == [{"ok": True, "tenant": "tenant-b"}] * 5

    asyncio.run(scenario())


def test_dashboard_read_cache_returns_stale_immediately_and_refreshes_in_background():
    async def scenario():
        cache = DashboardReadCache()
        calls = {"n": 0}

        async def producer(*, tenant):
            calls["n"] += 1
            await asyncio.sleep(0.03)
            return {"version": calls["n"], "tenant": tenant.tenant_id}

        kwargs = {"tenant": Tenant("tenant-c")}
        key = cache.key_for("/api/dashboard/free/channel", kwargs)
        first = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=0.01, stale_seconds=5)
        assert first["version"] == 1
        await asyncio.sleep(0.02)

        started = time.monotonic()
        stale = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=0.01, stale_seconds=5)
        elapsed = time.monotonic() - started
        assert stale["version"] == 1
        assert elapsed < 0.02

        await asyncio.sleep(0.08)
        refreshed = await cache.get(key=key, fn=producer, kwargs=kwargs, ttl_seconds=1, stale_seconds=5)
        assert refreshed["version"] == 2
        assert calls["n"] == 2

    asyncio.run(scenario())
