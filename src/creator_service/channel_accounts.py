from __future__ import annotations

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
