from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import Client

from creator_service.cloud_mcp_server_v1_compat import HANDOFF_UI_URI, create_server


EXPECTED_TOOLS = {
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


async def _catalog():
    async with Client(create_server(), raise_exceptions=True) as client:
        tools = (await client.list_tools()).tools
        resources = (await client.list_resources()).resources
        return tools, resources


def test_root_entrypoint_runs_composed_v1_compat_surface() -> None:
    root = Path("cloud_mcp_server.py").read_text(encoding="utf-8")
    assert "from creator_service.cloud_mcp_server_v1_compat import run" in root


def test_full_production_catalog_and_critical_schemas(monkeypatch) -> None:
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.com")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://creator.example.com/mcp")
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.com/oauth/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "test-client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "test-secret")

    tools, resources = asyncio.run(_catalog())
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == EXPECTED_TOOLS
    assert len(by_name) == 47
    assert HANDOFF_UI_URI in {str(resource.uri) for resource in resources}

    expected_schemas = {
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
    for name, (properties, required) in expected_schemas.items():
        schema = by_name[name].input_schema
        assert set(schema.get("properties", {})) == properties
        assert set(schema.get("required", [])) == required

    expected_annotations = {
        "preview_video_metadata_update": (True, False, False, True),
        "list_channel_videos": (True, False, False, True),
        "preview_playlist_create": (False, False, False, False),
        "apply_playlist_create": (False, True, True, False),
        "apply_playlist_create_rollback": (False, True, True, False),
        "audit_playlist_organization": (True, False, False, True),
        "audit_channel_profile": (True, False, False, True),
    }
    for name, expected in expected_annotations.items():
        hints = by_name[name].annotations.model_dump(by_alias=True, exclude_none=True)
        actual = (
            hints.get("readOnlyHint"), hints.get("openWorldHint"),
            hints.get("destructiveHint"), hints.get("idempotentHint"),
        )
        assert actual == expected

    for tool in tools:
        assert "tenant_id" not in tool.input_schema.get("properties", {})
        assert tool.annotations is not None
