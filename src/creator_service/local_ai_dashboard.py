from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


LOCAL_AI_INSTALLER_URL = (
    "https://github.com/Valtemir902/youtube-creator-agent/releases/download/"
    "local-ai-v1.0.0/YCA-Local-AI-Setup.exe"
)

_CSS = r'''
<style data-yca-local-ai>
.local-ai-card{display:grid;gap:10px}.local-ai-status{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.local-ai-dot{width:10px;height:10px;border-radius:50%;background:var(--muted)}.local-ai-dot.ready{background:var(--good);box-shadow:0 0 0 5px color-mix(in srgb,var(--good) 15%,transparent)}.local-ai-dot.wait{background:#f7a300}.local-ai-dot.off{background:#ff5e75}.local-ai-actions{display:flex;gap:8px;flex-wrap:wrap}.local-ai-meta{display:grid;grid-template-columns:1fr 1fr;gap:7px}.local-ai-meta>div{border:1px solid var(--line);border-radius:11px;padding:9px;background:var(--card2)}.local-ai-meta small{display:block;color:var(--muted);font-size:11px}.local-ai-meta b{display:block;margin-top:2px}.local-ai-result{border:1px solid color-mix(in srgb,var(--good) 38%,var(--line));background:color-mix(in srgb,var(--good) 5%,var(--card2));border-radius:12px;padding:11px;white-space:pre-wrap}.local-ai-install-note{font-size:12px;color:var(--muted)}.local-ai-btn{display:none}.local-ai-btn.available{display:inline-flex}.local-ai-progress{margin-top:10px;display:grid;gap:6px}.local-ai-progress-track{height:9px;border-radius:999px;background:color-mix(in srgb,var(--line) 72%,transparent);overflow:hidden}.local-ai-progress-fill{height:100%;border-radius:inherit;background:linear-gradient(90deg,#22c1dc,#7758f6);transition:width .25s ease}.local-ai-progress-copy{display:flex;justify-content:space-between;gap:12px;font-size:12px;color:var(--muted)}@media(max-width:760px){.local-ai-meta{grid-template-columns:1fr}.local-ai-actions .btn{width:100%;justify-content:center}.local-ai-progress-copy{display:grid;gap:2px}}
</style>
'''

_SCRIPT_TEMPLATE = r'''
<script data-yca-local-ai>
(()=>{
 if(window.__ycaLocalAiUi)return;window.__ycaLocalAiUi=true;
 const INSTALLER_URL=__INSTALLER_URL__;
 const BASE='http://127.0.0.1:17823';
 const evidence={video:{},channel:{}};let state={connected:false,ready:false,capabilities:null,install:null,error:null};let installTimer=null;
 const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
 function token(){return localStorage.getItem('yca_local_ai_token')||''}
 function consumePairToken(){const h=location.hash||'';const m=h.match(/(?:^#|[&#])local-ai-token=([^&]+)/);if(!m)return;const value=decodeURIComponent(m[1]);if(value&&value.length>20)localStorage.setItem('yca_local_ai_token',value);history.replaceState(null,'',location.pathname+location.search)}
 async function localFetch(path,opts={}){const headers={...(opts.headers||{})};if(token())headers.Authorization=`Bearer ${token()}`;headers['Content-Type']='application/json';const ctl=new AbortController();const tm=setTimeout(()=>ctl.abort(),opts.timeout||5000);try{return await fetch(BASE+path,{...opts,headers,signal:ctl.signal,mode:'cors'})}finally{clearTimeout(tm)}}
 function scheduleInstallPoll(){clearTimeout(installTimer);if(state.install?.status==='running')installTimer=setTimeout(refresh,1500)}
 async function refresh(){consumePairToken();state.error=null;try{const health=await localFetch('/v1/health',{timeout:1200});if(!health.ok)throw new Error('bridge_unhealthy');state.connected=true;try{const ir=await localFetch('/v1/install-status',{timeout:1200});if(ir.ok)state.install=await ir.json()}catch{}if(state.install?.status==='running'){state.ready=false;state.error='installing';render();scheduleInstallPoll();return state}if(!token()){state.ready=false;state.error='pairing_required';render();return state}const r=await localFetch('/v1/capabilities',{timeout:3500});if(!r.ok)throw new Error(`HTTP ${r.status}`);const d=await r.json();state.capabilities=d;state.install=d.install_state||state.install;state.ready=!!(d.supported&&d.ollama_ready&&d.model_ready);state.error=state.ready?null:(d.supported?'model_not_ready':'hardware_not_supported')}catch(e){state={connected:false,ready:false,capabilities:null,install:null,error:e.name==='AbortError'?'bridge_timeout':'bridge_unavailable'}}render();scheduleInstallPoll();return state}
 async function chat(messages,{temperature=.2,max_output_tokens=700}={}){if(!state.ready)await refresh();if(!state.ready)throw new Error('IA Local não está pronta neste dispositivo.');const r=await localFetch('/v1/chat',{method:'POST',body:JSON.stringify({messages,temperature,max_output_tokens}),timeout:180000});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.detail||d.error||`HTTP ${r.status}`);return d}
 function installCard(){const settings=document.getElementById('settings');if(!settings||document.getElementById('localAiSettings'))return;const grid=settings.querySelector('.settings-grid')||settings;const card=document.createElement('article');card.className='card full local-ai-card';card.id='localAiSettings';card.innerHTML='<div><h3 style="margin:0">IA Local</h3><div class="muted">Roda no próprio notebook quando o hardware é compatível. A Inteligência Nativa continua sendo a fonte dos dados reais.</div></div><div id="localAiStatus"></div>';grid.prepend(card)}
 function installDrawerRow(){const list=document.querySelector('#nativeSettingsOverlay .native-setting-list');if(!list||list.querySelector('[data-settings-target="localAiSettings"]'))return;const row=document.createElement('button');row.className='native-setting-row';row.dataset.settingsTarget='localAiSettings';row.innerHTML='<span>IA Local</span><small>GPU e modelo no dispositivo</small>';const external=[...list.querySelectorAll('.native-setting-row')].find(x=>(x.textContent||'').includes('IA externa'));if(external)list.insertBefore(row,external);else list.insertBefore(row,list.lastElementChild)}
 function platformEligible(){const ua=navigator.userAgent||'';return /Windows/i.test(ua)&&!/Android|Mobile/i.test(ua)}
 function progressHtml(){const i=state.install||{};if(i.status!=='running')return'';const pct=Number.isFinite(Number(i.percent))?Math.max(0,Math.min(Number(i.percent),100)):0;const size=i.estimated_download_mb?`Modelo ~${Number(i.estimated_download_mb).toLocaleString('pt-BR')} MB`:'Preparando componentes';return `<div class="local-ai-progress"><div class="local-ai-progress-track"><div class="local-ai-progress-fill" style="width:${pct}%"></div></div><div class="local-ai-progress-copy"><span>${esc(i.detail||'Instalando IA Local…')}</span><b>${pct}% · ${esc(size)}</b></div></div>`}
 function render(){installCard();installDrawerRow();const out=document.getElementById('localAiStatus');if(!out)return;const c=state.capabilities||{};const hw=c.hardware||{};let label='Não detectada',dot='wait',detail='Verificando o serviço local…';if(state.error==='installing'){label='Instalando';dot='wait';detail='O runtime e o modelo estão sendo preparados neste notebook.'}else if(state.ready){label='Ativa neste dispositivo';dot='ready';detail=`${c.model_display_name||c.model||'modelo local'} · ${hw.gpu_name||'GPU local'}`}else if(state.connected&&state.error==='hardware_not_supported'){label='Desativada neste dispositivo';dot='off';detail='A Inteligência Nativa continuará funcionando normalmente.'}else if(state.connected){label='Instalação incompleta';dot='wait';detail=c.repair_needed?'Runtime ou modelo local precisa de reparo.':'O serviço local respondeu, mas o modelo ainda não está pronto.'}else{label='Não instalada';dot='wait';detail=platformEligible()?'Instale uma vez. O sistema detecta GPU, escolhe e baixa o modelo automaticamente.':'IA Local fica oculta em celulares/dispositivos não compatíveis.'}const profile=c.profile||'—',vram=hw.vram_mb?`${Math.round(hw.vram_mb/1024)} GB`:'—',modelSize=c.model_estimated_download_mb?`~${Number(c.model_estimated_download_mb).toLocaleString('pt-BR')} MB`:'—';out.innerHTML=`<div class="local-ai-status"><span class="local-ai-dot ${dot}"></span><b>${esc(label)}</b><span class="pill">${esc(profile)}</span></div><div class="muted" style="margin-top:7px">${esc(detail)}</div>${progressHtml()}${c.hardware?`<div class="local-ai-meta" style="margin-top:9px"><div><small>GPU</small><b>${esc(hw.gpu_name||'Não detectada')}</b></div><div><small>VRAM</small><b>${esc(vram)}</b></div><div><small>Modelo</small><b>${esc(c.model||'Nenhum')}</b></div><div><small>Tamanho estimado</small><b>${esc(modelSize)}</b></div><div><small>Runtime</small><b>${c.ollama_ready?'Ollama pronto':'Aguardando'}</b></div><div><small>Manifesto</small><b>${esc(c.manifest_version||'—')}</b></div></div>`:''}<div class="local-ai-actions" style="margin-top:10px">${!state.ready&&state.error!=='installing'&&platformEligible()?`<a class="btn primary" href="${INSTALLER_URL}">Instalar IA Local</a>`:''}<button class="btn" id="localAiRecheck">Reavaliar dispositivo</button></div><div class="local-ai-install-note">Nenhum modelo grande fica no servidor do Creator Agent. O download e a inferência acontecem no notebook.</div>`;document.getElementById('localAiRecheck')?.addEventListener('click',refresh);updateActionButtons()}
 function updateActionButtons(){document.querySelectorAll('.local-ai-btn').forEach(b=>b.classList.toggle('available',state.ready))}
 function capture(url,data){if(/\/free\/video\/[^/]+\/optimization/.test(url))evidence.video.optimization=data;else if(/\/free\/video\/[^/]+\/performance/.test(url))evidence.video.performance=data;else if(/\/free\/channel\/optimization/.test(url))evidence.channel.profile=data;else if(/\/free\/channel\/trend/.test(url))evidence.channel.trend=data;else if(/\/free\/channel\/publication-strategy/.test(url))evidence.channel.publication=data;else if(/\/free\/catalog-opportunities/.test(url))evidence.channel.catalog=data;setTimeout(installContextButtons,40)}
 const previousFetch=window.fetch.bind(window);window.fetch=async function(input,init){const url=typeof input==='string'?input:String(input?.url||'');const r=await previousFetch(input,init);if(r.ok&&/\/api\/dashboard\/free\//.test(url)){r.clone().json().then(d=>capture(url,d)).catch(()=>{})}return r};
 function installContextButtons(){const video=document.getElementById('freeVideoLab');if(video&&!video.querySelector('#localAiVideoImprove')){const b=document.createElement('button');b.id='localAiVideoImprove';b.className='btn local-ai-btn';b.textContent='Aprimorar com IA Local';b.onclick=()=>improve('video');video.querySelector('.free-lab-head')?.appendChild(b)}const channel=document.getElementById('freeChannelLab');if(channel&&!channel.querySelector('#localAiChannelImprove')){const b=document.createElement('button');b.id='localAiChannelImprove';b.className='btn local-ai-btn';b.textContent='Interpretar com IA Local';b.onclick=()=>improve('channel');channel.querySelector('.free-lab-head')?.appendChild(b)}updateActionButtons()}
 async function improve(kind){const data=evidence[kind];const out=document.getElementById(kind==='video'?'freeVideoLabOut':'freeChannelLabOut');if(!out)return;const existing=out.querySelector('.local-ai-result');if(existing)existing.remove();const box=document.createElement('div');box.className='local-ai-result';box.textContent='IA Local interpretando as evidências no seu dispositivo…';out.appendChild(box);try{const facts=JSON.stringify(data).slice(0,45000);const system='Você é a camada local de linguagem do YouTube Creator Agent. Use SOMENTE os fatos fornecidos pela Inteligência Nativa. Não invente métricas, volume de busca, CTR, retenção ou resultados. Seja objetivo, explique prioridades e escreva em português do Brasil.';const task=kind==='video'?'Interprete a análise deste vídeo e proponha até 3 melhorias de título/descrição somente quando sustentadas pelas evidências.':'Interprete o diagnóstico do canal e explique as 3 prioridades mais importantes, sempre citando a evidência fornecida.';const d=await chat([{role:'system',content:system},{role:'user',content:`${task}\n\nEVIDÊNCIAS NATIVAS:\n${facts}`}]);box.textContent=d.text}catch(e){box.textContent=`IA Local indisponível agora. A análise nativa continua válida. ${e.message}`}}
 window.ycaLocalAI={refresh,chat,get state(){return state},evidence};
 function boot(){consumePairToken();installCard();installDrawerRow();installContextButtons();refresh()}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
 new MutationObserver(()=>{clearTimeout(window.__ycaLocalSettle);window.__ycaLocalSettle=setTimeout(()=>{installCard();installDrawerRow();installContextButtons()},100)}).observe(document.documentElement,{childList:true,subtree:true});
})();
</script>
'''

_SCRIPT = _SCRIPT_TEMPLATE.replace("__INSTALLER_URL__", repr(LOCAL_AI_INSTALLER_URL))


def install_local_ai_dashboard(app: FastAPI) -> None:
    if getattr(app.state, "local_ai_dashboard_installed", False):
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
        if "data-yca-local-ai" not in source:
            source = source.replace("</head>", _CSS + "\n</head>", 1).replace("</body>", _SCRIPT + "\n</body>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_local_ai")
    app.state.local_ai_dashboard_installed = True
