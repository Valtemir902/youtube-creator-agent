import json
import urllib.request
from pathlib import Path

from desktop_native_runtime import DesktopNativeCache, desktop_fetch_bootstrap, start_native_server


def test_desktop_native_cache_round_trip_and_provenance(tmp_path: Path):
    cache = DesktopNativeCache(tmp_path / "cache.json")
    key = "/api/dashboard/channel?period_days=28"
    cache.put(key, {"channel_title": "Canal Teste", "views": 123})
    hit = cache.get(key)
    assert hit is not None
    assert hit.data["channel_title"] == "Canal Teste"
    assert hit.data["desktop_native"]["engine"] == "python_native_cache"
    assert hit.data["desktop_native"]["external_ai_used"] is False
    assert cache.get("/oauth/token") is None


def test_desktop_native_http_server_exposes_only_local_read_cache(tmp_path: Path):
    server, thread, base = start_native_server(tmp_path / "cache.json")
    try:
        with urllib.request.urlopen(base + "/health", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["ok"] is True
        assert health["external_ai_used"] is False
        assert health["writes_performed"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_desktop_bootstrap_intercepts_reads_but_not_writes():
    script = desktop_fetch_bootstrap("http://127.0.0.1:43123")
    assert "window.fetch" in script
    assert "method!=='GET'" in script
    assert "8000" in script
    assert "12000" in script
    assert "cacheablePath" in script
    assert "'/api/dashboard/channel'" in script
    assert "'/api/dashboard/channel/identity'" not in script
    assert "/api/dashboard/status" not in script
    assert "desktop_native_timeout" in script
    assert "POST" in script  # local cache persistence only


def test_desktop_bootstrap_never_recursively_calls_refresh_all():
    script = desktop_fetch_bootstrap("http://127.0.0.1:43123")
    assert "refreshAll()" not in script
    assert "yca:desktop-cache-updated" in script
    assert "lastRefresh" in script
    assert "30000" in script


def test_desktop_profile_forces_persistent_secure_cookie_storage():
    source = Path("src/desktop_web_shell.py").read_text(encoding="utf-8")
    assert "ForcePersistentCookies" in source
    assert "DiskHttpCache" in source
    assert "web-storage" in source
