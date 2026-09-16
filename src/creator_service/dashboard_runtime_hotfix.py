from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from google.auth.exceptions import RefreshError

from elite_v2_ui import elite_v2_webengine_source

from .ai_vault_ui import enhance_ai_vault_html
from .dashboard_human_results_ui import enhance_human_results_html
from .dashboard_stability_guard import _HEAD_SCRIPT, _apply_fast_boot_policy
from .extended_onboarding import _enhance_dashboard_html

HOTFIX_REVISION = "revoked-token-recovery-v5-final-certification"

_RECONNECT_JS = r'''
(()=>{
  const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
  const installBanner=(detail)=>{
    if(document.querySelector('[data-yca-google-reconnect]'))return;
    const host=document.querySelector('.content')||document.body;
    const box=document.createElement('section');
    box.dataset.ycaGoogleReconnect='1';
    box.style.cssText='margin:0 0 16px;padding:15px 16px;border:1px solid rgba(251,191,36,.42);border-radius:16px;background:rgba(120,75,5,.18);box-shadow:0 16px 44px rgba(0,0,0,.2)';
    box.innerHTML=`<div style="display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap"><div><strong style="display:block;margin-bottom:4px">Reconecte o YouTube</strong><span style="color:#c5d2e2;font-size:12px">${esc(detail||'A autorização do Google expirou ou foi revogada. Seus dados permanecem intactos; é necessário autorizar novamente para ler o canal.')}</span></div><button type="button" class="btn primary" data-yca-reconnect-google>Reconectar agora</button></div>`;
    host.prepend(box);
    box.querySelector('[data-yca-reconnect-google]').onclick=async ev=>{
      const b=ev.currentTarget;b.disabled=true;b.textContent='Abrindo Google…';
      try{
        const r=await fetch('/api/dashboard/channels/connect',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'});
        const d=await r.json().catch(()=>({}));
        if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);
        if(!d.authorization_url)throw new Error('O servidor não retornou a URL de autorização do Google.');
        location.href=d.authorization_url;
      }catch(err){b.disabled=false;b.textContent='Reconectar agora';const span=box.querySelector('span');if(span)span.textContent=err.message||String(err)}
    };
  };
  const showReconnect=()=>{
    installBanner();
    const dot=document.getElementById('onlineDot');if(dot)dot.classList.remove('ok');
    const text=document.getElementById('onlineText');if(text)text.textContent='YouTube requer reconexão';
  };
  window.addEventListener('yca:youtube-reconnect-required',showReconnect);
  const boot=()=>{if(window.__ycaYoutubeReconnectRequired)showReconnect()};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
'''


def _apply_cloud_presentation(source: str) -> str:
    """Add cloud-only UX on top of the already-composed dashboard HTML."""
    source = enhance_human_results_html(source)
    bundle = elite_v2_webengine_source() + "\n" + _RECONNECT_JS
    injection = "<script data-yca-cloud-elite-v2>\n" + bundle.replace("</script", "<\\/script") + "\n</script>"
    if "data-yca-cloud-elite-v2" not in source:
        source = source.replace("</body>", injection + "\n</body>", 1)
    return source


def _dashboard_html() -> str:
    """Build a deterministic standalone fixture with the critical composition layers.

    Production does not use this function to replace the response anymore. It is
    intentionally kept for tests/fixtures that need a complete dashboard without
    starting the application.
    """
    page = Path(__file__).resolve().parent / "web" / "dashboard.html"
    html = page.read_text(encoding="utf-8")
    html = _enhance_dashboard_html(html)
    html = enhance_ai_vault_html(html)
    html = _apply_fast_boot_policy(html)
    if "data-yca-stability-guard" not in html:
        html = html.replace("</head>", _HEAD_SCRIPT + "\n</head>", 1)
    return _apply_cloud_presentation(html)


def install_dashboard_runtime_hotfix(app: FastAPI) -> None:
    """Harden cloud dashboard runtime without changing any YouTube write contract.

    The cloud layer wraps the dashboard route that previous installers already
    composed. It never rebuilds the page from the raw HTML at request time. This
    preserves stability guards, feature workspaces, the advanced key vault and any
    future route-level enhancer installed before this final presentation layer.
    """
    if getattr(app.state, "dashboard_runtime_hotfix_installed", False):
        return

    @app.exception_handler(RefreshError)
    async def google_refresh_error(_request: Request, exc: RefreshError) -> JSONResponse:
        text = str(exc).casefold()
        expired = "invalid_grant" in text or "expired" in text or "revoked" in text
        detail = (
            "A autorização do Google expirou ou foi revogada. Reconecte o YouTube para restaurar as leituras do canal."
            if expired
            else "A credencial do Google não pôde ser renovada. Reconecte o YouTube para continuar."
        )
        return JSONResponse(
            {
                "detail": detail,
                "code": "youtube_reconnect_required",
                "reconnect_required": True,
                "youtube_write_performed": False,
            },
            status_code=409,
            headers={"Cache-Control": "no-store"},
        )

    route = next(
        r for r in app.router.routes
        if isinstance(r, APIRoute) and r.path == "/dashboard" and "GET" in (r.methods or set())
    )
    original = route.endpoint
    app.router.routes.remove(route)

    async def dashboard(request: Request):
        response = await original(request)
        if not isinstance(response, HTMLResponse):
            return response
        headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in {"content-length", "content-type"}
        }
        headers["Cache-Control"] = "no-store"
        headers["X-YCA-Dashboard-UI"] = "elite-v2-cloud"
        headers["X-YCA-Dashboard-UX"] = "human-results-key-vault"
        source = response.body.decode("utf-8")
        source = _apply_cloud_presentation(source)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route(
        "/dashboard",
        dashboard,
        methods=["GET"],
        include_in_schema=False,
        name="dashboard_runtime_hotfix",
    )
    app.state.dashboard_runtime_hotfix_installed = True
