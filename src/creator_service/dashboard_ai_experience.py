from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_CSS = r'''
<style data-yca-ai-experience>
.vault-use-selection{display:flex;gap:8px;flex-wrap:wrap;padding:10px;border:1px solid color-mix(in srgb,var(--accent) 32%,var(--line));border-radius:13px;background:color-mix(in srgb,var(--accent) 5%,var(--card2))}.vault-use-selection .hint{flex:1 1 100%;color:var(--muted);font-size:12px}.advice-block{display:grid;gap:10px;margin-top:10px}.advice-head{border:1px solid color-mix(in srgb,var(--accent) 45%,var(--line));border-radius:14px;padding:12px;background:color-mix(in srgb,var(--accent) 6%,var(--card2))}.advice-group{display:grid;gap:8px}.advice-group h4{margin:4px 0 0}.advice-item{border:1px solid var(--line);border-radius:13px;padding:12px;background:var(--card2)}.advice-item b{display:block;margin-bottom:5px}.advice-item p{margin:5px 0;color:var(--muted)}.advice-evidence{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.advice-plan{display:grid;grid-template-columns:1fr 1fr;gap:10px}.advice-plan>div{border:1px solid var(--line);border-radius:13px;padding:12px;background:var(--card2)}.advice-plan ul{padding-left:18px;margin:6px 0}.ai-error-help{margin-top:8px;color:var(--muted);font-size:12px}@media(max-width:760px){.advice-plan{grid-template-columns:1fr}.vault-use-selection .btn{flex:1 1 100%}}
</style>
'''

_SCRIPT = r'''
<script data-yca-ai-experience>
(()=>{
  if(window.__ycaAiExperience)return;window.__ycaAiExperience=true;
  const escx=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const pretty=v=>typeof v==='object'?JSON.stringify(v):String(v??'—');
  function selectedKeyIds(){return [...document.querySelectorAll('#aiKeyVault .vault-key-check:checked')].map(x=>x.dataset.keyId).filter(Boolean)}
  async function applyKeySelection(rotation){
    const ids=selectedKeyIds();if(!ids.length)return toast('Marque pelo menos uma chave.',true);
    const provider=document.getElementById('keyProvider')?.value||'gemini';
    const button=rotation?document.getElementById('vaultRotateSelected'):document.getElementById('vaultUseSelectedOnly');
    setBusy(button,true,rotation?'Configurando rotação':'Selecionando');
    try{
      await api('/api/ai/selection',{method:'PUT',body:JSON.stringify({provider,key_ids:ids,rotation})});
      toast(rotation?`${ids.length} chave(s) selecionada(s) entrarão na rotação.`:'Somente a seleção marcada ficará disponível para a IA.');
      document.getElementById('refreshAiKeys')?.click();
      if(typeof loadStatus==='function')await loadStatus();
    }catch(e){toast(e.message,true)}finally{setBusy(button,false)}
  }
  function installSelectionControls(){
    const vault=document.getElementById('aiKeyVault');if(!vault||document.getElementById('vaultUseSelectedOnly'))return false;
    const toolbar=vault.querySelector('.vault-toolbar');if(!toolbar)return false;
    const box=document.createElement('div');box.className='vault-use-selection';
    box.innerHTML='<div class="hint"><b>Quais chaves a IA pode usar?</b> Marque exatamente as desejadas. Chaves não marcadas serão desativadas e nunca entrarão no fallback.</div><button class="btn success" id="vaultUseSelectedOnly">Usar somente selecionadas</button><button class="btn primary" id="vaultRotateSelected">Rotacionar selecionadas</button>';
    toolbar.insertAdjacentElement('afterend',box);
    document.getElementById('vaultUseSelectedOnly').onclick=()=>applyKeySelection(false);
    document.getElementById('vaultRotateSelected').onclick=()=>applyKeySelection(true);
    return true;
  }
  const vaultTimer=setInterval(()=>{if(installSelectionControls())clearInterval(vaultTimer)},120);
  setTimeout(()=>clearInterval(vaultTimer),10000);

  function actionHtml(item){
    const ev=item.evidence||{};const pills=Object.entries(ev).map(([k,v])=>`<span class="pill">${escx(k)}: ${escx(pretty(v))}</span>`).join('');
    return `<div class="advice-item"><b>${escx(item.title||'Ação recomendada')}</b>${item.why?`<p>${escx(item.why)}</p>`:''}<p><strong>O que fazer:</strong> ${escx(item.action||'')}</p>${pills?`<div class="advice-evidence">${pills}</div>`:''}</div>`;
  }
  function listGroup(title,items){return Array.isArray(items)&&items.length?`<div class="advice-group"><h4>${escx(title)}</h4>${items.map(actionHtml).join('')}</div>`:''}
  function adviceHtml(advice){
    if(!advice)return '';
    if(advice.status!=='ready')return `<div class="advice-head"><b>Dados reais coletados, IA de recomendações indisponível</b><div class="muted">${escx(advice.error||'A camada de recomendação não respondeu. Os dados factuais abaixo continuam válidos.')}</div></div>`;
    const week=(advice.next_7_days||[]).map(x=>`<li>${escx(x)}</li>`).join('');const month=(advice.next_30_days||[]).map(x=>`<li>${escx(x)}</li>`).join('');
    return `<div class="advice-block"><div class="advice-head"><b>Diagnóstico estratégico · ${escx(advice.health||'')}</b><div>${escx(advice.executive_summary||'')}</div><div class="muted" style="margin-top:6px">Recomendações ancoradas em YouTube/Analytics. Métricas não são inventadas pela IA.</div></div>${listGroup('Prioridades',advice.priorities)}${listGroup('SEO e descoberta',advice.seo_actions)}${listGroup('Analytics e medição',advice.analytics_actions)}${listGroup('Conteúdo',advice.content_actions)}${week||month?`<div class="advice-plan"><div><b>Próximos 7 dias</b><ul>${week||'<li>Sem ação adicional validada.</li>'}</ul></div><div><b>Próximos 30 dias</b><ul>${month||'<li>Sem ação adicional validada.</li>'}</ul></div></div>`:''}</div>`;
  }
  function extractRaw(node){const pre=node.querySelector('.tech-details pre');if(pre){try{return JSON.parse(pre.textContent)}catch{}}const text=node.textContent.trim();if(text.startsWith('{')){try{return JSON.parse(text)}catch{}}return null}
  function enhanceResult(node,kind){
    if(!node)return;const raw=extractRaw(node);if(!raw)return;
    const advice=kind==='audit'?raw.ai_advice:(raw.strategy||raw.ai_advice);if(!advice)return;
    const signature=JSON.stringify(advice);const existing=node.querySelector(':scope > .ai-advice-render');
    if(existing&&node.dataset.aiAdviceSignature===signature)return;
    existing?.remove();
    const details=node.querySelector('.tech-details');const holder=document.createElement('div');holder.className='ai-advice-render';holder.innerHTML=adviceHtml(advice);node.insertBefore(holder,details||null);node.dataset.aiAdviceSignature=signature;
    if(details){const summary=details.querySelector('summary');if(summary)summary.textContent='Dados técnicos (opcional)';details.open=false}
  }
  [['auditRaw','audit'],['strategyResult','strategy']].forEach(([id,kind])=>{const node=document.getElementById(id);if(!node)return;let pending=false;const obs=new MutationObserver(()=>{if(pending)return;pending=true;setTimeout(()=>{pending=false;enhanceResult(node,kind)},0)});obs.observe(node,{childList:true,subtree:true,characterData:true});setTimeout(()=>enhanceResult(node,kind),250)});

  function clearOnClick(buttonId,resultId){const b=document.getElementById(buttonId),out=document.getElementById(resultId);if(!b||!out)return;b.addEventListener('click',()=>{out.classList.add('hidden');out.textContent='';delete out.dataset.aiAdviceSignature},{capture:true})}
  clearOnClick('buildStrategy','strategyResult');clearOnClick('researchTopic','researchResult');clearOnClick('validateKeywords','keywordResult');

  const oldApi=window.api;
  if(typeof oldApi==='function'){
    window.api=async function(url,options={}){try{return await oldApi(url,options)}catch(e){if(String(e.message||'').match(/^Erro HTTP 5\d\d$/))e.message='O servidor não conseguiu concluir esta análise. Nenhuma alteração foi feita. Atualize a tela e, se persistir, teste a chave ativa em Ajustes.';throw e}}
  }
})();
</script>
'''


def enhance_ai_experience_html(source: str) -> str:
    if "data-yca-ai-experience" in source:
        return source
    if "</head>" not in source or "</body>" not in source:
        return source
    return source.replace("</head>", _CSS + "\n</head>", 1).replace("</body>", _SCRIPT + "\n</body>", 1)


def install_dashboard_ai_experience(app: FastAPI) -> None:
    route = next(
        route for route in app.router.routes
        if isinstance(route, APIRoute) and route.path == "/dashboard" and "GET" in (route.methods or set())
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
        return HTMLResponse(
            enhance_ai_experience_html(response.body.decode("utf-8")),
            status_code=response.status_code,
            headers=headers,
        )

    app.add_api_route(
        "/dashboard",
        dashboard,
        methods=["GET"],
        include_in_schema=False,
        name="dashboard_ai_experience",
    )
