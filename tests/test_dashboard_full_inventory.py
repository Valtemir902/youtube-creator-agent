from __future__ import annotations

from creator_service.dashboard_routes import _collect_upload_video_ids, _load_video_details_batched


class _Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _PlaylistItems:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(dict(kwargs))
        token = kwargs.get("pageToken")
        return _Request(self.pages[token])


class _Videos:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(dict(kwargs))
        ids = [value for value in kwargs["id"].split(",") if value]
        return _Request({
            "items": [
                {
                    "id": video_id,
                    "snippet": {"title": video_id, "publishedAt": "2026-01-01T00:00:00Z"},
                    "statistics": {},
                    "status": {"privacyStatus": "public"},
                    "contentDetails": {"duration": "PT10M"},
                }
                for video_id in ids
            ]
        })


class _YouTube:
    def __init__(self, pages):
        self._playlist_items = _PlaylistItems(pages)
        self._videos = _Videos()

    def playlistItems(self):
        return self._playlist_items

    def videos(self):
        return self._videos


def _rows(*ids):
    return [{"contentDetails": {"videoId": video_id}} for video_id in ids]


def test_complete_inventory_follows_every_uploads_playlist_page_in_order():
    youtube = _YouTube({
        None: {"items": _rows("newest", "middle"), "nextPageToken": "p2"},
        "p2": {"items": _rows("older"), "nextPageToken": "p3"},
        "p3": {"items": _rows("oldest")},
    })

    ids, pages, complete = _collect_upload_video_ids(youtube, "UPLOADS")

    assert ids == ["newest", "middle", "older", "oldest"]
    assert pages == 3
    assert complete is True
    assert [call.get("pageToken") for call in youtube._playlist_items.calls] == [None, "p2", "p3"]
    assert all(call["maxResults"] == 50 for call in youtube._playlist_items.calls)


def test_inventory_deduplicates_page_boundaries_without_reordering():
    youtube = _YouTube({
        None: {"items": _rows("a", "b"), "nextPageToken": "p2"},
        "p2": {"items": _rows("b", "c")},
    })

    ids, pages, complete = _collect_upload_video_ids(youtube, "UPLOADS")

    assert ids == ["a", "b", "c"]
    assert pages == 2
    assert complete is True


def test_optional_limit_still_supports_small_internal_samples():
    youtube = _YouTube({
        None: {"items": _rows(*[f"v{i}" for i in range(10)]), "nextPageToken": "p2"},
        "p2": {"items": _rows("should-not-be-read")},
    })

    ids, pages, complete = _collect_upload_video_ids(youtube, "UPLOADS", limit=3)

    assert ids == ["v0", "v1", "v2"]
    assert pages == 1
    assert complete is False
    assert youtube._playlist_items.calls[0]["maxResults"] == 3


def test_repeated_provider_page_token_stops_safely_instead_of_looping_forever():
    youtube = _YouTube({
        None: {"items": _rows("a"), "nextPageToken": "repeat"},
        "repeat": {"items": _rows("b"), "nextPageToken": "repeat"},
    })

    ids, pages, complete = _collect_upload_video_ids(youtube, "UPLOADS")

    assert ids == ["a", "b"]
    assert pages == 2
    assert complete is False


def test_video_details_are_hydrated_in_batches_of_at_most_50():
    youtube = _YouTube({None: {"items": []}})
    ids = [f"v{i:03d}" for i in range(121)]

    by_id = _load_video_details_batched(youtube, ids)

    assert list(by_id) == ids
    assert len(youtube._videos.calls) == 3
    assert [len(call["id"].split(",")) for call in youtube._videos.calls] == [50, 50, 21]
    assert all(call["part"] == "snippet,statistics,status,contentDetails,liveStreamingDetails" for call in youtube._videos.calls)


def test_content_dashboard_requests_complete_inventory_not_first_50_only():
    from pathlib import Path

    html = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    assert "api('/api/dashboard/videos')" in html
    assert "api('/api/dashboard/videos?limit=50')" not in html
    assert 'id="contentInventoryMeta"' in html

    routes = Path("src/creator_service/dashboard_routes.py").read_text(encoding="utf-8")
    assert "async def dashboard_videos(limit: int | None = None" in routes
    assert "_collect_upload_video_ids(" in routes
    assert "_load_video_details_batched(" in routes
    assert '"inventory_complete": inventory_complete' in routes
    assert '"order": "published_at_desc"' in routes
