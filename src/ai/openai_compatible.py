from __future__ import annotations

from typing import Any

import requests

from .base import AIProvider, AIProviderError
from .types import AIModel, AIResponse, Messages


class OpenAICompatibleProvider(AIProvider):
    """Adapter for OpenAI-compatible REST APIs.

    Used by OpenAI, Groq, xAI and custom compatible endpoints. Models are
    discovered dynamically through GET /v1/models instead of being hardcoded.
    """

    def __init__(self, config, *, provider_name: str, default_base_url: str):
        super().__init__(config)
        self.provider_name = provider_name
        self.base_url = (config.base_url or default_base_url).rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise AIProviderError(f"Chave API ausente para {self.provider_name}.")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.config.extra_headers)
        return headers

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                detail = f" Resposta: {exc.response.text[:1000]}"
            raise AIProviderError(
                f"Falha ao comunicar com {self.provider_name}.{detail}"
            ) from exc

    def list_models(self) -> list[AIModel]:
        payload = self._request("GET", "/v1/models").json()
        models = []
        for item in payload.get("data", []):
            model_id = item.get("id")
            if not model_id:
                continue
            models.append(
                AIModel(
                    id=model_id,
                    name=model_id,
                    provider=self.provider_name,
                    context_window=item.get("context_window"),
                    metadata={
                        key: value
                        for key, value in item.items()
                        if key not in {"id", "context_window"}
                    },
                )
            )
        return sorted(models, key=lambda model: model.id.lower())

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
        body: dict[str, Any] = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "temperature": temperature,
        }
        if max_output_tokens is not None:
            body["max_tokens"] = max_output_tokens
        if response_format == "json":
            body["response_format"] = {"type": "json_object"}

        payload = self._request("POST", "/v1/chat/completions", json=body).json()
        choices = payload.get("choices") or []
        if not choices:
            raise AIProviderError(
                f"{self.provider_name} não retornou nenhuma resposta utilizável."
            )
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
            )
        if not isinstance(content, str):
            raise AIProviderError(
                f"Formato de resposta inesperado retornado por {self.provider_name}."
            )
        return AIResponse(
            text=content,
            model=payload.get("model", model),
            provider=self.provider_name,
            usage=payload.get("usage") or {},
            raw=payload,
        )
