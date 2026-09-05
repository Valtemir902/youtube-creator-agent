from __future__ import annotations

from pathlib import Path

from .credential_store import CredentialStore
from .registry import AIProviderRegistry
from .settings import AISettings, AISettingsStore
from .types import AIModel, AIProviderConfig, AIResponse, Messages


class AIRuntime:
    """Single entry point used by the desktop app and future MCP backend."""

    def __init__(self, settings_path: str | Path):
        self.settings_store = AISettingsStore(settings_path)
        self.credentials = CredentialStore()
        self.registry = AIProviderRegistry()

    def load_settings(self) -> AISettings:
        return self.settings_store.load()

    def save_settings(self, settings: AISettings, api_key: str | None = None) -> None:
        provider = settings.provider.strip().lower()
        if provider != "ollama" and api_key:
            if settings.remember_api_key:
                self.credentials.save_key(provider, api_key)
            else:
                self.credentials.set_session_key(provider, api_key)
        self.settings_store.save(settings)

    def _provider(self, settings: AISettings | None = None, api_key: str | None = None):
        settings = settings or self.load_settings()
        provider_name = settings.provider.strip().lower()
        key = api_key or self.credentials.get_key(provider_name)
        if provider_name != "ollama" and not key:
            raise RuntimeError(f"Nenhuma chave API configurada para {provider_name}.")
        config = AIProviderConfig(
            provider=provider_name,
            api_key=key,
            base_url=settings.base_url.strip() or None,
            timeout_seconds=60.0,
        )
        return self.registry.create(config)

    def list_models(self, settings: AISettings | None = None, api_key: str | None = None) -> list[AIModel]:
        return self._provider(settings, api_key).list_models()

    def validate(self, settings: AISettings | None = None, api_key: str | None = None) -> bool:
        provider = self._provider(settings, api_key)
        return provider.validate_connection()

    def generate(
        self,
        messages: Messages,
        *,
        settings: AISettings | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        response_format: str | None = None,
    ) -> AIResponse:
        settings = settings or self.load_settings()
        selected_model = (model or settings.model).strip()
        if not selected_model:
            raise RuntimeError("Nenhum modelo de IA foi selecionado.")
        return self._provider(settings).generate(
            selected_model,
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_format=response_format,
        )
