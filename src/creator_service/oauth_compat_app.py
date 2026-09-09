from __future__ import annotations

from .ai_vault_ui import install_ai_vault_ui
from .extended_onboarding import create_app as create_extended_app
from .handoff_routes import install_handoff_routes
from .oauth_compat import install_oauth_compat_routes
from .pwa import install_pwa_routes


def create_app():
    app = create_extended_app()
    install_oauth_compat_routes(app)
    install_handoff_routes(app)
    install_pwa_routes(app)
    install_ai_vault_ui(app)
    return app
