from __future__ import annotations

from typing import Any

from mcp.types import ToolAnnotations

from . import cloud_mcp_server as base
from . import cloud_mcp_server_advanced as advanced
from .dashboard_ai import youtube_transcript


def _owned_video_details(service, video_id: str) -> dict[str, Any]:
    video_id = str(video_id or "").strip()
    if not video_id:
        raise ValueError("video_id é obrigatório.")

    youtube = service._youtube()
    channel_response = youtube.channels().list(part="snippet", mine=True).execute()
    channel_items = channel_response.get("items", [])
    if not channel_items:
        raise RuntimeError("Nenhum canal ativo foi encontrado para a conta conectada.")
    channel_id = str(channel_items[0].get("id", ""))

    response = youtube.videos().list(
        part="snippet,contentDetails,statistics,status",
        id=video_id,
    ).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError("Vídeo não encontrado.")
    item = items[0]
    snippet = item.get("snippet", {})
    if str(snippet.get("channelId", "")) != channel_id:
        raise PermissionError("O vídeo não pertence ao canal conectado.")

    thumbnails = snippet.get("thumbnails", {}) or {}
    thumbnail = (
        thumbnails.get("maxres")
        or thumbnails.get("standard")
        or thumbnails.get("high")
        or thumbnails.get("medium")
        or thumbnails.get("default")
        or {}
    ).get("url")
    statistics = item.get("statistics", {}) or {}
    status = item.get("status", {}) or {}
    content = item.get("contentDetails", {}) or {}
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
        "thumbnail": thumbnail,
        "duration": content.get("duration"),
        "definition": content.get("definition"),
        "caption": content.get("caption"),
        "privacy_status": status.get("privacyStatus"),
        "made_for_kids": status.get("madeForKids"),
        "views": int(statistics.get("viewCount", 0) or 0),
        "likes": int(statistics.get("likeCount", 0) or 0),
        "comments": int(statistics.get("commentCount", 0) or 0),
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
        """Leitura: retorna metadados, status e estatísticas de um vídeo pertencente ao canal conectado."""
        base._require_scope(base.READ_SCOPE)
        base._limit("video_details", limit=120)
        return _owned_video_details(advanced._service(), video_id)

    @server.tool(
        title="Obter transcrição de um vídeo do canal",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        ),
    )
    def get_video_transcript(video_id: str, max_chars: int = 28000) -> dict[str, Any]:
        """Leitura: baixa uma legenda autorizada do vídeo e devolve texto limpo; não modifica o YouTube."""
        base._require_scope(base.READ_SCOPE)
        base._limit("video_transcript", limit=60)
        service = advanced._service()
        details = _owned_video_details(service, video_id)
        limit = max(1000, min(100000, int(max_chars)))
        result = youtube_transcript(service._youtube(), details["video_id"], max_chars=limit)
        return {"video_id": details["video_id"], "title": details["title"], **result}

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
