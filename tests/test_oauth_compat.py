from __future__ import annotations

import pytest

from creator_service.oauth_compat import (
    OAuthCompatError,
    legacy_chatgpt_client_id,
    normalize_dynamic_client_registration,
    oauth_authorization_server_metadata,
    register_dynamic_client,
)


class RecordingStore:
    def __init__(self):
        self.clients: dict[str, dict] = {}

    def resolve_or_create(self, registration: dict) -> str:
        # Mirrors the production invariant: a registration is an immutable
        # client, so a second app cannot replace the first app's callback list.
        key = repr(sorted(registration.items()))
        self.clients.setdefault(key, dict(registration))
        return f"yca-chatgpt-dcr-{abs(hash(key)):032x}"[-48:]


def _payload(uri: str = "https://chatgpt.com/connector_platform_oauth_redirect", **extra):
    payload = {
        "client_name": "ChatGPT YouTube Creator Agent V2",
        "redirect_uris": [uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": "openid email offline_access yca:read yca:write",
        "token_endpoint_auth_method": "none",
    }
    payload.update(extra)
    return payload


def test_valid_chatgpt_registration_keeps_public_pkce_scopes(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    registration = normalize_dynamic_client_registration(_payload())
    assert registration["redirect_uris"] == ["https://chatgpt.com/connector_platform_oauth_redirect"]
    assert registration["token_endpoint_auth_method"] == "none"
    assert registration["grant_types"] == ["authorization_code", "refresh_token"]
    assert registration["response_types"] == ["code"]
    assert registration["scope"].split() == ["openid", "email", "offline_access", "yca:read", "yca:write"]


@pytest.mark.parametrize("uri", [
    "http://chatgpt.com/callback",
    "https://localhost/callback",
    "https://127.0.0.1/callback",
    "https://[::1]/callback",
    "https://chatgpt.com.evil.com/callback",
    "https://evil-chatgpt.com/callback",
    "https://*.chatgpt.com/callback",
    "javascript:alert(1)",
    "data:text/plain,nope",
    "https://user:pass@chatgpt.com/callback",
    "https://chatgpt.com/callback#fragment",
])
def test_dcr_rejects_unsafe_redirects(monkeypatch, uri):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    with pytest.raises(OAuthCompatError, match="redirect") as exc:
        normalize_dynamic_client_registration(_payload(uri))
    assert exc.value.error == "invalid_redirect_uri"


def test_dcr_rejects_missing_redirects(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    payload = _payload()
    payload.pop("redirect_uris")
    with pytest.raises(OAuthCompatError) as exc:
        normalize_dynamic_client_registration(payload)
    assert exc.value.error == "invalid_redirect_uri"


def test_dcr_deduplicates_canonical_redirects(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    payload = _payload("https://CHATGPT.COM:443/connector_platform_oauth_redirect")
    payload["redirect_uris"].append("https://chatgpt.com/connector_platform_oauth_redirect")
    assert normalize_dynamic_client_registration(payload)["redirect_uris"] == ["https://chatgpt.com/connector_platform_oauth_redirect"]


def test_dcr_rejects_scope_elevation(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    with pytest.raises(OAuthCompatError) as exc:
        normalize_dynamic_client_registration(_payload(scope="openid yca:read realm-admin"))
    assert exc.value.error == "invalid_scope"


def test_two_apps_receive_isolated_clients_and_callbacks(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    store = RecordingStore()
    a = register_dynamic_client(_payload(client_name="ChatGPT legacy"), store=store)
    b = register_dynamic_client(_payload("https://chatgpt.com/v2_callback", client_name="ChatGPT V2"), store=store)
    assert a.payload["client_id"] != b.payload["client_id"]
    assert a.payload["redirect_uris"] == ["https://chatgpt.com/connector_platform_oauth_redirect"]
    assert b.payload["redirect_uris"] == ["https://chatgpt.com/v2_callback"]
    # The exact redirect list is part of each client registration: A has no
    # authority to use B's callback and B has no authority to use A's.
    assert b.payload["redirect_uris"][0] not in a.payload["redirect_uris"]
    assert a.payload["redirect_uris"][0] not in b.payload["redirect_uris"]


def test_repeated_registration_is_idempotent(monkeypatch):
    monkeypatch.delenv("YCA_DCR_ALLOWED_REDIRECT_HOSTS", raising=False)
    store = RecordingStore()
    first = register_dynamic_client(_payload(), store=store)
    second = register_dynamic_client(_payload(), store=store)
    assert first.payload["client_id"] == second.payload["client_id"]
    assert len(store.clients) == 1


def test_legacy_client_identifier_is_preserved(monkeypatch):
    monkeypatch.delenv("YCA_CHATGPT_OAUTH_CLIENT_ID", raising=False)
    assert legacy_chatgpt_client_id() == "82da41e4-4d89-4ccf-b134-c6a8b01f8453"


def test_metadata_advertises_code_pkce_and_required_scopes(monkeypatch):
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example")
    monkeypatch.setenv("YCA_WEB_OIDC_ISSUER_URL", "https://auth.example/realms/yca")
    metadata = oauth_authorization_server_metadata()
    assert metadata["registration_endpoint"] == "https://creator.example/oauth/register"
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]
    assert {"openid", "email", "offline_access", "yca:read", "yca:write"} <= set(metadata["scopes_supported"])
