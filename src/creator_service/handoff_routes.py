from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .cloud_runtime import CloudTenantResolver
from .dashboard_store import DashboardActionStore
from .handoff import HandoffError, canonical_digest, open_handoff
from .handoff_store import HandoffExecutionStore
from .onboarding_api import COOKIE_NAME
from .onboarding_sessions import OnboardingSessionStore
from .publication_store import PublicationStore
from .responsible_service import ResponsibleCreatorService
from .security import signer_from_env


class HandoffApplyRequest(BaseModel):
    ticket: str = Field(min_length=32, max_length=120_000)


class ConfirmRequest(BaseModel):
    confirmed: bool


def _remove_route(app: FastAPI, path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in set(getattr(route, "methods", set()) or set())
        )
    ]


def _playlist_membership(service: ResponsibleCreatorService, playlist_id: str) -> list[dict[str, str]]:
    playlist_id = str(playlist_id or "").strip()
    if not playlist_id:
        return []
    response = service._youtube().playlists().list(
        part="snippet",
        id=playlist_id,
        maxResults=1,
    ).execute()
    items = response.get("items", [])
    if not items:
        raise HTTPException(status_code=409, detail="A playlist selecionada não existe mais.")
    owner = str((items[0].get("snippet", {}) or {}).get("channelId", "")).strip()
    if owner != service._authorized_channel_id():
        raise HTTPException(status_code=403, detail="A playlist não pertence ao canal autenticado.")

    rows: list[dict[str, str]] = []
    page_token = None
    while True:
        kwargs: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        page = service._youtube().playlistItems().list(**kwargs).execute()
        for item in page.get("items", []):
            snippet = item.get("snippet", {}) or {}
            details = item.get("contentDetails", {}) or {}
            rows.append(
                {
                    "playlist_item_id": str(item.get("id", "")),
                    "video_id": str(
                        details.get("videoId")
                        or (snippet.get("resourceId", {}) or {}).get("videoId")
                        or ""
                    ),
                }
            )
        page_token = page.get("nextPageToken")
        if not page_token:
            break
        if len(rows) >= 5000:
            raise HTTPException(status_code=409, detail="A playlist é grande demais para uma alteração atômica segura.")
    return rows


def _remove_playlist_item_verified(
    service: ResponsibleCreatorService,
    *,
    playlist_id: str,
    video_id: str,
    playlist_item_id: str,
) -> dict[str, Any]:
    """Delete only the exact playlist item we can prove belongs to this operation."""
    before = _playlist_membership(service, playlist_id)
    exact = [
        row
        for row in before
        if row["playlist_item_id"] == playlist_item_id and row["video_id"] == video_id
    ]
    if not exact:
        if any(row["playlist_item_id"] == playlist_item_id for row in before):
            raise RuntimeError("O item de playlist mudou de alvo; a remoção automática foi bloqueada.")
        return {
            "playlist_id": playlist_id,
            "video_id": video_id,
            "playlist_item_id": playlist_item_id,
            "already_absent": True,
            "persisted_verified": True,
        }

    provider_error: Exception | None = None
    try:
        service._youtube().playlistItems().delete(id=playlist_item_id).execute()
    except Exception as exc:
        provider_error = exc

    try:
        after = _playlist_membership(service, playlist_id)
    except Exception as read_error:
        raise RuntimeError(
            "A remoção do item de playlist foi enviada, mas a releitura falhou. "
            "A ferramenta não repetirá a exclusão às cegas."
        ) from provider_error or read_error

    still_exists = any(row["playlist_item_id"] == playlist_item_id for row in after)
    if still_exists:
        if provider_error is not None:
            raise provider_error
        raise RuntimeError("O YouTube não confirmou a remoção do item de playlist.")

    return {
        "playlist_id": playlist_id,
        "video_id": video_id,
        "playlist_item_id": playlist_item_id,
        "already_absent": False,
        "persisted_verified": True,
        "recovered_from_ambiguous_response": provider_error is not None,
    }


def _add_playlist_item_verified(
    service: ResponsibleCreatorService,
    *,
    playlist_id: str,
    video_id: str,
) -> dict[str, Any]:
    before = _playlist_membership(service, playlist_id)
    existing = [row for row in before if row["video_id"] == video_id]
    if existing:
        return {
            "playlist_id": playlist_id,
            "video_id": video_id,
            "already_present": True,
            "playlist_item_id": existing[0]["playlist_item_id"],
            "duplicate_count": len(existing),
            "persisted_verified": True,
        }

    response: dict[str, Any] = {}
    provider_error: Exception | None = None
    try:
        response = service._youtube().playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()
    except Exception as exc:
        provider_error = exc

    try:
        after = _playlist_membership(service, playlist_id)
    except Exception as read_error:
        service.memory.record_video_action(
            video_id=video_id,
            action_type="playlist_write_ambiguous_state",
            surface="responsible_creator_service",
            changed_fields=["playlist"],
            before={"playlist_id": playlist_id, "present": False},
            after={"playlist_id": playlist_id, "present": "unknown"},
            details={
                "tenant_id": service.context.tenant_id,
                "reason": "playlist_insert_readback_failed",
                "provider_error_type": type(provider_error).__name__ if provider_error else "",
                "read_error_type": type(read_error).__name__,
            },
        )
        raise RuntimeError(
            "A inclusão na playlist pode ter sido aceita, mas a releitura falhou. "
            "A ferramenta bloqueou qualquer nova tentativa automática para não duplicar o vídeo."
        ) from provider_error or read_error

    before_ids = {row["playlist_item_id"] for row in before}
    new_matches = [
        row
        for row in after
        if row["video_id"] == video_id and row["playlist_item_id"] not in before_ids
    ]
    all_matches = [row for row in after if row["video_id"] == video_id]
    returned_id = str((response or {}).get("id", "")).strip()

    if returned_id:
        returned_match = next(
            (row for row in new_matches if row["playlist_item_id"] == returned_id),
            None,
        )
        if returned_match is None:
            raise RuntimeError(
                "O YouTube retornou um item de playlist, mas a releitura não confirmou o mesmo ID. "
                "Nenhuma repetição automática será feita."
            )

        if len(all_matches) > 1:
            # A second actor may have inserted the same video between our baseline
            # read and our insert. Because YouTube returned our exact item ID, we
            # can safely remove only our copy and preserve the concurrent one.
            _remove_playlist_item_verified(
                service,
                playlist_id=playlist_id,
                video_id=video_id,
                playlist_item_id=returned_id,
            )
            remaining = [
                row for row in _playlist_membership(service, playlist_id)
                if row["video_id"] == video_id
            ]
            if not remaining:
                raise RuntimeError(
                    "Uma corrida concorrente foi detectada na playlist. Nossa cópia foi removida, "
                    "mas a outra inclusão também desapareceu; gere uma nova proposta."
                )
            return {
                "playlist_id": playlist_id,
                "video_id": video_id,
                "already_present": True,
                "playlist_item_id": remaining[0]["playlist_item_id"],
                "persisted_verified": True,
                "concurrent_duplicate_prevented": True,
            }
        item_id = returned_id
    elif len(new_matches) == 1 and len(all_matches) == 1:
        # Lost transport response, but the authoritative state has exactly one
        # new membership for the target video. Treat that state as success and
        # never retry the insert.
        item_id = new_matches[0]["playlist_item_id"]
    elif not new_matches and provider_error is not None:
        raise provider_error
    else:
        service.memory.record_video_action(
            video_id=video_id,
            action_type="playlist_write_ambiguous_state",
            surface="responsible_creator_service",
            changed_fields=["playlist"],
            before={"playlist_id": playlist_id, "present": False},
            after={"playlist_id": playlist_id, "matches": len(all_matches)},
            details={
                "tenant_id": service.context.tenant_id,
                "reason": "playlist_insert_ambiguous_membership",
            },
        )
        raise RuntimeError(
            "O estado da playlist ficou ambíguo após a tentativa de inclusão. "
            "A ferramenta bloqueou qualquer repetição automática para não duplicar o vídeo."
        ) from provider_error

    return {
        "playlist_id": playlist_id,
        "video_id": video_id,
        "already_present": False,
        "playlist_item_id": item_id,
        "persisted_verified": True,
        "recovered_from_ambiguous_response": provider_error is not None,
    }


def _normalize_ticket_proposal(
    service: ResponsibleCreatorService,
    *,
    video_id: str,
    proposed: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    normalized = service._normalize_metadata_payload(
        video_id=video_id,
        title=str(proposed.get("title", "")),
        description=str(proposed.get("description", "")),
        tags=list(proposed.get("tags", []) or []),
        current=current,
    )
    normalized["categoryId"] = service._normalize_category_id(proposed.get("categoryId"), current)
    normalized["defaultLanguage"] = current.get("defaultLanguage")
    return normalized


def _metadata_changed(service: ResponsibleCreatorService, current: dict[str, Any], proposed: dict[str, Any]) -> bool:
    return bool(service._mismatches(current, proposed))


def _apply_metadata_from_exact_baseline(
    service: ResponsibleCreatorService,
    *,
    video_id: str,
    baseline_digest: str,
    proposed: dict[str, Any],
) -> dict[str, Any]:
    payload = {"baseline_digest": baseline_digest, "proposed": proposed}
    token = signer_from_env().issue("update_video_metadata", video_id, payload)
    return service.apply_video_metadata_update(approval_payload=payload, approval_token=token)


def _rollback_metadata_after_secondary_failure(
    service: ResponsibleCreatorService,
    metadata_result: dict[str, Any] | None,
    original_error: Exception,
) -> None:
    if not metadata_result:
        raise original_error
    rollback = dict(metadata_result.get("rollback_preview", {}) or {})
    if not rollback:
        raise RuntimeError(
            "Uma ação secundária falhou depois da edição do vídeo e não havia pacote de rollback verificável."
        ) from original_error
    try:
        service.apply_video_metadata_rollback(
            rollback_payload=dict(rollback.get("rollback_payload", {}) or {}),
            rollback_token=str(rollback.get("rollback_token", "")),
        )
    except Exception as rollback_error:
        raise RuntimeError(
            "A ação secundária falhou após a edição do vídeo e o rollback automático também não pôde ser confirmado. "
            "A ferramenta bloqueou novas alterações para evitar sobrescrita adicional."
        ) from rollback_error
    raise RuntimeError(
        "A ação secundária falhou. A edição de metadados foi revertida automaticamente e a restauração foi verificada."
    ) from original_error


def _rollback_playlist_after_final_failure(
    service: ResponsibleCreatorService,
    playlist_result: dict[str, Any] | None,
    original_error: Exception,
) -> Exception:
    if not playlist_result or playlist_result.get("already_present"):
        return original_error
    item_id = str(playlist_result.get("playlist_item_id", "")).strip()
    playlist_id = str(playlist_result.get("playlist_id", "")).strip()
    video_id = str(playlist_result.get("video_id", "")).strip()
    if not item_id or not playlist_id or not video_id:
        return RuntimeError(
            "A verificação final falhou após uma inclusão de playlist sem identificadores suficientes para rollback seguro."
        )
    try:
        _remove_playlist_item_verified(
            service,
            playlist_id=playlist_id,
            video_id=video_id,
            playlist_item_id=item_id,
        )
    except Exception as rollback_error:
        return RuntimeError(
            "A verificação final falhou e a remoção compensatória do item de playlist também não pôde ser confirmada. "
            "Nenhuma nova tentativa automática será feita."
        )
    return RuntimeError(
        f"{original_error} A inclusão de playlist criada por esta operação foi removida e verificada."
    )


def install_handoff_routes(app: FastAPI) -> None:
    """Install YCA HandOff V1 and replace the weaker dashboard AI apply route."""

    resolver = CloudTenantResolver()
    web_sessions = OnboardingSessionStore(resolver.db)
    db_path = getattr(resolver.db, "path", None)
    if db_path is None:
        raise RuntimeError("YCA HandOff exige armazenamento persistente do tenant.")
    publication_store = PublicationStore(db_path)
    execution_store = HandoffExecutionStore(db_path)
    action_store = DashboardActionStore(db_path)
    public_origin = os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")

    def service_for(tenant_id: str) -> ResponsibleCreatorService:
        return ResponsibleCreatorService(resolver.resolve(tenant_id))

    def browser_identity(request: Request):
        identity = web_sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
        if identity is None:
            raise HTTPException(status_code=401, detail="Sessão web não autenticada ou expirada.")
        if "yca:write" not in set(identity.scopes or ()):
            raise HTTPException(status_code=403, detail="Esta sessão web não possui permissão de escrita.")
        return identity

    def require_same_origin(request: Request) -> None:
        if not public_origin:
            raise HTTPException(status_code=503, detail="Origem pública do handoff não configurada.")
        origin = str(request.headers.get("origin", "")).strip().rstrip("/")
        if origin != public_origin:
            raise HTTPException(status_code=403, detail="Origem da solicitação de handoff não autorizada.")

    def audit(event_type: str, outcome: str, tenant_id: str | None, metadata: dict[str, Any] | None = None) -> None:
        publication_store.record_event(
            event_type=event_type,
            outcome=outcome,
            tenant_id=tenant_id,
            metadata=metadata or {},
        )

    def reconcile_interrupted_handoff(
        *,
        ticket: str,
        package,
        service: ResponsibleCreatorService,
    ) -> dict[str, Any]:
        current = service._current_video_snippet(package.video_id)
        playlist_result = None
        playlist_ok = True
        if package.playlist_id:
            membership = _playlist_membership(service, package.playlist_id)
            matches = [row for row in membership if row["video_id"] == package.video_id]
            playlist_ok = bool(matches)
            if matches:
                playlist_result = {
                    "playlist_id": package.playlist_id,
                    "video_id": package.video_id,
                    "playlist_item_id": matches[0]["playlist_item_id"],
                    "already_present": True,
                    "persisted_verified": True,
                    "recovered_from_interrupted_response": True,
                }

        metadata_ok = not service._mismatches(current, package.proposed)
        baseline_unchanged = signer_from_env().payload_digest(current) == package.baseline_digest

        if metadata_ok and playlist_ok:
            result = {
                "ok": True,
                "video_id": package.video_id,
                "channel_id": package.channel_id,
                "changed_fields": list(package.changed_fields),
                "persisted_verified": True,
                "current": current,
                "playlist": playlist_result,
                "rollback_available": False,
                "recovered_from_interrupted_response": True,
            }
            execution_store.mark_success(ticket, result)
            audit("handoff_reconciled", "success", package.tenant_id, {"video_id": package.video_id})
            return result

        if baseline_unchanged:
            if "playlist" in set(package.changed_fields) and playlist_ok:
                message = (
                    "Uma execução anterior foi interrompida após uma possível inclusão de playlist, "
                    "mas antes de concluir os metadados. O ticket foi encerrado sem repetir nenhuma gravação."
                )
            else:
                message = (
                    "Uma execução anterior foi interrompida sem uma alteração de metadados verificável. "
                    "O ticket foi encerrado por segurança; gere uma nova proposta."
                )
            execution_store.mark_failed(ticket, message)
            audit("handoff_reconciled", "failed_safe", package.tenant_id, {"video_id": package.video_id, "baseline_unchanged": True})
            raise HTTPException(status_code=409, detail=message)

        message = (
            "Uma execução anterior foi interrompida e o estado atual não permite provar com segurança se a operação terminou. "
            "O ticket foi encerrado sem novas gravações; gere uma nova análise antes de qualquer outra mudança."
        )
        execution_store.mark_failed(ticket, message)
        service.memory.record_video_action(
            video_id=package.video_id,
            action_type="handoff_interrupted_ambiguous_state",
            surface="responsible_creator_service",
            changed_fields=list(package.changed_fields),
            before={"baseline_digest": package.baseline_digest},
            after=current,
            details={"tenant_id": package.tenant_id, "reason": "stale_processing_state_diverged"},
        )
        audit("handoff_reconciled", "failed_safe", package.tenant_id, {"video_id": package.video_id, "baseline_unchanged": False})
        raise HTTPException(status_code=409, detail=message)

    @app.get("/handoff/v1", response_class=FileResponse)
    async def handoff_page() -> FileResponse:
        page = Path(__file__).resolve().parent / "web" / "handoff.html"
        return FileResponse(
            page,
            media_type="text/html",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-Robots-Tag": "noindex, nofollow, noarchive",
            },
        )

    @app.post("/api/handoff/v1/apply")
    async def handoff_apply(payload: HandoffApplyRequest, request: Request) -> dict[str, Any]:
        require_same_origin(request)
        identity = browser_identity(request)
        decision = publication_store.consume_rate_limit(
            f"handoff:{identity.tenant_id}",
            limit=12,
            window_seconds=60,
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=429,
                detail="Muitas tentativas de handoff. Aguarde antes de tentar novamente.",
                headers={"Retry-After": str(decision.reset_after_seconds)},
            )

        try:
            package = open_handoff(payload.ticket)
        except HandoffError as exc:
            audit("handoff_rejected", "denied", identity.tenant_id, {"reason": type(exc).__name__})
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        if package.tenant_id != identity.tenant_id:
            audit("handoff_rejected", "denied", identity.tenant_id, {"reason": "tenant_mismatch"})
            raise HTTPException(status_code=403, detail="Este handoff pertence a outra conta.")

        service = service_for(identity.tenant_id)
        service.context.validate_youtube()
        channel_id = service._authorized_channel_id()
        if channel_id != package.channel_id:
            audit("handoff_rejected", "denied", identity.tenant_id, {"reason": "channel_mismatch"})
            raise HTTPException(
                status_code=409,
                detail="O canal ativo mudou desde a análise. Nenhuma alteração foi aplicada.",
            )

        existing = execution_store.get(
            payload.ticket,
            tenant_id=identity.tenant_id,
            video_id=package.video_id,
        )
        if existing is not None:
            if existing.status == "success" and existing.result:
                return {**existing.result, "idempotent_replay": True}
            if existing.status == "failed":
                raise HTTPException(status_code=409, detail=existing.error or "Este handoff já foi encerrado com falha segura.")
            if existing.status == "processing":
                if int(time.time()) - existing.updated_at < 45:
                    raise HTTPException(status_code=409, detail="Este handoff já está sendo processado.")
                return reconcile_interrupted_handoff(ticket=payload.ticket, package=package, service=service)

        service.memory.assert_not_recently_edited(package.video_id)
        current = service._current_video_snippet(package.video_id)
        if signer_from_env().payload_digest(current) != package.baseline_digest:
            audit("handoff_rejected", "denied", identity.tenant_id, {"reason": "baseline_changed", "video_id": package.video_id})
            raise HTTPException(
                status_code=409,
                detail="O vídeo mudou desde a análise. Nenhuma alteração foi aplicada; gere uma nova proposta.",
            )

        normalized = _normalize_ticket_proposal(
            service,
            video_id=package.video_id,
            proposed=package.proposed,
            current=current,
        )
        if canonical_digest(normalized) != package.proposed_digest:
            audit("handoff_rejected", "denied", identity.tenant_id, {"reason": "payload_changed", "video_id": package.video_id})
            raise HTTPException(status_code=409, detail="O conteúdo proposto não corresponde ao handoff assinado.")

        metadata_changed = _metadata_changed(service, current, normalized)
        playlist_needed = False
        if package.playlist_id:
            playlist_before = _playlist_membership(service, package.playlist_id)
            playlist_needed = not any(row["video_id"] == package.video_id for row in playlist_before)

        computed_fields = [
            field
            for field in ("title", "description", "tags", "categoryId")
            if service._semantic_value(field, current.get(field)) != service._semantic_value(field, normalized.get(field))
        ]
        if playlist_needed:
            computed_fields.append("playlist")
        if set(computed_fields) != set(package.changed_fields):
            raise HTTPException(
                status_code=409,
                detail="O conjunto de alterações não corresponde mais ao estado analisado. Gere um novo handoff.",
            )

        state, prior = execution_store.begin(
            payload.ticket,
            tenant_id=identity.tenant_id,
            video_id=package.video_id,
            expires_at=package.expires_at,
        )
        if state == "success" and prior and prior.result:
            return {**prior.result, "idempotent_replay": True}
        if state != "new":
            raise HTTPException(status_code=409, detail="Este handoff já possui uma execução registrada.")

        if not publication_store.consume_write_token(
            payload.ticket,
            tenant_id=identity.tenant_id,
            action="handoff_video_metadata_v1",
            subject=package.video_id,
            expires_at=package.expires_at,
        ):
            message = "Este handoff já foi utilizado e não será executado novamente."
            execution_store.mark_failed(payload.ticket, message)
            audit("handoff_rejected", "denied", identity.tenant_id, {"reason": "replay", "video_id": package.video_id})
            raise HTTPException(status_code=409, detail=message)

        metadata_result: dict[str, Any] | None = None
        playlist_result: dict[str, Any] | None = None
        try:
            if metadata_changed:
                metadata_result = _apply_metadata_from_exact_baseline(
                    service,
                    video_id=package.video_id,
                    baseline_digest=package.baseline_digest,
                    proposed=normalized,
                )

            if package.playlist_id and playlist_needed:
                try:
                    playlist_result = _add_playlist_item_verified(
                        service,
                        playlist_id=package.playlist_id,
                        video_id=package.video_id,
                    )
                except Exception as exc:
                    _rollback_metadata_after_secondary_failure(service, metadata_result, exc)

            verified = service._current_video_snippet(package.video_id)
            if metadata_changed and service._mismatches(verified, normalized):
                raise RuntimeError("A releitura final do vídeo divergiu da alteração aprovada.")
        except HTTPException as exc:
            final_error = _rollback_playlist_after_final_failure(service, playlist_result, exc)
            execution_store.mark_failed(payload.ticket, str(getattr(final_error, "detail", final_error)))
            raise
        except Exception as exc:
            final_error = _rollback_playlist_after_final_failure(service, playlist_result, exc)
            execution_store.mark_failed(payload.ticket, str(final_error))
            audit(
                "handoff_apply",
                "failed",
                identity.tenant_id,
                {"video_id": package.video_id, "error_type": type(final_error).__name__},
            )
            raise HTTPException(status_code=409, detail=str(final_error)) from final_error

        result = {
            "ok": True,
            "video_id": package.video_id,
            "channel_id": package.channel_id,
            "changed_fields": computed_fields,
            "persisted_verified": True,
            "current": verified,
            "playlist": playlist_result,
            "rollback_available": bool(metadata_result and metadata_result.get("rollback_preview")),
        }
        execution_store.mark_success(payload.ticket, result)
        audit(
            "handoff_apply",
            "success",
            identity.tenant_id,
            {"video_id": package.video_id, "changed_fields": computed_fields, "source": package.source},
        )
        return result

    # Replace the old dashboard AI apply endpoint so Gemini, OpenAI-compatible
    # providers and future internal models share the same responsible executor.
    _remove_route(app, "/api/dashboard/ai-optimize/apply/{action_id}", "POST")

    @app.post("/api/dashboard/ai-optimize/apply/{action_id}")
    async def dashboard_ai_apply_responsible(
        action_id: str,
        payload: ConfirmRequest,
        request: Request,
    ) -> dict[str, Any]:
        if payload.confirmed is not True:
            raise HTTPException(status_code=400, detail="Confirmação explícita obrigatória.")
        require_same_origin(request)
        identity = browser_identity(request)
        try:
            action = action_store.consume(
                action_id=action_id,
                tenant_id=identity.tenant_id,
                kind="ai_optimize_video",
            )
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        package = dict(action.payload or {})
        video_id = str(package.get("video_id", "")).strip()
        if not video_id:
            raise HTTPException(status_code=409, detail="A ação de IA não contém um vídeo alvo válido.")
        signer_from_env().verify(
            action.secret_token,
            action="ai_optimize_video",
            subject=video_id,
            payload=package,
        )

        service = service_for(identity.tenant_id)
        service.context.validate_youtube()
        service.memory.assert_not_recently_edited(video_id)
        current = service._current_video_snippet(video_id)
        baseline_digest = str(package.get("baseline_digest", "")).strip()
        if signer_from_env().payload_digest(current) != baseline_digest:
            raise HTTPException(
                status_code=409,
                detail="O vídeo mudou desde a análise. A ferramenta recusou sobrescrever o estado mais recente.",
            )

        plan = dict(package.get("plan", {}) or {})
        foreign_target = str(plan.get("video_id", "")).strip()
        if foreign_target and foreign_target != video_id:
            raise HTTPException(status_code=409, detail="A IA tentou alterar um vídeo diferente do alvo selecionado.")

        normalized = service._normalize_metadata_payload(
            video_id=video_id,
            title=str(plan.get("title", current["title"])),
            description=str(plan.get("description", current["description"])),
            tags=list(plan.get("tags", current.get("tags", [])) or []),
            current=current,
        )
        normalized["categoryId"] = service._normalize_category_id(plan.get("category_id"), current)
        normalized["defaultLanguage"] = current.get("defaultLanguage")

        playlist_id = str(plan.get("playlist_id", "")).strip()
        playlist_needed = False
        if playlist_id:
            before_membership = _playlist_membership(service, playlist_id)
            playlist_needed = not any(row["video_id"] == video_id for row in before_membership)

        metadata_result: dict[str, Any] | None = None
        playlist_result: dict[str, Any] | None = None
        try:
            if _metadata_changed(service, current, normalized):
                metadata_result = _apply_metadata_from_exact_baseline(
                    service,
                    video_id=video_id,
                    baseline_digest=baseline_digest,
                    proposed=normalized,
                )
            if playlist_id and playlist_needed:
                try:
                    playlist_result = _add_playlist_item_verified(
                        service,
                        playlist_id=playlist_id,
                        video_id=video_id,
                    )
                except Exception as exc:
                    _rollback_metadata_after_secondary_failure(service, metadata_result, exc)
            verified = service._current_video_snippet(video_id)
            if service._mismatches(verified, normalized):
                raise RuntimeError("A releitura final divergiu da proposta de IA aprovada.")
        except Exception as exc:
            final_error = _rollback_playlist_after_final_failure(service, playlist_result, exc)
            audit("dashboard_ai_responsible_apply", "failed", identity.tenant_id, {"video_id": video_id, "error_type": type(final_error).__name__})
            raise HTTPException(status_code=409, detail=str(final_error)) from final_error

        audit("dashboard_ai_responsible_apply", "success", identity.tenant_id, {"video_id": video_id})
        return {
            "ok": True,
            "video_id": video_id,
            "title": verified.get("title", ""),
            "persisted_verified": True,
            "playlist": playlist_result,
            "rollback_available": bool(metadata_result and metadata_result.get("rollback_preview")),
        }