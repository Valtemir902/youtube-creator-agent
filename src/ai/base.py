from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import AIModel, AIProviderConfig, AIResponse, Messages


class AIProviderError(RuntimeError):
    pass


class AIProvider(ABC):
    provider_name: str

    def __init__(self, config: AIProviderConfig):
        self.config = config

    @abstractmethod
    def list_models(self) -> list[AIModel]:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        model: str,
        messages: Messages,
        *,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        response_format: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AIResponse:
        raise NotImplementedError

    def validate_connection(self) -> bool:
        self.list_models()
        return True
