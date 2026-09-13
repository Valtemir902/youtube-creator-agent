from __future__ import annotations

import json

V2_CSS = r'''
:root{
  --v2-bg:#07111f;--v2-surface:#0d1727;--v2-surface-2:#121f32;--v2-glass:rgba(13,23,39,.78);
  --v2-border:rgba(148,163,184,.16);--v2-text:#f8fbff;--v2-muted:#93a4ba;--v2-accent:#22d3ee;
  --v2-accent-2:#8b5cf6;--v2-success:#34d399;--v2-warning:#fbbf24;--v2-danger:#fb7185;
  --v2-radius-sm:12px;--v2-radius:18px;--v2-radius-lg:24px;--v2-shadow:0 18px 55px rgba(0,0,0,.28);
  --v2-shadow-hover:0 26px 70px rgba(0,0,0,.34);--v2-ease:cubic-bezier(.2,.8,.2,1)
}
html[data-ui-version="elite-v2"]{scroll-behavior:smooth}
html[data-ui-version="elite-v2"] body{background:
 radial-gradient(circle at 85% -10%,rgba(139,92,246,.17),transparent 34%),
 radial-gradient(circle at 12% 4%,rgba(34,211,238,.13),transparent 30%),var(--v2-bg);color:var(--v2-text)}
html[data-ui-version="elite-v2"] .app{grid-template-columns:272px minmax(0,1fr)}
html[data-ui-version="elite-v2"] .sidebar{padding:20px 16px;border-right:1px solid var(--v2-border);background:rgba(7,17,31,.88);backdrop-filter:blur(22px)}
html[data-ui-version="elite-v2"] .brand{padding:6px 8px 22px}
html[data-ui-version="elite-v2"] .logo{width:50px;height:50px;border-radius:17px;background:linear-gradient(145deg,rgba(34,211,238,.2),rgba(139,92,246,.22));border-color:rgba(34,211,238,.38);box-shadow:0 12px 34px rgba(34,211,238,.12)}
html[data-ui-version="elite-v2"] .brand h1{font-size:13px;letter-spacing:.08em}
html[data-ui-version="elite-v2"] .brand small{font-size:11px;color:var(--v2-muted)}
html[data-ui-version="elite-v2"] .nav{gap:6px}
html[data-ui-version="elite-v2"] .nav button{position:relative;padding:12px 13px;border-radius:14px;color:var(--v2-muted);transition:transform .18s var(--v2-ease),background .18s,border-color .18s,color .18s}
html[data-ui-version="elite-v2"] .nav button:hover{transform:translateX(2px);background:rgba(148,163,184,.06)}
html[data-ui-version="elite-v2"] .nav button.active{background:linear-gradient(135deg,rgba(34,211,238,.14),rgba(139,92,246,.12));border-color:rgba(34,211,238,.24);box-shadow:inset 3px 0 0 var(--v2-accent),0 10px 30px rgba(0,0,0,.15)}
html[data-ui-version="elite-v2"] .topbar{padding:17px 26px;border-bottom:1px solid var(--v2-border);background:rgba(7,17,31,.72);backdrop-filter:blur(22px)}
html[data-ui-version="elite-v2"] .titlebox h2{font-size:24px;letter-spacing:-.025em}
html[data-ui-version="elite-v2"] .titlebox div{font-size:12px;color:var(--v2-muted)}
html[data-ui-version="elite-v2"] .content{padding:24px 26px 76px;max-width:1640px}
html[data-ui-version="elite-v2"] .grid{gap:16px}
html[data-ui-version="elite-v2"] .card{position:relative;overflow:hidden;border:1px solid var(--v2-border);border-radius:var(--v2-radius);background:linear-gradient(180deg,rgba(18,31,50,.94),rgba(10,20,35,.96));box-shadow:var(--v2-shadow);padding:18px;transition:transform .22s var(--v2-ease),box-shadow .22s,border-color .22s}
html[data-ui-version="elite-v2"] .card::after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(120deg,rgba(255,255,255,.025),transparent 30%)}
html[data-ui-version="elite-v2"] .card:hover{transform:translateY(-2px);box-shadow:var(--v2-shadow-hover);border-color:rgba(34,211,238,.28)}
html[data-ui-version="elite-v2"] .card h3{font-size:14px;letter-spacing:.01em}
html[data-ui-version="elite-v2"] .kpi{border:1px solid var(--v2-border);border-radius:15px;background:rgba(7,17,31,.52);padding:14px;transition:transform .2s var(--v2-ease),border-color .2s}
html[data-ui-version="elite-v2"] .kpi:hover{transform:translateY(-2px);border-color:rgba(34,211,238,.25)}
html[data-ui-version="elite-v2"] .kpi strong{font-size:24px;letter-spacing:-.04em;color:var(--v2-text)}
html[data-ui-version="elite-v2"] .btn{border-color:var(--v2-border);border-radius:12px;background:rgba(18,31,50,.72);transition:transform .16s var(--v2-ease),box-shadow .16s,border-color .16s}
html[data-ui-version="elite-v2"] .btn:hover{transform:translateY(-1px);box-shadow:0 12px 28px rgba(0,0,0,.24);border-color:rgba(34,211,238,.4)}
html[data-ui-version="elite-v2"] .btn.primary{background:linear-gradient(135deg,#0891b2,#6d4fe8);border-color:rgba(255,255,255,.14)}
html[data-ui-version="elite-v2"] .notice,html[data-ui-version="elite-v2"] input,html[data-ui-version="elite-v2"] textarea,html[data-ui-version="elite-v2"] select{background:rgba(7,17,31,.58);border-color:var(--v2-border)}
html[data-ui-version="elite-v2"] .video-list{grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
html[data-ui-version="elite-v2"] .video-item{position:relative;display:grid;grid-template-columns:1fr;border:1px solid var(--v2-border);border-radius:18px;padding:0;overflow:hidden;background:rgba(10,20,35,.9);transition:transform .2s var(--v2-ease),box-shadow .2s,border-color .2s}
html[data-ui-version="elite-v2"] .video-item:hover{transform:translateY(-3px);box-shadow:0 20px 48px rgba(0,0,0,.3);border-color:rgba(34,211,238,.3)}
html[data-ui-version="elite-v2"] .video-item .thumb{width:100%;aspect-ratio:16/9;border-radius:0;display:block}
html[data-ui-version="elite-v2"] .video-item>div:not(.video-actions){padding:13px 14px 5px}
html[data-ui-version="elite-v2"] .video-actions{padding:10px 14px 14px;justify-content:flex-start}
html[data-ui-version="elite-v2"] .playlist-list{grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
html[data-ui-version="elite-v2"] .playlist-item{grid-template-columns:112px minmax(0,1fr);border-radius:16px;border-color:var(--v2-border);background:rgba(7,17,31,.5);padding:0;overflow:hidden}
html[data-ui-version="elite-v2"] .playlist-thumb{width:112px;height:100%;min-height:76px;border-radius:0;object-fit:cover}
html[data-ui-version="elite-v2"] .playlist-actions{grid-column:1/-1;padding:0 10px 10px}
.v2-command-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:0 0 16px}
.v2-command-card{position:relative;overflow:hidden;min-height:146px;border:1px solid var(--v2-border);border-radius:20px;padding:17px;background:linear-gradient(150deg,rgba(18,31,50,.95),rgba(10,20,35,.93));box-shadow:var(--v2-shadow);cursor:pointer;transition:transform .22s var(--v2-ease),border-color .22s,box-shadow .22s}
.v2-command-card:hover{transform:translateY(-4px);border-color:rgba(34,211,238,.34);box-shadow:var(--v2-shadow-hover)}
.v2-command-card::before{content:"";position:absolute;width:140px;height:140px;right:-45px;top:-48px;border-radius:50%;background:radial-gradient(circle,rgba(34,211,238,.2),rgba(139,92,246,.06) 54%,transparent 70%)}
.v2-command-icon{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(145deg,rgba(34,211,238,.16),rgba(139,92,246,.18));border:1px solid rgba(255,255,255,.08);font-size:20px;margin-bottom:18px}
.v2-command-card strong{display:block;font-size:15px;margin-bottom:5px}.v2-command-card span{display:block;color:var(--v2-muted);font-size:12px;max-width:220px}
.v2-command-card em{position:absolute;right:14px;bottom:12px;color:var(--v2-accent);font-style:normal;font-size:11px;font-weight:800;letter-spacing:.04em}
.v2-section-eyebrow{display:flex;align-items:center;gap:8px;margin:2px 0 11px;color:var(--v2-muted);font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.v2-section-eyebrow::before{content:"";width:22px;height:2px;border-radius:99px;background:linear-gradient(90deg,var(--v2-accent),var(--v2-accent-2))}
.v2-status-chip{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid rgba(52,211,153,.22);background:rgba(52,211,153,.08);border-radius:999px;color:#bbf7d0;font-size:11px;font-weight:800}
.v2-status-chip::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--v2-success);box-shadow:0 0 14px rgba(52,211,153,.6)}
@media(max-width:1180px){.v2-command-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){html[data-ui-version="elite-v2"] .content{padding:14px 12px 100px}.v2-command-grid{grid-template-columns:1fr 1fr;gap:10px}.v2-command-card{min-height:132px;padding:14px}.v2-command-icon{margin-bottom:12px}.v2-command-card span{font-size:11px}.video-list{grid-template-columns:1fr!important}}
@media(max-width:460px){.v2-command-grid{grid-template-columns:1fr}.v2-command-card{min-height:118px}}
@media(prefers-reduced-motion:reduce){.v2-command-card,html[data-ui-version="elite-v2"] .card,html[data-ui-version="elite-v2"] .video-item{transition:none!important;transform:none!important}}
'''

V2_JS = r'''
(()=>{
  const root=document.documentElement;
  root.dataset.uiVersion='elite-v2';
  const install=()=>{
    if(document.querySelector('[data-v2-command-center]')) return;
    const overview=document.getElementById('overview');
    if(!overview) return;
    const grid=overview.querySelector('.grid');
    if(!grid) return;
    const shell=document.createElement('div');
    shell.dataset.v2CommandCenter='1';
    shell.innerHTML=`
      <div class="v2-section-eyebrow">Centro de comando</div>
      <div class="v2-command-grid">
        <button class="v2-command-card" type="button" data-v2-target="videos"><div class="v2-command-icon">▶</div><strong>Conteúdo</strong><span>Vídeos, miniaturas, desempenho e otimizações em um único fluxo.</span><em>ABRIR →</em></button>
        <button class="v2-command-card" type="button" data-v2-target="strategy"><div class="v2-command-icon">⌁</div><strong>Growth & SEO</strong><span>Oportunidades, palavras-chave, estratégia e recuperação de conteúdo.</span><em>ANALISAR →</em></button>
        <button class="v2-command-card" type="button" data-v2-target="audit"><div class="v2-command-icon">◎</div><strong>Saúde do canal</strong><span>Auditoria factual, riscos e pontos que merecem ação do criador.</span><em>REVISAR →</em></button>
        <button class="v2-command-card" type="button" data-v2-target="settings"><div class="v2-command-icon">✦</div><strong>IA & Automação</strong><span>IA Local, provedores e controles seguros de execução supervisionada.</span><em>GERENCIAR →</em></button>
      </div>`;
    overview.insertBefore(shell,grid);
    shell.querySelectorAll('[data-v2-target]').forEach(card=>card.addEventListener('click',()=>{
      const target=card.dataset.v2Target;
      const nav=document.querySelector(`.nav button[data-tab="${target}"]`);
      if(nav) nav.click();
    }));
    const brandSmall=document.querySelector('.brand small');
    if(brandSmall) brandSmall.textContent='Elite V2 · Local Command Center';
    const profile=document.getElementById('channelProfileCard');
    if(profile && !profile.querySelector('.v2-status-chip')){
      const chip=document.createElement('span');chip.className='v2-status-chip';chip.textContent='Local-first protegido';
      const toolbar=profile.querySelector('.toolbar');if(toolbar) toolbar.appendChild(chip);
    }
  };
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',install,{once:true}); else install();
})();
'''


def elite_v2_webengine_source() -> str:
    css_json=json.dumps(V2_CSS,ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-elite-v2]')){"
        "const s=document.createElement('style');s.dataset.ycaEliteV2='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n"+V2_JS
    )
