from __future__ import annotations

from typing import Any

import requests

from .base import AIProvider, AIProviderError
from .types import AIModel, AIResponse, Messages


class OpenAIProvider(AIProvider):
    """OpenAI adapter using the Responses API for current-generation models."""

    provider_name = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com"

    def __init__(self, config):
        super().__init__(config)
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise AIProviderError("Chave API ausente para OpenAI.")
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
            raise AIProviderError(f"Falha ao comunicar com OpenAI.{detail}") from exc

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
                    metadata={
                        key: value for key, value in item.items() if key != "id"
                    },
                )
            )
        return sorted(models, key=lambda model: model.id.lower())

    @staticmethod
    def _to_input(messages: Messages) -> list[dict[str, str]]:
        converted = []
        for message in messages:
            role = message.get("role", "user")
            if role == "system":
                role = "developer"
            if role not in {"developer", "user", "assistant"}:
                role = "user"
            converted.append({"role": role, "content": message.get("content", "")})
        return converted

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        texts: list[str] = []
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for part in item.get("content", []):
                if part.get("type") == "output_text" and part.get("text"):
                    texts.append(part["text"])
        return "\n".join(texts).strip()

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
            "input": self._to_input(messages),
            "store": False,
        }
        if max_output_tokens is not None:
            body["max_output_tokens"] = max_output_tokens
        if response_format == "json":
            body["text"] = {"format": {"type": "json_object"}}

        payload = self._request("POST", "/v1/responses", json=body).json()
        text = self._extract_output_text(payload)
        if not text:
            raise AIProviderError("OpenAI retornou uma resposta sem texto utilizável.")
        return AIResponse(
            text=text,
            model=payload.get("model", model),
            provider=self.provider_name,
            usage=payload.get("usage") or {},
            raw=payload,
        )
