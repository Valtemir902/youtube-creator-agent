from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Callable
from urllib.parse import urlencode

from pydantic import AnyHttpUrl
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations

from .cloud_auth import IntrospectionTokenVerifier
from .channel_accounts import activate_channel, channel_account_state, list_channel_accounts
from .mcp_errors import structured_call, success_response, tool_error, log_tool_exception
from .security import signer_from_env


READ_SCOPE = "yca:read"
WRITE_SCOPE = "yca:write"


def _access_token():
    token = get_access_token()
    if token is None:
        raise tool_error("authentication_required")
    return token


def _tenant_id() -> str:
    token = _access_token()
    tenant_id = str((token.claims or {}).get("tenant_id", "")).strip()
    if not tenant_id:
        raise tool_error("authentication_required", "Authenticated token has no tenant identity.")
    return tenant_id


def _require_scope(scope: str) -> None:
    token = _access_token()
    if scope not in set(token.scopes or []):
        if scope == WRITE_SCOPE:
            raise tool_error("write_scope_missing")
        raise tool_error("read_scope_missing")


def _resolver():
    from .cloud_runtime import CloudTenantResolver
    return CloudTenantResolver()


@lru_cache(maxsize=1)
def _ops_store():
    from .publication_store import PublicationStore
    resolver = _resolver()
    return PublicationStore(resolver.db.path)


def _limit(kind: str, *, limit: int, window_seconds: int = 60) -> None:
    tenant_id = _tenant_id()
    decision = _ops_store().consume_rate_limit(
        f"mcp:{kind}:{tenant_id}",
        limit=limit,
        window_seconds=window_seconds,
    )
    if not decision.allowed:
        raise tool_error(
            "rate_limited",
            f"Rate limit exceeded for {kind}. Try again in {decision.reset_after_seconds} seconds.",
        )


def _audit(event_type: str, outcome: str, metadata: dict[str, Any] | None = None) -> None:
    """Record operational audit without turning a completed YouTube write into a false failure."""
    try:
        _ops_store().record_event(
            event_type=event_type,
            outcome=outcome,
            tenant_id=_tenant_id(),
            metadata=metadata,
        )
    except Exception as exc:  # service-level creator memory remains the authoritative write audit
        log_tool_exception("audit_event", exc, tenant_id=None)


def _service():
    from .safe_service import SafeCreatorService
    resolver = _resolver()
    context = resolver.resolve(_tenant_id())
    return SafeCreatorService(context)


def _structured(operation: str, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    tenant_id = None
    try:
        tenant_id = _tenant_id()
    except Exception:
        pass
    result = structured_call(operation, callback, tenant_id=tenant_id)
    assert isinstance(result, dict)
    return result


def _signed_subject(payload: dict[str, Any]) -> str:
    proposed = dict(payload.get("proposed", {}) or {})
    video_id = str(proposed.get("video_id", "")).strip()
    if not video_id:
        raise tool_error("invalid_request", "video_id is missing from the signed payload.")
    return video_id


def _consume_signed_write(
    *,
    token: str,
    payload: dict[str, Any],
    action: str,
) -> str:
    """Verify a signed write package and atomically reject replay before mutation."""
    subject = _signed_subject(payload)
    parsed = signer_from_env().verify(
        token,
        action=action,
        subject=subject,
        payload=payload,
    )
    consumed = _ops_store().consume_write_token(
        token,
        tenant_id=_tenant_id(),
        action=action,
        subject=subject,
        expires_at=parsed.expires_at,
    )
    if not consumed:
        raise tool_error("approval_replayed")
    return subject


def create_server() -> MCPServer:
    token_issuer = os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()
    oauth_issuer = (
        os.environ.get("YCA_CHATGPT_OAUTH_ISSUER_URL", "").strip()
        or os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip()
        or token_issuer
    )
    resource = os.environ.get("YCA_MCP_PUBLIC_URL", "").strip()
    if not token_issuer or not oauth_issuer or not resource:
        raise RuntimeError(
            "YCA_AUTH_ISSUER_URL, um issuer OAuth público e YCA_MCP_PUBLIC_URL são obrigatórios no MCP cloud."
        )

    server = MCPServer(
        name="YouTube Creator Agent",
        instructions=(
            "Você é a camada de inteligência. Use estas ferramentas para obter dados reais, validar hipóteses e operar somente o YouTube do usuário autenticado. "
            "No modo ChatGPT Native, nenhuma IA externa do backend é necessária: gere candidatos, títulos e estratégia no próprio ChatGPT. "
            "Nunca trate demand_index como volume exato de buscas. Combine outros apps autorizados quando estiverem disponíveis e forem úteis. "
            "Ferramentas de leitura não alteram o canal. Ferramentas de escrita exigem escopo de escrita, prévia assinada e confirmação explícita do usuário."
        ),
        token_verifier=IntrospectionTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(oauth_issuer),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=[READ_SCOPE],
            validate_token_resource=True,
        ),
    )

    @server.tool(
        title="Verificar status do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def creator_status() -> dict[str, Any]:
        return _structured("creator_status", lambda: _creator_status())

    def _creator_status() -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("read", limit=180)
        return _service().status()

    @server.tool(
        title="Ver capacidades do YouTube Creator Agent",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_creator_capabilities() -> dict[str, Any]:
        return _structured("get_creator_capabilities", lambda: _creator_capabilities())

    def _creator_capabilities() -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("read", limit=180)
        return _service().chatgpt_capabilities()

    @server.tool(
        title="Listar canais conectados",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def list_connected_channels() -> dict[str, Any]:
        return _structured("list_connected_channels", lambda: _connected_channels())

    def _connected_channels() -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("read", limit=180)
        return list_channel_accounts(_resolver().db, _tenant_id())

    @server.tool(
        title="Ativar canal conectado",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def activate_connected_channel(channel_id: str, user_confirmed: bool) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            _require_scope(WRITE_SCOPE)
            _limit("channel_switch", limit=30)
            db = _resolver().db
            tenant_id = _tenant_id()
            # Refresh registry first, but never mutate the active channel merely
            # because the requested channel is already selected.
            list_channel_accounts(db, tenant_id)
            state = channel_account_state(db, tenant_id, channel_id)
            if not state["exists"]:
                raise tool_error("channel_not_found")
            if state["already_active"]:
                _audit("mcp_channel_activation_noop", "success", {"channel_id": channel_id})
                return success_response(
                    already_active=True,
                    channel_id=str(channel_id).strip(),
                    active_channel=state.get("channel"),
                )
            if user_confirmed is not True:
                _audit("mcp_channel_activated", "denied", {"reason": "confirmation_missing", "channel_id": channel_id})
                raise tool_error("confirmation_required")
            channel = activate_channel(db, tenant_id, channel_id)
            _audit("mcp_channel_activated", "success", {"channel_id": channel_id})
            return success_response(
                already_active=False,
                channel_id=str(channel_id).strip(),
                active_channel=channel,
            )

        return _structured("activate_connected_channel", action)

    @server.tool(
        title="Criar link seguro de conexão",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def create_onboarding_link() -> dict[str, Any]:
        def action() -> dict[str, Any]:
            _require_scope(READ_SCOPE)
            _limit("onboarding", limit=10)
            base_url = os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")
            if not base_url:
                raise RuntimeError("YCA_ONBOARDING_PUBLIC_URL não configurada no servidor.")
            from .onboarding_sessions import OnboardingSessionStore
            token = _access_token()
            scopes = list(token.scopes or [])
            launch = OnboardingSessionStore(_resolver().db).issue_launch(_tenant_id(), scopes, ttl_seconds=600)
            _audit("mcp_onboarding_link_created", "success")
            return {
                "url": f"{base_url}/onboarding/launch?{urlencode({'token': launch})}",
                "expires_in_seconds": 600,
                "single_use": True,
                "contains_tenant_id": False,
            }

        return _structured("create_onboarding_link", action)

    @server.tool(
        title="Obter perfil e métricas do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_channel_profile(period_days: int = 28) -> dict[str, Any]:
        return _structured("get_channel_profile", lambda: _channel_profile(period_days))

    def _channel_profile(period_days: int) -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("analytics", limit=60)
        return _service().channel_profile(period_days=period_days)

    @server.tool(
        title="Obter evidências para estratégia",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_strategy_evidence(period_days: int = 28) -> dict[str, Any]:
        return _structured("get_strategy_evidence", lambda: _strategy_evidence(period_days))

    def _strategy_evidence(period_days: int) -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("analytics", limit=60)
        return _service().strategy_evidence(period_days=period_days)

    @server.tool(
        title="Validar oportunidades de palavras-chave",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False, idempotent_hint=True),
    )
    def validate_keyword_candidates(
        keywords: list[str],
        period_days: int = 28,
        max_results: int = 25,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            _require_scope(READ_SCOPE)
            _limit("keyword_research", limit=20)
            return _service().validate_keyword_candidates(
                keywords,
                period_days=period_days,
                max_results=max_results,
            )

        return _structured("validate_keyword_candidates", action)

    @server.tool(
        title="Preparar prévia de metadados do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def preview_video_metadata_update(
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            _require_scope(WRITE_SCOPE)
            _limit("write_preview", limit=30)
            result = _service().preview_video_metadata_update(
                video_id=video_id,
                title=title,
                description=description,
                tags=tags,
            )
            _audit("mcp_video_metadata_preview", "success", metadata={"video_id": video_id, "changed": result.get("changed", {})})
            return success_response(result)

        return _structured("preview_video_metadata_update", action)

    @server.tool(
        title="Aplicar metadados aprovados no vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_update(
        approval_payload: dict[str, Any],
        approval_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            _require_scope(WRITE_SCOPE)
            _limit("write_apply", limit=15)
            if user_confirmed is not True:
                _audit("mcp_video_metadata_apply", "denied", metadata={"reason": "confirmation_missing"})
                raise tool_error("confirmation_required")
            video_id = _consume_signed_write(
                token=approval_token,
                payload=approval_payload,
                action="update_video_metadata",
            )
            try:
                result = _service().apply_video_metadata_update(
                    approval_payload=approval_payload,
                    approval_token=approval_token,
                )
            except Exception:
                _audit("mcp_video_metadata_apply", "failed", metadata={"video_id": video_id})
                raise
            _audit(
                "mcp_video_metadata_apply",
                "success",
                metadata={"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
            )
            return success_response(result)

        return _structured("apply_video_metadata_update", action)

    @server.tool(
        title="Restaurar metadados anteriores do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_rollback(
        rollback_payload: dict[str, Any],
        rollback_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        """Restore the exact previous metadata using the signed rollback package."""
        def action() -> dict[str, Any]:
            _require_scope(WRITE_SCOPE)
            _limit("write_rollback", limit=10)
            if user_confirmed is not True:
                _audit("mcp_video_metadata_rollback", "denied", metadata={"reason": "confirmation_missing"})
                raise tool_error("confirmation_required")
            video_id = _consume_signed_write(
                token=rollback_token,
                payload=rollback_payload,
                action="rollback_video_metadata",
            )
            try:
                result = _service().apply_video_metadata_rollback(
                    rollback_payload=rollback_payload,
                    rollback_token=rollback_token,
                )
            except Exception:
                _audit("mcp_video_metadata_rollback", "failed", metadata={"video_id": video_id})
                raise
            _audit(
                "mcp_video_metadata_rollback",
                "success",
                metadata={"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
            )
            return success_response(result)

        return _structured("apply_video_metadata_rollback", action)

    return server


def run() -> None:
    server = create_server()
    host = os.environ.get("YCA_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("YCA_MCP_PORT", "8000"))
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    run()
