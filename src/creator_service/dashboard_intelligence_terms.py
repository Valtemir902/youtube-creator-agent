from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_SCRIPT = r'''
<script data-yca-intelligence-terms>
(()=>{
 if(window.__ycaIntelligenceTerms)return;window.__ycaIntelligenceTerms=true;
 function normalize(){
   document.querySelectorAll('[data-settings-target="aiKeyVault"] span').forEach(n=>{n.textContent='IA externa'});
   document.querySelectorAll('[data-settings-target="aiKeyVault"] small').forEach(n=>{n.textContent='Chaves e modelos opcionais'});
   document.querySelectorAll('.native-route-badge').forEach(n=>{
     const t=(n.textContent||'').trim();
     if(t==='Premium')n.textContent='IA externa';
     if(t==='Nativa + Premium')n.textContent='Nativa + IA externa';
   });
   document.querySelectorAll('button[title]').forEach(n=>{
     if((n.title||'').includes('IA externa Premium'))n.title=n.title.replace('IA externa Premium','IA externa');
   });
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',normalize,{once:true});else normalize();
 new MutationObserver(()=>{clearTimeout(window.__ycaTermsSettle);window.__ycaTermsSettle=setTimeout(normalize,50)}).observe(document.documentElement,{childList:true,subtree:true});
})();
</script>
'''


def install_dashboard_intelligence_terms(app: FastAPI) -> None:
    if getattr(app.state, "dashboard_intelligence_terms_installed", False):
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
        if "data-yca-intelligence-terms" not in source:
            source = source.replace("</body>", _SCRIPT + "\n</body>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route(
        "/dashboard",
        dashboard,
        methods=["GET"],
        include_in_schema=False,
        name="dashboard_intelligence_terms",
    )
    app.state.dashboard_intelligence_terms_installed = True
