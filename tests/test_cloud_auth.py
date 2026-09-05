from __future__ import annotations

from src.creator_service.cloud_auth import tenant_id_from_subject


def test_tenant_identity_is_deterministic_and_issuer_scoped():
    a1 = tenant_id_from_subject("https://auth.example.com", "user-123")
    a2 = tenant_id_from_subject("https://auth.example.com", "user-123")
    b = tenant_id_from_subject("https://outro.example.com", "user-123")

    assert a1 == a2
    assert a1 != b
    assert a1.startswith("u_")
    assert len(a1) == 34
