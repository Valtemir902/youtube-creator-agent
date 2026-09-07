from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any

from .mcp_errors import tool_error
from .media_transcription import MediaTranscriptionError, WhisperCppTranscriber


_MEDIA_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mp3", ".wav", ".m4a")
_TIMECODE_RE = re.compile(
    r"^(?P<h>\d{1,3}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})$"
)


def _seconds(value: str) -> float:
    match = _TIMECODE_RE.match(str(value).strip())
    if not match:
        raise ValueError(f"Invalid caption timecode: {value}")
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(match.group("ms")) / 1000.0
    )


def parse_srt_segments(payload: str | bytes) -> list[dict[str, Any]]:
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload or "")
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    output: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        raw_start, raw_end = [part.strip().split(" ", 1)[0] for part in lines[timing_index].split("-->", 1)]
        try:
            start = _seconds(raw_start)
            end = _seconds(raw_end)
        except ValueError:
            continue
        cue_text = " ".join(lines[timing_index + 1 :])
        cue_text = re.sub(r"<[^>]+>", "", cue_text)
        cue_text = html.unescape(cue_text)
        cue_text = re.sub(r"\s+", " ", cue_text).strip()
        if not cue_text:
            continue
        output.append(
            {
                "start": round(max(0.0, start), 3),
                "duration": round(max(0.0, end - start), 3),
                "text": cue_text,
            }
        )
    return output


def _full_text(segments: list[dict[str, Any]]) -> str:
    return re.sub(r"\s+", " ", " ".join(str(segment.get("text", "")) for segment in segments)).strip()


def _language_rank(track_language: str | None, requested: str | None) -> int:
    if not requested:
        return 0
    track = str(track_language or "").casefold()
    wanted = str(requested).casefold()
    if track == wanted:
        return 0
    if track.split("-", 1)[0] == wanted.split("-", 1)[0] and track:
        return 1
    return 2


def _ordered_tracks(tracks: list[dict[str, Any]], language: str | None) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]):
        snippet = item.get("snippet", {}) or {}
        return (
            _language_rank(snippet.get("language"), language),
            str(snippet.get("trackKind", "")).upper() == "ASR",
            bool(snippet.get("isDraft", False)),
        )

    return sorted(tracks, key=key)


def caption_transcript(youtube, video_id: str, *, language: str | None = None) -> dict[str, Any] | None:
    try:
        tracks = youtube.captions().list(part="id,snippet", videoId=video_id).execute().get("items", [])
    except Exception as exc:
        raise tool_error("youtube_api_error", "YouTube caption listing failed.") from exc
    if not tracks:
        return None

    requested = str(language or "").strip() or None
    for track in _ordered_tracks(list(tracks), requested):
        caption_id = str(track.get("id", "")).strip()
        if not caption_id:
            continue
        snippet = track.get("snippet", {}) or {}
        try:
            payload = youtube.captions().download(id=caption_id, tfmt="srt").execute()
        except Exception:
            continue
        segments = parse_srt_segments(payload)
        if not segments:
            continue
        full_text = _full_text(segments)
        if not full_text:
            continue
        auto = str(snippet.get("trackKind", "")).upper() == "ASR"
        return {
            "language": snippet.get("language") or requested,
            "source": "youtube_caption",
            "is_auto_generated": auto,
            "caption_id": caption_id,
            "caption_name": snippet.get("name"),
            "track_kind": snippet.get("trackKind"),
            "segments": segments,
            "full_text": full_text,
            "word_count": len(full_text.split()),
        }
    return None


def authorized_local_media_path(context, video_id: str) -> Path | None:
    """Resolve only tenant-owned local source media; never scrape/download YouTube media."""
    video_id = str(video_id or "").strip()
    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", video_id):
        return None
    root = (Path(context.data_dir) / "video_sources").resolve()
    if not root.is_dir():
        return None
    for suffix in _MEDIA_SUFFIXES:
        candidate = (root / f"{video_id}{suffix}").resolve()
        if root not in candidate.parents:
            continue
        if candidate.is_file():
            return candidate
    return None


def local_audio_transcript(
    context,
    video_id: str,
    *,
    language: str | None = None,
    transcriber_factory=WhisperCppTranscriber,
) -> dict[str, Any] | None:
    media = authorized_local_media_path(context, video_id)
    if media is None:
        return None
    try:
        result = transcriber_factory().transcribe(media, language=language or "auto")
    except MediaTranscriptionError as exc:
        raise tool_error("transcription_failed", str(exc)[:500]) from exc
    segments = [
        {"start": segment.start, "duration": segment.duration, "text": segment.text}
        for segment in result.segments
    ]
    full_text = result.text.strip()
    return {
        "language": result.language,
        "source": "local_whisper",
        "is_auto_generated": True,
        "engine": result.engine,
        "segments": segments,
        "full_text": full_text,
        "word_count": len(full_text.split()),
    }


def get_video_transcript_data(
    service,
    video_id: str,
    *,
    language: str | None = None,
    include_segments: bool = True,
    segment_offset: int = 0,
    segment_limit: int = 500,
    transcriber_factory=WhisperCppTranscriber,
) -> dict[str, Any]:
    video_id = str(video_id or "").strip()
    if not video_id:
        raise tool_error("invalid_request", "video_id is required.")

    # Ownership must be established before captions or local fallback are read.
    service._owned_video_item(video_id, part="snippet")
    result = caption_transcript(service._youtube(), video_id, language=language)
    if result is None:
        result = local_audio_transcript(
            service.context,
            video_id,
            language=language,
            transcriber_factory=transcriber_factory,
        )
    if result is None:
        raise tool_error(
            "caption_not_available",
            "No downloadable owner-authorized caption is available, and no tenant-owned local source media exists for Whisper fallback.",
        )

    all_segments = list(result.pop("segments", []))
    offset = max(0, int(segment_offset))
    limit = max(1, min(2000, int(segment_limit)))
    page = all_segments[offset : offset + limit] if include_segments else []
    next_offset = offset + len(page)
    has_more = include_segments and next_offset < len(all_segments)
    return {
        "video_id": video_id,
        **result,
        "segments": page,
        "segment_count": len(all_segments),
        "segment_offset": offset,
        "segment_limit": limit,
        "segments_complete": not has_more,
        "next_segment_offset": next_offset if has_more else None,
        "full_text_complete": True,
    }
