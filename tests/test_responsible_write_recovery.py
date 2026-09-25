from __future__ import annotations

import json
import logging

import pytest

from creator_service.mcp_errors import CreatorToolError
from creator_service.responsible_service import ResponsibleCreatorService
from intelligence.creator_memory import CreatorMemoryStore


SECRET = "0123456789abcdef0123456789abcdef"


class _Request:
    def __init__(self, fn):
        self.fn = fn
        self.headers: dict[str, str] = {}
        self.body = None

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

        def read():
            snippet = dict(self.owner.snippet)
            snippet["channelId"] = self.owner.channel_id
            return {
                "items": [
                    {
                        "etag": self.owner.etag,
                        "snippet": snippet,
                    }
                ]
            }

        return _Request(read)

    def update(self, *, part: str, body: dict):
        assert part == "snippet"
        assert body["id"] == self.owner.video_id
        self.owner.update_bodies.append({
            "part": part,
            "body": {
                "id": body["id"],
                "snippet": {
                    key: (list(value) if isinstance(value, list) else value)
                    for key, value in dict(body["snippet"]).items()
                },
            },
        })
        holder: dict[str, _Request] = {}

        def apply():
            request = holder["request"]
            if_match = request.headers.get("If-Match")
            if if_match:
                self.owner.if_match_headers.append(if_match)
                if if_match != self.owner.etag:
                    raise RuntimeError("precondition failed: stale etag")

            self.owner.update_calls += 1
            incoming = dict(body["snippet"])
            mode = self.owner.mode
            call = self.owner.update_calls

            if call > 1 and mode in {
                "partial_confirmed",
                "partial_then_transport_failed",
                "partial_tags_missing",
            }:
                self.owner.set_snippet(incoming)
                return {"id": body["id"], "snippet": dict(incoming)}

            if mode == "accepted_then_transport_failed":
                self.owner.set_snippet(incoming)
                raise RuntimeError("connection reset after provider accepted request")
            if mode == "failed_before_provider_change":
                raise RuntimeError("connection failed before provider change")
            if mode == "divergent_after_failure":
                divergent = dict(incoming)
                divergent["title"] = "Concurrent external title"
                self.owner.set_snippet(divergent)
                raise RuntimeError("connection reset with divergent final state")
            if mode == "partial_tags_missing" and call == 1:
                partial = dict(incoming)
                partial["tags"] = list(self.owner.snippet.get("tags", []))
                self.owner.set_snippet(partial)
                return {"id": body["id"], "snippet": dict(self.owner.snippet)}
            if mode in {
                "partial_confirmed",
                "partial_then_transport_failed",
                "partial_restore_once",
                "partial_restore_stuck",
                "partial_restore_other",
            } and call == 1:
                partial = dict(self.owner.snippet)
                partial["tags"] = list(incoming.get("tags", []))
                self.owner.set_snippet(partial)
                if mode == "partial_then_transport_failed":
                    raise RuntimeError("connection reset after partial provider write")
                return {"id": body["id"], "snippet": dict(self.owner.snippet)}
            if mode == "partial_restore_once" and call == 2:
                # Simulate the exact production failure mode: the provider also
                # partially applies the first compensation, leaving new tags.
                partial = dict(incoming)
                partial["tags"] = list(self.owner.snippet.get("tags", []))
                self.owner.set_snippet(partial)
                return {"id": body["id"], "snippet": dict(self.owner.snippet)}
            if mode == "partial_restore_once" and call == 3:
                self.owner.set_snippet(incoming)
                return {"id": body["id"], "snippet": dict(incoming)}
            if mode == "partial_restore_stuck" and call > 1:
                partial = dict(incoming)
                partial["tags"] = list(self.owner.snippet.get("tags", []))
                self.owner.set_snippet(partial)
                return {"id": body["id"], "snippet": dict(self.owner.snippet)}
            if mode == "partial_restore_other" and call == 2:
                divergent = dict(incoming)
                divergent["title"] = "External title during restore"
                divergent["tags"] = list(self.owner.snippet.get("tags", []))
                self.owner.set_snippet(divergent)
                return {"id": body["id"], "snippet": dict(self.owner.snippet)}
            if mode == "provider_reorders_tags":
                reordered = dict(incoming)
                reordered["tags"] = sorted(
                    list(incoming.get("tags", [])),
                    key=lambda item: str(item).casefold(),
                )
                self.owner.set_snippet(reordered)
                return {"id": body["id"], "snippet": dict(self.owner.snippet)}

            self.owner.set_snippet(incoming)
            return {"id": body["id"], "snippet": dict(incoming)}

        request = _Request(apply)
        request.body = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        holder["request"] = request
        return request


class _VideoCategories:
    def __init__(self, owner):
        self.owner = owner

    def list(self, *, part: str, id: str):
        assert part == "snippet"
        item = {
            "id": str(id),
            "snippet": {"title": "Test category", "assignable": True},
        }
        return _Request(lambda: {"items": [item]})


class _FakeYouTube:
    def __init__(self, mode: str):
        self.video_id = "video-1"
        self.channel_id = "channel-1"
        self.mode = mode
        self.update_calls = 0
        self.revision = 1
        self.if_match_headers: list[str] = []
        self.update_bodies: list[dict] = []
        self.snippet = {
            "title": "Original",
            "description": "Description",
            "tags": ["old"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        }
        self._channels = _Channels(self)
        self._videos = _Videos(self)
        self._video_categories = _VideoCategories(self)

    @property
    def etag(self) -> str:
        return f'"etag-{self.revision}"'

    def set_snippet(self, snippet: dict):
        self.snippet = dict(snippet)
        self.revision += 1

    def channels(self):
        return self._channels

    def videos(self):
        return self._videos

    def videoCategories(self):
        return self._video_categories


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


def _preview_all_fields(service, youtube):
    return service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Approved title",
        description="Approved description",
        tags=["new", "tags"],
        category_id="10",
    )


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
    assert youtube.if_match_headers == ['"etag-1"']


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
    assert youtube.if_match_headers == ['"etag-1"']


def test_divergent_ambiguous_state_is_not_overwritten(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "divergent_after_failure")
    preview = service.preview_video_metadata_update(video_id=youtube.video_id, title="Approved title")
    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    assert caught.value.code == "write_state_uncertain"
    assert youtube.snippet["title"] == "Concurrent external title"
    assert youtube.update_calls == 1
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.last_action_type == "metadata_write_ambiguous_state"


def test_confirmed_partial_tags_write_is_restored_and_structured(tmp_path, monkeypatch, caplog):
    service, youtube = _service(tmp_path, monkeypatch, "partial_confirmed")
    before = dict(youtube.snippet)
    preview = _preview_all_fields(service, youtube)

    with caplog.at_level(logging.WARNING, logger="creator_service.responsible_service"):
        with pytest.raises(CreatorToolError) as caught:
            service.apply_video_metadata_update(
                approval_payload=preview["approval_payload"],
                approval_token=preview["approval_token"],
            )

    assert caught.value.code == "partial_write_detected"
    assert youtube.snippet == before
    assert youtube.update_calls == 2
    assert youtube.if_match_headers == ['"etag-1"', '"etag-2"']
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is False

    diagnostics = [
        json.loads(record.message)
        for record in caplog.records
        if '"event":"metadata_partial_write_state"' in record.message
    ]
    first = diagnostics[0]
    assert first["phase"] == "confirmed_response_initial_window"
    assert first["field_states"] == {
        "title": "before",
        "description": "before",
        "tags": "expected",
        "categoryId": "before",
        "defaultLanguage": "expected",
    }
    assert any(item["phase"] == "restore_attempt_1" for item in diagnostics)
    serialized = json.dumps(diagnostics)
    assert "Approved title" not in serialized
    assert "Approved description" not in serialized
    assert '"new"' not in serialized


def test_transport_failed_partial_tags_write_is_restored_and_structured(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_then_transport_failed")
    before = dict(youtube.snippet)
    preview = _preview_all_fields(service, youtube)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert caught.value.code == "partial_write_detected"
    assert youtube.snippet == before
    assert youtube.update_calls == 2
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is False


def test_partial_restore_reconciles_once_then_verifies_exact_snapshot(tmp_path, monkeypatch, caplog):
    service, youtube = _service(tmp_path, monkeypatch, "partial_restore_once")
    before = dict(youtube.snippet)
    preview = _preview_all_fields(service, youtube)

    with caplog.at_level(logging.WARNING, logger="creator_service.responsible_service"):
        with pytest.raises(CreatorToolError) as caught:
            service.apply_video_metadata_update(
                approval_payload=preview["approval_payload"],
                approval_token=preview["approval_token"],
            )

    assert caught.value.code == "partial_write_detected"
    assert youtube.snippet == before
    assert youtube.update_calls == 3
    assert youtube.if_match_headers == ['"etag-1"', '"etag-2"', '"etag-3"']
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is False
    phases = [
        json.loads(record.message)["phase"]
        for record in caplog.records
        if '"event":"metadata_partial_write_state"' in record.message
    ]
    assert "restore_attempt_1" in phases
    assert "restore_attempt_2" in phases


def test_restore_stops_on_third_party_value_and_protects_video(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_restore_other")
    preview = _preview_all_fields(service, youtube)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert caught.value.code == "write_state_uncertain"
    assert youtube.update_calls == 2
    assert youtube.snippet["title"] == "External title during restore"
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.last_action_type == "metadata_restore_uncertain_state"


def test_restore_budget_exhaustion_protects_video_without_unbounded_writes(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_restore_stuck")
    preview = _preview_all_fields(service, youtube)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert caught.value.code == "rollback_incomplete"
    assert caught.value.details is not None
    assert caught.value.details["restored_and_verified"] is False
    assert caught.value.details["mismatched_fields"] == ["tags"]
    assert caught.value.details["field_matches"]["title_matches"] is True
    assert caught.value.details["field_matches"]["description_matches"] is True
    assert caught.value.details["field_matches"]["tags_match"] is False
    assert caught.value.details["field_matches"]["category_matches"] is True
    assert youtube.update_calls == 1 + ResponsibleCreatorService._MAX_RESTORE_WRITES
    assert youtube.snippet["tags"] == ["new", "tags"]
    state = service.memory.recent_edit_state(youtube.video_id)
    assert state.protected is True
    assert state.last_action_type == "metadata_restore_uncertain_state"


def test_provider_tag_reordering_is_verified_as_success(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "provider_reorders_tags")
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Approved title",
        description="Approved description",
        tags=["Zulu tag", "alpha tag", "Middle tag"],
        category_id="10",
    )

    result = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["persisted_verified"] is True
    assert result["changed_fields"] == ["title", "description", "tags", "categoryId"]
    assert result["normalization_differences"] == ["tags"]
    assert youtube.snippet["tags"] == ["alpha tag", "Middle tag", "Zulu tag"]
    assert youtube.update_calls == 1


def test_verification_budgets_are_bounded_for_mcp_request_lifetime():
    assert sum(ResponsibleCreatorService._WRITE_VERIFY_DELAYS) <= 3.0
    assert sum(ResponsibleCreatorService._WRITE_SETTLE_VERIFY_DELAYS) <= 7.0
    assert sum(ResponsibleCreatorService._AMBIGUOUS_VERIFY_DELAYS) <= 3.0
    assert sum(ResponsibleCreatorService._RESTORE_VERIFY_DELAYS) <= 6.0
    assert sum(ResponsibleCreatorService._ROLLBACK_SETTLE_VERIFY_DELAYS) <= 12.0
    assert ResponsibleCreatorService._MAX_RESTORE_WRITES == 2
    assert sum(ResponsibleCreatorService._RESTORE_VERIFY_DELAYS) * ResponsibleCreatorService._MAX_RESTORE_WRITES <= 12.0
    assert (
        sum(ResponsibleCreatorService._WRITE_VERIFY_DELAYS)
        + sum(ResponsibleCreatorService._WRITE_SETTLE_VERIFY_DELAYS)
        + sum(ResponsibleCreatorService._RESTORE_VERIFY_DELAYS) * ResponsibleCreatorService._MAX_RESTORE_WRITES
        + sum(ResponsibleCreatorService._ROLLBACK_SETTLE_VERIFY_DELAYS)
    ) <= 32.0


def test_title_and_description_can_persist_while_tags_do_not_and_are_restored(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_tags_missing")
    before = dict(youtube.snippet)
    preview = _preview_all_fields(service, youtube)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert caught.value.code == "partial_write_detected"
    assert youtube.snippet == before
    assert youtube.update_calls == 2


def test_restore_budget_uses_read_only_settlement_before_declaring_incomplete(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_restore_stuck")
    before = dict(youtube.snippet)
    expected = dict(before)
    expected.update({
        "title": "Approved title",
        "description": "Approved description",
        "tags": ["new", "tags"],
        "categoryId": "10",
    })

    # Start exactly where the production incident enters compensation:
    # the original apply already happened and only the new tags are visible.
    youtube.set_snippet({**before, "tags": ["new", "tags"]})
    youtube.update_calls = 1

    original_wait = service._wait_for_snippet
    settle_calls = []

    def eventual_wait(video_id, wanted, delays):
        if delays == service._ROLLBACK_SETTLE_VERIFY_DELAYS:
            settle_calls.append(tuple(delays))
            # Simulate YouTube converging after the last compensation without
            # any additional videos.update call.
            youtube.set_snippet(before)
            return dict(before), [], [], 3
        return original_wait(video_id, wanted, delays)

    monkeypatch.setattr(service, "_wait_for_snippet", eventual_wait)

    restored, mismatches, _exact, attempts = service._restore_verified_snapshot(
        video_id=youtube.video_id,
        before=before,
        expected=expected,
    )

    assert restored == before
    assert mismatches == []
    assert settle_calls == [service._ROLLBACK_SETTLE_VERIFY_DELAYS]
    assert youtube.update_calls == 1 + ResponsibleCreatorService._MAX_RESTORE_WRITES
    assert attempts > 0


def test_partial_error_preserves_pre_rollback_snapshot(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_confirmed")
    before = dict(youtube.snippet)
    preview = _preview_all_fields(service, youtube)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert caught.value.code == "partial_write_detected"
    details = caught.value.details
    assert details["state"] == "partial_write_detected_and_restored"
    write = details["write_verification"]
    assert write["expected_snapshot"]["tags"] == ["new", "tags"]
    assert write["observed_snapshot_after_write"]["tags"] == ["new", "tags"]
    assert write["observed_snapshot_after_write"]["title"] == before["title"]
    assert write["mismatched_fields"] == ["title", "description", "categoryId"]
    assert write["tags_match"] is True
    assert write["verification_attempts"] == (
        len(service._WRITE_VERIFY_DELAYS) + len(service._WRITE_SETTLE_VERIFY_DELAYS)
    )
    assert write["elapsed_ms"] >= 0
    rollback = details["rollback"]
    assert rollback["restored_and_verified"] is True
    assert rollback["observed_snapshot"] == before
    assert youtube.snippet == before


def test_metadata_limit_is_blocked_before_any_video_update(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "normal")
    with pytest.raises(CreatorToolError) as caught:
        service.preview_video_metadata_update(
            video_id=youtube.video_id,
            title="Approved title",
            tags=["x" * 501],
            category_id="22",
        )
    assert caught.value.code == "metadata_limit_exceeded"
    assert caught.value.details["field"] == "tags"
    assert youtube.update_calls == 0


def test_request_body_contains_exact_approved_tags_with_unicode_and_spaces(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "normal")
    tags = [
        "café sem irrigação",
        "estresse hídrico no café",
        "Made in Roça",
        "roçada no café",
    ]
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Café novo",
        description="Descrição com acentos • teste",
        tags=tags,
        category_id="22",
    )
    proposed = preview["approval_payload"]["proposed"]

    result = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["persisted_verified"] is True
    assert youtube.update_calls == 1
    assert len(youtube.update_bodies) == 1
    request = youtube.update_bodies[0]
    assert request["part"] == "snippet"
    snippet = request["body"]["snippet"]
    assert snippet["title"] == proposed["title"]
    assert snippet["description"] == proposed["description"]
    assert snippet["tags"] == proposed["tags"]
    assert snippet["categoryId"] == proposed["categoryId"]
    assert snippet["defaultLanguage"] == proposed["defaultLanguage"]


def test_request_body_tags_are_not_overwritten_by_old_snapshot(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "normal")
    old_tags = list(youtube.snippet["tags"])
    new_tags = ["old", "new tag", "café"]
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Approved title",
        tags=new_tags,
        category_id="22",
    )

    service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    sent_tags = youtube.update_bodies[0]["body"]["snippet"]["tags"]
    assert sent_tags == new_tags
    assert sent_tags != old_tags


def test_request_diagnostics_prove_tags_presence_without_logging_tag_values(tmp_path, monkeypatch, caplog):
    service, youtube = _service(tmp_path, monkeypatch, "normal")
    tags = ["café sem irrigação", "Made in Roça"]
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Approved title",
        tags=tags,
        category_id="22",
    )

    with caplog.at_level(logging.INFO, logger="creator_service.responsible_service"):
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    events = [
        json.loads(record.message)
        for record in caplog.records
        if '"event":"metadata_update_request"' in record.message
    ]
    assert len(events) == 1
    event = events[0]
    assert event["has_tags"] is True
    assert event["tags_count"] == len(tags)
    assert event["snippet_keys"] == ["categoryId", "defaultLanguage", "description", "tags", "title"]
    assert event["tags_hash"]
    serialized = json.dumps(event, ensure_ascii=False)
    assert "café sem irrigação" not in serialized
    assert "Made in Roça" not in serialized


def test_original_write_waits_read_only_for_late_tags_before_rollback(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_tags_missing")
    preview = _preview_all_fields(service, youtube)
    expected = dict(preview["approval_payload"]["proposed"])
    before = dict(youtube.snippet)
    initial_partial = {
        **expected,
        "tags": list(before["tags"]),
    }
    calls = []
    original_wait = service._wait_for_snippet

    def controlled_wait(video_id, wanted, delays):
        calls.append(tuple(delays))
        if delays == service._WRITE_VERIFY_DELAYS:
            return dict(initial_partial), ["tags"], ["tags"], len(delays)
        if delays == service._WRITE_SETTLE_VERIFY_DELAYS:
            youtube.set_snippet(expected)
            return dict(expected), [], [], 3
        return original_wait(video_id, wanted, delays)

    monkeypatch.setattr(service, "_wait_for_snippet", controlled_wait)

    result = service.apply_video_metadata_update(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )

    assert result["persisted_verified"] is True
    assert result["state"] == "success_verified"
    assert result["verification_attempts"] == len(service._WRITE_VERIFY_DELAYS) + 3
    assert youtube.update_calls == 1
    assert calls[:2] == [
        service._WRITE_VERIFY_DELAYS,
        service._WRITE_SETTLE_VERIFY_DELAYS,
    ]
    assert youtube.snippet["tags"] == expected["tags"]


def test_original_write_settlement_exhaustion_still_rolls_back_once(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "partial_tags_missing")
    preview = _preview_all_fields(service, youtube)
    before = dict(youtube.snippet)
    expected = dict(preview["approval_payload"]["proposed"])
    partial = {**expected, "tags": list(before["tags"])}
    original_wait = service._wait_for_snippet
    settle_seen = []

    def controlled_wait(video_id, wanted, delays):
        if delays == service._WRITE_VERIFY_DELAYS:
            youtube.set_snippet(partial)
            return dict(partial), ["tags"], ["tags"], len(delays)
        if delays == service._WRITE_SETTLE_VERIFY_DELAYS:
            settle_seen.append(True)
            return dict(partial), ["tags"], ["tags"], len(delays)
        return original_wait(video_id, wanted, delays)

    monkeypatch.setattr(service, "_wait_for_snippet", controlled_wait)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert caught.value.code == "partial_write_detected"
    assert settle_seen == [True]
    assert youtube.update_calls == 2
    assert youtube.snippet == before
    write = caught.value.details["write_verification"]
    assert write["mismatched_fields"] == ["tags"]
    assert write["verification_attempts"] == (
        len(service._WRITE_VERIFY_DELAYS) + len(service._WRITE_SETTLE_VERIFY_DELAYS)
    )


def test_serialized_request_body_preserves_exact_tags(tmp_path, monkeypatch, caplog):
    service, youtube = _service(tmp_path, monkeypatch, "normal")
    tags = ["café sem irrigação", "Made in Roça", "roçada no café"]
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Approved title",
        description="Approved description",
        tags=tags,
        category_id="22",
    )

    with caplog.at_level(logging.INFO, logger="creator_service.responsible_service"):
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    serialized = [
        json.loads(record.message)
        for record in caplog.records
        if '"event":"metadata_update_serialized_request"' in record.message
    ]
    assert len(serialized) == 1
    event = serialized[0]
    assert event["has_tags"] is True
    assert event["tags_count"] == len(tags)
    assert event["snippet_keys"] == ["categoryId", "defaultLanguage", "description", "tags", "title"]
    request_event = [
        json.loads(record.message)
        for record in caplog.records
        if '"event":"metadata_update_request"' in record.message
    ][0]
    assert event["tags_hash"] == request_event["tags_hash"]


def test_serialized_request_tag_mutation_is_blocked_before_execute(tmp_path, monkeypatch):
    service, youtube = _service(tmp_path, monkeypatch, "normal")
    preview = service.preview_video_metadata_update(
        video_id=youtube.video_id,
        title="Approved title",
        tags=["new tag", "café"],
        category_id="22",
    )

    original_update = youtube._videos.update

    def corrupt_serialization(*, part, body):
        request = original_update(part=part, body=body)
        serialized = json.loads(request.body)
        serialized["snippet"]["tags"] = ["old"]
        request.body = json.dumps(serialized, ensure_ascii=False, separators=(",", ":"))
        return request

    monkeypatch.setattr(youtube._videos, "update", corrupt_serialization)

    with pytest.raises(CreatorToolError) as caught:
        service.apply_video_metadata_update(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )

    assert caught.value.code == "invalid_request"
    assert youtube.update_calls == 0
    assert caught.value.details["field"] == "tags"
    assert caught.value.details["serialized_has_tags"] is True
