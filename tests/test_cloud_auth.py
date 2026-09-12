from __future__ import annotations

import asyncio
from src.creator_service.cloud_auth import tenant_id_from_subject
from src.creator_service.cloud_auth import IntrospectionTokenVerifier


def test_tenant_identity_is_deterministic_and_issuer_scoped():
    a1 = tenant_id_from_subject("https://auth.example.com", "user-123")
    a2 = tenant_id_from_subject("https://auth.example.com", "user-123")
    b = tenant_id_from_subject("https://outro.example.com", "user-123")

    assert a1 == a2
    assert a1 != b
    assert a1.startswith("u_")
    assert len(a1) == 34


def test_token_verifier_accepts_legacy_and_managed_dcr_clients(monkeypatch):
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "resource-server")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "secret")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example/mcp")
    monkeypatch.setenv("YCA_WEB_OIDC_ISSUER_URL", "https://auth.example/realms/yca")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_CLIENT_ID", "82da41e4-4d89-4ccf-b134-c6a8b01f8453")
    verifier = IntrospectionTokenVerifier()
    monkeypatch.setattr(verifier, "_introspect", lambda _: {"active": True, "sub": "user", "client_id": "yca-chatgpt-dcr-123", "scope": "openid yca:read yca:write", "exp": 4102444800})
    assert asyncio.run(verifier.verify_token("dynamic")) is not None
    monkeypatch.setattr(verifier, "_introspect", lambda _: {"active": True, "sub": "user", "client_id": "82da41e4-4d89-4ccf-b134-c6a8b01f8453", "scope": "openid yca:read", "exp": 4102444800})
    assert asyncio.run(verifier.verify_token("legacy")) is not None
    monkeypatch.setattr(verifier, "_introspect", lambda _: {"active": True, "sub": "user", "client_id": "unmanaged-client", "scope": "openid yca:read", "exp": 4102444800})
    assert asyncio.run(verifier.verify_token("unmanaged")) is None
