from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from .dashboard_store import DashboardActionStore
from .safe_service import SafeCreatorService


@dataclass(frozen=True)
class DashboardTenant:
    tenant_id: str
    subject: str
    scopes: tuple[str, ...]


class MetadataPreviewRequest(BaseModel):
    video_id: str = Field(min_length=3, max_length=100)
    title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None


class ConfirmRequest(BaseModel):
    confirmed: bool


class KeywordRequest(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=20)
    period_days: int = Field(default=28, ge=7, le=90)
    max_results: int = Field(default=20, ge=1, le=25)


def install_dashboard_routes(
    app: FastAPI,
    *,
    resolver,
    verifier,
    web_sessions,
    cookie_name: str,
    publication_store=None,
) -> None:
    if getattr(resolver.db, "path", None) is None:
        raise RuntimeError("Dashboard requer armazenamento persistente do tenant registry.")
    action_store = DashboardActionStore(resolver.db.path)

    def service_for(tenant_id: str) -> SafeCreatorService:
        return SafeCreatorService(resolver.resolve(tenant_id))

    def enforce_limit(key: str, *, limit: int, window_seconds: int = 60) -> None:
        if publication_store is None:
            return
        decision = publication_store.consume_rate_limit(key, limit=limit, window_seconds=window_seconds)
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Muitas solicitações. Aguarde e tente novamente.",
                headers={"Retry-After": str(decision.reset_after_seconds)},
            )

    def audit(request: Request, event_type: str, outcome: str, tenant_id: str | None = None, metadata: dict | None = None) -> None:
        if publication_store is None:
            return
        publication_store.record_event(
            event_type=event_type,
            outcome=outcome,
            tenant_id=tenant_id,
            request_id=getattr(request.state, "request_id", None),
            metadata=metadata,
        )

    async def authenticated(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> DashboardTenant:
        if authorization and authorization.startswith("Bearer "):
            access = await verifier.verify_token(authorization[7:].strip())
            if access is None:
                raise HTTPException(status_code=401, detail="Token inválido ou expirado.")
            tenant_id = str((access.claims or {}).get("tenant_id", "")).strip()
            if not tenant_id:
                raise HTTPException(status_code=403, detail="Token sem tenant associado.")
            resolver.db.ensure_tenant(tenant_id)
            return DashboardTenant(tenant_id, str(access.subject or ""), tuple(access.scopes or ()))

        identity = web_sessions.resolve(request.cookies.get(cookie_name, ""))
        if identity is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sessão não autenticada ou expirada.",
            )
        return DashboardTenant(identity.tenant_id, "dashboard_web_session", tuple(identity.scopes))

    async def readable(tenant: DashboardTenant = Depends(authenticated)) -> DashboardTenant:
        if "yca:read" not in tenant.scopes:
            raise HTTPException(status_code=403, detail="Escopo obrigatório ausente: yca:read")
        enforce_limit(f"dashboard:read:{tenant.tenant_id}", limit=180)
        return tenant

    async def writable(tenant: DashboardTenant = Depends(authenticated)) -> DashboardTenant:
        if "yca:write" not in tenant.scopes:
            raise HTTPException(status_code=403, detail="Escopo obrigatório ausente: yca:write")
        enforce_limit(f"dashboard:write:{tenant.tenant_id}", limit=30)
        return tenant

    @app.get("/dashboard", response_class=FileResponse)
    async def dashboard_page(request: Request):
        identity = web_sessions.resolve(request.cookies.get(cookie_name, ""))
        if identity is None:
            return RedirectResponse("/onboarding/session-expired", status_code=303)
        page = Path(__file__).resolve().parent / "web" / "dashboard.html"
        return FileResponse(page, media_type="text/html", headers={"Cache-Control": "no-store"})

    @app.get("/api/dashboard/status")
    async def dashboard_status(tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        result = service_for(tenant.tenant_id).status()
        result.pop("tenant_id", None)
        return result

    @app.get("/api/dashboard/channel")
    async def dashboard_channel(period_days: int = 28, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).channel_profile(period_days=max(7, min(90, period_days)))

    @app.get("/api/dashboard/evidence")
    async def dashboard_evidence(period_days: int = 28, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).strategy_evidence(period_days=max(7, min(90, period_days)))

    @app.post("/api/dashboard/keywords/validate")
    async def dashboard_keywords(payload: KeywordRequest, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).validate_keyword_candidates(
            payload.keywords,
            period_days=payload.period_days,
            max_results=payload.max_results,
        )

    @app.post("/api/dashboard/metadata/preview")
    async def dashboard_metadata_preview(
        request: Request,
        payload: MetadataPreviewRequest,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        result = service_for(tenant.tenant_id).preview_video_metadata_update(
            video_id=payload.video_id,
            title=payload.title,
            description=payload.description,
            tags=payload.tags,
        )
        action_id = action_store.put(
            tenant_id=tenant.tenant_id,
            kind="metadata_update",
            payload=result["approval_payload"],
            secret_token=result["approval_token"],
            ttl_seconds=int(result.get("expires_in_seconds", 900)),
        )
        audit(request, "dashboard_metadata_preview", "success", tenant.tenant_id, {"video_id": payload.video_id})
        return {
            "action_id": action_id,
            "video_id": result["video_id"],
            "current": result["current"],
            "proposed": result["proposed"],
            "changed": result["changed"],
            "expires_in_seconds": int(result.get("expires_in_seconds", 900)),
            "requires_explicit_user_confirmation": True,
            "recent_edit_protection": result.get("recent_edit_protection"),
        }

    @app.post("/api/dashboard/metadata/apply/{action_id}")
    async def dashboard_metadata_apply(
        action_id: str,
        payload: ConfirmRequest,
        request: Request,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        if payload.confirmed is not True:
            audit(request, "dashboard_metadata_apply", "denied", tenant.tenant_id, {"reason": "confirmation_missing"})
            raise HTTPException(status_code=400, detail="Confirmação explícita obrigatória.")
        try:
            action = action_store.consume(action_id=action_id, tenant_id=tenant.tenant_id, kind="metadata_update")
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        result = service_for(tenant.tenant_id).apply_video_metadata_update(
            approval_payload=action.payload,
            approval_token=action.secret_token,
        )
        rollback = dict(result.pop("rollback_preview", {}) or {})
        rollback_id = None
        rollback_public = None
        if rollback:
            rollback_id = action_store.put(
                tenant_id=tenant.tenant_id,
                kind="metadata_rollback",
                payload=rollback["rollback_payload"],
                secret_token=rollback["rollback_token"],
                ttl_seconds=int(rollback.get("expires_in_seconds", 900)),
            )
            rollback_public = {
                "action_id": rollback_id,
                "current": rollback.get("current"),
                "restore": rollback.get("restore"),
                "expires_in_seconds": int(rollback.get("expires_in_seconds", 900)),
                "requires_explicit_user_confirmation": True,
            }
        audit(request, "dashboard_metadata_apply", "success", tenant.tenant_id, {"video_id": result.get("video_id")})
        result["rollback_preview"] = rollback_public
        return result

    @app.post("/api/dashboard/metadata/rollback/{action_id}")
    async def dashboard_metadata_rollback(
        action_id: str,
        payload: ConfirmRequest,
        request: Request,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        if payload.confirmed is not True:
            audit(request, "dashboard_metadata_rollback", "denied", tenant.tenant_id, {"reason": "confirmation_missing"})
            raise HTTPException(status_code=400, detail="Confirmação explícita obrigatória para rollback.")
        try:
            action = action_store.consume(action_id=action_id, tenant_id=tenant.tenant_id, kind="metadata_rollback")
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        result = service_for(tenant.tenant_id).apply_video_metadata_rollback(
            rollback_payload=action.payload,
            rollback_token=action.secret_token,
        )
        audit(request, "dashboard_metadata_rollback", "success", tenant.tenant_id, {"video_id": result.get("video_id")})
        return result
