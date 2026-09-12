from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai.base import AIProviderError
from ai.gemini import GeminiProvider
from ai.key_pool import APIKeyPoolStore
from ai.runtime import AIRuntime
from ai.types import AIModel


class _FailingProvider:
    def __init__(self, error: Exception):
        self.error = error

    def generate(self, *_args, **_kwargs):
        raise self.error


def _runtime_for_test(tmp_path, error: Exception) -> tuple[AIRuntime, APIKeyPoolStore, str]:
    store = APIKeyPoolStore(tmp_path / "keys.json")
    record = store.add("gemini", "test-api-key", label="Teste")
    runtime = object.__new__(AIRuntime)
    runtime.key_pool = store
    runtime.list_models = lambda _settings, key_id=None: [
        AIModel(id="gemini-test", name="Gemini Test", provider="gemini")
    ]
    runtime._provider = lambda _settings, key_id=None: _FailingProvider(error)
    return runtime, store, record.id


def test_gemini_extracts_candidate_part_when_response_text_is_empty():
    response = SimpleNamespace(
        text="",
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[SimpleNamespace(text="OK")]),
            )
        ],
    )
    assert GeminiProvider._response_text(response) == "OK"


def test_gemini_extracts_candidate_part_from_serialized_payload():
    class Response:
        text = ""
        candidates = []

        def model_dump(self, **_kwargs):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Resposta estruturada"}]}}
                ]
            }

    assert GeminiProvider._response_text(Response()) == "Resposta estruturada"


def test_empty_model_response_is_warning_not_bad_key(tmp_path):
    runtime, store, key_id = _runtime_for_test(
        tmp_path,
        AIProviderError(
            "Gemini autenticou a credencial e respondeu ao modelo, mas não retornou texto utilizável para este teste."
        ),
    )

    with pytest.raises(AIProviderError, match="não retornou texto utilizável"):
        runtime.test_api_key("gemini", key_id, model="gemini-test")

    record = store.get("gemini", key_id)
    assert record is not None
    assert record.status == "warning"
    assert "texto utilizável" in record.last_error


def test_invalid_api_key_remains_hard_error(tmp_path):
    runtime, store, key_id = _runtime_for_test(
        tmp_path,
        AIProviderError("401 unauthenticated: API key invalid"),
    )

    with pytest.raises(AIProviderError, match="401"):
        runtime.test_api_key("gemini", key_id, model="gemini-test")

    record = store.get("gemini", key_id)
    assert record is not None
    assert record.status == "error"


def test_quota_or_rate_limit_is_warning(tmp_path):
    runtime, store, key_id = _runtime_for_test(
        tmp_path,
        AIProviderError("429 resource exhausted: quota exceeded"),
    )

    with pytest.raises(AIProviderError, match="429"):
        runtime.test_api_key("gemini", key_id, model="gemini-test")

    record = store.get("gemini", key_id)
    assert record is not None
    assert record.status == "warning"


def test_model_incompatibility_is_warning_not_bad_key(tmp_path):
    store = APIKeyPoolStore(tmp_path / "keys.json")
    record = store.add("gemini", "test-api-key")
    store.mark_failure(
        "gemini",
        record.id,
        "Modelo Gemini incompatível com generateContent durante gerar conteúdo.",
        warning=False,
        model="gemini-test",
    )
    saved = store.get("gemini", record.id)
    assert saved is not None
    assert saved.status == "warning"
