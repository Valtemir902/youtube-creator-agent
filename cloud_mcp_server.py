from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# The MCP advertises a small OAuth 2.0 compatibility issuer for ChatGPT while
# token introspection and tenant identity remain anchored to the real Keycloak
# issuer. This avoids Keycloak DCR treating OIDC's `openid` protocol scope as a
# registered client-scope object.
keycloak_issuer = os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()
compat_issuer = (
    os.environ.get("YCA_CHATGPT_OAUTH_ISSUER_URL", "").strip()
    or os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip()
)
if keycloak_issuer and compat_issuer:
    os.environ.setdefault("YCA_TOKEN_ISSUER_URL", keycloak_issuer)
    os.environ["YCA_AUTH_ISSUER_URL"] = compat_issuer.rstrip("/")

from creator_service.cloud_mcp_server_extended import run


if __name__ == "__main__":
    run()
