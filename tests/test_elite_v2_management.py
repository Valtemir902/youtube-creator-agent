from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from elite_v2_management import (
    CAPABILITY_MATRIX,
    PlaylistItemAdapter,
    PlaylistMetadataAdapter,
    ThumbnailAdapter,
    ThumbnailPayload,
    VideoDeleteAdapter,
    VideoPrivacyAdapter,
)
from elite_v2_write_gateway import ApprovalError, SafeWriteGateway, WriteState


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def content(self) -> bytes:
        return b"{}" if self.payload is not None else b""

    def json(self) -> dict[str, Any]:
        return self.payload or {}


class FakeSession:
    def __init__(self, owner: "FakeClient") -> None:
        self.owner = owner

    def request(self, method: str, url: str, **kwargs):
        self.owner.requests.append((method, url, kwargs))
        method = method.upper()
        params = kwargs.get("params") or {}
        body = kwargs.get("json") or {}
        if url.endswith("/videos") and method == "PUT":
            self.owner.video_privacy = str((body.get("status") or {}).get("privacyStatus") or self.owner.video_privacy)
            return FakeResponse(200, {"id": body.get("id")})
        if url.endswith("/videos") and method == "DELETE":
            self.owner.video_exists = False
            return FakeResponse(204, None)
        if url.endswith("/playlists") and method == "POST":
            self.owner.playlist = {
                "id": "PL_CREATED",
                "title": body["snippet"]["title"],
                "description": body["snippet"].get("description", ""),
                "privacy": body["status"]["privacyStatus"],
            }
            return FakeResponse(200, {"id": "PL_CREATED"})
        if url.endswith("/playlists") and method == "PUT":
            self.owner.playlist = {
                "id": body["id"],
                "title": body["snippet"]["title"],
                "description": body["snippet"].get("description", ""),
                "privacy": body["status"]["privacyStatus"],
            }
            return FakeResponse(200, {"id": body["id"]})
        if url.endswith("/playlists") and method == "DELETE":
            self.owner.playlist = None
            return FakeResponse(204, None)
        if url.endswith("/playlistItems") and method == "POST":
            snippet = body["snippet"]
            self.owner.playlist_item = {
                "id": "PLI_CREATED",
                "playlistId": snippet["playlistId"],
                "videoId": snippet["resourceId"]["videoId"],
                "position": int(snippet.get("position", 0)),
            }
            return FakeResponse(200, {"id": "PLI_CREATED"})
        if url.endswith("/playlistItems") and method == "PUT":
            snippet = body["snippet"]
            self.owner.playlist_item = {
                "id": body["id"],
                "playlistId": snippet["playlistId"],
                "videoId": snippet["resourceId"]["videoId"],
                "position": int(snippet.get("position", 0)),
            }
            return FakeResponse(200, {"id": body["id"]})
        if url.endswith("/playlistItems") and method == "DELETE":
            self.owner.playlist_item = None
            return FakeResponse(204, None)
        if "thumbnails/set" in url and method == "POST":
            self.owner.thumbnail_set = True
            return FakeResponse(200, {"items": [{"id": params.get("videoId")}]})
        raise AssertionError(f"request inesperada: {method} {url}")


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.session = FakeSession(self)
        self.video_privacy = "private"
        self.video_exists = True
        self.thumbnail_set = False
        self.playlist: dict[str, Any] | None = {
            "id": "PL1",
            "title": "Atual",
            "description": "Antes",
            "privacy": "private",
        }
        self.playlist_item: dict[str, Any] | None = None

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url.endswith("/videos"):
            if not self.video_exists:
                return {"items": []}
            if params.get("part") == "status":
                return {
                    "items": [
                        {
                            "id": params.get("id"),
                            "status": {
                                "privacyStatus": self.video_privacy,
                                "license": "youtube",
                                "embeddable": True,
                                "publicStatsViewable": True,
                            },
                        }
                    ]
                }
            return {
                "items": [
                    {
                        "id": params.get("id"),
                        "snippet": {"thumbnails": {"high": {"url": "https://img.local/current.jpg"}}},
                    }
                ]
            }
        if url.endswith("/playlists"):
            if not self.playlist:
                return {"items": []}
            return {
                "items": [
                    {
                        "id": self.playlist["id"],
                        "snippet": {
                            "title": self.playlist["title"],
                            "description": self.playlist["description"],
                        },
                        "status": {"privacyStatus": self.playlist["privacy"]},
                        "contentDetails": {"itemCount": 0},
                    }
                ]
            }
        if url.endswith("/playlistItems"):
            if not self.playlist_item:
                return {"items": []}
            row = self.playlist_item
            return {
                "items": [
                    {
                        "id": row["id"],
                        "snippet": {
                            "playlistId": row["playlistId"],
                            "position": row["position"],
                            "resourceId": {"videoId": row["videoId"]},
                        },
                        "contentDetails": {"videoId": row["videoId"]},
                    }
                ]
            }
        raise AssertionError(f"GET inesperado: {url}")


def test_video_privacy_requires_preview_approval_and_verifies_readback():
    client = FakeClient()
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="privacy-v1",
        target_kind="video",
        target_id="VID1",
        operation="update",
        current={"privacy_status": "private"},
        proposed={"privacy_status": "unlisted"},
        reversible=True,
    )
    with pytest.raises(ApprovalError):
        gateway.apply(proposal.proposal_id, VideoPrivacyAdapter(client))
    gateway.approve(proposal.proposal_id, token)
    result = gateway.apply(proposal.proposal_id, VideoPrivacyAdapter(client))
    assert result.state is WriteState.VERIFIED
    assert client.video_privacy == "unlisted"
    gateway.rollback(proposal.proposal_id, VideoPrivacyAdapter(client))
    assert client.video_privacy == "private"


def test_playlist_create_mutates_target_id_then_verifies_and_can_rollback():
    client = FakeClient()
    client.playlist = None
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="playlist-create-v1",
        target_kind="playlist",
        target_id="pending",
        operation="create",
        current=None,
        proposed={"title": "Nova", "description": "Teste", "privacy_status": "private"},
        reversible=True,
    )
    gateway.approve(proposal.proposal_id, token)
    result = gateway.apply(proposal.proposal_id, PlaylistMetadataAdapter(client))
    assert result.state is WriteState.VERIFIED
    assert result.target_id == "PL_CREATED"
    assert client.playlist and client.playlist["title"] == "Nova"
    gateway.rollback(proposal.proposal_id, PlaylistMetadataAdapter(client))
    assert client.playlist is None


def test_playlist_item_add_and_reorder_are_readback_verified():
    client = FakeClient()
    gateway = SafeWriteGateway()
    add, token = gateway.preview(
        idempotency_key="pli-add-v1",
        target_kind="playlist_item",
        target_id="pending",
        operation="create",
        current=None,
        proposed={"playlist_id": "PL1", "video_id": "VID1", "position": 0},
        reversible=True,
    )
    gateway.approve(add.proposal_id, token)
    gateway.apply(add.proposal_id, PlaylistItemAdapter(client))
    assert add.target_id == "PLI_CREATED"

    reorder, token2 = gateway.preview(
        idempotency_key="pli-reorder-v1",
        target_kind="playlist_item",
        target_id="PLI_CREATED",
        operation="reorder",
        current={"playlist_id": "PL1", "video_id": "VID1", "position": 0},
        proposed={"playlist_id": "PL1", "video_id": "VID1", "position": 3},
        reversible=True,
    )
    gateway.approve(reorder.proposal_id, token2)
    result = gateway.apply(reorder.proposal_id, PlaylistItemAdapter(client))
    assert result.state is WriteState.VERIFIED
    assert client.playlist_item and client.playlist_item["position"] == 3


def test_destructive_video_delete_requires_exact_target_confirmation():
    client = FakeClient()
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="delete-v1",
        target_kind="video",
        target_id="VID1",
        operation="delete",
        current={"id": "VID1"},
        proposed=None,
        reversible=False,
    )
    assert proposal.confirmation_phrase == "EXCLUIR VIDEO VID1"
    with pytest.raises(ApprovalError):
        gateway.approve(proposal.proposal_id, token, confirmation_text="EXCLUIR VIDEO OUTRO")
    gateway.approve(proposal.proposal_id, token, confirmation_text="EXCLUIR VIDEO VID1")
    result = gateway.apply(proposal.proposal_id, VideoDeleteAdapter(client))
    assert result.state is WriteState.VERIFIED
    assert client.video_exists is False


def test_thumbnail_requires_high_risk_confirmation_and_no_false_rollback():
    client = FakeClient()
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="thumb-v1",
        target_kind="thumbnail",
        target_id="VID1",
        operation="update",
        current={"thumbnail_confirmed": False},
        proposed={"thumbnail_confirmed": True},
        reversible=False,
        confirmation_phrase="SUBSTITUIR THUMBNAIL VID1",
    )
    with pytest.raises(ApprovalError):
        gateway.approve(proposal.proposal_id, token)
    gateway.approve(proposal.proposal_id, token, confirmation_text="SUBSTITUIR THUMBNAIL VID1")
    adapter = ThumbnailAdapter(client, ThumbnailPayload("VID1", b"jpeg-bytes", "image/jpeg"))
    result = gateway.apply(proposal.proposal_id, adapter)
    assert result.state is WriteState.VERIFIED
    assert adapter.writes_performed == 1
    assert client.thumbnail_set is True
    with pytest.raises(ApprovalError):
        gateway.rollback(proposal.proposal_id, adapter)


def test_capability_matrix_explicitly_declares_rollback_limits():
    assert CAPABILITY_MATRIX["video_metadata"]["rollback"] is True
    assert CAPABILITY_MATRIX["video_delete"]["rollback"] is False
    assert CAPABILITY_MATRIX["thumbnail_replace"]["high_risk"] is True
