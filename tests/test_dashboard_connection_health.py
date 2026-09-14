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
