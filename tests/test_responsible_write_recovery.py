from __future__ import annotations

import pytest

from creator_service.responsible_service import ResponsibleCreatorService
from intelligence.creator_memory import CreatorMemoryStore


SECRET = "0123456789abcdef0123456789abcdef"


class _Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Channels:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, mine: bool):
        assert part == "id"
        assert mine is True
        return _Request(lambda: {"items": [{"id": self.owner.channel_id}]})


class _Videos:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, id: str):
        assert id == self.owner.video_id
        snippet = dict(self.owner.snippet)
        snippet["channelId"] = self.owner.channel_id
        return _Request(lambda: {"items": [{"snippet": snippet}]})

    def update(self, *, part: str, body: dict):
        assert part == "snippet"
        assert body["id"] == self.owner.video_id

        def apply():
            self.owner.update_calls += 1
            incoming = dict(body["snippet"])
            mode = self.owner.mode
            if mode == "accepted_then_transport_failed":
                self.owner.snippet = incoming
                raise RuntimeError("connection reset after provider accepted request")
            if mode == "failed_before_provider_change":
                raise RuntimeError("connection failed before provider change")
            if mode == "divergent_after_failure":
                self.owner.snippet = dict(incoming)
                self.owner.snippet["title"] = "Concurrent external title"
                raise RuntimeError("connection reset with divergent final state")
            self.owner.snippet = incoming
            return {"id": body["id"], "snippet": dict(incoming)}

        return _Request(apply)


class _FakeYouTube:
    def __init__(self, mode: str):
        self.video_id = "video-1"
        self.channel_id = "channel-1"
        self.mode = mode
        self.update_calls = 0
        self.snippet = {
            "title": "Original",
            "description": "Description",
            "tags": ["old"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        }
        self._channels = _Channels(self)
        self._videos = _Videos(self)

    def channels(self):
        return self._channels

    def videos(self):
        return self._videos


class _Context:
    tenant_id = "tenant-test"

    def validate_youtube(self):
        return None


def _service(tmp_path, monkeypatch, mode: str):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setattr("creator_service.verified_advanced_service.time.sleep", lambda _: None)
    service = ResponsibleCreatorService.__new__(ResponsibleCreatorService)
    service.context = _Context()
    service.memory = CreatorMemoryStore(tmp_path / f"memory-{mode}.sqlite3")
    youtube = _FakeYouTube(mode)
    monkeypatch.setattr(service, "_youtube", lambda: youtube)
    return service, youtube


def test_lost_response_is_recovered_by_authoritative_readback(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "accepted_then_transport_failed")
    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Approved title")
    result = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    assert result["persisted_verified"] is True
    assert result["recovered_from_ambiguous_response"] is True
    assert youtube.snippet["title"] == "Approved title"
    assert youtube.update_calls == 1


def test_transport_failure_without_write_never_claims_success(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "failed_before_provider_change")
    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Approved title")
    with pytest.raises(RuntimeError, match="connection failed before provider change"):
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    assert youtube.snippet["title"] == "Original"
    assert youtube.update_calls == 1


def test_divergent_ambiguous_state_is_not_overwritten(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "divergent_after_failure")
    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Approved title")
    with pytest.raises(RuntimeError, match="possível edição externa"):
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    assert youtube.snippet["title"] == "Concurrent external title"
    assert youtube.update_calls == 1
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.last_action_type == "metadata_write_ambiguous_state"
