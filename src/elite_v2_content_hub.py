from __future__ import annotations

import json

CONTENT_HUB_CSS = r'''
.v2-content-tools{grid-column:1/-1;display:grid;grid-template-columns:minmax(220px,1fr) 190px auto;gap:9px;align-items:end;border:1px solid var(--v2-border);border-radius:17px;padding:12px;background:rgba(7,17,31,.42);margin-bottom:2px}
.v2-content-tools label{font-size:10px;text-transform:uppercase;letter-spacing:.07em;font-weight:800;color:var(--v2-muted)}
.v2-content-tools input,.v2-content-tools select{margin-top:5px}
.v2-content-actions{display:flex;gap:7px;align-items:center;justify-content:flex-end}.v2-content-count{white-space:nowrap}.v2-video-hidden{display:none!important}
.v2-content-guide{grid-column:1/-1;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;margin-bottom:2px}
.v2-guide-card{border:1px solid var(--v2-border);border-radius:15px;padding:11px 12px;background:rgba(7,17,31,.34);min-width:0}
.v2-guide-card b{display:block;font-size:11px;margin-bottom:3px}.v2-guide-card span{display:block;color:var(--v2-muted);font-size:10px;line-height:1.4}
@media(max-width:760px){.v2-content-tools{grid-template-columns:1fr}.v2-content-actions{justify-content:stretch}.v2-content-actions .btn{flex:1}.v2-content-guide{grid-template-columns:1fr}}
'''

CONTENT_HUB_JS = r'''
(()=>{
  const install=()=>{
    if(document.querySelector('[data-v2-content-tools]'))return;
    const section=document.getElementById('videos'),grid=section&&section.querySelector('.grid');if(!grid)return;
    const anchor=grid.querySelector('.v2-section-banner')||grid.firstElementChild;
    const guide=document.createElement('div');guide.className='v2-content-guide';guide.dataset.v2ContentGuide='1';guide.innerHTML=`
      <div class="v2-guide-card"><b>Cards visuais</b><span>Miniatura real, métricas observadas e ações do vídeo no mesmo contexto.</span></div>
      <div class="v2-guide-card"><b>IA sob controle</b><span>Análise e proposta continuam separadas de qualquer escrita no canal.</span></div>
      <div class="v2-guide-card"><b>Gestão segura</b><span>Prévia e confirmação permanecem obrigatórias nas ações suportadas.</span></div>`;
    const tools=document.createElement('div');tools.className='v2-content-tools';tools.dataset.v2ContentTools='1';tools.innerHTML=`
      <label>Buscar conteúdo<input type="search" data-v2-video-search placeholder="Título do vídeo" autocomplete="off"></label>
      <label>Visibilidade<select data-v2-video-privacy><option value="all">Todos</option><option value="public">Públicos</option><option value="unlisted">Não listados</option><option value="private">Privados</option></select></label>
      <div class="v2-content-actions"><span class="v2-quiet-badge v2-content-count" data-v2-content-count>0 visíveis</span><button class="btn" type="button" data-v2-refresh-videos>Atualizar</button></div>`;
    if(anchor){anchor.insertAdjacentElement('afterend',guide);guide.insertAdjacentElement('afterend',tools)}else{grid.prepend(tools);grid.prepend(guide)}
    const list=document.getElementById('videoList'),search=tools.querySelector('[data-v2-video-search]'),privacy=tools.querySelector('[data-v2-video-privacy]'),count=tools.querySelector('[data-v2-content-count]');
    const apply=()=>{const q=(search.value||'').trim().toLocaleLowerCase('pt-BR'),p=privacy.value;let visible=0;(list?list.querySelectorAll('.video-item'):[]).forEach(card=>{const title=(card.querySelector('.video-title')?.textContent||'').toLocaleLowerCase('pt-BR'),stats=(card.querySelector('.stats')?.textContent||'').toLocaleLowerCase('pt-BR');const show=(!q||title.includes(q))&&(p==='all'||stats.includes(p));card.classList.toggle('v2-video-hidden',!show);if(show)visible++});count.textContent=`${visible} visíveis`};
    search.addEventListener('input',apply);privacy.addEventListener('change',apply);tools.querySelector('[data-v2-refresh-videos]').addEventListener('click',()=>document.getElementById('reloadVideos')?.click());
    if(list)new MutationObserver(apply).observe(list,{childList:true});apply();
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();
'''


def content_hub_webengine_source() -> str:
    css_json = json.dumps(CONTENT_HUB_CSS, ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-v2-content-hub]')){"
        "const s=document.createElement('style');s.dataset.ycaV2ContentHub='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n" + CONTENT_HUB_JS
    )
