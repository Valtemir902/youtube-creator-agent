from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from google.auth.exceptions import RefreshError

from elite_v2_ui import elite_v2_webengine_source

HOTFIX_REVISION = "revoked-token-recovery-v1"

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
  const probe=async()=>{
    try{
      const r=await fetch('/api/dashboard/channel/identity',{credentials:'same-origin',headers:{Accept:'application/json'}});
      if(r.status===409){const d=await r.json().catch(()=>({}));if(d.code==='youtube_reconnect_required'){installBanner(d.detail);const dot=document.getElementById('onlineDot');if(dot)dot.classList.remove('ok');const text=document.getElementById('onlineText');if(text)text.textContent='YouTube requer reconexão';}}
    }catch(_err){}
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(probe,120),{once:true});else setTimeout(probe,120);
})();
'''


def _inject_cloud_elite_v2(html: str) -> str:
    """Add the cloud Elite V2 layer without discarding previously composed HTML."""
    source = elite_v2_webengine_source() + "\n" + _RECONNECT_JS
    injection = "<script data-yca-cloud-elite-v2>\n" + source.replace("</script", "<\\/script") + "\n</script>"
    if "data-yca-cloud-elite-v2" not in html:
        html = html.replace("</body>", injection + "\n</body>", 1)
    return html


def _dashboard_html() -> str:
    page = Path(__file__).resolve().parent / "web" / "dashboard.html"
    return _inject_cloud_elite_v2(page.read_text(encoding="utf-8"))


def install_dashboard_runtime_hotfix(app: FastAPI) -> None:
    """Harden cloud dashboard runtime without changing any YouTube write contract.

    * Expired/revoked Google refresh tokens become a recoverable 409 instead of 500.
    * The authenticated web dashboard receives the certified Elite V2 visual layer.
    * Previously composed dashboard layers are preserved verbatim.
    * No Google/YouTube call is performed by this installer itself.
    """

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

    @app.middleware("http")
    async def cloud_elite_v2_dashboard(request: Request, call_next):
        response = await call_next(request)
        if request.url.path != "/dashboard" or response.status_code != 200:
            return response

        chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else bytes(chunk))
        html = b"".join(chunks).decode("utf-8")
        html = _inject_cloud_elite_v2(html)

        headers = {k: v for k, v in response.headers.items() if k.lower() not in {"content-length", "content-type"}}
        headers["Cache-Control"] = "no-store"
        headers["X-YCA-Dashboard-UI"] = "elite-v2-cloud"
        return HTMLResponse(html, status_code=200, headers=headers)
