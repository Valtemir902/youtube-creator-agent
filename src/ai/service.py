from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .base import AIProvider, AIProviderError
from .registry import AIProviderRegistry
from .types import AIModel, AIProviderConfig, AIResponse, Messages


@dataclass
class AISelection:
    provider: AIProvider
    model: str


class AIService:
    """Single entry point used by the desktop app and future MCP backend."""

    def __init__(self, registry: AIProviderRegistry | None = None):
        self.registry = registry or AIProviderRegistry()
        self._selection: AISelection | None = None

    def connect(self, config: AIProviderConfig, model: str | None = None) -> list[AIModel]:
        provider = self.registry.create(config)
        models = provider.list_models()
        if not models:
            raise AIProviderError(
                f"O provedor {config.provider} não retornou modelos disponíveis."
            )
        selected = model or models[0].id
        available_ids = {item.id for item in models}
        if selected not in available_ids:
            raise AIProviderError(
                f"O modelo '{selected}' não está disponível para {config.provider}."
            )
        self._selection = AISelection(provider=provider, model=selected)
        return models

    def select_model(self, model: str) -> None:
        if self._selection is None:
            raise AIProviderError("Nenhum provedor de IA está conectado.")
        models = self._selection.provider.list_models()
        if model not in {item.id for item in models}:
            raise AIProviderError(f"Modelo indisponível: {model}")
        self._selection.model = model

    def list_models(self) -> list[AIModel]:
        if self._selection is None:
            raise AIProviderError("Nenhum provedor de IA está conectado.")
        return self._selection.provider.list_models()

    def generate(
        self,
        messages: Messages,
        *,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
    ) -> AIResponse:
        if self._selection is None:
            raise AIProviderError("Nenhum provedor de IA está conectado.")
        return self._selection.provider.generate(
            self._selection.model,
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

    def generate_json(
        self,
        messages: Messages,
        *,
        temperature: float = 0.1,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        if self._selection is None:
            raise AIProviderError("Nenhum provedor de IA está conectado.")
        response = self._selection.provider.generate(
            self._selection.model,
            messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_format="json",
        )
        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "A IA não retornou JSON válido. A resposta foi rejeitada para evitar dados inventados ou corrompidos."
            ) from exc
        if not isinstance(parsed, dict):
            raise AIProviderError("A IA retornou JSON válido, mas não um objeto estruturado.")
        return parsed

    @property
    def selected_provider(self) -> str | None:
        return self._selection.provider.provider_name if self._selection else None

    @property
    def selected_model(self) -> str | None:
        return self._selection.model if self._selection else None
