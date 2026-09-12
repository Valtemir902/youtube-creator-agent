from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_SCRIPT = r'''
<script data-yca-native-first-policy>
(()=>{
  if(window.__ycaNativeFirstPolicy)return;window.__ycaNativeFirstPolicy=true;
  const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const apiGet=async url=>{const r=await fetch(url,{credentials:'same-origin',headers:{Accept:'application/json'}});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);return d};
  let lastStatus=null;
  function apply(status){
    const badge=document.getElementById('proAiBadge');
    if(badge){
      const optional=status?.external_ai_configured
        ? `<span class="pill">IA externa sob demanda · ${esc(status.ai_provider||'provedor')} / ${esc(status.ai_model||'modelo')}</span>`
        : '<span class="pill">IA externa opcional · não configurada</span>';
      badge.innerHTML=`<span class="pill good">◆ Inteligência Nativa ativa</span><span class="pill">motor Python · dados reais</span>${optional}`;
      badge.dataset.nativeFirst='1';
    }
    const head=document.getElementById('proDashboardHead');
    if(head){
      const subtitle=head.querySelector('.toolbar .muted');
      if(subtitle)subtitle.textContent='Resumo executivo calculado pelo motor nativo com dados atuais do YouTube';
      if(!head.querySelector('[data-native-first-note]')){
        const note=document.createElement('div');
        note.dataset.nativeFirstNote='1';
        note.className='muted';
        note.style.fontSize='12px';
        note.textContent='Esta verificação não consome API de IA externa. Gemini/OpenAI/Groq/xAI só são chamados quando você inicia uma ação de IA.';
        head.appendChild(note);
      }
    }
  }
  async function refresh(){
    try{lastStatus=await apiGet('/api/dashboard/status')}catch{}
    apply(lastStatus);
  }
  function settle(){apply(lastStatus);clearTimeout(window.__ycaNativeFirstSettle);window.__ycaNativeFirstSettle=setTimeout(()=>apply(lastStatus),80)}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{refresh();setTimeout(settle,250);setTimeout(settle,900)},{once:true});
  else{refresh();setTimeout(settle,250);setTimeout(settle,900)}
  new MutationObserver(settle).observe(document.documentElement,{childList:true,subtree:true});
})();
</script>
'''


def install_dashboard_native_first_policy(app: FastAPI) -> None:
    if getattr(app.state, "dashboard_native_first_policy_installed", False):
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
        source = response.body.decode("utf-8")
        if "data-yca-native-first-policy" not in source:
            source = source.replace("</body>", _SCRIPT + "\n</body>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_native_first_policy")
    app.state.dashboard_native_first_policy_installed = True
