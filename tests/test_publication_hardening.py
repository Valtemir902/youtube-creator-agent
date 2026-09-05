from __future__ import annotations

import sqlite3

from creator_service.publication import PublicationMetadata, publication_readiness
from creator_service.publication_store import PublicationStore


def test_publication_readiness_requires_https_and_secrets(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", "x" * 32)
    monkeypatch.setenv("YCA_DATA_ENCRYPTION_KEY", "configured")
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.com")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.com/introspect")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://app.example.com/oauth/google/callback")

    metadata = PublicationMetadata(
        name="YouTube Creator Agent",
        short_description="test",
        public_url="https://app.example.com",
        mcp_url="https://mcp.example.com/mcp",
        onboarding_url="https://app.example.com",
        privacy_url="https://app.example.com/privacy",
        terms_url="https://app.example.com/terms",
        support_url="https://app.example.com/support",
    )
    report = publication_readiness(metadata)
    assert report.ready is True
    assert report.missing == ()


def test_publication_readiness_rejects_insecure_public_url(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", "x" * 32)
    monkeypatch.setenv("YCA_DATA_ENCRYPTION_KEY", "configured")
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.com")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.com/introspect")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://app.example.com/oauth/google/callback")

    metadata = PublicationMetadata(
        name="YouTube Creator Agent",
        short_description="test",
        public_url="http://app.example.com",
        mcp_url="https://mcp.example.com/mcp",
        onboarding_url="https://app.example.com",
        privacy_url="https://app.example.com/privacy",
        terms_url="https://app.example.com/terms",
        support_url="https://app.example.com/support",
    )
    report = publication_readiness(metadata)
    assert report.ready is False
    assert "app_public_url_https" in report.missing


def test_rate_limit_is_shared_through_sqlite(tmp_path):
    path = tmp_path / "ops.sqlite3"
    first = PublicationStore(path)
    second = PublicationStore(path)

    assert first.consume_rate_limit("tenant-a", limit=2, window_seconds=60, now=120).allowed
    assert second.consume_rate_limit("tenant-a", limit=2, window_seconds=60, now=121).allowed
    denied = first.consume_rate_limit("tenant-a", limit=2, window_seconds=60, now=122)
    assert denied.allowed is False
    assert denied.remaining == 0


def test_audit_store_redacts_secret_like_fields(tmp_path):
    path = tmp_path / "ops.sqlite3"
    store = PublicationStore(path)
    store.record_event(
        event_type="test",
        outcome="success",
        tenant_id="tenant-a",
        metadata={
            "video_id": "abc123",
            "api_key": "should-never-be-stored",
            "nested": {"access_token": "also-secret"},
        },
    )

    with sqlite3.connect(path) as conn:
        payload = conn.execute("SELECT metadata_json FROM audit_events").fetchone()[0]
    assert "abc123" in payload
    assert "should-never-be-stored" not in payload
    assert "also-secret" not in payload
    assert "[redacted]" in payload
