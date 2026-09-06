from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .cloud_auth import IntrospectionTokenVerifier
from .cloud_runtime import CloudTenantResolver
from .dashboard_routes import install_dashboard_routes
from .observability import production_http_middleware
from .onboarding_service import OnboardingService
from .onboarding_sessions import OnboardingSessionStore
from .publication import publication_metadata_from_env, publication_readiness
from .publication_store import PublicationStore
from .public_pages import privacy_page, support_page, terms_page


COOKIE_NAME = "yca_onboarding_session"


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
    auth_method: str = "bearer"


def create_app(
    *,
    resolver: CloudTenantResolver | None = None,
    verifier: IntrospectionTokenVerifier | None = None,
    session_store: OnboardingSessionStore | None = None,
    publication_store: PublicationStore | None = None,
) -> FastAPI:
    resolver = resolver or CloudTenantResolver()
    verifier = verifier or IntrospectionTokenVerifier()
    onboarding = OnboardingService(resolver)
    web_sessions = session_store or OnboardingSessionStore(resolver.db)
    if publication_store is None and getattr(resolver.db, "path", None) is not None:
        publication_store = PublicationStore(resolver.db.path)

    docs_enabled = os.environ.get("YCA_ENABLE_API_DOCS", "0").strip() == "1"
    app = FastAPI(
        title="YouTube Creator Agent Onboarding API",
        version="13.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.middleware("http")(production_http_middleware)

    def enforce_limit(key: str, *, limit: int, window_seconds: int) -> None:
        if publication_store is None:
            return
        decision = publication_store.consume_rate_limit(
            key,
            limit=limit,
            window_seconds=window_seconds,
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Muitas solicitações. Aguarde e tente novamente.",
                headers={"Retry-After": str(decision.reset_after_seconds)},
            )

    def audit(
        request: Request,
        event_type: str,
        outcome: str,
        tenant_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if publication_store is None:
            return
        publication_store.record_event(
            event_type=event_type,
            outcome=outcome,
            tenant_id=tenant_id,
            request_id=getattr(request.state, "request_id", None),
            metadata=metadata,
        )

    async def authenticated_tenant(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> AuthenticatedTenant:
        if authorization and authorization.startswith("Bearer "):
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
                auth_method="bearer",
            )

        session_token = request.cookies.get(COOKIE_NAME, "")
        identity = web_sessions.resolve(session_token)
        if identity is not None:
            return AuthenticatedTenant(
                tenant_id=identity.tenant_id,
                subject="onboarding_web_session",
                scopes=list(identity.scopes),
                auth_method="cookie",
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessão não autenticada ou expirada.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def read_tenant(
        request: Request,
        tenant: AuthenticatedTenant = Depends(authenticated_tenant),
    ) -> AuthenticatedTenant:
        if "yca:read" not in tenant.scopes:
            raise HTTPException(status_code=403, detail="Escopo obrigatório ausente: yca:read")
        enforce_limit(f"read:{tenant.tenant_id}", limit=240, window_seconds=60)
        return tenant

    async def write_tenant(
        request: Request,
        tenant: AuthenticatedTenant = Depends(authenticated_tenant),
    ) -> AuthenticatedTenant:
        if "yca:write" not in tenant.scopes:
            raise HTTPException(status_code=403, detail="Escopo obrigatório ausente: yca:write")
        enforce_limit(f"write:{tenant.tenant_id}", limit=40, window_seconds=60)
        return tenant

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "service": "youtube-creator-agent-onboarding", "version": 13}

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy() -> HTMLResponse:
        return privacy_page()

    @app.get("/terms", response_class=HTMLResponse)
    async def terms() -> HTMLResponse:
        return terms_page()

    @app.get("/support", response_class=HTMLResponse)
    async def support() -> HTMLResponse:
        return support_page()

    @app.get("/ready")
    async def ready():
        report = publication_readiness()
        return JSONResponse(report.to_dict(), status_code=200 if report.ready else 503)

    @app.get("/api/app/metadata")
    async def app_metadata() -> dict:
        return publication_metadata_from_env().public_dict()

    @app.get("/onboarding/launch")
    async def onboarding_launch(request: Request, token: str = Query(min_length=32)):
        client_ip = request.client.host if request.client else "unknown"
        enforce_limit(f"launch:{client_ip}", limit=20, window_seconds=60)
        try:
            session_token, identity = web_sessions.exchange_launch(token)
        except PermissionError as exc:
            audit(request, "onboarding_launch", "denied")
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        audit(request, "onboarding_launch", "success", tenant_id=identity.tenant_id)
        response = RedirectResponse("/onboarding", status_code=303)
        secure_cookie = os.environ.get("YCA_SECURE_COOKIES", "1").strip() != "0"
        response.set_cookie(
            COOKIE_NAME,
            session_token,
            max_age=28800,
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/onboarding", response_class=FileResponse)
    async def onboarding_page(request: Request):
        identity = web_sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
        if identity is None:
            return RedirectResponse("/onboarding/session-expired", status_code=303)
        page = Path(__file__).resolve().parent / "web" / "onboarding.html"
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/onboarding/session-expired", response_class=HTMLResponse)
    async def onboarding_expired():
        return HTMLResponse(
            """<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
            <body style='margin:0;background:#050711;color:#eef7ff;font:16px system-ui;display:grid;place-items:center;min-height:100vh'>
            <main style='max-width:560px;padding:32px;text-align:center'><h1>Sessão encerrada</h1><p style='color:#8ea6bd'>Volte ao ChatGPT e peça para abrir ou configurar o YouTube Creator Agent novamente. Um novo link seguro será criado.</p></main></body></html>""",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/onboarding/logout")
    async def onboarding_logout(request: Request):
        token = request.cookies.get(COOKIE_NAME, "")
        identity = web_sessions.resolve(token)
        web_sessions.revoke(token)
        audit(
            request,
            "onboarding_logout",
            "success",
            tenant_id=identity.tenant_id if identity else None,
        )
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/me")
    async def me(tenant: AuthenticatedTenant = Depends(read_tenant)) -> dict:
        return {
            "tenant_id": tenant.tenant_id,
            "subject": tenant.subject,
            "scopes": tenant.scopes,
            "auth_method": tenant.auth_method,
        }

    @app.get("/api/onboarding/status")
    async def onboarding_status(tenant: AuthenticatedTenant = Depends(read_tenant)) -> dict:
        return onboarding.status(tenant.tenant_id)

    @app.post("/api/youtube/connect")
    async def youtube_connect(
        request: Request,
        tenant: AuthenticatedTenant = Depends(write_tenant),
    ) -> dict:
        result = onboarding.start_youtube_connection(tenant.tenant_id)
        audit(request, "youtube_connect_started", "success", tenant_id=tenant.tenant_id)
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
        audit(request, "youtube_connect_completed", "success", tenant_id=result.get("tenant_id"))
        success_url = os.environ.get("YCA_ONBOARDING_SUCCESS_URL", "").strip()
        if success_url:
            separator = "&" if "?" in success_url else "?"
            return RedirectResponse(f"{success_url}{separator}youtube=connected", status_code=302)
        if request.cookies.get(COOKIE_NAME):
            return RedirectResponse("/dashboard", status_code=303)
        return {
            "ok": True,
            "youtube_connected": result["youtube_connected"],
            "next_step": result["next_step"],
        }

    @app.delete("/api/youtube/connect")
    async def youtube_disconnect(
        request: Request,
        tenant: AuthenticatedTenant = Depends(write_tenant),
    ) -> dict:
        result = onboarding.disconnect_youtube(tenant.tenant_id)
        audit(request, "youtube_disconnect", "success", tenant_id=tenant.tenant_id)
        return result

    @app.post("/api/ai/test")
    async def ai_test(
        payload: AIProbeRequest,
        tenant: AuthenticatedTenant = Depends(write_tenant),
    ) -> dict:
        return onboarding.test_ai_connection(
            tenant.tenant_id,
            provider=payload.provider,
            api_key=payload.api_key,
            base_url=payload.base_url,
        )

    @app.post("/api/ai/models")
    async def ai_models(
        payload: AIProbeRequest,
        tenant: AuthenticatedTenant = Depends(write_tenant),
    ) -> dict:
        models = onboarding.list_ai_models(
            tenant.tenant_id,
            provider=payload.provider,
            api_key=payload.api_key,
            base_url=payload.base_url,
        )
        return {"models": models}

    @app.put("/api/ai/config")
    async def ai_config(
        request: Request,
        payload: AIConfigRequest,
        tenant: AuthenticatedTenant = Depends(write_tenant),
    ) -> dict:
        result = onboarding.configure_ai(
            tenant.tenant_id,
            provider=payload.provider,
            model=payload.model,
            api_key=payload.api_key,
            base_url=payload.base_url,
            validate_connection=payload.validate_connection,
        )
        audit(
            request,
            "external_ai_configured",
            "success",
            tenant_id=tenant.tenant_id,
            metadata={"provider": payload.provider, "model": payload.model},
        )
        return result

    install_dashboard_routes(
        app,
        resolver=resolver,
        verifier=verifier,
        web_sessions=web_sessions,
        cookie_name=COOKIE_NAME,
        publication_store=publication_store,
    )
    return app
