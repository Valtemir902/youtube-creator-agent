from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from creator_service.free_intelligence_dashboard import install_free_intelligence_dashboard


def _route(app: FastAPI, path: str):
    return next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == path)


def test_audit_gets_deterministic_free_report_without_replacing_existing_payload():
    app = FastAPI()

    @app.get("/api/dashboard/audit")
    async def audit(period_days: int = 28, tenant=None):
        return {
            "period_days": period_days,
            "channel": {
                "period_days": period_days,
                "subscribers": 10,
                "video_count": 3,
                "total_analytics_views": 100,
                "search_views": 2,
                "search_share": 0.02,
                "top_search_terms": [],
                "top_videos": [],
                "weak_videos": [],
                "topic_terms": ["café"],
            },
            "evidence": {"original": True},
            "ai_advice": {"status": "unavailable"},
        }

    @app.get("/dashboard")
    async def dashboard():
        return HTMLResponse("<html><head></head><body><div id='auditRaw'></div></body></html>")

    install_free_intelligence_dashboard(app)
    result = asyncio.run(_route(app, "/api/dashboard/audit").endpoint(period_days=28, tenant=None))
    assert result["evidence"] == {"original": True}
    assert result["ai_advice"] == {"status": "unavailable"}
    assert result["free_intelligence"]["mode"] == "deterministic_free"
    assert result["free_intelligence"]["uses_external_ai"] is False
    assert result["free_intelligence"]["writes_performed"] == 0


def test_dashboard_injects_free_intelligence_renderer_additively():
    app = FastAPI()

    @app.get("/api/dashboard/audit")
    async def audit(period_days: int = 28, tenant=None):
        return {"channel": {}, "evidence": {}}

    @app.get("/dashboard")
    async def dashboard(request=None):
        return HTMLResponse("<html><head></head><body><div id='auditRaw'></div></body></html>")

    install_free_intelligence_dashboard(app)
    response = asyncio.run(_route(app, "/dashboard").endpoint(request=None))
    html = response.body.decode("utf-8")
    assert "data-yca-free-intelligence" in html
    assert "Motor de Crescimento" in html
    assert "Dados reais" in html
    assert "auditRaw" in html


def test_installer_is_idempotent():
    app = FastAPI()

    @app.get("/api/dashboard/audit")
    async def audit(period_days: int = 28, tenant=None):
        return {"channel": {}, "evidence": {}}

    @app.get("/dashboard")
    async def dashboard(request=None):
        return HTMLResponse("<html><head></head><body><div id='auditRaw'></div></body></html>")

    install_free_intelligence_dashboard(app)
    install_free_intelligence_dashboard(app)
    dashboard_routes = [r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/dashboard"]
    assert len(dashboard_routes) == 1
