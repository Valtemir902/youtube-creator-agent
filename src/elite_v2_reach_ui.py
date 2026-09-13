from __future__ import annotations

import json

REACH_UI_CSS = r'''
.v2-reach-card{grid-column:1/-1;border:1px solid var(--v2-border);border-radius:18px;padding:15px;background:linear-gradient(145deg,rgba(10,22,38,.92),rgba(6,14,25,.88));box-shadow:var(--v2-shadow);margin-top:10px}.v2-reach-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}.v2-reach-head h3{margin:0;font-size:14px}.v2-reach-head p{margin:4px 0 0;color:var(--v2-muted);font-size:11px;max-width:760px}.v2-reach-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px}.v2-reach-metric{border:1px solid rgba(148,163,184,.11);border-radius:13px;padding:10px;background:rgba(5,13,24,.38)}.v2-reach-metric small{display:block;color:var(--v2-muted);font-size:9px;text-transform:uppercase;letter-spacing:.06em}.v2-reach-metric strong{display:block;margin-top:4px;font-size:18px}.v2-reach-message{margin-top:10px;color:var(--v2-muted);font-size:10px;line-height:1.45}.v2-reach-message.warn{color:#fde68a}.v2-reach-message.ok{color:#bbf7d0}@media(max-width:760px){.v2-reach-metrics{grid-template-columns:1fr}.v2-reach-head .btn{width:100%}}
'''

REACH_UI_JS = r'''
(()=>{
  const esc=value=>String(value??'').replace(/[&<>\"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const fmt=n=>new Intl.NumberFormat('pt-BR').format(Number(n)||0);
  const install=()=>{if(document.querySelector('[data-v2-reach-card]'))return true;const host=document.querySelector('[data-v2-growth-workspace]');if(!host)return false;const card=document.createElement('article');card.className='v2-reach-card';card.dataset.v2ReachCard='1';card.innerHTML=`<div class="v2-reach-head"><div><h3>CTR & Impressões oficiais</h3><p>YouTube Reporting API, consultada somente quando você pedir. A abertura do dashboard nunca dispara Reporting e nenhuma métrica ausente é estimada.</p></div><button class="btn" type="button" data-v2-reach-load>Carregar métricas oficiais</button></div><div class="v2-reach-metrics"><div class="v2-reach-metric"><small>Impressões</small><strong data-v2-reach-impressions>—</strong></div><div class="v2-reach-metric"><small>CTR</small><strong data-v2-reach-ctr>—</strong></div><div class="v2-reach-metric"><small>Baseline do canal</small><strong data-v2-reach-baseline>—</strong></div></div><div class="v2-reach-message" data-v2-reach-message>Aguardando solicitação manual. Nenhuma chamada à Reporting API foi feita por este card.</div>`;host.insertAdjacentElement('afterend',card);const button=card.querySelector('[data-v2-reach-load]'),msg=card.querySelector('[data-v2-reach-message]');let loading=false;
    button.addEventListener('click',async()=>{if(loading)return;loading=true;button.disabled=true;button.textContent='Consultando Reporting…';msg.className='v2-reach-message';msg.textContent='Consultando somente leitura…';try{const r=await fetch('/api/v2/reporting/reach',{headers:{Accept:'application/json'}}),d=await r.json();if(!r.ok&&r.status!==503)throw new Error(d.detail||'Falha na Reporting API');if(d.data_available){card.querySelector('[data-v2-reach-impressions]').textContent=fmt(d.impressions);card.querySelector('[data-v2-reach-ctr]').textContent=d.ctr_percent==null?'—':`${Number(d.ctr_percent).toLocaleString('pt-BR',{maximumFractionDigits:3})}%`;card.querySelector('[data-v2-reach-baseline]').textContent=d.channel_ctr_baseline_percent==null?'—':`${Number(d.channel_ctr_baseline_percent).toLocaleString('pt-BR',{maximumFractionDigits:3})}%`;msg.classList.add('ok');msg.textContent=`Fonte: ${d.source||'youtube_reporting_api'} · oficial · sem estimativas.`}else{card.querySelector('[data-v2-reach-impressions]').textContent='—';card.querySelector('[data-v2-reach-ctr]').textContent='—';card.querySelector('[data-v2-reach-baseline]').textContent='—';msg.classList.add('warn');msg.textContent=esc(d.blocked_reason||d.error||d.detail||'Métricas oficiais ainda não disponíveis. Nenhuma estimativa foi criada.')+(d.write_required?' Um job de Reporting precisaria ser criado por ação administrativa separada; esta tela não faz isso.':'')}}catch(err){msg.classList.add('warn');msg.textContent='Reporting indisponível: '+esc(err.message||err)}finally{loading=false;button.disabled=false;button.textContent='Atualizar métricas oficiais'}});return true};
  if(!install()){const o=new MutationObserver(()=>{if(install())o.disconnect()});o.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>o.disconnect(),10000)}
})();
'''


def reach_ui_webengine_source() -> str:
    css_json = json.dumps(REACH_UI_CSS, ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-v2-reach-ui]')){"
        "const s=document.createElement('style');s.dataset.ycaV2ReachUi='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n" + REACH_UI_JS
    )
