from __future__ import annotations

import re
from typing import Any

from .base import AIProvider, AIProviderError
from .types import AIModel, AIResponse, Messages


class GeminiProvider(AIProvider):
    """Gemini provider using Google's supported ``google-genai`` SDK.

    The backend remains optional. ChatGPT-native Creator Agent flows never need
    this provider; it is only instantiated for explicitly configured Gemini
    operations in the standalone/dashboard surface.
    """

    provider_name = "gemini"
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

    def __init__(self, config):
        super().__init__(config)
        self._client_instance = None
        self._compatible_models: list[AIModel] | None = None

    def _client(self):
        if self._client_instance is not None:
            return self._client_instance
        if not self.config.api_key:
            raise AIProviderError("Chave API ausente para Gemini.")
        custom = str(self.config.base_url or "").strip().rstrip("/")
        if custom and custom not in {
            self.DEFAULT_BASE_URL,
            f"{self.DEFAULT_BASE_URL}/v1beta",
            f"{self.DEFAULT_BASE_URL}/v1",
        }:
            raise AIProviderError(
                "Base URL personalizada do Gemini não é suportada neste modo. Use o endpoint oficial do Gemini API."
            )
        try:
            from google import genai
            from google.genai import types

            timeout_ms = max(1_000, min(300_000, int(float(self.config.timeout_seconds) * 1000)))
            http_options = types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(
                    attempts=3,
                    initial_delay=0.5,
                    max_delay=4.0,
                    exp_base=2.0,
                    jitter=0.2,
                    http_status_codes=[429, 500, 502, 503, 504],
                ),
            )
            self._client_instance = genai.Client(api_key=self.config.api_key, http_options=http_options)
            return self._client_instance
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(f"Falha ao inicializar o cliente oficial do Gemini: {exc}") from exc

    @staticmethod
    def _model_id(value: str) -> str:
        return str(value or "").strip().removeprefix("models/")

    def list_models(self) -> list[AIModel]:
        if self._compatible_models is not None:
            return list(self._compatible_models)
        try:
            models: list[AIModel] = []
            for item in self._client().models.list():
                model_id = self._model_id(getattr(item, "name", ""))
                supported = tuple(getattr(item, "supported_actions", None) or ())
                if not model_id or "generateContent" not in supported:
                    continue
                models.append(
                    AIModel(
                        id=model_id,
                        name=str(getattr(item, "display_name", None) or model_id),
                        provider=self.provider_name,
                        capabilities=supported,
                        context_window=getattr(item, "input_token_limit", None),
                        metadata={
                            "output_token_limit": getattr(item, "output_token_limit", None),
                            "description": getattr(item, "description", None),
                        },
                    )
                )
            self._compatible_models = sorted(models, key=lambda model: model.name.casefold())
            return list(self._compatible_models)
        except AIProviderError:
            raise
        except Exception as exc:
            raise self._provider_error("listar modelos", exc) from exc

    @staticmethod
    def _convert_messages(messages: Messages):
        try:
            from google.genai import types
        except Exception as exc:
            raise AIProviderError("O pacote google-genai não está disponível no servidor.") from exc

        system_parts: list[str] = []
        contents = []
        for message in messages:
            role = str(message.get("role", "user"))
            text = str(message.get("content", ""))
            if role == "system":
                if text.strip():
                    system_parts.append(text)
                continue
            contents.append(
                types.Content(
                    role="model" if role == "assistant" else "user",
                    parts=[types.Part.from_text(text=text)],
                )
            )
        return "\n\n".join(system_parts) or None, contents

    @staticmethod
    def _is_model_compatibility_error(exc: Exception) -> bool:
        text = " ".join(str(exc).lower().split())
        return any(
            signal in text
            for signal in (
                "only supports interactions api",
                "not supported for generatecontent",
                "does not support generatecontent",
                "method is not supported",
                "unsupported model",
                "model is not supported",
            )
        )

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

    def _resolve_generate_content_model(self, requested: str) -> str:
        requested = self._model_id(requested)
        if not requested:
            raise AIProviderError("Modelo Gemini ausente.")
        compatible = [model.id for model in self.list_models()]
        if requested in compatible:
            return requested
        if not compatible:
            raise AIProviderError("Nenhum modelo Gemini compatível com generateContent está disponível para esta chave.")
        fallback = max(compatible, key=lambda model_id: self._model_rank(model_id, requested))
        return fallback

    @staticmethod
    def _provider_error(operation: str, exc: Exception) -> AIProviderError:
        text = " ".join(str(exc).strip().split())
        lowered = text.casefold()
        if "timeout" in lowered or "timed out" in lowered:
            return AIProviderError(f"Timeout ao {operation} no Gemini.")
        if GeminiProvider._is_model_compatibility_error(exc):
            return AIProviderError(f"Modelo Gemini incompatível com generateContent durante {operation}.")
        return AIProviderError(f"Falha ao {operation} no Gemini. {text[:800]}".strip())

    @staticmethod
    def _plain(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            try:
                return dict(dump(mode="json", exclude_none=True))
            except TypeError:
                return dict(dump(exclude_none=True))
        return {}

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
        try:
            from google.genai import types
        except Exception as exc:
            raise AIProviderError("O pacote google-genai não está disponível no servidor.") from exc

        selected_model = self._resolve_generate_content_model(model)
        system_instruction, contents = self._convert_messages(messages)
        config_kwargs: dict[str, Any] = {"temperature": temperature}
        if max_output_tokens is not None:
            config_kwargs["max_output_tokens"] = max_output_tokens
        if response_format == "json":
            config_kwargs["response_mime_type"] = "application/json"
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        try:
            response = self._client().models.generate_content(
                model=selected_model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            # Model compatibility is resolved before inference. If Google still
            # changes the model surface between list and generate, invalidate the
            # cache once and retry with the best currently compatible model.
            if self._is_model_compatibility_error(exc):
                self._compatible_models = None
                retry_model = self._resolve_generate_content_model(selected_model)
                if retry_model != selected_model:
                    try:
                        response = self._client().models.generate_content(
                            model=retry_model,
                            contents=contents,
                            config=types.GenerateContentConfig(**config_kwargs),
                        )
                        selected_model = retry_model
                    except Exception as retry_exc:
                        raise self._provider_error("gerar conteúdo", retry_exc) from retry_exc
                else:
                    raise self._provider_error("gerar conteúdo", exc) from exc
            else:
                raise self._provider_error("gerar conteúdo", exc) from exc

        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise AIProviderError("Gemini retornou uma resposta sem texto utilizável.")
        usage = self._plain(getattr(response, "usage_metadata", None))
        raw = self._plain(response)
        return AIResponse(
            text=text,
            model=selected_model,
            provider=self.provider_name,
            usage=usage,
            raw=raw,
        )
