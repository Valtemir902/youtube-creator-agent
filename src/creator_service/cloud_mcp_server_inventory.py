from __future__ import annotations

import base64
import json
from typing import Any

from mcp.types import ToolAnnotations

from . import cloud_mcp_server as base
from . import cloud_mcp_server_management as management


_CURSOR_PREFIX = "yca-videos-v1."


def _encode_cursor(*, upstream_token: str, previous_video_ids: list[str], uploads_playlist_id: str) -> str:
    payload = {
        "u": str(upstream_token or ""),
        "p": [str(value) for value in previous_video_ids[-50:] if str(value)],
        "pl": str(uploads_playlist_id or ""),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return _CURSOR_PREFIX + encoded


def _decode_cursor(token: str | None) -> tuple[str | None, set[str], str | None]:
    value = str(token or "").strip()
    if not value:
        return None, set(), None
    if not value.startswith(_CURSOR_PREFIX):
        # Backward compatibility with the raw YouTube page token returned by
        # older server revisions.
        return value, set(), None
    encoded = value[len(_CURSOR_PREFIX) :]
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding).decode("utf-8"))
        upstream = str(payload.get("u", "")).strip() or None
        previous = {str(item).strip() for item in payload.get("p", []) if str(item).strip()}
        playlist_id = str(payload.get("pl", "")).strip() or None
    except Exception as exc:
        raise base.tool_error("invalid_request", "Invalid list_channel_videos page_token.") from exc
    if len(previous) > 50:
        raise base.tool_error("invalid_request", "Invalid list_channel_videos page_token state.")
    return upstream, previous, playlist_id


def _list_channel_videos_stable(service, *, max_results: int = 50, page_token: str | None = None) -> dict[str, Any]:
    channel_rows = service._youtube().channels().list(
        part="id,snippet,contentDetails,statistics",
        mine=True,
        maxResults=1,
    ).execute().get("items", [])
    if not channel_rows:
        raise base.tool_error("channel_not_found")
    channel = channel_rows[0]
    channel_id = str(channel.get("id", "")).strip()
    snippet = channel.get("snippet", {}) or {}
    content_details = channel.get("contentDetails", {}) or {}
    statistics = channel.get("statistics", {}) or {}
    uploads = str(((content_details.get("relatedPlaylists", {}) or {}).get("uploads", ""))).strip()
    if not uploads:
        raise base.tool_error("internal_error", "The authorized channel has no uploads playlist.")

    upstream_token, previous_ids, cursor_playlist_id = _decode_cursor(page_token)
    if cursor_playlist_id and cursor_playlist_id != uploads:
        raise base.tool_error("invalid_request", "The page_token belongs to a different uploads playlist.")

    limit = max(1, min(50, int(max_results)))
    selected_rows: list[tuple[str, dict[str, Any]]] = []
    selected_ids: set[str] = set()
    duplicate_ids: list[str] = []
    next_upstream = upstream_token

    # Fill the requested page even if YouTube repeats one item at a page
    # boundary. We only retain the previous page's IDs in the opaque cursor,
    # which keeps tokens small while addressing the observed boundary overlap.
    for _ in range(4):
        kwargs: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "playlistId": uploads,
            "maxResults": limit,
        }
        if next_upstream:
            kwargs["pageToken"] = next_upstream
        page = service._youtube().playlistItems().list(**kwargs).execute()
        for row in page.get("items", []):
            row_snippet = row.get("snippet", {}) or {}
            row_details = row.get("contentDetails", {}) or {}
            video_id = str(
                row_details.get("videoId")
                or (row_snippet.get("resourceId", {}) or {}).get("videoId")
                or ""
            ).strip()
            if not video_id:
                continue
            if video_id in previous_ids or video_id in selected_ids:
                duplicate_ids.append(video_id)
                continue
            selected_ids.add(video_id)
            selected_rows.append((video_id, row))
            if len(selected_rows) >= limit:
                break
        next_upstream = str(page.get("nextPageToken") or "").strip() or None
        if len(selected_rows) >= limit or not next_upstream:
            break

    ordered_ids = [video_id for video_id, _ in selected_rows]
    rows_by_id = {video_id: row for video_id, row in selected_rows}
    details_by_id: dict[str, dict[str, Any]] = {}
    if ordered_ids:
        response = service._youtube().videos().list(
            part="snippet,contentDetails,statistics,status",
            id=",".join(ordered_ids),
        ).execute()
        details_by_id = {str(item.get("id", "")): item for item in response.get("items", [])}

    videos: list[dict[str, Any]] = []
    for video_id in ordered_ids:
        item = details_by_id.get(video_id, {})
        video_snippet = item.get("snippet", {}) or {}
        video_content = item.get("contentDetails", {}) or {}
        video_statistics = item.get("statistics", {}) or {}
        status = item.get("status", {}) or {}
        if str(video_snippet.get("channelId", channel_id)) != channel_id:
            continue
        fallback_snippet = rows_by_id[video_id].get("snippet", {}) or {}
        videos.append(
            {
                "video_id": video_id,
                "title": str(video_snippet.get("title", fallback_snippet.get("title", ""))),
                "published_at": video_snippet.get("publishedAt"),
                "duration": video_content.get("duration"),
                "privacy_status": status.get("privacyStatus"),
                "view_count": int(video_statistics.get("viewCount", 0) or 0),
                "like_count": int(video_statistics.get("likeCount", 0) or 0),
                "comment_count": int(video_statistics.get("commentCount", 0) or 0),
                "thumbnail": (
                    (video_snippet.get("thumbnails", {}) or {}).get("high")
                    or (video_snippet.get("thumbnails", {}) or {}).get("default")
                    or {}
                ).get("url"),
            }
        )

    public_count = int(statistics.get("videoCount", 0) or 0)
    non_public_returned = sum(1 for row in videos if row.get("privacy_status") in {"private", "unlisted"})
    next_token = (
        _encode_cursor(
            upstream_token=next_upstream,
            previous_video_ids=[row["video_id"] for row in videos],
            uploads_playlist_id=uploads,
        )
        if next_upstream
        else None
    )
    return {
        "channel_id": channel_id,
        "channel_title": str(snippet.get("title", "")),
        "videos": videos,
        "next_page_token": next_token,
        "prev_page_token": None,
        "returned_count": len(videos),
        "deduplicated_boundary_count": len(duplicate_ids),
        "deduplicated_video_ids": list(dict.fromkeys(duplicate_ids)),
        "pagination_mode": "stable_forward_deduplicated",
        "inventory_scope": "owner_accessible_uploads_playlist",
        "public_video_count": public_count,
        "public_video_count_scope": "public_only_even_for_channel_owner",
        "non_public_returned_count": non_public_returned,
        "count_explanation": (
            "channels.statistics.videoCount counts public videos only, while list_channel_videos reads the authenticated "
            "channel uploads playlist and can therefore include owner-accessible unlisted/private uploads."
        ),
    }


def extend_server(server):
    # Preserve the existing tool name and exact input schema. Only the read
    # implementation is hardened, so V1/V2 snapshots remain compatible.
    server.remove_tool("list_channel_videos")

    @server.tool(
        name="list_channel_videos",
        title="Listar vídeos do canal",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
        ),
    )
    def list_channel_videos(max_results: int = 50, page_token: str | None = None) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("videos_list", limit=90)
            return base.success_response(
                _list_channel_videos_stable(
                    management._service(),
                    max_results=max_results,
                    page_token=page_token,
                )
            )

        return base._structured("list_channel_videos", action)

    return server
