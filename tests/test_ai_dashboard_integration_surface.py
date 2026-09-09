from __future__ import annotations

from fastapi.routing import APIRoute

from creator_service.oauth_compat_app import create_app


def test_grounded_ai_routes_install_without_replacing_existing_surface():
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
