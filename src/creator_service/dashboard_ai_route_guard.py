from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute


def _closure_values(fn) -> dict[str, Any]:
    values: dict[str, Any] = {}
    closure = getattr(fn, "__closure__", None) or ()
    for name, cell in zip(getattr(fn.__code__, "co_freevars", ()), closure):
        try:
            values[name] = cell.cell_contents
        except ValueError:
            pass
    return values


def _replace_call(app: FastAPI, path: str, replacement) -> None:
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.path == path:
            route.endpoint = replacement
            route.dependant.call = replacement
            return
    raise RuntimeError(f"Rota não encontrada para hardening: {path}")


def _safe_ai_error(exc: Exception) -> str:
    text = " ".join(str(exc or "").split())
    low = text.casefold()
    if "todas as chaves" in low and "desativ" in low:
        return "Nenhuma chave de IA está habilitada. Selecione uma ou mais chaves em Ajustes antes de analisar."
    if "nenhuma chave" in low or "credencial" in low:
        return "A chave de IA selecionada não está disponível. Revise as chaves habilitadas em Ajustes."
    if any(token in low for token in ("401", "403", "invalid api key", "api key invalid", "permission denied")):
        return "A chave de IA selecionada foi recusada pelo provedor. Desative-a ou teste outra chave em Ajustes."
    if any(token in low for token in ("429", "quota", "rate limit", "resource exhausted")):
        return "O provedor de IA atingiu limite ou cota. Com rotação ativa, a próxima chave habilitada será tentada automaticamente."
    if any(token in low for token in ("500", "502", "503", "504", "unavailable", "overloaded", "timeout", "timed out")):
        return "O provedor de IA ficou temporariamente indisponível. Se houver outras chaves selecionadas para rotação, elas serão tentadas automaticamente."
    if "nenhuma palavra-chave passou" in low:
        return text
    if "json" in low and "ia" in low:
        return "A IA respondeu em formato inválido. Nenhuma alteração foi feita; tente novamente ou use outro modelo habilitado."
    return text[:900] or "A análise não pôde ser concluída. Nenhuma alteração foi feita no YouTube."


def install_dashboard_ai_route_guard(app: FastAPI) -> None:
    from . import dashboard_routes
    from .security import signer_from_env

    video_route = next(
        route for route in app.router.routes
        if isinstance(route, APIRoute) and route.path == "/api/dashboard/video/{video_id}/ai-optimize"
    )
    video_original = video_route.endpoint
    video_ctx = _closure_values(video_original)
    service_for = video_ctx["service_for"]
    action_store = video_ctx["action_store"]
    audit_event = video_ctx["audit"]

    async def video_ai_optimize(video_id, payload, request, tenant):
        service = service_for(tenant.tenant_id)
        try:
            service.context.validate_youtube()
            # This is an explicit user-triggered AI preview. Passive dashboard reads
            # never enter this path and therefore never spend external AI quota.
            current = service._current_video_snippet(video_id)
            transcript = dashboard_routes.youtube_transcript(service._youtube(), video_id)
            transcript_text = str(transcript.get("text") or "").strip()
            if transcript_text:
                source = transcript_text
                source_kind = "youtube_transcript"
            elif str(current.get("description") or "").strip():
                source = str(current.get("description") or "")
                source_kind = "video_description_fallback"
            else:
                source = str(current.get("title") or "")
                source_kind = "video_title_fallback"
            playlists = dashboard_routes.list_playlists(service._youtube())
            plan = dashboard_routes.grounded_seo_plan(
                service,
                source_text=source,
                original_title=current.get("title", ""),
                user_context=payload.user_context,
                max_age_days=payload.max_age_days,
                playlists=playlists,
            )
            plan["content_source"] = source_kind
            plan["transcript_grounded"] = bool(transcript_text)
            plan["writes_performed"] = 0
            package = {
                "video_id": video_id,
                "baseline_digest": signer_from_env().payload_digest(current),
                "current": current,
                "plan": plan,
            }
            token = signer_from_env().issue("ai_optimize_video", video_id, package)
            action_id = action_store.put(
                tenant_id=tenant.tenant_id,
                kind="ai_optimize_video",
                payload=package,
                secret_token=token,
                ttl_seconds=900,
            )
            audit_event(request, "dashboard_ai_optimization_preview", "success", tenant.tenant_id, {"video_id": video_id})
            return {
                "action_id": action_id,
                "video_id": video_id,
                "current": current,
                "plan": plan,
                "transcript": {key: value for key, value in transcript.items() if key != "text"},
                "content_source": source_kind,
                "requires_explicit_user_confirmation": True,
                "expires_in_seconds": 900,
            }
        except HTTPException:
            raise
        except Exception as exc:
            audit_event(request, "dashboard_ai_optimization_preview", "failed", tenant.tenant_id, {"video_id": video_id, "error_type": type(exc).__name__})
            raise HTTPException(status_code=409, detail=_safe_ai_error(exc)) from exc

    _replace_call(app, "/api/dashboard/video/{video_id}/ai-optimize", video_ai_optimize)

    # Channel audit is a passive/read-only dashboard surface. It must stay 100%
    # deterministic and must never invoke Gemini/OpenAI/Groq/xAI merely because the
    # user opened or refreshed the dashboard. External AI remains available only on
    # explicit POST actions such as strategy build and AI optimization previews.
    audit_route = next(
        route for route in app.router.routes
        if isinstance(route, APIRoute) and route.path == "/api/dashboard/audit"
    )
    audit_original = audit_route.endpoint

    async def dashboard_audit(period_days=28, tenant=None):
        factual = await audit_original(period_days=period_days, tenant=tenant)
        return {
            **factual,
            "ai_advice": {
                "status": "not_requested",
                "grounded": True,
                "external_ai_used": False,
                "reason": "external_ai_requires_explicit_user_action",
                "no_invented_metrics": True,
                "writes_performed": 0,
            },
            "intelligence_mode": "native_first",
            "external_ai_used": False,
            "writes_performed": 0,
        }

    _replace_call(app, "/api/dashboard/audit", dashboard_audit)

    # Other AI previews are explicit POST actions. Keep them available, but convert
    # provider failures into readable 409 responses instead of opaque HTTP 500s.
    for path in (
        "/api/dashboard/playlists/{playlist_id}/ai-optimize",
        "/api/dashboard/upload/ai-plan",
        "/api/dashboard/strategy/build",
        "/api/dashboard/research/topic",
    ):
        route = next((item for item in app.router.routes if isinstance(item, APIRoute) and item.path == path), None)
        if route is None:
            continue
        original = route.endpoint

        async def guarded(*args, __original=original, **kwargs):
            try:
                return await __original(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=409, detail=_safe_ai_error(exc)) from exc

        route.endpoint = guarded
        route.dependant.call = guarded
