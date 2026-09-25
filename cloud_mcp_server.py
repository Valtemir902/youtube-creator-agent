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

# Keep the responsible 34-tool surface as the production base.  The V1 bridge
# only replaces the historical preview tool with a backward-compatible read
# mode when it is called with video_id alone.  Importing the responsible run
# symbol here also preserves the production contract assertion used by CI.
from creator_service.cloud_mcp_server_responsible import run as _responsible_run
from creator_service.cloud_mcp_server_v1_compat import run


if __name__ == "__main__":
    run()
