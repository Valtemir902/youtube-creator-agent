from __future__ import annotations

from dataclasses import dataclass, field

from ai.runtime import AIRuntime
from ai.settings import AISettings
from ai.types import AIModel, AIResponse


@dataclass
class FakeCredentials:
    legacy: dict[str, str] = field(default_factory=dict)
    named: dict[tuple[str, str], str] = field(default_factory=dict)

    def save_key(self, provider, api_key):
        self.legacy[provider] = api_key

    def get_key(self, provider):
        return self.legacy.get(provider)

    def delete_key(self, provider):
        self.legacy.pop(provider, None)

    def set_session_key(self, provider, api_key):
        self.save_key(provider, api_key)

    def save_named_key(self, provider, key_id, api_key):
        self.named[(provider, key_id)] = api_key

    def get_named_key(self, provider, key_id):
        return self.named.get((provider, key_id))

    def delete_named_key(self, provider, key_id):
        self.named.pop((provider, key_id), None)

    def set_named_session_key(self, provider, key_id, api_key):
        self.save_named_key(provider, key_id, api_key)


class FakeProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def list_models(self):
        return [AIModel(id="model-x", name="model-x", provider="gemini")]

    def validate_connection(self):
        return True

    def generate(self, model, messages, **kwargs):
        if self.api_key == "key-overloaded":
            raise RuntimeError("503 UNAVAILABLE: high demand, try again later")
        return AIResponse(text="ok", model=model, provider="gemini")


class FakeRegistry:
    def create(self, config):
        return FakeProvider(config.api_key)

    def available_providers(self):
        return ("gemini",)


def test_rotation_moves_to_next_key_and_marks_health(tmp_path):
    runtime = AIRuntime(tmp_path / "ai_settings.json", credential_store=FakeCredentials())
    runtime.registry = FakeRegistry()
    bad = runtime.add_api_key("gemini", "key-overloaded", label="primeira")
    good = runtime.add_api_key("gemini", "key-good", label="segunda", make_active=False)
    runtime.set_active_api_key("gemini", bad["id"])
    runtime.set_auto_rotation("gemini", True)
    settings = AISettings(provider="gemini", model="model-x", auto_rotate_keys=True)
    runtime.settings_store.save(settings)

    response = runtime.generate([{"role": "user", "content": "teste"}])

    assert response.text == "ok"
    records = {item["id"]: item for item in runtime.list_api_keys("gemini")}
    assert records[bad["id"]]["status"] == "warning"
    assert "503" in records[bad["id"]]["last_error"]
    assert records[good["id"]]["status"] == "ok"
    assert records[good["id"]]["active"] is True


def test_existing_legacy_key_is_migrated_to_pool(tmp_path):
    credentials = FakeCredentials(legacy={"gemini": "legacy-secret"})
    runtime = AIRuntime(tmp_path / "ai_settings.json", credential_store=credentials)

    records = runtime.list_api_keys("gemini")

    assert len(records) == 1
    assert records[0]["label"] == "Chave existente"
    assert "legacy-secret" not in records[0]["masked"]
    assert credentials.get_named_key("gemini", records[0]["id"]) == "legacy-secret"
