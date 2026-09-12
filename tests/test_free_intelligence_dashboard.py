from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from creator_service.free_intelligence_dashboard import install_free_intelligence_dashboard


def _route(app: FastAPI, path: str):
    return next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == path)


def _add_dashboard_contract(app: FastAPI) -> None:
    class Service:
        def status(self):
            return {"ok": True}

        def free_channel_intelligence(self, period_days=28):
            return {"mode": "deterministic_free", "period_days": period_days}

        def free_channel_trend(self, period_days=28):
            return {"mode": "deterministic_free", "period_days": period_days, "status": "stable"}

        def free_publication_strategy(self, period_days=28):
            return {"period_days": period_days, "recommendation_ready": False}

        def free_video_intelligence(self, video_id, period_days=28):
            return {"mode": "deterministic_free", "video_id": video_id, "period_days": period_days}

        def free_video_optimization_plan(self, video_id, period_days=28):
            return {"video_id": video_id, "optimization_ready": False, "blocked_reason": "teste"}

        def free_video_retention(self, video_id, period_days=28):
            return {"video_id": video_id, "data_available": True, "period_days": period_days}

        def free_video_reach(self, video_id):
            return {"video_id": video_id, "source": "youtube_reporting_api", "data_available": False}

        def free_video_performance(self, video_id, period_days=28):
            return {"video_id": video_id, "period_days": period_days, "writes_performed": 0}

        def free_category_suggestion(self, video_id):
            return {"video_id": video_id, "suggestion_ready": False}

        def free_catalog_opportunities(self, period_days=28, max_videos=5):
            return {"period_days": period_days, "max_videos": max_videos, "opportunities": []}

        def free_plan_route(self, action, plan="free", credits=0, ai_opt_in=False):
            return {"action": action, "plan": plan, "credits": credits, "ai_opt_in": ai_opt_in, "route": "deterministic_free"}

        def free_channel_action_plan(self, period_days=28, max_videos=3):
            return {"mode": "deterministic_free", "period_days": period_days, "max_videos": max_videos}

        def preview_video_metadata_update(self, **kwargs):
            return {"preview": True, **kwargs}

    service = Service()

    def service_for(tenant_id: str):
        return service

    async def readable():
        return None

    async def writable():
        return None

    @app.get("/api/dashboard/status")
    async def dashboard_status(tenant=Depends(readable)):
        return service_for("tenant").status()

    @app.post("/api/dashboard/video/{video_id}/ai-optimize")
    async def ai_optimize(video_id: str, tenant=Depends(writable)):
        return {"video_id": video_id}


def _base_app() -> FastAPI:
    app = FastAPI()
    _add_dashboard_contract(app)

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
    async def dashboard(request=None):
        return HTMLResponse("<html><head></head><body><div id='auditRaw'></div></body></html>")

    return app


def test_audit_gets_deterministic_free_report_without_replacing_existing_payload():
    app = _base_app()
    install_free_intelligence_dashboard(app)
    result = asyncio.run(_route(app, "/api/dashboard/audit").endpoint(period_days=28, tenant=None))
    assert result["evidence"] == {"original": True}
    assert result["ai_advice"] == {"status": "unavailable"}
    assert result["free_intelligence"]["mode"] == "deterministic_free"
    assert result["free_intelligence"]["uses_external_ai"] is False
    assert result["free_intelligence"]["writes_performed"] == 0


def test_dashboard_injects_free_intelligence_renderer_additively():
    app = _base_app()
    install_free_intelligence_dashboard(app)
    response = asyncio.run(_route(app, "/dashboard").endpoint(request=None))
    html = response.body.decode("utf-8")
    assert "data-yca-free-intelligence" in html
    assert "Motor de Crescimento" in html
    assert "Dados reais" in html
    assert "auditRaw" in html


def test_free_engine_routes_are_exposed_without_replacing_ai_route():
    app = _base_app()
    install_free_intelligence_dashboard(app)
    paths = {r.path for r in app.router.routes if isinstance(r, APIRoute)}
    expected = {
        "/api/dashboard/free/channel",
        "/api/dashboard/free/channel/trend",
        "/api/dashboard/free/channel/publication-strategy",
        "/api/dashboard/free/video/{video_id}",
        "/api/dashboard/free/video/{video_id}/optimization",
        "/api/dashboard/free/video/{video_id}/retention",
        "/api/dashboard/free/video/{video_id}/reach",
        "/api/dashboard/free/video/{video_id}/performance",
        "/api/dashboard/free/video/{video_id}/category",
        "/api/dashboard/free/catalog-opportunities",
        "/api/dashboard/free/action-plan",
        "/api/dashboard/free/plan-route",
        "/api/dashboard/free/video/{video_id}/preview",
        "/api/dashboard/video/{video_id}/ai-optimize",
    }
    assert expected <= paths


def test_installer_is_idempotent():
    app = _base_app()
    install_free_intelligence_dashboard(app)
    install_free_intelligence_dashboard(app)
    dashboard_routes = [r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/dashboard"]
    free_preview_routes = [r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/api/dashboard/free/video/{video_id}/preview"]
    assert len(dashboard_routes) == 1
    assert len(free_preview_routes) == 1
