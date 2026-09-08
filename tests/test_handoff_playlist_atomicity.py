from __future__ import annotations

import pytest

from creator_service.handoff_routes import _add_playlist_item_verified, _remove_playlist_item_verified
from intelligence.creator_memory import CreatorMemoryStore


class _Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class _Playlists:
    def __init__(self, owner):
        self.owner = owner

    def list(self, **_kwargs):
        return _Request(
            lambda: {
                "items": [
                    {
                        "id": "playlist-1",
                        "snippet": {"channelId": self.owner.channel_id, "title": "Safe playlist"},
                    }
                ]
            }
        )


class _PlaylistItems:
    def __init__(self, owner):
        self.owner = owner

    def list(self, **_kwargs):
        def read():
            self.owner.list_calls += 1
            if self.owner.fail_readback_after_insert and self.owner.insert_calls:
                raise RuntimeError("playlist readback unavailable")
            return {
                "items": [
                    {
                        "id": row["playlist_item_id"],
                        "snippet": {
                            "resourceId": {"kind": "youtube#video", "videoId": row["video_id"]}
                        },
                        "contentDetails": {"videoId": row["video_id"]},
                    }
                    for row in self.owner.members
                ]
            }

        return _Request(read)

    def insert(self, **_kwargs):
        def apply():
            self.owner.insert_calls += 1
            if self.owner.concurrent_insert:
                self.owner.members.append(
                    {"playlist_item_id": "external-1", "video_id": self.owner.video_id}
                )
            self.owner.members.append(
                {"playlist_item_id": "ours-1", "video_id": self.owner.video_id}
            )
            if self.owner.transport_fails_after_accept:
                raise RuntimeError("transport lost after insert")
            return {"id": "ours-1"}

        return _Request(apply)

    def delete(self, *, id: str):
        def apply():
            self.owner.delete_calls.append(id)
            self.owner.members = [row for row in self.owner.members if row["playlist_item_id"] != id]
            if self.owner.delete_transport_fails_after_accept:
                raise RuntimeError("transport lost after delete")
            return {}

        return _Request(apply)


class _FakeYouTube:
    def __init__(self):
        self.channel_id = "channel-1"
        self.video_id = "video-1"
        self.members: list[dict[str, str]] = []
        self.insert_calls = 0
        self.list_calls = 0
        self.delete_calls: list[str] = []
        self.concurrent_insert = False
        self.transport_fails_after_accept = False
        self.delete_transport_fails_after_accept = False
        self.fail_readback_after_insert = False
        self._playlists = _Playlists(self)
        self._playlist_items = _PlaylistItems(self)

    def playlists(self):
        return self._playlists

    def playlistItems(self):
        return self._playlist_items


class _Context:
    tenant_id = "tenant-1"


class _Service:
    def __init__(self, tmp_path):
        self.context = _Context()
        self.memory = CreatorMemoryStore(tmp_path / "memory.sqlite3")
        self.youtube = _FakeYouTube()

    def _youtube(self):
        return self.youtube

    def _authorized_channel_id(self):
        return self.youtube.channel_id


def test_existing_playlist_membership_never_inserts(tmp_path):
    service = _Service(tmp_path)
    service.youtube.members = [{"playlist_item_id": "existing-1", "video_id": "video-1"}]

    result = _add_playlist_item_verified(
        service,
        playlist_id="playlist-1",
        video_id="video-1",
    )

    assert result["already_present"] is True
    assert result["playlist_item_id"] == "existing-1"
    assert service.youtube.insert_calls == 0


def test_concurrent_duplicate_is_compensated_without_deleting_external_item(tmp_path):
    service = _Service(tmp_path)
    service.youtube.concurrent_insert = True

    result = _add_playlist_item_verified(
        service,
        playlist_id="playlist-1",
        video_id="video-1",
    )

    assert result["persisted_verified"] is True
    assert result["concurrent_duplicate_prevented"] is True
    assert result["playlist_item_id"] == "external-1"
    assert service.youtube.insert_calls == 1
    assert service.youtube.delete_calls == ["ours-1"]
    assert service.youtube.members == [
        {"playlist_item_id": "external-1", "video_id": "video-1"}
    ]


def test_lost_insert_response_is_reconciled_without_retry(tmp_path):
    service = _Service(tmp_path)
    service.youtube.transport_fails_after_accept = True

    result = _add_playlist_item_verified(
        service,
        playlist_id="playlist-1",
        video_id="video-1",
    )

    assert result["persisted_verified"] is True
    assert result["recovered_from_ambiguous_response"] is True
    assert result["playlist_item_id"] == "ours-1"
    assert service.youtube.insert_calls == 1
    assert len(service.youtube.members) == 1


def test_readback_failure_never_retries_insert_and_records_protection(tmp_path):
    service = _Service(tmp_path)
    service.youtube.fail_readback_after_insert = True

    with pytest.raises(RuntimeError, match="não duplicar"):
        _add_playlist_item_verified(
            service,
            playlist_id="playlist-1",
            video_id="video-1",
        )

    assert service.youtube.insert_calls == 1
    assert len(service.youtube.members) == 1
    state = service.memory.recent_edit_state("video-1")
    assert state.protected is True
    assert state.last_action_type == "playlist_write_ambiguous_state"


def test_delete_lost_response_is_reconciled_without_retry(tmp_path):
    service = _Service(tmp_path)
    service.youtube.members = [{"playlist_item_id": "ours-1", "video_id": "video-1"}]
    service.youtube.delete_transport_fails_after_accept = True

    result = _remove_playlist_item_verified(
        service,
        playlist_id="playlist-1",
        video_id="video-1",
        playlist_item_id="ours-1",
    )

    assert result["persisted_verified"] is True
    assert result["recovered_from_ambiguous_response"] is True
    assert service.youtube.delete_calls == ["ours-1"]
    assert service.youtube.members == []