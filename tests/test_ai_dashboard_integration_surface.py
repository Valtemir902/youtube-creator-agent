from __future__ import annotations

from cryptography.fernet import Fernet
from fastapi.routing import APIRoute

from creator_service.oauth_compat_app import create_app


def test_grounded_ai_routes_install_without_replacing_existing_surface(tmp_path, monkeypatch):
    monkeypatch.setenv("YCA_ROOT", str(tmp_path))
    monkeypatch.setenv("YCA_DATA_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("YCA_TENANT_DB_PATH", str(tmp_path / "tenants.sqlite3"))

    app = create_app()
    routes = {
        route.path: route
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }

    assert "/api/ai/selection" in routes
    assert "/api/dashboard/audit" in routes
    assert "/api/dashboard/strategy/build" in routes
    assert "/api/dashboard/video/{video_id}/ai-optimize" in routes
    assert app.state.dashboard_ui_revision == "professional-v1.2-grounded-ai"

    video_call = routes["/api/dashboard/video/{video_id}/ai-optimize"].dependant.call
    assert video_call.__name__ == "video_ai_optimize"
    audit_call = routes["/api/dashboard/audit"].dependant.call
    assert audit_call.__name__ == "dashboard_audit"
