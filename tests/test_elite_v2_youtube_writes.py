from __future__ import annotations

from dataclasses import dataclass

import pytest

from elite_v2_write_gateway import SafeWriteGateway, WriteState
from elite_v2_youtube_writes import ManualWriteSessionGate, YouTubeVideoMetadataAdapter, YouTubeWriteError


class FakeResponse:
    def __init__(self, payload=None, *, status=200):
        self._payload = payload or {}
        self.status_code = status
        self.ok = 200 <= status < 300
        self.content = b"{}"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse({"id": kwargs["json"]["id"]})


@dataclass
class FakeClient:
    session: FakeSession
    snippet: dict

    def video_details(self, video_id):
        return {"snippet": dict(self.snippet)}


def test_manual_write_gate_starts_disabled_and_requires_exact_confirmation() -> None:
    gate = ManualWriteSessionGate()
    assert gate.enabled is False
    with pytest.raises(PermissionError):
        gate.set_enabled(True, confirmation="sim")
    assert gate.enabled is False
    assert gate.set_enabled(True, confirmation=ManualWriteSessionGate.CONFIRMATION) is True
    assert gate.set_enabled(False) is False


def test_metadata_adapter_preserves_required_category_and_languages() -> None:
    session = FakeSession()
    client = FakeClient(
        session,
        {
            "title": "Antes",
            "description": "Descrição",
            "tags": ["a"],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
            "defaultAudioLanguage": "pt-BR",
        },
    )
    adapter = YouTubeVideoMetadataAdapter(client)  # type: ignore[arg-type]
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="meta-v1",
        target_kind="video",
        target_id="abc",
        operation="update",
        current={"title": "Antes", "description": "Descrição", "tags": ["a"]},
        proposed={"title": "Depois", "description": "Descrição", "tags": ["a", "b"]},
    )
    gateway.approve(proposal.proposal_id, token)

    # The fake readback remains old, so call the adapter directly here to inspect
    # the exact request shape without pretending a verification succeeded.
    adapter.apply(proposal)
    method, url, kwargs = session.calls[0]
    assert method == "PUT"
    assert url.endswith("/videos")
    assert kwargs["params"] == {"part": "snippet"}
    body = kwargs["json"]
    assert body["id"] == "abc"
    assert body["snippet"]["title"] == "Depois"
    assert body["snippet"]["categoryId"] == "22"
    assert body["snippet"]["defaultLanguage"] == "pt-BR"
    assert body["snippet"]["defaultAudioLanguage"] == "pt-BR"
    assert adapter.writes_performed == 1
    assert proposal.state is WriteState.APPROVED


def test_metadata_adapter_blocks_update_if_required_category_is_missing() -> None:
    adapter = YouTubeVideoMetadataAdapter(FakeClient(FakeSession(), {"title": "A"}))  # type: ignore[arg-type]
    gateway = SafeWriteGateway()
    proposal, _ = gateway.preview(
        idempotency_key="meta-v2",
        target_kind="video",
        target_id="abc",
        operation="update",
        current={"title": "A"},
        proposed={"title": "B"},
    )
    with pytest.raises(YouTubeWriteError, match="categoryId"):
        adapter.apply(proposal)
