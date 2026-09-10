from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from intelligence.free_growth_engine import FreeGrowthEngine


_CSS = r'''
<style data-yca-free-intelligence>
.free-intelligence{display:grid;gap:10px;margin-top:10px}.free-intelligence-head{border:1px solid color-mix(in srgb,var(--good) 38%,var(--line));border-radius:14px;padding:12px;background:color-mix(in srgb,var(--good) 5%,var(--card2))}.free-score-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.free-score{border:1px solid var(--line);border-radius:12px;padding:10px;background:var(--card2)}.free-score strong{display:block;font-size:19px}.free-rec{border:1px solid var(--line);border-radius:13px;padding:12px;background:var(--card2)}.free-rec b{display:block;margin-bottom:5px}.free-rec p{margin:5px 0;color:var(--muted)}.free-rec-evidence{font-size:12px;color:var(--muted);margin-top:7px;word-break:break-word}.free-engine-badge{display:inline-flex;margin-top:7px}.free-method{font-size:12px;color:var(--muted)}@media(max-width:760px){.free-score-grid{grid-template-columns:1fr 1fr}}
</style>
'''

_SCRIPT = r'''
<script data-yca-free-intelligence>
(()=>{
 if(window.__ycaFreeIntelligence)return;window.__ycaFreeIntelligence=true;
 const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
 const label=k=>({search_discovery:'Descoberta por busca',search_term_depth:'Profundidade de busca',content_consistency:'Consistência',topic_clarity:'Clareza temática',engagement:'Engajamento',momentum:'Momento'}[k]||k);
 function render(report){
   if(!report||report.mode!=='deterministic_free')return '';
   const scores=Object.entries(report.scores||{}).map(([k,v])=>`<div class="free-score"><span class="muted">${esc(label(k))}</span><strong>${esc(v)}/100</strong></div>`).join('');
   const recs=(report.recommendations||[]).map(r=>`<div class="free-rec"><b>${esc(r.title||'Recomendação')}</b><p>${esc(r.why||'')}</p><p><strong>O que fazer:</strong> ${esc(r.action||'')}</p><div class="free-rec-evidence">Evidência: ${esc(JSON.stringify(r.evidence||{}))} · confiança ${esc(r.confidence||0)}% · impacto ${esc(r.estimated_impact||'')}</div></div>`).join('');
   return `<div class="free-intelligence"><div class="free-intelligence-head"><b>Motor de Crescimento · análise sem IA externa</b><div>Score geral: <strong>${esc(report.overall_score)}/100 · ${esc(report.grade||'')}</strong></div><span class="pill good free-engine-badge">Dados reais · ${esc(report.confidence)}% confiança</span></div><div class="free-score-grid">${scores}</div>${recs||'<div class="free-rec">Nenhuma ação corretiva forte foi detectada nesta amostra.</div>'}<div class="free-method">${esc(report.methodology||'')}</div></div>`;
 }
 function enhance(){
   const node=document.getElementById('auditRaw');if(!node)return;
   const pre=node.querySelector('.tech-details pre');let raw=null;
   try{raw=pre?JSON.parse(pre.textContent):JSON.parse(node.textContent)}catch{return}
   if(!raw?.free_intelligence)return;
   const signature=JSON.stringify(raw.free_intelligence);if(node.dataset.freeIntelligenceSignature===signature)return;
   node.querySelector(':scope > .free-intelligence-render')?.remove();
   const holder=document.createElement('div');holder.className='free-intelligence-render';holder.innerHTML=render(raw.free_intelligence);
   const ai=node.querySelector(':scope > .ai-advice-render');const details=node.querySelector('.tech-details');
   node.insertBefore(holder,ai||details||null);node.dataset.freeIntelligenceSignature=signature;
 }
 const node=document.getElementById('auditRaw');if(node){let pending=false;new MutationObserver(()=>{if(pending)return;pending=true;setTimeout(()=>{pending=false;enhance()},0)}).observe(node,{childList:true,subtree:true,characterData:true});setTimeout(enhance,300)}
})();
</script>
'''


def _replace_call(app: FastAPI, path: str, replacement) -> None:
    route = next((r for r in app.router.routes if isinstance(r, APIRoute) and r.path == path), None)
    if route is None:
        raise RuntimeError(f"Rota não encontrada: {path}")
    route.endpoint = replacement
    route.dependant.call = replacement


def install_free_intelligence_dashboard(app: FastAPI) -> None:
    if getattr(app.state, "free_intelligence_dashboard_installed", False):
        return

    audit_route = next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/api/dashboard/audit")
    audit_original = audit_route.endpoint

    async def dashboard_audit(period_days=28, tenant=None):
        factual = await audit_original(period_days=period_days, tenant=tenant)
        report = FreeGrowthEngine().channel_report(
            dict(factual.get("channel") or {}),
            dict(factual.get("evidence") or {}),
        )
        return {**factual, "free_intelligence": report, "writes_performed": 0}

    _replace_call(app, "/api/dashboard/audit", dashboard_audit)

    dashboard_route = next(
        r for r in app.router.routes
        if isinstance(r, APIRoute) and r.path == "/dashboard" and "GET" in (r.methods or set())
    )
    original_dashboard = dashboard_route.endpoint
    app.router.routes.remove(dashboard_route)

    async def dashboard(request: Request):
        response = await original_dashboard(request)
        if not isinstance(response, HTMLResponse):
            return response
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("content-type", None)
        source = response.body.decode("utf-8")
        if "data-yca-free-intelligence" not in source:
            source = source.replace("</head>", _CSS + "\n</head>", 1).replace("</body>", _SCRIPT + "\n</body>", 1)
        return HTMLResponse(source, status_code=response.status_code, headers=headers)

    app.add_api_route("/dashboard", dashboard, methods=["GET"], include_in_schema=False, name="dashboard_free_intelligence")
    app.state.free_intelligence_dashboard_installed = True
