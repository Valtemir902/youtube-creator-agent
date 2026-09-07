from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .cloud_auth import IntrospectionTokenVerifier
from .cloud_runtime import CloudTenantResolver
from .onboarding_api import COOKIE_NAME, AuthenticatedTenant, create_app as create_base_app
from .onboarding_service import OnboardingService
from .onboarding_sessions import OnboardingSessionStore


class AIKeyCreateRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    api_key: str = Field(min_length=4, max_length=5000)
    label: str = Field(default="", max_length=80)
    base_url: str = Field(default="", max_length=1000)


class AIKeyUpdateRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    label: str | None = Field(default=None, max_length=80)
    preferred_model: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
    make_active: bool | None = None


class AIKeyTestRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=1000)


class AIRotationRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    enabled: bool


def _enhance_dashboard_html(source: str) -> str:
    if 'id="aiKeyVault"' in source:
        return source

    marker = '<article class="card full"><h3>Inteligência artificial externa opcional</h3>'
    panel = r'''
          <article class="card full" id="aiKeyVault">
            <h3>Cofre de chaves e rotação inteligente</h3>
            <p class="muted" style="margin-top:-2px">Salve várias credenciais por provedor. As chaves ficam criptografadas e nunca são exibidas novamente. Falhas temporárias podem acionar a próxima chave automaticamente.</p>
            <div class="form">
              <div class="row">
                <label>Provedor<select id="keyProvider"><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="groq">Groq</option><option value="xai">xAI</option><option value="openai_compatible">OpenAI-compatible</option></select></label>
                <label>Apelido da chave<input id="keyAlias" maxlength="80" placeholder="Ex.: Gemini principal, OpenAI trabalho"></label>
              </div>
              <label>Nova API key<input id="newApiKey" type="password" autocomplete="off" placeholder="Cole a chave somente para adicionar ao cofre"></label>
              <label>Endpoint personalizado<input id="keyBaseUrl" type="url" placeholder="Somente para APIs compatíveis/customizadas"></label>
              <div class="toolbar">
                <button class="btn primary" id="addAiKey">Testar e adicionar chave</button>
                <label class="pill" style="cursor:pointer"><input id="rotationToggle" type="checkbox" style="width:auto"> Rotação inteligente</label>
                <button class="btn" id="refreshAiKeys">Atualizar lista</button>
              </div>
            </div>
            <div id="keyPoolStatus" class="muted" style="margin:12px 0 8px">Carregando cofre...</div>
            <div id="aiKeyList" class="key-vault-list"></div>
          </article>
'''
    if marker in source:
        source = source.replace(marker, panel + '\n          ' + marker, 1)

    style_marker = '</style>'
    extra_style = r'''
    .key-vault-list{display:grid;gap:10px}.key-vault-item{border:1px solid var(--line);border-radius:14px;background:var(--card2);padding:12px;display:grid;gap:10px}.key-vault-head{display:flex;gap:10px;align-items:flex-start;justify-content:space-between}.key-vault-name{font-weight:900}.key-vault-meta{color:var(--muted);font-size:12px;word-break:break-word}.key-status{font-size:18px;line-height:1}.key-model-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}.key-vault-actions{display:flex;gap:7px;flex-wrap:wrap}.key-vault-actions .btn{min-height:44px}.key-error{font-size:12px;color:var(--bad);background:color-mix(in srgb,var(--bad) 8%,var(--card2));border:1px solid color-mix(in srgb,var(--bad) 35%,var(--line));border-radius:10px;padding:8px;word-break:break-word}.key-warning{color:var(--warn)}@media(max-width:760px){.key-model-row{grid-template-columns:1fr}.key-vault-actions .btn{flex:1 1 44%}}
'''
    source = source.replace(style_marker, extra_style + '\n  ' + style_marker, 1)

    js_marker = 'refreshAll();'
    extra_js = r'''
const keyModelCache={};
function keyStatusIcon(status){return status==='ok'?'✅':status==='warning'?'⚠️':status==='error'?'❌':'○'}
function currentKeyProvider(){return $('keyProvider')?.value||'gemini'}
function currentKeyBaseUrl(){return $('keyBaseUrl')?.value||''}
async function loadAiKeyPool(){
  if(!$('aiKeyList'))return;
  const provider=currentKeyProvider();
  $('keyPoolStatus').textContent='Carregando chaves de '+provider+'...';
  try{
    const d=await api('/api/ai/keys?provider='+encodeURIComponent(provider));
    $('rotationToggle').checked=!!d.auto_rotate;
    const keys=d.keys||[];
    $('keyPoolStatus').textContent=keys.length?`${keys.length} chave(s) salva(s). ${d.auto_rotate?'Rotação inteligente ativa.':'Rotação manual.'}`:'Nenhuma chave salva para este provedor.';
    $('aiKeyList').innerHTML=keys.map(k=>{
      const name=esc(k.label||'Chave sem apelido'); const active=k.active?'<span class="pill good">ATIVA</span>':''; const disabled=!k.enabled?'<span class="pill">DESATIVADA</span>':'';
      const model=k.preferred_model||k.last_model||'';
      const opts=(keyModelCache[k.id]||[]); const modelOptions=opts.length?opts.map(m=>`<option value="${esc(m)}" ${m===model?'selected':''}>${esc(m)}</option>`).join(''):(model?`<option value="${esc(model)}">${esc(model)}</option>`:'<option value="">Carregue os modelos</option>');
      const err=k.last_error?`<div class="${k.status==='warning'?'key-error key-warning':'key-error'}">${esc(k.last_error)}</div>`:'';
      return `<div class="key-vault-item" data-key-id="${esc(k.id)}"><div class="key-vault-head"><div><div class="key-vault-name">${keyStatusIcon(k.status)} ${name} ${active} ${disabled}</div><div class="key-vault-meta">${esc(k.masked||'')} · último modelo: ${esc(k.last_model||'nenhum')}</div></div><span class="key-status" title="${esc(k.status||'unknown')}">${keyStatusIcon(k.status)}</span></div>${err}<div class="key-model-row"><select class="key-model" data-key-id="${esc(k.id)}">${modelOptions}</select><button class="btn key-load-models" data-key-id="${esc(k.id)}">Modelos</button></div><div class="key-vault-actions"><button class="btn success key-use" data-key-id="${esc(k.id)}">Ativar / usar modelo</button><button class="btn key-test" data-key-id="${esc(k.id)}">Testar</button><button class="btn key-rename" data-key-id="${esc(k.id)}" data-label="${name}">Renomear</button><button class="btn key-toggle" data-key-id="${esc(k.id)}" data-enabled="${k.enabled?'1':'0'}">${k.enabled?'Desativar':'Ativar chave'}</button><button class="btn danger key-delete" data-key-id="${esc(k.id)}">Excluir</button></div></div>`;
    }).join('');
  }catch(e){$('keyPoolStatus').textContent=e.message;toast(e.message,true)}
}
async function testStoredKey(id,model=''){
  const d=await api('/api/ai/keys/'+encodeURIComponent(id)+'/test',{method:'POST',body:JSON.stringify({provider:currentKeyProvider(),model:model||'',base_url:currentKeyBaseUrl()})});
  if(d.models)keyModelCache[id]=d.models; return d;
}
if($('keyProvider'))$('keyProvider').onchange=loadAiKeyPool;
if($('refreshAiKeys'))$('refreshAiKeys').onclick=loadAiKeyPool;
if($('rotationToggle'))$('rotationToggle').onchange=async()=>{try{await api('/api/ai/rotation',{method:'PUT',body:JSON.stringify({provider:currentKeyProvider(),enabled:$('rotationToggle').checked})});toast($('rotationToggle').checked?'Rotação inteligente ativada.':'Rotação inteligente desativada.');await loadAiKeyPool()}catch(e){$('rotationToggle').checked=!$('rotationToggle').checked;toast(e.message,true)}};
if($('addAiKey'))$('addAiKey').onclick=async()=>{const key=$('newApiKey').value.trim();if(!key)return toast('Informe a nova API key.',true);setBusy($('addAiKey'),true,'Testando');try{const d=await api('/api/ai/keys',{method:'POST',body:JSON.stringify({provider:currentKeyProvider(),api_key:key,label:$('keyAlias').value.trim(),base_url:currentKeyBaseUrl()})});$('newApiKey').value='';$('keyAlias').value='';if(d.key?.id&&d.models)keyModelCache[d.key.id]=d.models;toast(d.test_ok?`Chave salva. ${d.model_count} modelo(s) disponíveis.`:'Chave salva, mas o teste encontrou um problema.',!d.test_ok);await loadAiKeyPool()}catch(e){toast(e.message,true)}finally{setBusy($('addAiKey'),false)}};
if($('aiKeyList'))$('aiKeyList').onclick=async ev=>{const b=ev.target.closest('button');if(!b)return;const id=b.dataset.keyId;if(!id)return;try{
  if(b.classList.contains('key-load-models')){setBusy(b,true,'Carregando');const d=await testStoredKey(id,'');keyModelCache[id]=d.models||[];toast(`${d.count||0} modelo(s) compatíveis encontrados.`);await loadAiKeyPool();}
  else if(b.classList.contains('key-test')){const sel=document.querySelector(`.key-model[data-key-id="${CSS.escape(id)}"]`);const model=sel?.value||'';if(!model)return toast('Carregue e selecione um modelo.',true);setBusy(b,true,'Testando');await testStoredKey(id,model);toast('Chave e modelo responderam corretamente.');await loadAiKeyPool();}
  else if(b.classList.contains('key-use')){const sel=document.querySelector(`.key-model[data-key-id="${CSS.escape(id)}"]`);const model=sel?.value||'';if(!model)return toast('Selecione um modelo antes de ativar.',true);setBusy(b,true,'Validando');await testStoredKey(id,model);await api('/api/ai/keys/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({provider:currentKeyProvider(),preferred_model:model,make_active:true})});await api('/api/ai/config',{method:'PUT',body:JSON.stringify({provider:currentKeyProvider(),model:model,api_key:null,base_url:currentKeyBaseUrl(),validate_connection:false})});toast('Chave ativa e modelo selecionado.');await loadAiKeyPool();await loadStatus();}
  else if(b.classList.contains('key-rename')){const next=prompt('Novo apelido para esta chave:',b.dataset.label||'');if(next===null)return;await api('/api/ai/keys/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({provider:currentKeyProvider(),label:next})});toast('Apelido atualizado.');await loadAiKeyPool();}
  else if(b.classList.contains('key-toggle')){await api('/api/ai/keys/'+encodeURIComponent(id),{method:'PATCH',body:JSON.stringify({provider:currentKeyProvider(),enabled:b.dataset.enabled!=='1'})});await loadAiKeyPool();}
  else if(b.classList.contains('key-delete')){if(!confirm('Excluir esta chave do cofre? Esta ação não pode ser desfeita.'))return;await api('/api/ai/keys/'+encodeURIComponent(id)+'?provider='+encodeURIComponent(currentKeyProvider()),{method:'DELETE'});toast('Chave excluída.');await loadAiKeyPool();}
}catch(e){toast(e.message,true);await loadAiKeyPool()}finally{if(b) setBusy(b,false)}};
setTimeout(loadAiKeyPool,150);
'''
    if js_marker in source:
        source = source.replace(js_marker, extra_js + '\n' + js_marker, 1)
    return source


def create_app():
    resolver = CloudTenantResolver()
    verifier = IntrospectionTokenVerifier()
    web_sessions = OnboardingSessionStore(resolver.db)
    onboarding = OnboardingService(resolver)
    app = create_base_app(resolver=resolver, verifier=verifier, session_store=web_sessions)

    async def tenant_from_request(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> AuthenticatedTenant:
        if authorization and authorization.startswith("Bearer "):
            access = await verifier.verify_token(authorization[7:].strip())
            if access is None:
                raise HTTPException(status_code=401, detail="Token inválido ou expirado.")
            tenant_id = str((access.claims or {}).get("tenant_id", "")).strip()
            if not tenant_id:
                raise HTTPException(status_code=403, detail="Token sem tenant associado.")
            resolver.db.ensure_tenant(tenant_id)
            return AuthenticatedTenant(tenant_id=tenant_id, subject=str(access.subject or ""), scopes=list(access.scopes or []), auth_method="bearer")
        identity = web_sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
        if identity is None:
            raise HTTPException(status_code=401, detail="Sessão não autenticada ou expirada.")
        return AuthenticatedTenant(tenant_id=identity.tenant_id, subject="browser_web_session", scopes=list(identity.scopes), auth_method="cookie")

    async def ai_read(tenant: AuthenticatedTenant = Depends(tenant_from_request)) -> AuthenticatedTenant:
        if "yca:read" not in tenant.scopes:
            raise HTTPException(status_code=403, detail="Escopo obrigatório ausente: yca:read")
        return tenant

    async def ai_write(tenant: AuthenticatedTenant = Depends(tenant_from_request)) -> AuthenticatedTenant:
        if "yca:write" not in tenant.scopes:
            raise HTTPException(status_code=403, detail="Escopo obrigatório ausente: yca:write")
        return tenant

    @app.get("/api/ai/keys")
    async def ai_keys(provider: str = Query(min_length=2, max_length=40), tenant: AuthenticatedTenant = Depends(ai_read)):
        try:
            return onboarding.ai_key_pool(tenant.tenant_id, provider)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ai/keys")
    async def ai_key_add(payload: AIKeyCreateRequest, tenant: AuthenticatedTenant = Depends(ai_write)):
        try:
            return onboarding.add_ai_key(tenant.tenant_id, provider=payload.provider, api_key=payload.api_key, label=payload.label, base_url=payload.base_url)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/ai/keys/{key_id}")
    async def ai_key_update(key_id: str, payload: AIKeyUpdateRequest, tenant: AuthenticatedTenant = Depends(ai_write)):
        try:
            return onboarding.update_ai_key(tenant.tenant_id, provider=payload.provider, key_id=key_id, label=payload.label, preferred_model=payload.preferred_model, enabled=payload.enabled, make_active=payload.make_active)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/ai/keys/{key_id}")
    async def ai_key_delete(key_id: str, provider: str = Query(min_length=2, max_length=40), tenant: AuthenticatedTenant = Depends(ai_write)):
        try:
            return onboarding.delete_ai_key(tenant.tenant_id, provider=provider, key_id=key_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/ai/keys/{key_id}/test")
    async def ai_key_test(key_id: str, payload: AIKeyTestRequest, tenant: AuthenticatedTenant = Depends(ai_write)):
        try:
            return onboarding.test_ai_key(tenant.tenant_id, provider=payload.provider, key_id=key_id, model=payload.model, base_url=payload.base_url)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/ai/rotation")
    async def ai_rotation(payload: AIRotationRequest, tenant: AuthenticatedTenant = Depends(ai_write)):
        try:
            return onboarding.set_ai_rotation(tenant.tenant_id, provider=payload.provider, enabled=payload.enabled)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Replace only the dashboard document route. All API routes from the base app stay intact.
    app.router.routes[:] = [route for route in app.router.routes if not (getattr(route, "path", None) == "/dashboard" and "GET" in getattr(route, "methods", set()))]

    @app.get("/dashboard", response_class=HTMLResponse)
    async def enhanced_dashboard(request: Request):
        identity = web_sessions.resolve(request.cookies.get(COOKIE_NAME, ""))
        if identity is None:
            return RedirectResponse("/onboarding/session-expired", status_code=303)
        page = Path(__file__).resolve().parent / "web" / "dashboard.html"
        html = _enhance_dashboard_html(page.read_text(encoding="utf-8"))
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return app
