from __future__ import annotations

import asyncio

import pytest
from mcp import Client

from ai.base import AIProviderError
from ai.gemini import GeminiProvider
from ai.types import AIProviderConfig
from creator_service.cloud_mcp_server_video import _owned_video_details, create_server


class _Execute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Channels:
    def __init__(self, channel_id="channel-1"):
        self.channel_id = channel_id

    def list(self, **_kwargs):
        return _Execute({"items": [{"id": self.channel_id, "snippet": {"title": "Canal"}}]})


class _Videos:
    def __init__(self, channel_id="channel-1"):
        self.channel_id = channel_id

    def list(self, **_kwargs):
        return _Execute(
            {
                "items": [
                    {
                        "id": "video-1",
                        "snippet": {
                            "channelId": self.channel_id,
                            "title": "Video title",
                            "description": "Description",
                            "tags": ["one", "two"],
                            "categoryId": "10",
                            "publishedAt": "2026-01-01T00:00:00Z",
                            "thumbnails": {"high": {"url": "https://example.test/thumb.jpg"}},
                        },
                        "contentDetails": {"duration": "PT3M", "definition": "hd", "caption": "true"},
                        "statistics": {"viewCount": "42", "likeCount": "7", "commentCount": "2"},
                        "status": {"privacyStatus": "public", "madeForKids": False},
                    }
                ]
            }
        )


class _Youtube:
    def __init__(self, *, video_channel_id="channel-1"):
        self._channels = _Channels()
        self._videos = _Videos(video_channel_id)

    def channels(self):
        return self._channels

    def videos(self):
        return self._videos


class _Service:
    def __init__(self, youtube):
        self.youtube = youtube

    def _youtube(self):
        return self.youtube


def test_video_details_restricts_reads_to_connected_channel():
    details = _owned_video_details(_Service(_Youtube()), "video-1")
    assert details["video_id"] == "video-1"
    assert details["title"] == "Video title"
    assert details["views"] == 42
    assert details["privacy_status"] == "public"

    with pytest.raises(PermissionError, match="não pertence"):
        _owned_video_details(_Service(_Youtube(video_channel_id="another-channel")), "video-1")


def test_production_mcp_surface_contains_write_tools_and_video_readers(monkeypatch):
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.test")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.test")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example.test/mcp")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.test/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "secret")

    async def names():
        async with Client(create_server(), raise_exceptions=True) as client:
            result = await client.list_tools()
            return {tool.name for tool in result.tools}

    tool_names = asyncio.run(names())
    required = {
        "activate_connected_channel",
        "preview_video_metadata_update",
        "apply_video_metadata_update",
        "apply_video_metadata_rollback",
        "get_video_details",
        "get_video_transcript",
    }
    assert required <= tool_names


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_gemini_recovers_from_incompatible_saved_model(monkeypatch):
    provider = GeminiProvider(
        AIProviderConfig(provider="gemini", api_key="test-key", base_url=None, timeout_seconds=1.0)
    )
    calls = []

    def fake_request(method, path, **_kwargs):
        calls.append((method, path))
        if path == "/models/bad-model:generateContent":
            raise AIProviderError(
                "Falha ao comunicar com Gemini. Resposta: model is not supported for generateContent"
            )
        if method == "GET" and path == "/models":
            return _Response(
                {
                    "models": [
                        {
                            "name": "models/gemini-3.5-flash-lite",
                            "displayName": "Gemini 3.5 Flash-Lite",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/embedding-model",
                            "displayName": "Embedding",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                    ]
                }
            )
        if path == "/models/gemini-3.5-flash-lite:generateContent":
            return _Response(
                {
                    "candidates": [{"content": {"parts": [{"text": "OK"}]}}],
                    "usageMetadata": {"promptTokenCount": 1},
                }
            )
        raise AssertionError((method, path))

    monkeypatch.setattr(provider, "_request", fake_request)
    response = provider.generate("bad-model", [{"role": "user", "content": "teste"}])
    assert response.text == "OK"
    assert response.model == "gemini-3.5-flash-lite"
    assert ("GET", "/models") in calls
