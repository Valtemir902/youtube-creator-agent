from __future__ import annotations

from fastapi.responses import HTMLResponse


_STYLE = """
<style>
:root { color-scheme: dark; }
body { margin: 0; background: #07111f; color: #e8f0fb; font: 16px/1.6 system-ui, sans-serif; }
main { max-width: 820px; margin: 0 auto; padding: 48px 24px 72px; }
h1, h2 { color: #ffffff; line-height: 1.2; }
a { color: #6bb7ff; }
small { color: #a8b8cc; }
</style>
"""


def _page(title: str, content: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{title} | YouTube Creator Agent</title>{_STYLE}</head>"
        f"<body><main>{content}</main></body></html>",
        headers={"Cache-Control": "public, max-age=3600"},
    )


def privacy_page() -> HTMLResponse:
    return _page(
        "Política de Privacidade",
        """
<h1>Política de Privacidade</h1>
<p><small>Vigente a partir de 5 de setembro de 2026</small></p>
<p>O YouTube Creator Agent é operado pela <strong>Silva Digital Tech</strong>.</p>
<h2>Dados processados</h2>
<p>Quando você usa o serviço, podemos processar dados necessários para analisar um canal do YouTube, executar ações que você aprovou e manter a segurança do serviço. Isso pode incluir identificadores de conta, dados de canal e vídeo, métricas disponibilizadas pelas APIs autorizadas do Google/YouTube, credenciais OAuth criptografadas e registros operacionais sem segredos.</p>
<h2>Finalidade e segurança</h2>
<p>Os dados são usados apenas para fornecer os recursos solicitados, proteger o acesso, prevenir abuso e manter a operação do produto. Credenciais de integração são armazenadas criptografadas; o serviço foi projetado para não registrar senhas, tokens ou chaves de API em registros operacionais.</p>
<h2>Provedores</h2>
<p>O serviço utiliza infraestrutura da Oracle Cloud, conectividade e proteção de borda da Cloudflare e APIs do Google/YouTube quando você conecta uma conta. Quando usado dentro do ChatGPT, o processamento de conversa segue os termos aplicáveis da OpenAI.</p>
<h2>Suas escolhas</h2>
<p>Você pode desconectar uma conta do YouTube pela interface de onboarding. Para solicitar acesso, correção ou exclusão de dados, escreva para <a href='mailto:silvadigitaltech@gmail.com'>silvadigitaltech@gmail.com</a>.</p>
<h2>Alterações</h2>
<p>Esta política pode ser atualizada quando o serviço ou os requisitos aplicáveis mudarem. A data de vigência será atualizada nesta página.</p>
<p><a href='/terms'>Termos de Uso</a> · <a href='/support'>Suporte</a></p>
""",
    )


def terms_page() -> HTMLResponse:
    return _page(
        "Termos de Uso",
        """
<h1>Termos de Uso</h1>
<p><small>Vigente a partir de 5 de setembro de 2026</small></p>
<p>O YouTube Creator Agent é operado pela <strong>Silva Digital Tech</strong>.</p>
<h2>Uso autorizado</h2>
<p>Use o serviço somente com contas e canais do YouTube que você tem autorização para administrar. Você é responsável por revisar as informações e confirmar qualquer alteração antes que ela seja aplicada.</p>
<h2>Recomendações e ações</h2>
<p>Análises, pontuações e recomendações servem como apoio à decisão. O serviço não garante visualizações, receita, crescimento, classificação, distribuição ou qualquer resultado específico. Alterações de metadados passam por uma etapa de prévia e aprovação.</p>
<h2>Serviços de terceiros</h2>
<p>O produto depende de serviços de terceiros, incluindo Google/YouTube, Cloudflare, Oracle Cloud e, quando aplicável, OpenAI/ChatGPT. A disponibilidade e as políticas desses provedores podem mudar independentemente deste serviço.</p>
<h2>Uso proibido</h2>
<p>Não use o serviço para acessar contas sem autorização, burlar limites, fornecer credenciais de terceiros, prejudicar a operação do produto ou violar leis e políticas das plataformas conectadas.</p>
<h2>Contato</h2>
<p>Dúvidas sobre estes termos podem ser enviadas para <a href='mailto:silvadigitaltech@gmail.com'>silvadigitaltech@gmail.com</a>.</p>
<p><a href='/privacy'>Política de Privacidade</a> · <a href='/support'>Suporte</a></p>
""",
    )


def support_page() -> HTMLResponse:
    return _page(
        "Suporte",
        """
<h1>Suporte</h1>
<p>Para suporte do YouTube Creator Agent, envie uma mensagem para:</p>
<p><a href='mailto:silvadigitaltech@gmail.com'>silvadigitaltech@gmail.com</a></p>
<p>Inclua uma descrição do problema, o horário aproximado e, se houver, o identificador da solicitação. Não envie senhas, tokens, chaves de API ou segredos por e-mail.</p>
<p><a href='/privacy'>Política de Privacidade</a> · <a href='/terms'>Termos de Uso</a></p>
""",
    )
