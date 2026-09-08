from __future__ import annotations

import base64
from pathlib import Path

import pytest

from creator_service.handoff import (
    HandoffError,
    _b64url_decode,
    build_handoff_url,
    open_handoff,
    seal_handoff,
)
from creator_service.handoff_store import HandoffExecutionStore


SECRET = "0123456789abcdef0123456789abcdef"


def _proposed():
    return {
        "video_id": "video-1",
        "title": "Título novo e específico",
        "description": "Descrição revisada sem inventar conteúdo.",
        "tags": ["dark country", "western gothic"],
        "categoryId": "10",
        "defaultLanguage": None,
    }


def test_handoff_round_trip_is_encrypted_and_target_bound():
    ticket, created = seal_handoff(
        tenant_id="tenant-1",
        channel_id="channel-1",
        video_id="video-1",
        baseline_digest="a" * 64,
        proposed=_proposed(),
        changed_fields=["title", "description", "tags"],
        now=1000,
        secret=SECRET,
    )
    assert "Título novo" not in ticket
    assert "video-1" not in ticket
    decoded = open_handoff(ticket, now=1001, secret=SECRET)
    assert decoded == created
    assert decoded.tenant_id == "tenant-1"
    assert decoded.channel_id == "channel-1"
    assert decoded.video_id == "video-1"
    assert decoded.proposed["title"] == _proposed()["title"]


def test_handoff_tampering_is_rejected():
    ticket, _ = seal_handoff(
        tenant_id="tenant-1",
        channel_id="channel-1",
        video_id="video-1",
        baseline_digest="b" * 64,
        proposed=_proposed(),
        changed_fields=["title"],
        now=1000,
        secret=SECRET,
    )
    # Mutate a full Base64 sextet in the ciphertext rather than the final
    # padding-adjacent character, so this test deterministically exercises AEAD.
    index = max(4, len(ticket) // 2)
    replacement = "A" if ticket[index] != "A" else "B"
    tampered = ticket[:index] + replacement + ticket[index + 1 :]
    with pytest.raises(HandoffError, match="criptográfica"):
        open_handoff(tampered, now=1001, secret=SECRET)


def test_handoff_rejects_noncanonical_base64_aliases():
    # RFC 4648 decoders can ignore unused low bits in the last sextet. Thus AA
    # and AB decode to the same byte under permissive decoding. Handoff tickets
    # must reject the alias so one ciphertext has exactly one replay-ledger key.
    assert base64.urlsafe_b64decode("AA==") == base64.urlsafe_b64decode("AB==") == b"\x00"
    assert _b64url_decode("AA") == b"\x00"
    with pytest.raises(HandoffError, match="Ticket de handoff inválido"):
        _b64url_decode("AB")


def test_handoff_expiry_is_fail_closed():
    ticket, _ = seal_handoff(
        tenant_id="tenant-1",
        channel_id="channel-1",
        video_id="video-1",
        baseline_digest="c" * 64,
        proposed=_proposed(),
        changed_fields=["title"],
        ttl_seconds=60,
        now=1000,
        secret=SECRET,
    )
    with pytest.raises(HandoffError, match="expirou"):
        open_handoff(ticket, now=1061, secret=SECRET)


def test_handoff_rejects_internal_video_substitution():
    proposed = _proposed()
    proposed["video_id"] = "video-OTHER"
    with pytest.raises(HandoffError, match="alvo interno"):
        seal_handoff(
            tenant_id="tenant-1",
            channel_id="channel-1",
            video_id="video-1",
            baseline_digest="d" * 64,
            proposed=proposed,
            changed_fields=["title"],
            now=1000,
            secret=SECRET,
        )


def test_handoff_url_keeps_ticket_out_of_query_string():
    url = build_handoff_url("v1.opaque-ticket", "https://creator.example.com")
    assert url == "https://creator.example.com/handoff/v1#ticket=v1.opaque-ticket"
    assert "?" not in url


def test_handoff_result_ledger_is_idempotent_and_stores_only_hash(tmp_path):
    db = tmp_path / "tenants.sqlite3"
    store = HandoffExecutionStore(db)
    ticket = "v1.super-secret-package"

    state, existing = store.begin(
        ticket,
        tenant_id="tenant-1",
        video_id="video-1",
        expires_at=2000,
        now=1000,
    )
    assert state == "new"
    assert existing is None

    store.mark_success(ticket, {"ok": True, "video_id": "video-1"}, now=1001)
    state, existing = store.begin(
        ticket,
        tenant_id="tenant-1",
        video_id="video-1",
        expires_at=2000,
        now=1002,
    )
    assert state == "success"
    assert existing is not None
    assert existing.result == {"ok": True, "video_id": "video-1"}

    raw = db.read_bytes()
    assert ticket.encode() not in raw
    assert b"super-secret-package" not in raw


def test_handoff_widget_and_execution_page_contracts():
    root = Path(__file__).resolve().parents[1] / "src" / "creator_service" / "web"
    widget = (root / "handoff_widget.html").read_text(encoding="utf-8")
    page = (root / "handoff.html").read_text(encoding="utf-8")

    assert "Enviar e aplicar mudanças" in widget
    assert ">Cancelar<" in widget
    assert "openExternal" in widget
    assert "requestClose" in widget
    assert "location.hash" in page
    assert "history.replaceState" in page
    assert "sessionStorage" in page
    assert "method:'POST'" in page
    assert "/api/handoff/v1/apply" in page
    assert "next:'/handoff/v1'" in page
