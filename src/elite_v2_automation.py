from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from threading import Lock
from typing import Any
from uuid import uuid4


class AutomationState(StrEnum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    HANDED_TO_WRITE_GATEWAY = "handed_to_write_gateway"
    FAILED = "failed"


@dataclass(slots=True)
class AutomationItem:
    item_id: str
    intent: str
    provider: str
    target_kind: str | None
    target_id: str | None
    proposal: dict[str, Any]
    facts: list[dict[str, Any]]
    state: AutomationState = AutomationState.AWAITING_APPROVAL
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    approved_at: str | None = None
    cancelled_at: str | None = None
    failure: str | None = None

    def public_payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "intent": self.intent,
            "provider": self.provider,
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "proposal": deepcopy(self.proposal),
            "facts": deepcopy(self.facts),
            "state": self.state.value,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "cancelled_at": self.cancelled_at,
            "failure": self.failure,
        }


class SupervisedAutomationQueue:
    """Local proposal queue. Approval never performs a YouTube write by itself."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, AutomationItem] = {}
        self.audit: list[dict[str, Any]] = []

    def _event(self, item: AutomationItem, event: str) -> None:
        self.audit.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "item_id": item.item_id,
                "event": event,
                "state": item.state.value,
                "youtube_write_performed": False,
            }
        )

    def enqueue(
        self,
        *,
        intent: str,
        provider: str,
        proposal: dict[str, Any],
        facts: list[dict[str, Any]],
        target_kind: str | None = None,
        target_id: str | None = None,
    ) -> AutomationItem:
        if not proposal:
            raise ValueError("proposal é obrigatório")
        if not facts or any(not isinstance(row, dict) or not row.get("source") for row in facts):
            raise ValueError("facts com source são obrigatórios")
        item = AutomationItem(
            item_id=str(uuid4()),
            intent=str(intent),
            provider=str(provider),
            target_kind=str(target_kind) if target_kind else None,
            target_id=str(target_id) if target_id else None,
            proposal=deepcopy(proposal),
            facts=deepcopy(facts),
        )
        with self._lock:
            self._items[item.item_id] = item
            self._event(item, "queued")
        return item

    def get(self, item_id: str) -> AutomationItem:
        with self._lock:
            try:
                return self._items[item_id]
            except KeyError as exc:
                raise KeyError(f"automation item desconhecido: {item_id}") from exc

    def list(self, *, limit: int = 100) -> list[AutomationItem]:
        with self._lock:
            values = list(self._items.values())[-max(1, min(int(limit), 500)):]
            return list(reversed(values))

    def approve(self, item_id: str, *, user_confirmed: bool) -> AutomationItem:
        if user_confirmed is not True:
            raise PermissionError("aprovação explícita ausente")
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                raise KeyError(f"automation item desconhecido: {item_id}")
            if item.state is not AutomationState.AWAITING_APPROVAL:
                raise RuntimeError(f"item não aguarda aprovação: {item.state.value}")
            item.state = AutomationState.APPROVED
            item.approved_at = datetime.now(timezone.utc).isoformat()
            self._event(item, "approved")
            return item

    def cancel(self, item_id: str) -> AutomationItem:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                raise KeyError(f"automation item desconhecido: {item_id}")
            if item.state not in {AutomationState.AWAITING_APPROVAL, AutomationState.APPROVED}:
                raise RuntimeError(f"item não pode ser cancelado: {item.state.value}")
            item.state = AutomationState.CANCELLED
            item.cancelled_at = datetime.now(timezone.utc).isoformat()
            self._event(item, "cancelled")
            return item

    def hand_to_write_gateway(self, item_id: str, *, user_confirmed: bool) -> AutomationItem:
        """Marks readiness only; caller must separately create/approve a SafeWriteGateway proposal."""
        if user_confirmed is not True:
            raise PermissionError("confirmação explícita ausente")
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                raise KeyError(f"automation item desconhecido: {item_id}")
            if item.state is not AutomationState.APPROVED:
                raise RuntimeError("somente item aprovado pode ser encaminhado ao Write Gateway")
            item.state = AutomationState.HANDED_TO_WRITE_GATEWAY
            self._event(item, "handed_to_write_gateway")
            return item
