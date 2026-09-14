from __future__ import annotations

import pytest

from elite_v2_write_gateway import ApprovalError, SafeWriteGateway, VerificationError, WriteState


class FakeAdapter:
    def __init__(self, initial=None, *, mismatch=False):
        self.state = initial
        self.applies = 0
        self.rollbacks = 0
        self.mismatch = mismatch

    def apply(self, proposal):
        self.applies += 1
        if proposal.operation == "delete":
            self.state = None
        else:
            self.state = dict(proposal.proposed or {})

    def readback(self, proposal):
        if self.mismatch and self.state is not None:
            return {**self.state, "title": "estado divergente"}
        return None if self.state is None else dict(self.state)

    def rollback(self, proposal, snapshot):
        self.rollbacks += 1
        self.state = None if snapshot is None else dict(snapshot)


def test_preview_does_not_apply_and_requires_exact_approval_token() -> None:
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="video-abc-title-v1",
        target_kind="video",
        target_id="abc",
        operation="update",
        current={"title": "Antes"},
        proposed={"title": "Depois"},
    )
    adapter = FakeAdapter({"title": "Antes"})
    assert proposal.state is WriteState.AWAITING_APPROVAL
    assert adapter.applies == 0
    with pytest.raises(ApprovalError):
        gateway.approve(proposal.proposal_id, "token-errado")
    gateway.approve(proposal.proposal_id, token)
    assert proposal.state is WriteState.APPROVED
    assert adapter.applies == 0


def test_apply_requires_approval_and_verifies_readback() -> None:
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="video-abc-description-v1",
        target_kind="video",
        target_id="abc",
        operation="update",
        current={"description": "A"},
        proposed={"description": "B"},
    )
    adapter = FakeAdapter({"description": "A"})
    with pytest.raises(ApprovalError):
        gateway.apply(proposal.proposal_id, adapter)
    gateway.approve(proposal.proposal_id, token)
    gateway.apply(proposal.proposal_id, adapter)
    assert proposal.state is WriteState.VERIFIED
    assert adapter.state == {"description": "B"}
    assert any(event["event"] == "readback_verified" for event in gateway.audit)


def test_readback_mismatch_marks_failure_instead_of_claiming_success() -> None:
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="video-abc-title-v2",
        target_kind="video",
        target_id="abc",
        operation="update",
        current={"title": "Antes"},
        proposed={"title": "Depois"},
    )
    gateway.approve(proposal.proposal_id, token)
    with pytest.raises(VerificationError):
        gateway.apply(proposal.proposal_id, FakeAdapter({"title": "Antes"}, mismatch=True))
    assert proposal.state is WriteState.FAILED
    assert "readback" in (proposal.failure or "")


def test_destructive_delete_requires_target_specific_confirmation_and_has_no_rollback() -> None:
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="delete-playlist-xyz-v1",
        target_kind="playlist",
        target_id="xyz",
        operation="delete",
        current={"title": "Minha playlist"},
        proposed=None,
    )
    assert proposal.reversible is False
    assert proposal.confirmation_phrase == "EXCLUIR PLAYLIST xyz"
    with pytest.raises(ApprovalError):
        gateway.approve(proposal.proposal_id, token, confirmation_text="EXCLUIR")
    gateway.approve(proposal.proposal_id, token, confirmation_text=proposal.confirmation_phrase)
    adapter = FakeAdapter({"title": "Minha playlist"})
    gateway.apply(proposal.proposal_id, adapter)
    assert proposal.state is WriteState.VERIFIED
    with pytest.raises(ApprovalError):
        gateway.rollback(proposal.proposal_id, adapter)


def test_reversible_verified_change_can_be_rolled_back_explicitly() -> None:
    gateway = SafeWriteGateway()
    proposal, token = gateway.preview(
        idempotency_key="video-abc-tags-v1",
        target_kind="video",
        target_id="abc",
        operation="update",
        current={"tags": ["a"]},
        proposed={"tags": ["a", "b"]},
    )
    adapter = FakeAdapter({"tags": ["a"]})
    gateway.approve(proposal.proposal_id, token)
    gateway.apply(proposal.proposal_id, adapter)
    gateway.rollback(proposal.proposal_id, adapter)
    assert proposal.state is WriteState.ROLLED_BACK
    assert adapter.state == {"tags": ["a"]}
    assert adapter.rollbacks == 1


def test_idempotency_key_cannot_silently_create_second_proposal() -> None:
    gateway = SafeWriteGateway()
    gateway.preview(
        idempotency_key="same-key",
        target_kind="video",
        target_id="abc",
        operation="update",
        current={"title": "A"},
        proposed={"title": "B"},
    )
    with pytest.raises(ValueError, match="idempotency_key"):
        gateway.preview(
            idempotency_key="same-key",
            target_kind="video",
            target_id="abc",
            operation="update",
            current={"title": "A"},
            proposed={"title": "C"},
        )
