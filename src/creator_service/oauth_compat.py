from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


ALLOWED_DCR_SCOPES = frozenset({"email", "profile", "offline_access", "yca:read", "yca:write"})
REQUIRED_DCR_SCOPES = ("openid", "email", "offline_access", "yca:read", "yca:write")
DEFAULT_ALLOWED_REDIRECT_HOSTS = frozenset({"chatgpt.com"})
DEFAULT_LEGACY_CHATGPT_CLIENT_ID = "82da41e4-4d89-4ccf-b134-c6a8b01f8453"
DEFAULT_DCR_CLIENT_PREFIX = "yca-chatgpt-dcr-"


class OAuthCompatError(ValueError):
    def __init__(self, error: str, description: str, status_code: int = 400):
        super().__init__(description)
        self.error, self.description, self.status_code = error, description, status_code


@dataclass(frozen=True)
class UpstreamResponse:
    status_code: int
    payload: dict[str, Any]


class DynamicClientStore(Protocol):
    def resolve_or_create(self, registration: dict[str, Any]) -> str: ...


def _keycloak_issuer() -> str:
    issuer = (os.environ.get("YCA_WEB_OIDC_ISSUER_URL", "").strip() or os.environ.get("YCA_TOKEN_ISSUER_URL", "").strip() or os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()).rstrip("/")
    if not issuer:
        raise RuntimeError("Issuer público do Keycloak não configurado.")
    return issuer


def oauth_compat_issuer() -> str:
    issuer = (os.environ.get("YCA_CHATGPT_OAUTH_ISSUER_URL", "").strip() or os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip()).rstrip("/")
    if not issuer:
        raise RuntimeError("YCA_ONBOARDING_PUBLIC_URL ou YCA_CHATGPT_OAUTH_ISSUER_URL é obrigatório.")
    return issuer


def legacy_chatgpt_client_id() -> str:
    return os.environ.get("YCA_CHATGPT_OAUTH_CLIENT_ID", "").strip() or DEFAULT_LEGACY_CHATGPT_CLIENT_ID


def dcr_client_prefix() -> str:
    value = os.environ.get("YCA_DCR_CLIENT_ID_PREFIX", "").strip() or DEFAULT_DCR_CLIENT_PREFIX
    if not value.replace("-", "").replace("_", "").isalnum() or len(value) > 80:
        raise RuntimeError("YCA_DCR_CLIENT_ID_PREFIX inválido.")
    return value


def oauth_authorization_server_metadata() -> dict[str, Any]:
    issuer, keycloak = oauth_compat_issuer(), _keycloak_issuer()
    return {"issuer": issuer, "authorization_endpoint": f"{keycloak}/protocol/openid-connect/auth", "token_endpoint": f"{keycloak}/protocol/openid-connect/token", "registration_endpoint": f"{issuer}/oauth/register", "scopes_supported": list(REQUIRED_DCR_SCOPES) + ["profile"], "response_types_supported": ["code"], "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"], "token_endpoint_auth_methods_supported": ["none"]}


def _allowed_redirect_hosts() -> frozenset[str]:
    configured = os.environ.get("YCA_DCR_ALLOWED_REDIRECT_HOSTS", "").strip()
    hosts = configured.split(",") if configured else list(DEFAULT_ALLOWED_REDIRECT_HOSTS)
    clean = frozenset(host.strip().rstrip(".").lower() for host in hosts if host.strip())
    if not clean or any("*" in host or "." not in host for host in clean):
        raise RuntimeError("YCA_DCR_ALLOWED_REDIRECT_HOSTS inválido.")
    return clean


def _canonical_redirect_uri(value: str, allowed_hosts: frozenset[str]) -> str:
    if not isinstance(value, str) or not value or len(value) > 2000 or any(char.isspace() for char in value):
        raise OAuthCompatError("invalid_redirect_uri", "redirect_uri inválida.")
    try:
        parsed, port = urllib.parse.urlsplit(value), urllib.parse.urlsplit(value).port
    except ValueError as exc:
        raise OAuthCompatError("invalid_redirect_uri", "redirect_uri inválida.") from exc
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not parsed.netloc or not host or parsed.username is not None or parsed.password is not None or parsed.fragment or host not in allowed_hosts or "*" in host or (port is not None and port != 443):
        raise OAuthCompatError("invalid_redirect_uri", "redirect_uri não autorizada para registro dinâmico.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise OAuthCompatError("invalid_redirect_uri", "redirect_uri não autorizada para registro dinâmico.")
    return urllib.parse.urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))


def _validate_redirect_uris(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise OAuthCompatError("invalid_redirect_uri", "redirect_uris deve conter pelo menos uma URL HTTPS.")
    return sorted({_canonical_redirect_uri(item, _allowed_redirect_hosts()) for item in value})


def _normalize_scope(scope_value: Any) -> str:
    if scope_value is None or scope_value == "":
        requested: list[str] = []
    elif isinstance(scope_value, str):
        requested = [part for part in scope_value.split() if part]
    else:
        raise OAuthCompatError("invalid_client_metadata", "scope deve ser uma string separada por espaços.")
    unknown = set(requested) - set(ALLOWED_DCR_SCOPES) - {"openid"}
    if unknown:
        raise OAuthCompatError("invalid_scope", f"Escopo de registro não permitido: {sorted(unknown)[0]}")
    return " ".join(REQUIRED_DCR_SCOPES)


def normalize_dynamic_client_registration(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OAuthCompatError("invalid_client_metadata", "Corpo JSON inválido.")
    name = payload.get("client_name", "ChatGPT YouTube Creator Agent")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
        raise OAuthCompatError("invalid_client_metadata", "client_name inválido.")
    if str(payload.get("token_endpoint_auth_method", "none") or "none") != "none":
        raise OAuthCompatError("invalid_client_metadata", "Somente clientes públicos com token_endpoint_auth_method=none são aceitos.")
    grants = payload.get("grant_types") or ["authorization_code", "refresh_token"]
    if not isinstance(grants, list) or "authorization_code" not in grants or set(grants) - {"authorization_code", "refresh_token"}:
        raise OAuthCompatError("invalid_client_metadata", "grant_type não permitido.")
    response_types = payload.get("response_types") or ["code"]
    if not isinstance(response_types, list) or set(response_types) != {"code"}:
        raise OAuthCompatError("invalid_client_metadata", "Somente response_type=code é permitido.")
    return {"client_name": name.strip(), "redirect_uris": _validate_redirect_uris(payload.get("redirect_uris")), "grant_types": sorted(set(grants)), "response_types": ["code"], "token_endpoint_auth_method": "none", "scope": _normalize_scope(payload.get("scope"))}


def _registration_fingerprint(registration: dict[str, Any]) -> str:
    stable = {key: registration[key] for key in ("client_name", "redirect_uris", "grant_types", "response_types", "scope")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class KeycloakDynamicClientStore:
    """Narrow Keycloak Admin API adapter for deterministic public DCR clients."""
    def __init__(self, *, opener=urllib.request.urlopen):
        self.opener = opener
        self.base_url = os.environ.get("YCA_KEYCLOAK_ADMIN_URL", "").strip().rstrip("/")
        self.realm = os.environ.get("YCA_KEYCLOAK_REALM", "yca").strip()
        self.service_client_id = os.environ.get("YCA_DCR_PROVISIONER_CLIENT_ID", "").strip()
        self.service_client_secret = os.environ.get("YCA_DCR_PROVISIONER_CLIENT_SECRET", "").strip()
        if not all((self.base_url, self.realm, self.service_client_id, self.service_client_secret)):
            raise RuntimeError("Provisionador DCR do Keycloak não configurado.")

    def _request(self, method: str, path: str, token: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
        request = urllib.request.Request(f"{self.base_url}{path}", data=json.dumps(body).encode("utf-8") if body is not None else None, method=method, headers={"Authorization": f"Bearer {token}", "Accept": "application/json", **({"Content-Type": "application/json"} if body is not None else {})})
        try:
            with self.opener(request, timeout=8) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try: return exc.code, json.loads(raw) if raw else None
            except json.JSONDecodeError: return exc.code, raw
        except (OSError, ValueError) as exc:
            raise RuntimeError("Não foi possível comunicar com o provisionador Keycloak.") from exc

    def _access_token(self) -> str:
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": self.service_client_id, "client_secret": self.service_client_secret}).encode("ascii")
        request = urllib.request.Request(f"{self.base_url}/realms/{urllib.parse.quote(self.realm)}/protocol/openid-connect/token", data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        try:
            with self.opener(request, timeout=8) as response: token = json.loads(response.read().decode("utf-8")).get("access_token", "")
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            raise RuntimeError("Não foi possível autenticar o provisionador DCR no Keycloak.") from exc
        if not isinstance(token, str) or not token: raise RuntimeError("Provisionador DCR do Keycloak não retornou access token.")
        return token

    def resolve_or_create(self, registration: dict[str, Any]) -> str:
        client_id, token = dcr_client_prefix() + _registration_fingerprint(registration)[:32], self._access_token()
        realm, query = urllib.parse.quote(self.realm), urllib.parse.urlencode({"clientId": client_id, "exact": "true"})
        status, found = self._request("GET", f"/admin/realms/{realm}/clients?{query}", token)
        if status != 200: raise RuntimeError("Não foi possível consultar cliente DCR no Keycloak.")
        if found: return client_id
        body = {"clientId": client_id, "name": registration["client_name"], "protocol": "openid-connect", "enabled": True, "publicClient": True, "standardFlowEnabled": True, "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False, "implicitFlowEnabled": False, "redirectUris": registration["redirect_uris"], "webOrigins": [], "attributes": {"pkce.code.challenge.method": "S256", "yca.dcr.fingerprint": _registration_fingerprint(registration)}}
        status, _ = self._request("POST", f"/admin/realms/{realm}/clients", token, body)
        if status not in (201, 204, 409): raise RuntimeError("Não foi possível criar cliente DCR no Keycloak.")
        status, found = self._request("GET", f"/admin/realms/{realm}/clients?{query}", token)
        if status != 200 or not found: raise RuntimeError("Cliente DCR não ficou disponível no Keycloak.")
        internal_id = str(found[0].get("id", ""))
        status, scopes = self._request("GET", f"/admin/realms/{realm}/client-scopes", token)
        if status != 200 or not internal_id: raise RuntimeError("Não foi possível configurar escopos do cliente DCR.")
        scope_ids = {str(item.get("name")): str(item.get("id")) for item in scopes if isinstance(item, dict)}
        for scope_name in ("yca:read", "yca:write"):
            scope_id = scope_ids.get(scope_name)
            if not scope_id: raise RuntimeError(f"Escopo obrigatório ausente no Keycloak: {scope_name}")
            status, _ = self._request("PUT", f"/admin/realms/{realm}/clients/{urllib.parse.quote(internal_id)}/default-client-scopes/{urllib.parse.quote(scope_id)}", token)
            if status not in (200, 204): raise RuntimeError(f"Não foi possível associar escopo DCR: {scope_name}")
        return client_id


def register_dynamic_client(payload: dict[str, Any], *, store: DynamicClientStore | None = None) -> UpstreamResponse:
    registration = normalize_dynamic_client_registration(payload)
    client_id = (store or KeycloakDynamicClientStore()).resolve_or_create(registration)
    return UpstreamResponse(status_code=201, payload={**registration, "client_id": client_id, "client_id_issued_at": int(time.time())})


def install_oauth_compat_routes(app: FastAPI) -> None:
    @app.get("/.well-known/oauth-authorization-server")
    async def oauth_metadata() -> JSONResponse:
        try: return JSONResponse(oauth_authorization_server_metadata(), headers={"Cache-Control": "public, max-age=300"})
        except RuntimeError as exc: return JSONResponse({"error": "server_error", "error_description": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
    @app.post("/oauth/register")
    async def oauth_register(request: Request) -> JSONResponse:
        try:
            result = register_dynamic_client(await request.json())
            return JSONResponse(result.payload, status_code=result.status_code, headers={"Cache-Control": "no-store"})
        except OAuthCompatError as exc: return JSONResponse({"error": exc.error, "error_description": exc.description}, status_code=exc.status_code, headers={"Cache-Control": "no-store"})
        except RuntimeError as exc: return JSONResponse({"error": "server_error", "error_description": str(exc)}, status_code=503, headers={"Cache-Control": "no-store"})
        except (ValueError, json.JSONDecodeError): return JSONResponse({"error": "invalid_client_metadata", "error_description": "Corpo JSON inválido."}, status_code=400, headers={"Cache-Control": "no-store"})
