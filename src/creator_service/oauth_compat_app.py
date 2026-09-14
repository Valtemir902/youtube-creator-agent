from __future__ import annotations

from .ai_language_policy import install_ai_language_policy
from .ai_runtime_policy import install_ai_runtime_policy
from .ai_selection_api import install_ai_selection_api
from .ai_vault_ui import install_ai_vault_ui
from .dashboard_ai_experience import install_dashboard_ai_experience
from .dashboard_ai_route_guard import install_dashboard_ai_route_guard
from .dashboard_grounded_advice import install_grounded_strategy_service
from .dashboard_intelligence_terms import install_dashboard_intelligence_terms
from .dashboard_performance import install_dashboard_performance
from .dashboard_runtime_hotfix import install_dashboard_runtime_hotfix
from .dashboard_stability_guard import install_dashboard_stability_guard
from .extended_onboarding import create_app as create_extended_app
from .free_channel_dashboard import install_free_channel_dashboard
from .free_intelligence_dashboard import install_free_intelligence_dashboard
from .free_intelligence_service import install_free_intelligence_service
from .free_intelligence_workspace import install_free_intelligence_workspace
from .free_performance_service import install_free_performance_service
from .free_playlist_optimizer_service import install_free_playlist_optimizer_dashboard, install_free_playlist_optimizer_service
from .handoff_routes import install_handoff_routes
from .local_ai_dashboard import install_local_ai_dashboard
from .oauth_compat import install_oauth_compat_routes
from .pwa import install_pwa_routes


DASHBOARD_UI_REVISION = "elite-v2-cloud-reconnect-v1"


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
    # Keep feature-specific surfaces, but do not install presentation layers that
    # start passive YouTube/Analytics/intelligence calls on page load. The base
    # dashboard already owns navigation and cards; network work is controlled by
    # the bounded boot policy installed last.
    install_dashboard_ai_experience(app)
    install_free_intelligence_dashboard(app)
    install_free_channel_dashboard(app)
    install_free_playlist_optimizer_dashboard(app)
    install_free_intelligence_workspace(app)
    # Deduplicate/cache expensive reads without changing any write contract.
    install_dashboard_performance(app)
    install_local_ai_dashboard(app)
    install_dashboard_intelligence_terms(app)
    # Native-first/external-AI policy is enforced by backend routes and status.
    # Do not install the legacy browser policy: its only live effect without the
    # removed Pro UI was a duplicate /status read plus a document-wide observer.
    install_dashboard_stability_guard(app)
    # Cloud-only hardening: recover revoked Google tokens as a reconnect state and
    # layer the certified Elite V2 presentation over the authenticated web panel.
    install_dashboard_runtime_hotfix(app)
    app.state.dashboard_ui_revision = DASHBOARD_UI_REVISION
    return app
