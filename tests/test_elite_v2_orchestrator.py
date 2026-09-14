from __future__ import annotations

import pytest

from elite_v2_orchestrator import (
    AIProposal,
    AIProvider,
    CommandIntent,
    OperationMode,
    ProviderStatus,
    classify_command,
    execution_policy,
    select_provider,
)


def test_provider_selection_prefers_local_then_internal_without_external_fallback() -> None:
    statuses = [
        ProviderStatus(AIProvider.API, True, model="external", external=True),
        ProviderStatus(AIProvider.INTERNAL, True, model="rules", external=False),
        ProviderStatus(AIProvider.LOCAL, True, model="qwen", external=False),
    ]
    assert select_provider(statuses, preferred=None, allow_external=False).provider is AIProvider.LOCAL
    unavailable_local = [
        ProviderStatus(AIProvider.LOCAL, False),
        ProviderStatus(AIProvider.INTERNAL, True, model="rules"),
        ProviderStatus(AIProvider.API, True, external=True),
    ]
    assert select_provider(unavailable_local, preferred=None, allow_external=False).provider is AIProvider.INTERNAL


def test_explicit_external_preference_is_blocked_when_external_is_not_allowed() -> None:
    with pytest.raises(RuntimeError):
        select_provider(
            [ProviderStatus(AIProvider.API, True, external=True)],
            preferred=AIProvider.API,
            allow_external=False,
        )


@pytest.mark.parametrize(
    ("command", "intent"),
    [
        ("analise por que meu canal caiu", CommandIntent.READ_ANALYZE),
        ("otimizar título e descrição deste vídeo", CommandIntent.PROPOSE_METADATA),
        ("criar uma playlist para estes vídeos", CommandIntent.PROPOSE_PLAYLIST),
        ("agendar upload amanhã", CommandIntent.PREPARE_PUBLISH),
        ("excluir este vídeo", CommandIntent.DESTRUCTIVE_REQUEST),
    ],
)
def test_command_classifier_is_conservative_and_never_executes(command, intent) -> None:
    assert classify_command(command) is intent


def test_all_mutating_policies_keep_apply_behind_explicit_approval() -> None:
    for mode in OperationMode:
        for intent in CommandIntent:
            policy = execution_policy(intent, mode)
            assert policy["may_apply_without_explicit_approval"] is False
    destructive = execution_policy(CommandIntent.DESTRUCTIVE_REQUEST, OperationMode.SUPERVISED)
    assert destructive["requires_target_specific_confirmation"] is True


def test_ai_proposal_requires_provenance_and_write_gateway() -> None:
    proposal = AIProposal(
        provider=AIProvider.LOCAL,
        model="qwen",
        intent=CommandIntent.PROPOSE_METADATA,
        facts=[{"source": "youtube_data_api", "title": "Atual"}],
        proposed_changes={"title": "Novo"},
        confidence=0.8,
    )
    proposal.validate()

    bad = AIProposal(
        provider=AIProvider.LOCAL,
        model="qwen",
        intent=CommandIntent.PROPOSE_METADATA,
        facts=[{"title": "sem origem"}],
        proposed_changes={"title": "Novo"},
    )
    with pytest.raises(ValueError, match="source"):
        bad.validate()

    bypass = AIProposal(
        provider=AIProvider.INTERNAL,
        model="rules",
        intent=CommandIntent.PROPOSE_METADATA,
        facts=[{"source": "cache", "title": "Atual"}],
        proposed_changes={"title": "Novo"},
        requires_write_gateway=False,
    )
    with pytest.raises(ValueError, match="Write Gateway"):
        bypass.validate()
