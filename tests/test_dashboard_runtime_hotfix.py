from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError

from creator_service.dashboard_runtime_hotfix import _dashboard_html, install_dashboard_runtime_hotfix


COMPOSED_SENTINEL = '''
<html><head><script data-yca-stability-guard>window.__priorComposition=true;</script></head>
<body><div id="aiKeyVault"><div data-ai-vault-manager-v2></div></div>
<div id="auditRaw">{"channel":{"channel_title":"Teste"}}</div>
<script>async function ycaInitialLoad(){};ycaInitialLoad();</script></body></html>
'''


def make_app() -> FastAPI:
    app = FastAPI()

    @app.get('/dashboard')
    async def dashboard(request):
        return HTMLResponse(COMPOSED_SENTINEL)

    @app.get('/boom')
    async def boom():
        raise RefreshError('invalid_grant: Token has been expired or revoked.')

    install_dashboard_runtime_hotfix(app)
    return app


def test_revoked_google_refresh_token_is_recoverable_not_500():
    client = TestClient(make_app(), raise_server_exceptions=False)
    response = client.get('/boom')
    assert response.status_code == 409
    payload = response.json()
    assert payload['code'] == 'youtube_reconnect_required'
    assert payload['reconnect_required'] is True
    assert payload['youtube_write_performed'] is False
    assert 'Reconecte' in payload['detail']


def test_cloud_layer_preserves_prior_composition_and_adds_human_results():
    client = TestClient(make_app(), raise_server_exceptions=False)
    response = client.get('/dashboard')
    assert response.status_code == 200
    assert response.headers['x-yca-dashboard-ui'] == 'elite-v2-cloud'
    assert response.headers['x-yca-dashboard-ux'] == 'human-results-key-vault'
    assert 'data-yca-stability-guard' in response.text
    assert 'window.__priorComposition=true' in response.text
    assert 'data-ai-vault-manager-v2' in response.text
    assert 'ycaInitialLoad();' in response.text
    assert 'data-yca-cloud-elite-v2' in response.text
    assert 'data-yca-google-reconnect' in response.text
    assert 'yca:youtube-reconnect-required' in response.text
    assert '__ycaYoutubeReconnectRequired' in response.text
    assert 'data-yca-human-results' in response.text
    assert 'Ver dados técnicos (JSON)' in response.text


def test_standalone_fixture_contains_real_advanced_vault_and_stability_guard():
    html = _dashboard_html()
    assert 'data-yca-stability-guard' in html
    assert 'ycaInitialLoad();' in html
    assert 'data-ai-vault-manager-v2' in html
    assert 'id="vaultModel"' in html
    assert 'id="vaultLoadModels"' in html
    assert "'/api/ai/keys/'+encodeURIComponent(id)+'/test'" in html
    assert 'data-yca-human-results' in html
    assert 'data-yca-cloud-elite-v2' in html
