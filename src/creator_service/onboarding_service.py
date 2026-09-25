from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ai.runtime import AIRuntime
from ai.settings import AISettings

from .cloud_runtime import CloudTenantResolver, GOOGLE_SECRET_NAME
from .channel_accounts import capture_current_channel
from .google_oauth import GoogleOAuthCoordinator


class OnboardingService:
    """Authenticated, tenant-scoped onboarding operations for the cloud product."""

    def __init__(self, resolver: CloudTenantResolver):
        self.resolver = resolver
        self.db = resolver.db
        self.google_oauth = GoogleOAuthCoordinator(self.db)

    def _context(self, tenant_id: str):
        return self.resolver.resolve(tenant_id)

    def _runtime(self, tenant_id: str) -> AIRuntime:
        context = self._context(tenant_id)
        return AIRuntime(context.ai_settings_file, credential_store=context.credential_store)

    def status(self, tenant_id: str) -> dict[str, Any]:
        self._context(tenant_id)
        runtime = self._runtime(tenant_id)
        settings = runtime.load_settings()
        youtube_connected = self.db.get_secret(tenant_id, GOOGLE_SECRET_NAME) is not None
        api_key_configured = True if settings.provider.strip().lower() == "ollama" else runtime.credentials.get_key(settings.provider) is not None
        external_ai_configured = bool(settings.model and api_key_configured)
        chatgpt_native_ready = bool(youtube_connected)
        standalone_ready = bool(youtube_connected and external_ai_configured)
        return {
            "tenant_id": tenant_id,
            "youtube_connected": youtube_connected,
            "intelligence_modes": {
                "chatgpt_native": {
                    "ready": chatgpt_native_ready,
                    "external_ai_required": False,
                    "next_step": "ready" if chatgpt_native_ready else "connect_youtube",
                },
                "standalone": {
                    "ready": standalone_ready,
                    "external_ai_required": True,
                    "next_step": self._standalone_next_step(
                        youtube_connected=youtube_connected,
                        model_configured=bool(settings.model),
                        api_key_configured=api_key_configured,
                    ),
                },
            },
            "ai": {
                "provider": settings.provider,
                "model": settings.model,
                "base_url": settings.base_url,
                "api_key_configured": api_key_configured,
                "configured": external_ai_configured,
                "optional_for_chatgpt": True,
                "auto_rotate_keys": bool(runtime.key_pool.auto_rotate(settings.provider)) if settings.provider != "ollama" else False,
                "key_count": len(runtime.list_api_keys(settings.provider)) if settings.provider != "ollama" else 0,
            },
            "ready": chatgpt_native_ready,
            "recommended_mode": "chatgpt_native" if chatgpt_native_ready else "not_ready",
            "next_step": "ready" if chatgpt_native_ready else "connect_youtube",
        }

    @staticmethod
    def _standalone_next_step(*, youtube_connected: bool, model_configured: bool, api_key_configured: bool) -> str:
        if not youtube_connected:
            return "connect_youtube"
        if not api_key_configured:
            return "configure_ai_key"
        if not model_configured:
            return "select_ai_model"
        return "ready"

    def start_youtube_connection(self, tenant_id: str) -> dict[str, Any]:
        return asdict(self.google_oauth.start(tenant_id))

    def complete_youtube_connection(self, *, state: str, authorization_response: str) -> dict[str, Any]:
        tenant_id = self.google_oauth.complete(state=state, authorization_response=authorization_response)
        try:
            capture_current_channel(self.db, tenant_id)
        except Exception:
            pass
        return self.status(tenant_id)

    def disconnect_youtube(self, tenant_id: str) -> dict[str, Any]:
        self.google_oauth.disconnect(tenant_id)
        return self.status(tenant_id)

    def ai_key_pool(self, tenant_id: str, provider: str) -> dict[str, Any]:
        provider = provider.strip().lower()
        runtime = self._runtime(tenant_id)
        if provider not in runtime.registry.available_providers():
            raise ValueError(f"Provedor de IA não suportado: {provider}")
        if provider == "ollama":
            return {"provider": provider, "auto_rotate": False, "active_key_id": "", "keys": []}
        keys = runtime.list_api_keys(provider)
        return {
            "provider": provider,
            "auto_rotate": runtime.key_pool.auto_rotate(provider),
            "active_key_id": runtime.key_pool.active_key_id(provider),
            "keys": keys,
        }

    def add_ai_key(self, tenant_id: str, *, provider: str, api_key: str, label: str = "", base_url: str = "") -> dict[str, Any]:
        provider = provider.strip().lower()
        runtime = self._runtime(tenant_id)
        if provider not in runtime.registry.available_providers() or provider == "ollama":
            raise ValueError("Este provedor não aceita chaves no cofre.")
        record = runtime.add_api_key(provider, api_key, label=label, remember=True, make_active=True)
        test_error = ""
        models: list[str] = []
        try:
            probe = runtime.test_api_key(provider, record["id"], base_url=base_url)
            models = list(probe.get("models") or [])
        except Exception as exc:
            test_error = str(exc)[:1200]
        current = runtime.key_pool.get(provider, record["id"])
        public = runtime.list_api_keys(provider)[runtime._record_index(provider, record["id"])]
        return {
            "key": public,
            "models": models,
            "model_count": len(models),
            "test_ok": bool(models) and not test_error,
            "test_error": test_error,
            "status": current.status if current else "unknown",
        }

    def test_ai_key(self, tenant_id: str, *, provider: str, key_id: str, model: str = "", base_url: str = "") -> dict[str, Any]:
        runtime = self._runtime(tenant_id)
        result = runtime.test_api_key(provider.strip().lower(), key_id, model=model.strip(), base_url=base_url.strip())
        result["key"] = runtime.list_api_keys(provider)[runtime._record_index(provider, key_id)]
        return result

    def update_ai_key(
        self,
        tenant_id: str,
        *,
        provider: str,
        key_id: str,
        label: str | None = None,
        preferred_model: str | None = None,
        enabled: bool | None = None,
        make_active: bool | None = None,
    ) -> dict[str, Any]:
        runtime = self._runtime(tenant_id)
        return runtime.update_api_key_metadata(
            provider.strip().lower(),
            key_id,
            label=label,
            preferred_model=preferred_model,
            enabled=enabled,
            make_active=make_active,
        )

    def delete_ai_key(self, tenant_id: str, *, provider: str, key_id: str) -> dict[str, Any]:
        runtime = self._runtime(tenant_id)
        runtime.delete_api_key(provider.strip().lower(), key_id)
        return self.ai_key_pool(tenant_id, provider)

    def set_ai_rotation(self, tenant_id: str, *, provider: str, enabled: bool) -> dict[str, Any]:
        runtime = self._runtime(tenant_id)
        runtime.set_auto_rotation(provider.strip().lower(), enabled)
        return self.ai_key_pool(tenant_id, provider)

    def configure_ai(
        self,
        tenant_id: str,
        *,
        provider: str,
        model: str,
        api_key: str | None = None,
        base_url: str = "",
        validate_connection: bool = True,
    ) -> dict[str, Any]:
        provider = provider.strip().lower()
        runtime = self._runtime(tenant_id)
        supported = runtime.registry.available_providers()
        if provider not in supported:
            raise ValueError(f"Provedor de IA não suportado: {provider}")
        if provider == "openai_compatible" and not base_url.strip():
            raise ValueError("base_url é obrigatória para provedor OpenAI-compatible.")
        if provider != "ollama" and api_key:
            runtime.add_api_key(provider, api_key, remember=True, make_active=True)
        settings = AISettings(
            provider=provider,
            model=model.strip(),
            base_url=base_url.strip(),
            remember_api_key=True,
            auto_rotate_keys=runtime.key_pool.auto_rotate(provider) if provider != "ollama" else False,
        )
        if provider != "ollama" and not runtime.credentials.get_key(provider):
            raise ValueError("Adicione pelo menos uma API key para este provedor.")
        if validate_connection:
            if provider == "ollama":
                if not runtime.validate(settings=settings):
                    raise RuntimeError("O provedor de IA recusou a conexão.")
            else:
                active_id = runtime.key_pool.active_key_id(provider)
                if not active_id:
                    raise RuntimeError("Nenhuma chave ativa foi selecionada.")
                runtime.test_api_key(provider, active_id, model=model.strip(), base_url=base_url.strip())
        runtime.save_settings(settings)
        return self.status(tenant_id)

    def list_ai_models(self, tenant_id: str, *, provider: str, api_key: str | None = None, base_url: str = "") -> list[dict[str, Any]]:
        provider = provider.strip().lower()
        runtime = self._runtime(tenant_id)
        settings = AISettings(provider=provider, model="", base_url=base_url.strip(), remember_api_key=True)
        models = runtime.list_models(settings=settings, api_key=api_key)
        return [asdict(model) for model in models]

    def test_ai_connection(self, tenant_id: str, *, provider: str, api_key: str | None = None, base_url: str = "") -> dict[str, Any]:
        runtime = self._runtime(tenant_id)
        settings = AISettings(provider=provider.strip().lower(), model="", base_url=base_url.strip(), remember_api_key=True)
        return {"ok": bool(runtime.validate(settings=settings, api_key=api_key))}
