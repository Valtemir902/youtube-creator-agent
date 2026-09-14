from __future__ import annotations

from typing import Any


EXPECTED_RESOURCE_URI = "ui://youtube-creator-agent/handoff-v1.html"

EXPECTED_TOOL_NAMES = {
    "creator_status", "get_creator_capabilities", "list_connected_channels",
    "activate_connected_channel", "create_onboarding_link", "get_channel_profile",
    "get_strategy_evidence", "validate_keyword_candidates",
    "preview_video_metadata_update", "apply_video_metadata_update", "apply_video_metadata_rollback",
    "list_channel_videos", "get_video_details", "get_video_transcript", "list_video_categories",
    "preview_video_metadata_update_advanced", "apply_video_metadata_update_advanced",
    "apply_video_metadata_rollback_advanced", "list_video_captions",
    "preview_caption_upload", "apply_caption_upload", "apply_caption_delete_rollback",
    "list_playlists", "get_playlist_details", "preview_playlist_metadata_update",
    "apply_playlist_metadata_update", "apply_playlist_metadata_rollback",
    "preview_playlist_item_add", "apply_playlist_item_add", "apply_playlist_item_add_rollback",
    "preview_playlist_item_remove", "apply_playlist_item_remove", "apply_playlist_item_remove_rollback",
    "render_video_metadata_handoff",
    "audit_playlist_organization", "preview_playlist_create", "apply_playlist_create",
    "apply_playlist_create_rollback", "preview_playlist_delete", "apply_playlist_delete",
    "apply_playlist_delete_recovery", "preview_playlist_item_reorder", "apply_playlist_item_reorder",
    "audit_channel_profile", "preview_channel_profile_update", "apply_channel_profile_update",
    "apply_channel_profile_rollback",
}

EXPECTED_SCHEMAS = {
    "preview_video_metadata_update": (
        {"video_id", "title", "description", "tags"}, {"video_id"}
    ),
    "list_channel_videos": (
        {"max_results", "page_token"}, set()
    ),
    "preview_playlist_create": (
        {"title", "description", "privacy_status", "default_language", "video_ids"}, {"title"}
    ),
    "apply_playlist_create": (
        {"approval_payload", "approval_token", "user_confirmed"},
        {"approval_payload", "approval_token", "user_confirmed"},
    ),
    "apply_playlist_create_rollback": (
        {"rollback_payload", "rollback_token", "user_confirmed"},
        {"rollback_payload", "rollback_token", "user_confirmed"},
    ),
}

EXPECTED_ANNOTATIONS = {
    "preview_video_metadata_update": (True, False, False, True),
    "list_channel_videos": (True, False, False, True),
    "preview_playlist_create": (False, False, False, False),
    "apply_playlist_create": (False, True, True, False),
    "apply_playlist_create_rollback": (False, True, True, False),
    "audit_playlist_organization": (True, False, False, True),
    "audit_channel_profile": (True, False, False, True),
}


def _annotation_tuple(tool: Any) -> tuple[bool | None, bool | None, bool | None, bool | None]:
    if tool.annotations is None:
        return (None, None, None, None)
    hints = tool.annotations.model_dump(by_alias=True, exclude_none=True)
    return (
        hints.get("readOnlyHint"),
        hints.get("openWorldHint"),
        hints.get("destructiveHint"),
        hints.get("idempotentHint"),
    )


def assert_registered_server_contract(server: Any) -> None:
    """Fail fast unless the in-process production MCP surface is exactly the approved contract."""
    tools = list(server._tool_manager.list_tools())
    by_name = {tool.name: tool for tool in tools}
    names = set(by_name)
    assert names == EXPECTED_TOOL_NAMES, (
        f"missing={sorted(EXPECTED_TOOL_NAMES - names)} "
        f"unexpected={sorted(names - EXPECTED_TOOL_NAMES)}"
    )
    assert len(names) == 47, len(names)

    resources = list(server._resource_manager.list_resources())
    uris = {str(resource.uri) for resource in resources}
    assert uris == {EXPECTED_RESOURCE_URI}, sorted(uris)

    for name, (properties, required) in EXPECTED_SCHEMAS.items():
        schema = by_name[name].parameters
        assert set(schema.get("properties", {})) == properties, (name, schema)
        assert set(schema.get("required", [])) == required, (name, schema)

    for name, expected in EXPECTED_ANNOTATIONS.items():
        assert _annotation_tuple(by_name[name]) == expected, (name, _annotation_tuple(by_name[name]))

    for tool in tools:
        assert "tenant_id" not in tool.parameters.get("properties", {}), tool.name
        assert tool.annotations is not None, tool.name
