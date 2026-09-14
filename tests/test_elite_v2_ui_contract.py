from __future__ import annotations

from elite_v2_ui import V2_CSS, V2_JS, elite_v2_webengine_source


def test_elite_v2_preserves_safe_read_only_ui_contract() -> None:
    source = elite_v2_webengine_source()

    for token in (
        "data-v2-command-center",
        "data-v2-growth-deck",
        "data-v2-ai-workspace",
        "Content Hub",
        "Growth & SEO",
        "AI Workspace",
        "Local-first protegido",
        "Não é previsão de crescimento",
        "/api/dashboard/videos?limit=10",
        "/api/dashboard/status",
    ):
        assert token in V2_JS or token in source

    assert "prefers-reduced-motion" in V2_CSS
    assert "Dados reais" in V2_JS
    assert "Sem métricas inventadas" in V2_JS
    assert "Readback e auditoria" in V2_JS

    # The V2 presentation layer may read data, but must not become a write path.
    upper = V2_JS.upper()
    assert "METHOD:'POST'" not in upper
    assert 'METHOD:"POST"' not in upper
    assert "METHOD:'PUT'" not in upper
    assert 'METHOD:"PUT"' not in upper
    assert "METHOD:'DELETE'" not in upper
    assert 'METHOD:"DELETE"' not in upper


def test_dynamic_video_titles_are_escaped_before_html_rendering() -> None:
    assert "const esc=" in V2_JS
    assert "${esc(v.title||'Vídeo')}" in V2_JS
    assert "${v.title||'Vídeo'}" not in V2_JS
