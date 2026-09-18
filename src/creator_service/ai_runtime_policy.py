from __future__ import annotations

from typing import Any


def _enabled_records(store, provider: str):
    return [item for item in store.list(provider) if item.enabled]


def install_ai_runtime_policy() -> None:
    """Make enabled/active/rotation state authoritative for every AI request.

    The old credential slot remains only as a migration bridge when no key-pool
    metadata exists. Once a pool exists, a disabled key can never be selected by
    fallback through that legacy slot.
    """
    from ai.key_pool import APIKeyPoolStore
    from ai.runtime import AIRuntime
    from .onboarding_service import OnboardingService
    from .service import CreatorService

    if getattr(AIRuntime, "_yca_pool_policy_installed", False):
        return

    original_set_enabled = APIKeyPoolStore.set_enabled
    original_delete = APIKeyPoolStore.delete
    original_set_active = APIKeyPoolStore.set_active
    original_creator_status = CreatorService.status
    original_onboarding_status = OnboardingService.status

    def set_active(self, provider: str, key_id: str) -> None:
        if key_id:
            record = self.get(provider, key_id)
            if record is None:
                raise KeyError("Chave não encontrada no pool.")
            if not record.enabled:
                raise ValueError("Uma chave desativada não pode ser selecionada para uso.")
        original_set_active(self, provider, key_id)

    def set_enabled(self, provider: str, key_id: str, enabled: bool) -> None:
        original_set_enabled(self, provider, key_id, enabled)
        active = self.active_key_id(provider)
        records = _enabled_records(self, provider)
        enabled_ids = [item.id for item in records]
        if not enabled:
            if active == key_id:
                original_set_active(self, provider, enabled_ids[0] if enabled_ids else "")
        elif not active or active not in enabled_ids:
            original_set_active(self, provider, key_id)

    def delete(self, provider: str, key_id: str) -> None:
        was_active = self.active_key_id(provider) == key_id
        original_delete(self, provider, key_id)
        if was_active:
            enabled = _enabled_records(self, provider)
            original_set_active(self, provider, enabled[0].id if enabled else "")

    def ordered_enabled_ids(self, provider: str) -> list[str]:
        records = _enabled_records(self, provider)
        if not records:
            return []
        ids = [item.id for item in records]
        active = self.active_key_id(provider)
        if active not in ids:
            active = ids[0]
            original_set_active(self, provider, active)
        ids.remove(active)
        ids.insert(0, active)
        return ids

    def resolve_key(self, provider: str, key_id: str | None = None):
        if provider == "ollama":
            return None, ""
        self._migrate_legacy_key_if_needed(provider)
        records = self.key_pool.list(provider)
        if records:
            if key_id:
                record = self.key_pool.get(provider, key_id)
                if record is None:
                    raise RuntimeError("A chave selecionada não existe mais no cofre.")
                if not record.enabled:
                    raise RuntimeError("A chave selecionada está desativada e não será utilizada.")
                key = self._key_for_id(provider, key_id)
                if not key:
                    raise RuntimeError("A credencial selecionada não está disponível no cofre seguro.")
                return key, key_id
            ids = self.key_pool.ordered_enabled_ids(provider)
            if not ids:
                raise RuntimeError(f"Todas as chaves de {provider} estão desativadas.")
            selected = ids[0]
            key = self._key_for_id(provider, selected)
            if not key:
                raise RuntimeError("A chave ativa não possui credencial disponível no cofre seguro.")
            return key, selected
        legacy = self.credentials.get_key(provider)
        if legacy:
            return legacy, ""
        raise RuntimeError(f"Nenhuma chave API configurada para {provider}.")

    def select_api_keys(self, provider: str, key_ids: list[str], *, rotate: bool) -> dict[str, Any]:
        provider = provider.strip().lower()
        wanted = []
        seen = set()
        for raw in key_ids:
            key_id = str(raw or "").strip()
            if key_id and key_id not in seen:
                wanted.append(key_id)
                seen.add(key_id)
        if not wanted:
            raise ValueError("Selecione pelo menos uma chave para uso.")
        payload = self.key_pool._load()
        bucket = self.key_pool._bucket(payload, provider)
        existing = {str(item.get("id", "")): item for item in bucket.get("keys", [])}
        missing = [item for item in wanted if item not in existing]
        if missing:
            raise KeyError("Uma ou mais chaves selecionadas não existem mais no cofre.")
        for key_id in wanted:
            if not self._key_for_id(provider, key_id):
                raise RuntimeError("Uma das chaves selecionadas não possui credencial disponível no cofre seguro.")
        selected = set(wanted)
        for item in bucket.get("keys", []):
            item["enabled"] = str(item.get("id", "")) in selected
        bucket["active_key_id"] = wanted[0]
        bucket["auto_rotate"] = bool(rotate)
        self.key_pool._save(payload)
        key = self._key_for_id(provider, wanted[0])
        if key:
            self.credentials.save_key(provider, key)
        settings = self.settings_store.load()
        if settings.provider.strip().lower() == provider:
            settings.auto_rotate_keys = bool(rotate)
            self.settings_store.save(settings)
        return {
            "provider": provider,
            "selected_key_ids": wanted,
            "active_key_id": wanted[0],
            "auto_rotate": bool(rotate),
            "keys": self.list_api_keys(provider),
        }

    def usable_status(runtime, provider: str, model: str) -> tuple[bool, int]:
        if provider == "ollama":
            return bool(model), 0
        records = runtime.key_pool.list(provider)
        usable = [item for item in records if item.enabled and runtime._key_for_id(provider, item.id)]
        if not records:
            return bool(model and runtime.credentials.get_key(provider)), 0
        return bool(model and usable), len(usable)

    def creator_status(self):
        result = original_creator_status(self)
        settings = self.ai_runtime.load_settings()
        configured, count = usable_status(self.ai_runtime, settings.provider.strip().lower(), settings.model)
        result["external_ai_configured"] = configured
        result["ai_enabled_key_count"] = count
        result["ai_auto_rotate_keys"] = bool(self.ai_runtime.key_pool.auto_rotate(settings.provider)) if settings.provider != "ollama" else False
        return result

    def onboarding_status(self, tenant_id: str):
        result = original_onboarding_status(self, tenant_id)
        runtime = self._runtime(tenant_id)
        settings = runtime.load_settings()
        configured, count = usable_status(runtime, settings.provider.strip().lower(), settings.model)
        result["ai"]["configured"] = configured
        result["ai"]["api_key_configured"] = configured if settings.provider != "ollama" else True
        result["ai"]["enabled_key_count"] = count
        result["intelligence_modes"]["standalone"]["ready"] = bool(result.get("youtube_connected") and configured)
        return result

    APIKeyPoolStore.set_active = set_active
    APIKeyPoolStore.set_enabled = set_enabled
    APIKeyPoolStore.delete = delete
    APIKeyPoolStore.ordered_enabled_ids = ordered_enabled_ids
    AIRuntime._resolve_key = resolve_key
    AIRuntime.select_api_keys = select_api_keys
    AIRuntime._yca_pool_policy_installed = True
    CreatorService.status = creator_status
    OnboardingService.status = onboarding_status
