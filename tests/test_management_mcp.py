from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from mcp import Client

from creator_service import cloud_mcp_server as base_mcp
from creator_service import cloud_mcp_server_management as management
from creator_service.publication_store import PublicationStore


SECRET = "0123456789abcdef0123456789abcdef"


class _Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Channels:
    def list(self, **_kwargs):
        return _Request(lambda: {"items": [{"id": "channel-1", "snippet": {"title": "Channel"}}]})


class _Videos:
    def list(self, **kwargs):
        ids = str(kwargs.get("id", "")).split(",")
        rows = []
        for video_id in ids:
            if not video_id:
                continue
            rows.append(
                {
                    "id": video_id,
                    "snippet": {
                        "channelId": "channel-1",
                        "title": f"Video {video_id}",
                        "description": "",
                        "tags": [],
                        "categoryId": "10",
                    },
                    "contentDetails": {"duration": "PT3M"},
                    "statistics": {"viewCount": "1"},
                    "status": {"privacyStatus": "public"},
                }
            )
        return _Request(lambda: {"items": rows})


class _Playlists:
    def __init__(self, owner):
        self.owner = owner
        self.update_calls = 0

    def list(self, **kwargs):
        playlist_id = kwargs.get("id")
        if playlist_id and playlist_id != "playlist-1":
            return _Request(lambda: {"items": []})
        item = {
            "id": "playlist-1",
            "snippet": {
                "channelId": "channel-1",
                "title": self.owner.playlist_title,
                "description": self.owner.playlist_description,
                "thumbnails": {},
            },
            "status": {"privacyStatus": self.owner.playlist_privacy},
            "contentDetails": {"itemCount": len(self.owner.members)},
        }
        return _Request(lambda: {"items": [item]})

    def update(self, *, part: str, body: dict):
        assert part == "snippet,status"
        assert body["id"] == "playlist-1"

        def apply():
            self.update_calls += 1
            self.owner.playlist_title = body["snippet"]["title"]
            self.owner.playlist_description = body["snippet"]["description"]
            self.owner.playlist_privacy = body["status"]["privacyStatus"]
            return {
                "id": "playlist-1",
                "snippet": dict(body["snippet"]),
                "status": dict(body["status"]),
            }

        return _Request(apply)


class _PlaylistItems:
    def __init__(self, owner):
        self.owner = owner
        self.next_id = 10
        self.insert_calls = 0
        self.delete_calls = 0

    def list(self, **_kwargs):
        def result():
            items = []
            for index, member in enumerate(self.owner.members):
                items.append(
                    {
                        "id": member["playlist_item_id"],
                        "snippet": {
                            "title": f"Video {member['video_id']}",
                            "position": index,
                            "resourceId": {"kind": "youtube#video", "videoId": member["video_id"]},
                            "thumbnails": {},
                        },
                        "contentDetails": {"videoId": member["video_id"]},
                    }
                )
            return {"items": items}

        return _Request(result)

    def insert(self, *, part: str, body: dict):
        assert part == "snippet"

        def apply():
            self.insert_calls += 1
            snippet = body["snippet"]
            video_id = snippet["resourceId"]["videoId"]
            item_id = f"item-{self.next_id}"
            self.next_id += 1
            position = snippet.get("position")
            row = {"playlist_item_id": item_id, "video_id": video_id}
            if position is None or int(position) >= len(self.owner.members):
                self.owner.members.append(row)
            else:
                self.owner.members.insert(max(0, int(position)), row)
            return {"id": item_id, "snippet": dict(snippet)}

        return _Request(apply)

    def delete(self, *, id: str):
        def apply():
            self.delete_calls += 1
            self.owner.members = [row for row in self.owner.members if row["playlist_item_id"] != id]
            return None

        return _Request(apply)


class _YouTube:
    def __init__(self):
        self.playlist_title = "Original Playlist"
        self.playlist_description = "Original description"
        self.playlist_privacy = "private"
        self.members = [{"playlist_item_id": "item-1", "video_id": "video-1"}]
        self._channels = _Channels()
        self._videos = _Videos()
        self._playlists = _Playlists(self)
        self._playlist_items = _PlaylistItems(self)

    def channels(self):
        return self._channels

    def videos(self):
        return self._videos

    def playlists(self):
        return self._playlists

    def playlistItems(self):
        return self._playlist_items


class _Service:
    def __init__(self, youtube):
        self.youtube = youtube
        self.context = SimpleNamespace(tenant_id="tenant-1")

    def _youtube(self):
        return self.youtube

    def _authorized_channel_id(self):
        return "channel-1"

    def _owned_video_item(self, video_id: str, *, part: str):
        item = self.youtube.videos().list(part=part, id=video_id).execute()["items"][0]
        assert item["snippet"]["channelId"] == "channel-1"
        return item


def _payload(result):
    assert not result.is_error
    assert result.content
    return json.loads(result.content[0].text)


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("YCA_APPROVAL_SECRET", SECRET)
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.test")
    monkeypatch.setenv("YCA_CHATGPT_OAUTH_ISSUER_URL", "https://creator.example.test")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://mcp.example.test/mcp")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.test/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "secret")
    youtube = _YouTube()
    service = _Service(youtube)
    store = PublicationStore(tmp_path / "operations.sqlite3")
    monkeypatch.setattr(base_mcp, "_require_scope", lambda _scope: None)
    monkeypatch.setattr(base_mcp, "_limit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(base_mcp, "_tenant_id", lambda: "tenant-1")
    monkeypatch.setattr(base_mcp, "_ops_store", lambda: store)
    monkeypatch.setattr(management, "_service", lambda: service)
    return youtube


def test_playlist_metadata_apply_rollback_and_replay(monkeypatch, tmp_path):
    youtube = _setup(monkeypatch, tmp_path)

    async def scenario():
        async with Client(management.create_server(), raise_exceptions=True) as client:
            preview = _payload(
                await client.call_tool(
                    "preview_playlist_metadata_update",
                    {
                        "playlist_id": "playlist-1",
                        "title": "Dark Country Essentials",
                        "description": "A stronger description",
                        "privacy_status": "public",
                    },
                )
            )
            assert preview["success"] is True
            assert preview["changed"] == {"title": True, "description": True, "privacy_status": True}

            apply_args = {
                "approval_payload": preview["approval_payload"],
                "approval_token": preview["approval_token"],
                "user_confirmed": True,
            }
            applied = _payload(await client.call_tool("apply_playlist_metadata_update", apply_args))
            assert applied["success"] is True
            assert applied["persisted_verified"] is True
            assert youtube.playlist_title == "Dark Country Essentials"
            assert youtube.playlist_privacy == "public"

            replay = _payload(await client.call_tool("apply_playlist_metadata_update", apply_args))
            assert replay["success"] is False
            assert replay["error"]["code"] == "approval_replayed"
            assert youtube._playlists.update_calls == 1

            rollback = applied["rollback_preview"]
            restored = _payload(
                await client.call_tool(
                    "apply_playlist_metadata_rollback",
                    {
                        "rollback_payload": rollback["rollback_payload"],
                        "rollback_token": rollback["rollback_token"],
                        "user_confirmed": True,
                    },
                )
            )
            assert restored["success"] is True
            assert restored["persisted_verified"] is True
            assert youtube.playlist_title == "Original Playlist"
            assert youtube.playlist_description == "Original description"
            assert youtube.playlist_privacy == "private"

    asyncio.run(scenario())


def test_playlist_item_add_and_signed_rollback(monkeypatch, tmp_path):
    youtube = _setup(monkeypatch, tmp_path)

    async def scenario():
        async with Client(management.create_server(), raise_exceptions=True) as client:
            preview = _payload(
                await client.call_tool(
                    "preview_playlist_item_add",
                    {"playlist_id": "playlist-1", "video_id": "video-2", "position": 1},
                )
            )
            assert preview["already_present"] is False
            applied = _payload(
                await client.call_tool(
                    "apply_playlist_item_add",
                    {
                        "approval_payload": preview["approval_payload"],
                        "approval_token": preview["approval_token"],
                        "user_confirmed": True,
                    },
                )
            )
            assert applied["persisted_verified"] is True
            assert [row["video_id"] for row in youtube.members] == ["video-1", "video-2"]

            rollback = applied["rollback_preview"]
            restored = _payload(
                await client.call_tool(
                    "apply_playlist_item_add_rollback",
                    {
                        "rollback_payload": rollback["rollback_payload"],
                        "rollback_token": rollback["rollback_token"],
                        "user_confirmed": True,
                    },
                )
            )
            assert restored["rolled_back"] is True
            assert restored["persisted_verified"] is True
            assert [row["video_id"] for row in youtube.members] == ["video-1"]

    asyncio.run(scenario())


def test_playlist_item_remove_and_signed_rollback(monkeypatch, tmp_path):
    youtube = _setup(monkeypatch, tmp_path)

    async def scenario():
        async with Client(management.create_server(), raise_exceptions=True) as client:
            preview = _payload(
                await client.call_tool(
                    "preview_playlist_item_remove",
                    {"playlist_id": "playlist-1", "video_id": "video-1"},
                )
            )
            assert preview["already_absent"] is False
            applied = _payload(
                await client.call_tool(
                    "apply_playlist_item_remove",
                    {
                        "approval_payload": preview["approval_payload"],
                        "approval_token": preview["approval_token"],
                        "user_confirmed": True,
                    },
                )
            )
            assert applied["persisted_verified"] is True
            assert youtube.members == []

            rollback = applied["rollback_preview"]
            restored = _payload(
                await client.call_tool(
                    "apply_playlist_item_remove_rollback",
                    {
                        "rollback_payload": rollback["rollback_payload"],
                        "rollback_token": rollback["rollback_token"],
                        "user_confirmed": True,
                    },
                )
            )
            assert restored["rolled_back"] is True
            assert restored["persisted_verified"] is True
            assert [row["video_id"] for row in youtube.members] == ["video-1"]

    asyncio.run(scenario())
