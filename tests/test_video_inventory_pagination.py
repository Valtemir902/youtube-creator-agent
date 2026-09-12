from __future__ import annotations

from creator_service import cloud_mcp_server_inventory as inventory


class _Execute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Channels:
    def list(self, **kwargs):
        return _Execute(
            {
                "items": [
                    {
                        "id": "channel-1",
                        "snippet": {"title": "Channel"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "uploads-1"}},
                        "statistics": {"videoCount": "2"},
                    }
                ]
            }
        )


class _PlaylistItems:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(dict(kwargs))
        token = kwargs.get("pageToken")
        if token is None:
            return _Execute(
                {
                    "items": [
                        {"id": "pi-1", "snippet": {"resourceId": {"videoId": "v1"}}, "contentDetails": {"videoId": "v1"}},
                        {"id": "pi-2", "snippet": {"resourceId": {"videoId": "v2"}}, "contentDetails": {"videoId": "v2"}},
                    ],
                    "nextPageToken": "UPSTREAM-2",
                }
            )
        assert token == "UPSTREAM-2"
        return _Execute(
            {
                "items": [
                    {"id": "pi-2b", "snippet": {"resourceId": {"videoId": "v2"}}, "contentDetails": {"videoId": "v2"}},
                    {"id": "pi-3", "snippet": {"resourceId": {"videoId": "v3"}}, "contentDetails": {"videoId": "v3"}},
                ]
            }
        )


class _Videos:
    def list(self, **kwargs):
        ids = [value for value in str(kwargs.get("id", "")).split(",") if value]
        items = []
        for video_id in ids:
            privacy = "unlisted" if video_id == "v3" else "public"
            items.append(
                {
                    "id": video_id,
                    "snippet": {"channelId": "channel-1", "title": f"Video {video_id}", "thumbnails": {}},
                    "contentDetails": {"duration": "PT1M"},
                    "statistics": {},
                    "status": {"privacyStatus": privacy},
                }
            )
        return _Execute({"items": items})


class _YouTube:
    def __init__(self):
        self.playlist_items = _PlaylistItems()

    def channels(self):
        return _Channels()

    def playlistItems(self):
        return self.playlist_items

    def videos(self):
        return _Videos()


class _Service:
    def __init__(self):
        self.youtube = _YouTube()

    def _youtube(self):
        return self.youtube


def test_cursor_round_trip_and_raw_token_compatibility():
    token = inventory._encode_cursor(
        upstream_token="NEXT",
        previous_video_ids=["v1", "v2"],
        uploads_playlist_id="uploads-1",
    )
    upstream, previous, playlist = inventory._decode_cursor(token)
    assert upstream == "NEXT"
    assert previous == {"v1", "v2"}
    assert playlist == "uploads-1"

    upstream, previous, playlist = inventory._decode_cursor("legacy-raw-token")
    assert upstream == "legacy-raw-token"
    assert previous == set()
    assert playlist is None


def test_forward_pagination_deduplicates_boundary_and_explains_count_scope():
    service = _Service()
    first = inventory._list_channel_videos_stable(service, max_results=2)
    assert [row["video_id"] for row in first["videos"]] == ["v1", "v2"]
    assert first["public_video_count"] == 2
    assert first["public_video_count_scope"] == "public_only_even_for_channel_owner"
    assert first["inventory_scope"] == "owner_accessible_uploads_playlist"
    assert first["next_page_token"].startswith("yca-videos-v1.")

    second = inventory._list_channel_videos_stable(
        service,
        max_results=2,
        page_token=first["next_page_token"],
    )
    assert [row["video_id"] for row in second["videos"]] == ["v3"]
    assert second["deduplicated_boundary_count"] == 1
    assert second["deduplicated_video_ids"] == ["v2"]
    assert second["non_public_returned_count"] == 1
    assert second["next_page_token"] is None
    assert "public videos only" in second["count_explanation"]


def test_cursor_is_bound_to_uploads_playlist():
    token = inventory._encode_cursor(
        upstream_token="NEXT",
        previous_video_ids=["v1"],
        uploads_playlist_id="different-uploads",
    )
    try:
        inventory._list_channel_videos_stable(_Service(), max_results=2, page_token=token)
    except Exception as exc:
        assert getattr(exc, "code", None) == "invalid_request"
    else:
        raise AssertionError("Expected invalid_request for cursor bound to a different uploads playlist")
