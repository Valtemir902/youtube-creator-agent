from __future__ import annotations

import asyncio
import json

from mcp import Client

from creator_service import cloud_mcp_server_v1_compat as bridge


def _configure_mcp_env(monkeypatch) -> None:
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.com/realms/yca")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.com")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example.com/")
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.com/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "test-client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "test-secret")


def test_v1_bridge_preserves_34_tool_surface_and_historical_schema(monkeypatch):
    _configure_mcp_env(monkeypatch)

    async def run() -> None:
        async with Client(bridge.create_server(), raise_exceptions=True) as client:
            result = await client.list_tools()
            names = {tool.name for tool in result.tools}
            assert len(names) >= 34
            assert "get_video_details" in names
            assert "get_video_transcript" in names
            assert "render_video_metadata_handoff" in names

            preview = next(tool for tool in result.tools if tool.name == "preview_video_metadata_update")
            assert set(preview.input_schema.get("properties", {})) == {
                "video_id",
                "title",
                "description",
                "tags",
            }
            hints = preview.annotations.model_dump(by_alias=True, exclude_none=True)
            assert hints["readOnlyHint"] is True
            assert hints["destructiveHint"] is False

    asyncio.run(run())


def test_v1_video_id_only_returns_details_and_full_transcript(monkeypatch):
    _configure_mcp_env(monkeypatch)
    service = object()
    transcript_calls: list[dict] = []

    monkeypatch.setattr(bridge.base, "_require_scope", lambda scope: None)
    monkeypatch.setattr(bridge.base, "_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge.responsible, "_service", lambda: service)
    monkeypatch.setattr(
        bridge.management,
        "_owned_video_details",
        lambda current_service, video_id: {
            "video_id": video_id,
            "title": "Bridge Test",
            "description": "unchanged",
            "tags": ["dark-country"],
        },
    )

    def fake_transcript(current_service, video_id, **kwargs):
        assert current_service is service
        transcript_calls.append({"video_id": video_id, **kwargs})
        return {
            "video_id": video_id,
            "language": "en",
            "source": "youtube_caption",
            "transcript_source": "youtube_manual_caption",
            "is_auto_generated": False,
            "has_manual_caption": True,
            "has_published_manual_caption": True,
            "has_auto_generated_caption": True,
            "caption_publish_needed": False,
            "caption_publish_reason": "manual_caption_already_published",
            "caption_policy": "reuse_published_manual",
            "seo_context_ready": True,
            "full_text": "first line second line",
            "word_count": 4,
            "segments": [
                {"start": 0.0, "duration": 1.0, "text": "first line"},
                {"start": 1.0, "duration": 1.0, "text": "second line"},
            ],
            "segment_count": 2,
            "segment_offset": 0,
            "segment_limit": 500,
            "segments_complete": True,
            "next_segment_offset": None,
            "full_text_complete": True,
        }

    monkeypatch.setattr(bridge.management, "get_video_transcript_data", fake_transcript)

    async def run() -> None:
        async with Client(bridge.create_server(), raise_exceptions=True) as client:
            result = await client.call_tool(
                "preview_video_metadata_update",
                {"video_id": "j4r_jTsS7xU"},
            )
            payload = json.loads(result.content[0].text)
            assert payload["success"] is True
            assert payload["compatibility_mode"] == "v1_video_details_and_transcript"
            assert payload["read_only"] is True
            assert payload["requires_user_click"] is False
            assert payload["changed_fields"] == []
            assert payload["video"]["title"] == "Bridge Test"
            assert payload["transcript"]["source"] == "youtube_caption"
            assert payload["transcript"]["transcript_source"] == "youtube_manual_caption"
            assert payload["transcript"]["caption_publish_needed"] is False
            assert payload["transcript"]["caption_policy"] == "reuse_published_manual"
            assert payload["transcript"]["seo_context_ready"] is True
            assert payload["transcript"]["full_text"] == "first line second line"
            assert len(payload["transcript"]["segments"]) == 2
            assert "approval_payload" not in payload
            assert "handoff_url" not in payload

    asyncio.run(run())
    assert transcript_calls == [
        {
            "video_id": "j4r_jTsS7xU",
            "include_segments": True,
            "segment_offset": 0,
            "segment_limit": 500,
        }
    ]


def test_v1_metadata_arguments_keep_existing_preview_handoff_path(monkeypatch):
    _configure_mcp_env(monkeypatch)
    read_calls: list[str] = []
    preview_calls: list[dict] = []

    monkeypatch.setattr(
        bridge,
        "_legacy_v1_video_read",
        lambda video_id: read_calls.append(video_id) or {"success": True},
    )

    def fake_preview(**kwargs):
        preview_calls.append(kwargs)
        return {
            "success": True,
            "video_id": kwargs["video_id"],
            "changed_fields": ["title"],
            "requires_user_click": True,
        }

    monkeypatch.setattr(bridge.responsible, "_preview_metadata_with_handoff", fake_preview)

    async def run() -> None:
        async with Client(bridge.create_server(), raise_exceptions=True) as client:
            result = await client.call_tool(
                "preview_video_metadata_update",
                {"video_id": "j4r_jTsS7xU", "title": "Candidate title"},
            )
            payload = json.loads(result.content[0].text)
            assert payload["success"] is True
            assert payload["changed_fields"] == ["title"]

    asyncio.run(run())
    assert read_calls == []
    assert preview_calls == [
        {
            "video_id": "j4r_jTsS7xU",
            "title": "Candidate title",
            "description": None,
            "tags": None,
        }
    ]
