from creator_service.dashboard_connection_health import _SCRIPT


def test_live_youtube_probe_is_bounded_and_non_blocking():
    assert "/api/dashboard/channel/identity?live_probe=" in _SCRIPT
    assert "6500" in _SCRIPT
    assert "YouTube API verificada" in _SCRIPT
    assert "YouTube API não verificada" in _SCRIPT
    assert "stopEndlessPlaceholders" in _SCRIPT
    assert "8500" in _SCRIPT
    assert "window.refreshAll=guarded" in _SCRIPT
    assert "15000" in _SCRIPT


def test_live_probe_bypasses_dashboard_snapshot_cache_and_stays_read_only():
    source = Path("src/creator_service/dashboard_performance.py").read_text(encoding="utf-8")
    route_source = Path("src/creator_service/dashboard_routes.py").read_text(encoding="utf-8")
    assert 'request.headers.get("X-YCA-Live-Probe") == "1"' in source
    assert "async def dashboard_channel_identity(\n        request: Request," in route_source
    assert "playlists().insert" not in route_source.split("async def dashboard_channel_identity", 1)[1].split("@app.post(\"/api/dashboard/playlists\")", 1)[0]
