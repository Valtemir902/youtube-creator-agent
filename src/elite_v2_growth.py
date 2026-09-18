from __future__ import annotations

import json

GROWTH_CSS = r'''
.v2-growth-workspace{grid-column:1/-1;border:1px solid var(--v2-border);border-radius:20px;padding:17px;background:linear-gradient(180deg,rgba(18,31,50,.94),rgba(9,18,31,.96));box-shadow:var(--v2-shadow);margin-bottom:2px}
.v2-growth-toolbar{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}.v2-growth-toolbar h3{margin:0;font-size:16px}.v2-growth-toolbar p{margin:4px 0 0;color:var(--v2-muted);font-size:11px}.v2-growth-controls{display:flex;gap:7px;align-items:center;flex-wrap:wrap}.v2-growth-controls select{width:auto;min-width:112px}
.v2-growth-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:13px 0}.v2-growth-kpi{border:1px solid var(--v2-border);border-radius:14px;padding:11px;background:rgba(7,17,31,.4)}.v2-growth-kpi small{display:block;color:var(--v2-muted);font-size:9px;text-transform:uppercase;letter-spacing:.07em}.v2-growth-kpi strong{display:block;font-size:21px;margin-top:4px;letter-spacing:-.03em}.v2-timeseries-shell{border:1px solid rgba(148,163,184,.1);border-radius:16px;padding:12px;background:rgba(5,13,24,.5);min-height:260px}.v2-timeseries-chart{width:100%;height:230px;display:block}.v2-timeseries-grid{stroke:rgba(148,163,184,.09);stroke-width:1}.v2-timeseries-line{fill:none;stroke:url(#v2GrowthGradient);stroke-width:4;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 5px 9px rgba(34,211,238,.16))}.v2-timeseries-area{fill:url(#v2GrowthArea);opacity:.52}.v2-chart-axis-label{fill:#8293aa;font-size:10px}.v2-growth-empty{min-height:230px;display:grid;place-items:center;text-align:center;color:var(--v2-muted);padding:20px}.v2-source-row{display:flex;justify-content:space-between;gap:12px;align-items:center;margin-top:9px;color:var(--v2-muted);font-size:10px}.v2-source-row code{font-size:9px;color:#b9c8da}.v2-source-badge{display:inline-flex;align-items:center;gap:6px}.v2-source-badge::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--v2-success);box-shadow:0 0 12px rgba(52,211,153,.5)}
@media(max-width:760px){.v2-growth-kpis{grid-template-columns:1fr 1fr}.v2-growth-controls{width:100%}.v2-growth-controls select,.v2-growth-controls .btn{flex:1}.v2-timeseries-shell{padding:7px}.v2-timeseries-chart{height:205px}}
'''

GROWTH_JS = r'''
(()=>{
  const fmt=(n,d=0)=>new Intl.NumberFormat('pt-BR',{maximumFractionDigits:d}).format(Number(n)||0);
  const esc=value=>String(value??'').replace(/[&<>\"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const install=()=>{
    if(document.querySelector('[data-v2-growth-workspace]'))return;const section=document.getElementById('strategy'),grid=section&&section.querySelector('.grid');if(!grid)return;
    const banner=grid.querySelector('.v2-section-banner');const box=document.createElement('article');box.className='v2-growth-workspace';box.dataset.v2GrowthWorkspace='1';box.innerHTML=`
      <div class="v2-growth-toolbar"><div><h3>Growth & Analytics</h3><p>Série temporal oficial do YouTube Analytics. Carregada sob demanda, nunca inventada.</p></div><div class="v2-growth-controls"><span class="v2-quiet-badge real">YouTube Analytics</span><select data-v2-growth-period aria-label="Período"><option value="7">7 dias</option><option value="28" selected>28 dias</option><option value="90">90 dias</option></select><button class="btn" type="button" data-v2-growth-load>Carregar Analytics</button></div></div>
      <div class="v2-growth-kpis"><div class="v2-growth-kpi"><small>Views no período</small><strong data-v2-growth-views>—</strong></div><div class="v2-growth-kpi"><small>Watch time</small><strong data-v2-growth-watch>—</strong></div><div class="v2-growth-kpi"><small>Inscritos líquidos</small><strong data-v2-growth-subs>—</strong></div><div class="v2-growth-kpi"><small>Média diária</small><strong data-v2-growth-average>—</strong></div></div>
      <div class="v2-timeseries-shell" data-v2-growth-chart><div class="v2-growth-empty">Abra Growth & SEO para carregar dados oficiais do período.</div></div>
      <div class="v2-source-row"><span class="v2-source-badge">Fonte oficial, sem estimativas</span><code data-v2-growth-range>youtube_analytics_api</code></div>`;
    if(banner)banner.insertAdjacentElement('afterend',box);else grid.prepend(box);
    const period=box.querySelector('[data-v2-growth-period]'),button=box.querySelector('[data-v2-growth-load]'),chart=box.querySelector('[data-v2-growth-chart]');let loading=false,loaded=false;
    const render=payload=>{const rows=payload.rows||[];if(!payload.available){chart.innerHTML=`<div class="v2-growth-empty"><div><b>Analytics indisponível agora</b><br><span>${esc(payload.error||payload.detail||'A API não retornou dados oficiais.')}</span></div></div>`;return}if(!rows.length){chart.innerHTML='<div class="v2-growth-empty">A API respondeu sem linhas para este período. Nenhum dado foi estimado.</div>';return}
      const values=rows.map(r=>Number(r.views)||0),max=Math.max(...values,1),w=800,h=210,padX=28,padY=18,usableW=w-padX*2,usableH=h-padY*2;const pts=rows.map((r,i)=>{const x=padX+(rows.length===1?usableW/2:i/(rows.length-1)*usableW),y=padY+(1-(Number(r.views)||0)/max)*usableH;return [x,y]});const line=pts.map(p=>p.map(v=>v.toFixed(1)).join(',')).join(' '),area=`${padX},${h-padY} ${line} ${w-padX},${h-padY}`;const gridLines=[.25,.5,.75,1].map(f=>`<line class="v2-timeseries-grid" x1="${padX}" y1="${(padY+usableH*(1-f)).toFixed(1)}" x2="${w-padX}" y2="${(padY+usableH*(1-f)).toFixed(1)}"/>`).join('');chart.innerHTML=`<svg class="v2-timeseries-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Views diárias oficiais"><defs><linearGradient id="v2GrowthGradient" x1="0" x2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient><linearGradient id="v2GrowthArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#22d3ee" stop-opacity=".32"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></linearGradient></defs>${gridLines}<polygon class="v2-timeseries-area" points="${area}"/><polyline class="v2-timeseries-line" points="${line}"/><text class="v2-chart-axis-label" x="${padX}" y="${h-2}">${esc(rows[0].date)}</text><text class="v2-chart-axis-label" text-anchor="end" x="${w-padX}" y="${h-2}">${esc(rows[rows.length-1].date)}</text><text class="v2-chart-axis-label" x="${padX}" y="12">${fmt(max)} views/dia</text></svg>`;
      const totalViews=rows.reduce((s,r)=>s+(Number(r.views)||0),0),watch=rows.reduce((s,r)=>s+(Number(r.watch_time_hours)||0),0),subs=rows.reduce((s,r)=>s+(Number(r.subscribers_net)||0),0);box.querySelector('[data-v2-growth-views]').textContent=fmt(totalViews);box.querySelector('[data-v2-growth-watch]').textContent=`${fmt(watch,1)} h`;box.querySelector('[data-v2-growth-subs]').textContent=(subs>0?'+':'')+fmt(subs);box.querySelector('[data-v2-growth-average]').textContent=fmt(totalViews/rows.length,1);box.querySelector('[data-v2-growth-range]').textContent=`${payload.start_date} → ${payload.end_date} · ${payload.source}`;};
    const load=async force=>{if(loading)return;loading=true;button.disabled=true;button.textContent='Carregando…';chart.innerHTML='<div class="v2-growth-empty"><span class="loader"></span></div>';try{const r=await fetch(`/api/v2/analytics/timeseries?period_days=${encodeURIComponent(period.value)}${force?'&refresh=1':''}`,{headers:{Accept:'application/json'}});const payload=await r.json();render(payload);loaded=true}catch(err){chart.innerHTML=`<div class="v2-growth-empty">${esc(err.message||'Falha ao carregar Analytics.')}</div>`}finally{loading=false;button.disabled=false;button.textContent=loaded?'Atualizar Analytics':'Carregar Analytics'}};
    button.addEventListener('click',()=>load(true));period.addEventListener('change',()=>load(true));document.querySelector('.nav button[data-tab="strategy"]')?.addEventListener('click',()=>{if(!loaded)setTimeout(()=>load(false),120)});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();
'''


def growth_webengine_source() -> str:
    css_json = json.dumps(GROWTH_CSS, ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-v2-growth]')){"
        "const s=document.createElement('style');s.dataset.ycaV2Growth='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n" + GROWTH_JS
    )
