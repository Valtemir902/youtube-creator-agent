from __future__ import annotations

import pytest

from creator_service import cloud_mcp_server_playlist_consistency as consistency
from creator_service.mcp_errors import CreatorToolError


class _Request:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class _Playlists:
    def __init__(self):
        self.insert_calls = 0
        self.delete_calls = 0

    def insert(self, **kwargs):
        self.insert_calls += 1
        return _Request({"id": "PL-created"})

    def delete(self, **kwargs):
        assert kwargs["id"] == "PL-created"
        self.delete_calls += 1
        return _Request({})


class _PlaylistItems:
    def insert(self, **kwargs):
        return _Request({})


class _YouTube:
    def __init__(self):
        self.playlists_api = _Playlists()
        self.items_api = _PlaylistItems()

    def playlists(self):
        return self.playlists_api

    def playlistItems(self):
        return self.items_api


class _Service:
    def __init__(self):
        self.youtube = _YouTube()

    def _youtube(self):
        return self.youtube


PROPOSED = {
    "title": "YCA Test",
    "description": "temporary",
    "privacy_status": "private",
    "default_language": None,
    "video_ids": [],
}


def test_create_retries_readback_without_retrying_insert(monkeypatch):
    service = _Service()
    attempts = {"snapshot": 0}

    def snapshot(_service, playlist_id):
        assert playlist_id == "PL-created"
        attempts["snapshot"] += 1
        if attempts["snapshot"] < 3:
            raise CreatorToolError("playlist_not_found", "not visible yet")
        return {
            "playlist_id": playlist_id,
            "title": "YCA Test",
            "description": "temporary",
            "privacy_status": "private",
        }

    monkeypatch.setattr(consistency, "_READBACK_DELAYS_SECONDS", (0, 0, 0))
    monkeypatch.setattr(consistency.management, "_playlist_snapshot", snapshot)
    monkeypatch.setattr(consistency.management, "_playlist_membership", lambda service, playlist_id: [])

    result = consistency._create_playlist_consistent(service, PROPOSED)

    assert result["playlist_id"] == "PL-created"
    assert attempts["snapshot"] == 3
    assert service.youtube.playlists_api.insert_calls == 1
    assert service.youtube.playlists_api.delete_calls == 0


def test_create_compensates_exact_new_playlist_when_readback_never_appears(monkeypatch):
    service = _Service()

    monkeypatch.setattr(consistency, "_READBACK_DELAYS_SECONDS", (0, 0))
    monkeypatch.setattr(
        consistency.management,
        "_playlist_snapshot",
        lambda service, playlist_id: (_ for _ in ()).throw(CreatorToolError("playlist_not_found", "not visible")),
    )
    monkeypatch.setattr(
        consistency.management,
        "_owned_playlist",
        lambda service, playlist_id: (_ for _ in ()).throw(CreatorToolError("playlist_not_found", "gone")),
    )

    with pytest.raises(CreatorToolError) as caught:
        consistency._create_playlist_consistent(service, PROPOSED)

    assert caught.value.code == "youtube_api_error"
    assert "accepted playlist creation" in caught.value.message
    assert "Compensation delete was verified" in caught.value.message
    assert service.youtube.playlists_api.insert_calls == 1
    assert service.youtube.playlists_api.delete_calls == 1


def test_install_replaces_helper_without_changing_tool_definitions(monkeypatch):
    monkeypatch.setattr(consistency.growth, "_create_playlist", object())
    consistency.install()
    assert consistency.growth._create_playlist is consistency._create_playlist_consistent
