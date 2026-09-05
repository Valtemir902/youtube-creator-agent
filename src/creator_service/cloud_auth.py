from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
from hashlib import sha256

from mcp.server.auth.provider import AccessToken, TokenVerifier


def tenant_id_from_subject(issuer: str, subject: str) -> str:
    if not subject:
        raise ValueError("Token autenticado não possui subject.")
    digest = sha256(f"{issuer}|{subject}".encode("utf-8")).hexdigest()[:32]
    return f"u_{digest}"


class IntrospectionTokenVerifier(TokenVerifier):
    """RFC 7662 verifier for an external OAuth/OIDC authorization server."""

    def __init__(self):
        self.endpoint = os.environ.get("YCA_AUTH_INTROSPECTION_URL", "").strip()
        self.client_id = os.environ.get("YCA_AUTH_INTROSPECTION_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "").strip()
        self.resource = os.environ.get("YCA_MCP_PUBLIC_URL", "").strip()
        self.issuer = os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()
        if not all((self.endpoint, self.client_id, self.client_secret, self.resource, self.issuer)):
            raise RuntimeError("Configuração OAuth do resource server está incompleta.")

    def _introspect(self, token: str) -> dict:
        body = urllib.parse.urlencode({"token": token}).encode("ascii")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return {}

    async def verify_token(self, token: str) -> AccessToken | None:
        data = self._introspect(token)
        if not data.get("active"):
            return None
        subject = str(data.get("sub", "")).strip()
        if not subject:
            return None
        scope_value = data.get("scope", "")
        scopes = scope_value.split() if isinstance(scope_value, str) else list(scope_value or [])
        expires_at = int(data.get("exp", 0) or 0) or None
        if expires_at and expires_at < int(time.time()):
            return None
        aud = data.get("aud")
        audiences = [aud] if isinstance(aud, str) else list(aud or [])
        if audiences and self.resource not in audiences:
            return None
        return AccessToken(
            token=token,
            client_id=str(data.get("client_id", "chatgpt")),
            scopes=scopes,
            expires_at=expires_at,
            resource=self.resource,
            subject=subject,
            claims={"tenant_id": tenant_id_from_subject(self.issuer, subject)},
        )
