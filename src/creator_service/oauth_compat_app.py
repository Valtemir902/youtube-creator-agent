from __future__ import annotations

from .ai_language_policy import install_ai_language_policy
from .ai_runtime_policy import install_ai_runtime_policy
from .ai_selection_api import install_ai_selection_api
from .ai_vault_ui import install_ai_vault_ui
from .dashboard_ai_experience import install_dashboard_ai_experience
from .dashboard_ai_route_guard import install_dashboard_ai_route_guard
from .dashboard_grounded_advice import install_grounded_strategy_service
from .dashboard_overview_compat import install_dashboard_overview_compat
from .dashboard_pro_ui import install_dashboard_pro_ui
from .extended_onboarding import create_app as create_extended_app
from .free_channel_dashboard import install_free_channel_dashboard
from .free_intelligence_dashboard import install_free_intelligence_dashboard
from .free_intelligence_service import install_free_intelligence_service
from .free_intelligence_workspace import install_free_intelligence_workspace
from .free_performance_service import install_free_performance_service
from .free_playlist_optimizer_service import install_free_playlist_optimizer_dashboard, install_free_playlist_optimizer_service
from .handoff_routes import install_handoff_routes
from .oauth_compat import install_oauth_compat_routes
from .pwa import install_pwa_routes


DASHBOARD_UI_REVISION = "professional-v1.4-free-intelligence"


def create_app():
    app = create_extended_app()
    install_ai_runtime_policy()
    install_grounded_strategy_service()
    install_free_intelligence_service()
    install_free_performance_service()
    install_free_playlist_optimizer_service()
    install_ai_language_policy()
    install_ai_selection_api(app)
    install_dashboard_ai_route_guard(app)
    install_oauth_compat_routes(app)
    install_handoff_routes(app)
    install_pwa_routes(app)
    install_ai_vault_ui(app)
    install_dashboard_pro_ui(app)
    install_dashboard_overview_compat(app)
    install_dashboard_ai_experience(app)
    install_free_intelligence_dashboard(app)
    install_free_channel_dashboard(app)
    install_free_playlist_optimizer_dashboard(app)
    install_free_intelligence_workspace(app)
    app.state.dashboard_ui_revision = DASHBOARD_UI_REVISION
    return app
