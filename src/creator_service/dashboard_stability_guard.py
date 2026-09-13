from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_HEAD_SCRIPT = r'''
<script data-yca-stability-guard>
(()=>{
  if(window.__ycaStabilityGuard)return;
  window.__ycaStabilityGuard=true;
  const baseFetch=window.fetch.bind(window);
  const classify=(input,init)=>{
    const method=String((init&&init.method)||(input&&input.method)||'GET').toUpperCase();
    let url;try{url=new URL(typeof input==='string'?input:input.url,location.href)}catch{return null}
    if(method!=='GET'||url.origin!==location.origin||!url.pathname.startsWith('/api/dashboard/'))return null;
    const heavy=/\/(?:audit|evidence|free|strategy|research)(?:\/|$)/.test(url.pathname);
    return {url,timeout:heavy?15000:8000};
  };
  const markVerified=()=>{
    const label=document.getElementById('ytStatus');
    const badge=document.getElementById('profileConnectionBadge');
    if(label)label.textContent='Conectado · leitura verificada';
    if(badge)badge.className='pill good';
  };
  window.addEventListener('yca:youtube-read-verified',markVerified);
  window.fetch=async function(input,init={}){
    const policy=classify(input,init);
    if(!policy)return baseFetch(input,init);
    const controller=new AbortController();
    const upstream=init&&init.signal;
    if(upstream){
      if(upstream.aborted)controller.abort(upstream.reason);
      else upstream.addEventListener('abort',()=>controller.abort(upstream.reason),{once:true});
    }
    const timer=setTimeout(()=>controller.abort('dashboard-read-timeout'),policy.timeout);
    try{
      const response=await baseFetch(input,{...init,signal:controller.signal});
      if(response.ok&&policy.url.pathname==='/api/dashboard/channel/identity'){
        window.dispatchEvent(new Event('yca:youtube-read-verified'));
      }
      return response;
    }catch(err){
      if(controller.signal.aborted&&!upstream?.aborted){
        const seconds=Math.round(policy.timeout/1000);
        const timeoutError=new Error(`A leitura excedeu ${seconds}s. Esta área falhou sem bloquear o restante do painel; tente novamente.`);
        timeoutError.name='DashboardReadTimeout';
        throw timeoutError;
      }
      throw err;
    }finally{
      clearTimeout(timer);
    }
  };
})();
</script>
'''


_FAST_BOOT = r'''
async function ycaInitialLoad(){
  placePlaylistsOnOverview();
  void Promise.allSettled([
    loadStatus(),
    loadChannelIdentity(),
    loadChannels(),
    loadCapabilities()
  ]);
  setTimeout(()=>{
    void Promise.allSettled([
      loadPlaylists(),
      loadVideos(),
      loadChannel()
    ]);
  },80);
}
ycaInitialLoad();
'''

_SESSION_REDIRECT_OLD = "if(r.status===401){location.href='/onboarding/session-expired';throw new Error('Sessão expirada')}"
_SESSION_REDIRECT_NEW = "if(r.status===401){if(!window.__ycaSessionRedirecting){window.__ycaSessionRedirecting=true;setTimeout(()=>location.replace('/onboarding/session-expired'),0)}throw new Error('Sessão expirada')}"
_CONNECTION_LABEL_OLD = "if(label)label.textContent=s.youtube_connected?'Conectado':'Desconectado';"
_CONNECTION_LABEL_NEW = "if(label)label.textContent=s.youtube_connected?'Credencial disponível':'Desconectado';"
_LEGACY_AI_VAULT_AUTOLOAD = "setTimeout(loadAiKeyPool,150);"


def _apply_fast_boot_policy(source: str) -> str:
    """Remove passive duplicate/heavy boot work while preserving explicit actions."""
    source = source.replace(_SESSION_REDIRECT_OLD, _SESSION_REDIRECT_NEW, 1)
    source = source.replace(_CONNECTION_LABEL_OLD, _CONNECTION_LABEL_NEW, 1)
    # AI vault v2 owns its own bounded initial read. The legacy injected manager
    # remains available for explicit controls but must not perform a second GET.
    source = source.replace(_LEGACY_AI_VAULT_AUTOLOAD, "", 1)
    marker = "refreshAll();\n</script>"
    if marker in source:
        source = source.replace(marker, _FAST_BOOT + "\n</script>", 1)
    return source


def install_dashboard_stability_guard(app: FastAPI) -> None:
    """Bound dashboard reads and make startup independent and recoverable.

    Only same-origin dashboard GETs are wrapped. Writes are never intercepted,
    no external AI is invoked, and no automatic YouTube health probe is issued.
    """
    if getattr(app.state, "dashboard_stability_guard_installed", False):
        return
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
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-type", None)
        source = _apply_fast_boot_policy(response.body.decode("utf-8"))
        if "data-yca-stability-guard" not in source:
            source = source.replace("</head>", _HEAD_SCRIPT + "\n</head>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_stability_guard")
    app.state.dashboard_stability_guard_installed = True
