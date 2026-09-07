from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from creator_service.mcp_errors import CreatorToolError
from creator_service.media_transcription import MediaTranscriptionResult, MediaTranscriptionSegment
from creator_service.video_transcript import (
    caption_transcript,
    get_video_transcript_data,
    parse_srt_segments,
)


SRT = b"""1
00:00:00,000 --> 00:00:04,200
The cursed fiddle calls.

2
00:00:04,200 --> 00:00:07,000
From the Appalachian dark.
"""


class _Execute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Captions:
    def __init__(self, tracks=None, downloads=None):
        self.tracks = list(tracks or [])
        self.downloads = dict(downloads or {})

    def list(self, **_kwargs):
        return _Execute({"items": list(self.tracks)})

    def download(self, *, id: str, tfmt: str):
        assert tfmt == "srt"
        if id not in self.downloads:
            raise RuntimeError("not downloadable")
        return _Execute(self.downloads[id])


class _Youtube:
    def __init__(self, captions):
        self._captions = captions

    def captions(self):
        return self._captions


class _Service:
    def __init__(self, context, youtube):
        self.context = context
        self.youtube = youtube
        self.ownership_checks = 0

    def _youtube(self):
        return self.youtube

    def _owned_video_item(self, video_id: str, *, part: str):
        assert video_id == "video-1"
        assert "snippet" in part
        self.ownership_checks += 1
        return {"id": video_id, "snippet": {"channelId": "channel-1"}}


def test_parse_srt_preserves_real_segment_timing():
    segments = parse_srt_segments(SRT)
    assert segments == [
        {"start": 0.0, "duration": 4.2, "text": "The cursed fiddle calls."},
        {"start": 4.2, "duration": 2.8, "text": "From the Appalachian dark."},
    ]


def test_caption_transcript_prefers_owner_caption_over_asr():
    tracks = [
        {"id": "asr", "snippet": {"language": "en", "trackKind": "ASR", "isDraft": False}},
        {"id": "official", "snippet": {"language": "en", "trackKind": "standard", "isDraft": False}},
    ]
    result = caption_transcript(_Youtube(_Captions(tracks, {"official": SRT, "asr": SRT})), "video-1", language="en")
    assert result is not None
    assert result["caption_id"] == "official"
    assert result["source"] == "youtube_caption"
    assert result["is_auto_generated"] is False
    assert result["word_count"] == 8
    assert len(result["segments"]) == 2


def test_get_video_transcript_without_caption_or_local_media_is_typed(tmp_path):
    context = SimpleNamespace(data_dir=tmp_path)
    service = _Service(context, _Youtube(_Captions()))
    with pytest.raises(CreatorToolError) as caught:
        get_video_transcript_data(service, "video-1")
    assert caught.value.code == "caption_not_available"
    assert service.ownership_checks == 1


def test_get_video_transcript_falls_back_to_tenant_local_whisper(tmp_path):
    source_dir = Path(tmp_path) / "video_sources"
    source_dir.mkdir(parents=True)
    (source_dir / "video-1.mp4").write_bytes(b"authorized-source-fixture")
    context = SimpleNamespace(data_dir=tmp_path)
    service = _Service(context, _Youtube(_Captions()))

    class _Transcriber:
        def transcribe(self, media_path, *, language="auto"):
            assert Path(media_path).name == "video-1.mp4"
            assert language == "en"
            return MediaTranscriptionResult(
                text="Real words from local media",
                engine="test-whisper",
                language="en",
                chars=27,
                segments=(
                    MediaTranscriptionSegment(start=0.0, duration=2.5, text="Real words"),
                    MediaTranscriptionSegment(start=2.5, duration=2.0, text="from local media"),
                ),
            )

    result = get_video_transcript_data(
        service,
        "video-1",
        language="en",
        transcriber_factory=_Transcriber,
    )
    assert result["source"] == "local_whisper"
    assert result["full_text"] == "Real words from local media"
    assert result["word_count"] == 5
    assert result["segments"][0]["start"] == 0.0
    assert result["full_text_complete"] is True


def test_segments_are_paginated_without_truncating_full_text(tmp_path):
    tracks = [{"id": "official", "snippet": {"language": "en", "trackKind": "standard", "isDraft": False}}]
    context = SimpleNamespace(data_dir=tmp_path)
    service = _Service(context, _Youtube(_Captions(tracks, {"official": SRT})))
    result = get_video_transcript_data(service, "video-1", segment_limit=1)
    assert len(result["segments"]) == 1
    assert result["segment_count"] == 2
    assert result["segments_complete"] is False
    assert result["next_segment_offset"] == 1
    assert result["full_text"] == "The cursed fiddle calls. From the Appalachian dark."
    assert result["full_text_complete"] is True
