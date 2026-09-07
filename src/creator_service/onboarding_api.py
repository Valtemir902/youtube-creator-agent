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
from .web_auth import BrowserAuthStore, BrowserOIDCClient, TurnstileVerifier


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


class BrowserAuthRequest(BaseModel):
    mode: str = Field(default="login", pattern="^(login|register|recover)$")
    next: str = Field(default="/dashboard", max_length=300)
    turnstile_token: str = Field(default="", max_length=4096)


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
    browser_auth = BrowserAuthStore(resolver.db) if hasattr(resolver.db, "_connect") else None
    if publication_store is None and getattr(resolver.db, "path", None) is not None:
        publication_store = PublicationStore(resolver.db.path)

    docs_enabled = os.environ.get("YCA_ENABLE_API_DOCS", "0").strip() == "1"
    app = FastAPI(
        title="YouTube Creator Agent Onboarding API",
        version="14.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.middleware("http")(production_http_middleware)

    def secure_cookie_enabled() -> bool:
        return os.environ.get("YCA_SECURE_COOKIES", "1").strip() != "0"

    def public_origin() -> str:
        return os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")

    def set_session_cookie(response, token: str, max_age: int = 28800) -> None:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=max_age,
            httponly=True,
            secure=secure_cookie_enabled(),
            samesite="lax",
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"

    def enforce_limit(key: str, *, limit: int, window_seconds: int) -> None:
        if publication_store is None:
            return
        decision = publication_store.consume_rate_limit(key, limit=limit, window_seconds=window_seconds)
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
                subject="browser_web_session",
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

    @app.get("/")
    async def root(request: Request):
        identity = web_sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
        return RedirectResponse("/dashboard" if identity else "/login", status_code=303)

    @app.get("/login", response_class=FileResponse)
    async def login_page(request: Request):
        identity = web_sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
        if identity is not None:
            return RedirectResponse("/dashboard", status_code=303)
        page = Path(__file__).resolve().parent / "web" / "login.html"
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/api/auth/config")
    async def auth_config() -> dict:
        turnstile = TurnstileVerifier()
        try:
            BrowserOIDCClient()
            oidc_ready = True
        except RuntimeError:
            oidc_ready = False
        return {
            "oidc_ready": oidc_ready,
            "turnstile_required": not turnstile.bypass,
            "turnstile_ready": turnstile.configured,
            "turnstile_bypass": turnstile.bypass,
            "turnstile_site_key": turnstile.site_key if not turnstile.bypass else "",
        }

    @app.post("/api/auth/begin")
    async def auth_begin(payload: BrowserAuthRequest, request: Request) -> dict:
        client_ip = request.client.host if request.client else "unknown"
        enforce_limit(f"browser-auth:{client_ip}", limit=12, window_seconds=60)
        if browser_auth is None:
            raise HTTPException(status_code=503, detail="Armazenamento de autenticação web indisponível.")
        turnstile = TurnstileVerifier()
        if not turnstile.configured:
            raise HTTPException(status_code=503, detail="Proteção anti-robô ainda não foi configurada no servidor.")
        if not turnstile.verify(payload.turnstile_token, client_ip):
            audit(request, "browser_auth_challenge", "denied", metadata={"mode": payload.mode})
            raise HTTPException(status_code=403, detail="Verificação anti-robô inválida ou expirada.")
        try:
            oidc = BrowserOIDCClient()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        pending = browser_auth.issue(next_path=payload.next, mode=payload.mode)
        audit(request, "browser_auth_started", "success", metadata={"mode": payload.mode})
        return {"authorization_url": oidc.authorization_url(pending), "expires_in_seconds": 600}

    @app.get("/auth/callback")
    async def auth_callback(
        request: Request,
        state: str = Query(min_length=20),
        code: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ):
        client_ip = request.client.host if request.client else "unknown"
        enforce_limit(f"browser-callback:{client_ip}", limit=24, window_seconds=60)
        if browser_auth is None:
            raise HTTPException(status_code=503, detail="Armazenamento de autenticação web indisponível.")
        try:
            pending = browser_auth.consume(state)
        except PermissionError as exc:
            audit(request, "browser_auth_callback", "denied")
            return RedirectResponse(f"/login?error={str(exc).replace(' ', '+')}", status_code=303)
        if error or not code:
            audit(request, "browser_auth_callback", "cancelled", metadata={"provider_error": error or "missing_code"})
            return RedirectResponse("/login?error=acesso_cancelado", status_code=303)
        try:
            oidc = BrowserOIDCClient()
            tokens = oidc.exchange_code(code=code, verifier=pending.verifier)
            profile = oidc.userinfo(str(tokens["access_token"]))
            subject = str(profile["sub"])
            tenant_id = oidc.tenant_id(subject)
            resolver.db.ensure_tenant(tenant_id)
            session_token, identity = web_sessions.issue_session(tenant_id, ("yca:read", "yca:write"))
        except (RuntimeError, PermissionError, KeyError) as exc:
            audit(request, "browser_auth_callback", "denied", metadata={"reason": type(exc).__name__})
            return RedirectResponse(f"/login?error={urllib_quote(str(exc))}", status_code=303)
        audit(
            request,
            "browser_auth_callback",
            "success",
            tenant_id=identity.tenant_id,
            metadata={"mode": pending.mode, "email_verified": profile.get("email_verified")},
        )
        destination = pending.next_path
        if destination == "/dashboard":
            try:
                status_payload = onboarding.status(identity.tenant_id)
                if not status_payload.get("youtube_connected"):
                    destination = "/onboarding"
            except Exception:
                destination = "/onboarding"
        response = RedirectResponse(destination, status_code=303)
        set_session_cookie(response, session_token)
        return response

    @app.get("/auth/logout")
    async def auth_logout(request: Request):
        token = request.cookies.get(COOKIE_NAME, "")
        identity = web_sessions.resolve(token)
        web_sessions.revoke(token)
        audit(request, "browser_logout", "success", tenant_id=identity.tenant_id if identity else None)
        redirect_target = "/login"
        origin = public_origin()
        try:
            oidc = BrowserOIDCClient()
            if origin:
                redirect_target = oidc.logout_url(f"{origin}/login")
        except RuntimeError:
            pass
        response = RedirectResponse(redirect_target, status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "service": "youtube-creator-agent-onboarding", "version": 14}

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
        set_session_cookie(response, session_token)
        return response

    @app.get("/onboarding", response_class=FileResponse)
    async def onboarding_page(request: Request):
        identity = web_sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
        if identity is None:
            return RedirectResponse("/login?next=/onboarding", status_code=303)
        page = Path(__file__).resolve().parent / "web" / "onboarding.html"
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/onboarding/session-expired", response_class=HTMLResponse)
    async def onboarding_expired():
        return HTMLResponse(
            """<!doctype html><html lang='pt-BR'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
            <body style='margin:0;background:#050711;color:#eef7ff;font:16px system-ui;display:grid;place-items:center;min-height:100vh'>
            <main style='max-width:560px;padding:32px;text-align:center'><h1>Sessão encerrada</h1><p style='color:#8ea6bd'>Sua sessão terminou com segurança. Entre novamente para continuar no Creator Agent Elite.</p><p><a href='/login' style='display:inline-block;padding:12px 18px;border-radius:12px;background:#126d83;color:white;text-decoration:none;font-weight:700'>Entrar novamente</a></p></main></body></html>""",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/onboarding/logout")
    async def onboarding_logout(request: Request):
        token = request.cookies.get(COOKIE_NAME, "")
        identity = web_sessions.resolve(token)
        web_sessions.revoke(token)
        audit(request, "onboarding_logout", "success", tenant_id=identity.tenant_id if identity else None)
        response = JSONResponse({"ok": True, "login_url": "/login"})
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
    async def youtube_connect(request: Request, tenant: AuthenticatedTenant = Depends(write_tenant)) -> dict:
        result = onboarding.start_youtube_connection(tenant.tenant_id)
        audit(request, "youtube_connect_started", "success", tenant_id=tenant.tenant_id)
        return {"authorization_url": result["authorization_url"], "expires_in_seconds": result["expires_in_seconds"]}

    @app.get("/oauth/google/callback")
    async def google_callback(request: Request, state: str = Query(min_length=20)):
        authorization_response = str(request.url)
        result = onboarding.complete_youtube_connection(state=state, authorization_response=authorization_response)
        audit(request, "youtube_connect_completed", "success", tenant_id=result.get("tenant_id"))
        success_url = os.environ.get("YCA_ONBOARDING_SUCCESS_URL", "").strip()
        if success_url:
            separator = "&" if "?" in success_url else "?"
            return RedirectResponse(f"{success_url}{separator}youtube=connected", status_code=302)
        if request.cookies.get(COOKIE_NAME):
            return RedirectResponse("/dashboard", status_code=303)
        return {"ok": True, "youtube_connected": result["youtube_connected"], "next_step": result["next_step"]}

    @app.delete("/api/youtube/connect")
    async def youtube_disconnect(request: Request, tenant: AuthenticatedTenant = Depends(write_tenant)) -> dict:
        result = onboarding.disconnect_youtube(tenant.tenant_id)
        audit(request, "youtube_disconnect", "success", tenant_id=tenant.tenant_id)
        return result

    @app.post("/api/ai/test")
    async def ai_test(payload: AIProbeRequest, tenant: AuthenticatedTenant = Depends(write_tenant)) -> dict:
        return onboarding.test_ai_connection(tenant.tenant_id, provider=payload.provider, api_key=payload.api_key, base_url=payload.base_url)

    @app.post("/api/ai/models")
    async def ai_models(payload: AIProbeRequest, tenant: AuthenticatedTenant = Depends(write_tenant)) -> dict:
        models = onboarding.list_ai_models(tenant.tenant_id, provider=payload.provider, api_key=payload.api_key, base_url=payload.base_url)
        return {"models": models}

    @app.put("/api/ai/config")
    async def ai_config(request: Request, payload: AIConfigRequest, tenant: AuthenticatedTenant = Depends(write_tenant)) -> dict:
        result = onboarding.configure_ai(
            tenant.tenant_id,
            provider=payload.provider,
            model=payload.model,
            api_key=payload.api_key,
            base_url=payload.base_url,
            validate_connection=payload.validate_connection,
        )
        audit(request, "external_ai_configured", "success", tenant_id=tenant.tenant_id, metadata={"provider": payload.provider, "model": payload.model})
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


def urllib_quote(value: str) -> str:
    from urllib.parse import quote_plus

    return quote_plus(value[:300])
