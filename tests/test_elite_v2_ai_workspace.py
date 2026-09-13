from __future__ import annotations

from elite_v2_ai_workspace import AI_WORKSPACE_CSS, AI_WORKSPACE_JS, ai_workspace_webengine_source


def test_ai_workspace_exposes_provider_mode_and_command_planning_without_writes() -> None:
    source = ai_workspace_webengine_source()
    for token in (
        "data-v2-ai-controls",
        "Motor preferido",
        "Modo operacional",
        "IA Local",
        "ChatGPT",
        "Supervisionado",
        "Interpretar comando",
        "Write Gateway",
    ):
        assert token in source
    assert "localStorage" in AI_WORKSPACE_JS
    assert "fetch(" not in AI_WORKSPACE_JS
    assert "method:" not in AI_WORKSPACE_JS.lower()
    assert ".v2-ai-controls" in AI_WORKSPACE_CSS


def test_destructive_language_is_classified_as_plan_only() -> None:
    assert "Solicitação destrutiva" in AI_WORKSPACE_JS
    assert "Nenhuma exclusão será executada aqui" in AI_WORKSPACE_JS
    assert "preview, aprovação explícita, readback" in AI_WORKSPACE_JS
