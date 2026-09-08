from __future__ import annotations

import pytest

from creator_service.safe_service import SafeCreatorService
from intelligence.creator_memory import CreatorMemoryStore


SECRET = "0123456789abcdef0123456789abcdef"


class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _Videos:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, id: str):
        assert part == "snippet"
        assert id == self.owner.video_id
        return _Request(lambda: {"items": [{"snippet": dict(self.owner.snippet)}]})

    def update(self, *, part: str, body: dict):
        assert part == "snippet"
        assert body["id"] == self.owner.video_id

        def _apply():
            self.owner.update_calls += 1
            self.owner.snippet = dict(body["snippet"])
            return {"id": body["id"], "snippet": dict(self.owner.snippet)}

        return _Request(_apply)


class _FakeYouTube:
    def __init__(self, video_id: str = "abc123"):
        self.video_id = video_id
        self.snippet = {
            "title": "Titulo atual",
            "description": "Descricao atual",
            "tags": ["roca", "maquina"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        }
        self.update_calls = 0
        self._videos = _Videos(self)

    def videos(self):
        return self._videos


class _FakeContext:
    tenant_id = "test-tenant"

    def validate_youtube(self):
        return None


def _service(tmp_path, monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.delenv("YCA_RECENT_EDIT_PROTECTION_HOURS", raising=False)

    service = SafeCreatorService.__new__(SafeCreatorService)
    service.context = _FakeContext()
    service.memory = CreatorMemoryStore(tmp_path / "creator_memory.sqlite3")

    youtube = _FakeYouTube()
    monkeypatch.setattr(service, "_youtube", lambda: youtube)
    return service, youtube


def test_stale_baseline_is_rejected_before_youtube_write(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)

    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Titulo aprovado")
    youtube.snippet["title"] = "Alterado fora do agente"

    with pytest.raises(RuntimeError, match="mudou desde a prévia"):
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert youtube.update_calls == 0


def test_successful_apply_returns_signed_rollback_and_keeps_recent_edit_protection(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)

    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Titulo aprovado")
    result = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["ok"] is True
    assert result["changed_fields"] == ["title"]
    assert youtube.update_calls == 1
    assert result["rollback_preview"]["restore"]["title"] == "Titulo atual"
    assert result["rollback_preview"]["expires_in_seconds"] == 900
    assert result["rollback_preview"]["requires_explicit_user_confirmation"] is True

    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.protection_hours == 168

    with pytest.raises(RuntimeError, match="Proteção de memória ativa"):
        service.preview_video_metadata_update(video_id=youtube.video_id, title="Outra edicao")


def test_signed_rollback_restores_previous_metadata_despite_recent_edit_guard(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)

    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Titulo temporario")
    applied = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    rollback = applied["rollback_preview"]

    result = service.apply_video_metadata_rollback(
        rollback_payload=rollback["rollback_payload"],
        rollback_token=rollback["rollback_token"],
    )

    assert result["ok"] is True
    assert result["rolled_back"] is True
    assert youtube.snippet["title"] == "Titulo atual"
    assert youtube.update_calls == 2
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.last_action_type == "metadata_rollback"


def test_rollback_is_blocked_if_video_changes_after_apply(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)

    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Titulo temporario")
    applied = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    rollback = applied["rollback_preview"]
    youtube.snippet["title"] = "Mudanca externa posterior"

    with pytest.raises(RuntimeError, match="rollback automático foi bloqueado"):
        service.apply_video_metadata_rollback(
            rollback_payload=rollback["rollback_payload"],
            rollback_token=rollback["rollback_token"],
        )

    assert youtube.update_calls == 1


def test_rollback_rejects_tampered_payload(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)

    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Titulo temporario")
    applied = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    rollback = applied["rollback_preview"]
    tampered = {
        "baseline_digest": rollback["rollback_payload"]["baseline_digest"],
        "proposed": dict(rollback["rollback_payload"]["proposed"]),
    }
    tampered["proposed"]["title"] = "Titulo adulterado"

    with pytest.raises(ValueError, match="changed after approval"):
        service.apply_video_metadata_rollback(
            rollback_payload=tampered,
            rollback_token=rollback["rollback_token"],
        )

    assert youtube.update_calls == 1
