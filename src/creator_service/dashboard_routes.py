from __future__ import annotations

import json
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from googleapiclient.http import MediaFileUpload
from pydantic import BaseModel, Field

from .dashboard_ai import (
    channel_identity,
    grounded_seo_plan,
    grounded_playlist_plan,
    list_live_broadcasts,
    list_playlists,
    youtube_transcript,
)
from .dashboard_store import DashboardActionStore
from .safe_service import SafeCreatorService
from .security import signer_from_env
from .upload_safety import (
    UploadCapacityError,
    UploadSafetyPolicy,
    ensure_capacity,
    ensure_chunk_headroom,
    purge_expired_sessions,
)


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
THUMB_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 64 * 1024 * 1024 * 1024
MAX_THUMB_BYTES = 10 * 1024 * 1024
UPLOAD_SAFETY = UploadSafetyPolicy()
UPLOAD_SESSION_TTL_SECONDS = UPLOAD_SAFETY.ttl_seconds


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


class TopicResearchRequest(BaseModel):
    seed: str = Field(min_length=2, max_length=250)
    candidate_limit: int = Field(default=8, ge=3, le=12)


class AIOptimizeRequest(BaseModel):
    user_context: str = Field(default="", max_length=4000)
    max_age_days: int = Field(default=30, ge=1, le=180)


class UploadAIPlanRequest(BaseModel):
    video_name: str = Field(min_length=1, max_length=255)
    transcript: str = Field(default="", max_length=30000)
    user_context: str = Field(default="", max_length=4000)
    max_age_days: int = Field(default=30, ge=1, le=180)


class PlaylistAIRequest(BaseModel):
    user_context: str = Field(default="", max_length=4000)
    max_age_days: int = Field(default=30, ge=1, le=180)


class PlaylistCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=5000)
    privacy_status: str = Field(default="private", pattern="^(public|unlisted|private)$")


class PlaylistRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=5000)
    privacy_status: str = Field(default="private", pattern="^(public|unlisted|private)$")


class UploadStartRequest(BaseModel):
    video_name: str = Field(min_length=1, max_length=255)
    video_size: int = Field(gt=0, le=MAX_VIDEO_BYTES)
    thumbnail_name: str | None = Field(default=None, max_length=255)
    thumbnail_size: int = Field(default=0, ge=0, le=MAX_THUMB_BYTES)
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    format: str = Field(default="long", pattern="^(long|short)$")
    visibility: str = Field(default="public", pattern="^(public|unlisted|private|scheduled)$")
    publish_at: str | None = Field(default=None, max_length=80)
    category_id: str = Field(default="27", max_length=10)
    default_language: str = Field(default="pt-BR", max_length=20)


def _clean_tags(tags: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        value = " ".join(str(raw).strip().split())
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(value)
        if len(output) >= 12:
            break
    if sum(len(item) + 1 for item in output) > 500:
        raise ValueError("As tags ultrapassam o limite seguro de 500 caracteres.")
    return output


def _validate_schedule(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Informe data e hora para o agendamento.")
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("Data de agendamento inválida.") from exc
    if parsed.tzinfo is None:
        raise ValueError("O agendamento precisa incluir fuso horário.")
    if parsed.astimezone(timezone.utc).timestamp() <= time.time() + 60:
        raise ValueError("O agendamento precisa estar no futuro.")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def install_dashboard_routes(
    app: FastAPI,
    *,
    resolver,
    verifier,
    web_sessions,
    cookie_name: str,
    publication_store=None,
) -> None:
    db_path = getattr(resolver.db, "path", None)
    if db_path is None:
        db_path = Path(tempfile.gettempdir()) / f"yca-dashboard-{id(resolver)}.sqlite3"
    action_store = DashboardActionStore(db_path)

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

    def upload_root(tenant_id: str) -> Path:
        root = service_for(tenant_id).context.data_dir / "dashboard_uploads"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def session_dir(tenant_id: str, session_id: str) -> Path:
        if not session_id or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in session_id):
            raise HTTPException(status_code=400, detail="Sessão de upload inválida.")
        root = upload_root(tenant_id).resolve()
        candidate = (root / session_id).resolve()
        if root not in candidate.parents:
            raise HTTPException(status_code=400, detail="Sessão de upload inválida.")
        return candidate

    def manifest_path(tenant_id: str, session_id: str) -> Path:
        return session_dir(tenant_id, session_id) / "manifest.json"

    def load_manifest(tenant_id: str, session_id: str) -> dict[str, Any]:
        path = manifest_path(tenant_id, session_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Sessão de upload não encontrada ou expirada.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=409, detail="Manifesto de upload inválido.") from exc
        if data.get("tenant_id") != tenant_id:
            raise HTTPException(status_code=403, detail="Sessão de upload não pertence a esta conta.")
        if int(data.get("expires_at", 0)) < int(time.time()):
            shutil.rmtree(path.parent, ignore_errors=True)
            raise HTTPException(status_code=410, detail="Sessão de upload expirada.")
        return data

    def save_manifest(tenant_id: str, session_id: str, data: dict[str, Any]) -> None:
        path = manifest_path(tenant_id, session_id)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

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

    @app.get("/api/dashboard/capabilities")
    async def dashboard_capabilities(tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).chatgpt_capabilities()

    @app.get("/api/dashboard/channel")
    async def dashboard_channel(period_days: int = 28, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).channel_profile(period_days=max(7, min(90, period_days)))

    @app.get("/api/dashboard/channel/identity")
    async def dashboard_channel_identity(tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        return channel_identity(service._youtube())

    @app.get("/api/dashboard/playlists")
    async def dashboard_playlists(tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        return {"playlists": list_playlists(service._youtube())}

    @app.post("/api/dashboard/playlists")
    async def dashboard_playlist_create(payload: PlaylistCreateRequest, request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        response = service._youtube().playlists().insert(
            part="snippet,status",
            body={"snippet": {"title": payload.title.strip(), "description": payload.description.strip()}, "status": {"privacyStatus": payload.privacy_status}},
        ).execute()
        audit(request, "dashboard_playlist_created", "success", tenant.tenant_id, {"playlist_id": response.get("id")})
        return {"ok": True, "playlist": response}

    @app.put("/api/dashboard/playlists/{playlist_id}")
    async def dashboard_playlist_update(playlist_id: str, payload: PlaylistRenameRequest, request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        response = service._youtube().playlists().update(
            part="snippet,status",
            body={"id": playlist_id, "snippet": {"title": payload.title.strip(), "description": payload.description.strip()}, "status": {"privacyStatus": payload.privacy_status}},
        ).execute()
        audit(request, "dashboard_playlist_updated", "success", tenant.tenant_id, {"playlist_id": playlist_id})
        return {"ok": True, "playlist": response}

    @app.post("/api/dashboard/playlists/{playlist_id}/ai-optimize")
    async def dashboard_playlist_ai_optimize(playlist_id: str, payload: PlaylistAIRequest, request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        yt = service._youtube()
        found = yt.playlists().list(part="snippet,status,contentDetails", id=playlist_id, maxResults=1).execute().get("items", [])
        if not found:
            raise HTTPException(status_code=404, detail="Playlist não encontrada.")
        item = found[0]
        snippet = item.get("snippet", {})
        current = {"id": playlist_id, "title": str(snippet.get("title", "")), "description": str(snippet.get("description", "")), "privacy_status": item.get("status", {}).get("privacyStatus", "private")}
        rows = yt.playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=50).execute().get("items", [])
        video_titles = [str(r.get("snippet", {}).get("title", "")) for r in rows if str(r.get("snippet", {}).get("title", "")).strip()]
        try:
            plan = grounded_playlist_plan(service, playlist=current, video_titles=video_titles, user_context=payload.user_context, max_age_days=payload.max_age_days)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        package = {"playlist_id": playlist_id, "baseline_digest": signer_from_env().payload_digest(current), "current": current, "plan": plan}
        token = signer_from_env().issue("ai_optimize_playlist", playlist_id, package)
        action_id = action_store.put(tenant_id=tenant.tenant_id, kind="ai_optimize_playlist", payload=package, secret_token=token, ttl_seconds=900)
        audit(request, "dashboard_playlist_ai_preview", "success", tenant.tenant_id, {"playlist_id": playlist_id})
        return {"action_id": action_id, "current": current, "plan": plan, "requires_explicit_user_confirmation": True, "expires_in_seconds": 900}

    @app.post("/api/dashboard/playlists/ai-optimize/apply/{action_id}")
    async def dashboard_playlist_ai_apply(action_id: str, payload: ConfirmRequest, request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        if payload.confirmed is not True:
            raise HTTPException(status_code=400, detail="Confirmação explícita obrigatória.")
        try:
            action = action_store.consume(action_id=action_id, tenant_id=tenant.tenant_id, kind="ai_optimize_playlist")
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        package = dict(action.payload or {})
        playlist_id = str(package.get("playlist_id", "")).strip()
        signer_from_env().verify(action.secret_token, action="ai_optimize_playlist", subject=playlist_id, payload=package)
        service = service_for(tenant.tenant_id)
        yt = service._youtube()
        found = yt.playlists().list(part="snippet,status", id=playlist_id, maxResults=1).execute().get("items", [])
        if not found:
            raise HTTPException(status_code=404, detail="Playlist não encontrada.")
        item = found[0]
        snippet = item.get("snippet", {})
        current = {"id": playlist_id, "title": str(snippet.get("title", "")), "description": str(snippet.get("description", "")), "privacy_status": item.get("status", {}).get("privacyStatus", "private")}
        if signer_from_env().payload_digest(current) != str(package.get("baseline_digest", "")):
            raise HTTPException(status_code=409, detail="A playlist mudou desde a análise. Gere uma nova prévia.")
        plan = dict(package.get("plan", {}) or {})
        response = yt.playlists().update(part="snippet,status", body={"id": playlist_id, "snippet": {"title": str(plan.get("title", current["title"]))[:150], "description": str(plan.get("description", current["description"]))[:5000]}, "status": {"privacyStatus": current["privacy_status"]}}).execute()
        audit(request, "dashboard_playlist_ai_applied", "success", tenant.tenant_id, {"playlist_id": playlist_id})
        return {"ok": True, "playlist": response}

    @app.get("/api/dashboard/live")
    async def dashboard_live(tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        return {"broadcasts": list_live_broadcasts(service._youtube())}

    @app.post("/api/dashboard/video/{video_id}/ai-optimize")
    async def dashboard_video_ai_optimize(video_id: str, payload: AIOptimizeRequest, request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        service.memory.assert_not_recently_edited(video_id)
        current = service._current_video_snippet(video_id)
        transcript = youtube_transcript(service._youtube(), video_id)
        source = transcript.get("text", "") or current.get("description", "") or current.get("title", "")
        playlists = list_playlists(service._youtube())
        try:
            plan = grounded_seo_plan(
                service, source_text=source, original_title=current.get("title", ""),
                user_context=payload.user_context, max_age_days=payload.max_age_days, playlists=playlists,
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        package = {"video_id": video_id, "baseline_digest": signer_from_env().payload_digest(current), "current": current, "plan": plan}
        token = signer_from_env().issue("ai_optimize_video", video_id, package)
        action_id = action_store.put(tenant_id=tenant.tenant_id, kind="ai_optimize_video", payload=package, secret_token=token, ttl_seconds=900)
        audit(request, "dashboard_ai_optimization_preview", "success", tenant.tenant_id, {"video_id": video_id})
        return {"action_id": action_id, "video_id": video_id, "current": current, "plan": plan, "transcript": {k: v for k, v in transcript.items() if k != "text"}, "requires_explicit_user_confirmation": True, "expires_in_seconds": 900}

    @app.post("/api/dashboard/ai-optimize/apply/{action_id}")
    async def dashboard_video_ai_apply(action_id: str, payload: ConfirmRequest, request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        if payload.confirmed is not True:
            raise HTTPException(status_code=400, detail="Confirmação explícita obrigatória.")
        try:
            action = action_store.consume(action_id=action_id, tenant_id=tenant.tenant_id, kind="ai_optimize_video")
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        package = dict(action.payload or {})
        video_id = str(package.get("video_id", "")).strip()
        signer_from_env().verify(action.secret_token, action="ai_optimize_video", subject=video_id, payload=package)
        service = service_for(tenant.tenant_id)
        service.memory.assert_not_recently_edited(video_id)
        current = service._current_video_snippet(video_id)
        if signer_from_env().payload_digest(current) != str(package.get("baseline_digest", "")):
            raise HTTPException(status_code=409, detail="O vídeo mudou desde a análise. Gere uma nova otimização.")
        plan = dict(package.get("plan", {}) or {})
        tags = _clean_tags(list(plan.get("tags", []) or []))
        snippet = {
            "title": str(plan.get("title", current["title"]))[:100],
            "description": str(plan.get("description", current["description"]))[:5000],
            "tags": tags,
            "categoryId": str(plan.get("category_id") or current.get("categoryId") or "22"),
        }
        language = str(plan.get("language") or current.get("defaultLanguage") or "").strip()
        if language:
            snippet["defaultLanguage"] = language
        response = service._youtube().videos().update(part="snippet", body={"id": video_id, "snippet": snippet}).execute()
        playlist_id = str(plan.get("playlist_id", "")).strip()
        playlist_added = False
        if playlist_id:
            try:
                service._youtube().playlistItems().insert(
                    part="snippet", body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
                ).execute()
                playlist_added = True
            except Exception:
                playlist_added = False
        service.memory.record_video_action(video_id=video_id, action_type="ai_metadata_update", surface="dashboard_web", changed_fields=["title", "description", "tags", "categoryId"], before=current, after=snippet, details={"tenant_id": tenant.tenant_id, "playlist_id": playlist_id})
        audit(request, "dashboard_ai_optimization_applied", "success", tenant.tenant_id, {"video_id": video_id})
        return {"ok": True, "video_id": video_id, "title": response.get("snippet", {}).get("title", snippet["title"]), "playlist_added": playlist_added}

    @app.post("/api/dashboard/upload/ai-plan")
    async def dashboard_upload_ai_plan(payload: UploadAIPlanRequest, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        try:
            plan = grounded_seo_plan(
                service, source_text=payload.transcript, original_title=payload.video_name, user_context=payload.user_context,
                max_age_days=payload.max_age_days, playlists=list_playlists(service._youtube()),
            )
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"plan": plan, "requires_review": True}

    @app.get("/api/dashboard/videos")
    async def dashboard_videos(limit: int = 20, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        youtube = service._youtube()
        channel_result = youtube.channels().list(part="contentDetails", mine=True).execute()
        items = channel_result.get("items", [])
        if not items:
            return {"videos": []}
        uploads = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads:
            return {"videos": []}
        playlist = youtube.playlistItems().list(
            part="contentDetails,snippet",
            playlistId=uploads,
            maxResults=max(1, min(50, int(limit))),
        ).execute()
        ordered_ids = [str(item.get("contentDetails", {}).get("videoId", "")) for item in playlist.get("items", [])]
        ordered_ids = [video_id for video_id in ordered_ids if video_id]
        if not ordered_ids:
            return {"videos": []}
        details = youtube.videos().list(
            part="snippet,statistics,status",
            id=",".join(ordered_ids),
        ).execute()
        by_id = {str(item.get("id")): item for item in details.get("items", [])}
        output: list[dict[str, Any]] = []
        for video_id in ordered_ids:
            item = by_id.get(video_id)
            if not item:
                continue
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            thumbs = snippet.get("thumbnails", {})
            thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
            output.append({
                "id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "tags": list(snippet.get("tags", []) or []),
                "published_at": snippet.get("publishedAt"),
                "thumbnail": thumb,
                "privacy_status": item.get("status", {}).get("privacyStatus"),
                "views": int(stats.get("viewCount", 0) or 0),
                "likes": int(stats.get("likeCount", 0) or 0),
                "comments": int(stats.get("commentCount", 0) or 0),
                "memory": service.video_memory_state(video_id),
            })
        return {"videos": output}

    @app.get("/api/dashboard/video/{video_id}")
    async def dashboard_video(video_id: str, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        response = service._youtube().videos().list(part="snippet,statistics,status", id=video_id).execute()
        items = response.get("items", [])
        if not items:
            raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
        item = items[0]
        return {
            "id": video_id,
            "snippet": item.get("snippet", {}),
            "statistics": item.get("statistics", {}),
            "status": item.get("status", {}),
            "memory": service.video_memory_state(video_id),
            "recent_actions": service.memory.recent_actions(video_id, limit=20),
        }

    @app.get("/api/dashboard/evidence")
    async def dashboard_evidence(period_days: int = 28, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).strategy_evidence(period_days=max(7, min(90, period_days)))

    @app.get("/api/dashboard/audit")
    async def dashboard_audit(period_days: int = 28, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        service = service_for(tenant.tenant_id)
        days = max(7, min(90, int(period_days)))
        return {
            "period_days": days,
            "channel": service.channel_profile(period_days=days),
            "evidence": service.strategy_evidence(period_days=days),
        }

    @app.post("/api/dashboard/keywords/validate")
    async def dashboard_keywords(payload: KeywordRequest, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return service_for(tenant.tenant_id).validate_keyword_candidates(
            payload.keywords,
            period_days=payload.period_days,
            max_results=payload.max_results,
        )

    @app.post("/api/dashboard/research/topic")
    async def dashboard_research_topic(payload: TopicResearchRequest, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        try:
            return service_for(tenant.tenant_id).research_topic(payload.seed, candidate_limit=payload.candidate_limit)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/dashboard/strategy/build")
    async def dashboard_build_strategy(tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        try:
            return service_for(tenant.tenant_id).build_channel_strategy()
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/dashboard/actions/{video_id}")
    async def dashboard_actions(video_id: str, tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return {"actions": service_for(tenant.tenant_id).memory.recent_actions(video_id, limit=50)}

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

    @app.post("/api/dashboard/upload/start")
    async def dashboard_upload_start(
        request: Request,
        payload: UploadStartRequest,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        service_for(tenant.tenant_id).context.validate_youtube()
        root = upload_root(tenant.tenant_id)
        try:
            purge_expired_sessions(root, policy=UPLOAD_SAFETY)
            ensure_capacity(
                root,
                int(payload.video_size) + int(payload.thumbnail_size),
                policy=UPLOAD_SAFETY,
            )
        except UploadCapacityError as exc:
            audit(request, "dashboard_upload_rejected_capacity", "denied", tenant.tenant_id, {"reason": str(exc)})
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        video_suffix = Path(payload.video_name).suffix.lower()
        if video_suffix not in VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Formato de vídeo não suportado.")
        thumb_suffix = ""
        if payload.thumbnail_name:
            thumb_suffix = Path(payload.thumbnail_name).suffix.lower()
            if thumb_suffix not in THUMB_EXTENSIONS:
                raise HTTPException(status_code=400, detail="Formato de miniatura não suportado.")
            if payload.thumbnail_size <= 0:
                raise HTTPException(status_code=400, detail="Tamanho da miniatura inválido.")
        elif payload.thumbnail_size:
            raise HTTPException(status_code=400, detail="Nome da miniatura ausente.")
        try:
            tags = _clean_tags(payload.tags)
            publish_at = _validate_schedule(payload.publish_at) if payload.visibility == "scheduled" else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        session_id = secrets.token_urlsafe(24)
        directory = session_dir(tenant.tenant_id, session_id)
        directory.mkdir(parents=True, exist_ok=False)
        manifest = {
            "tenant_id": tenant.tenant_id,
            "session_id": session_id,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + UPLOAD_SESSION_TTL_SECONDS,
            "video": {"name": payload.video_name, "size": payload.video_size, "suffix": video_suffix, "received": 0, "next_index": 0},
            "thumbnail": {"name": payload.thumbnail_name, "size": payload.thumbnail_size, "suffix": thumb_suffix, "received": 0, "next_index": 0},
            "metadata": {
                "title": payload.title.strip(),
                "description": payload.description.strip(),
                "tags": tags,
                "format": payload.format,
                "visibility": payload.visibility,
                "publish_at": publish_at,
                "category_id": payload.category_id,
                "default_language": payload.default_language,
            },
        }
        save_manifest(tenant.tenant_id, session_id, manifest)
        audit(request, "dashboard_upload_started", "success", tenant.tenant_id, {"session_id": session_id})
        return {"session_id": session_id, "chunk_size": UPLOAD_CHUNK_BYTES, "expires_in_seconds": UPLOAD_SESSION_TTL_SECONDS}

    @app.post("/api/dashboard/upload/chunk/{session_id}")
    async def dashboard_upload_chunk(
        session_id: str,
        request: Request,
        kind: str,
        index: int,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        if kind not in {"video", "thumbnail"}:
            raise HTTPException(status_code=400, detail="Tipo de arquivo inválido.")
        manifest = load_manifest(tenant.tenant_id, session_id)
        item = manifest[kind]
        expected = int(item.get("next_index", 0))
        if index != expected:
            raise HTTPException(status_code=409, detail=f"Chunk fora de ordem. Esperado: {expected}.")
        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="Chunk vazio.")
        if len(body) > UPLOAD_CHUNK_BYTES:
            raise HTTPException(status_code=413, detail="Chunk excede o limite permitido.")
        try:
            ensure_chunk_headroom(upload_root(tenant.tenant_id), len(body), policy=UPLOAD_SAFETY)
        except UploadCapacityError as exc:
            audit(request, "dashboard_upload_paused_capacity", "denied", tenant.tenant_id, {"session_id": session_id})
            raise HTTPException(status_code=507, detail=str(exc)) from exc
        declared = int(item.get("size", 0))
        received = int(item.get("received", 0))
        if received + len(body) > declared:
            raise HTTPException(status_code=413, detail="Dados recebidos excedem o tamanho declarado.")
        target = session_dir(tenant.tenant_id, session_id) / f"{kind}{item.get('suffix', '')}"
        with target.open("ab") as handle:
            handle.write(body)
        item["received"] = received + len(body)
        item["next_index"] = expected + 1
        save_manifest(tenant.tenant_id, session_id, manifest)
        return {"ok": True, "kind": kind, "received": item["received"], "total": declared, "next_index": item["next_index"]}

    @app.post("/api/dashboard/upload/finish/{session_id}")
    async def dashboard_upload_finish(
        session_id: str,
        request: Request,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        manifest = load_manifest(tenant.tenant_id, session_id)
        for kind in ("video", "thumbnail"):
            item = manifest[kind]
            declared = int(item.get("size", 0))
            if declared and int(item.get("received", 0)) != declared:
                raise HTTPException(status_code=409, detail=f"Upload de {kind} incompleto.")
        directory = session_dir(tenant.tenant_id, session_id)
        video_path = directory / f"video{manifest['video'].get('suffix', '')}"
        thumb_path = None
        if int(manifest["thumbnail"].get("size", 0)):
            thumb_path = directory / f"thumbnail{manifest['thumbnail'].get('suffix', '')}"
        if not video_path.exists():
            raise HTTPException(status_code=409, detail="Arquivo de vídeo não encontrado após o upload.")
        package = {
            "session_id": session_id,
            "video_path": str(video_path),
            "thumbnail_path": str(thumb_path) if thumb_path else None,
            "metadata": manifest["metadata"],
            "video_size": manifest["video"]["size"],
            "thumbnail_size": manifest["thumbnail"]["size"],
        }
        signer = signer_from_env()
        signed = signer.issue("publish_video", tenant.tenant_id, package)
        action_id = action_store.put(
            tenant_id=tenant.tenant_id,
            kind="publish_video",
            payload=package,
            secret_token=signed,
            ttl_seconds=900,
        )
        manifest["ready_action_id"] = action_id
        save_manifest(tenant.tenant_id, session_id, manifest)
        audit(request, "dashboard_upload_ready", "success", tenant.tenant_id, {"session_id": session_id})
        return {
            "action_id": action_id,
            "session_id": session_id,
            "preview": {
                "title": manifest["metadata"]["title"],
                "format": manifest["metadata"]["format"],
                "visibility": manifest["metadata"]["visibility"],
                "publish_at": manifest["metadata"].get("publish_at"),
                "tags": manifest["metadata"]["tags"],
                "video_name": manifest["video"]["name"],
                "video_size": manifest["video"]["size"],
                "thumbnail_name": manifest["thumbnail"].get("name"),
            },
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
        }

    @app.delete("/api/dashboard/upload/{session_id}")
    async def dashboard_upload_cancel(
        session_id: str,
        request: Request,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        directory = session_dir(tenant.tenant_id, session_id)
        manifest = load_manifest(tenant.tenant_id, session_id)
        shutil.rmtree(directory, ignore_errors=True)
        audit(request, "dashboard_upload_cancelled", "success", tenant.tenant_id, {"session_id": manifest.get("session_id")})
        return {"ok": True}

    @app.post("/api/dashboard/upload/apply/{action_id}")
    async def dashboard_upload_apply(
        action_id: str,
        payload: ConfirmRequest,
        request: Request,
        tenant: DashboardTenant = Depends(writable),
    ) -> dict[str, Any]:
        if payload.confirmed is not True:
            raise HTTPException(status_code=400, detail="Confirmação explícita obrigatória para publicar.")
        try:
            action = action_store.consume(action_id=action_id, tenant_id=tenant.tenant_id, kind="publish_video")
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        signer_from_env().verify(
            action.secret_token,
            action="publish_video",
            subject=tenant.tenant_id,
            payload=action.payload,
        )
        service = service_for(tenant.tenant_id)
        service.context.validate_youtube()
        root = upload_root(tenant.tenant_id).resolve()
        video_path = Path(str(action.payload.get("video_path", ""))).resolve()
        thumb_raw = action.payload.get("thumbnail_path")
        thumb_path = Path(str(thumb_raw)).resolve() if thumb_raw else None
        if root not in video_path.parents or not video_path.exists():
            raise HTTPException(status_code=409, detail="Arquivo temporário do vídeo inválido ou ausente.")
        if thumb_path and (root not in thumb_path.parents or not thumb_path.exists()):
            raise HTTPException(status_code=409, detail="Arquivo temporário da miniatura inválido ou ausente.")
        metadata = dict(action.payload.get("metadata", {}) or {})
        title = str(metadata.get("title", "")).strip()
        description = str(metadata.get("description", ""))
        tags = _clean_tags(list(metadata.get("tags", []) or []))
        if metadata.get("format") == "short":
            if "#shorts" not in title.lower():
                title = (title + " #shorts")[:100]
            if "#shorts" not in description.lower():
                description = (description + "\n\n#shorts").strip()
        visibility = str(metadata.get("visibility", "public"))
        status_body: dict[str, Any] = {"selfDeclaredMadeForKids": False}
        if visibility == "scheduled":
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = _validate_schedule(metadata.get("publish_at"))
        else:
            status_body["privacyStatus"] = visibility if visibility in {"public", "unlisted", "private"} else "private"
        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags,
                "categoryId": str(metadata.get("category_id", "27")),
                "defaultLanguage": str(metadata.get("default_language", "pt-BR")),
            },
            "status": status_body,
        }
        youtube = service._youtube()
        try:
            media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/*")
            request_upload = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = None
            while response is None:
                _, response = request_upload.next_chunk()
            video_id = str(response.get("id", ""))
            if not video_id:
                raise RuntimeError("O YouTube não retornou o ID do vídeo publicado.")
            thumbnail_applied = False
            if thumb_path and metadata.get("format") != "short":
                youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb_path))).execute()
                thumbnail_applied = True
            service.memory.record_video_action(
                video_id=video_id,
                action_type="publish",
                surface="dashboard_web",
                changed_fields=["title", "description", "tags"],
                before={},
                after=body["snippet"],
                details={"visibility": visibility, "format": metadata.get("format")},
            )
            audit(request, "dashboard_video_published", "success", tenant.tenant_id, {"video_id": video_id})
            return {
                "ok": True,
                "video_id": video_id,
                "title": title,
                "privacy_status": status_body["privacyStatus"],
                "publish_at": status_body.get("publishAt"),
                "thumbnail_applied": thumbnail_applied,
            }
        finally:
            session_id = str(action.payload.get("session_id", ""))
            if session_id:
                shutil.rmtree(session_dir(tenant.tenant_id, session_id), ignore_errors=True)
