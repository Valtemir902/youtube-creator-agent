from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError

from creator_service.dashboard_runtime_hotfix import install_dashboard_runtime_hotfix


def make_app() -> FastAPI:
    app = FastAPI()

    @app.get('/dashboard')
    async def dashboard():
        return HTMLResponse('<html><body>placeholder</body></html>')

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


def test_dashboard_gets_cloud_elite_v2_reconnect_key_vault_and_human_results():
    client = TestClient(make_app(), raise_server_exceptions=False)
    response = client.get('/dashboard')
    assert response.status_code == 200
    assert response.headers['x-yca-dashboard-ui'] == 'elite-v2-cloud'
    assert response.headers['x-yca-dashboard-ux'] == 'human-results-key-vault'
    assert 'data-yca-cloud-elite-v2' in response.text
    assert 'data-yca-google-reconnect' in response.text
    assert 'youtube_reconnect_required' in response.text
    assert 'data-ai-vault-manager-v2' in response.text
    assert 'id="vaultModel"' in response.text
    assert 'id="vaultLoadModels"' in response.text
    assert "'/api/ai/keys/'+encodeURIComponent(id)+'/test'" in response.text
    assert 'data-yca-human-results' in response.text
    assert 'Ver dados técnicos (JSON)' in response.text
    assert 'Elite V2' in response.text or 'v2-command' in response.text
