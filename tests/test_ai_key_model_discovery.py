from __future__ import annotations

from ai.key_test import inspect_key_and_model
from ai.types import AIModel


class FakeRuntime:
    def list_models(self, settings, api_key=None, *, key_id=None):
        assert key_id == "key-1"
        return [
            AIModel(id="gemini-a", name="Gemini A", provider="gemini"),
            AIModel(id="gemini-b", name="Gemini B", provider="gemini"),
            AIModel(id="gemini-c", name="Gemini C", provider="gemini"),
        ]

    def test_api_key(self, provider, key_id, *, model="", base_url=""):
        raise RuntimeError("503 UNAVAILABLE: selected model is overloaded")


def test_discovered_models_are_preserved_when_smoke_test_fails():
    result = inspect_key_and_model(
        FakeRuntime(),
        "gemini",
        "key-1",
        model="gemini-b",
    )

    assert result["models"] == ["gemini-a", "gemini-b", "gemini-c"]
    assert result["count"] == 3
    assert result["model_test_ok"] is False
    assert "503" in result["model_test_error"]


def test_discovery_without_selected_model_returns_full_list():
    result = inspect_key_and_model(FakeRuntime(), "gemini", "key-1")

    assert result["ok"] is True
    assert result["models"] == ["gemini-a", "gemini-b", "gemini-c"]
    assert result["model_test_ok"] is None
