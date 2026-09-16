from __future__ import annotations


_CSS = r'''
<style data-yca-human-results>
.human-result{display:grid;gap:12px;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
.human-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.human-metric{border:1px solid var(--line);border-radius:14px;padding:12px;background:linear-gradient(180deg,color-mix(in srgb,var(--card2) 94%,transparent),color-mix(in srgb,var(--card) 86%,transparent))}
.human-metric small{display:block;color:var(--muted);font-size:11px;margin-bottom:4px}.human-metric strong{font-size:21px;line-height:1.15;word-break:break-word}.human-section{border:1px solid var(--line);border-radius:14px;padding:12px;background:color-mix(in srgb,var(--card2) 90%,transparent)}
.human-section>h4{margin:0 0 9px;font-size:13px;color:var(--text)}.human-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:9px}.human-field{border:1px solid color-mix(in srgb,var(--line) 75%,transparent);border-radius:11px;padding:9px;background:color-mix(in srgb,var(--bg) 35%,transparent);min-width:0}.human-field small{display:block;color:var(--muted);font-size:10px;text-transform:none}.human-field b,.human-field span{display:block;margin-top:3px;overflow-wrap:anywhere}.human-list{display:grid;gap:7px}.human-list-item{border:1px solid color-mix(in srgb,var(--line) 70%,transparent);border-radius:11px;padding:9px;background:color-mix(in srgb,var(--card) 70%,transparent)}.human-chips{display:flex;gap:6px;flex-wrap:wrap}.human-chip{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:5px 8px;color:var(--muted);font-size:11px}.human-technical{margin-top:2px;border-top:1px solid color-mix(in srgb,var(--line) 72%,transparent);padding-top:9px}.human-technical summary{cursor:pointer;color:var(--muted);font-size:11px;font-weight:750;user-select:none}.human-technical pre{white-space:pre-wrap;word-break:break-word;max-height:330px;overflow:auto;background:color-mix(in srgb,var(--bg) 88%,#000);border:1px solid var(--line);border-radius:11px;padding:10px;font:11px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace;margin:8px 0 0}.human-video-title{font-weight:800}.human-video-meta{color:var(--muted);font-size:11px;margin-top:3px}.human-empty{color:var(--muted);padding:8px 0}.human-status-good{color:var(--good)}.human-status-warn{color:var(--warn)}.human-status-bad{color:var(--bad)}
@media(max-width:760px){.human-summary{grid-template-columns:1fr 1fr}.human-grid{grid-template-columns:1fr}.human-metric strong{font-size:18px}}
</style>
'''

_SCRIPT = r'''
<script data-yca-human-results>
(()=>{
  if(window.__ycaHumanResults)return;window.__ycaHumanResults=true;
  const ids=['auditRaw','evidenceRaw','keywordResult','researchResult','strategyResult'];
  const labels={period_days:'Período',channel:'Canal',channel_title:'Canal',subscribers:'Inscritos',total_views:'Views totais',total_analytics_views:'Views no período',video_count:'Vídeos',search_views:'Views por busca',search_share:'Participação da busca',top_search_terms:'Termos de busca',top_videos:'Vídeos em destaque',weak_videos:'Vídeos que precisam de atenção',opportunities:'Oportunidades',keywords:'Palavras-chave',candidates:'Candidatos',recommendations:'Recomendações',actions:'Ações',priorities:'Prioridades',strengths:'Pontos fortes',weaknesses:'Pontos de atenção',engagement_rate_28d:'Engajamento',views_28d:'Views em 28 dias',likes_28d:'Likes em 28 dias',comments_28d:'Comentários em 28 dias',shares_28d:'Compartilhamentos em 28 dias',subscribers_gained_28d:'Inscritos ganhos',estimated_minutes_watched_28d:'Minutos assistidos',average_view_duration_28d:'Duração média',title:'Título',video_id:'ID do vídeo',published_at:'Publicado em',format:'Formato',country:'País / mercado',language:'Idioma',default_language:'Idioma',niche:'Nicho',topic_terms:'Temas',competition_label:'Concorrência',demand_index:'Demanda',keyword:'Palavra-chave',score:'Score',rationale:'Motivo',status:'Status',message:'Mensagem',evidence:'Evidências'};
  const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const label=k=>labels[k]||String(k||'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
  const number=v=>new Intl.NumberFormat('pt-BR',{maximumFractionDigits:2}).format(Number(v));
  function primitive(v,k=''){
    if(v===null||v===undefined||v==='')return '—';
    if(typeof v==='boolean')return v?'Sim':'Não';
    if(typeof v==='number'){
      if(/share|rate|ctr|percent/i.test(k) && Math.abs(v)<=1)return (v*100).toFixed(1)+'%';
      return number(v);
    }
    const s=String(v);
    if(/^\d{4}-\d\d-\d\dT/.test(s)){const d=new Date(s);if(!Number.isNaN(d.getTime()))return d.toLocaleString('pt-BR')}
    return s;
  }
  function chips(arr){return `<div class="human-chips">${arr.slice(0,40).map(x=>`<span class="human-chip">${esc(typeof x==='object'?(x.term||x.keyword||x.title||JSON.stringify(x)):primitive(x))}</span>`).join('')}</div>`}
  function videoItem(v){const title=v?.title||v?.name||v?.video_title||v?.video_id||'Vídeo';const meta=[];if(v?.views_28d!==undefined)meta.push(`${number(v.views_28d)} views / 28d`);else if(v?.views_total!==undefined)meta.push(`${number(v.views_total)} views`);if(v?.engagement_rate_28d!==undefined)meta.push(`${primitive(v.engagement_rate_28d,'engagement_rate')} engajamento`);if(v?.format)meta.push(String(v.format));return `<div class="human-list-item"><div class="human-video-title">${esc(title)}</div>${meta.length?`<div class="human-video-meta">${esc(meta.join(' · '))}</div>`:''}</div>`}
  function arrayView(arr,key,depth){if(!arr.length)return '<div class="human-empty">Nenhum item encontrado.</div>';if(arr.every(x=>x===null||['string','number','boolean'].includes(typeof x)))return chips(arr);if(/video/i.test(key))return `<div class="human-list">${arr.slice(0,30).map(videoItem).join('')}</div>`;return `<div class="human-list">${arr.slice(0,30).map((x,i)=>`<div class="human-list-item">${valueView(x,`${key} ${i+1}`,depth+1)}</div>`).join('')}</div>`}
  function objectView(obj,depth=0){const entries=Object.entries(obj||{}).filter(([,v])=>v!==undefined);if(!entries.length)return '<div class="human-empty">Sem dados disponíveis.</div>';const simple=entries.filter(([,v])=>v===null||['string','number','boolean'].includes(typeof v));const complex=entries.filter(([,v])=>!(v===null||['string','number','boolean'].includes(typeof v)));let html='';if(simple.length)html+=`<div class="human-grid">${simple.map(([k,v])=>`<div class="human-field"><small>${esc(label(k))}</small><b>${esc(primitive(v,k))}</b></div>`).join('')}</div>`;for(const [k,v] of complex){if(depth>3){html+=`<div class="human-field"><small>${esc(label(k))}</small><span>${esc(Array.isArray(v)?`${v.length} item(ns)`:'Dados disponíveis')}</span></div>`;continue}html+=`<div class="human-section"><h4>${esc(label(k))}</h4>${valueView(v,k,depth+1)}</div>`}return html}
  function valueView(v,key='',depth=0){if(Array.isArray(v))return arrayView(v,key,depth);if(v&&typeof v==='object')return objectView(v,depth);return `<span>${esc(primitive(v,key))}</span>`}
  function pick(obj,names){for(const n of names)if(obj&&obj[n]!==undefined)return obj[n];return undefined}
  function auditView(data){const ch=data?.channel||{};const ev=data?.evidence||data||{};const metrics=[['Canal',pick(ch,['channel_title','title'])],['Inscritos',pick(ch,['subscribers','subscriber_count'])],['Views totais',pick(ch,['total_views','views'])],['Vídeos',pick(ch,['video_count','videos_analyzed'])],['Views por busca',pick(ch,['search_views'])],['Engajamento',pick(ch,['engagement_rate_28d'])]].filter(([,v])=>v!==undefined);let html=`<div class="human-summary">${metrics.map(([k,v])=>`<div class="human-metric"><small>${esc(k)}</small><strong>${esc(primitive(v,k==='Engajamento'?'rate':''))}</strong></div>`).join('')}</div>`;const sections=[['Pontos fortes',pick(ev,['strengths','wins'])],['Pontos de atenção',pick(ev,['weaknesses','risks'])],['Vídeos em destaque',pick(ch,['top_videos'])||pick(ev,['top_videos'])],['Vídeos que precisam de atenção',pick(ch,['weak_videos'])||pick(ev,['weak_videos'])],['Oportunidades',pick(ev,['opportunities','candidates','keywords'])],['Recomendações',pick(ev,['recommendations','actions','priorities'])]];for(const [title,v] of sections)if(v!==undefined&&v!==null&&(!Array.isArray(v)||v.length))html+=`<div class="human-section"><h4>${esc(title)}</h4>${valueView(v,title,1)}</div>`;return html||objectView(data)}
  function keywordView(data){const rows=Array.isArray(data)?data:(pick(data,['keywords','results','candidates','items'])||[]);if(!Array.isArray(rows)||!rows.length)return objectView(data);return `<div class="human-list">${rows.map(row=>{if(typeof row!=='object')return `<div class="human-list-item">${esc(primitive(row))}</div>`;const name=row.keyword||row.term||row.query||row.title||'Palavra-chave';const bits=[];if(row.demand_index!==undefined)bits.push(`Demanda ${primitive(row.demand_index)}`);if(row.competition_label!==undefined)bits.push(`Concorrência ${primitive(row.competition_label)}`);if(row.score!==undefined)bits.push(`Score ${primitive(row.score)}`);return `<div class="human-list-item"><div class="human-video-title">${esc(name)}</div>${bits.length?`<div class="human-video-meta">${esc(bits.join(' · '))}</div>`:''}${row.rationale?`<div style="margin-top:5px">${esc(row.rationale)}</div>`:''}</div>`}).join('')}</div>`}
  function render(el,data,raw){const type=el.id==='auditRaw'?'audit':el.id==='keywordResult'?'keywords':'generic';let content=type==='audit'?auditView(data):type==='keywords'?keywordView(data):objectView(data);el.classList.remove('code');el.classList.add('human-result');el.innerHTML=`${content}<details class="human-technical"><summary>Ver dados técnicos (JSON)</summary><pre>${esc(raw)}</pre></details>`;el.dataset.humanized='1'}
  function humanize(el){if(!el||el.dataset.humanizing==='1')return;const raw=(el.textContent||'').trim();if(!raw||(!raw.startsWith('{')&&!raw.startsWith('[')))return;let data;try{data=JSON.parse(raw)}catch{return}el.dataset.humanizing='1';try{render(el,data,raw)}finally{delete el.dataset.humanizing}}
  function scan(){for(const id of ids)humanize(document.getElementById(id));document.querySelectorAll('#memoryBox .code').forEach(humanize)}
  const observer=new MutationObserver(mutations=>{for(const m of mutations){const t=m.target.nodeType===1?m.target:m.target.parentElement;if(!t)continue;const el=t.closest?.('#auditRaw,#evidenceRaw,#keywordResult,#researchResult,#strategyResult,#memoryBox .code');if(el)humanize(el)}});
  const start=()=>{scan();observer.observe(document.body,{subtree:true,childList:true,characterData:true});};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
</script>
'''


def enhance_human_results_html(source: str) -> str:
    """Turn user-facing JSON dumps into readable cards while retaining JSON on demand."""
    if 'data-yca-human-results' in source:
        return source
    if '</head>' not in source or '</body>' not in source:
        return source
    source = source.replace('</head>', _CSS + '\n</head>', 1)
    source = source.replace('</body>', _SCRIPT + '\n</body>', 1)
    return source
