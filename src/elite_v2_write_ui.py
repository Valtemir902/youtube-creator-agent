from __future__ import annotations

import json

WRITE_UI_CSS = r'''
.v2-write-control{grid-column:1/-1;border:1px solid var(--v2-border);border-radius:18px;padding:15px;background:linear-gradient(145deg,rgba(18,31,50,.9),rgba(7,17,31,.82));box-shadow:var(--v2-shadow)}.v2-write-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.v2-write-head h3{margin:0;font-size:14px}.v2-write-head p{margin:4px 0 0;color:var(--v2-muted);font-size:11px;max-width:760px}.v2-write-state{display:inline-flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid rgba(251,191,36,.22);border-radius:999px;color:#fde68a;background:rgba(251,191,36,.07);font-size:10px;font-weight:900;white-space:nowrap}.v2-write-state.enabled{border-color:rgba(52,211,153,.24);color:#bbf7d0;background:rgba(52,211,153,.07)}.v2-write-body{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:end;margin-top:12px}.v2-write-body label{font-size:10px}.v2-write-actions{display:flex;gap:7px}.v2-write-rules{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:11px}.v2-write-rule{border:1px solid rgba(148,163,184,.1);border-radius:12px;padding:9px;background:rgba(5,13,24,.34);font-size:10px;color:var(--v2-muted)}.v2-write-rule b{display:block;color:#dcecff;margin-bottom:2px}@media(max-width:760px){.v2-write-head{flex-direction:column}.v2-write-body{grid-template-columns:1fr}.v2-write-actions .btn{flex:1}.v2-write-rules{grid-template-columns:1fr}}
'''

WRITE_UI_JS = r'''
(()=>{
  const esc=value=>String(value??'').replace(/[&<>\"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const install=async()=>{if(document.querySelector('[data-v2-write-control]'))return true;const section=document.getElementById('settings'),grid=section&&section.querySelector('.grid');if(!grid)return false;const card=document.createElement('article');card.className='v2-write-control';card.dataset.v2WriteControl='1';card.innerHTML=`<div class="v2-write-head"><div><h3>Write Gateway · gerenciamento manual</h3><p>O aplicativo inicia bloqueado a cada abertura. Prévia pode ser preparada bloqueada; aplicar alterações no YouTube só é liberado nesta sessão após confirmação explícita.</p></div><span class="v2-write-state" data-v2-write-state>Bloqueado</span></div><div class="v2-write-body"><label>Confirmação da sessão<input data-v2-write-confirm autocomplete="off" spellcheck="false" placeholder="Carregando frase de confirmação…"></label><div class="v2-write-actions"><button class="btn primary" type="button" data-v2-write-enable>Ativar gerenciamento</button><button class="btn" type="button" data-v2-write-disable>Bloquear agora</button></div></div><div class="v2-write-rules"><div class="v2-write-rule"><b>Preview primeiro</b>Nenhum botão de edição pula a comparação antes/depois.</div><div class="v2-write-rule"><b>Readback obrigatório</b>Sucesso só é declarado depois de reler o estado no YouTube.</div><div class="v2-write-rule"><b>Exclusões separadas</b>Ações destrutivas exigem confirmação específica do alvo e não prometem undo.</div></div><div class="v2-command-result" data-v2-write-message>Nenhuma escrita no YouTube foi executada por este controle.</div>`;const ai=grid.querySelector('[data-v2-ai-workspace]');if(ai)ai.insertAdjacentElement('afterend',card);else grid.prepend(card);
    const state=card.querySelector('[data-v2-write-state]'),input=card.querySelector('[data-v2-write-confirm]'),msg=card.querySelector('[data-v2-write-message]'),enable=card.querySelector('[data-v2-write-enable]'),disable=card.querySelector('[data-v2-write-disable]');let required='ATIVAR GERENCIAMENTO';
    const paint=enabled=>{state.textContent=enabled?'Ativo nesta sessão':'Bloqueado';state.classList.toggle('enabled',enabled);enable.disabled=enabled;disable.disabled=!enabled};
    try{const r=await fetch('/api/v2/write-mode',{headers:{Accept:'application/json'}}),d=await r.json();required=d.confirmation_required||required;input.placeholder=required;paint(!!d.enabled)}catch(err){msg.textContent='Não foi possível consultar o Write Gateway: '+esc(err.message)}
    enable.addEventListener('click',async()=>{if(input.value!==required){msg.textContent=`Digite exatamente: ${required}`;return}enable.disabled=true;try{const r=await fetch('/api/v2/write-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:true,confirmation:input.value})}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Falha ao ativar');paint(!!d.enabled);input.value='';msg.textContent='Gerenciamento manual liberado somente nesta sessão. Cada alteração ainda exige preview e confirmação própria.'}catch(err){msg.textContent=err.message;paint(false)}});
    disable.addEventListener('click',async()=>{try{const r=await fetch('/api/v2/write-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:false})}),d=await r.json();if(!r.ok)throw new Error(d.detail||'Falha ao bloquear');paint(false);msg.textContent='Gerenciamento bloqueado novamente. Nenhuma escrita é permitida até nova ativação.'}catch(err){msg.textContent=err.message}});return true};
  if(!install()){const o=new MutationObserver(()=>install().then(ok=>{if(ok)o.disconnect()}));o.observe(document.documentElement,{childList:true,subtree:true});setTimeout(()=>o.disconnect(),8000)}
})();
'''


def write_ui_webengine_source() -> str:
    css_json = json.dumps(WRITE_UI_CSS, ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-v2-write-ui]')){"
        "const s=document.createElement('style');s.dataset.ycaV2WriteUi='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n" + WRITE_UI_JS
    )
