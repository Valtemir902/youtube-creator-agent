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
        self.deleted_ids: list[str] = []

    def insert(self, **kwargs):
        self.insert_calls += 1
        return _Request({"id": "PL-created"})

    def delete(self, **kwargs):
        self.delete_calls += 1
        self.deleted_ids.append(kwargs["id"])
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
    monkeypatch.setattr(consistency, "_DELETE_CONFIRM_DELAYS_SECONDS", (0, 0))
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
    assert service.youtube.playlists_api.deleted_ids == ["PL-created"]


def test_delete_once_retries_only_absence_confirmation_until_not_found(monkeypatch):
    service = _Service()
    reads: list[str] = []

    def owned(_service, playlist_id):
        reads.append(playlist_id)
        assert playlist_id == "PL-created"
        if len(reads) < 3:
            return {"id": playlist_id}
        raise CreatorToolError("playlist_not_found", "gone")

    monkeypatch.setattr(consistency, "_DELETE_CONFIRM_DELAYS_SECONDS", (0, 0, 0))
    monkeypatch.setattr(consistency.management, "_owned_playlist", owned)

    consistency._delete_playlist_once_and_confirm(
        service,
        "PL-created",
        failure_message="YouTube did not confirm deletion.",
    )

    assert reads == ["PL-created", "PL-created", "PL-created"]
    assert service.youtube.playlists_api.delete_calls == 1
    assert service.youtube.playlists_api.deleted_ids == ["PL-created"]


def test_delete_once_returns_youtube_api_error_when_all_bounded_reads_still_find_playlist(monkeypatch):
    service = _Service()
    reads: list[str] = []

    def owned(_service, playlist_id):
        reads.append(playlist_id)
        return {"id": playlist_id}

    monkeypatch.setattr(consistency, "_DELETE_CONFIRM_DELAYS_SECONDS", (0, 0))
    monkeypatch.setattr(consistency.management, "_owned_playlist", owned)

    with pytest.raises(CreatorToolError) as caught:
        consistency._delete_playlist_once_and_confirm(
            service,
            "PL-created",
            failure_message="YouTube did not confirm playlist deletion.",
        )

    assert caught.value.code == "youtube_api_error"
    assert "did not confirm" in caught.value.message
    assert reads == ["PL-created", "PL-created", "PL-created"]
    assert service.youtube.playlists_api.delete_calls == 1
    assert service.youtube.playlists_api.deleted_ids == ["PL-created"]


def test_delete_confirmation_propagates_non_not_found_read_error_without_retrying_delete(monkeypatch):
    service = _Service()

    monkeypatch.setattr(consistency, "_DELETE_CONFIRM_DELAYS_SECONDS", (0, 0))
    monkeypatch.setattr(
        consistency.management,
        "_owned_playlist",
        lambda service, playlist_id: (_ for _ in ()).throw(CreatorToolError("playlist_not_owned", "wrong owner")),
    )

    with pytest.raises(CreatorToolError) as caught:
        consistency._delete_playlist_once_and_confirm(
            service,
            "PL-created",
            failure_message="YouTube did not confirm playlist deletion.",
        )

    assert caught.value.code == "playlist_not_owned"
    assert service.youtube.playlists_api.delete_calls == 1
    assert service.youtube.playlists_api.deleted_ids == ["PL-created"]
    assert "PL-real-do-not-touch" not in service.youtube.playlists_api.deleted_ids


def test_install_replaces_create_and_growth_extension_without_changing_public_names(monkeypatch):
    monkeypatch.setattr(consistency.growth, "_create_playlist", object())
    monkeypatch.setattr(consistency.growth, "extend_server", consistency._ORIGINAL_EXTEND_SERVER)

    consistency.install()

    assert consistency.growth._create_playlist is consistency._create_playlist_consistent
    assert consistency.growth.extend_server is consistency._extend_server_consistent
