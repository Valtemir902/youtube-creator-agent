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



def test_overview_prioritizes_channel_profile_and_switcher():
    html = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    assert 'id="channelProfileCard"' in html
    assert 'id="channelDescription"' in html
    assert 'id="kpiTotalViews"' in html
    assert 'id="channelSelect"' in html
    assert 'id="addChannel"' in html
    assert 'id="playlistHomeSlot"' in html
    assert html.index('id="channelProfileCard"') < html.index('id="playlistHomeSlot"') < html.index('Inteligência do mercado do canal')


def test_multi_channel_backend_contract_exists():
    code = Path("src/creator_service/channel_accounts.py").read_text(encoding="utf-8")
    routes = Path("src/creator_service/dashboard_routes.py").read_text(encoding="utf-8")
    assert 'CHANNEL_REGISTRY_SECRET' in code
    assert 'def activate_channel' in code
    assert '/api/dashboard/channels/connect' in routes
    assert '/api/dashboard/channels/{channel_id}/activate' in routes
