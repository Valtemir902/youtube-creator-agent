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
.v2-command-card{position:relative;overflow:hidden;min-height:146px;border:1px solid var(--v2-border);border-radius:20px;padding:17px;background:linear-gradient(150deg,rgba(18,31,50,.95),rgba(10,20,35,.93));box-shadow:var(--v2-shadow);cursor:pointer;transition:transform .22s var(--v2-ease),border-color .22s,box-shadow .22s;color:var(--v2-text);text-align:left}
.v2-command-card:hover{transform:translateY(-4px);border-color:rgba(34,211,238,.34);box-shadow:var(--v2-shadow-hover)}
.v2-command-card::before{content:"";position:absolute;width:140px;height:140px;right:-45px;top:-48px;border-radius:50%;background:radial-gradient(circle,rgba(34,211,238,.2),rgba(139,92,246,.06) 54%,transparent 70%)}
.v2-command-icon{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(145deg,rgba(34,211,238,.16),rgba(139,92,246,.18));border:1px solid rgba(255,255,255,.08);font-size:20px;margin-bottom:18px}
.v2-command-card strong{display:block;font-size:15px;margin-bottom:5px}.v2-command-card span{display:block;color:var(--v2-muted);font-size:12px;max-width:220px}.v2-command-card em{position:absolute;right:14px;bottom:12px;color:var(--v2-accent);font-style:normal;font-size:11px;font-weight:800;letter-spacing:.04em}
.v2-section-eyebrow{display:flex;align-items:center;gap:8px;margin:2px 0 11px;color:var(--v2-muted);font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}.v2-section-eyebrow::before{content:"";width:22px;height:2px;border-radius:99px;background:linear-gradient(90deg,var(--v2-accent),var(--v2-accent-2))}
.v2-status-chip{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid rgba(52,211,153,.22);background:rgba(52,211,153,.08);border-radius:999px;color:#bbf7d0;font-size:11px;font-weight:800}.v2-status-chip::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--v2-success);box-shadow:0 0 14px rgba(52,211,153,.6)}
.v2-section-banner{grid-column:1/-1;display:flex;justify-content:space-between;align-items:flex-end;gap:18px;padding:4px 2px 2px;margin-bottom:2px}.v2-section-banner h2{margin:0;font-size:25px;letter-spacing:-.035em}.v2-section-banner p{margin:5px 0 0;color:var(--v2-muted);max-width:760px}.v2-banner-actions{display:flex;gap:8px;align-items:center}.v2-quiet-badge{display:inline-flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid var(--v2-border);border-radius:999px;background:rgba(7,17,31,.42);color:var(--v2-muted);font-size:11px;font-weight:800}.v2-quiet-badge.real::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--v2-success);box-shadow:0 0 12px rgba(52,211,153,.55)}
.v2-growth-deck{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(280px,.8fr);gap:14px;margin:0 0 16px}.v2-growth-panel{border:1px solid var(--v2-border);border-radius:20px;background:linear-gradient(180deg,rgba(18,31,50,.92),rgba(9,18,31,.95));box-shadow:var(--v2-shadow);padding:17px;min-width:0}.v2-panel-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:12px}.v2-panel-head h3{margin:0;font-size:14px}.v2-panel-head p{margin:4px 0 0;color:var(--v2-muted);font-size:12px}.v2-bar-chart{height:214px;display:flex;align-items:flex-end;gap:8px;padding:12px 4px 6px;border-top:1px solid rgba(148,163,184,.08);overflow:hidden}.v2-chart-col{flex:1;min-width:0;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:6px}.v2-chart-bar{width:min(38px,72%);min-height:3px;border-radius:9px 9px 4px 4px;background:linear-gradient(180deg,var(--v2-accent),var(--v2-accent-2));box-shadow:0 8px 24px rgba(34,211,238,.12);transition:height .42s var(--v2-ease)}.v2-chart-value{font-size:10px;font-weight:800;color:#dcecff}.v2-chart-label{width:100%;font-size:9px;line-height:1.2;color:var(--v2-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:center}.v2-readiness{display:grid;grid-template-columns:122px minmax(0,1fr);gap:15px;align-items:center}.v2-score-ring{--score:0;width:116px;aspect-ratio:1;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--v2-accent) calc(var(--score)*1%),rgba(148,163,184,.11) 0);position:relative}.v2-score-ring::after{content:"";position:absolute;inset:10px;border-radius:50%;background:#0b1727}.v2-score-ring>div{position:relative;z-index:1;text-align:center}.v2-score-ring strong{font-size:30px;display:block;line-height:1}.v2-score-ring small{font-size:9px;color:var(--v2-muted);letter-spacing:.08em}.v2-factor-list{display:grid;gap:8px}.v2-factor{display:flex;justify-content:space-between;gap:10px;border-bottom:1px solid rgba(148,163,184,.08);padding-bottom:7px;font-size:11px}.v2-factor span{color:var(--v2-muted)}.v2-factor b{color:#dcecff}.v2-disclaimer{font-size:10px;color:var(--v2-muted);margin-top:9px;line-height:1.35}
.v2-ai-workspace{grid-column:1/-1;border:1px solid var(--v2-border);border-radius:20px;background:linear-gradient(150deg,rgba(18,31,50,.94),rgba(9,18,31,.96));padding:18px;box-shadow:var(--v2-shadow)}.v2-ai-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}.v2-ai-card{border:1px solid var(--v2-border);border-radius:16px;padding:14px;background:rgba(7,17,31,.48);min-height:126px;position:relative}.v2-ai-card strong{display:block;margin:8px 0 4px}.v2-ai-card p{margin:0;color:var(--v2-muted);font-size:11px}.v2-ai-mark{width:35px;height:35px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(145deg,rgba(34,211,238,.15),rgba(139,92,246,.17));border:1px solid rgba(255,255,255,.07)}.v2-ai-state{position:absolute;right:11px;top:11px;font-size:9px;font-weight:900;color:var(--v2-muted);text-transform:uppercase;letter-spacing:.06em}.v2-ai-state.ready{color:#86efac}.v2-safe-strip{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.v2-safe-step{flex:1;min-width:120px;border:1px solid rgba(148,163,184,.11);border-radius:12px;padding:9px 10px;font-size:10px;color:var(--v2-muted);background:rgba(7,17,31,.32)}.v2-safe-step b{display:block;color:#dcecff;margin-bottom:2px}
@media(max-width:1180px){.v2-command-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.v2-ai-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:900px){.v2-growth-deck{grid-template-columns:1fr}.v2-readiness{grid-template-columns:110px minmax(0,1fr)}}
@media(max-width:760px){html[data-ui-version="elite-v2"] .content{padding:14px 12px 100px}.v2-command-grid{grid-template-columns:1fr 1fr;gap:10px}.v2-command-card{min-height:132px;padding:14px}.v2-command-icon{margin-bottom:12px}.v2-command-card span{font-size:11px}.video-list{grid-template-columns:1fr!important}.v2-section-banner{align-items:flex-start;flex-direction:column}.v2-ai-grid{grid-template-columns:1fr 1fr}.v2-growth-panel{padding:14px}.v2-bar-chart{height:190px}}
@media(max-width:460px){.v2-command-grid{grid-template-columns:1fr}.v2-command-card{min-height:118px}.v2-ai-grid{grid-template-columns:1fr}.v2-readiness{grid-template-columns:1fr}.v2-score-ring{margin:auto}.v2-bar-chart{gap:3px}.v2-chart-value{font-size:8px}}
@media(prefers-reduced-motion:reduce){.v2-command-card,html[data-ui-version="elite-v2"] .card,html[data-ui-version="elite-v2"] .video-item,.v2-chart-bar{transition:none!important;transform:none!important}}
'''

V2_JS = r'''
(()=>{
  const root=document.documentElement;root.dataset.uiVersion='elite-v2';
  const api=async path=>{try{const r=await fetch(path,{headers:{Accept:'application/json'}});if(!r.ok)return null;return await r.json()}catch{return null}};
  const fmt=n=>new Intl.NumberFormat('pt-BR',{notation:Number(n)>=10000?'compact':'standard',maximumFractionDigits:1}).format(Number(n)||0);
  const esc=value=>String(value??'').replace(/[&<>\"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[ch]));
  const clickTab=target=>{const nav=document.querySelector(`.nav button[data-tab="${target}"]`);if(nav)nav.click()};
  const banner=(title,desc,actions='')=>`<div class="v2-section-banner"><div><div class="v2-section-eyebrow">Elite V2</div><h2>${title}</h2><p>${desc}</p></div><div class="v2-banner-actions">${actions}</div></div>`;

  const installCommandCenter=()=>{
    if(document.querySelector('[data-v2-command-center]'))return;
    const overview=document.getElementById('overview');if(!overview)return;const grid=overview.querySelector('.grid');if(!grid)return;
    const shell=document.createElement('div');shell.dataset.v2CommandCenter='1';
    shell.innerHTML=`<div class="v2-section-eyebrow">Centro de comando</div><div class="v2-command-grid">
      <button class="v2-command-card" type="button" data-v2-target="videos"><div class="v2-command-icon">▶</div><strong>Content Hub</strong><span>Vídeos, miniaturas, playlists, desempenho e otimizações em um único fluxo.</span><em>ABRIR →</em></button>
      <button class="v2-command-card" type="button" data-v2-target="strategy"><div class="v2-command-icon">⌁</div><strong>Growth & SEO</strong><span>Oportunidades, palavras-chave, estratégia e recuperação de conteúdo.</span><em>ANALISAR →</em></button>
      <button class="v2-command-card" type="button" data-v2-target="audit"><div class="v2-command-icon">◎</div><strong>Saúde do canal</strong><span>Auditoria factual, riscos e pontos que merecem ação do criador.</span><em>REVISAR →</em></button>
      <button class="v2-command-card" type="button" data-v2-target="settings"><div class="v2-command-icon">✦</div><strong>AI Workspace</strong><span>IA Local, provedores e controles seguros de execução supervisionada.</span><em>GERENCIAR →</em></button>
    </div>`;overview.insertBefore(shell,grid);shell.querySelectorAll('[data-v2-target]').forEach(card=>card.addEventListener('click',()=>clickTab(card.dataset.v2Target)));
    const brandSmall=document.querySelector('.brand small');if(brandSmall)brandSmall.textContent='Elite V2 · Local Command Center';
    const profile=document.getElementById('channelProfileCard');if(profile&&!profile.querySelector('.v2-status-chip')){const chip=document.createElement('span');chip.className='v2-status-chip';chip.textContent='Local-first protegido';const toolbar=profile.querySelector('.toolbar');if(toolbar)toolbar.appendChild(chip)}
  };

  const installGrowthDeck=async()=>{
    if(document.querySelector('[data-v2-growth-deck]'))return;const command=document.querySelector('[data-v2-command-center]');if(!command)return;
    const deck=document.createElement('section');deck.className='v2-growth-deck';deck.dataset.v2GrowthDeck='1';deck.innerHTML=`
      <article class="v2-growth-panel"><div class="v2-panel-head"><div><h3>Desempenho real dos vídeos recentes</h3><p>Views oficiais lidas diretamente da API do YouTube. Sem números decorativos.</p></div><span class="v2-quiet-badge real">Dados reais</span></div><div class="v2-bar-chart" data-v2-video-chart><span class="muted">Aguardando canal conectado…</span></div></article>
      <article class="v2-growth-panel"><div class="v2-panel-head"><div><h3>Growth Readiness</h3><p>Leitura explicável do catálogo recente.</p></div></div><div class="v2-readiness"><div class="v2-score-ring" data-v2-score style="--score:0"><div><strong>—</strong><small>READINESS</small></div></div><div><div class="v2-factor-list" data-v2-factors><div class="v2-factor"><span>Catálogo</span><b>—</b></div><div class="v2-factor"><span>Diversificação</span><b>—</b></div><div class="v2-factor"><span>Engajamento</span><b>—</b></div></div><div class="v2-disclaimer">Não é previsão de crescimento. É um indicador heurístico calculado somente com sinais observados e mostra os fatores usados.</div></div></div></article>`;
    command.insertAdjacentElement('afterend',deck);
    const payload=await api('/api/dashboard/videos?limit=10');const rows=(payload&&payload.videos)||[];const chart=deck.querySelector('[data-v2-video-chart]');
    if(rows.length){
      const top=[...rows].sort((a,b)=>(b.views||0)-(a.views||0)).slice(0,8);const max=Math.max(...top.map(v=>Number(v.views)||0),1);
      chart.innerHTML=top.map(v=>`<div class="v2-chart-col" title="${esc(v.title||'Vídeo')} · ${fmt(v.views)} views"><div class="v2-chart-value">${fmt(v.views)}</div><div class="v2-chart-bar" style="height:${Math.max(3,Math.round((Number(v.views)||0)/max*145))}px"></div><div class="v2-chart-label">${esc(v.title||'Vídeo')}</div></div>`).join('');
      const total=rows.reduce((s,v)=>s+(Number(v.views)||0),0),best=Math.max(...rows.map(v=>Number(v.views)||0),0),concentration=total?best/total:1;
      const engagement=rows.reduce((s,v)=>s+(Number(v.likes)||0)+(Number(v.comments)||0),0)/Math.max(total,1),depth=Math.min(rows.length/10,1),distribution=Math.max(0,1-concentration);
      const score=Math.round(Math.max(0,Math.min(100,(depth*.35+distribution*.45+Math.min(engagement*20,1)*.20)*100)));
      const ring=deck.querySelector('[data-v2-score]');ring.style.setProperty('--score',String(score));ring.querySelector('strong').textContent=score;
      deck.querySelector('[data-v2-factors]').innerHTML=`<div class="v2-factor"><span>Profundidade do catálogo analisado</span><b>${rows.length}/10</b></div><div class="v2-factor"><span>Diversificação de views</span><b>${Math.round(distribution*100)}%</b></div><div class="v2-factor"><span>Engajamento relativo observado</span><b>${(engagement*100).toFixed(2)}%</b></div>`;
    }
  };

  const installSectionBanners=()=>{
    const sections={videos:['Content Hub','Conteúdo visual, metadados e playlists organizados por ação.','<span class="v2-quiet-badge real">Thumbnails reais</span>'],strategy:['Growth & SEO','Pesquisa, oportunidades e estratégia apoiadas em evidências.','<span class="v2-quiet-badge">Sem métricas inventadas</span>'],audit:['Saúde do canal','Diagnóstico factual e riscos antes de qualquer alteração.','<span class="v2-quiet-badge">Somente leitura</span>'],publish:['Publicação','Prepare conteúdo com validação antes de enviar ao YouTube.','<span class="v2-quiet-badge">Confirmação obrigatória</span>'],settings:['AI Workspace & Integrações','Escolha o motor de inteligência sem misturar fatos, sugestões e execução.','<span class="v2-quiet-badge">Controle do criador</span>']};
    Object.entries(sections).forEach(([id,args])=>{const section=document.getElementById(id);const grid=section&&section.querySelector('.grid');if(grid&&!grid.querySelector('.v2-section-banner'))grid.insertAdjacentHTML('afterbegin',banner(...args))});
  };

  const installAIWorkspace=async()=>{
    if(document.querySelector('[data-v2-ai-workspace]'))return;const section=document.getElementById('settings');const grid=section&&section.querySelector('.grid');if(!grid)return;
    const box=document.createElement('article');box.className='v2-ai-workspace';box.dataset.v2AiWorkspace='1';box.innerHTML=`<div class="v2-panel-head"><div><h3>Orquestração de IA</h3><p>Um único local para escolher quem analisa e quem apenas propõe mudanças.</p></div><span class="v2-quiet-badge">Execução supervisionada</span></div><div class="v2-ai-grid">
      <div class="v2-ai-card"><span class="v2-ai-state" data-ai-state="local">Verificando</span><div class="v2-ai-mark">⌂</div><strong>IA Local</strong><p>Ollama no próprio computador, sem depender de sessão cloud.</p></div>
      <div class="v2-ai-card"><span class="v2-ai-state" data-ai-state="api">Verificando</span><div class="v2-ai-mark">API</div><strong>IA via API</strong><p>Provedor externo configurável para análises que realmente precisem dele.</p></div>
      <div class="v2-ai-card"><span class="v2-ai-state" data-ai-state="chatgpt">Verificando</span><div class="v2-ai-mark">GPT</div><strong>ChatGPT / Plugin</strong><p>Usa evidências estruturadas e mantém escrita separada da recomendação.</p></div>
      <div class="v2-ai-card"><span class="v2-ai-state ready">Disponível</span><div class="v2-ai-mark">◆</div><strong>Motor interno</strong><p>Regras explicáveis para SEO, prioridade e diagnóstico sem inventar métricas.</p></div></div><div class="v2-safe-strip"><div class="v2-safe-step"><b>1 · Fatos</b>Dados oficiais/cache identificados.</div><div class="v2-safe-step"><b>2 · Proposta</b>IA ou motor sugere, não executa.</div><div class="v2-safe-step"><b>3 · Aprovação</b>Diff explícito antes da escrita.</div><div class="v2-safe-step"><b>4 · Verificação</b>Readback e auditoria após aplicar.</div></div>`;
    grid.insertAdjacentElement('afterbegin',box);const status=await api('/api/dashboard/status');
    const set=(key,ready,label)=>{const el=box.querySelector(`[data-ai-state="${key}"]`);if(el){el.textContent=label;el.classList.toggle('ready',!!ready)}};
    set('local',!!(window.ycaLocalAI&&window.ycaLocalAI.state&&window.ycaLocalAI.state.ready),window.ycaLocalAI&&window.ycaLocalAI.state&&window.ycaLocalAI.state.ready?'Ativa':'Sob demanda');
    set('api',!!(status&&status.external_ai_configured),status&&status.external_ai_configured?'Configurada':'Não configurada');
    set('chatgpt',!!(status&&status.chatgpt_native_ready),status&&status.chatgpt_native_ready?'Disponível':'Indisponível');
  };

  const install=()=>{installCommandCenter();installSectionBanners();installGrowthDeck();installAIWorkspace()};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
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
