from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ai.registry import AIProviderRegistry
from creator_service.ai_vault_ui import enhance_ai_vault_html
from creator_service.extended_onboarding import _enhance_dashboard_html


def _enhanced_dashboard() -> str:
    source = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    return enhance_ai_vault_html(_enhance_dashboard_html(source))


def test_vault_manager_hides_legacy_ui_but_preserves_legacy_controls():
    html = _enhanced_dashboard()
    assert 'class="card full legacy-ai-config" hidden aria-hidden="true"' in html
    assert 'id="loadModels"' in html
    assert 'id="saveAi"' in html
    assert '/api/ai/config' in html
    assert html.count('Inteligência artificial externa opcional') == 1


def test_vault_manager_has_compact_scrollable_selection_actions():
    html = _enhanced_dashboard()
    for element_id in (
        "vaultSelectAll",
        "vaultTest",
        "vaultModel",
        "vaultRename",
        "vaultEnable",
        "vaultDisable",
        "vaultDelete",
        "vaultModelPanel",
        "aiKeyList",
    ):
        assert f'id="{element_id}"' in html
    assert "max-height:390px" in html
    assert "overflow:auto" in html
    assert "vault-key-check" in html
    assert "✅" in html and "⚠️" in html and "❌" in html
    assert "k.masked" in html
    assert "k.api_key" not in html


def test_vault_manager_keeps_backend_contract_and_exact_id_actions():
    html = _enhanced_dashboard()
    assert "'/api/ai/keys?provider='" in html
    assert "'/api/ai/keys/'+encodeURIComponent(id)" in html
    assert "method:'PATCH'" in html
    assert "method:'DELETE'" in html
    assert "'/api/ai/rotation'" in html
    assert "'/api/ai/config'" in html
    assert "for(const k of rows)" in html


def test_supported_provider_boundary_is_explicit_and_not_hardcoded_to_models():
    registry = AIProviderRegistry()
    assert set(registry.available_providers()) == {
        "gemini",
        "openai",
        "groq",
        "xai",
        "ollama",
        "openai_compatible",
    }
    code = Path("src/ai/registry.py").read_text(encoding="utf-8")
    assert "Providers expose their own active model lists at runtime" in code
    assert "OpenAI-compatible" in code


def test_injected_vault_javascript_is_syntax_valid_when_node_is_available():
    node = shutil.which("node")
    if not node:
        return
    html = _enhanced_dashboard()
    match = re.search(r'<script data-ai-vault-manager-v2>(.*?)</script>', html, re.S)
    assert match is not None
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(match.group(1))
        path = handle.name
    try:
        result = subprocess.run([node, "--check", path], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
    finally:
        Path(path).unlink(missing_ok=True)
