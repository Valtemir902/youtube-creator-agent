from __future__ import annotations

import hashlib
import hmac
import secrets
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4


class WriteState(StrEnum):
    DRAFT = "draft"
    PREVIEWED = "previewed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    APPLYING = "applying"
    VERIFIED = "verified"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class WriteAdapter(Protocol):
    def apply(self, proposal: "WriteProposal") -> None: ...
    def readback(self, proposal: "WriteProposal") -> dict[str, Any] | None: ...
    def rollback(self, proposal: "WriteProposal", snapshot: dict[str, Any] | None) -> None: ...


@dataclass(slots=True)
class WriteProposal:
    proposal_id: str
    idempotency_key: str
    target_kind: str
    target_id: str
    operation: str
    current: dict[str, Any] | None
    proposed: dict[str, Any] | None
    diff: dict[str, dict[str, Any]]
    reversible: bool
    confirmation_phrase: str | None
    state: WriteState = WriteState.AWAITING_APPROVAL
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    verified_at: str | None = None
    failure: str | None = None
    _approval_digest: str = field(default="", repr=False)
    _rollback_snapshot: dict[str, Any] | None = field(default=None, repr=False)

    def public_payload(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "idempotency_key": self.idempotency_key,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "operation": self.operation,
            "current": deepcopy(self.current),
            "proposed": deepcopy(self.proposed),
            "diff": deepcopy(self.diff),
            "reversible": self.reversible,
            "confirmation_phrase": self.confirmation_phrase,
            "state": self.state.value,
            "created_at": self.created_at,
            "verified_at": self.verified_at,
            "failure": self.failure,
        }


class ApprovalError(RuntimeError):
    pass


class VerificationError(RuntimeError):
    pass


def _diff(current: dict[str, Any] | None, proposed: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    before = current or {}
    after = proposed or {}
    keys = sorted(set(before) | set(after))
    return {
        key: {"before": deepcopy(before.get(key)), "after": deepcopy(after.get(key))}
        for key in keys
        if before.get(key) != after.get(key)
    }


def _matches_expected(actual: dict[str, Any] | None, expected: dict[str, Any] | None) -> bool:
    if expected is None:
        return actual is None
    if actual is None:
        return False
    return all(actual.get(key) == value for key, value in expected.items())


class SafeWriteGateway:
    """Stateful preview → approval → apply → readback gate.

    This class is transport-agnostic. Nothing in it knows how to write to
    YouTube. A concrete adapter must be supplied explicitly, which keeps the
    desktop product from accidentally turning a UI button into a network write.
    """

    def __init__(self) -> None:
        self._proposals: dict[str, WriteProposal] = {}
        self._by_idempotency: dict[str, str] = {}
        self.audit: list[dict[str, Any]] = []

    def _event(self, proposal: WriteProposal, event: str, **extra: Any) -> None:
        self.audit.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "proposal_id": proposal.proposal_id,
                "target_kind": proposal.target_kind,
                "target_id": proposal.target_id,
                "state": proposal.state.value,
                "event": event,
                **extra,
            }
        )

    def preview(
        self,
        *,
        idempotency_key: str,
        target_kind: str,
        target_id: str,
        operation: str,
        current: dict[str, Any] | None,
        proposed: dict[str, Any] | None,
        reversible: bool = True,
    ) -> tuple[WriteProposal, str]:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key é obrigatório")
        if idempotency_key in self._by_idempotency:
            existing = self._proposals[self._by_idempotency[idempotency_key]]
            raise ValueError(f"idempotency_key já usado pelo proposal {existing.proposal_id}")
        op = operation.strip().lower()
        if op not in {"update", "create", "delete", "reorder", "publish"}:
            raise ValueError(f"operação não suportada pelo gateway: {operation}")
        changes = _diff(current, proposed)
        if op == "update" and not changes:
            raise ValueError("preview sem alterações")
        if op == "delete":
            reversible = False
            confirmation_phrase = f"EXCLUIR {target_kind.upper()} {target_id}"
        else:
            confirmation_phrase = None
        token = secrets.token_urlsafe(32)
        proposal = WriteProposal(
            proposal_id=str(uuid4()),
            idempotency_key=idempotency_key,
            target_kind=target_kind,
            target_id=target_id,
            operation=op,
            current=deepcopy(current),
            proposed=deepcopy(proposed),
            diff=changes,
            reversible=reversible,
            confirmation_phrase=confirmation_phrase,
            state=WriteState.AWAITING_APPROVAL,
            _approval_digest=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            _rollback_snapshot=deepcopy(current) if reversible else None,
        )
        self._proposals[proposal.proposal_id] = proposal
        self._by_idempotency[idempotency_key] = proposal.proposal_id
        self._event(proposal, "preview_created", reversible=reversible)
        return proposal, token

    def get(self, proposal_id: str) -> WriteProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError as exc:
            raise KeyError(f"proposal desconhecido: {proposal_id}") from exc

    def approve(self, proposal_id: str, approval_token: str, *, confirmation_text: str | None = None) -> WriteProposal:
        proposal = self.get(proposal_id)
        if proposal.state is not WriteState.AWAITING_APPROVAL:
            raise ApprovalError(f"proposal não aguarda aprovação: {proposal.state.value}")
        digest = hashlib.sha256(approval_token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest, proposal._approval_digest):
            raise ApprovalError("approval_token inválido")
        if proposal.confirmation_phrase and confirmation_text != proposal.confirmation_phrase:
            raise ApprovalError("confirmação destrutiva não corresponde ao alvo exato")
        proposal.state = WriteState.APPROVED
        self._event(proposal, "approved", destructive=proposal.operation == "delete")
        return proposal

    def apply(self, proposal_id: str, adapter: WriteAdapter) -> WriteProposal:
        proposal = self.get(proposal_id)
        if proposal.state is not WriteState.APPROVED:
            raise ApprovalError(f"apply bloqueado no estado {proposal.state.value}")
        proposal.state = WriteState.APPLYING
        self._event(proposal, "apply_started")
        try:
            adapter.apply(proposal)
            actual = adapter.readback(proposal)
            if proposal.operation == "delete":
                verified = actual is None
            elif proposal.operation == "create":
                verified = _matches_expected(actual, proposal.proposed)
            else:
                verified = _matches_expected(actual, proposal.proposed)
            if not verified:
                raise VerificationError("readback não corresponde ao estado aprovado")
            proposal.state = WriteState.VERIFIED
            proposal.verified_at = datetime.now(timezone.utc).isoformat()
            self._event(proposal, "readback_verified")
            return proposal
        except Exception as exc:
            proposal.state = WriteState.FAILED
            proposal.failure = str(exc)[:500]
            self._event(proposal, "apply_failed", error=proposal.failure)
            raise

    def rollback(self, proposal_id: str, adapter: WriteAdapter) -> WriteProposal:
        proposal = self.get(proposal_id)
        if proposal.state not in {WriteState.VERIFIED, WriteState.FAILED}:
            raise ApprovalError(f"rollback bloqueado no estado {proposal.state.value}")
        if not proposal.reversible:
            raise ApprovalError("esta operação não oferece rollback")
        adapter.rollback(proposal, deepcopy(proposal._rollback_snapshot))
        proposal.state = WriteState.ROLLED_BACK
        self._event(proposal, "rollback_applied")
        return proposal
