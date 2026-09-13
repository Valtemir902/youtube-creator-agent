from __future__ import annotations

from elite_v2_ai_execution_ui import AI_EXEC_JS, ai_execution_ui_webengine_source


def test_ai_execution_ui_requires_explicit_click_and_returns_proposal_only() -> None:
    source = ai_execution_ui_webengine_source()
    for token in (
        "data-v2-ai-exec",
        "/api/v2/ai/status",
        "/api/v2/ai/propose",
        "requires_explicit_approval",
        "youtube_write_performed",
        "Gerar proposta",
    ):
        assert token in source
    click = AI_EXEC_JS.index("button.addEventListener('click'")
    propose = AI_EXEC_JS.index("fetch('/api/v2/ai/propose")
    assert propose > click
    assert "/api/v2/manage/apply/" not in AI_EXEC_JS
    assert "/api/dashboard/metadata/apply/" not in AI_EXEC_JS
