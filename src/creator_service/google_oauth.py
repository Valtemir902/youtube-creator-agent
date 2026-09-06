from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass

from .cloud_runtime import GOOGLE_SCOPES, GOOGLE_SECRET_NAME
from .tenant_store import TenantDatabase, TenantStoreError, validate_tenant_id


@dataclass(frozen=True)
class OAuthStart:
    tenant_id: str
    authorization_url: str
    state: str
    expires_in_seconds: int


class GoogleOAuthCoordinator:
    """Per-tenant YouTube OAuth with one-time state and encrypted token storage."""

    PKCE_SECRET_PREFIX = "oauth:google:pkce:"

    def __init__(self, db: TenantDatabase):
        self.db = db

    @staticmethod
    def _client_config() -> dict:
        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
        if not client_id or not client_secret or not redirect_uri:
            raise TenantStoreError(
                "GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET e GOOGLE_OAUTH_REDIRECT_URI são obrigatórios."
            )
        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }

    @staticmethod
    def _redirect_uri() -> str:
        return os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()

    @classmethod
    def _pkce_secret_name(cls, state: str) -> str:
        return f"{cls.PKCE_SECRET_PREFIX}{TenantDatabase.state_hash(state)}"

    def start(self, tenant_id: str, ttl_seconds: int = 600) -> OAuthStart:
        from google_auth_oauthlib.flow import Flow

        tenant_id = validate_tenant_id(tenant_id)
        self.db.ensure_tenant(tenant_id)
        state = secrets.token_urlsafe(32)
        ttl_seconds = max(120, min(1800, int(ttl_seconds)))

        flow = Flow.from_client_config(
            self._client_config(),
            scopes=GOOGLE_SCOPES,
            state=state,
            redirect_uri=self._redirect_uri(),
            autogenerate_code_verifier=True,
        )
        url, returned_state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        if returned_state != state:
            raise TenantStoreError("Falha interna ao criar estado OAuth.")
        verifier = str(flow.code_verifier or "").strip()
        if not verifier:
            raise TenantStoreError("Falha interna ao criar verificador PKCE do OAuth.")

        self.db.save_oauth_state(tenant_id, state, int(time.time()) + ttl_seconds)
        self.db.put_secret(tenant_id, self._pkce_secret_name(state), verifier)
        return OAuthStart(tenant_id, url, state, ttl_seconds)

    def complete(self, *, state: str, authorization_response: str) -> str:
        from google_auth_oauthlib.flow import Flow

        tenant_id = self.db.consume_oauth_state(state, int(time.time()))
        pkce_name = self._pkce_secret_name(state)
        verifier = self.db.get_secret(tenant_id, pkce_name)
        if not verifier:
            raise TenantStoreError("Verificador PKCE do OAuth não foi encontrado ou já expirou.")

        try:
            flow = Flow.from_client_config(
                self._client_config(),
                scopes=GOOGLE_SCOPES,
                state=state,
                redirect_uri=self._redirect_uri(),
                code_verifier=verifier,
                autogenerate_code_verifier=False,
            )
            flow.fetch_token(authorization_response=authorization_response)
            creds = flow.credentials
            payload = json.loads(creds.to_json())
            payload["scopes"] = list(GOOGLE_SCOPES)
            self.db.put_secret(
                tenant_id,
                GOOGLE_SECRET_NAME,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            )
            return tenant_id
        finally:
            self.db.delete_secret(tenant_id, pkce_name)

    def disconnect(self, tenant_id: str) -> None:
        self.db.delete_secret(validate_tenant_id(tenant_id), GOOGLE_SECRET_NAME)
