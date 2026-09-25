from __future__ import annotations

from typing import Any

from desktop_local_server import LocalYouTubeClient, YOUTUBE_API
from elite_v2_youtube_writes import YouTubeWriteError


def authorized_channel_id(client: LocalYouTubeClient) -> str:
    channel_id = str(client.channel_identity().get("id") or "").strip()
    if not channel_id:
        raise YouTubeWriteError("Canal autorizado não pôde ser identificado.")
    return channel_id


def require_owned_video(client: LocalYouTubeClient, video_id: str) -> dict[str, Any]:
    video_id = str(video_id or "").strip()
    if not video_id:
        raise YouTubeWriteError("video_id é obrigatório")
    item = client.video_details(video_id)
    owner = str((item.get("snippet") or {}).get("channelId") or "").strip()
    expected = authorized_channel_id(client)
    if not owner or owner != expected:
        raise YouTubeWriteError("Operação bloqueada: o vídeo não pertence ao canal autorizado.")
    return item


def require_owned_playlist(client: LocalYouTubeClient, playlist_id: str) -> dict[str, Any]:
    playlist_id = str(playlist_id or "").strip()
    if not playlist_id:
        raise YouTubeWriteError("playlist_id é obrigatório")
    payload = client._get(  # noqa: SLF001 - local control-plane ownership check
        f"{YOUTUBE_API}/playlists",
        {"part": "snippet,status,contentDetails", "id": playlist_id, "maxResults": 1},
    )
    items = payload.get("items") or []
    if not items:
        raise YouTubeWriteError("Playlist não encontrada.")
    item = items[0]
    owner = str((item.get("snippet") or {}).get("channelId") or "").strip()
    expected = authorized_channel_id(client)
    if not owner or owner != expected:
        raise YouTubeWriteError("Operação bloqueada: a playlist não pertence ao canal autorizado.")
    return item


def require_owned_playlist_item(client: LocalYouTubeClient, item_id: str) -> dict[str, Any]:
    item_id = str(item_id or "").strip()
    if not item_id:
        raise YouTubeWriteError("playlist_item_id é obrigatório")
    payload = client._get(  # noqa: SLF001
        f"{YOUTUBE_API}/playlistItems",
        {"part": "snippet,contentDetails", "id": item_id, "maxResults": 1},
    )
    items = payload.get("items") or []
    if not items:
        raise YouTubeWriteError("Item de playlist não encontrado.")
    item = items[0]
    playlist_id = str((item.get("snippet") or {}).get("playlistId") or "").strip()
    require_owned_playlist(client, playlist_id)
    return item


def require_proposal_ownership(client: LocalYouTubeClient, target_kind: str, target_id: str, operation: str, proposed: dict[str, Any] | None) -> None:
    """Revalidate ownership immediately before mutation, guarding account switches after preview."""
    if target_kind in {"video", "thumbnail"}:
        require_owned_video(client, target_id)
        return
    if target_kind == "playlist":
        if operation != "create":
            require_owned_playlist(client, target_id)
        return
    if target_kind == "playlist_item":
        if operation == "create":
            playlist_id = str((proposed or {}).get("playlist_id") or "")
            require_owned_playlist(client, playlist_id)
        else:
            require_owned_playlist_item(client, target_id)
        return
    raise YouTubeWriteError(f"target_kind sem política de ownership: {target_kind}")
