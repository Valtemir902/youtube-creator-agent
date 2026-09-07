from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from .credential_store import CredentialStore
from .key_pool import APIKeyPoolStore
from .registry import AIProviderRegistry
from .settings import AISettings, AISettingsStore
from .types import AIModel, AIProviderConfig, AIResponse, Messages


class AIRuntime:
    """Single entry point used by desktop, cloud and MCP surfaces.

    Desktop keeps secrets in the OS keyring. Cloud callers can inject a
    tenant-scoped encrypted credential store. Non-secret key-pool health metadata
    lives beside the AI settings file.
    """

    def __init__(
        self,
        settings_path: str | Path,
        *,
        credential_store: Any | None = None,
        settings_store: Any | None = None,
        key_pool_store: APIKeyPoolStore | None = None,
    ):
        settings_path = Path(settings_path)
        self.settings_store = settings_store or AISettingsStore(settings_path)
        self.credentials = credential_store or CredentialStore()
        self.key_pool = key_pool_store or APIKeyPoolStore(settings_path.with_name("ai_key_pool.json"))
        self.registry = AIProviderRegistry()

    def load_settings(self) -> AISettings:
        settings = self.settings_store.load()
        if settings.provider != "ollama":
            self._migrate_legacy_key_if_needed(settings.provider)
            settings.auto_rotate_keys = self.key_pool.auto_rotate(settings.provider) or settings.auto_rotate_keys
        return settings

    def save_settings(self, settings: AISettings, api_key: str | None = None) -> None:
        provider = settings.provider.strip().lower()
        settings.provider = provider
        if provider != "ollama":
            self._migrate_legacy_key_if_needed(provider)
            self.key_pool.set_auto_rotate(provider, settings.auto_rotate_keys)
            if api_key:
                self.add_api_key(provider, api_key, remember=settings.remember_api_key, make_active=True)
        self.settings_store.save(settings)

    @staticmethod
    def _supports_named_credentials(store: Any) -> bool:
        return all(hasattr(store, name) for name in ("save_named_key", "get_named_key", "delete_named_key"))

    def _migrate_legacy_key_if_needed(self, provider: str) -> None:
        provider = (provider or "").strip().lower()
        if not provider or provider == "ollama" or self.key_pool.list(provider):
            return
        legacy = self.credentials.get_key(provider)
        if not legacy:
            return
        record = self.key_pool.add(provider, legacy, label="Chave existente")
        try:
            if self._supports_named_credentials(self.credentials):
                self.credentials.save_named_key(provider, record.id, legacy)
        except Exception:
            self.key_pool.delete(provider, record.id)
            raise
        self.key_pool.set_active(provider, record.id)

    def add_api_key(
        self,
        provider: str,
        api_key: str,
        *,
        label: str = "",
        remember: bool = True,
        make_active: bool = True,
    ) -> dict:
        provider = provider.strip().lower()
        api_key = (api_key or "").strip()
        if provider == "ollama":
            raise ValueError("Ollama local não usa chave API.")
        if not api_key:
            raise ValueError("A chave API não pode ser vazia.")
        self._migrate_legacy_key_if_needed(provider)

        if self._supports_named_credentials(self.credentials):
            for record in self.key_pool.list(provider):
                existing = self.credentials.get_named_key(provider, record.id)
                if existing and secrets.compare_digest(existing, api_key):
                    if label:
                        self.key_pool.set_label(provider, record.id, label)
                    if make_active:
                        self.key_pool.set_active(provider, record.id)
                    return {**self.key_pool.export_public(provider)[self._record_index(provider, record.id)], "reused": True}

        record = self.key_pool.add(provider, api_key, label=label)
        try:
            if self._supports_named_credentials(self.credentials):
                if remember:
                    self.credentials.save_named_key(provider, record.id, api_key)
                elif hasattr(self.credentials, "set_named_session_key"):
                    self.credentials.set_named_session_key(provider, record.id, api_key)
                else:
                    self.credentials.save_named_key(provider, record.id, api_key)
            else:
                if remember:
                    self.credentials.save_key(provider, api_key)
                else:
                    self.credentials.set_session_key(provider, api_key)
            if remember:
                self.credentials.save_key(provider, api_key)
            else:
                self.credentials.set_session_key(provider, api_key)
        except Exception:
            self.key_pool.delete(provider, record.id)
            raise
        if make_active:
            self.key_pool.set_active(provider, record.id)
        return {**self.key_pool.export_public(provider)[self._record_index(provider, record.id)], "reused": False}

    def _record_index(self, provider: str, key_id: str) -> int:
        for index, item in enumerate(self.key_pool.list(provider)):
            if item.id == key_id:
                return index
        raise KeyError("Chave não encontrada no pool.")

    def list_api_keys(self, provider: str) -> list[dict]:
        self._migrate_legacy_key_if_needed(provider)
        return self.key_pool.export_public(provider)

    def set_active_api_key(self, provider: str, key_id: str) -> None:
        self.key_pool.set_active(provider, key_id)
        key = self._key_for_id(provider, key_id)
        if key:
            self.credentials.save_key(provider, key)

    def update_api_key_metadata(
        self,
        provider: str,
        key_id: str,
        *,
        label: str | None = None,
        preferred_model: str | None = None,
        enabled: bool | None = None,
        make_active: bool | None = None,
    ) -> dict:
        provider = provider.strip().lower()
        if self.key_pool.get(provider, key_id) is None:
            raise KeyError("Chave não encontrada no pool.")
        if label is not None:
            self.key_pool.set_label(provider, key_id, label)
        if preferred_model is not None:
            self.key_pool.set_preferred_model(provider, key_id, preferred_model)
        if enabled is not None:
            self.key_pool.set_enabled(provider, key_id, enabled)
        if make_active:
            self.set_active_api_key(provider, key_id)
        record = self.key_pool.get(provider, key_id)
        return {**(self.key_pool.export_public(provider)[self._record_index(provider, key_id)]), "provider": provider}

    def set_api_key_enabled(self, provider: str, key_id: str, enabled: bool) -> None:
        self.key_pool.set_enabled(provider, key_id, enabled)

    def set_auto_rotation(self, provider: str, enabled: bool) -> None:
        self.key_pool.set_auto_rotate(provider, enabled)
        settings = self.settings_store.load()
        if settings.provider.strip().lower() == provider.strip().lower():
            settings.auto_rotate_keys = bool(enabled)
            self.settings_store.save(settings)

    def delete_api_key(self, provider: str, key_id: str) -> None:
        provider = provider.strip().lower()
        if self._supports_named_credentials(self.credentials):
            self.credentials.delete_named_key(provider, key_id)
        self.key_pool.delete(provider, key_id)
        remaining = self.key_pool.list(provider)
        if not remaining:
            self.credentials.delete_key(provider)
            return
        active_id = self.key_pool.active_key_id(provider)
        active_key = self._key_for_id(provider, active_id)
        if active_key:
            self.credentials.save_key(provider, active_key)

    def _key_for_id(self, provider: str, key_id: str) -> str | None:
        if not key_id:
            return None
        if self._supports_named_credentials(self.credentials):
            return self.credentials.get_named_key(provider, key_id)
        return None

    def _resolve_key(self, provider: str, key_id: str | None = None) -> tuple[str | None, str]:
        if provider == "ollama":
            return None, ""
        self._migrate_legacy_key_if_needed(provider)
        selected_id = (key_id or self.key_pool.active_key_id(provider)).strip()
        if selected_id:
            key = self._key_for_id(provider, selected_id)
            if key:
                return key, selected_id
        key = self.credentials.get_key(provider)
        if key:
            return key, ""
        raise RuntimeError(f"Nenhuma chave API configurada para {provider}.")

    def _provider(self, settings: AISettings | None = None, api_key: str | None = None, *, key_id: str | None = None):
        settings = settings or self.load_settings()
        provider_name = settings.provider.strip().lower()
        if api_key is None:
            key, _ = self._resolve_key(provider_name, key_id)
        else:
            key = api_key
        if provider_name != "ollama" and not key:
            raise RuntimeError(f"Nenhuma chave API configurada para {provider_name}.")
        config = AIProviderConfig(
            provider=provider_name,
            api_key=key,
            base_url=settings.base_url.strip() or None,
            timeout_seconds=60.0,
        )
        return self.registry.create(config)

    def list_models(self, settings: AISettings | None = None, api_key: str | None = None, *, key_id: str | None = None) -> list[AIModel]:
        return self._provider(settings, api_key, key_id=key_id).list_models()

    def validate(self, settings: AISettings | None = None, api_key: str | None = None, *, key_id: str | None = None) -> bool:
        provider = self._provider(settings, api_key, key_id=key_id)
        return provider.validate_connection()

    def test_api_key(self, provider: str, key_id: str, *, model: str = "", base_url: str = "") -> dict:
        settings = AISettings(provider=provider, model=model, base_url=base_url)
        try:
            models = self.list_models(settings, key_id=key_id)
            model_ids = [item.id for item in models]
            selected_model = (model or "").strip()
            if selected_model:
                if selected_model not in model_ids:
                    raise RuntimeError(f"O modelo selecionado não está disponível para esta chave: {selected_model}")
                provider_obj = self._provider(settings, key_id=key_id)
                provider_obj.generate(
                    selected_model,
                    [{"role": "user", "content": "Responda somente OK."}],
                    temperature=0.0,
                    max_output_tokens=8,
                )
                self.key_pool.set_preferred_model(provider, key_id, selected_model)
            self.key_pool.mark_success(provider, key_id, model=selected_model)
            return {"ok": True, "models": model_ids, "count": len(model_ids), "tested_model": selected_model}
        except Exception as exc:
            warning, _rotate = self._classify_failure(exc)
            self.key_pool.mark_failure(provider, key_id, str(exc), warning=warning, model=model)
            raise

    @staticmethod
    def _classify_failure(exc: Exception) -> tuple[bool, bool]:
        text = " ".join(str(exc).lower().split())
        transient = (
            "429", "500", "502", "503", "504", "unavailable", "overloaded",
            "high demand", "resource exhausted", "resource_exhausted", "rate limit",
            "quota", "timeout", "timed out", "temporarily", "try again later",
        )
        auth = (
            "401", "403", "unauthenticated", "invalid api key", "api key invalid",
            "api_key_invalid", "permission denied", "permission_denied",
        )
        incompatible_model = (
            "only supports interactions api", "not supported for generatecontent",
            "unsupported model", "method is not supported", "not found for api version",
        )
        if any(token in text for token in transient):
            return True, True
        if any(token in text for token in auth):
            return False, True
        if any(token in text for token in incompatible_model):
            return False, True
        return False, False

    def _generate_with_key(
        self,
        *,
        settings: AISettings,
        key_id: str,
        selected_model: str,
        messages: Messages,
        temperature: float,
        max_output_tokens: int | None,
        response_format: str | None,
    ) -> AIResponse:
        provider_name = settings.provider.strip().lower()
        key = self._key_for_id(provider_name, key_id)
        if not key:
            raise RuntimeError("A credencial selecionada não está disponível no cofre seguro.")
        provider = self._provider(settings, key)
        try:
            response = provider.generate(
                selected_model,
                messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_format=response_format,
            )
        except Exception as exc:
            warning, _rotate = self._classify_failure(exc)
            self.key_pool.mark_failure(provider_name, key_id, str(exc), warning=warning, model=selected_model)
            raise
        self.key_pool.mark_success(provider_name, key_id, model=selected_model)
        self.key_pool.set_active(provider_name, key_id)
        self.credentials.save_key(provider_name, key)
        return response

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
        provider_name = settings.provider.strip().lower()

        if provider_name == "ollama":
            return self._provider(settings).generate(
                selected_model,
                messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_format=response_format,
            )

        self._migrate_legacy_key_if_needed(provider_name)
        all_records = self.key_pool.list(provider_name)
        ids = self.key_pool.ordered_enabled_ids(provider_name)
        if all_records and not ids:
            raise RuntimeError(f"Todas as chaves de {provider_name} estão desativadas.")
        if not ids:
            return self._provider(settings).generate(
                selected_model,
                messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_format=response_format,
            )

        rotation_enabled = bool(settings.auto_rotate_keys or self.key_pool.auto_rotate(provider_name))
        candidates = ids if rotation_enabled else ids[:1]
        failures: list[str] = []
        for index, key_id in enumerate(candidates):
            record = self.key_pool.get(provider_name, key_id)
            masked = record.masked if record else key_id
            key_model = (record.preferred_model if record and record.preferred_model else selected_model).strip()
            try:
                return self._generate_with_key(
                    settings=settings,
                    key_id=key_id,
                    selected_model=key_model,
                    messages=messages,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    response_format=response_format,
                )
            except Exception as exc:
                _warning, rotate = self._classify_failure(exc)
                failures.append(f"{masked}/{key_model}: {str(exc)}")
                has_next = index + 1 < len(candidates)
                if not rotation_enabled or not rotate or not has_next:
                    if rotation_enabled and not has_next and len(failures) > 1:
                        raise RuntimeError("Todas as chaves habilitadas falharam. " + " | ".join(failures)) from exc
                    raise

        raise RuntimeError("Nenhuma chave habilitada conseguiu concluir a solicitação.")
