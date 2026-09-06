from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .cloud_auth import tenant_id_from_subject
from .tenant_store import TenantDatabase


@dataclass(frozen=True)
class PendingOIDC:
    state: str
    verifier: str
    next_path: str
    mode: str


class BrowserAuthStore:
    """Short-lived OIDC state/PKCE storage for browser login flows."""

    def __init__(self, db: TenantDatabase):
        self.db = db
        self._init_db()

    def _init_db(self) -> None:
        with self.db._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS browser_auth_pending (
                    state_hash TEXT PRIMARY KEY,
                    verifier TEXT NOT NULL,
                    next_path TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    consumed_at INTEGER,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_browser_auth_expiry
                    ON browser_auth_pending(expires_at);
                """
            )

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def issue(self, *, next_path: str = "/dashboard", mode: str = "login", ttl_seconds: int = 600) -> PendingOIDC:
        if not str(next_path).startswith("/") or str(next_path).startswith("//"):
            next_path = "/dashboard"
        mode = mode if mode in {"login", "register", "recover"} else "login"
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        now = int(time.time())
        ttl = max(120, min(1200, int(ttl_seconds)))
        with self.db._connect() as conn:
            conn.execute(
                "INSERT INTO browser_auth_pending(state_hash,verifier,next_path,mode,expires_at,consumed_at,created_at) "
                "VALUES(?,?,?,?,?,NULL,?)",
                (self._hash(state), verifier, next_path, mode, now + ttl, now),
            )
            conn.execute(
                "DELETE FROM browser_auth_pending WHERE expires_at < ? OR consumed_at IS NOT NULL",
                (now - 3600,),
            )
        return PendingOIDC(state=state, verifier=verifier, next_path=next_path, mode=mode)

    def consume(self, state: str) -> PendingOIDC:
        if not state:
            raise PermissionError("Estado de autenticação ausente.")
        now = int(time.time())
        digest = self._hash(state)
        with self.db._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT verifier,next_path,mode,expires_at,consumed_at FROM browser_auth_pending WHERE state_hash=?",
                (digest,),
            ).fetchone()
            if not row:
                raise PermissionError("Sessão de autenticação inválida.")
            verifier, next_path, mode, expires_at, consumed_at = row
            if consumed_at is not None:
                raise PermissionError("Esta autenticação já foi utilizada.")
            if int(expires_at) < now:
                raise PermissionError("Esta autenticação expirou. Inicie o login novamente.")
            updated = conn.execute(
                "UPDATE browser_auth_pending SET consumed_at=? WHERE state_hash=? AND consumed_at IS NULL",
                (now, digest),
            ).rowcount
            if updated != 1:
                raise PermissionError("Esta autenticação já foi utilizada.")
        return PendingOIDC(state=state, verifier=str(verifier), next_path=str(next_path), mode=str(mode))


class TurnstileVerifier:
    """Deprecated compatibility shim.

    Browser authentication no longer uses a CAPTCHA gate in front of Keycloak.
    Abuse protection belongs with the identity-provider login/register/recovery
    flows, while this service retains rate limits plus OIDC state/nonce/PKCE.
    The class remains temporarily so older API code can roll forward safely.
    """

    def __init__(self) -> None:
        self.site_key = ""
        self.secret = ""
        self.bypass = True

    @property
    def configured(self) -> bool:
        return True

    def verify(self, token: str, remote_ip: str | None = None) -> bool:
        return True


class BrowserOIDCClient:
    """Authorization-code + PKCE browser client for the existing Keycloak realm."""

    def __init__(self) -> None:
        self.issuer = (
            os.environ.get("YCA_WEB_OIDC_ISSUER_URL", "").strip()
            or os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()
        ).rstrip("/")
        self.client_id = os.environ.get("YCA_WEB_OIDC_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("YCA_WEB_OIDC_CLIENT_SECRET", "").strip()
        public_origin = os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")
        self.redirect_uri = (
            os.environ.get("YCA_WEB_OIDC_REDIRECT_URI", "").strip()
            or (f"{public_origin}/auth/callback" if public_origin else "")
        )
        self.scope = os.environ.get("YCA_WEB_OIDC_SCOPE", "openid email profile").strip() or "openid email profile"
        self.require_verified_email = os.environ.get("YCA_REQUIRE_VERIFIED_EMAIL", "1").strip() != "0"
        if not self.issuer or not self.client_id or not self.redirect_uri:
            raise RuntimeError("Configuração OIDC web incompleta.")

    @property
    def authorization_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/auth"

    @property
    def forgot_credentials_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/forgot-credentials"

    @property
    def token_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/token"

    @property
    def userinfo_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/userinfo"

    @property
    def logout_endpoint(self) -> str:
        return f"{self.issuer}/protocol/openid-connect/logout"

    @staticmethod
    def code_challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def authorization_url(self, pending: PendingOIDC) -> str:
        endpoint = self.forgot_credentials_endpoint if pending.mode == "recover" else self.authorization_endpoint
        query = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "state": pending.state,
            "code_challenge": self.code_challenge(pending.verifier),
            "code_challenge_method": "S256",
        }
        if pending.mode == "register":
            query["prompt"] = "create"
        return f"{endpoint}?{urllib.parse.urlencode(query)}"

    def exchange_code(self, *, code: str, verifier: str) -> dict[str, Any]:
        form = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
        }
        if self.client_secret:
            form["client_secret"] = self.client_secret
        request = urllib.request.Request(
            self.token_endpoint,
            data=urllib.parse.urlencode(form).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise PermissionError("Não foi possível concluir o login seguro.") from exc
        access_token = str(data.get("access_token", "")).strip()
        if not access_token:
            raise PermissionError("O provedor de identidade não retornou um token de acesso.")
        return data

    def userinfo(self, access_token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            self.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise PermissionError("Não foi possível confirmar a identidade da conta.") from exc
        subject = str(data.get("sub", "")).strip()
        if not subject:
            raise PermissionError("A conta autenticada não possui identificador de usuário.")
        if self.require_verified_email and data.get("email") and data.get("email_verified") is False:
            raise PermissionError("Confirme seu e-mail antes de entrar no painel.")
        return data

    def tenant_id(self, subject: str) -> str:
        return tenant_id_from_subject(self.issuer, subject)

    def logout_url(self, post_logout_redirect_uri: str) -> str:
        query = {"client_id": self.client_id, "post_logout_redirect_uri": post_logout_redirect_uri}
        return f"{self.logout_endpoint}?{urllib.parse.urlencode(query)}"
