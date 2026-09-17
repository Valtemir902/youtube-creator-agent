from __future__ import annotations

from pathlib import Path

from creator_service.dashboard_stability_guard import _apply_fast_boot_policy


def test_active_dashboard_composition_does_not_install_passive_probe_layers():
    source = Path("src/creator_service/oauth_compat_app.py").read_text(encoding="utf-8")
    assert "install_dashboard_connection_health" not in source
    assert "install_dashboard_activity_ux" not in source
    assert "install_dashboard_pro_ui" not in source
    assert "install_dashboard_native_ux" not in source
    assert "install_dashboard_native_first_policy" not in source
    assert "install_dashboard_overview_compat" not in source
    assert "install_dashboard_stability_guard(app)" in source


def test_stability_guard_replaces_automatic_full_refresh_with_independent_boot():
    source = """<script>\nasync function refreshAll(){return 'manual'}\nrefreshAll();\n</script>"""
    result = _apply_fast_boot_policy(source)
    assert "async function refreshAll()" in result
    assert "ycaInitialLoad();" in result
    assert "loadChannelIdentity()" in result
    assert "loadPlaylists()" in result
    # Videos already have a dedicated initial loader in the composed dashboard.
    # The stability guard must not add a second automatic read during boot.
    assert "loadVideos()" not in result
    assert "loadChannel()" in result
    assert "loadLive()" not in result
    assert "\nrefreshAll();\n</script>" not in result


def test_stability_guard_removes_legacy_duplicate_ai_vault_autoload():
    source = "<script>setTimeout(loadAiKeyPool,150);</script>"
    result = _apply_fast_boot_policy(source)
    assert "setTimeout(loadAiKeyPool,150);" not in result


def test_stability_guard_prevents_repeated_session_redirects():
    source = "<script>if(r.status===401){location.href='/onboarding/session-expired';throw new Error('Sessão expirada')}</script>"
    result = _apply_fast_boot_policy(source)
    assert "window.__ycaSessionRedirecting" in result
    assert "location.replace('/onboarding/session-expired')" in result


def test_stability_guard_does_not_claim_youtube_connected_from_credentials_only():
    source = "<script>if(label)label.textContent=s.youtube_connected?'Conectado':'Desconectado';</script>"
    result = _apply_fast_boot_policy(source)
    assert "Credencial disponível" in result
    assert "s.youtube_connected?'Conectado'" not in result


def test_browser_read_guard_is_get_only_and_has_bounded_light_and_heavy_reads():
    source = Path("src/creator_service/dashboard_stability_guard.py").read_text(encoding="utf-8")
    assert "method!=='GET'" in source
    assert "heavy?15000:8000" in source
    assert "'/api/dashboard/channel/identity'" in source
    assert "yca:youtube-read-verified" in source
    assert "Conectado · leitura verificada" in source
    assert "POST/PUT/PATCH/DELETE" not in source
