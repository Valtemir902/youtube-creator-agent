from __future__ import annotations

from typing import Any

import requests

from .base import AIProvider, AIProviderError
from .types import AIModel, AIResponse, Messages


class OllamaProvider(AIProvider):
    provider_name = "ollama"
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(self, config):
        super().__init__(config)
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise AIProviderError(
                "Não foi possível conectar ao Ollama local. Verifique se o serviço está ativo."
            ) from exc

    def list_models(self) -> list[AIModel]:
        payload = self._request("GET", "/api/tags").json()
        models = []
        for item in payload.get("models", []):
            model_id = item.get("model") or item.get("name")
            if not model_id:
                continue
            details = item.get("details") or {}
            models.append(
                AIModel(
                    id=model_id,
                    name=model_id,
                    provider=self.provider_name,
                    metadata={
                        "size": item.get("size"),
                        "modified_at": item.get("modified_at"),
                        "family": details.get("family"),
                        "parameter_size": details.get("parameter_size"),
                        "quantization_level": details.get("quantization_level"),
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
        options: dict[str, Any] = {"temperature": temperature}
        if max_output_tokens is not None:
            options["num_predict"] = max_output_tokens

        body: dict[str, Any] = {
            "model": model,
            "messages": [dict(message) for message in messages],
            "stream": False,
            "options": options,
        }
        if response_format == "json":
            body["format"] = "json"

        payload = self._request("POST", "/api/chat", json=body).json()
        message = payload.get("message") or {}
        text = message.get("content")
        if not isinstance(text, str) or not text:
            raise AIProviderError("Ollama retornou uma resposta sem texto utilizável.")
        usage = {
            "prompt_eval_count": payload.get("prompt_eval_count"),
            "eval_count": payload.get("eval_count"),
            "total_duration": payload.get("total_duration"),
        }
        return AIResponse(
            text=text,
            model=payload.get("model", model),
            provider=self.provider_name,
            usage=usage,
            raw=payload,
        )
