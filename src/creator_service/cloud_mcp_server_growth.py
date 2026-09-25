from __future__ import annotations

import re
from typing import Any

from mcp.types import ToolAnnotations

from . import cloud_mcp_server as base
from . import cloud_mcp_server_management as management
from .security import signer_from_env


_PLAYLIST_TITLE_MAX = 150
_PLAYLIST_DESCRIPTION_MAX = 5000
_CHANNEL_DESCRIPTION_MAX = 1000
_CHANNEL_KEYWORDS_MAX = 500
_PRIVACY = {"public", "unlisted", "private"}
_GENERIC_PLAYLIST_TITLES = {
    "music",
    "songs",
    "videos",
    "playlist",
    "my playlist",
    "favorites",
    "favourites",
    "country music",
}


def _service():
    return management._service()


def _normalize_title(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_description(value: str) -> str:
    return str(value or "").strip()


def _normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_keywords(values: list[str] | None) -> tuple[list[str], str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        token = " ".join(str(value or "").replace('"', " ").split())
        if not token:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(token)
    serialized = " ".join(f'"{item}"' if " " in item else item for item in cleaned)
    if len(serialized) > _CHANNEL_KEYWORDS_MAX:
        raise base.tool_error("invalid_request", "Channel keywords exceed the YouTube 500-character limit.")
    return cleaned, serialized


def _parse_channel_keywords(value: str | None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    parts = re.findall(r'"([^"]+)"|(\S+)', text)
    values = [a or b for a, b in parts]
    return [" ".join(value.split()) for value in values if value.strip()]


def _channel_snapshot(service) -> dict[str, Any]:
    rows = service._youtube().channels().list(
        part="id,snippet,brandingSettings,contentDetails",
        mine=True,
        maxResults=1,
    ).execute().get("items", [])
    if not rows:
        raise base.tool_error("channel_not_found")
    item = rows[0]
    channel_id = str(item.get("id", "")).strip()
    if channel_id != service._authorized_channel_id():
        raise base.tool_error("channel_not_owned")
    snippet = item.get("snippet", {}) or {}
    branding = (item.get("brandingSettings", {}) or {}).get("channel", {}) or {}
    return {
        "channel_id": channel_id,
        "title": str(snippet.get("title", "")),
        "description": str(branding.get("description", snippet.get("description", "")) or ""),
        "keywords": _parse_channel_keywords(branding.get("keywords")),
        "keywords_serialized": str(branding.get("keywords", "") or ""),
        "country": str(branding.get("country", snippet.get("country", "")) or ""),
        "default_language": str(branding.get("defaultLanguage", "") or ""),
        "unsubscribed_trailer": str(branding.get("unsubscribedTrailer", "") or ""),
        "tracking_analytics_account_id": str(branding.get("trackingAnalyticsAccountId", "") or ""),
    }


def _channel_update_body(current: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    channel: dict[str, Any] = {}
    values = {
        "description": proposed["description"],
        "keywords": proposed["keywords_serialized"],
        "country": proposed["country"],
        "defaultLanguage": proposed["default_language"],
        "unsubscribedTrailer": proposed["unsubscribed_trailer"],
        "trackingAnalyticsAccountId": proposed["tracking_analytics_account_id"],
    }
    # channels.update replaces mutable properties omitted from brandingSettings,
    # so preserve every supported value we currently know instead of sending a
    # partial object that could silently erase unrelated settings.
    for key, value in values.items():
        if value not in (None, ""):
            channel[key] = value
    return {"id": current["channel_id"], "brandingSettings": {"channel": channel}}


def _normalize_channel_profile(
    current: dict[str, Any],
    *,
    description: str | None,
    keywords: list[str] | None,
    country: str | None,
    default_language: str | None,
    unsubscribed_trailer: str | None,
) -> dict[str, Any]:
    final_description = current["description"] if description is None else _normalize_description(description)
    if len(final_description) > _CHANNEL_DESCRIPTION_MAX:
        raise base.tool_error("invalid_request", "Channel description exceeds the YouTube 1,000-character limit.")
    if keywords is None:
        final_keywords = list(current["keywords"])
        serialized = str(current["keywords_serialized"])
    else:
        final_keywords, serialized = _normalize_keywords(keywords)
    final_country = current["country"] if country is None else str(country).strip().upper()
    if final_country and (len(final_country) != 2 or not final_country.isalpha()):
        raise base.tool_error("invalid_request", "country must be an ISO 3166-1 alpha-2 code such as BR or US.")
    final_language = current["default_language"] if default_language is None else (_normalize_language(default_language) or "")
    final_trailer = current["unsubscribed_trailer"] if unsubscribed_trailer is None else str(unsubscribed_trailer).strip()
    return {
        **current,
        "description": final_description,
        "keywords": final_keywords,
        "keywords_serialized": serialized,
        "country": final_country,
        "default_language": final_language,
        "unsubscribed_trailer": final_trailer,
    }


def _channel_seo_audit(service) -> dict[str, Any]:
    current = _channel_snapshot(service)
    issues: list[dict[str, Any]] = []
    desc_len = len(current["description"])
    keyword_count = len(current["keywords"])
    if not current["description"]:
        issues.append({"code": "missing_description", "severity": "high"})
    elif desc_len < 180:
        issues.append({"code": "thin_description", "severity": "medium", "description_length": desc_len})
    if keyword_count == 0:
        issues.append({"code": "missing_channel_keywords", "severity": "medium"})
    elif keyword_count < 5:
        issues.append({"code": "sparse_channel_keywords", "severity": "low", "keyword_count": keyword_count})
    return {
        "channel": current,
        "seo_context": {
            "description_length": desc_len,
            "keyword_count": keyword_count,
            "keyword_characters": len(current["keywords_serialized"]),
            "issues": issues,
            "writable_fields": ["description", "keywords", "country", "default_language", "unsubscribed_trailer"],
            "channel_category_supported_by_youtube_data_api": False,
            "channel_title_update_supported_by_youtube_data_api": False,
            "notes": [
                "Video category is managed per video, not as a writable channel category.",
                "Channel title changes are intentionally excluded because channels.update does not permit changing the title.",
            ],
        },
        "read_only": True,
    }


def _list_all_playlists(service) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    token = None
    while True:
        kwargs: dict[str, Any] = {"part": "snippet,status,contentDetails", "mine": True, "maxResults": 50}
        if token:
            kwargs["pageToken"] = token
        page = service._youtube().playlists().list(**kwargs).execute()
        for item in page.get("items", []):
            snippet = item.get("snippet", {}) or {}
            rows.append({
                "playlist_id": str(item.get("id", "")),
                "title": str(snippet.get("title", "")),
                "description": str(snippet.get("description", "")),
                "default_language": str(snippet.get("defaultLanguage", "") or ""),
                "privacy_status": str((item.get("status", {}) or {}).get("privacyStatus", "private")),
                "item_count": int((item.get("contentDetails", {}) or {}).get("itemCount", 0) or 0),
            })
        token = page.get("nextPageToken")
        if not token:
            break
        if len(rows) >= 1000:
            raise base.tool_error("invalid_request", "Channel has too many playlists for one safe organization audit.")
    return rows


def _related_playlist_ids(service) -> set[str]:
    rows = service._youtube().channels().list(part="contentDetails", mine=True, maxResults=1).execute().get("items", [])
    if not rows:
        return set()
    related = ((rows[0].get("contentDetails", {}) or {}).get("relatedPlaylists", {}) or {})
    return {str(value).strip() for value in related.values() if str(value).strip()}


def _playlist_inventory_digest_rows(service) -> list[dict[str, Any]]:
    return [
        {"playlist_id": row["playlist_id"], "title": row["title"], "item_count": row["item_count"]}
        for row in _list_all_playlists(service)
    ]


def _playlist_organization_audit(service, *, include_membership: bool = True) -> dict[str, Any]:
    playlists = _list_all_playlists(service)
    title_groups: dict[str, list[str]] = {}
    analyses: list[dict[str, Any]] = []
    membership_sets: dict[str, set[str]] = {}
    for row in playlists:
        normalized_title = _normalize_title(row["title"]).casefold()
        title_groups.setdefault(normalized_title, []).append(row["playlist_id"])
        issues: list[dict[str, Any]] = []
        if row["item_count"] == 0:
            issues.append({"code": "empty_playlist", "severity": "medium"})
        if not row["description"].strip():
            issues.append({"code": "missing_description", "severity": "medium"})
        elif len(row["description"].strip()) < 100:
            issues.append({"code": "thin_description", "severity": "low"})
        if normalized_title in _GENERIC_PLAYLIST_TITLES or len(normalized_title) < 8:
            issues.append({"code": "generic_or_weak_title", "severity": "medium"})
        if include_membership:
            membership = management._playlist_membership(service, row["playlist_id"])
            membership_sets[row["playlist_id"]] = {item["video_id"] for item in membership if item["video_id"]}
        analyses.append({**row, "issues": issues})

    duplicate_title_groups = [ids for title, ids in title_groups.items() if title and len(ids) > 1]
    overlaps: list[dict[str, Any]] = []
    if include_membership:
        ids = [row["playlist_id"] for row in playlists]
        for index, left_id in enumerate(ids):
            left = membership_sets.get(left_id, set())
            if not left:
                continue
            for right_id in ids[index + 1 :]:
                right = membership_sets.get(right_id, set())
                if not right:
                    continue
                shared = left & right
                union = left | right
                ratio = len(shared) / len(union) if union else 0.0
                if len(shared) >= 2 and ratio >= 0.6:
                    overlaps.append({
                        "playlist_ids": [left_id, right_id],
                        "shared_video_count": len(shared),
                        "jaccard_overlap": round(ratio, 3),
                        "recommendation": "review_for_merge_or_repositioning",
                    })
    return {
        "playlists": analyses,
        "playlist_count": len(playlists),
        "duplicate_title_groups": duplicate_title_groups,
        "high_overlap_groups": overlaps,
        "creation_guidance": {
            "create_only_when": "a distinct recurring topic has enough owned videos and is not already covered by an existing playlist",
            "recommended_minimum_video_count": 3,
        },
        "read_only": True,
        "seo_context_ready": True,
    }


def _validate_playlist_create(
    service,
    *,
    title: str,
    description: str,
    privacy_status: str,
    default_language: str | None,
    video_ids: list[str] | None,
) -> dict[str, Any]:
    final_title = _normalize_title(title)
    final_description = _normalize_description(description)
    final_privacy = str(privacy_status or "private").strip().lower()
    final_language = _normalize_language(default_language)
    if not final_title:
        raise base.tool_error("invalid_request", "Playlist title is required.")
    if len(final_title) > _PLAYLIST_TITLE_MAX:
        raise base.tool_error("invalid_request", "Playlist title exceeds 150 characters.")
    if len(final_description) > _PLAYLIST_DESCRIPTION_MAX:
        raise base.tool_error("invalid_request", "Playlist description exceeds 5,000 characters.")
    if final_privacy not in _PRIVACY:
        raise base.tool_error("invalid_request", "privacy_status must be public, unlisted, or private.")
    existing = _list_all_playlists(service)
    duplicate = next((row for row in existing if _normalize_title(row["title"]).casefold() == final_title.casefold()), None)
    if duplicate:
        raise base.tool_error("invalid_request", f"A playlist with the same normalized title already exists: {duplicate['playlist_id']}.")
    clean_video_ids: list[str] = []
    seen: set[str] = set()
    for raw in video_ids or []:
        video_id = str(raw or "").strip()
        if not video_id or video_id in seen:
            continue
        service._owned_video_item(video_id, part="snippet")
        seen.add(video_id)
        clean_video_ids.append(video_id)
    return {
        "title": final_title,
        "description": final_description,
        "privacy_status": final_privacy,
        "default_language": final_language,
        "video_ids": clean_video_ids,
    }


def _create_playlist(service, proposed: dict[str, Any]) -> dict[str, Any]:
    snippet: dict[str, Any] = {
        "title": proposed["title"],
        "description": proposed["description"],
    }
    if proposed.get("default_language"):
        snippet["defaultLanguage"] = proposed["default_language"]
    response = service._youtube().playlists().insert(
        part="snippet,status",
        body={"snippet": snippet, "status": {"privacyStatus": proposed["privacy_status"]}},
    ).execute()
    playlist_id = str(response.get("id", "")).strip()
    if not playlist_id:
        raise base.tool_error("youtube_api_error", "YouTube did not return the created playlist ID.")
    try:
        for position, video_id in enumerate(proposed.get("video_ids", [])):
            service._youtube().playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        "position": position,
                    }
                },
            ).execute()
    except Exception:
        # The playlist itself was created by this operation, so deleting it here
        # is a safe compensation that prevents a half-built organization state.
        try:
            service._youtube().playlists().delete(id=playlist_id).execute()
        finally:
            raise
    observed = management._playlist_snapshot(service, playlist_id)
    membership = management._playlist_membership(service, playlist_id)
    actual_ids = [row["video_id"] for row in membership]
    if actual_ids != proposed.get("video_ids", []):
        raise base.tool_error("youtube_api_error", "YouTube did not persist the approved playlist membership exactly.")
    return {"playlist_id": playlist_id, "playlist": observed, "membership": membership}


def _playlist_recovery_snapshot(service, playlist_id: str) -> dict[str, Any]:
    current = management._playlist_snapshot(service, playlist_id)
    membership = management._playlist_membership(service, playlist_id)
    return {"playlist": current, "membership": membership}


def _ensure_deletable_playlist(service, playlist_id: str) -> None:
    if str(playlist_id).strip() in _related_playlist_ids(service):
        raise base.tool_error("invalid_request", "YouTube system/related playlists cannot be deleted by this management flow.")
    management._owned_playlist(service, playlist_id)


def _recreate_from_snapshot(service, snapshot: dict[str, Any]) -> dict[str, Any]:
    playlist = dict(snapshot.get("playlist", {}) or {})
    membership = list(snapshot.get("membership", []) or [])
    proposed = {
        "title": playlist.get("title", "Recovered playlist"),
        "description": playlist.get("description", ""),
        "privacy_status": playlist.get("privacy_status", "private"),
        "default_language": None,
        "video_ids": [str(row.get("video_id", "")).strip() for row in membership if str(row.get("video_id", "")).strip()],
    }
    return _create_playlist(service, proposed)


def extend_server(server):
    @server.tool(
        title="Auditar SEO e organização das playlists",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def audit_playlist_organization(include_membership: bool = True) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("playlist_audit", limit=20)
            return base.success_response(_playlist_organization_audit(_service(), include_membership=include_membership))
        return base._structured("audit_playlist_organization", action)

    @server.tool(
        title="Preparar criação segura de playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_playlist_create(
        title: str,
        description: str = "",
        privacy_status: str = "private",
        default_language: str | None = None,
        video_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_preview", limit=30)
            service = _service()
            proposed = _validate_playlist_create(
                service,
                title=title,
                description=description,
                privacy_status=privacy_status,
                default_language=default_language,
                video_ids=video_ids,
            )
            channel_id = service._authorized_channel_id()
            baseline = _playlist_inventory_digest_rows(service)
            payload = {"baseline_digest": signer_from_env().payload_digest(baseline), "proposed": proposed}
            token = signer_from_env().issue("create_playlist", channel_id, payload)
            return base.success_response({
                "channel_id": channel_id,
                "proposed": proposed,
                "approval_payload": payload,
                "approval_token": token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
            })
        return base._structured("preview_playlist_create", action)

    @server.tool(
        title="Criar playlist aprovada",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_create(approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_apply", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            service = _service()
            channel_id = service._authorized_channel_id()
            management._consume_token(token=approval_token, payload=approval_payload, action="create_playlist", subject=channel_id)
            baseline = _playlist_inventory_digest_rows(service)
            if signer_from_env().payload_digest(baseline) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            proposed = dict(approval_payload.get("proposed", {}) or {})
            result = _create_playlist(service, proposed)
            recovery_snapshot = {"playlist": result["playlist"], "membership": result["membership"]}
            rollback_payload = {"snapshot": recovery_snapshot}
            rollback_token = signer_from_env().issue("rollback_created_playlist", result["playlist_id"], rollback_payload)
            base._audit("mcp_playlist_create", "success", {"playlist_id": result["playlist_id"]})
            return base.success_response({
                **result,
                "persisted_verified": True,
                "rollback_preview": {
                    "rollback_payload": rollback_payload,
                    "rollback_token": rollback_token,
                    "expires_in_seconds": 900,
                    "requires_explicit_user_confirmation": True,
                },
            })
        return base._structured("apply_playlist_create", action)

    @server.tool(
        title="Desfazer criação de playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_create_rollback(rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_rollback", limit=10)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            snapshot = dict(rollback_payload.get("snapshot", {}) or {})
            playlist_id = str((snapshot.get("playlist", {}) or {}).get("playlist_id", "")).strip()
            management._consume_token(token=rollback_token, payload=rollback_payload, action="rollback_created_playlist", subject=playlist_id)
            service = _service()
            current = _playlist_recovery_snapshot(service, playlist_id)
            if signer_from_env().payload_digest(current) != signer_from_env().payload_digest(snapshot):
                raise base.tool_error("external_change_detected")
            service._youtube().playlists().delete(id=playlist_id).execute()
            try:
                management._owned_playlist(service, playlist_id)
            except Exception:
                base._audit("mcp_playlist_create_rollback", "success", {"playlist_id": playlist_id})
                return base.success_response({"playlist_id": playlist_id, "rolled_back": True, "persisted_verified": True})
            raise base.tool_error("youtube_api_error", "YouTube did not confirm deletion of the newly created playlist.")
        return base._structured("apply_playlist_create_rollback", action)

    @server.tool(
        title="Preparar exclusão segura de playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_playlist_delete(playlist_id: str) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_preview", limit=20)
            service = _service()
            _ensure_deletable_playlist(service, playlist_id)
            snapshot = _playlist_recovery_snapshot(service, playlist_id)
            payload = {"baseline_digest": signer_from_env().payload_digest(snapshot), "snapshot": snapshot}
            token = signer_from_env().issue("delete_playlist", playlist_id, payload)
            return base.success_response({
                "playlist_id": playlist_id,
                "snapshot": snapshot,
                "item_count": len(snapshot["membership"]),
                "approval_payload": payload,
                "approval_token": token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": True,
                "recovery_supported": True,
            })
        return base._structured("preview_playlist_delete", action)

    @server.tool(
        title="Excluir playlist aprovada",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_delete(approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_apply", limit=8)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            snapshot = dict(approval_payload.get("snapshot", {}) or {})
            playlist_id = str((snapshot.get("playlist", {}) or {}).get("playlist_id", "")).strip()
            service = _service()
            _ensure_deletable_playlist(service, playlist_id)
            management._consume_token(token=approval_token, payload=approval_payload, action="delete_playlist", subject=playlist_id)
            current = _playlist_recovery_snapshot(service, playlist_id)
            if signer_from_env().payload_digest(current) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            service._youtube().playlists().delete(id=playlist_id).execute()
            try:
                management._owned_playlist(service, playlist_id)
            except Exception:
                recovery_payload = {"snapshot": snapshot}
                recovery_token = signer_from_env().issue("recover_deleted_playlist", playlist_id, recovery_payload)
                base._audit("mcp_playlist_delete", "success", {"playlist_id": playlist_id})
                return base.success_response({
                    "playlist_id": playlist_id,
                    "deleted_verified": True,
                    "recovery_preview": {
                        "recovery_payload": recovery_payload,
                        "recovery_token": recovery_token,
                        "expires_in_seconds": 900,
                        "requires_explicit_user_confirmation": True,
                        "note": "Recovery recreates the playlist and therefore receives a new YouTube playlist ID.",
                    },
                })
            raise base.tool_error("youtube_api_error", "YouTube did not confirm playlist deletion.")
        return base._structured("apply_playlist_delete", action)

    @server.tool(
        title="Recuperar playlist excluída a partir do snapshot",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_delete_recovery(recovery_payload: dict[str, Any], recovery_token: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_recovery", limit=5)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            snapshot = dict(recovery_payload.get("snapshot", {}) or {})
            original_id = str((snapshot.get("playlist", {}) or {}).get("playlist_id", "")).strip()
            management._consume_token(token=recovery_token, payload=recovery_payload, action="recover_deleted_playlist", subject=original_id)
            result = _recreate_from_snapshot(_service(), snapshot)
            base._audit("mcp_playlist_delete_recovery", "success", {"original_playlist_id": original_id, "new_playlist_id": result["playlist_id"]})
            return base.success_response({"original_playlist_id": original_id, "new_playlist_id": result["playlist_id"], **result, "persisted_verified": True})
        return base._structured("apply_playlist_delete_recovery", action)

    @server.tool(
        title="Preparar reordenação de vídeos da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_playlist_item_reorder(playlist_id: str, ordered_video_ids: list[str]) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_preview", limit=20)
            service = _service()
            before = management._playlist_membership(service, playlist_id)
            current_ids = [row["video_id"] for row in before]
            if len(set(current_ids)) != len(current_ids):
                raise base.tool_error("invalid_request", "Playlist contains duplicate video IDs; reorder by video ID is ambiguous.")
            proposed_ids = [str(video_id).strip() for video_id in ordered_video_ids]
            if len(set(proposed_ids)) != len(proposed_ids) or set(proposed_ids) != set(current_ids) or len(proposed_ids) != len(current_ids):
                raise base.tool_error("invalid_request", "ordered_video_ids must contain every current playlist video exactly once.")
            proposed = {"playlist_id": playlist_id, "ordered_video_ids": proposed_ids}
            payload = {"baseline_digest": signer_from_env().payload_digest(before), "proposed": proposed}
            token = signer_from_env().issue("reorder_playlist_items", playlist_id, payload)
            return base.success_response({
                "playlist_id": playlist_id,
                "current_order": current_ids,
                "proposed_order": proposed_ids,
                "changed": current_ids != proposed_ids,
                "approval_payload": payload,
                "approval_token": token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": current_ids != proposed_ids,
            })
        return base._structured("preview_playlist_item_reorder", action)

    @server.tool(
        title="Aplicar reordenação aprovada da playlist",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_playlist_item_reorder(approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("playlist_apply", limit=8)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(approval_payload.get("proposed", {}) or {})
            playlist_id = str(proposed.get("playlist_id", "")).strip()
            target_ids = [str(value).strip() for value in proposed.get("ordered_video_ids", [])]
            management._consume_token(token=approval_token, payload=approval_payload, action="reorder_playlist_items", subject=playlist_id)
            service = _service()
            before = management._playlist_membership(service, playlist_id)
            if signer_from_env().payload_digest(before) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            by_video = {row["video_id"]: row for row in before}
            if set(by_video) != set(target_ids):
                raise base.tool_error("external_change_detected")
            for position, video_id in enumerate(target_ids):
                row = by_video[video_id]
                service._youtube().playlistItems().update(
                    part="snippet",
                    body={
                        "id": row["playlist_item_id"],
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                            "position": position,
                        },
                    },
                ).execute()
            after = management._playlist_membership(service, playlist_id)
            actual = [row["video_id"] for row in after]
            if actual != target_ids:
                raise base.tool_error("youtube_api_error", "YouTube did not persist the approved playlist order exactly.")
            rollback_payload = {
                "baseline_digest": signer_from_env().payload_digest(after),
                "proposed": {"playlist_id": playlist_id, "ordered_video_ids": [row["video_id"] for row in before]},
            }
            rollback_token = signer_from_env().issue("reorder_playlist_items", playlist_id, rollback_payload)
            base._audit("mcp_playlist_reorder", "success", {"playlist_id": playlist_id})
            return base.success_response({
                "playlist_id": playlist_id,
                "ordered_video_ids": actual,
                "persisted_verified": True,
                "rollback_preview": {
                    "approval_payload": rollback_payload,
                    "approval_token": rollback_token,
                    "expires_in_seconds": 900,
                    "requires_explicit_user_confirmation": True,
                },
            })
        return base._structured("apply_playlist_item_reorder", action)

    @server.tool(
        title="Auditar perfil e SEO do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def audit_channel_profile() -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.READ_SCOPE)
            base._limit("channel_profile_audit", limit=30)
            return base.success_response(_channel_seo_audit(_service()))
        return base._structured("audit_channel_profile", action)

    @server.tool(
        title="Preparar atualização SEO do perfil do canal",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_channel_profile_update(
        description: str | None = None,
        keywords: list[str] | None = None,
        country: str | None = None,
        default_language: str | None = None,
        unsubscribed_trailer: str | None = None,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("channel_profile_preview", limit=20)
            if all(value is None for value in (description, keywords, country, default_language, unsubscribed_trailer)):
                raise base.tool_error("invalid_request", "At least one writable channel profile field must be supplied.")
            service = _service()
            current = _channel_snapshot(service)
            proposed = _normalize_channel_profile(
                current,
                description=description,
                keywords=keywords,
                country=country,
                default_language=default_language,
                unsubscribed_trailer=unsubscribed_trailer,
            )
            if proposed["unsubscribed_trailer"] and proposed["unsubscribed_trailer"] != current["unsubscribed_trailer"]:
                trailer = service._owned_video_item(proposed["unsubscribed_trailer"], part="snippet,status")
                privacy = str((trailer.get("status", {}) or {}).get("privacyStatus", ""))
                if privacy not in {"public", "unlisted"}:
                    raise base.tool_error("invalid_request", "Channel trailer must be a public or unlisted owned video.")
            fields = ["description", "keywords_serialized", "country", "default_language", "unsubscribed_trailer"]
            changed = {field: current[field] != proposed[field] for field in fields}
            payload = {"baseline_digest": signer_from_env().payload_digest(current), "proposed": proposed}
            token = signer_from_env().issue("update_channel_profile", current["channel_id"], payload)
            return base.success_response({
                "channel_id": current["channel_id"],
                "current": current,
                "proposed": proposed,
                "changed": changed,
                "approval_payload": payload,
                "approval_token": token,
                "expires_in_seconds": 900,
                "requires_explicit_user_confirmation": any(changed.values()),
            })
        return base._structured("preview_channel_profile_update", action)

    @server.tool(
        title="Aplicar atualização SEO aprovada do canal",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_channel_profile_update(approval_payload: dict[str, Any], approval_token: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("channel_profile_apply", limit=8)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(approval_payload.get("proposed", {}) or {})
            channel_id = str(proposed.get("channel_id", "")).strip()
            management._consume_token(token=approval_token, payload=approval_payload, action="update_channel_profile", subject=channel_id)
            service = _service()
            current = _channel_snapshot(service)
            if signer_from_env().payload_digest(current) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            body = _channel_update_body(current, proposed)
            service._youtube().channels().update(part="brandingSettings", body=body).execute()
            observed = _channel_snapshot(service)
            verify_fields = ["description", "keywords_serialized", "country", "default_language", "unsubscribed_trailer"]
            if any(observed[field] != proposed[field] for field in verify_fields):
                raise base.tool_error("youtube_api_error", "YouTube did not persist the approved channel profile exactly.")
            rollback_payload = {"baseline_digest": signer_from_env().payload_digest(observed), "proposed": current}
            rollback_token = signer_from_env().issue("rollback_channel_profile", channel_id, rollback_payload)
            base._audit("mcp_channel_profile_apply", "success", {"channel_id": channel_id})
            return base.success_response({
                "channel_id": channel_id,
                "current": observed,
                "persisted_verified": True,
                "rollback_preview": {
                    "rollback_payload": rollback_payload,
                    "rollback_token": rollback_token,
                    "expires_in_seconds": 900,
                    "requires_explicit_user_confirmation": True,
                },
            })
        return base._structured("apply_channel_profile_update", action)

    @server.tool(
        title="Restaurar perfil anterior do canal",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_channel_profile_rollback(rollback_payload: dict[str, Any], rollback_token: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            base._require_scope(base.WRITE_SCOPE)
            base._limit("channel_profile_rollback", limit=5)
            if user_confirmed is not True:
                raise base.tool_error("confirmation_required")
            proposed = dict(rollback_payload.get("proposed", {}) or {})
            channel_id = str(proposed.get("channel_id", "")).strip()
            management._consume_token(token=rollback_token, payload=rollback_payload, action="rollback_channel_profile", subject=channel_id)
            service = _service()
            current = _channel_snapshot(service)
            if signer_from_env().payload_digest(current) != str(rollback_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            service._youtube().channels().update(part="brandingSettings", body=_channel_update_body(current, proposed)).execute()
            observed = _channel_snapshot(service)
            verify_fields = ["description", "keywords_serialized", "country", "default_language", "unsubscribed_trailer"]
            if any(observed[field] != proposed[field] for field in verify_fields):
                raise base.tool_error("youtube_api_error", "YouTube did not persist the channel profile rollback exactly.")
            base._audit("mcp_channel_profile_rollback", "success", {"channel_id": channel_id})
            return base.success_response({"channel_id": channel_id, "rolled_back": True, "persisted_verified": True, "current": observed})
        return base._structured("apply_channel_profile_rollback", action)

    return server
