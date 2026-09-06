from __future__ import annotations

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
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    monkeypatch.delenv("YCA_WEB_OIDC_REDIRECT_URI", raising=False)
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


def test_tenant_identity_is_stable_for_same_subject(monkeypatch):
    client = oidc(monkeypatch)
    first = client.tenant_id("user-123")
    second = client.tenant_id("user-123")
    assert first == second
    assert first.startswith("u_")
