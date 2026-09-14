from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from . import cloud_mcp_server as base
from . import cloud_mcp_server_advanced as advanced
from .video_transcript import get_video_transcript_data


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _owned_video_details(service, video_id: str) -> dict[str, Any]:
    video_id = str(video_id or "").strip()
    if not video_id:
        raise base.tool_error("invalid_request", "video_id is required.")

    item = service._owned_video_item(
        video_id,
        part="snippet,contentDetails,statistics,status,player,recordingDetails,topicDetails",
    )
    snippet = item.get("snippet", {}) or {}
    statistics = item.get("statistics", {}) or {}
    status = item.get("status", {}) or {}
    content = item.get("contentDetails", {}) or {}
    player = item.get("player", {}) or {}
    recording = item.get("recordingDetails", {}) or {}
    topics = item.get("topicDetails", {}) or {}
    thumbnails = dict(snippet.get("thumbnails", {}) or {})
    channel_id = str(snippet.get("channelId", ""))

    return {
        "video_id": video_id,
        "channel_id": channel_id,
        "title": str(snippet.get("title", "")),
        "description": str(snippet.get("description", "")),
        "tags": list(snippet.get("tags", []) or []),
        "category_id": str(snippet.get("categoryId", "")),
        "default_language": snippet.get("defaultLanguage"),
        "default_audio_language": snippet.get("defaultAudioLanguage"),
        "published_at": snippet.get("publishedAt"),
        "live_broadcast_content": snippet.get("liveBroadcastContent"),
        "thumbnails": thumbnails,
        "duration": content.get("duration"),
        "dimension": content.get("dimension"),
        "definition": content.get("definition"),
        "caption": content.get("caption"),
        "licensed_content": content.get("licensedContent"),
        "projection": content.get("projection"),
        "privacy_status": status.get("privacyStatus"),
        "upload_status": status.get("uploadStatus"),
        "embeddable": status.get("embeddable"),
        "public_stats_viewable": status.get("publicStatsViewable"),
        "made_for_kids": status.get("madeForKids"),
        "self_declared_made_for_kids": status.get("selfDeclaredMadeForKids"),
        "view_count": _int_or_zero(statistics.get("viewCount")),
        "like_count": _int_or_zero(statistics.get("likeCount")),
        "comment_count": _int_or_zero(statistics.get("commentCount")),
        # Compatibility aliases retained for existing plugin clients.
        "views": _int_or_zero(statistics.get("viewCount")),
        "likes": _int_or_zero(statistics.get("likeCount")),
        "comments": _int_or_zero(statistics.get("commentCount")),
        "embed_html": player.get("embedHtml"),
        "embed_width": player.get("embedWidth"),
        "embed_height": player.get("embedHeight"),
        "recording_date": recording.get("recordingDate"),
        "recording_location": recording.get("location"),
        "topic_categories": list(topics.get("topicCategories", []) or []),
    }


def create_server():
    server = advanced.create_server()

    @server.tool(
        title="Obter detalhes de um vídeo do canal",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        ),
    )
    def get_video_details(video_id: str) -> dict[str, Any]:
        """Leitura segura de metadados/status/estatísticas de um vídeo pertencente ao canal autenticado."""
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("video_details", limit=120)
            return base.success_response(_owned_video_details(advanced._service(), video_id))

        return base._structured("get_video_details", action)

    @server.tool(
        title="Obter transcrição completa de um vídeo do canal",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        ),
    )
    def get_video_transcript(
        video_id: str,
        language: str | None = None,
        include_segments: bool = True,
        segment_offset: int = 0,
        segment_limit: int = 500,
    ) -> dict[str, Any]:
        """Leitura: legenda oficial/ASR autorizada; fallback Whisper apenas para mídia local pertencente ao tenant."""
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("video_transcript", limit=60)
            service = advanced._service()
            details = _owned_video_details(service, video_id)
            transcript = get_video_transcript_data(
                service,
                details["video_id"],
                language=language,
                include_segments=include_segments,
                segment_offset=segment_offset,
                segment_limit=segment_limit,
            )
            return base.success_response({"title": details["title"], **transcript})

        return base._structured("get_video_transcript", action)

    return server


def run() -> None:
    server = create_server()
    import os

    host = os.environ.get("YCA_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("YCA_MCP_PORT", "8000"))
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    run()
