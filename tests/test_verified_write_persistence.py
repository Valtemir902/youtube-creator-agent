from __future__ import annotations

import pytest

from creator_service.verified_advanced_service import VerifiedAdvancedSafeCreatorService
from intelligence.creator_memory import CreatorMemoryStore


SECRET = "0123456789abcdef0123456789abcdef"


class _Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


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

        def apply():
            self.owner.update_calls += 1
            incoming = dict(body["snippet"])
            # Simulate the real production anomaly discovered during the live
            # audit: YouTube accepts the request but silently keeps old tags.
            if incoming.get("tags") == ["new-tag"]:
                incoming["tags"] = list(self.owner.snippet.get("tags", []))
            self.owner.snippet = incoming
            return {"id": body["id"], "snippet": dict(self.owner.snippet)}

        return _Request(apply)


class _FakeYouTube:
    def __init__(self):
        self.video_id = "video-1"
        self.snippet = {
            "title": "Original",
            "description": "Descricao",
            "tags": ["old-tag"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        }
        self.update_calls = 0
        self._videos = _Videos(self)

    def videos(self):
        return self._videos


class _Context:
    tenant_id = "test-tenant"

    def validate_youtube(self):
        return None


def _service(tmp_path, monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr("creator_service.verified_advanced_service.time.sleep", lambda _: None)
    service = VerifiedAdvancedSafeCreatorService.__new__(VerifiedAdvancedSafeCreatorService)
    service.context = _Context()
    service.memory = CreatorMemoryStore(tmp_path / "memory.sqlite3")
    youtube = _FakeYouTube()
    monkeypatch.setattr(service, "_youtube", lambda: youtube)
    return service, youtube


def test_success_is_reported_only_after_readback(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)
    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Novo titulo")
    result = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    assert result["persisted_verified"] is True
    assert youtube.snippet["title"] == "Novo titulo"
    assert youtube.update_calls == 1


def test_partial_write_is_restored_and_never_reported_as_success(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch)
    before = dict(youtube.snippet)
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Titulo temporario",
        tags=["new-tag"],
    )

    with pytest.raises(RuntimeError, match="revertida automaticamente"):
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert youtube.snippet == before
    assert youtube.update_calls == 2
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.last_action_type == "metadata_write_verification_rollback"
