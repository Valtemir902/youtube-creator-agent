from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from .context import LocalTenantResolver
from .service import CreatorService


mcp = MCPServer(
    name="YouTube Creator Agent Elite",
    instructions=(
        "Ferramentas para analisar, pesquisar e operar um canal do YouTube usando dados reais. "
        "Não prometa viralização nem invente volume de busca. Operações que alteram o canal exigem "
        "prévia assinada e confirmação explícita do usuário."
    ),
)


_resolver = LocalTenantResolver()


def _service(tenant_id: str = "local") -> CreatorService:
    return CreatorService(_resolver.resolve(tenant_id))


@mcp.custom_route("/", methods=["GET"])
async def local_home(request: Request) -> Response:
    host = request.url.netloc or "127.0.0.1:8000"
    return HTMLResponse(
        f"""<!doctype html><html lang='pt-BR'><meta charset='utf-8'>
        <meta name='viewport' content='width=device-width,initial-scale=1'>
        <body style='margin:0;background:#07101f;color:#eaf7ff;font:16px system-ui;display:grid;place-items:center;min-height:100vh'>
        <main style='max-width:760px;padding:36px;border:1px solid #173554;border-radius:18px;background:#0b1728'>
        <h1 style='color:#14d9f4'>YouTube Creator Agent MCP local está ativo ✅</h1>
        <p>Esta página é apenas o status humano. O endpoint do protocolo MCP é:</p>
        <pre style='padding:14px;background:#050b14;border-radius:10px'>http://{host}/mcp</pre>
        <p>Health check: <code>/health</code></p>
        <p style='color:#91a9bd'>Abrir <code>/mcp</code> diretamente no navegador não é um teste completo do protocolo; use um cliente MCP.</p>
        </main></body></html>""",
        headers={"Cache-Control": "no-store"},
    )


@mcp.custom_route("/health", methods=["GET"])
async def local_health(request: Request) -> Response:
    return JSONResponse({"ok": True, "service": "youtube-creator-agent-mcp-local", "mcp_path": "/mcp"})


@mcp.tool()
def creator_status(tenant_id: str = "local") -> dict[str, Any]:
    """Verifica conexão do YouTube e configuração de IA sem modificar nada."""
    return _service(tenant_id).status()


@mcp.tool()
def get_channel_profile(tenant_id: str = "local", period_days: int = 28) -> dict[str, Any]:
    """Obtém perfil analítico do próprio canal para 7 a 90 dias, sem modificar nada."""
    return _service(tenant_id).channel_profile(period_days=period_days)


@mcp.tool()
def research_youtube_topic(
    seed: str,
    tenant_id: str = "local",
    candidate_limit: int = 8,
) -> dict[str, Any]:
    """Pesquisa um assunto e retorna oportunidades validadas por dados reais do YouTube e fit do canal."""
    return _service(tenant_id).research_topic(seed, candidate_limit=candidate_limit)


@mcp.tool()
def build_channel_strategy(tenant_id: str = "local") -> dict[str, Any]:
    """Cria a estratégia atual do canal, incluindo plano de 7 dias, momentum e auditoria baseada em evidências."""
    return _service(tenant_id).build_channel_strategy()


@mcp.tool()
def preview_video_metadata_update(
    video_id: str,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    tenant_id: str = "local",
) -> dict[str, Any]:
    """Gera uma prévia de alteração de título/descrição/tags. NÃO altera o canal.

    A resposta inclui current, proposed, approval_payload e approval_token. Mostre a
    prévia ao usuário e peça confirmação explícita antes de chamar a ferramenta de aplicação.
    Vídeos recém-editados pela própria ferramenta são bloqueados pela memória persistente.
    """
    return _service(tenant_id).preview_video_metadata_update(
        video_id=video_id,
        title=title,
        description=description,
        tags=tags,
    )


@mcp.tool()
def apply_video_metadata_update(
    approval_payload: dict[str, Any],
    approval_token: str,
    user_confirmed: bool,
    tenant_id: str = "local",
) -> dict[str, Any]:
    """APLICA uma prévia assinada de metadata no YouTube.

    Só chame depois que o usuário confirmar explicitamente a prévia apresentada nesta
    conversa. `user_confirmed` deve ser true. O servidor rejeita payload alterado, token
    expirado, vídeo modificado depois da prévia ou vídeo ainda sob proteção de reedição.
    """
    if user_confirmed is not True:
        raise ValueError("Confirmação explícita do usuário é obrigatória para alterar o canal.")
    return _service(tenant_id).apply_video_metadata_update(
        approval_payload=approval_payload,
        approval_token=approval_token,
    )


def run() -> None:
    host = os.environ.get("YCA_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("YCA_MCP_PORT", "8000"))
    print(f"MCP local: http://{host}:{port}/mcp")
    print(f"Status humano: http://{host}:{port}/")
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    run()
