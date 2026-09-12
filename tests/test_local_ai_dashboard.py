from src.creator_service.local_ai_dashboard import LOCAL_AI_INSTALLER_URL, _SCRIPT


def test_dashboard_exposes_versioned_direct_installer_link():
    assert LOCAL_AI_INSTALLER_URL.endswith(
        "/releases/download/local-ai-v1.0.0/YCA-Local-AI-Setup.exe"
    )
    assert "github.com/Valtemir902/youtube-creator-agent" in LOCAL_AI_INSTALLER_URL


def test_dashboard_pairs_through_fragment_and_loopback_handshake():
    assert "#local-ai-token=" not in _SCRIPT
    assert "local-ai-token=" in _SCRIPT
    assert "location.hash" in _SCRIPT
    assert "localStorage.setItem('yca_local_ai_token'" in _SCRIPT
    assert "/v1/pair" in _SCRIPT
    assert "autoPair" in _SCRIPT
    assert "legacy_companion" in _SCRIPT


def test_dashboard_avoids_an_unnecessary_preflight_for_legacy_health_checks():
    assert "if(opts.body!==undefined&&!headers['Content-Type'])" in _SCRIPT
    assert "credentials:'omit'" in _SCRIPT


def test_dashboard_uses_loopback_bridge_and_bearer_auth():
    assert "http://127.0.0.1:17823" in _SCRIPT
    assert "Authorization" in _SCRIPT
    assert "Bearer ${token()}" in _SCRIPT


def test_dashboard_polls_install_and_recovers_after_companion_appears():
    assert "/v1/install-status" in _SCRIPT
    assert "state.install?.status==='running'" in _SCRIPT
    assert "else if(!state.connected)delay=3000" in _SCRIPT
    assert "estimated_download_mb" in _SCRIPT
    assert "local-ai-progress-fill" in _SCRIPT


def test_dashboard_embeds_professional_local_ai_command_center():
    assert "Central de Comando IA Local" in _SCRIPT
    assert "Diagnóstico SEO avançado" in _SCRIPT
    assert "Otimizar vídeo atual" in _SCRIPT
    assert "Estratégia de 30 dias" in _SCRIPT
    assert "Ideias de conteúdo" in _SCRIPT
    assert "runCommand" in _SCRIPT
    assert "Diferencie fato, inferência e hipótese" in _SCRIPT


def test_local_ai_is_grounded_on_native_evidence():
    assert "EVIDÊNCIAS NATIVAS" in _SCRIPT
    assert "Use SOMENTE os fatos" in _SCRIPT
    assert "Nunca invente CTR" in _SCRIPT
    assert "Não execute nem afirme ter executado alterações no YouTube" in _SCRIPT


def test_local_ai_never_changes_youtube_directly_from_browser():
    forbidden = (
        "apply_video_metadata_update",
        "apply_playlist_metadata_update",
        "apply_channel_profile_update",
        "videos.update",
        "playlists.update",
    )
    assert all(item not in _SCRIPT for item in forbidden)
