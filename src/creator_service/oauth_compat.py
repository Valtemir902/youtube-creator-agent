from __future__ import annotations

import json
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


ALLOWED_DCR_SCOPES = frozenset({
    "email",
    "profile",
    "offline_access",
    "yca:read",
    "yca:write",
})
DEFAULT_DCR_SCOPE = "yca:read"
DEFAULT_ALLOWED_REDIRECT_HOSTS = frozenset({"chatgpt.com"})
# Public OIDC client dedicated to ChatGPT. A public client id is not a secret.
DEFAULT_CHATGPT_PUBLIC_CLIENT_ID = "82da41e4-4d89-4ccf-b134-c6a8b01f8453"


class OAuthCompatError(ValueError):
    def __init__(self, error: str, description: str, status_code: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


@dataclass(frozen=True)
class UpstreamResponse:
    status_code: int
    payload: dict[str, Any]


def _keycloak_issuer() -> str:
    issuer = (
        os.environ.get("YCA_WEB_OIDC_ISSUER_URL", "").strip()
        or os.environ.get("YCA_TOKEN_ISSUER_URL", "").strip()
        or os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()
    ).rstrip("/")
    if not issuer:
        raise RuntimeError("Issuer público do Keycloak não configurado.")
    return issuer


def oauth_compat_issuer() -> str:
    issuer = (
        os.environ.get("YCA_CHATGPT_OAUTH_ISSUER_URL", "").strip()
        or os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip()
    ).rstrip("/")
    if not issuer:
        raise RuntimeError("YCA_ONBOARDING_PUBLIC_URL ou YCA_CHATGPT_OAUTH_ISSUER_URL é obrigatório.")
    return issuer


def _chatgpt_public_client_id() -> str:
    client_id = (
        os.environ.get("YCA_CHATGPT_OAUTH_CLIENT_ID", "").strip()
        or DEFAULT_CHATGPT_PUBLIC_CLIENT_ID
    )
    if not client_id:
        raise RuntimeError("Cliente OAuth público do ChatGPT não configurado.")
    return client_id


def oauth_authorization_server_metadata() -> dict[str, Any]:
    issuer = oauth_compat_issuer()
    keycloak = _keycloak_issuer()
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{keycloak}/protocol/openid-connect/auth",
        "token_endpoint": f"{keycloak}/protocol/openid-connect/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "scopes_supported": ["openid", "email", "profile", "offline_access", "yca:read", "yca:write"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


def _allowed_redirect_hosts() -> frozenset[str]:
    configured = os.environ.get("YCA_DCR_ALLOWED_REDIRECT_HOSTS", "").strip()
    if not configured:
        return DEFAULT_ALLOWED_REDIRECT_HOSTS
    return frozenset(host.strip().lower() for host in configured.split(",") if host.strip())


def _validate_redirect_uris(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise OAuthCompatError("invalid_redirect_uri", "redirect_uris deve conter pelo menos uma URL HTTPS.")
    allowed_hosts = _allowed_redirect_hosts()
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item) > 2000:
            raise OAuthCompatError("invalid_redirect_uri", "redirect_uri inválida.")
        parsed = urllib.parse.urlparse(item)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in allowed_hosts or parsed.username or parsed.password:
            raise OAuthCompatError("invalid_redirect_uri", "redirect_uri não autorizada para registro dinâmico.")
        result.append(item)
    return result


def _normalize_scope(scope_value: Any) -> str:
    if scope_value is None or scope_value == "":
        requested: list[str] = []
    elif isinstance(scope_value, str):
        requested = [part for part in scope_value.split() if part]
    else:
        raise OAuthCompatError("invalid_client_metadata", "scope deve ser uma string separada por espaços.")

    filtered: list[str] = []
    seen: set[str] = set()
    for scope in requested:
        if scope == "openid":
            # openid é um escopo de protocolo OIDC e continua sendo pedido na
            # autorização. Ele não precisa virar um Client Scope registrado.
            continue
        if scope not in ALLOWED_DCR_SCOPES:
            raise OAuthCompatError("invalid_scope", f"Escopo de registro não permitido: {scope}")
        if scope not in seen:
            filtered.append(scope)
            seen.add(scope)

    if DEFAULT_DCR_SCOPE not in seen:
        filtered.append(DEFAULT_DCR_SCOPE)
    return " ".join(filtered)


def normalize_dynamic_client_registration(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OAuthCompatError("invalid_client_metadata", "Corpo JSON inválido.")

    redirect_uris = _validate_redirect_uris(payload.get("redirect_uris"))
    auth_method = str(payload.get("token_endpoint_auth_method", "none") or "none")
    if auth_method != "none":
        raise OAuthCompatError(
            "invalid_client_metadata",
            "Somente clientes públicos com token_endpoint_auth_method=none são aceitos.",
        )

    grant_types = payload.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grant_types, list) or "authorization_code" not in grant_types:
        raise OAuthCompatError("invalid_client_metadata", "authorization_code é obrigatório.")
    allowed_grants = {"authorization_code", "refresh_token"}
    if any(grant not in allowed_grants for grant in grant_types):
        raise OAuthCompatError("invalid_client_metadata", "grant_type não permitido.")

    response_types = payload.get("response_types") or ["code"]
    if not isinstance(response_types, list) or any(item != "code" for item in response_types):
        raise OAuthCompatError("invalid_client_metadata", "Somente response_type=code é permitido.")

    normalized: dict[str, Any] = {
        "client_name": str(payload.get("client_name", "ChatGPT YouTube Creator Agent"))[:200],
        "redirect_uris": redirect_uris,
        "grant_types": grant_types,
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": _normalize_scope(payload.get("scope")),
    }

    for key in ("client_uri", "logo_uri", "tos_uri", "policy_uri", "contacts"):
        if key in payload:
            normalized[key] = payload[key]
    return normalized


def register_dynamic_client(payload: dict[str, Any]) -> UpstreamResponse:
    """RFC 7591 compatibility facade backed by one audited public Keycloak client.

    ChatGPT still performs Dynamic Client Registration against this endpoint. We
    validate the full request, but deliberately do not create anonymous Keycloak
    clients. All approved ChatGPT connections reuse the dedicated public client,
    protected by exact redirect URIs, authorization code flow and PKCE S256.
    """
    normalized = normalize_dynamic_client_registration(payload)
    response = dict(normalized)
    response.update(
        {
            "client_id": _chatgpt_public_client_id(),
            "client_id_issued_at": int(time.time()),
        }
    )
    return UpstreamResponse(status_code=201, payload=response)


def install_oauth_compat_routes(app: FastAPI) -> None:
    @app.get("/.well-known/oauth-authorization-server")
    async def oauth_metadata() -> JSONResponse:
        try:
            payload = oauth_authorization_server_metadata()
        except RuntimeError as exc:
            return JSONResponse(
                {"error": "server_error", "error_description": str(exc)},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(payload, headers={"Cache-Control": "public, max-age=300"})

    @app.post("/oauth/register")
    async def oauth_register(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            result = register_dynamic_client(payload)
            return JSONResponse(
                result.payload,
                status_code=result.status_code,
                headers={"Cache-Control": "no-store"},
            )
        except OAuthCompatError as exc:
            return JSONResponse(
                {"error": exc.error, "error_description": exc.description},
                status_code=exc.status_code,
                headers={"Cache-Control": "no-store"},
            )
        except RuntimeError as exc:
            return JSONResponse(
                {"error": "server_error", "error_description": str(exc)},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        except (ValueError, json.JSONDecodeError):
            return JSONResponse(
                {"error": "invalid_client_metadata", "error_description": "Corpo JSON inválido."},
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )
