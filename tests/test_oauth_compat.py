from __future__ import annotations

import os

import pytest

from creator_service.oauth_compat import (
    OAuthCompatError,
    normalize_dynamic_client_registration,
    oauth_authorization_server_metadata,
)


def _payload(scope: str):
    return {
        "client_name": "ChatGPT exact scope probe",
        "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": scope,
        "token_endpoint_auth_method": "none",
    }


def test_dcr_strips_only_openid_and_preserves_required_scopes(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    result = normalize_dynamic_client_registration(
        _payload("openid email offline_access yca:read")
    )
    assert result["scope"] == "email offline_access yca:read"
    assert "openid" not in result["scope"].split()
    assert result["token_endpoint_auth_method"] == "none"


def test_dcr_adds_read_scope_when_client_omits_scope(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    payload = _payload("")
    result = normalize_dynamic_client_registration(payload)
    assert result["scope"] == "yca:read"


def test_dcr_rejects_unknown_scope(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    with pytest.raises(OAuthCompatError) as exc:
        normalize_dynamic_client_registration(_payload("openid admin yca:read"))
    assert exc.value.error == "invalid_scope"


def test_dcr_rejects_non_chatgpt_redirect(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    payload = _payload("yca:read")
    payload["redirect_uris"] = ["https://evil.example/callback"]
    with pytest.raises(OAuthCompatError) as exc:
        normalize_dynamic_client_registration(payload)
    assert exc.value.error == "invalid_redirect_uri"


def test_oauth_metadata_routes_registration_through_creator_and_keeps_openid(monkeypatch):
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example")
    monkeypatch.setenv("YCA_WEB_OIDC_ISSUER_URL", "https://auth.example/realms/yca")
    metadata = oauth_authorization_server_metadata()
    assert metadata["issuer"] == "https://creator.example"
    assert metadata["registration_endpoint"] == "https://creator.example/oauth/register"
    assert metadata["authorization_endpoint"] == "https://auth.example/realms/yca/protocol/openid-connect/auth"
    assert metadata["token_endpoint"] == "https://auth.example/realms/yca/protocol/openid-connect/token"
    assert "openid" in metadata["scopes_supported"]
    assert "offline_access" in metadata["scopes_supported"]
    assert "yca:read" in metadata["scopes_supported"]
    assert "S256" in metadata["code_challenge_methods_supported"]
