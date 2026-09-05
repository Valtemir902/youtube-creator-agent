from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ai.runtime import AIRuntime
from ai.settings import AISettings

from .cloud_runtime import CloudTenantResolver, GOOGLE_SECRET_NAME
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
        return AIRuntime(
            context.ai_settings_file,
            credential_store=context.credential_store,
        )

    def status(self, tenant_id: str) -> dict[str, Any]:
        context = self._context(tenant_id)
        runtime = self._runtime(tenant_id)
        settings = runtime.load_settings()
        youtube_connected = self.db.get_secret(tenant_id, GOOGLE_SECRET_NAME) is not None
        api_key_configured = (
            True
            if settings.provider.strip().lower() == "ollama"
            else runtime.credentials.get_key(settings.provider) is not None
        )
        ready = bool(youtube_connected and settings.model and api_key_configured)
        return {
            "tenant_id": tenant_id,
            "youtube_connected": youtube_connected,
            "ai": {
                "provider": settings.provider,
                "model": settings.model,
                "base_url": settings.base_url,
                "api_key_configured": api_key_configured,
            },
            "ready": ready,
            "next_step": self._next_step(
                youtube_connected=youtube_connected,
                model_configured=bool(settings.model),
                api_key_configured=api_key_configured,
            ),
        }

    @staticmethod
    def _next_step(*, youtube_connected: bool, model_configured: bool, api_key_configured: bool) -> str:
        if not youtube_connected:
            return "connect_youtube"
        if not api_key_configured:
            return "configure_ai_key"
        if not model_configured:
            return "select_ai_model"
        return "ready"

    def start_youtube_connection(self, tenant_id: str) -> dict[str, Any]:
        result = self.google_oauth.start(tenant_id)
        return asdict(result)

    def complete_youtube_connection(self, *, state: str, authorization_response: str) -> dict[str, Any]:
        tenant_id = self.google_oauth.complete(
            state=state,
            authorization_response=authorization_response,
        )
        return self.status(tenant_id)

    def disconnect_youtube(self, tenant_id: str) -> dict[str, Any]:
        self.google_oauth.disconnect(tenant_id)
        return self.status(tenant_id)

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
        settings = AISettings(
            provider=provider,
            model=model.strip(),
            base_url=base_url.strip(),
            remember_api_key=True,
        )
        if provider != "ollama" and not api_key and not runtime.credentials.get_key(provider):
            raise ValueError("API key é obrigatória para este provedor.")
        if validate_connection:
            if not runtime.validate(settings=settings, api_key=api_key):
                raise RuntimeError("O provedor de IA recusou a conexão ou a credencial.")
        runtime.save_settings(settings, api_key=api_key)
        return self.status(tenant_id)

    def list_ai_models(
        self,
        tenant_id: str,
        *,
        provider: str,
        api_key: str | None = None,
        base_url: str = "",
    ) -> list[dict[str, Any]]:
        provider = provider.strip().lower()
        runtime = self._runtime(tenant_id)
        settings = AISettings(
            provider=provider,
            model="",
            base_url=base_url.strip(),
            remember_api_key=True,
        )
        models = runtime.list_models(settings=settings, api_key=api_key)
        return [asdict(model) for model in models]

    def test_ai_connection(
        self,
        tenant_id: str,
        *,
        provider: str,
        api_key: str | None = None,
        base_url: str = "",
    ) -> dict[str, Any]:
        runtime = self._runtime(tenant_id)
        settings = AISettings(
            provider=provider.strip().lower(),
            model="",
            base_url=base_url.strip(),
            remember_api_key=True,
        )
        return {"ok": bool(runtime.validate(settings=settings, api_key=api_key))}
