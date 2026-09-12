from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_CSS = r'''
<style data-yca-activity-ux>
.native-work-toast{position:fixed;left:50%;top:calc(env(safe-area-inset-top) + 78px);transform:translateX(-50%);z-index:115;width:min(620px,calc(100% - 28px));border:1px solid color-mix(in srgb,var(--accent) 42%,var(--line));border-radius:16px;background:color-mix(in srgb,var(--panel) 96%,transparent);box-shadow:0 18px 50px #0009;backdrop-filter:blur(12px);padding:10px 12px;display:none}.native-work-toast.active{display:block}.native-work-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.native-work-title{display:flex;align-items:center;gap:9px;font-weight:850}.native-work-spinner{width:16px;height:16px;border:2px solid color-mix(in srgb,var(--accent) 25%,transparent);border-top-color:var(--accent);border-radius:50%;animation:native-spin .8s linear infinite}.native-work-count{font-size:12px;color:var(--muted)}.native-work-list{display:grid;gap:5px;margin-top:7px}.native-work-row{display:grid;grid-template-columns:auto 1fr auto;gap:8px;align-items:center;font-size:13px}.native-work-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 14%,transparent)}.native-work-row.done .native-work-dot{background:var(--good)}.native-work-row.failed .native-work-dot{background:#ff5e75}.native-work-kind{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 6px}.native-work-time{color:var(--muted);font-variant-numeric:tabular-nums}.native-work-progress{height:3px;background:color-mix(in srgb,var(--line) 65%,transparent);border-radius:999px;overflow:hidden;margin-top:9px}.native-work-progress>i{display:block;height:100%;width:38%;background:linear-gradient(90deg,var(--accent),#f7a300);border-radius:999px;animation:native-sweep 1.25s ease-in-out infinite}.native-inline-status{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;margin-top:7px}.native-inline-status .native-work-spinner{width:12px;height:12px}.native-route-badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:4px 8px;font-size:11px;color:var(--muted);margin-left:6px}@keyframes native-spin{to{transform:rotate(360deg)}}@keyframes native-sweep{0%{transform:translateX(-120%)}50%{transform:translateX(130%)}100%{transform:translateX(300%)}}@media(max-width:760px){.native-work-toast{top:calc(env(safe-area-inset-top) + 69px);width:calc(100% - 20px);padding:9px 10px}.native-work-row{font-size:12px}}
</style>
'''

_SCRIPT = r'''
<script data-yca-activity-ux>
(()=>{
 if(window.__ycaActivityUx)return;window.__ycaActivityUx=true;
 const nativeFetch=window.fetch.bind(window);
 const jobs=new Map();let serial=0,timer=null,hideTimer=null;
 const matchers=[
  [/\/api\/dashboard\/videos(?:\?|$)/,'Buscando vídeos e miniaturas no YouTube','Nativa'],
  [/\/api\/dashboard\/channel(?:\?|$)/,'Atualizando desempenho e Analytics do canal','Nativa'],
  [/\/api\/dashboard\/channel\/identity/,'Confirmando a identidade do canal conectado','Nativa'],
  [/\/api\/dashboard\/playlists(?:\?|$)/,'Carregando playlists do canal','Nativa'],
  [/\/api\/dashboard\/free\/channel\/trend/,'Comparando histórico e tendência do canal','Nativa'],
  [/\/api\/dashboard\/free\/channel\/publication-strategy/,'Calculando melhores janelas de publicação','Nativa'],
  [/\/api\/dashboard\/free\/channel(?:\?|$)/,'Calculando score e diagnóstico do canal','Nativa'],
  [/\/api\/dashboard\/free\/action-plan/,'Priorizando oportunidades com dados reais','Nativa'],
  [/\/api\/dashboard\/free\/catalog-opportunities/,'Procurando oportunidades no catálogo','Nativa'],
  [/\/api\/dashboard\/free\/video\/[^/]+\/retention/,'Lendo curva de retenção e abandono','Nativa'],
  [/\/api\/dashboard\/free\/video\/[^/]+\/reach/,'Consultando impressões e CTR oficial','Nativa'],
  [/\/api\/dashboard\/free\/video\/[^/]+\/performance/,'Comparando desempenho do vídeo','Nativa'],
  [/\/api\/dashboard\/free\/video\/[^/]+\/optimization/,'Montando plano de SEO determinístico','Nativa'],
  [/\/api\/dashboard\/free\/video\//,'Analisando conteúdo, SEO e sinais do vídeo','Nativa'],
  [/\/api\/dashboard\/audit/,'Coletando fatos para a auditoria','Nativa'],
  [/\/api\/dashboard\/keywords\/validate/,'Validando palavras-chave com dados reais','Nativa'],
  [/\/api\/dashboard\/research\/topic/,'Pesquisando oportunidades recentes','Premium'],
  [/\/api\/dashboard\/strategy\/build/,'IA Premium interpretando evidências do canal','Premium'],
  [/\/ai-optimize/,'IA Premium preparando uma proposta','Premium'],
  [/\/api\/dashboard\/upload\/analyze/,'Transcrevendo e analisando o vídeo enviado','Nativa + Premium']
 ];
 function spec(url){for(const [re,label,kind] of matchers){if(re.test(url))return{label,kind}}return null}
 function ensureToast(){let box=document.getElementById('nativeWorkToast');if(box)return box;box=document.createElement('aside');box.id='nativeWorkToast';box.className='native-work-toast';box.setAttribute('aria-live','polite');box.innerHTML='<div class="native-work-head"><div class="native-work-title"><span class="native-work-spinner"></span><span>Processando dados</span></div><span class="native-work-count"></span></div><div class="native-work-list"></div><div class="native-work-progress"><i></i></div>';document.body.appendChild(box);return box}
 function elapsed(ms){const s=Math.max(0,Math.round(ms/1000));return s<60?`${s}s`:`${Math.floor(s/60)}m ${s%60}s`}
 function render(){const box=ensureToast(),list=box.querySelector('.native-work-list'),count=box.querySelector('.native-work-count');const active=[...jobs.values()].filter(j=>j.state==='active');const recent=[...jobs.values()].filter(j=>j.state!=='active'&&Date.now()-j.finished<1400);const visible=[...active,...recent].slice(-4);if(!visible.length){box.classList.remove('active');return}box.classList.add('active');count.textContent=active.length?`${active.length} etapa${active.length>1?'s':''} em andamento`:'Atualização concluída';list.innerHTML=visible.map(j=>`<div class="native-work-row ${j.state==='active'?'':j.state}"><span class="native-work-dot"></span><span>${j.label}<span class="native-route-badge">${j.kind}</span></span><span class="native-work-time">${j.state==='active'?elapsed(Date.now()-j.started):(j.state==='done'?'✓':'!')}</span></div>`).join('');clearTimeout(hideTimer);if(!active.length)hideTimer=setTimeout(()=>{box.classList.remove('active')},1450)}
 function tick(){render();if([...jobs.values()].some(j=>j.state==='active'))timer=setTimeout(tick,500);else timer=null}
 function start(label,kind){const id=++serial;jobs.set(id,{id,label,kind,state:'active',started:Date.now(),finished:0});if(!timer)tick();return id}
 function finish(id,state){const j=jobs.get(id);if(!j)return;j.state=state;j.finished=Date.now();render();setTimeout(()=>{jobs.delete(id);render()},1600)}
 window.fetch=async function(input,init){const url=typeof input==='string'?input:String(input?.url||'');const cfg=spec(url);if(!cfg)return nativeFetch(input,init);const id=start(cfg.label,cfg.kind);try{const response=await nativeFetch(input,init);finish(id,response.ok?'done':'failed');return response}catch(err){finish(id,'failed');throw err}};
 function markButtons(){
  const labels=[['runFreeVideoLab','Inteligência Nativa'],['runFreeChannelLab','Inteligência Nativa']];for(const [id,text] of labels){const b=document.getElementById(id);if(b&&!b.dataset.routeBadge){b.dataset.routeBadge='1';const s=document.createElement('span');s.className='native-route-badge';s.textContent=text;b.appendChild(s)}}
  document.querySelectorAll('button').forEach(b=>{const t=(b.textContent||'').trim();if(b.dataset.engineLabeled)return;if(/Construir|Mapear oportunidades|SEO com IA|IA\b/.test(t)){b.dataset.engineLabeled='1';b.title='Usa IA externa Premium quando configurada.'}})
 }
 function annotateSlowPlaceholders(){
  document.querySelectorAll('.muted, .notice, p, div').forEach(n=>{if(n.children.length>0)return;const t=(n.textContent||'').trim();if(!/^Carregando |^Construindo/.test(t)||n.dataset.nativeProgress)return;n.dataset.nativeProgress='1';n.classList.add('native-inline-status');n.innerHTML='<span class="native-work-spinner"></span><span>'+t+'</span>'})
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{markButtons();annotateSlowPlaceholders()},{once:true});else{markButtons();annotateSlowPlaceholders()}
 new MutationObserver(()=>{clearTimeout(window.__ycaActivitySettle);window.__ycaActivitySettle=setTimeout(()=>{markButtons();annotateSlowPlaceholders()},80)}).observe(document.documentElement,{childList:true,subtree:true});
})();
</script>
'''


def install_dashboard_activity_ux(app: FastAPI) -> None:
    if getattr(app.state, "dashboard_activity_ux_installed", False):
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
        if "data-yca-activity-ux" not in source:
            source = source.replace("</head>", _CSS + "\n</head>", 1).replace("</body>", _SCRIPT + "\n</body>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_activity_ux")
    app.state.dashboard_activity_ux_installed = True
