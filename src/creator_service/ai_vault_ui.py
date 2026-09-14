from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


LEGACY_MARKER = '<article class="card full"><h3>Inteligência artificial externa opcional</h3>'
VAULT_MARKER = '<article class="card full" id="aiKeyVault">'

_CSS = r'''
<style data-ai-vault-manager-v2>
.legacy-ai-config{display:none!important}
#aiKeyVault .vault-manager-v2{display:grid;gap:14px}
#aiKeyVault .vault-add-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
#aiKeyVault .vault-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:10px;border:1px solid var(--line);border-radius:13px;background:color-mix(in srgb,var(--card2) 90%,transparent)}
#aiKeyVault .vault-toolbar .btn{min-height:40px}
#aiKeyVault .vault-selection-meta{margin-left:auto;color:var(--muted);font-size:12px;font-weight:700}
#aiKeyVault .vault-scroll{max-height:390px;overflow:auto;overscroll-behavior:contain;border:1px solid var(--line);border-radius:14px;background:var(--card2)}
#aiKeyVault .vault-key-row{display:grid;grid-template-columns:auto auto minmax(0,1fr) auto;gap:10px;align-items:center;padding:11px 12px;border-bottom:1px solid color-mix(in srgb,var(--line) 75%,transparent)}
#aiKeyVault .vault-key-row:last-child{border-bottom:0}
#aiKeyVault .vault-key-row:hover{background:color-mix(in srgb,var(--accent) 5%,var(--card2))}
#aiKeyVault .vault-key-row.selected{background:color-mix(in srgb,var(--accent) 9%,var(--card2))}
#aiKeyVault .vault-key-check,#aiKeyVault #vaultSelectAll{width:18px;height:18px;accent-color:var(--accent)}
#aiKeyVault .vault-status{font-size:19px;line-height:1}
#aiKeyVault .vault-key-main{min-width:0}.vault-key-name{display:flex;align-items:center;gap:7px;flex-wrap:wrap;font-weight:850}.vault-key-meta{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.vault-key-issue{color:var(--warn);font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
#aiKeyVault .vault-badges{display:flex;gap:6px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
#aiKeyVault .vault-model-panel{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:8px;padding:10px;border:1px solid var(--line);border-radius:13px;background:var(--card2)}
#aiKeyVault .vault-empty{padding:18px;text-align:center;color:var(--muted)}
#aiKeyVault .vault-provider-note{font-size:11px;color:var(--muted)}
@media(max-width:760px){#aiKeyVault .vault-add-grid{grid-template-columns:1fr}#aiKeyVault .vault-scroll{max-height:330px}#aiKeyVault .vault-toolbar{display:grid;grid-template-columns:1fr 1fr}#aiKeyVault .vault-toolbar .vault-select-all,#aiKeyVault .vault-selection-meta{grid-column:1/-1;margin-left:0}#aiKeyVault .vault-key-row{grid-template-columns:auto auto minmax(0,1fr)}#aiKeyVault .vault-badges{grid-column:3;justify-content:flex-start}#aiKeyVault .vault-model-panel{grid-template-columns:1fr}#aiKeyVault .vault-toolbar .btn{width:100%}}
</style>
'''

_SCRIPT = r'''
<script data-ai-vault-manager-v2>
(()=>{
  const root=document.getElementById('aiKeyVault');
  if(!root||root.dataset.vaultMounted==='1')return;
  root.dataset.vaultMounted='1';
  const selected=new Set();
  const modelCache={};
  let keys=[];
  const statusInfo={ok:['✅','Saudável'],warning:['⚠️','Atenção'],error:['❌','Erro'],unknown:['○','Não testada']};
  const providerName=()=>document.getElementById('keyProvider')?.value||'gemini';
  const baseUrl=()=>document.getElementById('keyBaseUrl')?.value||'';
  const selectedKeys=()=>keys.filter(k=>selected.has(String(k.id)));
  const oneSelected=()=>{const rows=selectedKeys();if(rows.length!==1){toast('Selecione exatamente uma chave para esta ação.',true);return null}return rows[0]};
  const escHtml=v=>typeof esc==='function'?esc(v):String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  function updateSelectionUi(){
    const n=selected.size;const meta=document.getElementById('vaultSelectionMeta');if(meta)meta.textContent=n?`${n} selecionada(s)`:'Nenhuma selecionada';
    const all=document.getElementById('vaultSelectAll');if(all){all.checked=!!keys.length&&n===keys.length;all.indeterminate=n>0&&n<keys.length}
    document.querySelectorAll('.vault-key-row').forEach(row=>row.classList.toggle('selected',selected.has(row.dataset.keyId)));
  }
  function render(){
    const list=document.getElementById('aiKeyList');if(!list)return;
    if(!keys.length){list.innerHTML='<div class="vault-empty">Nenhuma chave salva para este provedor.</div>';updateSelectionUi();return}
    list.innerHTML=keys.map(k=>{
      const id=String(k.id);const [icon,label]=statusInfo[k.status]||statusInfo.unknown;const name=escHtml(k.label||'Chave sem apelido');const model=escHtml(k.preferred_model||k.last_model||'Nenhum modelo selecionado');const issue=k.last_error?`<div class="vault-key-issue">${escHtml(k.last_error)}</div>`:'';
      return `<div class="vault-key-row" data-key-id="${escHtml(id)}"><input class="vault-key-check" type="checkbox" aria-label="Selecionar ${name}" data-key-id="${escHtml(id)}" ${selected.has(id)?'checked':''}><span class="vault-status" title="${label}">${icon}</span><div class="vault-key-main"><div class="vault-key-name">${name}</div><div class="vault-key-meta">${escHtml(k.masked||'')} · ${model}</div>${issue}</div><div class="vault-badges">${k.active?'<span class="pill good">ATIVA</span>':''}${!k.enabled?'<span class="pill">DESATIVADA</span>':''}</div></div>`;
    }).join('');updateSelectionUi();
  }
  async function load(){
    const status=document.getElementById('keyPoolStatus');if(status)status.textContent='Carregando cofre...';
    try{const d=await api('/api/ai/keys?provider='+encodeURIComponent(providerName()));keys=d.keys||[];const live=new Set(keys.map(k=>String(k.id)));[...selected].forEach(id=>{if(!live.has(id))selected.delete(id)});const rot=document.getElementById('rotationToggle');if(rot)rot.checked=!!d.auto_rotate;if(status)status.textContent=keys.length?`${keys.length} chave(s) salva(s). ${d.auto_rotate?'Rotação inteligente ativa.':'Rotação manual.'}`:'Nenhuma chave salva para este provedor.';render()}catch(e){if(status)status.textContent=e.message;toast(e.message,true)}
  }
  async function patchKey(id,payload){return api('/api/ai/keys/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({provider:providerName(),...payload})})}
  async function testKey(id,model=''){const d=await api('/api/ai/keys/'+encodeURIComponent(id)+'/test',{method:'POST',body:JSON.stringify({provider:providerName(),model,base_url:baseUrl()})});if(d.models)modelCache[id]=d.models;return d}
  root.innerHTML=`<div class="vault-manager-v2"><div><h3 style="margin-bottom:6px">Cofre de chaves e rotação inteligente</h3><p class="muted" style="margin:0">Gerencie várias credenciais por provedor. As chaves ficam criptografadas e só a versão mascarada volta para a interface.</p></div><div class="vault-add-grid"><label>Provedor<select id="keyProvider"><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="groq">Groq</option><option value="xai">xAI</option><option value="openai_compatible">OpenAI-compatible</option></select></label><label>Apelido da chave<input id="keyAlias" maxlength="80" placeholder="Ex.: Gemini principal"></label></div><label>Nova API key<input id="newApiKey" type="password" autocomplete="off" placeholder="Cole somente para adicionar ao cofre"></label><label>Endpoint personalizado<input id="keyBaseUrl" type="url" placeholder="Obrigatório apenas para OpenAI-compatible personalizado"></label><div class="vault-provider-note">Gemini, OpenAI, Groq e xAI têm integração própria. Endpoints adicionais funcionam quando expõem uma API OpenAI-compatible. Ollama local não usa chave neste cofre.</div><div class="toolbar"><button class="btn primary" id="addAiKey">Testar e adicionar chave</button><label class="pill"><input id="rotationToggle" type="checkbox" style="width:auto"> Rotação inteligente</label><button class="btn" id="refreshAiKeys">Atualizar lista</button></div><div id="keyPoolStatus" class="muted">Carregando cofre...</div><div class="vault-toolbar"><label class="pill vault-select-all"><input id="vaultSelectAll" type="checkbox"> Selecionar todas</label><button class="btn" id="vaultTest">Testar</button><button class="btn success" id="vaultModel">Modelo / usar</button><button class="btn" id="vaultRename">Renomear</button><button class="btn" id="vaultEnable">Ativar</button><button class="btn" id="vaultDisable">Desativar</button><button class="btn danger" id="vaultDelete">Excluir</button><span class="vault-selection-meta" id="vaultSelectionMeta">Nenhuma selecionada</span></div><div id="vaultModelPanel" class="vault-model-panel hidden"><select id="vaultModelSelect"><option value="">Carregue os modelos</option></select><button class="btn" id="vaultLoadModels">Carregar modelos</button><button class="btn success" id="vaultUseModel">Ativar / usar modelo</button></div><div id="aiKeyList" class="vault-scroll"></div></div>`;
  document.getElementById('aiKeyList').addEventListener('change',ev=>{const cb=ev.target.closest('.vault-key-check');if(!cb)return;cb.checked?selected.add(cb.dataset.keyId):selected.delete(cb.dataset.keyId);updateSelectionUi()});
  document.getElementById('vaultSelectAll').onchange=ev=>{selected.clear();if(ev.target.checked)keys.forEach(k=>selected.add(String(k.id)));render()};
  document.getElementById('keyProvider').onchange=()=>{selected.clear();document.getElementById('vaultModelPanel').classList.add('hidden');load()};
  document.getElementById('refreshAiKeys').onclick=load;
  document.getElementById('rotationToggle').onchange=async ev=>{try{await api('/api/ai/rotation',{method:'PUT',body:JSON.stringify({provider:providerName(),enabled:ev.target.checked})});toast(ev.target.checked?'Rotação inteligente ativada.':'Rotação inteligente desativada.');await load()}catch(e){ev.target.checked=!ev.target.checked;toast(e.message,true)}};
  document.getElementById('addAiKey').onclick=async()=>{const b=document.getElementById('addAiKey');const key=document.getElementById('newApiKey').value.trim();if(!key)return toast('Informe a nova API key.',true);setBusy(b,true,'Testando');try{const d=await api('/api/ai/keys',{method:'POST',body:JSON.stringify({provider:providerName(),api_key:key,label:document.getElementById('keyAlias').value.trim(),base_url:baseUrl()})});document.getElementById('newApiKey').value='';document.getElementById('keyAlias').value='';if(d.key?.id&&d.models)modelCache[String(d.key.id)]=d.models;toast(d.test_ok?`Chave salva. ${d.model_count} modelo(s) disponíveis.`:'Chave salva, mas o teste encontrou um problema.',!d.test_ok);await load()}catch(e){toast(e.message,true)}finally{setBusy(b,false)}};
  document.getElementById('vaultTest').onclick=async()=>{const rows=selectedKeys();if(!rows.length)return toast('Selecione pelo menos uma chave.',true);for(const k of rows){try{await testKey(String(k.id),'')}catch(e){toast(`${k.label||'Chave'}: ${e.message}`,true)}}await load()};
  document.getElementById('vaultRename').onclick=async()=>{const k=oneSelected();if(!k)return;const next=prompt('Novo apelido para esta chave:',k.label||'');if(next===null)return;try{await patchKey(String(k.id),{label:next});toast('Apelido atualizado.');await load()}catch(e){toast(e.message,true)}};
  document.getElementById('vaultEnable').onclick=async()=>{const rows=selectedKeys();if(!rows.length)return toast('Selecione pelo menos uma chave.',true);try{for(const k of rows)await patchKey(String(k.id),{enabled:true});toast(`${rows.length} chave(s) ativada(s).`);await load()}catch(e){toast(e.message,true)}};
  document.getElementById('vaultDisable').onclick=async()=>{const rows=selectedKeys();if(!rows.length)return toast('Selecione pelo menos uma chave.',true);try{for(const k of rows)await patchKey(String(k.id),{enabled:false});toast(`${rows.length} chave(s) desativada(s).`);await load()}catch(e){toast(e.message,true)}};
  document.getElementById('vaultDelete').onclick=async()=>{const rows=selectedKeys();if(!rows.length)return toast('Selecione pelo menos uma chave.',true);if(!confirm(`Excluir ${rows.length} chave(s) do cofre? Esta ação não pode ser desfeita.`))return;try{for(const k of rows)await api('/api/ai/keys/'+encodeURIComponent(k.id)+'?provider='+encodeURIComponent(providerName()),{method:'DELETE'});selected.clear();toast(`${rows.length} chave(s) excluída(s).`);await load()}catch(e){toast(e.message,true)}};
  document.getElementById('vaultModel').onclick=async()=>{const k=oneSelected();if(!k)return;const panel=document.getElementById('vaultModelPanel');panel.classList.remove('hidden');document.getElementById('vaultModelSelect').dataset.keyId=String(k.id);document.getElementById('vaultModelSelect').innerHTML=`<option value="${escHtml(k.preferred_model||k.last_model||'')}">${escHtml(k.preferred_model||k.last_model||'Carregue os modelos')}</option>`};
  document.getElementById('vaultLoadModels').onclick=async()=>{const sel=document.getElementById('vaultModelSelect');const id=sel.dataset.keyId;if(!id)return toast('Selecione uma chave e abra Modelo / usar.',true);try{const d=await testKey(id,'');const models=d.models||[];sel.innerHTML=models.length?models.map(m=>`<option value="${escHtml(m)}">${escHtml(m)}</option>`).join(''):'<option value="">Nenhum modelo compatível encontrado</option>';toast(`${models.length} modelo(s) compatíveis encontrados.`);await load()}catch(e){toast(e.message,true)}};
  document.getElementById('vaultUseModel').onclick=async()=>{const sel=document.getElementById('vaultModelSelect');const id=sel.dataset.keyId;const model=sel.value;if(!id||!model)return toast('Selecione uma chave e um modelo.',true);try{await testKey(id,model);await patchKey(id,{preferred_model:model,make_active:true});await api('/api/ai/config',{method:'PUT',body:JSON.stringify({provider:providerName(),model,api_key:null,base_url:baseUrl(),validate_connection:false})});toast('Chave ativa e modelo selecionado.');await load();if(typeof loadStatus==='function')await loadStatus()}catch(e){toast(e.message,true)}};
  setTimeout(load,220);
})();
</script>
'''


def enhance_ai_vault_html(source: str) -> str:
    if 'data-ai-vault-manager-v2' in source:
        return source
    if VAULT_MARKER not in source:
        raise RuntimeError('AI key vault UI marker not found in dashboard HTML.')
    if LEGACY_MARKER in source:
        source = source.replace(
            LEGACY_MARKER,
            '<article class="card full legacy-ai-config" hidden aria-hidden="true"><h3>Inteligência artificial externa opcional</h3>',
            1,
        )
    if '</head>' not in source or '</body>' not in source:
        raise RuntimeError('AI key vault enhancement requires complete HTML.')
    source = source.replace('</head>', _CSS + '\n</head>', 1)
    return source.replace('</body>', _SCRIPT + '\n</body>', 1)


def _find_dashboard_route(app: FastAPI) -> APIRoute:
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.path == '/dashboard' and 'GET' in (route.methods or set()):
            return route
    raise RuntimeError('Dashboard route not found for AI vault UX enhancement.')


def install_ai_vault_ui(app: FastAPI) -> None:
    route = _find_dashboard_route(app)
    original = route.endpoint
    app.router.routes.remove(route)

    async def enhanced_dashboard(request: Request):
        response = await original(request)
        if not isinstance(response, HTMLResponse):
            return response
        body = response.body.decode('utf-8')
        headers = dict(response.headers)
        headers.pop('content-length', None)
        headers.pop('content-type', None)
        headers['Cache-Control'] = 'no-store'
        return HTMLResponse(
            enhance_ai_vault_html(body),
            status_code=response.status_code,
            headers=headers,
        )

    app.add_api_route(
        '/dashboard',
        enhanced_dashboard,
        methods=['GET'],
        include_in_schema=False,
        name='ai_vault_dashboard',
    )
