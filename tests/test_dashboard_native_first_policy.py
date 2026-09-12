from pathlib import Path

from creator_service.dashboard_native_first_policy import _SCRIPT


def test_passive_dashboard_policy_never_labels_configured_external_ai_as_active():
    assert "◆ Inteligência Nativa ativa" in _SCRIPT
    assert "motor Python · dados reais" in _SCRIPT
    assert "IA externa sob demanda" in _SCRIPT
    assert "Esta verificação não consome API de IA externa" in _SCRIPT
    assert "✦ IA ativa" not in _SCRIPT


def test_passive_channel_audit_does_not_call_external_ai_advice():
    source = Path("src/creator_service/dashboard_ai_route_guard.py").read_text(encoding="utf-8")
    audit_block = source.split("async def dashboard_audit", 1)[1].split("_replace_call(app, \"/api/dashboard/audit\"", 1)[0]
    assert "grounded_channel_advice" not in audit_block
    assert '"status": "not_requested"' in audit_block
    assert '"external_ai_used": False' in audit_block
    assert '"intelligence_mode": "native_first"' in audit_block


def test_native_engine_status_exposes_explicit_ai_invocation_policy():
    source = Path("src/creator_service/free_intelligence_service.py").read_text(encoding="utf-8")
    assert '"mode": "native_first"' in source
    assert '"primary_engine": "python_native_intelligence"' in source
    assert '"passive_dashboard_uses_external_ai": False' in source
    assert '"external_ai_invocation": "explicit_user_action_only"' in source
    assert '"passive_external_ai_calls": 0' in source


def test_native_first_policy_is_installed_last_in_dashboard_app():
    source = Path("src/creator_service/oauth_compat_app.py").read_text(encoding="utf-8")
    assert 'DASHBOARD_UI_REVISION = "professional-v1.8-native-first-no-passive-ai"' in source
    policy_pos = source.index("install_dashboard_native_first_policy(app)")
    intelligence_terms_pos = source.index("install_dashboard_intelligence_terms(app)")
    assert policy_pos > intelligence_terms_pos
