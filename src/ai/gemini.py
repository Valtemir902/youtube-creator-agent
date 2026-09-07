from __future__ import annotations

import re
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

    @staticmethod
    def _is_model_compatibility_error(exc: Exception) -> bool:
        text = " ".join(str(exc).lower().split())
        signals = (
            "not found for api version",
            "not supported for generatecontent",
            "method is not supported",
            "unsupported model",
            "only supports interactions api",
            "does not support generatecontent",
            "model is not supported",
        )
        return any(signal in text for signal in signals)

    @staticmethod
    def _model_rank(model_id: str, requested: str) -> tuple[int, int, int, int, str]:
        value = model_id.lower()
        requested_value = requested.lower()
        family = 0
        for token, weight in (("flash-lite", 3), ("flash", 2), ("pro", 1)):
            if token in requested_value and token in value:
                family = weight
                break
        stable = 0 if any(token in value for token in ("preview", "exp", "experimental", "latest")) else 1
        match = re.search(r"gemini-(\d+)(?:\.(\d+))?", value)
        major = int(match.group(1)) if match else 0
        minor = int(match.group(2) or 0) if match else 0
        return family, stable, major, minor, value

    def _fallback_generate_content_model(self, requested: str) -> str | None:
        candidates = [model.id for model in self.list_models() if model.id != requested]
        if not candidates:
            return None
        return max(candidates, key=lambda model_id: self._model_rank(model_id, requested))

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

        selected_model = str(model or "").strip()
        if not selected_model:
            raise AIProviderError("Modelo Gemini ausente.")

        try:
            payload = self._request(
                "POST",
                f"/models/{selected_model}:generateContent",
                json=body,
                headers={"Content-Type": "application/json"},
            ).json()
        except AIProviderError as exc:
            if not self._is_model_compatibility_error(exc):
                raise
            fallback = self._fallback_generate_content_model(selected_model)
            if not fallback:
                raise AIProviderError(
                    f"O modelo Gemini '{selected_model}' é incompatível com generateContent e nenhuma alternativa compatível foi encontrada."
                ) from exc
            selected_model = fallback
            payload = self._request(
                "POST",
                f"/models/{selected_model}:generateContent",
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
            model=selected_model,
            provider=self.provider_name,
            usage=payload.get("usageMetadata") or {},
            raw=payload,
        )
