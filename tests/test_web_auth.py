from __future__ import annotations

import io
import urllib.error
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from creator_service.tenant_store import EncryptionBox, TenantDatabase
from creator_service.web_auth import BrowserAuthStore, BrowserOIDCClient


def make_store(tmp_path) -> BrowserAuthStore:
    db = TenantDatabase(tmp_path / "tenants.sqlite3", EncryptionBox(Fernet.generate_key()))
    return BrowserAuthStore(db)


def oidc(monkeypatch) -> BrowserOIDCClient:
    monkeypatch.setenv("YCA_WEB_OIDC_ISSUER_URL", "https://auth.example.com/realms/yca")
    monkeypatch.setenv("YCA_WEB_OIDC_CLIENT_ID", "creator-web")
    monkeypatch.setenv("YCA_WEB_OIDC_CLIENT_SECRET", "server-secret")
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    monkeypatch.delenv("YCA_WEB_OIDC_REDIRECT_URI", raising=False)
    monkeypatch.delenv("YCA_WEB_OIDC_BACKCHANNEL_BASE_URL", raising=False)
    return BrowserOIDCClient()


def test_pending_auth_is_single_use_and_sanitizes_next_path(tmp_path):
    store = make_store(tmp_path)
    pending = store.issue(next_path="https://evil.example/steal", mode="login")
    assert pending.next_path == "/dashboard"
    consumed = store.consume(pending.state)
    assert consumed.verifier == pending.verifier
    with pytest.raises(PermissionError):
        store.consume(pending.state)


def test_login_url_uses_authorization_code_pkce(tmp_path, monkeypatch):
    client = oidc(monkeypatch)
    pending = make_store(tmp_path).issue(mode="login")
    parsed = urlparse(client.authorization_url(pending))
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/protocol/openid-connect/auth")
    assert query["client_id"] == ["creator-web"]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["https://creator.example.com/auth/callback"]
    assert "prompt" not in query
    assert "client_secret" not in query


def test_registration_url_uses_standard_prompt_create(tmp_path, monkeypatch):
    client = oidc(monkeypatch)
    pending = make_store(tmp_path).issue(mode="register")
    parsed = urlparse(client.authorization_url(pending))
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/protocol/openid-connect/auth")
    assert query["prompt"] == ["create"]


def test_recovery_url_uses_supported_forgot_credentials_flow(tmp_path, monkeypatch):
    client = oidc(monkeypatch)
    pending = make_store(tmp_path).issue(mode="recover")
    parsed = urlparse(client.authorization_url(pending))
    assert parsed.path.endswith("/protocol/openid-connect/forgot-credentials")


def test_backchannel_override_keeps_browser_urls_public(monkeypatch):
    monkeypatch.setenv("YCA_WEB_OIDC_ISSUER_URL", "https://auth.example.com/realms/yca")
    monkeypatch.setenv("YCA_WEB_OIDC_BACKCHANNEL_BASE_URL", "http://keycloak:8080/realms/yca")
    monkeypatch.setenv("YCA_WEB_OIDC_CLIENT_ID", "creator-web")
    monkeypatch.setenv("YCA_WEB_OIDC_CLIENT_SECRET", "server-secret")
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    client = BrowserOIDCClient()
    assert client.authorization_endpoint == "https://auth.example.com/realms/yca/protocol/openid-connect/auth"
    assert client.logout_endpoint == "https://auth.example.com/realms/yca/protocol/openid-connect/logout"
    assert client.token_endpoint == "http://keycloak:8080/realms/yca/protocol/openid-connect/token"
    assert client.userinfo_endpoint == "http://keycloak:8080/realms/yca/protocol/openid-connect/userinfo"


def test_backchannel_defaults_to_public_issuer(monkeypatch):
    client = oidc(monkeypatch)
    assert client.token_endpoint == "https://auth.example.com/realms/yca/protocol/openid-connect/token"
    assert client.userinfo_endpoint == "https://auth.example.com/realms/yca/protocol/openid-connect/userinfo"


def test_tenant_identity_is_stable_for_same_subject(monkeypatch):
    client = oidc(monkeypatch)
    first = client.tenant_id("user-123")
    second = client.tenant_id("user-123")
    assert first == second
    assert first.startswith("u_")


def test_token_exchange_reports_invalid_client_without_leaking_credentials(monkeypatch):
    client = oidc(monkeypatch)
    body = io.BytesIO(b'{"error":"invalid_client","error_description":"Invalid client credentials"}')
    error = urllib.error.HTTPError(client.token_endpoint, 401, "Unauthorized", {}, body)
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(PermissionError) as exc:
            client.exchange_code(code="one-time-code", verifier="v" * 48)
    text = str(exc.value)
    assert "cliente OIDC" in text
    assert "server-secret" not in text
    assert "one-time-code" not in text


def test_token_exchange_reports_invalid_grant_as_restartable_login(monkeypatch):
    client = oidc(monkeypatch)
    body = io.BytesIO(b'{"error":"invalid_grant","error_description":"Code not valid"}')
    error = urllib.error.HTTPError(client.token_endpoint, 400, "Bad Request", {}, body)
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(PermissionError) as exc:
            client.exchange_code(code="expired-code", verifier="v" * 48)
    assert "Inicie o login novamente" in str(exc.value)


def test_provider_error_parser_truncates_untrusted_description(monkeypatch):
    client = oidc(monkeypatch)
    error, description = client._safe_provider_error(
        b'{"error":"invalid_grant","error_description":"' + b"x" * 1000 + b'"}'
    )
    assert error == "invalid_grant"
    assert len(description) <= 240
