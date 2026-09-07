from __future__ import annotations

from .extended_onboarding import create_app as create_extended_app
from .oauth_compat import install_oauth_compat_routes


def create_app():
    app = create_extended_app()
    install_oauth_compat_routes(app)
    return app
