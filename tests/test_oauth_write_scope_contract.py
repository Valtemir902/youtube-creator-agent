from __future__ import annotations

from creator_service.oauth_compat import (
    normalize_dynamic_client_registration,
    oauth_authorization_server_metadata,
    register_dynamic_client,
)


def _configure(monkeypatch):
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.com")
    monkeypatch.setenv("YCA_WEB_OIDC_ISSUER_URL", "https://auth.example.com/realms/yca")
    monkeypatch.setenv(
        "YCA_CHATGPT_OAUTH_CLIENT_ID",
        "82da41e4-4d89-4ccf-b134-c6a8b01f8453",
    )


def _read_only_dcr_request() -> dict:
    return {
        "client_name": "ChatGPT YouTube Creator Agent",
        "redirect_uris": ["https://chatgpt.com/connector_platform_oauth_redirect"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "openid email offline_access yca:read",
    }


def test_oauth_metadata_advertises_read_and_write(monkeypatch):
    _configure(monkeypatch)
    metadata = oauth_authorization_server_metadata()
    scopes = set(metadata["scopes_supported"])
    assert "yca:read" in scopes
    assert "yca:write" in scopes


def test_dcr_promotes_management_connection_to_read_and_write(monkeypatch):
    _configure(monkeypatch)
    normalized = normalize_dynamic_client_registration(_read_only_dcr_request())
    scopes = set(normalized["scope"].split())
    assert "yca:read" in scopes
    assert "yca:write" in scopes


def test_dcr_response_returns_write_scope_even_if_client_requested_read_only(monkeypatch):
    _configure(monkeypatch)
    result = register_dynamic_client(_read_only_dcr_request())
    assert result.status_code == 201
    scopes = set(result.payload["scope"].split())
    assert {"yca:read", "yca:write"} <= scopes
    assert result.payload["client_id"] == "82da41e4-4d89-4ccf-b134-c6a8b01f8453"
