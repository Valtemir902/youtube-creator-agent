from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

from pydantic import AnyHttpUrl
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings

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


def _service():
    from .service import CreatorService
    resolver = _resolver()
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
            "Você é a camada de inteligência. Use estas ferramentas apenas para obter dados reais, validar hipóteses e operar o YouTube do usuário autenticado. "
            "No modo ChatGPT Native, nenhuma IA externa do backend é necessária: gere candidatos, títulos e estratégia no próprio ChatGPT. "
            "Nunca trate demand_index como volume exato de buscas. Combine outros apps autorizados quando estiverem disponíveis e forem úteis. "
            "Ações de escrita exigem prévia assinada e confirmação explícita do usuário."
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
        """Status da conta autenticada. No ChatGPT Native, IA externa é opcional."""
        _require_scope(READ_SCOPE)
        return _service().status()

    @server.tool()
    def get_creator_capabilities() -> dict[str, Any]:
        """Descreve responsabilidades do ChatGPT, do backend e as limitações das métricas."""
        _require_scope(READ_SCOPE)
        return _service().chatgpt_capabilities()

    @server.tool()
    def create_onboarding_link() -> dict[str, Any]:
        """Cria um link web de onboarding de uso único para o usuário autenticado.

        O link expira rapidamente, não contém tenant_id e é trocado no navegador por
        uma sessão HttpOnly. Use quando o usuário precisar conectar YouTube ou revisar
        as configurações da conta.
        """
        _require_scope(READ_SCOPE)
        base_url = os.environ.get("YCA_ONBOARDING_PUBLIC_URL", "").strip().rstrip("/")
        if not base_url:
            raise RuntimeError("YCA_ONBOARDING_PUBLIC_URL não configurada no servidor.")
        from .onboarding_sessions import OnboardingSessionStore
        token = _access_token()
        scopes = list(token.scopes or [])
        launch = OnboardingSessionStore(_resolver().db).issue_launch(
            _tenant_id(), scopes, ttl_seconds=600
        )
        return {
            "url": f"{base_url}/onboarding/launch?{urlencode({'token': launch})}",
            "expires_in_seconds": 600,
            "single_use": True,
            "contains_tenant_id": False,
        }

    @server.tool()
    def get_channel_profile(period_days: int = 28) -> dict[str, Any]:
        """Obtém métricas reais do canal autenticado para 7 a 90 dias, sem chamar IA externa."""
        _require_scope(READ_SCOPE)
        return _service().channel_profile(period_days=period_days)

    @server.tool()
    def get_strategy_evidence(period_days: int = 28) -> dict[str, Any]:
        """Retorna um pacote de evidências do canal para o próprio ChatGPT montar a estratégia.

        Inclui termos reais de busca, vídeos fortes/fracos, formato e tráfego. Não gera estratégia via IA externa.
        """
        _require_scope(READ_SCOPE)
        return _service().strategy_evidence(period_days=period_days)

    @server.tool()
    def validate_keyword_candidates(
        keywords: list[str],
        period_days: int = 28,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """Valida até 20 keywords sugeridas pelo ChatGPT usando YouTube + Analytics reais.

        Retorna demanda como índice estimado, concorrência, atualidade, velocidade, breakout, channel fit e evidências.
        A API pública do YouTube não fornece contagem exata de buscas diárias para keywords arbitrárias.
        """
        _require_scope(READ_SCOPE)
        return _service().validate_keyword_candidates(
            keywords,
            period_days=period_days,
            max_results=max_results,
        )

    @server.tool()
    def preview_video_metadata_update(
        video_id: str,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Gera prévia assinada de metadata proposta pelo ChatGPT. Não altera o canal."""
        _require_scope(WRITE_SCOPE)
        return _service().preview_video_metadata_update(
            video_id=video_id,
            title=title,
            description=description,
            tags=tags,
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
