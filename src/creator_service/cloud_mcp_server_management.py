from __future__ import annotations

import os
from typing import Any

from mcp.types import ToolAnnotations

from . import cloud_mcp_server as base
from .cloud_mcp_server_video import _owned_video_details
from .security import signer_from_env
from .verified_advanced_service import VerifiedAdvancedSafeCreatorService
from .video_transcript import get_video_transcript_data


def _service() -> VerifiedAdvancedSafeCreatorService:
    resolver = base._resolver()
    context = resolver.resolve(base._tenant_id())
    return VerifiedAdvancedSafeCreatorService(context)


def _consume_token(*, token: str, payload: dict[str, Any], action: str, subject: str) -> None:
    subject = str(subject or "").strip()
    if not subject:
        raise base.tool_error("invalid_request", "The signed action subject is missing.")
    parsed = signer_from_env().verify(token, action=action, subject=subject, payload=payload)
    if not base._ops_store().consume_write_token(
        token,
        tenant_id=base._tenant_id(),
        action=action,
        subject=subject,
        expires_at=parsed.expires_at,
    ):
        raise base.tool_error("approval_replayed")


def _owned_playlist(service: VerifiedAdvancedSafeCreatorService, playlist_id: str) -> dict[str, Any]:
    playlist_id = str(playlist_id or "").strip()
    if not playlist_id:
        raise base.tool_error("invalid_request", "playlist_id is required.")
    response = service._youtube().playlists().list(
        part="snippet,status,contentDetails",
        id=playlist_id,
        maxResults=1,
    ).execute()
    items = response.get("items", [])
    if not items:
        raise base.tool_error("playlist_not_found", "The requested playlist was not found.")
    item = dict(items[0])
    snippet = item.get("snippet", {}) or {}
    owner = str(snippet.get("channelId", "")).strip()
    if owner != service._authorized_channel_id():
        raise base.tool_error("playlist_not_owned", "The requested playlist does not belong to the authorized channel.")
    return item


def _playlist_snapshot(service: VerifiedAdvancedSafeCreatorService, playlist_id: str) -> dict[str, Any]:
    item = _owned_playlist(service, playlist_id)
    snippet = item.get("snippet", {}) or {}
    status = item.get("status", {}) or {}
    return {
        "playlist_id": str(item.get("id", playlist_id)),
        "channel_id": str(snippet.get("channelId", "")),
        "title": str(snippet.get("title", "")),
        "description": str(snippet.get("description", "")),
        "privacy_status": str(status.get("privacyStatus", "private")),
    }


def _normalize_playlist_metadata(
    current: dict[str, Any],
    *,
    title: str | None,
    description: str | None,
    privacy_status: str | None,
) -> dict[str, Any]:
    final_title = current["title"] if title is None else " ".join(str(title).strip().split())
    final_description = current["description"] if description is None else str(description).strip()
    final_privacy = current["privacy_status"] if privacy_status is None else str(privacy_status).strip().lower()
    if not final_title:
        raise base.tool_error("invalid_request", "Playlist title cannot be empty.")
    if len(final_title) > 150:
        raise base.tool_error("invalid_request", "Playlist title exceeds 150 characters.")
    if len(final_description) > 5000:
        raise base.tool_error("invalid_request", "Playlist description exceeds 5,000 characters.")
    if final_privacy not in {"public", "unlisted", "private"}:
        raise base.tool_error("invalid_request", "privacy_status must be public, unlisted, or private.")
    return {
        "playlist_id": current["playlist_id"],
        "channel_id": current["channel_id"],
        "title": final_title,
        "description": final_description,
        "privacy_status": final_privacy,
    }


def _playlist_membership(service: VerifiedAdvancedSafeCreatorService, playlist_id: str) -> list[dict[str, Any]]:
    _owned_playlist(service, playlist_id)
    rows: list[dict[str, Any]] = []
    page_token = None
    while True:
        kwargs: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        response = service._youtube().playlistItems().list(**kwargs).execute()
        for item in response.get("items", []):
            snippet = item.get("snippet", {}) or {}
            content = item.get("contentDetails", {}) or {}
            video_id = str(content.get("videoId") or (snippet.get("resourceId", {}) or {}).get("videoId") or "")
            rows.append(
                {
                    "playlist_item_id": str(item.get("id", "")),
                    "video_id": video_id,
                    "position": int(snippet.get("position", 0) or 0),
                }
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
        if len(rows) >= 5000:
            raise base.tool_error("invalid_request", "Playlist is too large for a safe atomic membership edit.")
    rows.sort(key=lambda row: (row["position"], row["playlist_item_id"]))
    return rows


def _playlist_details(
    service: VerifiedAdvancedSafeCreatorService,
    playlist_id: str,
    *,
    max_results: int = 50,
    page_token: str | None = None,
) -> dict[str, Any]:
    item = _owned_playlist(service, playlist_id)
    snippet = item.get("snippet", {}) or {}
    status = item.get("status", {}) or {}
    content_details = item.get("contentDetails", {}) or {}
    limit = max(1, min(50, int(max_results)))
    kwargs: dict[str, Any] = {
        "part": "snippet,contentDetails",
        "playlistId": playlist_id,
        "maxResults": limit,
    }
    if page_token:
        kwargs["pageToken"] = page_token
    page = service._youtube().playlistItems().list(**kwargs).execute()
    videos = []
    for row in page.get("items", []):
        row_snippet = row.get("snippet", {}) or {}
        row_content = row.get("contentDetails", {}) or {}
        videos.append(
            {
                "playlist_item_id": str(row.get("id", "")),
                "video_id": str(row_content.get("videoId") or (row_snippet.get("resourceId", {}) or {}).get("videoId") or ""),
                "title": str(row_snippet.get("title", "")),
                "position": int(row_snippet.get("position", 0) or 0),
                "published_at": row_snippet.get("publishedAt"),
                "video_published_at": row_content.get("videoPublishedAt"),
                "thumbnails": dict(row_snippet.get("thumbnails", {}) or {}),
            }
        )
    return {
        "playlist_id": playlist_id,
        "channel_id": str(snippet.get("channelId", "")),
        "title": str(snippet.get("title", "")),
        "description": str(snippet.get("description", "")),
        "privacy_status": str(status.get("privacyStatus", "private")),
        "item_count": int(content_details.get("itemCount", 0) or 0),
        "items": videos,
        "next_page_token": page.get("nextPageToken"),
        "prev_page_token": page.get("prevPageToken"),
    }


def _list_channel_videos(
    service: VerifiedAdvancedSafeCreatorService,
    *,
    max_results: int = 50,
    page_token: str | None = None,
) -> dict[str, Any]:
    channel = service._youtube().channels().list(part="id,snippet,contentDetails", mine=True).execute().get("items", [])
    if not channel:
        raise base.tool_error("channel_not_found")
    channel_item = channel[0]
    channel_id = str(channel_item.get("id", ""))
    uploads = str((((channel_item.get("contentDetails", {}) or {}).get("relatedPlaylists", {}) or {}).get("uploads", "")))
    if not uploads:
        raise base.tool_error("internal_error", "The authorized channel has no uploads playlist.")
    limit = max(1, min(50, int(max_results)))
    kwargs: dict[str, Any] = {
        "part": "snippet,contentDetails",
        "playlistId": uploads,
        "maxResults": limit,
    }
    if page_token:
        kwargs["pageToken"] = page_token
    page = service._youtube().playlistItems().list(**kwargs).execute()
    ordered_ids = []
    playlist_rows: dict[str, dict[str, Any]] = {}
    for row in page.get("items", []):
        snippet = row.get("snippet", {}) or {}
        details = row.get("contentDetails", {}) or {}
        video_id = str(details.get("videoId") or (snippet.get("resourceId", {}) or {}).get("videoId") or "")
        if video_id:
            ordered_ids.append(video_id)
            playlist_rows[video_id] = row
    details_by_id: dict[str, dict[str, Any]] = {}
    if ordered_ids:
        response = service._youtube().videos().list(
            part="snippet,contentDetails,statistics,status",
            id=",".join(ordered_ids),
        ).execute()
        details_by_id = {str(item.get("id", "")): item for item in response.get("items", [])}
    videos = []
    for video_id in ordered_ids:
        item = details_by_id.get(video_id, {})
        snippet = item.get("snippet", {}) or {}
        content = item.get("contentDetails", {}) or {}
        statistics = item.get("statistics", {}) or {}
        status = item.get("status", {}) or {}
        if str(snippet.get("channelId", channel_id)) != channel_id:
            continue
        videos.append(
            {
                "video_id": video_id,
                "title": str(snippet.get("title", playlist_rows[video_id].get("snippet", {}).get("title", ""))),
                "published_at": snippet.get("publishedAt"),
                "duration": content.get("duration"),
                "privacy_status": status.get("privacyStatus"),
                "view_count": int(statistics.get("viewCount", 0) or 0),
                "like_count": int(statistics.get("likeCount", 0) or 0),
                "comment_count": int(statistics.get("commentCount", 0) or 0),
                "thumbnail": ((snippet.get("thumbnails", {}) or {}).get("high") or (snippet.get("thumbnails", {}) or {}).get("default") or {}).get("url"),
            }
        )
    return {
        "channel_id": channel_id,
        "channel_title": str((channel_item.get("snippet", {}) or {}).get("title", "")),
        "videos": videos,
        "next_page_token": page.get("nextPageToken"),
        "prev_page_token": page.get("prevPageToken"),
    }


def _caption_belongs_to_video(service: VerifiedAdvancedSafeCreatorService, caption_id: str, video_id: str) -> bool:
    response = service._youtube().captions().list(part="snippet", videoId=video_id).execute()
    return any(str(item.get("id", "")) == caption_id for item in response.get("items", []))


def create_server():
    # The production surface uses one verified service for every legacy base
    # metadata write and every advanced operation below.
    base._service = _service
    server = base.create_server()

    @server.tool(
        title="Listar vídeos do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def list_channel_videos(max_results: int = 50, page_token: str | None = None) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("videos_list", limit=90)
            return base.success_response(_list_channel_videos(_service(), max_results=max_results, page_token=page_token))
        return base._structured("list_channel_videos", action)

    @server.tool(
        title="Obter detalhes de um vídeo do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_video_details(video_id: str) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("video_details", limit=120)
            return base.success_response(_owned_video_details(_service(), video_id))
        return base._structured("get_video_details", action)

    @server.tool(
        title="Obter transcrição completa de um vídeo do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_video_transcript(
        video_id: str,
        language: str | None = None,
        include_segments: bool = True,
        segment_offset: int = 0,
        segment_limit: int = 500,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("video_transcript", limit=60)
            service = _service()
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

    @server.tool(
        title="Listar categorias de vídeo do YouTube",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False, idempotent_hint=True),
    )
    def list_video_categories(region_code: str = "BR") -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("categories", limit=60)
            return base.success_response(_service().list_video_categories(region_code))
        return base._structured("list_video_categories", action)

    @server.tool(
        title="Preparar prévia completa de metadados do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_video_metadata_update_advanced(
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        category_id: str | None = None,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("write_preview", limit=30)
            result = _service().preview_video_metadata_update(
                video_id=video_id,
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
            )
            base._audit("mcp_video_metadata_advanced_preview", "success", {"video_id": video_id, "changed": result.get("changed", {})})
            return base.success_response(result)
        return base._structured("preview_video_metadata_update_advanced", action)

    def _apply_video(approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool) -> dict[str, Any]:
        base._require_scope(base.WRITE_SCOPE)
        base._limit("write_apply", limit=15)
        if user_confirmed is not True:
            raise base.tool_error("confirmation_required")
        video_id = base._consume_signed_write(token=approval_token, payload=approval_payload, action="update_video_metadata")
        result = _service().apply_video_metadata_update(approval_payload=approval_payload, approval_token=approval_token)
        base._audit("mcp_video_metadata_advanced_apply", "success", {"video_id": video_id, "changed_fields": result.get("changed_fields", [])})
        return base.success_response(result)

    @server.tool(
        title="Aplicar metadados completos aprovados no vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_update_advanced(
        approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        return base._structured(
            "apply_video_metadata_update_advanced",
            lambda: _apply_video(approval_payload, approval_token, user_confirmed),
        )

    def _rollback_video(rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool) -> dict[str, Any]:
        base._require_scope(base.WRITE_SCOPE)
        base._limit("write_rollback", limit=10)
        if user_confirmed is not True:
            raise base.tool_error("confirmation_required")
        video_id = base._consume_signed_write(token=rollback_token, payload=rollback_payload, action="rollback_video_metadata")
        result = _service().apply_video_metadata_rollback(rollback_payload=rollback_payload, rollback_token=rollback_token)
        base._audit("mcp_video_metadata_advanced_rollback", "success", {"video_id": video_id, "changed_fields": result.get("changed_fields", [])})
        return base.success_response(result)

    @server.tool(
        title="Restaurar metadados completos anteriores do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_rollback_advanced(
        rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        return base._structured(
            "apply_video_metadata_rollback_advanced",
            lambda: _rollback_video(rollback_payload, rollback_token, user_confirmed),
        )

    @server.tool(
        title="Listar legendas do vídeo",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False, idempotent_hint=True),
    )
    def list_video_captions(video_id: str) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("captions_read", limit=60)
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            return base.success_response(service.list_video_captions(video_id))
        return base._structured("list_video_captions", action)

    @server.tool(
        title="Preparar prévia de envio de legenda",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_caption_upload(
        video_id: str,
        language: str,
        content: str,
        name: str | None = None,
        caption_format: str = "srt",
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("caption_preview", limit=20)
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            result = service.preview_caption_upload(
                video_id=video_id,
                language=language,
                content=content,
                name=name,
                caption_format=caption_format,
            )
            base._audit("mcp_caption_preview", "success", {"video_id": video_id, "language": language})
            return base.success_response(result)
        return base._structured("preview_caption_upload", action)

    @server.tool(
        title="Enviar legenda aprovada ao vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_caption_upload(
        approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("caption_apply", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            video_id = str(approval_payload.get("video_id", "")).strip()
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            _consume_token(token=approval_token, payload=approval_payload, action="upload_video_caption", subject=video_id)
            result = service.apply_caption_upload(approval_payload=approval_payload, approval_token=approval_token)
            base._audit("mcp_caption_upload", "success", {"video_id": video_id, "caption_id": result.get("caption_id")})
            return base.success_response(result)
        return base._structured("apply_caption_upload", action)

    @server.tool(
        title="Excluir a legenda criada usando rollback aprovado",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_caption_delete_rollback(
        rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("caption_rollback", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            video_id = str(rollback_payload.get("video_id", "")).strip()
            caption_id = str(rollback_payload.get("caption_id", "")).strip()
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            if not _caption_belongs_to_video(service, caption_id, video_id):
                raise base.tool_error("external_change_detected", "The caption no longer matches the rollback state.")
            _consume_token(token=rollback_token, payload=rollback_payload, action="delete_uploaded_caption", subject=caption_id)
            result = service.apply_caption_delete(rollback_payload=rollback_payload, rollback_token=rollback_token)
            base._audit("mcp_caption_delete_rollback", "success", {"video_id": video_id, "caption_id": caption_id})
            return base.success_response(result)
        return base._structured("apply_caption_delete_rollback", action)

    @server.tool(
        title="Listar playlists do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def list_playlists(max_results: int = 50, page_token: str | None = None) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("playlist_read", limit=90)
            limit = max(1, min(50, int(max_results)))
            kwargs: dict[str, Any] = {"part": "snippet,status,contentDetails", "mine": True, "maxResults": limit}
            if page_token:
                kwargs["pageToken"] = page_token
            response = _service()._youtube().playlists().list(**kwargs).execute()
            rows = []
            for item in response.get("items", []):
                snippet = item.get("snippet", {}) or {}
                rows.append({
                    "playlist_id": str(item.get("id", "")),
                    "title": str(snippet.get("title", "")),
                    "description": str(snippet.get("description", "")),
                    "privacy_status": str((item.get("status", {}) or {}).get("privacyStatus", "private")),
                    "item_count": int((item.get("contentDetails", {}) or {}).get("itemCount", 0) or 0),
                    "thumbnails": dict(snippet.get("thumbnails", {}) or {}),
                })
            return base.success_response({"playlists": rows, "next_page_token": response.get("nextPageToken"), "prev_page_token": response.get("prevPageToken")})
        return base._structured("list_playlists", action)

    @server.tool(
        title="Obter detalhes e vídeos de uma playlist",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_playlist_details(
        playlist_id: str, max_results: int = 50, page_token: str | None = None
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("playlist_read", limit=90)
            return base.success_response(_playlist_details(_service(), playlist_id, max_results=max_results, page_token=page_token))
        return base._structured("get_playlist_details", action)

    @server.tool(
        title="Preparar prévia de edição de metadados da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_playlist_metadata_update(
        playlist_id: str,
        title: str | None = None,
        description: str | None = None,
        privacy_status: str | None = None,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_preview", limit=30)
            if title is None and description is None and privacy_status is None:
                raise base.tool_error("invalid_request", "At least one playlist field must be supplied.")
            service = _service()
            current = _playlist_snapshot(service, playlist_id)
            proposed = _normalize_playlist_metadata(current, title=title, description=description, privacy_status=privacy_status)
            payload = {"baseline_digest": signer_from_env().payload_digest(current), "proposed": proposed}
            token = signer_from_env().issue("update_playlist_metadata", playlist_id, payload)
            changed = {field: current[field] != proposed[field] for field in ("title", "description", "privacy_status")}
            return base.success_response({
                "playlist_id": playlist_id,
                "current": current,
                "proposed": proposed,
                "changed": changed,
                "approval_payload": payload,
                "approval_token": token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
            })
        return base._structured("preview_playlist_metadata_update", action)

    @server.tool(
        title="Aplicar edição aprovada da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_metadata_update(
        approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_apply", limit=15)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(approval_payload.get("proposed", {}) or {})
            playlist_id = str(proposed.get("playlist_id", "")).strip()
            _consume_token(token=approval_token, payload=approval_payload, action="update_playlist_metadata", subject=playlist_id)
            service = _service()
            current = _playlist_snapshot(service, playlist_id)
            if signer_from_env().payload_digest(current) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            normalized = _normalize_playlist_metadata(
                current,
                title=proposed.get("title"),
                description=proposed.get("description"),
                privacy_status=proposed.get("privacy_status"),
            )
            response = service._youtube().playlists().update(
                part="snippet,status",
                body={
                    "id": playlist_id,
                    "snippet": {"title": normalized["title"], "description": normalized["description"]},
                    "status": {"privacyStatus": normalized["privacy_status"]},
                },
            ).execute()
            observed = _playlist_snapshot(service, playlist_id)
            if any(observed[field] != normalized[field] for field in ("title", "description", "privacy_status")):
                raise base.tool_error("youtube_api_error", "YouTube did not persist the approved playlist metadata exactly.")
            rollback_proposed = dict(current)
            rollback_payload = {"baseline_digest": signer_from_env().payload_digest(observed), "proposed": rollback_proposed}
            rollback_token = signer_from_env().issue("rollback_playlist_metadata", playlist_id, rollback_payload)
            base._audit("mcp_playlist_metadata_apply", "success", {"playlist_id": playlist_id})
            return base.success_response({
                "playlist_id": playlist_id,
                "playlist": response,
                "persisted_verified": True,
                "rollback_preview": {
                    "rollback_payload": rollback_payload,
                    "rollback_token": rollback_token,
                    "restore": rollback_proposed,
                    "expires_in_seconds": 900,
                    "requires_explicit_user_confirmation": True,
                },
            })
        return base._structured("apply_playlist_metadata_update", action)

    @server.tool(
        title="Restaurar metadados anteriores da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_metadata_rollback(
        rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_rollback", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(rollback_payload.get("proposed", {}) or {})
            playlist_id = str(proposed.get("playlist_id", "")).strip()
            _consume_token(token=rollback_token, payload=rollback_payload, action="rollback_playlist_metadata", subject=playlist_id)
            service = _service()
            current = _playlist_snapshot(service, playlist_id)
            if signer_from_env().payload_digest(current) != str(rollback_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            normalized = _normalize_playlist_metadata(
                current,
                title=proposed.get("title"),
                description=proposed.get("description"),
                privacy_status=proposed.get("privacy_status"),
            )
            service._youtube().playlists().update(
                part="snippet,status",
                body={
                    "id": playlist_id,
                    "snippet": {"title": normalized["title"], "description": normalized["description"]},
                    "status": {"privacyStatus": normalized["privacy_status"]},
                },
            ).execute()
            observed = _playlist_snapshot(service, playlist_id)
            if any(observed[field] != normalized[field] for field in ("title", "description", "privacy_status")):
                raise base.tool_error("youtube_api_error", "YouTube did not persist the playlist rollback exactly.")
            base._audit("mcp_playlist_metadata_rollback", "success", {"playlist_id": playlist_id})
            return base.success_response({"playlist_id": playlist_id, "rolled_back": True, "persisted_verified": True, "current": observed})
        return base._structured("apply_playlist_metadata_rollback", action)

    @server.tool(
        title="Preparar prévia para adicionar vídeo à playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_playlist_item_add(playlist_id: str, video_id: str, position: int | None = None) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_preview", limit=30)
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            membership = _playlist_membership(service, playlist_id)
            existing = [row for row in membership if row["video_id"] == video_id]
            if existing:
                return base.success_response({"playlist_id": playlist_id, "video_id": video_id, "already_present": True, "requires_explicit_user_confirmation": False})
            final_position = None if position is None else max(0, int(position))
            proposed = {"playlist_id": playlist_id, "video_id": video_id, "position": final_position}
            payload = {"baseline_digest": signer_from_env().payload_digest(membership), "proposed": proposed}
            token = signer_from_env().issue("add_playlist_item", playlist_id, payload)
            return base.success_response({
                "playlist_id": playlist_id,
                "video_id": video_id,
                "already_present": False,
                "approval_payload": payload,
                "approval_token": token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
            })
        return base._structured("preview_playlist_item_add", action)

    @server.tool(
        title="Adicionar vídeo aprovado à playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_item_add(
        approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_apply", limit=15)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(approval_payload.get("proposed", {}) or {})
            playlist_id = str(proposed.get("playlist_id", "")).strip()
            video_id = str(proposed.get("video_id", "")).strip()
            _consume_token(token=approval_token, payload=approval_payload, action="add_playlist_item", subject=playlist_id)
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            before = _playlist_membership(service, playlist_id)
            if signer_from_env().payload_digest(before) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            snippet: dict[str, Any] = {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
            if proposed.get("position") is not None:
                snippet["position"] = max(0, int(proposed["position"]))
            response = service._youtube().playlistItems().insert(part="snippet", body={"snippet": snippet}).execute()
            item_id = str(response.get("id", "")).strip()
            after = _playlist_membership(service, playlist_id)
            if not item_id or not any(row["playlist_item_id"] == item_id and row["video_id"] == video_id for row in after):
                raise base.tool_error("youtube_api_error", "YouTube did not confirm the playlist item insertion.")
            rollback_payload = {
                "baseline_digest": signer_from_env().payload_digest(after),
                "proposed": {"playlist_id": playlist_id, "playlist_item_id": item_id, "video_id": video_id},
            }
            rollback_token = signer_from_env().issue("rollback_add_playlist_item", item_id, rollback_payload)
            base._audit("mcp_playlist_item_add", "success", {"playlist_id": playlist_id, "video_id": video_id, "playlist_item_id": item_id})
            return base.success_response({
                "playlist_id": playlist_id,
                "video_id": video_id,
                "playlist_item_id": item_id,
                "persisted_verified": True,
                "rollback_preview": {
                    "rollback_payload": rollback_payload,
                    "rollback_token": rollback_token,
                    "expires_in_seconds": 900,
                    "requires_explicit_user_confirmation": True,
                },
            })
        return base._structured("apply_playlist_item_add", action)

    @server.tool(
        title="Desfazer adição de vídeo à playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_item_add_rollback(
        rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_rollback", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(rollback_payload.get("proposed", {}) or {})
            playlist_id = str(proposed.get("playlist_id", "")).strip()
            item_id = str(proposed.get("playlist_item_id", "")).strip()
            _consume_token(token=rollback_token, payload=rollback_payload, action="rollback_add_playlist_item", subject=item_id)
            service = _service()
            before = _playlist_membership(service, playlist_id)
            if signer_from_env().payload_digest(before) != str(rollback_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            if not any(row["playlist_item_id"] == item_id for row in before):
                raise base.tool_error("external_change_detected", "The playlist item no longer exists in the expected state.")
            service._youtube().playlistItems().delete(id=item_id).execute()
            after = _playlist_membership(service, playlist_id)
            if any(row["playlist_item_id"] == item_id for row in after):
                raise base.tool_error("youtube_api_error", "YouTube did not confirm playlist item rollback.")
            base._audit("mcp_playlist_item_add_rollback", "success", {"playlist_id": playlist_id, "playlist_item_id": item_id})
            return base.success_response({"playlist_id": playlist_id, "playlist_item_id": item_id, "rolled_back": True, "persisted_verified": True})
        return base._structured("apply_playlist_item_add_rollback", action)

    @server.tool(
        title="Preparar prévia para remover vídeo da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_playlist_item_remove(playlist_id: str, video_id: str) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_preview", limit=30)
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            membership = _playlist_membership(service, playlist_id)
            matches = [row for row in membership if row["video_id"] == video_id]
            if not matches:
                return base.success_response({"playlist_id": playlist_id, "video_id": video_id, "already_absent": True, "requires_explicit_user_confirmation": False})
            if len(matches) != 1:
                raise base.tool_error("invalid_request", "The playlist contains this video more than once; remove by playlist item ID is required.")
            target = matches[0]
            proposed = {"playlist_id": playlist_id, **target}
            payload = {"baseline_digest": signer_from_env().payload_digest(membership), "proposed": proposed}
            token = signer_from_env().issue("remove_playlist_item", target["playlist_item_id"], payload)
            return base.success_response({
                "playlist_id": playlist_id,
                "video_id": video_id,
                "already_absent": False,
                "target": target,
                "approval_payload": payload,
                "approval_token": token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
            })
        return base._structured("preview_playlist_item_remove", action)

    @server.tool(
        title="Remover vídeo aprovado da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_item_remove(
        approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_apply", limit=15)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(approval_payload.get("proposed", {}) or {})
            playlist_id = str(proposed.get("playlist_id", "")).strip()
            item_id = str(proposed.get("playlist_item_id", "")).strip()
            video_id = str(proposed.get("video_id", "")).strip()
            _consume_token(token=approval_token, payload=approval_payload, action="remove_playlist_item", subject=item_id)
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            before = _playlist_membership(service, playlist_id)
            if signer_from_env().payload_digest(before) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            if not any(row["playlist_item_id"] == item_id and row["video_id"] == video_id for row in before):
                raise base.tool_error("external_change_detected")
            service._youtube().playlistItems().delete(id=item_id).execute()
            after = _playlist_membership(service, playlist_id)
            if any(row["playlist_item_id"] == item_id for row in after):
                raise base.tool_error("youtube_api_error", "YouTube did not confirm playlist item removal.")
            rollback_payload = {
                "baseline_digest": signer_from_env().payload_digest(after),
                "proposed": {
                    "playlist_id": playlist_id,
                    "video_id": video_id,
                    "position": int(proposed.get("position", 0) or 0),
                },
            }
            rollback_token = signer_from_env().issue("rollback_remove_playlist_item", playlist_id, rollback_payload)
            base._audit("mcp_playlist_item_remove", "success", {"playlist_id": playlist_id, "video_id": video_id, "playlist_item_id": item_id})
            return base.success_response({
                "playlist_id": playlist_id,
                "video_id": video_id,
                "playlist_item_id": item_id,
                "persisted_verified": True,
                "rollback_preview": {
                    "rollback_payload": rollback_payload,
                    "rollback_token": rollback_token,
                    "expires_in_seconds": 900,
                    "requires_explicit_user_confirmation": True,
                },
            })
        return base._structured("apply_playlist_item_remove", action)

    @server.tool(
        title="Desfazer remoção de vídeo da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_item_remove_rollback(
        rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_rollback", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(rollback_payload.get("proposed", {}) or {})
            playlist_id = str(proposed.get("playlist_id", "")).strip()
            video_id = str(proposed.get("video_id", "")).strip()
            _consume_token(token=rollback_token, payload=rollback_payload, action="rollback_remove_playlist_item", subject=playlist_id)
            service = _service()
            service._owned_video_item(video_id, part="snippet")
            before = _playlist_membership(service, playlist_id)
            if signer_from_env().payload_digest(before) != str(rollback_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            response = service._youtube().playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        "position": max(0, int(proposed.get("position", 0) or 0)),
                    }
                },
            ).execute()
            new_item_id = str(response.get("id", "")).strip()
            after = _playlist_membership(service, playlist_id)
            if not new_item_id or not any(row["playlist_item_id"] == new_item_id and row["video_id"] == video_id for row in after):
                raise base.tool_error("youtube_api_error", "YouTube did not confirm playlist removal rollback.")
            base._audit("mcp_playlist_item_remove_rollback", "success", {"playlist_id": playlist_id, "video_id": video_id, "playlist_item_id": new_item_id})
            return base.success_response({"playlist_id": playlist_id, "video_id": video_id, "playlist_item_id": new_item_id, "rolled_back": True, "persisted_verified": True})
        return base._structured("apply_playlist_item_remove_rollback", action)

    return server


def run() -> None:
    server = create_server()
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
