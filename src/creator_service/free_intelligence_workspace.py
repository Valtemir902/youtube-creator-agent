from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_CSS = r'''
<style data-yca-free-workspace>
.free-lab{display:grid;gap:12px}.free-lab-head{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}.free-lab-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.free-lab-kpi{border:1px solid var(--line);border-radius:12px;padding:10px;background:var(--card2)}.free-lab-kpi strong{display:block;font-size:20px}.free-bars{display:grid;gap:8px}.free-bar-row{display:grid;grid-template-columns:minmax(100px,1.4fr) 2fr auto;gap:8px;align-items:center}.free-bar-track{height:9px;background:var(--bg);border:1px solid var(--line);border-radius:99px;overflow:hidden}.free-bar-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:99px}.free-tags{display:flex;gap:6px;flex-wrap:wrap}.free-mini{font-size:12px;color:var(--muted)}.free-output{display:grid;gap:10px}.free-plan-card{border:1px solid var(--line);border-radius:12px;padding:11px;background:var(--card2)}@media(max-width:760px){.free-lab-grid{grid-template-columns:1fr 1fr}.free-bar-row{grid-template-columns:1fr}.free-bar-track{height:8px}}
</style>
'''

_SCRIPT = r'''
<script data-yca-free-workspace>
(()=>{
 if(window.__ycaFreeWorkspace)return;window.__ycaFreeWorkspace=true;
 const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
 const pct=v=>v==null?'—':`${Number(v).toFixed(2)}%`;
 const get=async url=>{const r=await fetch(url,{credentials:'same-origin',headers:{Accept:'application/json'}});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);return d};
 const bars=rows=>(rows||[]).slice(0,10).map(x=>`<div class="free-bar-row"><span title="${esc(x.keyword)}">${esc(x.keyword)}</span><div><div class="free-mini">Demanda ${esc(x.demand)} · Concorrência ${esc(x.competition)} · Tendência ${esc(x.trend)}</div><div class="free-bar-track"><div class="free-bar-fill" style="width:${Math.max(0,Math.min(100,Number(x.opportunity||0)))}%"></div></div></div><b>${esc(x.opportunity||0)}</b></div>`).join('');
 const tags=rows=>(rows||[]).slice(0,12).map(x=>`<span class="pill">${esc(x.keyword||x)}</span>`).join('');
 function installCards(){
   const videos=document.querySelector('#videos .grid');
   if(videos&&!document.getElementById('freeVideoLab')){
     const card=document.createElement('article');card.className='card full';card.id='freeVideoLab';card.innerHTML=`<div class="free-lab"><div class="free-lab-head"><div><h3 style="margin:0">Motor gratuito avançado</h3><div class="muted">SEO, keywords, playlist, retenção e CTR oficial sem IA externa.</div></div><button class="btn primary" id="runFreeVideoLab">Analisar vídeo selecionado sem IA</button></div><div id="freeVideoLabOut" class="notice">Selecione um vídeo e execute a análise.</div></div>`;videos.appendChild(card);
   }
   const strategy=document.querySelector('#strategy .grid');
   if(strategy&&!document.getElementById('freeChannelLab')){
     const card=document.createElement('article');card.className='card full';card.id='freeChannelLab';card.innerHTML=`<div class="free-lab"><div class="free-lab-head"><div><h3 style="margin:0">Inteligência determinística do canal</h3><div class="muted">Histórico, perfil, catálogo e janelas de publicação com dados do próprio canal.</div></div><button class="btn" id="runFreeChannelLab">Atualizar inteligência gratuita</button></div><div id="freeChannelLabOut" class="notice">Aguardando análise.</div></div>`;strategy.appendChild(card);
   }
 }
 async function runVideo(){
   const id=(document.getElementById('videoId')?.value||'').trim(),out=document.getElementById('freeVideoLabOut');if(!id){out.textContent='Selecione um vídeo primeiro.';return}out.innerHTML='<span class="loader"></span> Cruzando transcrição, pesquisas, playlists e métricas oficiais…';
   try{
     const [plan,perf]=await Promise.all([get(`/api/dashboard/free/video/${encodeURIComponent(id)}/optimization`),get(`/api/dashboard/free/video/${encodeURIComponent(id)}/performance`)]);
     const kw=plan.keyword_intelligence||{}, reach=perf.reach||{}, retention=perf.retention||{}, pm=plan.playlist_match||{}, cat=plan.category_suggestion||{};
     out.innerHTML=`<div class="free-output"><div class="free-lab-grid"><div class="free-lab-kpi"><span class="free-mini">SEO atual</span><strong>${esc(plan.baseline_score??'—')}/100</strong></div><div class="free-lab-kpi"><span class="free-mini">SEO projetado</span><strong>${esc(plan.projected_score??'—')}/100</strong></div><div class="free-lab-kpi"><span class="free-mini">CTR oficial</span><strong>${reach.ctr_percent==null?'—':pct(reach.ctr_percent)}</strong></div><div class="free-lab-kpi"><span class="free-mini">Retenção</span><strong>${retention.retention_score??'—'}/100</strong></div></div><div class="free-plan-card"><b>Keywords positivas</b><div class="free-tags" style="margin-top:7px">${tags(kw.positive_keywords)||'<span class="muted">Sem evidência suficiente.</span>'}</div></div><div class="free-plan-card"><b>Evitar / negativas</b><div class="free-tags" style="margin-top:7px">${tags(kw.negative_keywords)||'<span class="muted">Nenhuma sinalizada.</span>'}</div></div><div class="free-plan-card"><b>Demanda × concorrência</b><div class="free-bars" style="margin-top:8px">${bars(kw.charts?.demand_vs_competition)||'<span class="muted">Sem pesquisa medida.</span>'}</div></div><div class="free-plan-card"><b>Proposta</b><div class="free-mini">Título: ${esc(plan.proposed?.title||'sem alteração')}</div><div class="free-mini">Playlist: ${esc(pm.recommended_playlist?.title||'sem recomendação')}</div><div class="free-mini">Categoria: ${cat.suggestion_ready?esc(cat.suggested_category_id):'preservar atual'}</div><div class="free-mini">Thumbnail: ${esc(perf.thumbnail_recommendation||'')}</div></div><details><summary class="muted">Evidência técnica completa</summary><pre class="code">${esc(JSON.stringify({plan,performance:perf},null,2))}</pre></details></div>`;
   }catch(e){out.textContent=`Falha na análise gratuita: ${e.message}`}
 }
 async function runChannel(){
   const out=document.getElementById('freeChannelLabOut');out.innerHTML='<span class="loader"></span> Comparando histórico e perfil do canal…';
   try{
     const [profile,trend,pub,catalog]=await Promise.all([get('/api/dashboard/free/channel/optimization'),get('/api/dashboard/free/channel/trend'),get('/api/dashboard/free/channel/publication-strategy'),get('/api/dashboard/free/catalog-opportunities')]);
     const windows=(pub.best_windows||[]).map(x=>`dia ${x.weekday}, ${String(x.hour_start).padStart(2,'0')}:00–${String(x.hour_end).padStart(2,'0')}:00`).join(' · ');
     out.innerHTML=`<div class="free-output"><div class="free-lab-grid"><div class="free-lab-kpi"><span class="free-mini">Momento</span><strong>${esc(trend.momentum_score??'—')}/100</strong></div><div class="free-lab-kpi"><span class="free-mini">Perfil</span><strong>${esc(profile.confidence??'—')}%</strong></div><div class="free-lab-kpi"><span class="free-mini">Oportunidades</span><strong>${(catalog.opportunities||[]).length}</strong></div><div class="free-lab-kpi"><span class="free-mini">Amostra horários</span><strong>${esc(pub.sample_size??0)}</strong></div></div><div class="free-plan-card"><b>Perfil do canal</b><div class="free-mini">${profile.optimization_ready?'Existe proposta baseada em termos observados.':'Nenhuma mudança segura recomendada.'}</div><div class="free-tags" style="margin-top:7px">${(profile.evidence_terms||[]).map(x=>`<span class="pill">${esc(x)}</span>`).join('')}</div></div><div class="free-plan-card"><b>Melhores janelas observadas</b><div class="free-mini">${esc(windows||pub.blocked_reason||'Sem amostra suficiente.')}</div></div><details><summary class="muted">Evidência técnica completa</summary><pre class="code">${esc(JSON.stringify({profile,trend,publication:pub,catalog},null,2))}</pre></details></div>`;
   }catch(e){out.textContent=`Falha na inteligência do canal: ${e.message}`}
 }
 function bind(){installCards();document.getElementById('runFreeVideoLab')?.addEventListener('click',runVideo);document.getElementById('runFreeChannelLab')?.addEventListener('click',runChannel)}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();
</script>
'''


def install_free_intelligence_workspace(app: FastAPI) -> None:
    if getattr(app.state, "free_intelligence_workspace_installed", False):
        return
    route = next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/dashboard" and "GET" in (r.methods or set()))
    original = route.endpoint
    app.router.routes.remove(route)

    async def dashboard(request: Request):
        response = await original(request)
        if not isinstance(response, HTMLResponse):
            return response
        headers = dict(response.headers);headers.pop("content-length",None);headers.pop("content-type",None)
        source=response.body.decode("utf-8")
        if "data-yca-free-workspace" not in source:
            source=source.replace("</head>",_CSS+"\n</head>",1).replace("</body>",_SCRIPT+"\n</body>",1)
        return HTMLResponse(source,status_code=response.status_code,headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_free_workspace")
    app.state.free_intelligence_workspace_installed = True
