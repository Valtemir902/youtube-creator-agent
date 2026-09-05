from __future__ import annotations

import os
from typing import Any

from pydantic import AnyHttpUrl
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings

from .cloud_auth import IntrospectionTokenVerifier


READ_SCOPE = "yca:read"
WRITE_SCOPE = "yca:write"


def _tenant_id() -> str:
    token = get_access_token()
    if token is None:
        raise PermissionError("Requisição não autenticada.")
    tenant_id = str((token.claims or {}).get("tenant_id", "")).strip()
    if not tenant_id:
        raise PermissionError("Token autenticado sem identidade de tenant.")
    return tenant_id


def _require_scope(scope: str) -> None:
    token = get_access_token()
    if token is None or scope not in set(token.scopes or []):
        raise PermissionError(f"Escopo obrigatório ausente: {scope}")


def _service():
    from .cloud_runtime import CloudTenantResolver
    from .service import CreatorService

    resolver = CloudTenantResolver()
    context = resolver.resolve(_tenant_id())
    return CreatorService(context)


def create_server() -> MCPServer:
    issuer = os.environ.get("YCA_AUTH_ISSUER_URL", "").strip()
    resource = os.environ.get("YCA_MCP_PUBLIC_URL", "").strip()
    if not issuer or not resource:
        raise RuntimeError("YCA_AUTH_ISSUER_URL e YCA_MCP_PUBLIC_URL são obrigatórios no MCP cloud.")

    server = MCPServer(
        name="YouTube Creator Agent Elite Cloud",
        instructions=(
            "Analise e opere somente o canal pertencente ao usuário autenticado. "
            "Nunca invente métricas. Ações de escrita exigem prévia assinada e confirmação explícita."
        ),
        token_verifier=IntrospectionTokenVerifier(),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=[READ_SCOPE],
            validate_token_resource=True,
        ),
    )

    @server.tool()
    def creator_status() -> dict[str, Any]:
        """Status da conta autenticada. Não modifica nada."""
        _require_scope(READ_SCOPE)
        return _service().status()

    @server.tool()
    def get_channel_profile(period_days: int = 28) -> dict[str, Any]:
        """Perfil analítico do canal autenticado para 7 a 90 dias."""
        _require_scope(READ_SCOPE)
        return _service().channel_profile(period_days=period_days)

    @server.tool()
    def research_youtube_topic(seed: str, candidate_limit: int = 8) -> dict[str, Any]:
        """Pesquisa oportunidades reais para o canal autenticado."""
        _require_scope(READ_SCOPE)
        return _service().research_topic(seed, candidate_limit=candidate_limit)

    @server.tool()
    def build_channel_strategy() -> dict[str, Any]:
        """Cria estratégia, momentum e plano editorial do canal autenticado."""
        _require_scope(READ_SCOPE)
        return _service().build_channel_strategy()

    @server.tool()
    def preview_video_metadata_update(
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Gera prévia assinada de metadata. Não altera o canal."""
        _require_scope(WRITE_SCOPE)
        return _service().preview_video_metadata_update(
            video_id=video_id, title=title, description=description, tags=tags
        )

    @server.tool()
    def apply_video_metadata_update(
        approval_payload: dict[str, Any],
        approval_token: str,
        user_confirmed: bool,
    ) -> dict[str, Any]:
        """Aplica exatamente uma prévia assinada após confirmação explícita."""
        _require_scope(WRITE_SCOPE)
        if user_confirmed is not True:
            raise ValueError("Confirmação explícita do usuário é obrigatória.")
        return _service().apply_video_metadata_update(
            approval_payload=approval_payload,
            approval_token=approval_token,
        )

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
