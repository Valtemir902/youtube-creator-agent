from pathlib import Path


def test_dashboard_elite_mobile_contract():
    html = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    assert "Elite UX hardening" in html
    assert "id=\"marketLanguage\"" in html
    assert "min-height:52px" in html
    assert "aria-label=\"Navegação principal do painel\"" in html
    assert "loading=\"lazy\"" in html
    assert "i.ytimg.com/vi/" in html


def test_csp_allows_youtube_thumbnail_hosts():
    code = Path("src/creator_service/observability.py").read_text(encoding="utf-8")
    assert "https://i.ytimg.com" in code
    assert "https://yt3.ggpht.com" in code


def test_channel_profile_keeps_market_context():
    code = Path("src/intelligence/channel_learning.py").read_text(encoding="utf-8")
    assert "country: str" in code
    assert "default_language: str" in code
    assert "brandingSettings" in code
