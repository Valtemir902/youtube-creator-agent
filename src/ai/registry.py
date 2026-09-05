from __future__ import annotations

from collections.abc import Callable

from .base import AIProvider
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider
from .types import AIProviderConfig


ProviderFactory = Callable[[AIProviderConfig], AIProvider]


class AIProviderRegistry:
    """Creates AI providers without hardcoding model IDs.

    Providers expose their own active model lists at runtime. A custom
    OpenAI-compatible endpoint is also supported for future providers.
    """

    DEFAULTS = {
        "openai": "https://api.openai.com",
        "groq": "https://api.groq.com/openai",
        "xai": "https://api.x.ai",
    }

    def __init__(self):
        self._factories: dict[str, ProviderFactory] = {
            "gemini": lambda config: GeminiProvider(config),
            "ollama": lambda config: OllamaProvider(config),
            "openai": lambda config: OpenAICompatibleProvider(
                config,
                provider_name="openai",
                default_base_url=self.DEFAULTS["openai"],
            ),
            "groq": lambda config: OpenAICompatibleProvider(
                config,
                provider_name="groq",
                default_base_url=self.DEFAULTS["groq"],
            ),
            "xai": lambda config: OpenAICompatibleProvider(
                config,
                provider_name="xai",
                default_base_url=self.DEFAULTS["xai"],
            ),
        }

    def register(self, name: str, factory: ProviderFactory) -> None:
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("Nome do provedor não pode ser vazio.")
        self._factories[normalized] = factory

    def available_providers(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories)) + ("openai_compatible",)

    def create(self, config: AIProviderConfig) -> AIProvider:
        name = config.provider.strip().lower()
        if name == "openai_compatible":
            if not config.base_url:
                raise ValueError(
                    "Um endpoint OpenAI-compatible personalizado exige base_url."
                )
            return OpenAICompatibleProvider(
                config,
                provider_name="openai_compatible",
                default_base_url=config.base_url,
            )
        factory = self._factories.get(name)
        if factory is None:
            raise ValueError(f"Provedor de IA não suportado: {config.provider}")
        return factory(config)
