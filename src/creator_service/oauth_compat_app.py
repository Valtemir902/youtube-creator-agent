from __future__ import annotations

from .ai_language_policy import install_ai_language_policy
from .ai_vault_ui import install_ai_vault_ui
from .dashboard_pro_ui import install_dashboard_pro_ui
from .extended_onboarding import create_app as create_extended_app
from .handoff_routes import install_handoff_routes
from .oauth_compat import install_oauth_compat_routes
from .pwa import install_pwa_routes


DASHBOARD_UI_REVISION = "professional-v1"


def create_app():
    app = create_extended_app()
    install_ai_language_policy()
    install_oauth_compat_routes(app)
    install_handoff_routes(app)
    install_pwa_routes(app)
    install_ai_vault_ui(app)
    install_dashboard_pro_ui(app)
    app.state.dashboard_ui_revision = DASHBOARD_UI_REVISION
    return app
