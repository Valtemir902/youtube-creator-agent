from __future__ import annotations

import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

from pydantic import AnyHttpUrl
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations

from .cloud_auth import IntrospectionTokenVerifier


READ_SCOPE = "yca:read"
WRITE_SCOPE = "yca:write"


def _access_token():
    token = get_access_token()
    if token is None:
        raise PermissionError("Requisição não autenticada.")
    return token


def _tenant_id() -> str:
    token = _access_token()
    tenant_id = str((token.claims or {}).get("tenant_id", "")).strip()
    if not tenant_id:
        raise PermissionError("Token autenticado sem identidade de tenant.")
    return tenant_id


def _require_scope(scope: str) -> None:
    token = _access_token()
    if scope not in set(token.scopes or []):
        raise PermissionError(f"Escopo obrigatório ausente: {scope}")


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
        raise RuntimeError(
            f"Limite temporário excedido para {kind}. Tente novamente em "
            f"{decision.reset_after_seconds} segundos."
        )


def _audit(event_type: str, outcome: str, metadata: dict[str, Any] | None = None) -> None:
    _ops_store().record_event(
        event_type=event_type,
        outcome=outcome,
        tenant_id=_tenant_id(),
        metadata=metadata,
    )


def _service():
    from .safe_service import SafeCreatorService
    resolver = _resolver()
    context = resolver.resolve(_tenant_id())
    return SafeCreatorService(context)


def create_server() -> MCPServer:
    issuer = os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()
    resource = os.environ.get("YCA_MCP_PUBLIC_URL", "").strip()
    if not issuer or not resource:
        raise RuntimeError("YCA_AUTH_ISSUER_URL e YCA_MCP_PUBLIC_URL são obrigatórios no MCP cloud.")

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
            issuer_url=AnyHttpUrl(issuer),
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
        _require_scope(READ_SCOPE)
        _limit("read", limit=180)
        return _service().status()

    @server.tool(
        title="Ver capacidades do YouTube Creator Agent",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_creator_capabilities() -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("read", limit=180)
        return _service().chatgpt_capabilities()

    @server.tool(
        title="Criar link seguro de conexão",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=False, destructive_hint=False, idempotent_hint=False),
    )
    def create_onboarding_link() -> dict[str, Any]:
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

    @server.tool(
        title="Obter perfil e métricas do canal",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_channel_profile(period_days: int = 28) -> dict[str, Any]:
        _require_scope(READ_SCOPE)
        _limit("analytics", limit=60)
        return _service().channel_profile(period_days=period_days)

    @server.tool(
        title="Obter evidências para estratégia",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False, idempotent_hint=True),
    )
    def get_strategy_evidence(period_days: int = 28) -> dict[str, Any]:
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
        _require_scope(READ_SCOPE)
        _limit("keyword_research", limit=20)
        return _service().validate_keyword_candidates(
            keywords,
            period_days=period_days,
            max_results=max_results,
        )

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
        _require_scope(WRITE_SCOPE)
        _limit("write_preview", limit=30)
        result = _service().preview_video_metadata_update(
            video_id=video_id,
            title=title,
            description=description,
            tags=tags,
        )
        _audit("mcp_video_metadata_preview", "success", metadata={"video_id": video_id, "changed": result.get("changed", {})})
        return result

    @server.tool(
        title="Aplicar metadados aprovados no vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_update(
        approval_payload: dict[str, Any],
        approval_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        _require_scope(WRITE_SCOPE)
        _limit("write_apply", limit=15)
        if user_confirmed is not True:
            _audit("mcp_video_metadata_apply", "denied", metadata={"reason": "confirmation_missing"})
            raise ValueError("Confirmação explícita do usuário é obrigatória.")
        result = _service().apply_video_metadata_update(
            approval_payload=approval_payload,
            approval_token=approval_token,
        )
        _audit(
            "mcp_video_metadata_apply",
            "success",
            metadata={"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
        )
        return result

    @server.tool(
        title="Restaurar metadados anteriores do vídeo",
        annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=True, idempotent_hint=False),
    )
    def apply_video_metadata_rollback(
        rollback_payload: dict[str, Any],
        rollback_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        """Restaura exatamente os metadados anteriores com o pacote assinado retornado pelo apply.

        Exige confirmação explícita e escopo de escrita. É a única exceção à proteção de
        reedição recente e falha se o vídeo mudou, o token expirou ou o payload foi alterado.
        """
        _require_scope(WRITE_SCOPE)
        _limit("write_rollback", limit=10)
        if user_confirmed is not True:
            _audit("mcp_video_metadata_rollback", "denied", metadata={"reason": "confirmation_missing"})
            raise ValueError("Confirmação explícita do usuário é obrigatória para executar rollback.")
        result = _service().apply_video_metadata_rollback(
            rollback_payload=rollback_payload,
            rollback_token=rollback_token,
        )
        _audit(
            "mcp_video_metadata_rollback",
            "success",
            metadata={"video_id": result.get("video_id"), "changed_fields": result.get("changed_fields", [])},
        )
        return result

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
