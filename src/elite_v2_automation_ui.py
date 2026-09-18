from __future__ import annotations

import json

AUTOMATION_UI_CSS = r'''
.v2-automation{grid-column:1/-1;border:1px solid var(--v2-border);border-radius:20px;padding:16px;background:linear-gradient(145deg,rgba(15,27,44,.94),rgba(6,14,25,.93));box-shadow:var(--v2-shadow);margin-top:10px}.v2-automation-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}.v2-automation-head h3{margin:0;font-size:15px}.v2-automation-head p{margin:4px 0 0;color:var(--v2-muted);font-size:11px;max-width:740px}.v2-automation-list{display:grid;gap:8px;margin-top:12px}.v2-automation-item{border:1px solid rgba(148,163,184,.11);border-radius:14px;padding:11px;background:rgba(5,13,24,.38);display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px}.v2-automation-item h4{margin:0;font-size:11px}.v2-automation-item p{margin:4px 0 0;color:var(--v2-muted);font-size:9px}.v2-automation-actions{display:flex;gap:6px;align-items:center;flex-wrap:wrap}.v2-automation-state{display:inline-flex;padding:5px 7px;border-radius:999px;border:1px solid rgba(148,163,184,.13);font-size:8px;color:var(--v2-muted);text-transform:uppercase}.v2-automation-empty{padding:20px;text-align:center;color:var(--v2-muted);font-size:10px}@media(max-width:760px){.v2-automation-item{grid-template-columns:1fr}.v2-automation-actions .btn{flex:1}}
'''

AUTOMATION_UI_JS = r'''
(()=>{
 const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
 const install=()=>{if(document.querySelector('[data-v2-automation]'))return true;const section=document.getElementById('audit'),grid=section&&section.querySelector('.grid');if(!grid)return false;const box=document.createElement('article');box.className='v2-automation';box.dataset.v2Automation='1';box.innerHTML=`<div class="v2-automation-head"><div><h3>Automation & Approvals</h3><p>A fila guarda propostas de IA para revisão. Aprovar uma proposta não escreve no YouTube; o encaminhamento apenas libera o próximo passo no Write Gateway.</p></div><button class="btn" type="button" data-v2-automation-refresh>Atualizar fila</button></div><div class="v2-automation-list" data-v2-automation-list><div class="v2-automation-empty">Nenhuma proposta carregada.</div></div>`;grid.append(box);const list=box.querySelector('[data-v2-automation-list]'),refresh=box.querySelector('[data-v2-automation-refresh]');
 const action=async(url,body={})=>{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Ação não concluída');if(d.youtube_write_performed!==false)throw new Error('Contrato de segurança inválido');return d};
 const load=async()=>{refresh.disabled=true;try{const r=await fetch('/api/v2/automation?limit=100',{headers:{Accept:'application/json'}}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Falha ao ler fila');const rows=d.items||[];list.innerHTML=rows.length?rows.map(item=>`<div class="v2-automation-item" data-item="${esc(item.item_id)}"><div><h4>${esc(item.intent)} · ${esc(item.provider)}</h4><p>${esc(item.target_kind||'sem alvo')} ${esc(item.target_id||'')} · criado ${esc((item.created_at||'').slice(0,19))}</p><span class="v2-automation-state">${esc(item.state)}</span></div><div class="v2-automation-actions">${item.state==='awaiting_approval'?'<button class="btn" data-act="approve">Aprovar proposta</button><button class="btn" data-act="cancel">Cancelar</button>':''}${item.state==='approved'?'<button class="btn primary" data-act="handoff">Encaminhar ao Write Gateway</button><button class="btn" data-act="cancel">Cancelar</button>':''}</div></div>`).join(''):'<div class="v2-automation-empty">Nenhuma proposta pendente nesta sessão.</div>'}catch(err){list.innerHTML=`<div class="v2-automation-empty">${esc(err.message||err)}</div>`}finally{refresh.disabled=false}};
 list.addEventListener('click',async ev=>{const button=ev.target.closest('button[data-act]');if(!button)return;const row=button.closest('[data-item]'),id=row?.dataset.item;if(!id)return;button.disabled=true;try{if(button.dataset.act==='approve')await action(`/api/v2/automation/approve/${encodeURIComponent(id)}`,{confirmed:true});else if(button.dataset.act==='cancel')await action(`/api/v2/automation/cancel/${encodeURIComponent(id)}`);else if(button.dataset.act==='handoff')await action(`/api/v2/automation/handoff/${encodeURIComponent(id)}`,{confirmed:true});await load()}catch(err){button.disabled=false;button.textContent=esc(err.message||err)}});refresh.addEventListener('click',load);document.querySelector('.nav button[data-tab="audit"]')?.addEventListener('click',()=>setTimeout(load,120));return true};
 if(!install()){const o=new MutationObserver(()=>{if(install())o.disconnect()});o.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>o.disconnect(),10000)}
})();
'''


def automation_ui_webengine_source() -> str:
    css_json = json.dumps(AUTOMATION_UI_CSS, ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-v2-automation-ui]')){"
        "const s=document.createElement('style');s.dataset.ycaV2AutomationUi='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n" + AUTOMATION_UI_JS
    )
