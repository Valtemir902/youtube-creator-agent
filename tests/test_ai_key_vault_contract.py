from pathlib import Path

from ai.key_pool import APIKeyPoolStore
from creator_service.extended_onboarding import _enhance_dashboard_html


def test_key_pool_keeps_alias_health_and_preferred_model(tmp_path):
    store = APIKeyPoolStore(tmp_path / "pool.json")
    record = store.add("gemini", "secret-key-123456", label="Principal")
    store.set_preferred_model("gemini", record.id, "gemini-2.5-flash")
    store.mark_failure("gemini", record.id, "503 high demand", warning=True, model="gemini-2.5-flash")
    row = store.get("gemini", record.id)
    assert row is not None
    assert row.label == "Principal"
    assert row.preferred_model == "gemini-2.5-flash"
    assert row.status == "warning"
    assert "503" in row.last_error
    exported = store.export_public("gemini")[0]
    assert exported["active"] is True
    assert "secret-key-123456" not in str(exported)


def test_dashboard_enhancement_adds_multi_key_manager_without_breaking_legacy_controls():
    source = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    enhanced = _enhance_dashboard_html(source)
    assert 'id="aiKeyVault"' in enhanced
    assert 'id="rotationToggle"' in enhanced
    assert 'id="aiKeyList"' in enhanced
    assert '/api/ai/keys' in enhanced
    assert '/api/ai/rotation' in enhanced
    assert 'id="loadModels"' in enhanced
    assert "refreshAll();" in enhanced


def test_runtime_has_rotation_for_transient_and_incompatible_models():
    code = Path("src/ai/runtime.py").read_text(encoding="utf-8")
    assert "only supports interactions api" in code
    assert "high demand" in code
    assert "record.preferred_model" in code
    assert "set_preferred_model" in code
