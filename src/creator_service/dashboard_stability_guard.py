from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute


_HEAD_SCRIPT = r'''
<script data-yca-stability-guard>
(()=>{
  if(window.__ycaStabilityGuard)return;
  window.__ycaStabilityGuard=true;
  const baseFetch=window.fetch.bind(window);
  const isBoundedRead=(input,init)=>{
    const method=String((init&&init.method)||(input&&input.method)||'GET').toUpperCase();
    if(method!=='GET')return false;
    let u;try{u=new URL(typeof input==='string'?input:input.url,location.href)}catch{return false}
    return u.origin===location.origin&&u.pathname.startsWith('/api/dashboard/');
  };
  window.fetch=async function(input,init={}){
    if(!isBoundedRead(input,init))return baseFetch(input,init);
    const controller=new AbortController();
    const upstream=init&&init.signal;
    if(upstream){
      if(upstream.aborted)controller.abort(upstream.reason);
      else upstream.addEventListener('abort',()=>controller.abort(upstream.reason),{once:true});
    }
    const timer=setTimeout(()=>controller.abort('dashboard-read-timeout'),9000);
    try{
      return await baseFetch(input,{...init,signal:controller.signal});
    }catch(err){
      if(controller.signal.aborted&&!upstream?.aborted){
        const timeoutError=new Error('A leitura demorou mais de 9 segundos. A interface continua disponível; use Atualizar para tentar novamente.');
        timeoutError.name='DashboardReadTimeout';
        throw timeoutError;
      }
      throw err;
    }finally{
      clearTimeout(timer);
    }
  };
})();
</script>
'''


def install_dashboard_stability_guard(app: FastAPI) -> None:
    """Bound passive dashboard reads without issuing any automatic API probe.

    The guard is injected in <head>, before the dashboard JavaScript starts its
    normal reads. It never touches POST/PUT/PATCH/DELETE requests and therefore
    cannot perform or alter YouTube write actions.
    """
    if getattr(app.state, "dashboard_stability_guard_installed", False):
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
        if "data-yca-stability-guard" not in source:
            source = source.replace("</head>", _HEAD_SCRIPT + "\n</head>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_stability_guard")
    app.state.dashboard_stability_guard_installed = True
