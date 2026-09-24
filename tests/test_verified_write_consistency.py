from __future__ import annotations

from types import SimpleNamespace

import pytest

from creator_service.mcp_errors import CreatorToolError
from creator_service.verified_advanced_service import VerifiedAdvancedSafeCreatorService


def _snippet(*, title="Title", description="Description", tags=None, category_id="22"):
    return {
        "title": title,
        "description": description,
        "tags": list(tags or []),
        "categoryId": category_id,
        "defaultLanguage": None,
    }


def test_metadata_normalizer_preserves_more_than_twelve_tags():
    tags = [f"tag {index}" for index in range(25)]
    normalized = VerifiedAdvancedSafeCreatorService._normalize_metadata_payload(
        video_id="video-1",
        title="Title",
        description="Description",
        tags=tags,
        current=_snippet(tags=tags),
    )
    assert normalized["tags"] == tags
    assert len(normalized["tags"]) == 25


def test_metadata_normalizer_rejects_aggregate_tag_budget():
    tags = ["x" * 260, "y" * 260]
    with pytest.raises(ValueError, match="500 caracteres"):
        VerifiedAdvancedSafeCreatorService._normalize_metadata_payload(
            video_id="video-1",
            title="Title",
            description="Description",
            tags=tags,
            current=_snippet(),
        )


def test_semantic_comparison_tolerates_only_harmless_text_normalization():
    expected = _snippet(
        title="Meu   vídeo",
        description="linha 1\r\nlinha 2\n\n",
        tags=["tag um", "tag dois"],
    )
    actual = _snippet(
        title="Meu vídeo",
        description="linha 1\nlinha 2",
        tags=["tag um", "tag dois"],
    )
    assert VerifiedAdvancedSafeCreatorService._mismatches(actual, expected) == []
    assert set(VerifiedAdvancedSafeCreatorService._exact_differences(actual, expected)) == {"title", "description"}


def test_wait_for_snippet_retries_until_eventual_consistency(monkeypatch):
    service = object.__new__(VerifiedAdvancedSafeCreatorService)
    expected = _snippet(tags=["a", "b"])
    observations = [
        _snippet(title="old", tags=["a", "b"]),
        _snippet(tags=["a", "b"]),
    ]
    sleeps = []

    monkeypatch.setattr(service, "_current_video_snippet", lambda _video_id: observations.pop(0))
    monkeypatch.setattr("creator_service.verified_advanced_service.time.sleep", lambda seconds: sleeps.append(seconds))

    observed, mismatches, exact, attempts = service._wait_for_snippet(
        "video-1",
        expected,
        (0.0, 1.0, 2.0),
    )
    assert observed == expected
    assert mismatches == []
    assert exact == []
    assert attempts == 2
    assert sleeps == [1.0]


class _Execute:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class _Videos:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def update(self, *, part, body):
        self.calls.append((part, body))
        return _Execute(lambda: self.callback(body))


class _YouTube:
    def __init__(self, callback):
        self._videos = _Videos(callback)

    def videos(self):
        return self._videos


class _Memory:
    def __init__(self):
        self.actions = []
        self.fail_record = False

    def record_video_action(self, **kwargs):
        if self.fail_record:
            raise OSError("simulated memory failure")
        self.actions.append(kwargs)
        return len(self.actions)


def _canonical_remote(remote):
    value = dict(remote)
    value.setdefault("defaultLanguage", None)
    return value


def _service_for_apply(monkeypatch, before, expected, remote):
    service = object.__new__(VerifiedAdvancedSafeCreatorService)
    service.context = SimpleNamespace(tenant_id="tenant")
    service.memory = _Memory()

    def mutate(body):
        remote.clear()
        remote.update(body["snippet"])
        return {"snippet": dict(remote)}

    youtube = _YouTube(mutate)
    monkeypatch.setattr(service, "_youtube", lambda: youtube)
    monkeypatch.setattr(service, "_current_video_snippet", lambda _video_id: _canonical_remote(remote))
    monkeypatch.setattr(
        service,
        "_prepare_verified_update",
        lambda **_kwargs: ("video-1", dict(before), dict(expected), ["title", "description", "tags", "categoryId"]),
    )
    monkeypatch.setattr(service, "video_memory_state", lambda _video_id: {"protected": True})
    monkeypatch.setattr(service, "_build_rollback_package", lambda **_kwargs: {"rollback_payload": {}, "rollback_token": "token"})
    monkeypatch.setattr("creator_service.verified_advanced_service.time.sleep", lambda _seconds: None)
    return service, youtube


def test_success_is_recorded_only_after_verified_readback(monkeypatch):
    before = _snippet(tags=["old"])
    expected = _snippet(title="New", description="New description", tags=["new"], category_id="10")
    remote = dict(before)
    service, youtube = _service_for_apply(monkeypatch, before, expected, remote)

    result = service.apply_video_metadata_update(approval_payload={}, approval_token="token")

    assert result["ok"] is True
    assert result["persisted_verified"] is True
    assert _canonical_remote(remote) == expected
    assert len(youtube._videos.calls) == 1
    assert [action["action_type"] for action in service.memory.actions] == ["metadata_update"]


def test_partial_readback_is_compensated_without_recent_edit_record(monkeypatch):
    before = _snippet(tags=["old"])
    expected = _snippet(title="New", description="New description", tags=["new"], category_id="10")
    remote = dict(before)
    service, youtube = _service_for_apply(monkeypatch, before, expected, remote)

    def partial_mutate(body):
        if len(youtube._videos.calls) == 1:
            remote["tags"] = list(body["snippet"]["tags"])
        else:
            remote.clear()
            remote.update(body["snippet"])
        return {"snippet": dict(remote)}

    youtube._videos.callback = partial_mutate
    service._WRITE_VERIFY_DELAYS = (0.0,)
    service._RESTORE_VERIFY_DELAYS = (0.0,)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(approval_payload={}, approval_token="token")

    assert caught.value.code == "partial_write_detected"
    assert _canonical_remote(remote) == before
    assert len(youtube._videos.calls) == 2
    assert service.memory.actions == []


def test_execute_exception_after_remote_mutation_is_compensated(monkeypatch):
    before = _snippet(tags=["old"])
    expected = _snippet(title="New", description="New description", tags=["new"], category_id="10")
    remote = dict(before)
    service, youtube = _service_for_apply(monkeypatch, before, expected, remote)

    def ambiguous_mutate(body):
        if len(youtube._videos.calls) == 1:
            remote.clear()
            remote.update(body["snippet"])
            raise ConnectionError("transport dropped after mutation")
        remote.clear()
        remote.update(body["snippet"])
        return {"snippet": dict(remote)}

    youtube._videos.callback = ambiguous_mutate
    service._RESTORE_VERIFY_DELAYS = (0.0,)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(approval_payload={}, approval_token="token")

    assert caught.value.code == "partial_write_detected"
    assert _canonical_remote(remote) == before
    assert len(youtube._videos.calls) == 2
    assert service.memory.actions == []


def test_rollback_package_failure_after_verified_write_is_compensated(monkeypatch):
    before = _snippet(tags=["old"])
    expected = _snippet(title="New", description="New description", tags=["new"], category_id="10")
    remote = dict(before)
    service, youtube = _service_for_apply(monkeypatch, before, expected, remote)
    service._RESTORE_VERIFY_DELAYS = (0.0,)
    monkeypatch.setattr(service, "_build_rollback_package", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("signer failed")))

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(approval_payload={}, approval_token="token")

    assert caught.value.code == "partial_write_detected"
    assert _canonical_remote(remote) == before
    assert len(youtube._videos.calls) == 2
    assert service.memory.actions == []


def test_memory_failure_after_verified_write_is_compensated(monkeypatch):
    before = _snippet(tags=["old"])
    expected = _snippet(title="New", description="New description", tags=["new"], category_id="10")
    remote = dict(before)
    service, youtube = _service_for_apply(monkeypatch, before, expected, remote)
    service._RESTORE_VERIFY_DELAYS = (0.0,)
    service.memory.fail_record = True

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(approval_payload={}, approval_token="token")

    assert caught.value.code == "partial_write_detected"
    assert _canonical_remote(remote) == before
    assert len(youtube._videos.calls) == 2
    assert service.memory.actions == []


def test_semantic_tag_comparison_tolerates_order_and_exact_provider_deduplication():
    expected = _snippet(tags=["Zulu tag", "alpha tag", "alpha tag"])
    actual = _snippet(tags=["alpha tag", "Zulu tag"])
    assert VerifiedAdvancedSafeCreatorService._mismatches(actual, expected) == []


def test_semantic_tag_comparison_rejects_real_tag_content_change():
    expected = _snippet(tags=["alpha tag", "Zulu tag"])
    actual = _snippet(tags=["alpha tag", "Different tag"])
    assert VerifiedAdvancedSafeCreatorService._mismatches(actual, expected) == ["tags"]
