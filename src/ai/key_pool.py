from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def mask_api_key(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:2]}***{value[-2:]}"
    return f"{value[:5]}{'*' * 10}{value[-4:]}"


@dataclass
class APIKeyRecord:
    id: str
    provider: str
    masked: str
    label: str = ""
    enabled: bool = True
    status: str = "unknown"  # unknown | ok | warning | error
    last_error: str = ""
    last_error_at: str = ""
    last_success_at: str = ""
    last_model: str = ""
    preferred_model: str = ""


class APIKeyPoolStore:
    """Non-secret metadata for tenant-scoped API key pools.

    Secret values never live here. Cloud deployments keep each key encrypted in
    TenantCredentialStore while this file stores only display-safe metadata,
    health state, active selection and rotation preferences.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 2, "providers": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 2, "providers": {}}
        if not isinstance(payload, dict):
            return {"version": 2, "providers": {}}
        payload.setdefault("version", 2)
        payload.setdefault("providers", {})
        return payload

    def _save(self, payload: dict) -> None:
        payload["version"] = 2
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @staticmethod
    def _provider(provider: str) -> str:
        value = (provider or "").strip().lower()
        if not value:
            raise ValueError("Provedor de IA inválido.")
        return value

    def _bucket(self, payload: dict, provider: str) -> dict:
        provider = self._provider(provider)
        providers = payload.setdefault("providers", {})
        bucket = providers.setdefault(
            provider,
            {"auto_rotate": False, "active_key_id": "", "keys": []},
        )
        bucket.setdefault("auto_rotate", False)
        bucket.setdefault("active_key_id", "")
        bucket.setdefault("keys", [])
        return bucket

    def list(self, provider: str) -> list[APIKeyRecord]:
        payload = self._load()
        bucket = self._bucket(payload, provider)
        records: list[APIKeyRecord] = []
        for raw in bucket.get("keys", []):
            if not isinstance(raw, dict):
                continue
            normalized = dict(raw)
            normalized.setdefault("preferred_model", "")
            try:
                records.append(APIKeyRecord(**normalized))
            except TypeError:
                continue
        return records

    def get(self, provider: str, key_id: str) -> APIKeyRecord | None:
        for item in self.list(provider):
            if item.id == key_id:
                return item
        return None

    def active_key_id(self, provider: str) -> str:
        payload = self._load()
        return str(self._bucket(payload, provider).get("active_key_id", ""))

    def auto_rotate(self, provider: str) -> bool:
        payload = self._load()
        return bool(self._bucket(payload, provider).get("auto_rotate", False))

    def set_auto_rotate(self, provider: str, enabled: bool) -> None:
        payload = self._load()
        self._bucket(payload, provider)["auto_rotate"] = bool(enabled)
        self._save(payload)

    def set_active(self, provider: str, key_id: str) -> None:
        payload = self._load()
        bucket = self._bucket(payload, provider)
        ids = {str(item.get("id", "")) for item in bucket.get("keys", [])}
        if key_id and key_id not in ids:
            raise KeyError("Chave não encontrada no pool.")
        bucket["active_key_id"] = key_id
        self._save(payload)

    def add(self, provider: str, api_key: str, label: str = "") -> APIKeyRecord:
        provider = self._provider(provider)
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("A chave API não pode ser vazia.")
        payload = self._load()
        bucket = self._bucket(payload, provider)
        record = APIKeyRecord(
            id=secrets.token_hex(8),
            provider=provider,
            masked=mask_api_key(api_key),
            label=" ".join((label or "").split())[:80],
        )
        bucket["keys"].append(asdict(record))
        if not bucket.get("active_key_id"):
            bucket["active_key_id"] = record.id
        self._save(payload)
        return record

    def delete(self, provider: str, key_id: str) -> None:
        payload = self._load()
        bucket = self._bucket(payload, provider)
        bucket["keys"] = [item for item in bucket.get("keys", []) if item.get("id") != key_id]
        if bucket.get("active_key_id") == key_id:
            bucket["active_key_id"] = str(bucket["keys"][0].get("id", "")) if bucket["keys"] else ""
        self._save(payload)

    def set_enabled(self, provider: str, key_id: str, enabled: bool) -> None:
        self._patch(provider, key_id, enabled=bool(enabled))

    def set_label(self, provider: str, key_id: str, label: str) -> None:
        clean = " ".join((label or "").split())[:80]
        self._patch(provider, key_id, label=clean)

    def set_preferred_model(self, provider: str, key_id: str, model: str) -> None:
        self._patch(provider, key_id, preferred_model=" ".join((model or "").split())[:200])

    def mark_success(self, provider: str, key_id: str, model: str = "") -> None:
        changes = {
            "status": "ok",
            "last_error": "",
            "last_success_at": _utc_now(),
            "last_model": (model or "")[:200],
        }
        if model:
            changes["preferred_model"] = (model or "")[:200]
        self._patch(provider, key_id, **changes)

    def mark_failure(self, provider: str, key_id: str, error: str, *, warning: bool, model: str = "") -> None:
        self._patch(
            provider,
            key_id,
            status="warning" if warning else "error",
            last_error=" ".join(str(error).split())[:500],
            last_error_at=_utc_now(),
            last_model=(model or "")[:200],
        )

    def _patch(self, provider: str, key_id: str, **changes) -> None:
        payload = self._load()
        bucket = self._bucket(payload, provider)
        found = False
        for item in bucket.get("keys", []):
            if item.get("id") == key_id:
                item.update(changes)
                found = True
                break
        if not found:
            raise KeyError("Chave não encontrada no pool.")
        self._save(payload)

    def ordered_enabled_ids(self, provider: str) -> list[str]:
        records = [item for item in self.list(provider) if item.enabled]
        if not records:
            return []
        active = self.active_key_id(provider)
        ids = [item.id for item in records]
        if active in ids:
            ids.remove(active)
            ids.insert(0, active)
        return ids

    def export_public(self, provider: str) -> list[dict]:
        active = self.active_key_id(provider)
        return [
            {
                **asdict(item),
                "active": item.id == active,
            }
            for item in self.list(provider)
        ]
