from __future__ import annotations

from types import SimpleNamespace

import pytest

from creator_service.advanced_service import AdvancedSafeCreatorService
from creator_service.caption_quality import parse_srt, process_srt, sanitize_caption_text
from creator_service.mcp_errors import CreatorToolError
from creator_service.security import ApprovalTokenSigner
import creator_service.cloud_mcp_server_management as management


SECRET = "0123456789abcdef0123456789abcdef"


VALID_SRT = """1
00:00:00,000 --> 00:00:02,000
Ghost town road.

2
00:00:02,100 --> 00:00:04,500
Midnight rider returns.
"""


class _Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Memory:
    def __init__(self):
        self.actions = []

    def record_video_action(self, **kwargs):
        self.actions.append(kwargs)


class _Captions:
    def __init__(self, tracks=None):
        self.tracks = list(tracks or [])
        self.insert_calls = 0
        self.delete_calls = 0

    def list(self, **kwargs):
        assert kwargs["videoId"] == "video-1"
        return _Request(lambda: {"items": [dict(item) for item in self.tracks]})

    def insert(self, *, part: str, body: dict, media_body):
        assert part == "snippet"
        assert body["snippet"]["videoId"] == "video-1"

        def do_insert():
            self.insert_calls += 1
            item = {
                "id": "manual-new",
                "snippet": {
                    "videoId": "video-1",
                    "language": body["snippet"]["language"],
                    "name": body["snippet"]["name"],
                    "trackKind": "standard",
                    "status": "serving",
                    "isDraft": False,
                },
            }
            self.tracks.append(item)
            return item

        return _Request(do_insert)

    def delete(self, *, id: str):
        def do_delete():
            self.delete_calls += 1
            self.tracks = [item for item in self.tracks if str(item.get("id")) != id]
            return {}

        return _Request(do_delete)


class _Videos:
    def __init__(self, channel_id="channel-1", duration="PT10S"):
        self.channel_id = channel_id
        self.duration = duration

    def list(self, *, part: str, id: str):
        assert id == "video-1"
        return _Request(
            lambda: {
                "items": [
                    {
                        "id": "video-1",
                        "snippet": {"channelId": self.channel_id},
                        "contentDetails": {"duration": self.duration},
                    }
                ]
            }
        )


class _Youtube:
    def __init__(self, tracks=None, channel_id="channel-1", duration="PT10S"):
        self._captions = _Captions(tracks)
        self._videos = _Videos(channel_id=channel_id, duration=duration)

    def captions(self):
        return self._captions

    def videos(self):
        return self._videos


class _Service(AdvancedSafeCreatorService):
    def __init__(self, youtube):
        self.context = SimpleNamespace(tenant_id="tenant-1", validate_youtube=lambda: None)
        self.memory = _Memory()
        self._authorized_channel_cache = "channel-1"
        self.youtube = youtube

    def _youtube(self):
        return self.youtube


@pytest.fixture(autouse=True)
def _approval_secret(monkeypatch):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)


def test_valid_srt_passes_and_reports_quality():
    result = process_srt(VALID_SRT, video_duration=10.0)
    assert result["validation_passed"] is True
    assert result["cue_count"] == 2
    assert result["overlap_count"] == 0
    assert result["empty_cue_count"] == 0
    assert result["malformed_cue_count"] == 0
    assert result["estimated_readability"]["rating"] in {"good", "fast", "too_fast"}


def test_overlap_is_repaired_deterministically_without_simultaneous_cues():
    srt = """1
00:00:00,000 --> 00:00:03,000
Ghost town road.

2
00:00:02,500 --> 00:00:05,000
Midnight rider returns.
"""
    result = process_srt(srt, video_duration=10.0)
    assert result["validation_passed"] is True
    assert result["source_overlap_count"] == 1
    assert result["overlap_count"] == 0
    cues, errors, _ = parse_srt(result["content"])
    assert not errors
    assert cues[1].start >= cues[0].end


@pytest.mark.parametrize(
    "srt,error_prefix",
    [
        (
            """1
00:00:03,000 --> 00:00:02,000
Bad time.
""",
            "non_positive_duration:",
        ),
        (
            """1
00:00:00,000 --> 00:00:02,000

""",
            "empty_cue:",
        ),
        (
            """1
00:00:00,000 --> 00:00:01,000
One.

1
00:00:01,000 --> 00:00:02,000
Two.
""",
            "duplicate_index:",
        ),
        (
            """1
00:00:09,000 --> 00:00:11,000
Outside.
""",
            "cue_outside_video:",
        ),
        (
            """1
not-a-time
Broken.
""",
            "missing_timing:",
        ),
    ],
)
def test_structural_errors_block_publication_preview(srt, error_prefix):
    result = process_srt(srt, video_duration=10.0)
    assert result["validation_passed"] is False
    assert any(error.startswith(error_prefix) for error in result["validation_errors"])


def test_negative_timestamp_is_malformed_and_blocked():
    srt = """1
-00:00:01,000 --> 00:00:02,000
Impossible.
"""
    result = process_srt(srt, video_duration=10.0)
    assert result["validation_passed"] is False
    assert any(error.startswith("invalid_timestamp:") for error in result["validation_errors"])


def test_music_and_singing_markers_are_sanitized_by_default():
    assert sanitize_caption_text("[music] [singing] Midnight road") == "Midnight road"


def test_fragmented_asr_is_merged_when_it_is_clearly_one_phrase():
    srt = """1
00:00:00,000 --> 00:00:02,000
I ride through the

2
00:00:02,050 --> 00:00:04,000
ghost town tonight.
"""
    result = process_srt(srt, video_duration=10.0)
    assert result["validation_passed"] is True
    assert result["cue_count"] == 1
    assert "I ride through the ghost town tonight." in result["content"]


def test_music_mode_preserves_distinct_verses_instead_of_merging():
    srt = """1
00:00:00,000 --> 00:00:02,000
Down the haunted highway

2
00:00:02,050 --> 00:00:04,000
Under a blood-red moon
"""
    result = process_srt(srt, video_duration=10.0, music_mode=True)
    assert result["validation_passed"] is True
    assert result["cue_count"] == 2


def test_preview_flags_existing_manual_caption_and_requires_explicit_decision():
    youtube = _Youtube(
        [
            {
                "id": "asr-1",
                "snippet": {
                    "language": "en",
                    "trackKind": "ASR",
                    "status": "serving",
                    "isDraft": False,
                },
            },
            {
                "id": "manual-1",
                "snippet": {
                    "language": "en",
                    "trackKind": "standard",
                    "status": "serving",
                    "isDraft": False,
                },
            },
        ]
    )
    preview = _Service(youtube).preview_caption_upload(
        video_id="video-1",
        language="en",
        content=VALID_SRT,
        name="English - Manual",
    )
    assert preview["manual_caption_already_exists"] is True
    assert preview["source_track_kind"] == "ASR"
    assert preview["source_caption_id"] == "asr-1"
    assert preview["apply_allowed"] is False
    assert "manual_caption_decision_required" in preview["validation_errors"]


def test_separate_manual_caption_requires_explicit_name_and_then_allows_preview():
    youtube = _Youtube(
        [
            {
                "id": "manual-1",
                "snippet": {
                    "language": "en",
                    "trackKind": "standard",
                    "status": "serving",
                    "isDraft": False,
                },
            }
        ]
    )
    service = _Service(youtube)
    blocked = service.preview_caption_upload(
        video_id="video-1",
        language="en",
        content=VALID_SRT,
        existing_manual_action="separate",
    )
    assert blocked["apply_allowed"] is False
    assert "separate_manual_caption_requires_name" in blocked["validation_errors"]

    allowed = service.preview_caption_upload(
        video_id="video-1",
        language="en",
        content=VALID_SRT,
        name="English Alternate",
        existing_manual_action="separate",
    )
    assert allowed["validation_passed"] is True
    assert allowed["apply_allowed"] is True


def test_invalid_duration_preview_cannot_be_applied():
    youtube = _Youtube(duration="PT10S")
    service = _Service(youtube)
    invalid = "1\n00:00:09,000 --> 00:00:11,000\nOutside duration.\n"
    preview = service.preview_caption_upload(
        video_id="video-1", language="en", content=invalid, name="English - Manual"
    )
    assert preview["validation_passed"] is False
    assert preview["apply_allowed"] is False
    with pytest.raises(ValueError, match="validação estrutural"):
        service.apply_caption_upload(
            approval_payload=preview["approval_payload"],
            approval_token=preview["approval_token"],
        )
    assert youtube._captions.insert_calls == 0

def test_apply_requires_signed_payload_and_confirms_serving_standard_readback():
    youtube = _Youtube(
        [
            {
                "id": "asr-1",
                "snippet": {
                    "language": "en",
                    "trackKind": "ASR",
                    "status": "serving",
                    "isDraft": False,
                },
            }
        ]
    )
    service = _Service(youtube)
    preview = service.preview_caption_upload(
        video_id="video-1",
        language="en",
        content=VALID_SRT,
        name="English - Manual",
        caption_mode="music",
    )
    result = service.apply_caption_upload(
        approval_payload=preview["approval_payload"],
        approval_token=preview["approval_token"],
    )
    assert result["ok"] is True
    assert result["persisted_verified"] is True
    assert result["track_kind"] == "standard"
    assert result["status"] == "serving"
    assert result["is_draft"] is False
    assert result["has_published_manual_caption"] is True
    assert result["verification_attempts"] == 1

    rollback = result["rollback_preview"]
    deleted = service.apply_caption_delete(
        rollback_payload=rollback["rollback_payload"],
        rollback_token=rollback["rollback_token"],
    )
    assert deleted["deleted"] is True
    assert youtube._captions.delete_calls == 1


def test_expired_caption_approval_token_is_rejected():
    signer = ApprovalTokenSigner(SECRET, ttl_seconds=60)
    payload = {"video_id": "video-1"}
    token = signer.issue("upload_video_caption", "video-1", payload, now=100)
    with pytest.raises(ValueError, match="expired"):
        signer.verify(
            token,
            action="upload_video_caption",
            subject="video-1",
            payload=payload,
            now=1000,
        )


def test_caption_replay_guard_rejects_second_consumption(monkeypatch):
    signer = ApprovalTokenSigner(SECRET)
    payload = {"video_id": "video-1"}
    token = signer.issue("upload_video_caption", "video-1", payload)

    class _Store:
        def __init__(self):
            self.used = False

        def consume_write_token(self, *_args, **_kwargs):
            if self.used:
                return False
            self.used = True
            return True

    store = _Store()
    monkeypatch.setattr(management, "signer_from_env", lambda: signer)
    monkeypatch.setattr(management.base, "_ops_store", lambda: store)
    monkeypatch.setattr(management.base, "_tenant_id", lambda: "tenant-1")
    management._consume_token(
        token=token,
        payload=payload,
        action="upload_video_caption",
        subject="video-1",
    )
    with pytest.raises(CreatorToolError):
        management._consume_token(
            token=token,
            payload=payload,
            action="upload_video_caption",
            subject="video-1",
        )


def test_ownership_validation_blocks_foreign_video():
    service = _Service(_Youtube(channel_id="foreign-channel"))
    with pytest.raises(CreatorToolError):
        service.preview_caption_upload(
            video_id="video-1",
            language="en",
            content=VALID_SRT,
            name="English - Manual",
        )
