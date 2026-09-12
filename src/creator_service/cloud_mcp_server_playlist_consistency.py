from __future__ import annotations

import time
from typing import Any

from mcp.types import ToolAnnotations

from . import cloud_mcp_server as base
from . import cloud_mcp_server_growth as growth
from . import cloud_mcp_server_management as management
from .mcp_errors import CreatorToolError


_READBACK_DELAYS_SECONDS = (0.20, 0.40, 0.80, 1.60, 3.00)
_DELETE_CONFIRM_DELAYS_SECONDS = (0.20, 0.40, 0.80, 1.60, 3.00)
_ORIGINAL_EXTEND_SERVER = growth.extend_server


def _is_playlist_not_found(exc: BaseException) -> bool:
    return isinstance(exc, CreatorToolError) and exc.code == "playlist_not_found"


def _read_created_playlist_with_retry(service, playlist_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read a newly-created playlist without retrying the create operation itself.

    YouTube can acknowledge playlists.insert before the resource is visible to a
    following playlists.list/playlistItems.list read. Retrying the INSERT would
    risk duplicate playlists, so only the authoritative readback is retried.
    """
    last_error: BaseException | None = None
    attempts = len(_READBACK_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            observed = management._playlist_snapshot(service, playlist_id)
            membership = management._playlist_membership(service, playlist_id)
            return observed, membership
        except Exception as exc:
            if not _is_playlist_not_found(exc):
                raise
            last_error = exc
            if attempt >= len(_READBACK_DELAYS_SECONDS):
                break
            time.sleep(_READBACK_DELAYS_SECONDS[attempt])
    raise base.tool_error(
        "youtube_api_error",
        f"YouTube accepted playlist creation for {playlist_id} but the new playlist was not visible after {attempts} authoritative readback attempts.",
    ) from last_error


def _confirm_playlist_absent_with_retry(service, playlist_id: str) -> bool:
    """Confirm deletion using bounded authoritative reads only.

    A successful playlists.delete can remain briefly visible through playlists.list.
    The mutation must never be retried. Success is the authoritative
    playlist_not_found state observed during one of the bounded read attempts.
    """
    attempts = len(_DELETE_CONFIRM_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            management._owned_playlist(service, playlist_id)
        except Exception as exc:
            if _is_playlist_not_found(exc):
                return True
            raise
        if attempt < len(_DELETE_CONFIRM_DELAYS_SECONDS):
            time.sleep(_DELETE_CONFIRM_DELAYS_SECONDS[attempt])
    return False


def _delete_playlist_once_and_confirm(service, playlist_id: str, *, failure_message: str) -> None:
    """Execute playlists.delete exactly once, then retry only absence confirmation."""
    service._youtube().playlists().delete(id=playlist_id).execute()
    if not _confirm_playlist_absent_with_retry(service, playlist_id):
        raise base.tool_error("youtube_api_error", failure_message)


def _delete_created_playlist_compensation(service, playlist_id: str) -> bool:
    """Best-effort cleanup for a playlist created by this same operation."""
    try:
        _delete_playlist_once_and_confirm(
            service,
            playlist_id,
            failure_message="YouTube did not confirm compensation deletion of the newly created playlist.",
        )
        return True
    except Exception:
        return False


def _create_playlist_consistent(service, proposed: dict[str, Any]) -> dict[str, Any]:
    snippet: dict[str, Any] = {
        "title": proposed["title"],
        "description": proposed["description"],
    }
    if proposed.get("default_language"):
        snippet["defaultLanguage"] = proposed["default_language"]

    # IMPORTANT: playlists.insert executes exactly once. Only readback retries.
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

        observed, membership = _read_created_playlist_with_retry(service, playlist_id)
        actual_ids = [row["video_id"] for row in membership]
        if actual_ids != proposed.get("video_ids", []):
            raise base.tool_error(
                "youtube_api_error",
                "YouTube did not persist the approved playlist membership exactly.",
            )
        return {"playlist_id": playlist_id, "playlist": observed, "membership": membership}
    except Exception as exc:
        # The exact playlist ID came from this operation, so compensating only
        # that resource is safe. Never retry playlists.insert after ambiguity.
        compensated = _delete_created_playlist_compensation(service, playlist_id)
        if isinstance(exc, CreatorToolError) and exc.code == "youtube_api_error":
            suffix = " Compensation delete was verified." if compensated else " Compensation delete could not be verified."
            raise base.tool_error("youtube_api_error", f"{exc.message}{suffix}") from exc
        raise


def _extend_server_consistent(server):
    """Keep growth schemas intact while hardening only post-delete verification."""
    server = _ORIGINAL_EXTEND_SERVER(server)

    server.remove_tool("apply_playlist_create_rollback")

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
            management._consume_token(
                token=rollback_token,
                payload=rollback_payload,
                action="rollback_created_playlist",
                subject=playlist_id,
            )
            service = growth._service()
            current = growth._playlist_recovery_snapshot(service, playlist_id)
            if growth.signer_from_env().payload_digest(current) != growth.signer_from_env().payload_digest(snapshot):
                raise base.tool_error("external_change_detected")
            _delete_playlist_once_and_confirm(
                service,
                playlist_id,
                failure_message="YouTube did not confirm deletion of the newly created playlist.",
            )
            base._audit("mcp_playlist_create_rollback", "success", {"playlist_id": playlist_id})
            return base.success_response({"playlist_id": playlist_id, "rolled_back": True, "persisted_verified": True})
        return base._structured("apply_playlist_create_rollback", action)

    server.remove_tool("apply_playlist_delete")

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
            service = growth._service()
            growth._ensure_deletable_playlist(service, playlist_id)
            management._consume_token(
                token=approval_token,
                payload=approval_payload,
                action="delete_playlist",
                subject=playlist_id,
            )
            current = growth._playlist_recovery_snapshot(service, playlist_id)
            if growth.signer_from_env().payload_digest(current) != str(approval_payload.get("baseline_digest", "")):
                raise base.tool_error("external_change_detected")
            _delete_playlist_once_and_confirm(
                service,
                playlist_id,
                failure_message="YouTube did not confirm playlist deletion.",
            )
            recovery_payload = {"snapshot": snapshot}
            recovery_token = growth.signer_from_env().issue("recover_deleted_playlist", playlist_id, recovery_payload)
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
        return base._structured("apply_playlist_delete", action)

    return server


def install() -> None:
    """Install hardened create/readback/delete behavior without changing MCP schemas."""
    growth._create_playlist = _create_playlist_consistent
    growth.extend_server = _extend_server_consistent
