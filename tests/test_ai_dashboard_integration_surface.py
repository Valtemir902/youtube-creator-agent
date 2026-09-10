from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.routing import APIRoute

import creator_service.extended_onboarding as extended_onboarding
from creator_service.oauth_compat_app import create_app


class _TestVerifier:
    async def verify_token(self, token):
        return None


def test_grounded_ai_routes_install_without_replacing_existing_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("YCA_ROOT", str(tmp_path))
    monkeypatch.setenv("YCA_DATA_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("YCA_TENANT_DB_PATH", str(tmp_path / "tenants.sqlite3"))
    monkeypatch.setattr(extended_onboarding, "IntrospectionTokenVerifier", _TestVerifier)

    app = create_app()
    routes = {route.path: route for route in app.router.routes if isinstance(route, APIRoute)}

    assert "/api/ai/selection" in routes
    assert "/api/dashboard/audit" in routes
    assert "/api/dashboard/strategy/build" in routes
    assert "/api/dashboard/video/{video_id}/ai-optimize" in routes
    assert "/api/dashboard/free/channel/optimization" in routes
    assert "/api/dashboard/free/channel/trend" in routes
    assert "/api/dashboard/free/channel/publication-strategy" in routes
    assert "/api/dashboard/free/video/{video_id}/performance" in routes
    assert "/api/dashboard/free/video/{video_id}/reach" in routes
    assert "/api/dashboard/free/video/{video_id}/retention" in routes
    assert app.state.dashboard_ui_revision == "professional-v1.4-free-intelligence"
    assert app.state.free_intelligence_dashboard_installed is True
    assert app.state.free_channel_dashboard_installed is True

    video_call = routes["/api/dashboard/video/{video_id}/ai-optimize"].dependant.call
    assert video_call.__name__ == "video_ai_optimize"
    audit_call = routes["/api/dashboard/audit"].dependant.call
    assert audit_call.__name__ == "dashboard_audit"
