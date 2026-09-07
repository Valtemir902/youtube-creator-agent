from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp import Client

from ai.base import AIProviderError
from ai.gemini import GeminiProvider
from ai.types import AIProviderConfig
from creator_service import cloud_mcp_server as base_mcp
from creator_service import cloud_mcp_server_management as management_mcp
from creator_service.cloud_mcp_server_management import create_server
from creator_service.cloud_mcp_server_video import _owned_video_details


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

    def list(self, **kwargs):
        if kwargs.get("id") == "missing":
            return _Execute({"items": []})
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
                            "defaultLanguage": "en",
                            "defaultAudioLanguage": "en",
                            "thumbnails": {"high": {"url": "https://example.test/thumb.jpg"}},
                        },
                        "contentDetails": {
                            "duration": "PT3M",
                            "definition": "hd",
                            "dimension": "2d",
                            "caption": "true",
                            "licensedContent": False,
                            "projection": "rectangular",
                        },
                        "statistics": {"viewCount": "42", "likeCount": "7", "commentCount": "2"},
                        "status": {
                            "privacyStatus": "public",
                            "madeForKids": False,
                            "embeddable": True,
                            "publicStatsViewable": True,
                        },
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

    def _owned_video_item(self, video_id: str, *, part: str):
        response = self.youtube.videos().list(part=part, id=video_id).execute()
        items = response.get("items", [])
        if not items:
            raise ValueError("Vídeo não encontrado.")
        item = items[0]
        channel = self.youtube.channels().list(part="id", mine=True).execute().get("items", [])[0]["id"]
        if item.get("snippet", {}).get("channelId") != channel:
            raise PermissionError("O vídeo não pertence ao canal conectado.")
        return item


class _WriteProbeService:
    def preview_video_metadata_update(self, **kwargs):
        return {
            "video_id": kwargs["video_id"],
            "changed": {},
            "approval_payload": {"proposed": {"video_id": kwargs["video_id"]}},
            "approval_token": "test-only",
            "requires_explicit_user_confirmation": True,
        }

    def apply_video_metadata_update(self, **_kwargs):
        raise AssertionError("apply service must not run without explicit confirmation")

    def apply_video_metadata_rollback(self, **_kwargs):
        raise AssertionError("rollback service must not run without explicit confirmation")


def _mcp_env(monkeypatch):
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.test")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.test")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example.test/mcp")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.test/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "secret")


def _payload(result):
    assert result.content
    text = getattr(result.content[0], "text", None)
    assert text, result
    return json.loads(text)


def test_video_details_restricts_reads_to_connected_channel():
    details = _owned_video_details(_Service(_Youtube()), "video-1")
    assert details["video_id"] == "video-1"
    assert details["channel_id"] == "channel-1"
    assert details["title"] == "Video title"
    assert details["view_count"] == 42
    assert details["views"] == 42
    assert details["privacy_status"] == "public"
    assert details["embeddable"] is True
    assert details["default_audio_language"] == "en"
    assert details["thumbnails"]["high"]["url"].endswith("thumb.jpg")

    with pytest.raises(PermissionError, match="não pertence"):
        _owned_video_details(_Service(_Youtube(video_channel_id="another-channel")), "video-1")

    with pytest.raises(ValueError, match="não encontrado"):
        _owned_video_details(_Service(_Youtube()), "missing")


def test_production_mcp_surface_contains_full_management_tools(monkeypatch):
    _mcp_env(monkeypatch)

    async def names():
        async with Client(create_server(), raise_exceptions=True) as client:
            result = await client.list_tools()
            return {tool.name for tool in result.tools}

    tool_names = asyncio.run(names())
    required = {
        "activate_connected_channel",
        "list_channel_videos",
        "get_video_details",
        "get_video_transcript",
        "preview_video_metadata_update",
        "apply_video_metadata_update",
        "apply_video_metadata_rollback",
        "preview_video_metadata_update_advanced",
        "list_video_captions",
        "preview_caption_upload",
        "apply_caption_upload",
        "list_playlists",
        "get_playlist_details",
        "preview_playlist_metadata_update",
        "apply_playlist_metadata_update",
        "preview_playlist_item_add",
        "apply_playlist_item_add",
        "preview_playlist_item_remove",
        "apply_playlist_item_remove",
    }
    assert required <= tool_names


def test_write_tools_are_invokable_and_confirmation_errors_are_structured(monkeypatch):
    _mcp_env(monkeypatch)
    monkeypatch.setattr(base_mcp, "_require_scope", lambda _scope: None)
    monkeypatch.setattr(base_mcp, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_tenant_id", lambda: "test-tenant")
    monkeypatch.setattr(base_mcp, "_resolver", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(base_mcp, "list_channel_accounts", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        base_mcp,
        "channel_account_state",
        lambda *_args, **_kwargs: {
            "channel_id": "channel-2",
            "exists": True,
            "already_active": False,
            "channel": {"id": "channel-2", "active": False},
        },
    )
    monkeypatch.setattr(management_mcp, "_service", lambda: _WriteProbeService())

    async def probe():
        async with Client(create_server(), raise_exceptions=True) as client:
            preview = await client.call_tool("preview_video_metadata_update", {"video_id": "video-1"})
            assert not preview.is_error
            assert _payload(preview)["success"] is True

            for name, args in (
                ("activate_connected_channel", {"channel_id": "channel-2", "user_confirmed": False}),
                (
                    "apply_video_metadata_update",
                    {"approval_payload": {}, "approval_token": "invalid-test-token", "user_confirmed": False},
                ),
                (
                    "apply_video_metadata_rollback",
                    {"rollback_payload": {}, "rollback_token": "invalid-test-token", "user_confirmed": False},
                ),
            ):
                result = await client.call_tool(name, args)
                assert not result.is_error
                payload = _payload(result)
                assert payload["success"] is False
                assert payload["error"]["code"] == "confirmation_required"

    asyncio.run(probe())


def test_activate_connected_channel_is_idempotent_without_confirmation(monkeypatch):
    _mcp_env(monkeypatch)
    monkeypatch.setattr(base_mcp, "_require_scope", lambda _scope: None)
    monkeypatch.setattr(base_mcp, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_tenant_id", lambda: "test-tenant")
    monkeypatch.setattr(base_mcp, "_resolver", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(base_mcp, "list_channel_accounts", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        base_mcp,
        "channel_account_state",
        lambda *_args, **_kwargs: {
            "channel_id": "channel-1",
            "exists": True,
            "already_active": True,
            "channel": {"id": "channel-1", "active": True},
        },
    )

    async def probe():
        async with Client(create_server(), raise_exceptions=True) as client:
            result = await client.call_tool(
                "activate_connected_channel",
                {"channel_id": "channel-1", "user_confirmed": False},
            )
            payload = _payload(result)
            assert payload["success"] is True
            assert payload["already_active"] is True
            assert payload["channel_id"] == "channel-1"

    asyncio.run(probe())


def test_activate_connected_channel_missing_is_typed(monkeypatch):
    _mcp_env(monkeypatch)
    monkeypatch.setattr(base_mcp, "_require_scope", lambda _scope: None)
    monkeypatch.setattr(base_mcp, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_tenant_id", lambda: "test-tenant")
    monkeypatch.setattr(base_mcp, "_resolver", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(base_mcp, "list_channel_accounts", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        base_mcp,
        "channel_account_state",
        lambda *_args, **_kwargs: {
            "channel_id": "missing",
            "exists": False,
            "already_active": False,
            "channel": None,
        },
    )

    async def probe():
        async with Client(create_server(), raise_exceptions=True) as client:
            result = await client.call_tool(
                "activate_connected_channel",
                {"channel_id": "missing", "user_confirmed": True},
            )
            payload = _payload(result)
            assert payload["success"] is False
            assert payload["error"]["code"] == "channel_not_found"

    asyncio.run(probe())


class _FakeGeminiModels:
    def __init__(self, *, compatible: bool = True, timeout: bool = False):
        self.compatible = compatible
        self.timeout = timeout
        self.generated_models: list[str] = []

    def list(self):
        models = [
            SimpleNamespace(
                name="models/interactions-only",
                display_name="Interactions only",
                supported_actions=["interactions"],
                input_token_limit=1000,
                output_token_limit=100,
                description="not generateContent",
            )
        ]
        if self.compatible:
            models.append(
                SimpleNamespace(
                    name="models/gemini-3.5-flash-lite",
                    display_name="Gemini 3.5 Flash-Lite",
                    supported_actions=["generateContent"],
                    input_token_limit=1000000,
                    output_token_limit=8192,
                    description="compatible",
                )
            )
        return models

    def generate_content(self, *, model, contents, config):
        self.generated_models.append(model)
        if self.timeout:
            raise TimeoutError("request timed out")
        return _FakeGeminiResponse("OK")


class _FakeGeminiResponse:
    def __init__(self, text: str):
        self.text = text
        self.usage_metadata = SimpleNamespace(model_dump=lambda **_kwargs: {"prompt_token_count": 1})

    def model_dump(self, **_kwargs):
        return {"text": self.text}


class _FakeGeminiClient:
    def __init__(self, **kwargs):
        self.models = _FakeGeminiModels(**kwargs)


def _provider_with_client(client: _FakeGeminiClient) -> GeminiProvider:
    provider = GeminiProvider(
        AIProviderConfig(provider="gemini", api_key="test-key", base_url=None, timeout_seconds=1.0)
    )
    provider._client_instance = client
    return provider


def test_gemini_valid_generate_content_model_works():
    client = _FakeGeminiClient()
    provider = _provider_with_client(client)
    response = provider.generate(
        "gemini-3.5-flash-lite",
        [{"role": "user", "content": "teste"}],
    )
    assert response.text == "OK"
    assert response.model == "gemini-3.5-flash-lite"
    assert client.models.generated_models == ["gemini-3.5-flash-lite"]


def test_gemini_incompatible_saved_model_falls_back_only_to_generate_content_model():
    client = _FakeGeminiClient()
    provider = _provider_with_client(client)
    response = provider.generate(
        "interactions-only",
        [{"role": "user", "content": "teste"}],
    )
    assert response.text == "OK"
    assert response.model == "gemini-3.5-flash-lite"
    assert client.models.generated_models == ["gemini-3.5-flash-lite"]
    assert all(model.id != "interactions-only" for model in provider.list_models())


def test_gemini_rejects_when_no_generate_content_model_exists():
    provider = _provider_with_client(_FakeGeminiClient(compatible=False))
    with pytest.raises(AIProviderError, match="Nenhum modelo Gemini compatível"):
        provider.generate("interactions-only", [{"role": "user", "content": "teste"}])


def test_gemini_timeout_is_useful_error():
    provider = _provider_with_client(_FakeGeminiClient(timeout=True))
    with pytest.raises(AIProviderError, match="Timeout"):
        provider.generate("gemini-3.5-flash-lite", [{"role": "user", "content": "teste"}])
