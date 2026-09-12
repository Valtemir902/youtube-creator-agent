from __future__ import annotations

import asyncio
import subprocess

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from creator_service.dashboard_native_ux import _SCRIPT, install_dashboard_native_ux


def _app() -> FastAPI:
    app = FastAPI()

    @app.get('/dashboard')
    async def dashboard(request: Request):
        return HTMLResponse('''<html><head></head><body>
        <header class="topbar"><div class="top-actions"><button id="logout">Sair</button></div></header>
        <section id="overview"><div class="grid"><article class="card"><h3>Proteção</h3></article><article class="card"><h3>Inteligência</h3></article><article class="card"><h3>Capacidades conectadas</h3></article></div></section>
        <section id="videos"><div class="grid"></div></section><section id="strategy"><div class="grid"></div></section>
        <section id="settings"><div class="settings-grid"><article class="card full"><h3>Tema do painel</h3></article></div></section>
        <nav class="mobile-nav"><button data-tab="settings">Ajustes</button></nav>
        </body></html>''')

    return app


def test_native_ux_injects_once_and_rebrands_primary_intelligence():
    app = _app()
    install_dashboard_native_ux(app)
    install_dashboard_native_ux(app)
    route = next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == '/dashboard')
    response = asyncio.run(route.endpoint(request=None))
    html = response.body.decode('utf-8')
    assert html.count('data-yca-native-ux') == 2  # style + script markers
    assert 'Inteligência Nativa ativa' in html
    assert 'Inteligência Nativa do vídeo' in html
    assert 'Inteligência Nativa do canal' in html
    assert 'nativeSettingsButton' in html
    assert 'Sair da conta' in html
    assert 'tech-details .code{display:none!important}' in html


def test_native_ux_javascript_is_valid_node_syntax():
    js = _SCRIPT.replace('<script data-yca-native-ux>', '', 1).rsplit('</script>', 1)[0]
    result = subprocess.run(['node', '--check'], input=js, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_native_ux_keeps_external_ai_as_premium_optional_and_native_engine_primary():
    source = _SCRIPT
    assert 'IA externa Premium' in source
    assert 'motor próprio · dados reais' in source
    assert '/api/dashboard/free/channel' in source
    assert '/api/dashboard/free/channel/trend' in source
    assert '/api/dashboard/free/action-plan?max_videos=3' in source
    assert "evidence.classList.add('native-hide')" in source
    assert "old.classList.add('native-hide')" in source
