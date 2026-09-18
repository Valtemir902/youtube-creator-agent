from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_CSS = r'''
<style data-yca-connection-health>
.yca-api-health{display:none;grid-column:1/-1;border:1px solid var(--line);border-radius:14px;padding:10px 12px;background:var(--card2);font-size:13px}.yca-api-health.show{display:block}.yca-api-health.ok{border-color:color-mix(in srgb,var(--good) 55%,var(--line));color:var(--good)}.yca-api-health.warn{border-color:color-mix(in srgb,var(--warn) 60%,var(--line));color:var(--warn)}.yca-api-health.bad{border-color:color-mix(in srgb,var(--bad) 60%,var(--line));color:#ffd5dc}.yca-api-health button{margin-left:10px}.yca-stale-note{font-size:11px;color:var(--muted);margin-top:5px}
</style>
'''

_SCRIPT = r'''
<script data-yca-connection-health>
(()=>{
 if(window.__ycaConnectionHealth)return;window.__ycaConnectionHealth=true;
 const $=id=>document.getElementById(id);
 const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
 const started=Date.now();
 let probing=false;

 function ensureHealthBox(){
   let box=$('ycaApiHealth');if(box)return box;
   box=document.createElement('div');box.id='ycaApiHealth';box.className='yca-api-health';
   const grid=document.querySelector('#overview .grid');if(grid)grid.prepend(box);
   return box;
 }
 function setConnection(state,message,title){
   const online=$('onlineText'), dot=$('onlineDot'), badge=$('profileConnectionBadge'), yt=$('ytStatus');
   if(online)online.textContent=message;
   if(dot){dot.classList.toggle('ok',state==='ok');}
   if(badge){badge.className='pill '+(state==='ok'?'good':state==='bad'?'bad':'');badge.textContent=message;}
   if(yt)yt.textContent=message;
   const box=ensureHealthBox();
   if(!box)return;
   if(state==='ok'){
     box.className='yca-api-health show ok';
     box.innerHTML=`YouTube Data API verificada${title?` · <b>${esc(title)}</b>`:''}. O painel pode usar snapshots locais enquanto atualiza dados em segundo plano.`;
     setTimeout(()=>{if(box.classList.contains('ok'))box.classList.remove('show')},3500);
   }else{
     box.className='yca-api-health show '+(state==='bad'?'bad':'warn');
     box.innerHTML=`${esc(message)} <button class="btn" id="ycaRetryApi">Tentar novamente</button>`;
     $('ycaRetryApi')?.addEventListener('click',()=>probe(true),{once:true});
   }
 }
 async function rawProbe(){
   const c=new AbortController(), timer=setTimeout(()=>c.abort('youtube-probe-timeout'),6500);
   try{
     const url='/api/dashboard/channel/identity?live_probe='+Date.now();
     const r=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:c.signal,headers:{Accept:'application/json','X-YCA-Live-Probe':'1'}});
     let d={};try{d=await r.json()}catch{}
     if(!r.ok)throw new Error(d.detail||d.message||`HTTP ${r.status}`);
     if(!d||(!d.title&&!d.channel_id&&!d.id))throw new Error('A API respondeu sem identificar o canal.');
     return d;
   }finally{clearTimeout(timer)}
 }
 async function probe(force=false){
   if(probing)return;probing=true;
   setConnection('checking','Verificando YouTube API…');
   try{const d=await rawProbe();setConnection('ok','YouTube API verificada',d.title||d.channel_title||'');}
   catch(e){
     const msg=e?.name==='AbortError'?'YouTube API não respondeu em 6,5s. O painel continua utilizável.':`YouTube API não verificada: ${e?.message||'falha desconhecida'}`;
     setConnection('bad',msg);
   }finally{probing=false}
 }
 function stopEndlessPlaceholders(){
   if(Date.now()-started<8500)return;
   const replacements=[
     ['channelIdentity','Não foi possível atualizar o canal agora. Use “Tentar novamente” acima.'],
     ['channelDescription','Descrição temporariamente indisponível.'],
     ['playlistList','Playlists temporariamente indisponíveis.'],
     ['profileSummary','O snapshot do canal ainda não foi recebido. A interface permanece disponível.']
   ];
   for(const [id,text] of replacements){const n=$(id);if(!n)continue;const t=(n.textContent||'').trim();if(/Carregando|Detectando|Coletando|Atualizando/i.test(t))n.innerHTML=`<div class="notice warn">${esc(text)}</div>`;}
   for(const id of ['marketLanguage','marketCountry','searchShare','shortShare','longShare','topSignal']){const n=$(id);if(n&&/Detectando|Coletando|^—$/.test((n.textContent||'').trim()))n.textContent='Aguardando dados';}
 }
 function guardAutomaticRefresh(){
   const current=window.refreshAll;if(typeof current!=='function'||current.__ycaGuarded)return;
   let last=0,running=false;
   const guarded=async function(){const now=Date.now();if(running||now-last<15000)return;last=now;running=true;try{return await current()}finally{running=false}};
   guarded.__ycaGuarded=true;window.refreshAll=guarded;
 }
 function boot(){guardAutomaticRefresh();ensureHealthBox();probe(false);setTimeout(stopEndlessPlaceholders,9000);setTimeout(guardAutomaticRefresh,1000);}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
</script>
'''


def install_dashboard_connection_health(app: FastAPI) -> None:
    if getattr(app.state, "dashboard_connection_health_installed", False):
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
        if "data-yca-connection-health" not in source:
            source = source.replace("</head>", _CSS + "\n</head>", 1).replace("</body>", _SCRIPT + "\n</body>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_connection_health")
    app.state.dashboard_connection_health_installed = True
