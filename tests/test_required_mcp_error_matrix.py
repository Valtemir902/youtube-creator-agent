from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

from mcp import Client

from creator_service import cloud_mcp_server as mcp_base
from creator_service import mcp_errors


def _payload(result):
    assert not result.is_error
    assert result.content
    return json.loads(result.content[0].text)


def _mcp_env(monkeypatch):
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.test")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.test")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example.test/mcp")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.test/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "secret")


def test_creator_status_and_list_connected_channels_return_real_structured_payloads(monkeypatch):
    _mcp_env(monkeypatch)
    monkeypatch.setattr(mcp_base, "_require_scope", lambda _scope: None)
    monkeypatch.setattr(mcp_base, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(mcp_base, "_tenant_id", lambda: "tenant-1")
    monkeypatch.setattr(
        mcp_base,
        "_service",
        lambda: SimpleNamespace(status=lambda: {"youtube_connected": True, "chatgpt_native_ready": True}),
    )
    monkeypatch.setattr(mcp_base, "_resolver", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(
        mcp_base,
        "list_channel_accounts",
        lambda _db, tenant_id: {
            "active_channel_id": "channel-1",
            "channels": [{"id": "channel-1", "title": "Logan Western", "active": True}],
            "tenant_seen": tenant_id,
        },
    )

    async def scenario():
        async with Client(mcp_base.create_server(), raise_exceptions=True) as client:
            status = _payload(await client.call_tool("creator_status", {}))
            assert status["youtube_connected"] is True
            assert status["chatgpt_native_ready"] is True

            channels = _payload(await client.call_tool("list_connected_channels", {}))
            assert channels["active_channel_id"] == "channel-1"
            assert channels["channels"][0]["title"] == "Logan Western"
            assert channels["tenant_seen"] == "tenant-1"

    asyncio.run(scenario())


def test_missing_yca_write_scope_is_typed(monkeypatch):
    monkeypatch.setattr(
        mcp_base,
        "_access_token",
        lambda: SimpleNamespace(scopes=["yca:read"], claims={"tenant_id": "tenant-1"}),
    )
    try:
        mcp_base._require_scope(mcp_base.WRITE_SCOPE)
    except mcp_errors.CreatorToolError as exc:
        assert exc.code == "write_scope_missing"
    else:  # pragma: no cover
        raise AssertionError("missing yca:write must be rejected")


def test_database_error_is_structured():
    response = mcp_errors.error_response(sqlite3.DatabaseError("disk I/O error"))
    assert response == {
        "success": False,
        "error": {
            "code": "database_error",
            "message": "The operation could not be completed because of a database error.",
        },
    }


def test_youtube_api_error_is_structured(monkeypatch):
    class FakeHttpError(Exception):
        pass

    monkeypatch.setattr(mcp_errors, "HttpError", FakeHttpError)
    response = mcp_errors.error_response(FakeHttpError("403 forbidden secret detail"))
    assert response["success"] is False
    assert response["error"]["code"] == "youtube_api_error"
    assert "secret detail" not in response["error"]["message"]


def test_incompatible_ai_model_is_structured():
    response = mcp_errors.error_response(RuntimeError("This model only supports Interactions API"))
    assert response["success"] is False
    assert response["error"]["code"] == "unsupported_ai_model"
