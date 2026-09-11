from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from creator_service.dashboard_activity_ux import install_dashboard_activity_ux


def test_activity_ux_injects_progress_monitor_into_dashboard():
    app = FastAPI()

    @app.get('/dashboard', response_class=HTMLResponse)
    async def dashboard(request: Request):
        return HTMLResponse('<html><head></head><body><main>Dashboard</main></body></html>')

    install_dashboard_activity_ux(app)
    response = TestClient(app).get('/dashboard')
    assert response.status_code == 200
    assert 'data-yca-activity-ux' in response.text
    assert 'Processando dados' in response.text
    assert 'Calculando score e diagnóstico do canal' in response.text
    assert 'IA Premium interpretando evidências do canal' in response.text
    assert 'window.fetch=async function' in response.text


def test_activity_ux_is_idempotent():
    app = FastAPI()

    @app.get('/dashboard', response_class=HTMLResponse)
    async def dashboard(request: Request):
        return HTMLResponse('<html><head></head><body>ok</body></html>')

    install_dashboard_activity_ux(app)
    install_dashboard_activity_ux(app)
    response = TestClient(app).get('/dashboard')
    assert response.text.count('<style data-yca-activity-ux>') == 1
    assert response.text.count('<script data-yca-activity-ux>') == 1
    assert response.text.count('if(window.__ycaActivityUx)return') == 1
