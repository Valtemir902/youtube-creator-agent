from __future__ import annotations

from elite_v2_content_hub import CONTENT_HUB_CSS, CONTENT_HUB_JS, content_hub_webengine_source


def test_content_hub_is_visual_read_only_extension() -> None:
    source = content_hub_webengine_source()
    for token in (
        "data-v2-content-tools",
        "v2ContentGuide",
        "data-v2-video-search",
        "data-v2-video-privacy",
        "Cards visuais",
        "IA sob controle",
        "Gestão segura",
    ):
        assert token in source

    assert ".video-item" in CONTENT_HUB_JS
    assert ".video-title" in CONTENT_HUB_JS
    assert "MutationObserver" in CONTENT_HUB_JS
    assert "reloadVideos" in CONTENT_HUB_JS
    assert "fetch(" not in CONTENT_HUB_JS
    assert "method:" not in CONTENT_HUB_JS.lower()
    assert "v2-video-hidden" in CONTENT_HUB_CSS
