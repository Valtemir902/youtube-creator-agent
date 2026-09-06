from pathlib import Path
import re

ROOT = Path.cwd()

# --- Multi-channel credential registry, encrypted through TenantDatabase ---
(ROOT / 'src/creator_service/channel_accounts.py').write_text('''from __future__ import annotations

import json
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .cloud_runtime import GOOGLE_SCOPES, GOOGLE_SECRET_NAME

CHANNEL_REGISTRY_SECRET = "google:channels_registry"
ACTIVE_CHANNEL_SECRET = "google:active_channel_id"
CHANNEL_CREDENTIAL_PREFIX = "google:channel:"


def _credential_name(channel_id: str) -> str:
    value = "".join(ch for ch in str(channel_id or "").strip() if ch.isalnum() or ch in "_-.")
    if not value:
        raise RuntimeError("ID de canal inválido.")
    return f"{CHANNEL_CREDENTIAL_PREFIX}{value}:authorized_user_json"


def _load_registry(db, tenant_id: str) -> dict[str, dict[str, Any]]:
    raw = db.get_secret(tenant_id, CHANNEL_REGISTRY_SECRET)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _save_registry(db, tenant_id: str, registry: dict[str, dict[str, Any]]) -> None:
    db.put_secret(tenant_id, CHANNEL_REGISTRY_SECRET, json.dumps(registry, ensure_ascii=False, separators=(",", ":")))


def _channel_snapshot_from_raw(raw: str) -> dict[str, Any]:
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Credencial Google armazenada está corrompida.") from exc
    creds = Credentials.from_authorized_user_info(info, GOOGLE_SCOPES)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    response = youtube.channels().list(part="snippet,statistics,brandingSettings", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("Nenhum canal do YouTube foi encontrado nesta autorização.")
    item = items[0]
    snippet = item.get("snippet", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    stats = item.get("statistics", {})
    branding = item.get("brandingSettings", {}).get("channel", {})
    return {
        "id": str(item.get("id", "")),
        "title": str(snippet.get("title", "")),
        "description": str(snippet.get("description", "")),
        "thumbnail": thumb,
        "country": snippet.get("country") or branding.get("country"),
        "default_language": snippet.get("defaultLanguage") or branding.get("defaultLanguage"),
        "subscribers": int(stats.get("subscriberCount", 0) or 0),
        "views": int(stats.get("viewCount", 0) or 0),
        "videos": int(stats.get("videoCount", 0) or 0),
    }


def capture_current_channel(db, tenant_id: str) -> dict[str, Any] | None:
    raw = db.get_secret(tenant_id, GOOGLE_SECRET_NAME)
    if not raw:
        return None
    snapshot = _channel_snapshot_from_raw(raw)
    channel_id = str(snapshot["id"])
    db.put_secret(tenant_id, _credential_name(channel_id), raw)
    registry = _load_registry(db, tenant_id)
    registry[channel_id] = snapshot
    _save_registry(db, tenant_id, registry)
    db.put_secret(tenant_id, ACTIVE_CHANNEL_SECRET, channel_id)
    return snapshot


def list_channel_accounts(db, tenant_id: str) -> dict[str, Any]:
    registry = _load_registry(db, tenant_id)
    active = db.get_secret(tenant_id, ACTIVE_CHANNEL_SECRET) or ""
    if db.get_secret(tenant_id, GOOGLE_SECRET_NAME):
        try:
            snapshot = capture_current_channel(db, tenant_id)
            if snapshot:
                registry = _load_registry(db, tenant_id)
                active = str(snapshot["id"])
        except Exception:
            pass
    rows = []
    for channel_id, data in registry.items():
        if not isinstance(data, dict):
            continue
        item = dict(data)
        item["id"] = channel_id
        item["active"] = channel_id == active
        rows.append(item)
    rows.sort(key=lambda item: (not item.get("active", False), str(item.get("title", "")).casefold()))
    return {"active_channel_id": active, "channels": rows}


def activate_channel(db, tenant_id: str, channel_id: str) -> dict[str, Any]:
    channel_id = str(channel_id or "").strip()
    raw = db.get_secret(tenant_id, _credential_name(channel_id))
    if not raw:
        raise RuntimeError("Este canal não está conectado a esta conta do Creator Agent.")
    db.put_secret(tenant_id, GOOGLE_SECRET_NAME, raw)
    db.put_secret(tenant_id, ACTIVE_CHANNEL_SECRET, channel_id)
    registry = _load_registry(db, tenant_id)
    data = dict(registry.get(channel_id) or {})
    data["id"] = channel_id
    data["active"] = True
    return data
''', encoding='utf-8')

# Google OAuth: explicitly show account chooser when adding another channel.
path = ROOT / 'src/creator_service/google_oauth.py'
text = path.read_text(encoding='utf-8')
if 'select_account: bool = False' not in text:
    text = text.replace(
        'def start(self, tenant_id: str, ttl_seconds: int = 600) -> OAuthStart:',
        'def start(self, tenant_id: str, ttl_seconds: int = 600, select_account: bool = False) -> OAuthStart:',
        1,
    )
    text = text.replace(
        '            prompt="consent",',
        '            prompt="select_account consent" if select_account else "consent",',
        1,
    )
path.write_text(text, encoding='utf-8')

# Register newly-authorized channel, preserving older stored channels.
path = ROOT / 'src/creator_service/onboarding_service.py'
text = path.read_text(encoding='utf-8')
if 'from .channel_accounts import capture_current_channel' not in text:
    text = text.replace('from .cloud_runtime import CloudTenantResolver, GOOGLE_SECRET_NAME\n', 'from .cloud_runtime import CloudTenantResolver, GOOGLE_SECRET_NAME\nfrom .channel_accounts import capture_current_channel\n', 1)
old = '''        tenant_id = self.google_oauth.complete(
            state=state,
            authorization_response=authorization_response,
        )
        return self.status(tenant_id)
'''
new = '''        tenant_id = self.google_oauth.complete(
            state=state,
            authorization_response=authorization_response,
        )
        try:
            capture_current_channel(self.db, tenant_id)
        except Exception:
            # OAuth remains valid if immediate identity refresh is temporarily unavailable.
            pass
        return self.status(tenant_id)
'''
if old in text:
    text = text.replace(old, new, 1)
elif 'capture_current_channel(self.db, tenant_id)' not in text:
    raise SystemExit('onboarding complete anchor not found')
path.write_text(text, encoding='utf-8')

# Dashboard endpoints for list/add/activate channel while preserving the web session.
path = ROOT / 'src/creator_service/dashboard_routes.py'
text = path.read_text(encoding='utf-8')
if 'from .channel_accounts import activate_channel, capture_current_channel, list_channel_accounts' not in text:
    text = text.replace('from .dashboard_store import DashboardActionStore\n', 'from .channel_accounts import activate_channel, capture_current_channel, list_channel_accounts\nfrom .google_oauth import GoogleOAuthCoordinator\nfrom .dashboard_store import DashboardActionStore\n', 1)
if '@app.get("/api/dashboard/channels")' not in text:
    anchor = '    @app.get("/api/dashboard/channel/identity")\n'
    block = '''    @app.get("/api/dashboard/channels")
    async def dashboard_channels(tenant: DashboardTenant = Depends(readable)) -> dict[str, Any]:
        return list_channel_accounts(resolver.db, tenant.tenant_id)

    @app.post("/api/dashboard/channels/connect")
    async def dashboard_channel_connect(request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        try:
            if resolver.db.get_secret(tenant.tenant_id, "google:authorized_user_json"):
                capture_current_channel(resolver.db, tenant.tenant_id)
            oauth = GoogleOAuthCoordinator(resolver.db).start(tenant.tenant_id, select_account=True)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit(request, "dashboard_channel_connect_started", "success", tenant.tenant_id)
        return {"authorization_url": oauth.authorization_url, "expires_in_seconds": oauth.expires_in_seconds}

    @app.post("/api/dashboard/channels/{channel_id}/activate")
    async def dashboard_channel_activate(channel_id: str, request: Request, tenant: DashboardTenant = Depends(writable)) -> dict[str, Any]:
        try:
            channel = activate_channel(resolver.db, tenant.tenant_id, channel_id)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        audit(request, "dashboard_channel_activated", "success", tenant.tenant_id, {"channel_id": channel_id})
        return {"ok": True, "channel": channel}

'''
    if anchor not in text:
        raise SystemExit('dashboard channel route anchor not found')
    text = text.replace(anchor, block + anchor, 1)
path.write_text(text, encoding='utf-8')

# Rebuild overview hierarchy.
path = ROOT / 'src/creator_service/web/dashboard.html'
text = path.read_text(encoding='utf-8')
overview = '''      <section id="overview" class="section active">
        <div class="grid">
          <article class="card full" id="channelProfileCard">
            <div class="toolbar" style="justify-content:space-between;align-items:flex-start">
              <div id="channelIdentity" class="channel-hero"><div class="loader"></div><div><h3 style="margin:0">Carregando canal…</h3><div class="muted">Identidade do canal selecionado</div></div></div>
              <span class="pill good" id="profileConnectionBadge"><span class="dot ok"></span><span id="profileConnectionText">Conectado</span></span>
            </div>
            <div class="notice" style="margin-top:14px"><b>Descrição do canal</b><div id="channelDescription" class="muted" style="margin-top:6px;white-space:pre-wrap">Carregando descrição…</div></div>
            <div class="kpis" style="margin-top:14px;grid-template-columns:repeat(5,minmax(0,1fr))">
              <div class="kpi"><strong id="kpiSubs">—</strong><span>Inscritos</span></div>
              <div class="kpi"><strong id="kpiViews">—</strong><span>Views / 28 dias</span></div>
              <div class="kpi"><strong id="kpiTotalViews">—</strong><span>Views totais</span></div>
              <div class="kpi"><strong id="kpiVideos">—</strong><span>Vídeos</span></div>
              <div class="kpi"><strong id="kpiWatch">—</strong><span>Watch time</span></div>
            </div>
            <div class="channel-switch-panel" style="margin-top:14px">
              <div><b>Canais conectados</b><div class="muted">Troque de canal sem sair do Creator Agent. A IA passa a usar o contexto do canal ativo.</div></div>
              <div class="row" style="margin-top:10px;align-items:end">
                <label>Canal ativo<select id="channelSelect"><option>Carregando…</option></select></label>
                <div class="toolbar"><button class="btn" id="activateChannel">Ativar canal</button><button class="btn primary" id="addChannel">+ Adicionar outro canal</button></div>
              </div>
              <div id="channelSwitchHint" class="muted" style="margin-top:8px"></div>
            </div>
          </article>

          <div id="playlistHomeSlot" style="display:contents"></div>

          <article class="card full"><div class="toolbar" style="justify-content:space-between"><div><h3 style="margin:0">Inteligência do mercado do canal</h3><div class="muted">Contexto usado para SEO, pautas e recomendações do canal selecionado.</div></div><span class="pill"><span class="dot ok"></span> contexto isolado por canal</span></div><div class="channel-intel" style="margin-top:12px"><div class="intel-chip"><small>Idioma estratégico</small><strong id="marketLanguage">Detectando…</strong></div><div class="intel-chip"><small>País / mercado</small><strong id="marketCountry">Detectando…</strong></div><div class="intel-chip"><small>Views via busca</small><strong id="searchShare">—</strong></div><div class="intel-chip"><small>Shorts no período</small><strong id="shortShare">—</strong></div><div class="intel-chip"><small>Longos no período</small><strong id="longShare">—</strong></div><div class="intel-chip"><small>Sinal dominante</small><strong id="topSignal">—</strong></div></div></article>

          <article class="card span8"><h3>Perfil aprendido do canal</h3><div id="profileSummary" class="notice">Carregando dados reais...</div><details style="margin-top:10px"><summary class="muted">Ver diagnóstico técnico</summary><div id="profileRaw" class="code" style="margin-top:8px"></div></details></article>
          <article class="card"><h3>Proteção</h3><div class="metric good">Ativa</div><div class="muted">Prévia, confirmação, memória e rollback assinado.</div></article>
          <article class="card"><h3>Inteligência</h3><div class="metric" id="aiMode">...</div><div class="muted" id="aiHint">ChatGPT Native + IA externa opcional</div></article>
          <article class="card span8"><h3>Capacidades conectadas</h3><div id="capabilities" class="muted">Consultando...</div></article>
        </div>
      </section>
'''
pattern = re.compile(r'      <section id="overview" class="section active">.*?      </section>\n\n(?=      <section id="videos")', re.S)
if not pattern.search(text):
    raise SystemExit('overview block not found')
text = pattern.sub(overview + '\n', text, count=1)

if '#channelProfileCard .kpis{grid-template-columns:1fr 1fr!important}' not in text:
    text = text.replace('@media(max-width:760px){body{overflow-x:hidden}', '@media(max-width:760px){#channelProfileCard .kpis{grid-template-columns:1fr 1fr!important}.channel-switch-panel .row{grid-template-columns:1fr}.channel-switch-panel .toolbar .btn{flex:1}body{overflow-x:hidden}', 1)

text = text.replace(
    "function placePlaylistsOnOverview(){const card=$('playlistManager'),grid=document.querySelector('#overview .grid');if(card&&grid&&card.parentNode!==grid){card.classList.add('overview-playlists');grid.appendChild(card)}}",
    "function placePlaylistsOnOverview(){const card=$('playlistManager'),slot=$('playlistHomeSlot');if(card&&slot&&card.parentNode!==slot){card.classList.add('overview-playlists');slot.appendChild(card)}}",
    1,
)

if 'async function loadStatusLegacy(){' not in text:
    text = text.replace('async function loadStatus(){', 'async function loadStatusLegacy(){', 1)
if 'async function loadChannelIdentityLegacy(){' not in text:
    text = text.replace('async function loadChannelIdentity(){', 'async function loadChannelIdentityLegacy(){', 1)

if 'async function loadChannels(){' not in text:
    anchor = 'async function loadCapabilities()'
    funcs = '''async function loadStatus(){try{const s=await api('/api/dashboard/status');const badge=$('profileConnectionBadge'),label=$('profileConnectionText');if(label)label.textContent=s.youtube_connected?'Conectado':'Desconectado';if(badge)badge.className='pill '+(s.youtube_connected?'good':'bad');if($('aiMode'))$('aiMode').textContent=s.chatgpt_native_ready?'ChatGPT Native':'Aguardando';if($('aiHint'))$('aiHint').textContent=s.external_ai_configured?`IA opcional: ${s.ai_provider} / ${s.ai_model}`:'ChatGPT Native ativo; IA externa opcional';$('onlineDot')?.classList.add('ok');if($('onlineText'))$('onlineText').textContent='Online';if(s.ai_provider&&$('provider'))$('provider').value=s.ai_provider;if(s.ai_model&&$('model'))$('model').innerHTML=`<option value="${esc(s.ai_model)}">${esc(s.ai_model)}</option>`;if($('aiSettingsStatus'))$('aiSettingsStatus').textContent=s.external_ai_configured?`Configurado: ${s.ai_provider} / ${s.ai_model}`:'ChatGPT Native pronto. IA externa ainda não configurada.'}catch(e){if($('onlineText'))$('onlineText').textContent=e.message;$('onlineDot')?.classList.remove('ok')}}
async function loadChannelIdentity(){try{const d=await api('/api/dashboard/channel/identity');const box=$('channelIdentity');if(box)box.innerHTML=`<img class="channel-avatar" src="${esc(d.thumbnail||'')}" alt="Foto do canal"><div><h3 style="margin:0">${esc(d.title||'Canal conectado')}</h3><div class="muted">${esc(d.country||'Mercado global')} · ${esc(d.default_language||'idioma detectado pela estratégia')} · ${fmt(d.subscribers)} inscritos</div></div>`;if($('channelDescription'))$('channelDescription').textContent=d.description||'Este canal ainda não possui descrição.';if($('kpiTotalViews'))$('kpiTotalViews').textContent=fmt(d.views||0)}catch(e){if($('channelIdentity'))$('channelIdentity').innerHTML=`<div class="notice bad">${esc(e.message)}</div>`;if($('channelDescription'))$('channelDescription').textContent='Não foi possível carregar a descrição agora.'}}
async function loadChannels(){const select=$('channelSelect');if(!select)return;try{const d=await api('/api/dashboard/channels');const rows=d.channels||[];if(!rows.length){select.innerHTML='<option value="">Nenhum canal salvo</option>';if($('channelSwitchHint'))$('channelSwitchHint').textContent='Conecte um canal para começar.';return}select.innerHTML=rows.map(c=>`<option value="${esc(c.id)}" ${c.active?'selected':''}>${esc(c.title||c.id)}${c.active?' · ativo':''}</option>`).join('');if($('channelSwitchHint'))$('channelSwitchHint').textContent=`${rows.length} canal${rows.length===1?'':'is'} conectado${rows.length===1?'':'s'} nesta conta.`}catch(e){select.innerHTML='<option value="">Canais indisponíveis</option>';if($('channelSwitchHint'))$('channelSwitchHint').textContent=e.message}}
async function activateSelectedChannel(){const id=$('channelSelect')?.value;if(!id)return toast('Selecione um canal.',true);setBusy($('activateChannel'),true,'Ativando');try{await api('/api/dashboard/channels/'+encodeURIComponent(id)+'/activate',{method:'POST',body:'{}'});toast('Canal ativado. Atualizando contexto da IA…');await Promise.allSettled([loadChannels(),loadStatus(),loadChannelIdentity(),loadChannel(),loadPlaylists(),loadVideos()])}catch(e){toast(e.message,true)}finally{setBusy($('activateChannel'),false)}}
async function addAnotherChannel(){setBusy($('addChannel'),true,'Abrindo Google');try{const d=await api('/api/dashboard/channels/connect',{method:'POST',body:'{}'});if(!d.authorization_url)throw new Error('URL de autorização não recebida.');location.href=d.authorization_url}catch(e){toast(e.message,true);setBusy($('addChannel'),false)}}
'''
    if anchor not in text:
        raise SystemExit('capabilities anchor not found')
    text = text.replace(anchor, funcs + anchor, 1)

text = text.replace(
    'async function refreshAll(){await Promise.allSettled([loadStatus(),loadChannel(),loadChannelIdentity(),loadCapabilities(),loadPlaylists(),loadLive()])}',
    'async function refreshAll(){placePlaylistsOnOverview();await Promise.allSettled([loadStatus(),loadChannel(),loadChannelIdentity(),loadChannels(),loadCapabilities(),loadPlaylists(),loadLive()])}',
    1,
)
if "$('activateChannel').onclick" not in text:
    text = text.replace("$('reloadPlaylists').onclick=loadPlaylists;", "$('reloadPlaylists').onclick=loadPlaylists;$('activateChannel').onclick=activateSelectedChannel;$('addChannel').onclick=addAnotherChannel;", 1)
path.write_text(text, encoding='utf-8')

# Contract tests.
test_path = ROOT / 'tests/test_dashboard_elite_ui.py'
test_text = test_path.read_text(encoding='utf-8')
if 'test_overview_prioritizes_channel_profile_and_switcher' not in test_text:
    test_text += '''\n\n\ndef test_overview_prioritizes_channel_profile_and_switcher():\n    html = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")\n    assert 'id="channelProfileCard"' in html\n    assert 'id="channelDescription"' in html\n    assert 'id="kpiTotalViews"' in html\n    assert 'id="channelSelect"' in html\n    assert 'id="addChannel"' in html\n    assert 'id="playlistHomeSlot"' in html\n    assert html.index('id="channelProfileCard"') < html.index('id="playlistHomeSlot"') < html.index('Inteligência do mercado do canal')\n\n\ndef test_multi_channel_backend_contract_exists():\n    code = Path("src/creator_service/channel_accounts.py").read_text(encoding="utf-8")\n    routes = Path("src/creator_service/dashboard_routes.py").read_text(encoding="utf-8")\n    assert 'CHANNEL_REGISTRY_SECRET' in code\n    assert 'def activate_channel' in code\n    assert '/api/dashboard/channels/connect' in routes\n    assert '/api/dashboard/channels/{channel_id}/activate' in routes\n'''
    test_path.write_text(test_text, encoding='utf-8')

print('overview-channels-v5 patch applied')
