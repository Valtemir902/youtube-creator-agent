from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ai.runtime import AIRuntime
from ai.settings import AISettings
from ai.types import AIResponse
from creator_service.ai_runtime_policy import install_ai_runtime_policy


@dataclass
class FakeCredentials:
    legacy: dict[str, str] = field(default_factory=dict)
    named: dict[tuple[str, str], str] = field(default_factory=dict)

    def save_key(self, provider, api_key): self.legacy[provider] = api_key
    def get_key(self, provider): return self.legacy.get(provider)
    def delete_key(self, provider): self.legacy.pop(provider, None)
    def set_session_key(self, provider, api_key): self.save_key(provider, api_key)
    def save_named_key(self, provider, key_id, api_key): self.named[(provider, key_id)] = api_key
    def get_named_key(self, provider, key_id): return self.named.get((provider, key_id))
    def delete_named_key(self, provider, key_id): self.named.pop((provider, key_id), None)
    def set_named_session_key(self, provider, key_id, api_key): self.save_named_key(provider, key_id, api_key)


class TrackingProvider:
    calls: list[str] = []

    def __init__(self, key: str): self.key = key
    def generate(self, model, messages, **kwargs):
        self.calls.append(self.key)
        if self.key.startswith("bad"):
            raise RuntimeError("503 UNAVAILABLE: high demand")
        return AIResponse(text="ok", model=model, provider="gemini")
    def list_models(self): return []
    def validate_connection(self): return True


class Registry:
    def create(self, config): return TrackingProvider(config.api_key)
    def available_providers(self): return ("gemini",)


def runtime(tmp_path):
    install_ai_runtime_policy()
    rt = AIRuntime(tmp_path / "ai_settings.json", credential_store=FakeCredentials())
    rt.registry = Registry()
    rt.settings_store.save(AISettings(provider="gemini", model="model-x", auto_rotate_keys=False))
    return rt


def test_single_selected_key_is_exclusive_even_with_many_saved(tmp_path):
    rt = runtime(tmp_path)
    first = rt.add_api_key("gemini", "good-first", make_active=False)
    chosen = rt.add_api_key("gemini", "good-chosen", make_active=False)
    third = rt.add_api_key("gemini", "good-third", make_active=False)

    state = rt.select_api_keys("gemini", [chosen["id"]], rotate=False)
    TrackingProvider.calls = []
    response = rt.generate([{"role": "user", "content": "teste"}])

    assert response.text == "ok"
    assert TrackingProvider.calls == ["good-chosen"]
    public = {item["id"]: item for item in state["keys"]}
    assert public[chosen["id"]]["enabled"] is True
    assert public[first["id"]]["enabled"] is False
    assert public[third["id"]]["enabled"] is False
    assert state["active_key_id"] == chosen["id"]
    assert state["auto_rotate"] is False


def test_rotation_uses_only_selected_subset_and_fails_over(tmp_path):
    rt = runtime(tmp_path)
    excluded = rt.add_api_key("gemini", "good-excluded", make_active=False)
    bad = rt.add_api_key("gemini", "bad-selected", make_active=False)
    good = rt.add_api_key("gemini", "good-selected", make_active=False)

    rt.select_api_keys("gemini", [bad["id"], good["id"]], rotate=True)
    TrackingProvider.calls = []
    response = rt.generate([{"role": "user", "content": "teste"}])

    assert response.text == "ok"
    assert TrackingProvider.calls == ["bad-selected", "good-selected"]
    assert "good-excluded" not in TrackingProvider.calls
    records = {item["id"]: item for item in rt.list_api_keys("gemini")}
    assert records[excluded["id"]]["enabled"] is False
    assert records[bad["id"]]["status"] == "warning"
    assert records[good["id"]]["active"] is True


def test_disabling_active_key_moves_active_to_enabled_key(tmp_path):
    rt = runtime(tmp_path)
    first = rt.add_api_key("gemini", "good-one")
    second = rt.add_api_key("gemini", "good-two", make_active=False)
    rt.set_active_api_key("gemini", first["id"])

    rt.set_api_key_enabled("gemini", first["id"], False)

    assert rt.key_pool.active_key_id("gemini") == second["id"]
    with pytest.raises((ValueError, RuntimeError)):
        rt.key_pool.set_active("gemini", first["id"])


def test_pool_never_falls_back_to_stale_legacy_disabled_key(tmp_path):
    rt = runtime(tmp_path)
    only = rt.add_api_key("gemini", "stale-secret")
    rt.set_api_key_enabled("gemini", only["id"], False)
    # Simulate the historical provider-level credential slot still containing it.
    rt.credentials.save_key("gemini", "stale-secret")

    with pytest.raises(RuntimeError, match="desativadas"):
        rt.generate([{"role": "user", "content": "teste"}])
