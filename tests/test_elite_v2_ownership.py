from __future__ import annotations

import pytest

from elite_v2_ownership import (
    require_owned_playlist,
    require_owned_playlist_item,
    require_owned_video,
    require_proposal_ownership,
)
from elite_v2_youtube_writes import YouTubeWriteError


class FakeClient:
    def __init__(self, *, channel_id="CHAN1", video_owner="CHAN1", playlist_owner="CHAN1") -> None:
        self.channel_id = channel_id
        self.video_owner = video_owner
        self.playlist_owner = playlist_owner

    def channel_identity(self):
        return {"id": self.channel_id}

    def video_details(self, video_id):
        return {"id": video_id, "snippet": {"channelId": self.video_owner, "title": "Teste"}}

    def _get(self, url, params):
        if url.endswith("/playlists"):
            return {
                "items": [
                    {
                        "id": params.get("id"),
                        "snippet": {"channelId": self.playlist_owner, "title": "Playlist"},
                        "status": {"privacyStatus": "private"},
                        "contentDetails": {"itemCount": 1},
                    }
                ]
            }
        if url.endswith("/playlistItems"):
            return {
                "items": [
                    {
                        "id": params.get("id"),
                        "snippet": {"playlistId": "PL1", "position": 0, "resourceId": {"videoId": "VID1"}},
                        "contentDetails": {"videoId": "VID1"},
                    }
                ]
            }
        raise AssertionError(url)


def test_owned_video_and_playlist_are_allowed() -> None:
    client = FakeClient()
    assert require_owned_video(client, "VID1")["id"] == "VID1"
    assert require_owned_playlist(client, "PL1")["id"] == "PL1"
    assert require_owned_playlist_item(client, "PLI1")["id"] == "PLI1"


def test_foreign_video_is_rejected_before_mutation() -> None:
    client = FakeClient(video_owner="FOREIGN")
    with pytest.raises(YouTubeWriteError, match="não pertence"):
        require_owned_video(client, "VID1")
    with pytest.raises(YouTubeWriteError, match="não pertence"):
        require_proposal_ownership(client, "video", "VID1", "delete", None)


def test_foreign_playlist_and_items_are_rejected_before_mutation() -> None:
    client = FakeClient(playlist_owner="FOREIGN")
    with pytest.raises(YouTubeWriteError, match="não pertence"):
        require_owned_playlist(client, "PL1")
    with pytest.raises(YouTubeWriteError, match="não pertence"):
        require_owned_playlist_item(client, "PLI1")
    with pytest.raises(YouTubeWriteError, match="não pertence"):
        require_proposal_ownership(
            client,
            "playlist_item",
            "pending",
            "create",
            {"playlist_id": "PL1", "video_id": "VID1"},
        )
