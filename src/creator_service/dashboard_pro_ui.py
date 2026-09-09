from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_CSS = r'''
<style data-yca-pro-dashboard>
:root{--pro-radius:18px;--pro-soft:color-mix(in srgb,var(--card2) 92%,transparent)}
body{background:radial-gradient(circle at 80% 0,color-mix(in srgb,var(--accent2) 10%,transparent),transparent 28%),radial-gradient(circle at 8% 8%,color-mix(in srgb,var(--accent) 8%,transparent),transparent 24%),var(--bg)}
.sidebar{background:linear-gradient(180deg,color-mix(in srgb,var(--panel) 98%,#05070c),color-mix(in srgb,var(--panel) 94%,#05070c));box-shadow:12px 0 38px #0004}
.brand .logo{background:linear-gradient(145deg,color-mix(in srgb,#ff2e45 82%,var(--card)),color-mix(in srgb,#ff9d00 64%,var(--card)));color:#fff;border-color:#ff6a5a}
.card{border-radius:var(--pro-radius);box-shadow:0 18px 50px #0005}
.topbar{box-shadow:0 10px 30px #0003}
.pro-dashboard-head{grid-column:1/-1;display:grid;gap:14px}
.pro-kpi-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.pro-kpi{border:1px solid var(--line);border-radius:15px;background:linear-gradient(180deg,var(--pro-soft),color-mix(in srgb,var(--bg) 84%,transparent));padding:13px;min-width:0}
.pro-kpi span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}.pro-kpi strong{display:block;font-size:24px;margin-top:4px}.pro-ai-badge{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.pro-ai-badge .pill{border-color:color-mix(in srgb,var(--good) 55%,var(--line));color:var(--good)}
.pro-chart{display:grid;gap:10px}.pro-chart-row{display:grid;grid-template-columns:minmax(110px,1.2fr) 3fr auto;gap:10px;align-items:center}.pro-chart-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted);font-size:12px}.pro-chart-track{height:10px;border-radius:99px;background:color-mix(in srgb,var(--line) 72%,transparent);overflow:hidden}.pro-chart-bar{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--accent2));min-width:3px}.pro-chart-value{font-weight:800;font-size:12px}
#channelProfileCard .notice:has(#channelDescription){padding:0;overflow:hidden}#channelDescription{max-height:64px;overflow:hidden;position:relative;margin:0!important;padding:10px 14px 12px;cursor:pointer;transition:max-height .25s ease}#channelDescription::after{content:'Toque para expandir';display:block;margin-top:8px;color:var(--accent);font-size:11px;font-weight:800}#channelDescription.expanded{max-height:800px}#channelDescription.expanded::after{content:'Toque para recolher'}#channelProfileCard .notice:has(#channelDescription)>b{display:block;padding:11px 14px 0}
.result-panel{margin-top:10px;display:grid;gap:10px}.result-summary{border:1px solid color-mix(in srgb,var(--good) 48%,var(--line));background:color-mix(in srgb,var(--good) 7%,var(--card2));border-radius:14px;padding:12px}.result-summary strong{display:block;margin-bottom:4px}.result-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.result-card{border:1px solid var(--line);border-radius:14px;background:var(--card2);padding:12px;min-width:0}.result-card h4{margin:0 0 6px;font-size:13px}.result-card p{margin:4px 0;color:var(--muted)}.result-card .score{font-size:22px;font-weight:900;color:var(--accent)}.result-list{display:flex;gap:6px;flex-wrap:wrap}.result-list .pill{white-space:normal}.tech-details{border:1px solid var(--line);border-radius:13px;background:color-mix(in srgb,var(--bg) 82%,#000);overflow:hidden}.tech-details summary{cursor:pointer;padding:10px 12px;font-weight:800;color:var(--muted)}.tech-details .code{border:0;border-top:1px solid var(--line);border-radius:0;margin:0;max-height:320px}.ai-context-note{display:flex;gap:8px;align-items:flex-start;padding:10px 12px;border:1px solid color-mix(in srgb,var(--accent) 38%,var(--line));border-radius:13px;background:color-mix(in srgb,var(--accent) 6%,var(--card2));color:var(--muted);font-size:12px}.ai-context-note b{color:var(--text)}
#strategy .card>p.muted:first-of-type,#audit .card>p.muted:first-of-type{max-width:72ch}.code{font-size:11px}
@media(max-width:760px){.pro-kpi-grid{grid-template-columns:1fr 1fr}.pro-chart-row{grid-template-columns:minmax(90px,1fr) 1.7fr auto}.result-grid{grid-template-columns:1fr}.card{border-radius:17px}.topbar{padding-top:calc(12px + env(safe-area-inset-top))}#channelDescription{max-height:58px}.pro-dashboard-head{gap:10px}.pro-kpi strong{font-size:20px}}
</style>
'''

_SCRIPT = r'''
<script data-yca-pro-dashboard>
(()=>{
  if(window.__ycaProDashboardMounted)return;window.__ycaProDashboardMounted=true;
  const $id=id=>document.getElementById(id);
  const escv=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const fmt=n=>{const v=Number(n||0);if(!Number.isFinite(v))return String(n??'—');return new Intl.NumberFormat('pt-BR',{notation:Math.abs(v)>=10000?'compact':'standard',maximumFractionDigits:1}).format(v)};
  const titleCase=s=>String(s||'').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
  const asArray=v=>Array.isArray(v)?v:[];
  function summaryFor(data,kind){
    if(kind==='research'){const ops=asArray(data.opportunities);return ops.length?`${ops.length} oportunidade(s) mapeada(s). Os cartões abaixo mostram os sinais mais úteis, sem exigir que você decifre JSON.`:'Pesquisa concluída com dados reais.'}
    if(kind==='strategy')return 'Estratégia construída. Abaixo estão os pontos que merecem decisão, enquanto os dados técnicos continuam disponíveis para auditoria.';
    if(kind==='keywords')return 'Validação concluída com evidências reais do YouTube. Priorize termos com melhor combinação entre demanda, competição e aderência ao canal.';
    if(kind==='audit')return 'Auditoria concluída. O resumo abaixo transforma a coleta técnica em informações legíveis; nenhum dado foi alterado no canal.';
    return 'Dados coletados com sucesso. A visualização foi simplificada para leitura humana.';
  }
  function cardHtml(label,value){
    if(value===null||value===undefined||value==='')return '';
    if(Array.isArray(value)){const items=value.slice(0,8).map(x=>typeof x==='object'?escv(x.keyword||x.term||x.title||JSON.stringify(x)):escv(x));return `<div class="result-card"><h4>${escv(label)}</h4><div class="result-list">${items.map(x=>`<span class="pill">${x}</span>`).join('')}</div></div>`}
    if(typeof value==='object')return '';
    return `<div class="result-card"><h4>${escv(label)}</h4><p>${escv(value)}</p></div>`;
  }
  function opportunityCards(data){
    const ops=asArray(data.opportunities).slice(0,8);if(!ops.length)return '';
    return ops.map(op=>{const r=op.research||{};const o=r.opportunity||{};const score=o.score??op.score??'—';const keyword=op.keyword||r.query||'Oportunidade';const reason=asArray(o.reasons)[0]||r.competition_label||'';return `<div class="result-card"><h4>${escv(keyword)}</h4><div class="score">${escv(score)}</div><p>Score de oportunidade</p>${reason?`<p>${escv(reason)}</p>`:''}${r.result_count!==undefined?`<span class="pill">${fmt(r.result_count)} resultados</span>`:''}</div>`}).join('');
  }
  function channelCards(data){const c=data.channel||data;const fields=[['Canal',c.channel_title||c.title],['Inscritos',c.subscribers!==undefined?fmt(c.subscribers):null],['Views totais',c.total_views!==undefined?fmt(c.total_views):null],['Vídeos',c.video_count!==undefined?fmt(c.video_count):null],['Views no período',c.total_analytics_views!==undefined?fmt(c.total_analytics_views):null],['Participação da busca',c.search_share!==undefined?(Number(c.search_share)*100).toFixed(1)+'%':null]];return fields.map(([a,b])=>cardHtml(a,b)).join('')}
  function genericCards(data){const preferred=['title','summary','rationale','recommendation','recommended_action','language','provider','model','keyword_candidates','verified_keywords','top_search_terms'];return preferred.map(k=>k in data?cardHtml(titleCase(k),data[k]):'').join('')}
  function renderStructured(node,data,kind){
    const raw=JSON.stringify(data,null,2);let cards='';
    if(kind==='research')cards=opportunityCards(data)||genericCards(data);
    else if(kind==='audit')cards=channelCards(data)+(data.evidence?genericCards(data.evidence):'');
    else cards=genericCards(data)||channelCards(data);
    node.className='result-panel';
    node.innerHTML=`<div class="result-summary"><strong>${kind==='audit'?'Diagnóstico legível':'Resultado pronto para decisão'}</strong>${escv(summaryFor(data,kind))}</div>${cards?`<div class="result-grid">${cards}</div>`:''}<details class="tech-details"><summary>Ver dados técnicos</summary><pre class="code">${escv(raw)}</pre></details>`;
  }
  const kinds={researchResult:'research',strategyResult:'strategy',keywordResult:'keywords',evidenceRaw:'evidence',auditRaw:'audit'};
  Object.entries(kinds).forEach(([id,kind])=>{const node=$id(id);if(!node)return;const obs=new MutationObserver(()=>{const raw=node.textContent.trim();if((raw.startsWith('{')||raw.startsWith('['))&&!node.querySelector('.tech-details')){try{renderStructured(node,JSON.parse(raw),kind)}catch(_){}}});obs.observe(node,{childList:true,subtree:true,characterData:true});});
  const desc=$id('channelDescription');if(desc){desc.setAttribute('role','button');desc.setAttribute('tabindex','0');const toggle=()=>desc.classList.toggle('expanded');desc.addEventListener('click',toggle);desc.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle()}})}
  function addAiNotes(){
    [['strategy','A IA externa é usada para pesquisa, estratégia e propostas. Evidências e dados do YouTube continuam sendo a fonte de verdade.'],['videos','A IA pode propor SEO e metadados, mas qualquer alteração continua exigindo revisão e confirmação.'],['publish','A IA pode preparar título, descrição, tags e plano de publicação. O idioma original é preservado pelo servidor.'],['audit','A auditoria coleta fatos primeiro. A IA ajuda a interpretar e propor próximos passos sem alterar nada automaticamente.']].forEach(([section,text])=>{const root=document.getElementById(section);if(!root||root.querySelector('.ai-context-note'))return;const grid=root.querySelector('.grid');if(!grid)return;const note=document.createElement('div');note.className='ai-context-note card full';note.innerHTML=`<span>✦</span><div><b>IA assistiva</b><br>${escv(text)}</div>`;grid.prepend(note)});
  }
  async function loadProOverview(){
    const home=document.getElementById('home');const grid=home?.querySelector('.grid');if(!grid||document.getElementById('proDashboardHead'))return;
    const shell=document.createElement('article');shell.id='proDashboardHead';shell.className='card full pro-dashboard-head';shell.innerHTML='<div class="toolbar" style="justify-content:space-between"><div><h3 style="font-size:17px;margin:0">Desempenho real do canal</h3><div class="muted">Resumo executivo com dados atuais do YouTube</div></div><div class="pro-ai-badge" id="proAiBadge"><span class="pill">Verificando IA…</span></div></div><div class="pro-kpi-grid" id="proKpis"></div><div class="pro-chart" id="proChart"><div class="muted">Carregando vídeos reais…</div></div>';
    grid.prepend(shell);
    try{
      const [channel,videos,status]=await Promise.all([api('/api/dashboard/channel?period_days=28'),api('/api/dashboard/videos?limit=12'),api('/api/dashboard/status')]);
      const c=channel||{};$id('proKpis').innerHTML=[['Inscritos',c.subscribers],['Views / 28 dias',c.total_analytics_views],['Views totais',c.total_views],['Vídeos',c.video_count]].map(([l,v])=>`<div class="pro-kpi"><span>${escv(l)}</span><strong>${fmt(v)}</strong></div>`).join('');
      const rows=asArray(videos.videos).slice().sort((a,b)=>(b.views||0)-(a.views||0)).slice(0,6);const max=Math.max(1,...rows.map(r=>Number(r.views||0)));$id('proChart').innerHTML=rows.length?rows.map(r=>`<div class="pro-chart-row"><div class="pro-chart-label" title="${escv(r.title)}">${escv(r.title)}</div><div class="pro-chart-track"><div class="pro-chart-bar" style="width:${Math.max(2,Number(r.views||0)/max*100)}%"></div></div><div class="pro-chart-value">${fmt(r.views)}</div></div>`).join(''):'<div class="muted">Ainda não há vídeos suficientes para o gráfico.</div>';
      $id('proAiBadge').innerHTML=status.external_ai_configured?`<span class="pill">✦ IA ativa</span><span class="pill">${escv(status.ai_provider||'IA')} · ${escv(status.ai_model||'modelo configurado')}</span>`:'<span class="pill">IA externa não configurada</span>';
    }catch(e){$id('proChart').innerHTML=`<div class="notice warn">Não foi possível montar o gráfico agora: ${escv(e.message)}</div>`}
  }
  addAiNotes();setTimeout(loadProOverview,180);
})();
</script>
'''


def enhance_dashboard_html(source: str) -> str:
    if 'data-yca-pro-dashboard' in source:
        return source
    if '</head>' not in source or '</body>' not in source:
        raise RuntimeError('Professional dashboard enhancement requires complete HTML.')
    source = source.replace('</head>', _CSS + '\n</head>', 1)
    return source.replace('</body>', _SCRIPT + '\n</body>', 1)


def _find_dashboard_route(app: FastAPI) -> APIRoute:
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.path == '/dashboard' and 'GET' in (route.methods or set()):
            return route
    raise RuntimeError('Dashboard route not found for professional UX enhancement.')


def install_dashboard_pro_ui(app: FastAPI) -> None:
    route = _find_dashboard_route(app)
    original = route.endpoint
    app.router.routes.remove(route)

    async def enhanced_dashboard(request: Request):
        response = await original(request)
        if not isinstance(response, HTMLResponse):
            return response
        headers = dict(response.headers)
        headers.pop('content-length', None)
        headers.pop('content-type', None)
        headers['Cache-Control'] = 'no-store'
        return HTMLResponse(
            enhance_dashboard_html(response.body.decode('utf-8')),
            status_code=response.status_code,
            headers=headers,
        )

    app.add_api_route('/dashboard', enhanced_dashboard, methods=['GET'], include_in_schema=False, name='professional_dashboard')
