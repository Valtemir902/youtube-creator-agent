from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from creator_service.free_intelligence_workspace import _SCRIPT, install_free_intelligence_workspace


def test_free_engine_has_no_external_llm_or_youtube_content_write_calls():
    root = Path(__file__).resolve().parents[1] / "src"
    files = list((root / "intelligence").glob("free_*.py")) + [
        root / "creator_service" / "free_intelligence_service.py",
        root / "creator_service" / "free_performance_service.py",
        root / "creator_service" / "free_intelligence_dashboard.py",
        root / "creator_service" / "free_channel_dashboard.py",
        root / "creator_service" / "free_intelligence_workspace.py",
    ]
    forbidden = (
        "AIRuntime", "openai.ChatCompletion", "google.generativeai",
        ".videos().update(", ".videos().delete(", ".playlists().insert(", ".playlists().update(", ".playlists().delete(",
        ".playlistItems().insert(", ".playlistItems().delete(", ".channels().update(", ".captions().insert(", ".captions().delete(",
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{needle} found in free engine file {path.name}"


def test_injected_workspace_javascript_is_valid_node_syntax():
    js = _SCRIPT.replace("<script data-yca-free-workspace>", "", 1).rsplit("</script>", 1)[0]
    result = subprocess.run(["node", "--check"], input=js, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_workspace_injects_professional_free_cards_additively():
    app = FastAPI()

    @app.get("/dashboard")
    async def dashboard(request=None):
        return HTMLResponse("<html><head></head><body><section id='videos'><div class='grid'></div></section><section id='strategy'><div class='grid'></div></section><input id='videoId'></body></html>")

    install_free_intelligence_workspace(app)
    route = next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/dashboard")
    response = asyncio.run(route.endpoint(request=None))
    html = response.body.decode("utf-8")
    assert "data-yca-free-workspace" in html
    assert "Motor gratuito avançado" in html
    assert "Inteligência determinística do canal" in html
    assert "/api/dashboard/free/video/" in html
    assert "/api/dashboard/free/channel/optimization" in html
    assert "CTR oficial" in html
    assert "Demanda × concorrência" in html


def test_workspace_installer_is_idempotent():
    app = FastAPI()

    @app.get("/dashboard")
    async def dashboard(request=None):
        return HTMLResponse("<html><head></head><body></body></html>")

    install_free_intelligence_workspace(app)
    install_free_intelligence_workspace(app)
    routes = [r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/dashboard"]
    assert len(routes) == 1
