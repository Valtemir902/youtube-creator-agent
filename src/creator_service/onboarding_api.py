from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .cloud_auth import IntrospectionTokenVerifier
from .cloud_runtime import CloudTenantResolver
from .onboarding_service import OnboardingService


class AIConfigRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    model: str = Field(default="", max_length=200)
    api_key: str | None = Field(default=None, max_length=5000)
    base_url: str = Field(default="", max_length=1000)
    validate_connection: bool = True


class AIProbeRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    api_key: str | None = Field(default=None, max_length=5000)
    base_url: str = Field(default="", max_length=1000)


class AuthenticatedTenant(BaseModel):
    tenant_id: str
    subject: str
    scopes: list[str]


def create_app(
    *,
    resolver: CloudTenantResolver | None = None,
    verifier: IntrospectionTokenVerifier | None = None,
) -> FastAPI:
    resolver = resolver or CloudTenantResolver()
    verifier = verifier or IntrospectionTokenVerifier()
    onboarding = OnboardingService(resolver)

    docs_enabled = os.environ.get("YCA_ENABLE_API_DOCS", "0").strip() == "1"
    app = FastAPI(
        title="YouTube Creator Agent Onboarding API",
        version="10.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    async def authenticated_tenant(
        authorization: Annotated[str | None, Header()] = None,
    ) -> AuthenticatedTenant:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token obrigatório.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raw_token = authorization[7:].strip()
        if not raw_token:
            raise HTTPException(status_code=401, detail="Bearer token vazio.")
        access = await verifier.verify_token(raw_token)
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido ou expirado.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        tenant_id = str((access.claims or {}).get("tenant_id", "")).strip()
        if not tenant_id:
            raise HTTPException(status_code=403, detail="Token não está vinculado a um tenant.")
        resolver.db.ensure_tenant(tenant_id)
        return AuthenticatedTenant(
            tenant_id=tenant_id,
            subject=str(access.subject or ""),
            scopes=list(access.scopes or []),
        )

    def require_scope(scope: str):
        async def dependency(
            tenant: Annotated[AuthenticatedTenant, Depends(authenticated_tenant)],
        ) -> AuthenticatedTenant:
            if scope not in tenant.scopes:
                raise HTTPException(status_code=403, detail=f"Escopo obrigatório ausente: {scope}")
            return tenant
        return dependency

    ReadTenant = Annotated[AuthenticatedTenant, Depends(require_scope("yca:read"))]
    WriteTenant = Annotated[AuthenticatedTenant, Depends(require_scope("yca:write"))]

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "service": "youtube-creator-agent-onboarding"}

    @app.get("/api/me")
    async def me(tenant: ReadTenant) -> dict:
        return {
            "tenant_id": tenant.tenant_id,
            "subject": tenant.subject,
            "scopes": tenant.scopes,
        }

    @app.get("/api/onboarding/status")
    async def onboarding_status(tenant: ReadTenant) -> dict:
        return onboarding.status(tenant.tenant_id)

    @app.post("/api/youtube/connect")
    async def youtube_connect(tenant: WriteTenant) -> dict:
        result = onboarding.start_youtube_connection(tenant.tenant_id)
        return {
            "authorization_url": result["authorization_url"],
            "expires_in_seconds": result["expires_in_seconds"],
        }

    @app.get("/oauth/google/callback")
    async def google_callback(request: Request, state: str = Query(min_length=20)):
        authorization_response = str(request.url)
        result = onboarding.complete_youtube_connection(
            state=state,
            authorization_response=authorization_response,
        )
        success_url = os.environ.get("YCA_ONBOARDING_SUCCESS_URL", "").strip()
        if success_url:
            separator = "&" if "?" in success_url else "?"
            return RedirectResponse(f"{success_url}{separator}youtube=connected", status_code=302)
        return {
            "ok": True,
            "youtube_connected": result["youtube_connected"],
            "next_step": result["next_step"],
        }

    @app.delete("/api/youtube/connect")
    async def youtube_disconnect(tenant: WriteTenant) -> dict:
        return onboarding.disconnect_youtube(tenant.tenant_id)

    @app.post("/api/ai/test")
    async def ai_test(payload: AIProbeRequest, tenant: WriteTenant) -> dict:
        return onboarding.test_ai_connection(
            tenant.tenant_id,
            provider=payload.provider,
            api_key=payload.api_key,
            base_url=payload.base_url,
        )

    @app.post("/api/ai/models")
    async def ai_models(payload: AIProbeRequest, tenant: WriteTenant) -> dict:
        models = onboarding.list_ai_models(
            tenant.tenant_id,
            provider=payload.provider,
            api_key=payload.api_key,
            base_url=payload.base_url,
        )
        return {"models": models}

    @app.put("/api/ai/config")
    async def ai_config(payload: AIConfigRequest, tenant: WriteTenant) -> dict:
        return onboarding.configure_ai(
            tenant.tenant_id,
            provider=payload.provider,
            model=payload.model,
            api_key=payload.api_key,
            base_url=payload.base_url,
            validate_connection=payload.validate_connection,
        )

    return app
