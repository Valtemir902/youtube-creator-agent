from __future__ import annotations

from dataclasses import dataclass

import pytest

from ai.settings import AISettings
from elite_v2_ai_runtime import EliteV2AIError, EliteV2AIRuntime, proposal_payload
from elite_v2_orchestrator import AIProvider, CommandIntent


@dataclass
class FakeAIResponse:
    text: str


class FakeRuntime:
    def __init__(self, provider: str = "ollama", model: str = "qwen-test") -> None:
        self.settings = AISettings(provider=provider, model=model)
        self.generate_calls = []

    def load_settings(self):
        return self.settings

    def generate(self, messages, **kwargs):
        self.generate_calls.append((messages, kwargs))
        return FakeAIResponse(
            '{"facts":[{"source":"youtube_data_api","name":"title","value":"Antes"}],'
            '"proposed_changes":{"title":"Depois"},"confidence":0.8,"limitations":[]}'
        )


def test_internal_provider_is_deterministic_and_never_writes() -> None:
    runtime = EliteV2AIRuntime(FakeRuntime())
    proposal = runtime.propose(
        provider=AIProvider.INTERNAL,
        command="otimizar título deste vídeo",
        context={"source": "youtube_data_api", "video_id": "VID1", "title": "Atual", "tags": []},
    )
    assert proposal.provider is AIProvider.INTERNAL
    assert proposal.intent is CommandIntent.PROPOSE_METADATA
    assert proposal.requires_write_gateway is True
    payload = proposal_payload(proposal)
    assert payload["youtube_write_performed"] is False
    assert payload["requires_explicit_approval"] is True


def test_local_provider_returns_structured_proposal_only() -> None:
    fake = FakeRuntime(provider="ollama", model="qwen-test")
    runtime = EliteV2AIRuntime(fake)
    proposal = runtime.propose(
        provider=AIProvider.LOCAL,
        command="melhore o título",
        context={"source": "youtube_data_api", "video_id": "VID1", "title": "Antes"},
    )
    assert proposal.provider is AIProvider.LOCAL
    assert proposal.proposed_changes == {"title": "Depois"}
    assert proposal.facts[0]["source"] == "youtube_data_api"
    assert len(fake.generate_calls) == 1


def test_api_provider_requires_external_provider_configuration() -> None:
    runtime = EliteV2AIRuntime(FakeRuntime(provider="ollama", model="qwen-test"))
    with pytest.raises(EliteV2AIError):
        runtime.propose(provider=AIProvider.API, command="otimizar título", context={"source": "youtube_data_api"})


def test_chatgpt_provider_never_reuses_chat_credentials_inside_exe() -> None:
    runtime = EliteV2AIRuntime(FakeRuntime())
    with pytest.raises(EliteV2AIError, match="plugin/conector"):
        runtime.propose(provider=AIProvider.CHATGPT, command="analisar canal", context={"source": "youtube_data_api"})


def test_malformed_model_output_is_rejected_not_applied() -> None:
    fake = FakeRuntime()
    fake.generate = lambda *args, **kwargs: FakeAIResponse("isso não é json")
    runtime = EliteV2AIRuntime(fake)
    with pytest.raises(EliteV2AIError, match="JSON estruturado"):
        runtime.propose(provider=AIProvider.LOCAL, command="otimizar título", context={"source": "youtube_data_api"})
