from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_CSS = r'''
<style data-yca-native-ux>
.native-settings-trigger{display:inline-flex;align-items:center;gap:7px;white-space:nowrap}.native-settings-overlay{position:fixed;inset:0;z-index:120;background:#0008;backdrop-filter:blur(8px);display:none;justify-content:flex-end}.native-settings-overlay.open{display:flex}.native-settings-drawer{width:min(430px,100%);height:100%;overflow:auto;background:var(--panel);border-left:1px solid var(--line);box-shadow:-20px 0 70px #0008;padding:calc(18px + env(safe-area-inset-top)) 16px calc(28px + env(safe-area-inset-bottom));display:grid;align-content:start;gap:12px}.native-settings-head{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:4px 2px 12px}.native-settings-head h3{font-size:20px;margin:0}.native-setting-list{display:grid;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--card2)}.native-setting-row{appearance:none;width:100%;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--text);padding:15px 14px;display:flex;align-items:center;justify-content:space-between;gap:12px;text-align:left;font-weight:800;cursor:pointer}.native-setting-row:last-child{border-bottom:0}.native-setting-row small{font-weight:500;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:55%}.native-setting-row:hover{background:color-mix(in srgb,var(--accent) 7%,var(--card2))}.native-setting-row.danger{color:#ffd5dc}.native-engine-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:2px}.native-engine-kpi{border:1px solid var(--line);border-radius:13px;padding:10px;background:var(--card2)}.native-engine-kpi span{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}.native-engine-kpi strong{display:block;font-size:19px;margin-top:3px}.native-priority-list{display:grid;gap:7px;margin-top:10px}.native-priority{border:1px solid var(--line);border-radius:12px;background:var(--card2);padding:10px}.native-priority b{display:block}.native-priority small{color:var(--muted)}.native-evidence{display:grid;gap:7px;border:1px solid var(--line);border-radius:13px;padding:11px;background:var(--card2)}.native-evidence-row{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid color-mix(in srgb,var(--line) 70%,transparent);padding-bottom:7px}.native-evidence-row:last-child{border-bottom:0;padding-bottom:0}.native-evidence-row span{color:var(--muted)}.native-evidence-row b{text-align:right}.native-hide{display:none!important}.ai-context-note{display:none!important}#freeVideoLab,#freeChannelLab{scroll-margin-top:92px}.tech-details .code{display:none!important}.tech-details summary{list-style:none}.tech-details summary::-webkit-details-marker{display:none}.tech-details[open] summary{border-bottom:0}.tech-details::after{content:'Detalhes técnicos preservados para diagnóstico interno. A interface mostra somente evidências úteis para decisão.';display:block;color:var(--muted);font-size:12px;padding:0 12px 10px}.native-settings-inline{display:grid;gap:10px;margin-top:10px}.native-settings-inline .channel-switch-panel{margin-top:0!important}
@media(max-width:760px){.native-settings-trigger .native-settings-label{display:none}.native-settings-trigger{min-width:52px!important;padding:10px 12px!important}.native-engine-strip{grid-template-columns:1fr 1fr}.native-settings-drawer{border-left:0}.mobile-nav{grid-template-columns:repeat(5,1fr)!important}.native-setting-row{padding:16px 14px}.native-setting-row small{max-width:50%}}
</style>
'''

_SCRIPT = r'''
<script data-yca-native-ux>
(()=>{
 if(window.__ycaNativeUx)return;window.__ycaNativeUx=true;
 const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
 const apiGet=async url=>{const r=await fetch(url,{credentials:'same-origin',headers:{Accept:'application/json'}});let d={};try{d=await r.json()}catch{}if(!r.ok)throw new Error(d.detail||`HTTP ${r.status}`);return d};
 const textOf=n=>(n?.textContent||'').trim();
 function articleByTitle(root,title){return [...(root?.querySelectorAll('article.card')||[])].find(a=>textOf(a.querySelector('h3'))===title)}
 function activateTab(name){const btn=document.querySelector(`[data-tab="${name}"]`);if(btn)btn.click()}
 function ensureSettingsTargets(){
   const settings=document.getElementById('settings');if(!settings)return;
   const grid=settings.querySelector('.settings-grid')||settings;
   const channel=document.querySelector('#channelProfileCard .channel-switch-panel');
   if(channel&&!document.getElementById('nativeChannelSettings')){const wrap=document.createElement('article');wrap.className='card full';wrap.id='nativeChannelSettings';wrap.innerHTML='<h3>Canais conectados</h3><div class="native-settings-inline"></div>';wrap.querySelector('.native-settings-inline').appendChild(channel);grid.prepend(wrap)}
   const caps=articleByTitle(document.getElementById('overview'),'Capacidades conectadas');
   if(caps){caps.id='nativeCapabilitiesSettings';grid.appendChild(caps)}
   const protection=articleByTitle(document.getElementById('overview'),'Proteção');
   if(protection){protection.id='nativeProtectionSettings';grid.appendChild(protection)}
   const intelligence=articleByTitle(document.getElementById('overview'),'Inteligência');if(intelligence)intelligence.remove();
 }
 function openSettingsTarget(id){
   closeDrawer();activateTab('settings');setTimeout(()=>{const n=document.getElementById(id);if(n)n.scrollIntoView({behavior:'smooth',block:'start'})},80)
 }
 function buildDrawer(){
   if(document.getElementById('nativeSettingsOverlay'))return;
   const overlay=document.createElement('div');overlay.id='nativeSettingsOverlay';overlay.className='native-settings-overlay';overlay.innerHTML=`<aside class="native-settings-drawer" role="dialog" aria-modal="true" aria-label="Configurações"><div class="native-settings-head"><div><h3>Configurações</h3><div class="muted">Preferências, integrações e conta</div></div><button class="btn" id="nativeSettingsClose" aria-label="Fechar">✕</button></div><div class="native-setting-list"><button class="native-setting-row" data-settings-target="nativeChannelSettings"><span>Canal e conexões</span><small>YouTube e canais</small></button><button class="native-setting-row" data-settings-target="appearance"><span>Aparência</span><small>Tema e animações</small></button><button class="native-setting-row" data-settings-target="aiKeyVault"><span>IA externa Premium</span><small>Chaves e modelos</small></button><button class="native-setting-row" data-settings-target="nativeProtectionSettings"><span>Segurança</span><small>Prévia e rollback</small></button><button class="native-setting-row" data-settings-target="nativeCapabilitiesSettings"><span>Integrações</span><small>Capacidades conectadas</small></button><a class="native-setting-row danger" href="/auth/logout"><span>Sair da conta</span><small>Encerrar sessão</small></a></div></aside>`;document.body.appendChild(overlay);
   const appearance=articleByTitle(document.getElementById('settings'),'Tema do painel');if(appearance)appearance.id='appearance';
   overlay.addEventListener('click',e=>{if(e.target===overlay)closeDrawer();const row=e.target.closest('[data-settings-target]');if(row){const id=row.dataset.settingsTarget;closeDrawer();openSettingsTarget(id)}});
   document.getElementById('nativeSettingsClose').onclick=closeDrawer;
   document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer()});
 }
 function openDrawer(){ensureSettingsTargets();buildDrawer();document.getElementById('nativeSettingsOverlay')?.classList.add('open')}
 function closeDrawer(){document.getElementById('nativeSettingsOverlay')?.classList.remove('open')}
 function replaceLogout(){
   const old=document.getElementById('logout');if(old)old.classList.add('native-hide');
   const actions=document.querySelector('.top-actions');if(actions&&!document.getElementById('nativeSettingsButton')){const b=document.createElement('button');b.id='nativeSettingsButton';b.className='btn native-settings-trigger';b.innerHTML='<span>⚙</span><span class="native-settings-label">Configurações</span>';b.onclick=openDrawer;actions.appendChild(b)}
   document.querySelectorAll('[data-tab="settings"]').forEach(b=>b.classList.add('native-hide'));
 }
 function declutter(){
   ensureSettingsTargets();replaceLogout();buildDrawer();
   document.querySelectorAll('.ai-context-note').forEach(n=>n.classList.add('native-hide'));
   const evidence=articleByTitle(document.getElementById('strategy'),'Evidências para o ChatGPT');if(evidence)evidence.classList.add('native-hide');
 }
 function nameNativeIntelligence(){
   const fv=document.getElementById('freeVideoLab');if(fv){const h=fv.querySelector('h3');if(h)h.textContent='Inteligência Nativa do vídeo';const m=fv.querySelector('.muted');if(m)m.textContent='SEO, keywords, playlist, retenção e CTR oficial com o motor próprio da ferramenta.';const b=fv.querySelector('#runFreeVideoLab');if(b)b.textContent='Analisar com Inteligência Nativa';const grid=document.querySelector('#videos .grid');if(grid&&grid.firstElementChild!==fv)grid.prepend(fv)}
   const fc=document.getElementById('freeChannelLab');if(fc){const h=fc.querySelector('h3');if(h)h.textContent='Inteligência Nativa do canal';const m=fc.querySelector('.muted');if(m)m.textContent='Histórico, perfil, catálogo e publicação analisados pelo motor próprio.';const b=fc.querySelector('#runFreeChannelLab');if(b)b.textContent='Atualizar Inteligência Nativa';const grid=document.querySelector('#strategy .grid');if(grid&&grid.firstElementChild!==fc)grid.prepend(fc)}
   document.querySelectorAll('.free-intelligence-head b').forEach(n=>{if(textOf(n).includes('Motor de Crescimento'))n.textContent='Inteligência Nativa · análise determinística'});
 }
 function humanizeEvidence(){
   document.querySelectorAll('.free-output details').forEach(d=>{if(d.dataset.nativeHumanized)return;const pre=d.querySelector('pre');if(!pre)return;let raw;try{raw=JSON.parse(pre.textContent)}catch{return}d.dataset.nativeHumanized='1';const p=raw.profile||raw.plan||{};const perf=raw.performance||{};const pub=raw.publication||{};const trend=raw.trend||{};const rows=[['Motor',p.engine||p.mode||'Inteligência Nativa'],['Confiança',p.confidence!=null?`${p.confidence}%`:'calculada por evidência'],['Fonte','YouTube Data, Analytics e Reporting quando disponível'],['Amostra',pub.sample_size??trend.sample_size??p.sample_size??'dados disponíveis'],['Escritas realizadas','0']];d.innerHTML=`<summary class="muted">Evidências da análise</summary><div class="native-evidence">${rows.map(([a,b])=>`<div class="native-evidence-row"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join('')}</div>`});
 }
 async function enhanceHome(){
   const head=document.getElementById('proDashboardHead');if(!head||head.dataset.nativeEnhanced)return;head.dataset.nativeEnhanced='1';
   const badge=document.getElementById('proAiBadge');if(badge)badge.innerHTML='<span class="pill good">◆ Inteligência Nativa ativa</span><span class="pill">motor próprio · dados reais</span>';
   const toolbar=head.querySelector('.toolbar .muted');if(toolbar)toolbar.textContent='Resumo executivo calculado pelo motor próprio com dados atuais do YouTube';
   const strip=document.createElement('div');strip.id='nativeHomeIntelligence';strip.innerHTML='<div class="muted">Carregando diagnóstico nativo…</div>';head.appendChild(strip);
   try{const [channel,trend,actions]=await Promise.all([apiGet('/api/dashboard/free/channel'),apiGet('/api/dashboard/free/channel/trend'),apiGet('/api/dashboard/free/action-plan?max_videos=3')]);const scores=channel.scores||{};const list=actions.actions||actions.priorities||[];strip.innerHTML=`<div class="native-engine-strip"><div class="native-engine-kpi"><span>Score nativo</span><strong>${esc(channel.overall_score??'—')}/100</strong></div><div class="native-engine-kpi"><span>Momento</span><strong>${esc(trend.momentum_score??scores.momentum??'—')}/100</strong></div><div class="native-engine-kpi"><span>Descoberta</span><strong>${esc(scores.search_discovery??'—')}/100</strong></div><div class="native-engine-kpi"><span>Confiança</span><strong>${esc(channel.confidence??'—')}%</strong></div></div>${list.length?`<div class="native-priority-list">${list.slice(0,3).map((x,i)=>`<div class="native-priority"><b>${i+1}. ${esc(x.title||x.action||x.video_title||'Ação recomendada')}</b><small>${esc(x.reason||x.why||x.recommendation||'Prioridade calculada por evidência do canal.')}</small></div>`).join('')}</div>`:''}`}
   catch(e){strip.innerHTML=`<div class="notice warn">A Inteligência Nativa continua ativa, mas o resumo avançado não carregou agora: ${esc(e.message)}</div>`}
 }
 function stabilize(){declutter();nameNativeIntelligence();humanizeEvidence();enhanceHome();const badge=document.getElementById('proAiBadge');if(badge&&!textOf(badge).includes('Inteligência Nativa'))badge.innerHTML='<span class="pill good">◆ Inteligência Nativa ativa</span><span class="pill">motor próprio · dados reais</span>'}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{stabilize();setTimeout(stabilize,250);setTimeout(stabilize,900)},{once:true});else{stabilize();setTimeout(stabilize,250);setTimeout(stabilize,900)}
 new MutationObserver(()=>{clearTimeout(window.__ycaNativeSettle);window.__ycaNativeSettle=setTimeout(()=>{nameNativeIntelligence();humanizeEvidence();replaceLogout()},60)}).observe(document.documentElement,{childList:true,subtree:true});
})();
</script>
'''


def install_dashboard_native_ux(app: FastAPI) -> None:
    if getattr(app.state, "dashboard_native_ux_installed", False):
        return
    route = next(
        r for r in app.router.routes
        if isinstance(r, APIRoute) and r.path == "/dashboard" and "GET" in (r.methods or set())
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
        source = response.body.decode("utf-8")
        if "data-yca-native-ux" not in source:
            source = source.replace("</head>", _CSS + "\n</head>", 1).replace("</body>", _SCRIPT + "\n</body>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_native_ux")
    app.state.dashboard_native_ux_installed = True
