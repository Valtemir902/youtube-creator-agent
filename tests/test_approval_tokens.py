from __future__ import annotations

import pytest

from creator_service.security import ApprovalTokenSigner


SECRET = "0123456789abcdef0123456789abcdef"


def test_approval_token_accepts_exact_payload():
    signer = ApprovalTokenSigner(SECRET, ttl_seconds=300)
    payload = {"video_id": "abc123", "title": "Novo título", "tags": ["roça", "sítio"]}
    token = signer.issue("update_video_metadata", "abc123", payload, now=1000)

    parsed = signer.verify(
        token,
        action="update_video_metadata",
        subject="abc123",
        payload=payload,
        now=1100,
    )
    assert parsed.subject == "abc123"


def test_approval_token_rejects_changed_payload():
    signer = ApprovalTokenSigner(SECRET, ttl_seconds=300)
    payload = {"video_id": "abc123", "title": "Título aprovado"}
    token = signer.issue("update_video_metadata", "abc123", payload, now=1000)

    with pytest.raises(ValueError, match="changed after approval"):
        signer.verify(
            token,
            action="update_video_metadata",
            subject="abc123",
            payload={"video_id": "abc123", "title": "Título diferente"},
            now=1100,
        )


def test_approval_token_rejects_wrong_target():
    signer = ApprovalTokenSigner(SECRET, ttl_seconds=300)
    payload = {"video_id": "abc123", "title": "Título"}
    token = signer.issue("update_video_metadata", "abc123", payload, now=1000)

    with pytest.raises(ValueError, match="does not authorize"):
        signer.verify(
            token,
            action="update_video_metadata",
            subject="outro-video",
            payload=payload,
            now=1100,
        )


def test_approval_token_expires():
    signer = ApprovalTokenSigner(SECRET, ttl_seconds=60)
    payload = {"video_id": "abc123"}
    token = signer.issue("update_video_metadata", "abc123", payload, now=1000)

    with pytest.raises(ValueError, match="expired"):
        signer.verify(
            token,
            action="update_video_metadata",
            subject="abc123",
            payload=payload,
            now=1061,
        )
