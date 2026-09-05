from __future__ import annotations

from typing import Any

import requests

from .base import AIProvider, AIProviderError
from .types import AIModel, AIResponse, Messages


class GeminiProvider(AIProvider):
    provider_name = "gemini"
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, config):
        super().__init__(config)
        self.base_url = (config.base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if not self.config.api_key:
            raise AIProviderError("Chave API ausente para Gemini.")
        params = dict(kwargs.pop("params", {}) or {})
        params["key"] = self.config.api_key
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                timeout=self.config.timeout_seconds,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            detail = ""
            if getattr(exc, "response", None) is not None:
                detail = f" Resposta: {exc.response.text[:1000]}"
            raise AIProviderError(f"Falha ao comunicar com Gemini.{detail}") from exc

    def list_models(self) -> list[AIModel]:
        models: list[AIModel] = []
        page_token = None
        while True:
            params = {"pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            payload = self._request("GET", "/models", params=params).json()
            for item in payload.get("models", []):
                raw_name = item.get("name", "")
                model_id = raw_name.removeprefix("models/")
                supported = tuple(item.get("supportedGenerationMethods") or ())
                if not model_id or "generateContent" not in supported:
                    continue
                models.append(
                    AIModel(
                        id=model_id,
                        name=item.get("displayName") or model_id,
                        provider=self.provider_name,
                        capabilities=supported,
                        context_window=item.get("inputTokenLimit"),
                        metadata={
                            "output_token_limit": item.get("outputTokenLimit"),
                            "description": item.get("description"),
                        },
                    )
                )
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return sorted(models, key=lambda model: model.name.lower())

    @staticmethod
    def _convert_messages(messages: Messages) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts = []
        contents = []
        for message in messages:
            role = message.get("role", "user")
            text = message.get("content", "")
            if role == "system":
                system_parts.append(text)
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": text}],
                }
            )
        return "\n\n".join(system_parts) or None, contents

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
        system_instruction, contents = self._convert_messages(messages)
        generation_config: dict[str, Any] = {"temperature": temperature}
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens
        if response_format == "json":
            generation_config["responseMimeType"] = "application/json"

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        payload = self._request(
            "POST",
            f"/models/{model}:generateContent",
            json=body,
            headers={"Content-Type": "application/json"},
        ).json()
        candidates = payload.get("candidates") or []
        if not candidates:
            raise AIProviderError("Gemini não retornou nenhum candidato de resposta.")
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        text = "\n".join(part.get("text", "") for part in parts if part.get("text"))
        if not text:
            raise AIProviderError("Gemini retornou uma resposta sem texto utilizável.")
        return AIResponse(
            text=text,
            model=model,
            provider=self.provider_name,
            usage=payload.get("usageMetadata") or {},
            raw=payload,
        )
