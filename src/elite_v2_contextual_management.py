from __future__ import annotations

import json

CONTEXTUAL_MANAGEMENT_CSS = r'''
html[data-ui-version="elite-v2"] #onlineText{min-width:54px}
'''

CONTEXTUAL_MANAGEMENT_JS = r'''
(()=>{
 const open=(detail={})=>{
   const settings=document.querySelector('.nav button[data-tab="settings"]');if(settings)settings.click();
   let attempts=0;const fill=()=>{const card=document.querySelector('[data-v2-management]');if(!card){if(attempts++<50)setTimeout(fill,100);return}const action=card.querySelector('[data-v2-manage-action]');if(!action)return;action.value=detail.action||'video_privacy';action.dispatchEvent(new Event('change',{bubbles:true}));const set=(sel,val)=>{const el=card.querySelector(sel);if(el&&val!=null)el.value=String(val)};set('[data-v2-video-id]',detail.video_id);set('[data-v2-playlist-id]',detail.playlist_id);set('[data-v2-playlist-item-id]',detail.playlist_item_id);set('[data-v2-position]',detail.position);card.scrollIntoView({behavior:'smooth',block:'start'});};setTimeout(fill,100)
 };
 window.addEventListener('yca:v2-manage-open',event=>open(event.detail||{}));
 const clarify=()=>{const text=document.getElementById('onlineText');if(text&&text.textContent.trim()==='Online')text.textContent='App local';const yt=document.getElementById('ytStatus');const logout=document.getElementById('logout');if(logout&&yt&&yt.textContent.trim()==='Desconectado'){logout.disabled=true;logout.title='Nenhum canal conectado nesta sessão';logout.textContent='YouTube desconectado'}else if(logout&&yt&&yt.textContent.trim()==='Conectado'){logout.disabled=false;logout.title='';logout.textContent='Desconectar YouTube'}};
 clarify();new MutationObserver(clarify).observe(document.documentElement,{childList:true,subtree:true,characterData:true});
})();
'''


def contextual_management_webengine_source() -> str:
    css_json = json.dumps(CONTEXTUAL_MANAGEMENT_CSS, ensure_ascii=False)
    return (
        "(()=>{if(!document.querySelector('style[data-yca-v2-contextual-management]')){"
        "const s=document.createElement('style');s.dataset.ycaV2ContextualManagement='1';"
        f"s.textContent={css_json};(document.head||document.documentElement).appendChild(s);"
        "}})();\n" + CONTEXTUAL_MANAGEMENT_JS
    )
