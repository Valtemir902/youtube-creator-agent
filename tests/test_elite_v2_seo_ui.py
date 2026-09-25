from __future__ import annotations

from elite_v2_seo_ui import SEO_UI_CSS, SEO_UI_JS, seo_ui_webengine_source


def test_seo_lab_is_read_only_and_labels_provenance() -> None:
    source = seo_ui_webengine_source()
    for token in (
        "data-v2-seo-lab",
        "SEO & Strategy Lab",
        "/api/v2/seo/video/",
        "não inventa volume de busca nem CTR",
        "Separação de evidência",
    ):
        assert token in source
    assert "method:" not in SEO_UI_JS.lower()
    assert "POST" not in SEO_UI_JS
    assert "PUT" not in SEO_UI_JS
    assert "DELETE" not in SEO_UI_JS
    assert ".v2-seo-lab" in SEO_UI_CSS


def test_seo_lab_can_sync_existing_selected_video_without_mutating_it() -> None:
    assert "document.getElementById('videoId')" in SEO_UI_JS
    assert "Analisar fatos" in SEO_UI_JS
    assert "recommendation" in SEO_UI_JS
