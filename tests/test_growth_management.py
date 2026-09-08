from __future__ import annotations

import asyncio

import pytest
from mcp import Client

from creator_service import cloud_mcp_server_growth as growth
from creator_service import cloud_mcp_server_v1_compat as bridge
from creator_service.mcp_errors import CreatorToolError


def _configure_mcp_env(monkeypatch) -> None:
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.com/realms/yca")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.com")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example.com/")
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.com/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "test-client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "test-secret")


def test_growth_helpers_normalize_channel_keywords_without_duplicates():
    values, serialized = growth._normalize_keywords(
        ["Dark Country", "western gothic", "dark country", "  outlaw   country  "]
    )
    assert values == ["Dark Country", "western gothic", "outlaw country"]
    assert serialized == '"Dark Country" "western gothic" "outlaw country"'
    assert growth._parse_channel_keywords(serialized) == values


def test_growth_rejects_channel_keywords_over_youtube_limit():
    with pytest.raises(CreatorToolError) as caught:
        growth._normalize_keywords(["x" * 501])
    assert caught.value.code == "invalid_request"


def test_channel_update_body_preserves_supported_existing_fields():
    current = {
        "channel_id": "channel-1",
        "title": "Channel",
        "description": "old",
        "keywords": ["old"],
        "keywords_serialized": "old",
        "country": "BR",
        "default_language": "en",
        "unsubscribed_trailer": "video-1",
        "tracking_analytics_account_id": "UA-TEST",
    }
    proposed = {
        **current,
        "description": "new optimized description",
        "keywords": ["dark country"],
        "keywords_serialized": '"dark country"',
    }
    body = growth._channel_update_body(current, proposed)
    assert body["id"] == "channel-1"
    channel = body["brandingSettings"]["channel"]
    assert channel["description"] == "new optimized description"
    assert channel["keywords"] == '"dark country"'
    assert channel["country"] == "BR"
    assert channel["defaultLanguage"] == "en"
    assert channel["unsubscribedTrailer"] == "video-1"
    assert channel["trackingAnalyticsAccountId"] == "UA-TEST"
    assert "title" not in channel


def test_v1_bridge_keeps_historical_tool_and_exposes_expanded_v2_catalog(monkeypatch):
    _configure_mcp_env(monkeypatch)

    async def run() -> None:
        async with Client(bridge.create_server(), raise_exceptions=True) as client:
            result = await client.list_tools()
            tools = {tool.name: tool for tool in result.tools}
            required = {
                "get_video_details",
                "get_video_transcript",
                "list_playlists",
                "preview_playlist_metadata_update",
                "apply_playlist_metadata_update",
                "audit_playlist_organization",
                "preview_playlist_create",
                "apply_playlist_create",
                "apply_playlist_create_rollback",
                "preview_playlist_delete",
                "apply_playlist_delete",
                "apply_playlist_delete_recovery",
                "preview_playlist_item_reorder",
                "apply_playlist_item_reorder",
                "audit_channel_profile",
                "preview_channel_profile_update",
                "apply_channel_profile_update",
                "apply_channel_profile_rollback",
            }
            assert required <= set(tools)
            assert len(tools) >= 47

            historical = tools["preview_video_metadata_update"]
            assert set(historical.input_schema.get("properties", {})) == {
                "video_id", "title", "description", "tags"
            }
            historical_hints = historical.annotations.model_dump(by_alias=True, exclude_none=True)
            assert historical_hints["readOnlyHint"] is True
            assert historical_hints["destructiveHint"] is False

            audit_hints = tools["audit_playlist_organization"].annotations.model_dump(
                by_alias=True, exclude_none=True
            )
            assert audit_hints["readOnlyHint"] is True
            assert audit_hints["destructiveHint"] is False

            delete_hints = tools["apply_playlist_delete"].annotations.model_dump(
                by_alias=True, exclude_none=True
            )
            assert delete_hints["readOnlyHint"] is False
            assert delete_hints["destructiveHint"] is True

    asyncio.run(run())


def test_playlist_audit_detects_empty_thin_and_overlapping_playlists(monkeypatch):
    class Service:
        pass

    playlists = [
        {"playlist_id": "p1", "title": "Music", "description": "", "default_language": "", "privacy_status": "public", "item_count": 3},
        {"playlist_id": "p2", "title": "Dark Country", "description": "short", "default_language": "en", "privacy_status": "public", "item_count": 3},
        {"playlist_id": "p3", "title": "Empty", "description": "", "default_language": "", "privacy_status": "private", "item_count": 0},
    ]
    memberships = {
        "p1": [
            {"playlist_item_id": "i1", "video_id": "v1", "position": 0},
            {"playlist_item_id": "i2", "video_id": "v2", "position": 1},
            {"playlist_item_id": "i3", "video_id": "v3", "position": 2},
        ],
        "p2": [
            {"playlist_item_id": "j1", "video_id": "v1", "position": 0},
            {"playlist_item_id": "j2", "video_id": "v2", "position": 1},
            {"playlist_item_id": "j3", "video_id": "v4", "position": 2},
        ],
        "p3": [],
    }
    monkeypatch.setattr(growth, "_list_all_playlists", lambda service: playlists)
    monkeypatch.setattr(
        growth.management,
        "_playlist_membership",
        lambda service, playlist_id: memberships[playlist_id],
    )
    result = growth._playlist_organization_audit(Service(), include_membership=True)
    by_id = {row["playlist_id"]: row for row in result["playlists"]}
    assert {issue["code"] for issue in by_id["p1"]["issues"]} >= {
        "missing_description", "generic_or_weak_title"
    }
    assert "empty_playlist" in {issue["code"] for issue in by_id["p3"]["issues"]}
    assert result["high_overlap_groups"][0]["shared_video_count"] == 2
    assert result["seo_context_ready"] is True
