from src.creator_service.local_ai_dashboard import LOCAL_AI_INSTALLER_URL, _SCRIPT


def test_dashboard_exposes_versioned_direct_installer_link():
    assert LOCAL_AI_INSTALLER_URL.endswith(
        "/releases/download/local-ai-v1.0.0/YCA-Local-AI-Setup.exe"
    )
    assert "github.com/Valtemir902/youtube-creator-agent" in LOCAL_AI_INSTALLER_URL


def test_dashboard_pairs_through_url_fragment_not_server_query_string():
    assert "#local-ai-token=" not in _SCRIPT
    assert "local-ai-token=" in _SCRIPT
    assert "location.hash" in _SCRIPT
    assert "localStorage.setItem('yca_local_ai_token'" in _SCRIPT


def test_dashboard_uses_loopback_bridge_and_bearer_auth():
    assert "http://127.0.0.1:17823" in _SCRIPT
    assert "Authorization" in _SCRIPT
    assert "Bearer ${token()}" in _SCRIPT


def test_local_ai_is_grounded_on_native_evidence():
    assert "EVIDÊNCIAS NATIVAS" in _SCRIPT
    assert "Use SOMENTE os fatos" in _SCRIPT
    assert "Não invente métricas" in _SCRIPT


def test_local_ai_never_changes_youtube_directly_from_browser():
    forbidden = (
        "apply_video_metadata_update",
        "apply_playlist_metadata_update",
        "apply_channel_profile_update",
        "videos.update",
        "playlists.update",
    )
    assert all(item not in _SCRIPT for item in forbidden)
