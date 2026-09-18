from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class AIProvider(StrEnum):
    LOCAL = "local"
    API = "api"
    CHATGPT = "chatgpt"
    INTERNAL = "internal"


class OperationMode(StrEnum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    SUPERVISED = "supervised"


class CommandIntent(StrEnum):
    READ_ANALYZE = "read_analyze"
    PROPOSE_METADATA = "propose_metadata"
    PROPOSE_PLAYLIST = "propose_playlist"
    PREPARE_PUBLISH = "prepare_publish"
    DESTRUCTIVE_REQUEST = "destructive_request"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class ProviderStatus:
    provider: AIProvider
    available: bool
    model: str | None = None
    reason: str | None = None
    external: bool = False


@dataclass(slots=True)
class AIProposal:
    provider: AIProvider
    model: str | None
    intent: CommandIntent
    facts: list[dict[str, Any]]
    proposed_changes: dict[str, Any]
    confidence: float | None = None
    limitations: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    requires_write_gateway: bool = True

    def validate(self) -> None:
        if not self.facts:
            raise ValueError("proposta de IA sem fatos/proveniência")
        for fact in self.facts:
            if not isinstance(fact, dict) or not fact.get("source"):
                raise ValueError("todo fato precisa declarar source")
        if not self.proposed_changes:
            raise ValueError("proposta sem alterações estruturadas")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence deve ficar entre 0 e 1")
        if not self.requires_write_gateway:
            raise ValueError("propostas mutáveis não podem contornar o Write Gateway")


def select_provider(
    statuses: list[ProviderStatus],
    *,
    preferred: AIProvider | None,
    allow_external: bool,
) -> ProviderStatus:
    by_provider = {item.provider: item for item in statuses}
    if preferred is not None:
        selected = by_provider.get(preferred)
        if selected and selected.available and (allow_external or not selected.external):
            return selected
        raise RuntimeError(f"provedor preferido indisponível: {preferred.value}")

    order = [AIProvider.LOCAL, AIProvider.INTERNAL, AIProvider.CHATGPT, AIProvider.API]
    for provider in order:
        item = by_provider.get(provider)
        if item and item.available and (allow_external or not item.external):
            return item
    raise RuntimeError("nenhum provedor permitido está disponível")


def classify_command(text: str) -> CommandIntent:
    """Conservative local intent classification. It never executes a command."""

    value = " ".join(text.lower().split())
    destructive = ("excluir", "deletar", "apagar", "delete", "remove video", "remove playlist")
    if any(term in value for term in destructive):
        return CommandIntent.DESTRUCTIVE_REQUEST
    if any(term in value for term in ("playlist", "lista de reprodução")) and any(
        term in value for term in ("criar", "organizar", "mover", "adicionar", "sugerir")
    ):
        return CommandIntent.PROPOSE_PLAYLIST
    if any(term in value for term in ("publicar", "upload", "agendar", "schedule")):
        return CommandIntent.PREPARE_PUBLISH
    if any(term in value for term in ("título", "titulo", "descrição", "descricao", "tag", "seo", "otimizar")):
        return CommandIntent.PROPOSE_METADATA
    if any(term in value for term in ("analisar", "auditar", "diagnóstico", "diagnostico", "crescimento", "analytics", "por que")):
        return CommandIntent.READ_ANALYZE
    return CommandIntent.UNKNOWN


def execution_policy(intent: CommandIntent, mode: OperationMode) -> dict[str, Any]:
    """Return the most permissive action allowed before explicit user approval."""

    if intent is CommandIntent.DESTRUCTIVE_REQUEST:
        return {
            "may_read": True,
            "may_propose": True,
            "may_preview": True,
            "may_apply_without_explicit_approval": False,
            "requires_target_specific_confirmation": True,
        }
    if mode is OperationMode.MANUAL:
        return {
            "may_read": True,
            "may_propose": False,
            "may_preview": True,
            "may_apply_without_explicit_approval": False,
            "requires_target_specific_confirmation": False,
        }
    return {
        "may_read": True,
        "may_propose": True,
        "may_preview": True,
        "may_apply_without_explicit_approval": False,
        "requires_target_specific_confirmation": False,
    }
