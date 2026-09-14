from __future__ import annotations

import json

AI_EXEC_CSS = r'''
.v2-ai-exec-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}.v2-ai-provider-health{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.v2-ai-provider-chip{padding:5px 8px;border-radius:999px;border:1px solid rgba(148,163,184,.13);font-size:9px;color:var(--v2-muted)}.v2-ai-provider-chip.ok{color:#bbf7d0;border-color:rgba(52,211,153,.25)}.v2-ai-proposal{margin-top:8px;white-space:pre-wrap;word-break:break-word;max-height:260px;overflow:auto;color:#cbd9ea;font-size:10px}
'''

AI_EXEC_JS = r'''
(()=>{
 const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
 const install=async()=>{const host=document.querySelector('[data-v2-ai-controls]');if(!host||host.querySelector('[data-v2-ai-exec]'))return false;const wrap=document.createElement('div');wrap.dataset.v2AiExec='1';wrap.innerHTML=`<div class="v2-ai-provider-health" data-v2-ai-health><span class="v2-ai-provider-chip">Consultando provedores…</span></div><div class="v2-ai-exec-actions"><button class="btn primary" type="button" data-v2-ai-propose>Gerar proposta com o motor selecionado</button><label style="display:flex;align-items:center;gap:6px;font-size:10px;color:var(--v2-muted)"><input type="checkbox" data-v2-ai-enqueue> Enviar proposta para fila de aprovação</label></div><div class="v2-command-result"><b>Proposta estruturada</b><pre class="v2-ai-proposal" data-v2-ai-proposal>Nenhuma chamada de IA executada.</pre></div>`;host.append(wrap);const health=wrap.querySelector('[data-v2-ai-health]'),out=wrap.querySelector('[data-v2-ai-proposal]'),button=wrap.querySelector('[data-v2-ai-propose]');
 try{const r=await fetch('/api/v2/ai/status',{headers:{Accept:'application/json'}}),d=await r.json();health.innerHTML=(d.providers||[]).map(p=>`<span class="v2-ai-provider-chip ${p.available?'ok':''}" title="${esc(p.reason||p.model||'Disponível')}">${esc(p.provider)} · ${p.available?'pronto':'indisponível'}</span>`).join('')||'<span class="v2-ai-provider-chip">Status indisponível</span>'}catch(err){health.innerHTML=`<span class="v2-ai-provider-chip">${esc(err.message||err)}</span>`}
 button.addEventListener('click',async()=>{const command=host.querySelector('[data-v2-command-input]')?.value?.trim()||'';if(!command){out.textContent='Digite um comando primeiro.';return}const provider=localStorage.getItem('yca.eliteV2.provider')||'local';button.disabled=true;button.textContent='Gerando proposta…';out.textContent='Aguardando somente a proposta. Nenhuma escrita será executada.';try{const context={source:'user_selected_context'};const r=await fetch('/api/v2/ai/propose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider,command,context,enqueue:wrap.querySelector('[data-v2-ai-enqueue]').checked})}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Falha ao gerar proposta');if(d.youtube_write_performed!==false)throw new Error('Contrato de segurança da IA inválido');out.textContent=JSON.stringify({provider:d.provider,model:d.model,intent:d.intent,facts:d.facts,proposed_changes:d.proposed_changes,confidence:d.confidence,limitations:d.limitations,requires_explicit_approval:d.requires_explicit_approval,automation_item:d.automation_item||null},null,2)}catch(err){out.textContent='Proposta não liberada: '+esc(err.message||err)}finally{button.disabled=false;button.textContent='Gerar proposta com o motor selecionado'}});return true};
 if(!install()){const o=new MutationObserver(()=>{if(install())o.disconnect()});o.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>o.disconnect(),10000)}
})();
'''


def ai_execution_ui_webengine_source() -> str:
    css_json = json.dumps(AI_EXEC_CSS, ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-v2-ai-exec]')){"
        "const s=document.createElement('style');s.dataset.ycaV2AiExec='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n" + AI_EXEC_JS
    )
