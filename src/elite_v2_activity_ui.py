from __future__ import annotations

import json

ACTIVITY_CSS = r'''
.v2-activity{grid-column:1/-1;border:1px solid var(--v2-border);border-radius:20px;padding:17px;background:linear-gradient(145deg,rgba(18,31,50,.91),rgba(7,17,31,.94));box-shadow:var(--v2-shadow)}.v2-activity-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.v2-activity-head h3{margin:0;font-size:15px}.v2-activity-head p{margin:4px 0 0;color:var(--v2-muted);font-size:11px}.v2-activity-list{display:grid;gap:8px;margin-top:12px}.v2-activity-row{display:grid;grid-template-columns:124px 140px minmax(0,1fr) auto;gap:10px;align-items:center;border:1px solid rgba(148,163,184,.1);border-radius:13px;padding:10px;background:rgba(5,13,24,.32);font-size:10px}.v2-activity-row time,.v2-activity-row span{color:var(--v2-muted)}.v2-activity-row b{font-size:10px}.v2-event-state{padding:5px 7px;border:1px solid var(--v2-border);border-radius:999px;font-size:8px;text-transform:uppercase;letter-spacing:.05em}.v2-event-state.verified{color:#86efac;border-color:rgba(52,211,153,.22)}.v2-event-state.failed{color:#fda4af;border-color:rgba(251,113,133,.22)}.v2-activity-empty{padding:22px;text-align:center;color:var(--v2-muted);font-size:11px}@media(max-width:760px){.v2-activity-row{grid-template-columns:1fr auto}.v2-activity-row time,.v2-activity-row span{grid-column:1/-1}.v2-activity-head{flex-direction:column}}
'''

ACTIVITY_JS = r'''
(()=>{
  const esc=value=>String(value??'').replace(/[&<>\"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const install=()=>{if(document.querySelector('[data-v2-activity]'))return;const section=document.getElementById('audit'),grid=section&&section.querySelector('.grid');if(!grid)return;const box=document.createElement('article');box.className='v2-activity';box.dataset.v2Activity='1';box.innerHTML=`<div class="v2-activity-head"><div><h3>Activity & Audit</h3><p>Histórico local das propostas, aprovações, verificações e rollbacks do Write Gateway.</p></div><button class="btn" type="button" data-v2-activity-refresh>Atualizar histórico</button></div><div class="v2-activity-list" data-v2-activity-list><div class="v2-activity-empty">Nenhuma ação carregada.</div></div>`;const banner=grid.querySelector('.v2-section-banner');if(banner)banner.insertAdjacentElement('afterend',box);else grid.prepend(box);const list=box.querySelector('[data-v2-activity-list]'),button=box.querySelector('[data-v2-activity-refresh]');let loaded=false;
    const load=async()=>{button.disabled=true;try{const r=await fetch('/api/v2/activity?limit=100',{headers:{Accept:'application/json'}}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Falha ao ler auditoria');const rows=d.events||[];list.innerHTML=rows.length?rows.map(e=>`<div class="v2-activity-row"><time>${esc((e.timestamp||'').replace('T',' ').slice(0,19))}</time><b>${esc(e.event||'evento')}</b><span>${esc(e.target_kind||'')} ${esc(e.target_id||'')}</span><i class="v2-event-state ${esc(e.state||'')}">${esc(e.state||'')}</i></div>`).join(''):'<div class="v2-activity-empty">Nenhuma alteração passou pelo Write Gateway nesta sessão.</div>';loaded=true}catch(err){list.innerHTML=`<div class="v2-activity-empty">${esc(err.message)}</div>`}finally{button.disabled=false}};
    button.addEventListener('click',load);document.querySelector('.nav button[data-tab="audit"]')?.addEventListener('click',()=>{if(!loaded)setTimeout(load,100)})};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();
'''


def activity_ui_webengine_source() -> str:
    css_json=json.dumps(ACTIVITY_CSS,ensure_ascii=False)
    return "(()=>{if(!document.querySelector('style[data-yca-v2-activity]')){const s=document.createElement('style');s.dataset.ycaV2Activity='1';s.textContent="+css_json+";(document.head||document.documentElement).appendChild(s);}})();\n"+ACTIVITY_JS
