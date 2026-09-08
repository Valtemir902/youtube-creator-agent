from __future__ import annotations

import time
from typing import Any

from . import cloud_mcp_server as base
from . import cloud_mcp_server_growth as growth
from . import cloud_mcp_server_management as management
from .mcp_errors import CreatorToolError


_READBACK_DELAYS_SECONDS = (0.20, 0.40, 0.80, 1.60, 3.00)


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


def _delete_created_playlist_compensation(service, playlist_id: str) -> bool:
    """Best-effort cleanup for a playlist created by this same operation."""
    try:
        service._youtube().playlists().delete(id=playlist_id).execute()
    except Exception:
        return False

    # Deletion verification is deliberately tolerant of playlist_not_found,
    # which is the expected state after a successful delete.
    try:
        management._owned_playlist(service, playlist_id)
    except Exception as exc:
        if _is_playlist_not_found(exc):
            return True
        return False
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


def install() -> None:
    """Install the hardened create helper without changing MCP tool schemas."""
    growth._create_playlist = _create_playlist_consistent
