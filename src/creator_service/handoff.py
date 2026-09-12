from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import zlib
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


HANDOFF_VERSION = "YCA_HANDOFF_V1"
HANDOFF_AAD = b"youtube-creator-agent:handoff:v1"
HANDOFF_DEFAULT_TTL_SECONDS = 300
HANDOFF_MAX_TTL_SECONDS = 600
HANDOFF_MAX_DECOMPRESSED_BYTES = 64 * 1024
_ALLOWED_CHANGED_FIELDS = {"title", "description", "tags", "categoryId", "playlist"}
_B64URL_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


class HandoffError(ValueError):
    """Raised when an AI handoff package is malformed, expired or unauthentic."""


@dataclass(frozen=True)
class HandoffPackage:
    version: str
    ticket_id: str
    tenant_id: str
    channel_id: str
    video_id: str
    baseline_digest: str
    proposed_digest: str
    proposed: dict[str, Any]
    changed_fields: tuple[str, ...]
    playlist_id: str
    source: str
    issued_at: int
    expires_at: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ticket_id": self.ticket_id,
            "tenant_id": self.tenant_id,
            "channel_id": self.channel_id,
            "video_id": self.video_id,
            "baseline_digest": self.baseline_digest,
            "proposed_digest": self.proposed_digest,
            "proposed": dict(self.proposed),
            "changed_fields": list(self.changed_fields),
            "playlist_id": self.playlist_id,
            "source": self.source,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    # Handoff replay protection hashes the exact ticket string. Accepting multiple
    # textual Base64URL aliases for the same ciphertext would therefore create
    # distinct replay-ledger keys for one cryptographic package. Require the
    # unpadded RFC 4648 representation to be canonical before accepting it.
    if not value or any(ch not in _B64URL_ALPHABET for ch in value):
        raise HandoffError("Ticket de handoff inválido.")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)
    except Exception as exc:  # pragma: no cover - implementation detail
        raise HandoffError("Ticket de handoff inválido.") from exc
    if _b64url_encode(decoded) != value:
        raise HandoffError("Ticket de handoff inválido.")
    return decoded


def canonical_digest(payload: Any) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _handoff_key(secret: str | bytes | None = None) -> bytes:
    if secret is None:
        secret = os.environ.get("YCA_APPROVAL_SECRET", "").strip()
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not secret or len(secret) < 24:
        raise RuntimeError("YCA_APPROVAL_SECRET é obrigatório e deve ter pelo menos 24 bytes.")
    return hashlib.sha256(b"YCA_HANDOFF_KEY_V1\x00" + secret).digest()


def _validate_digest(value: str, field: str) -> str:
    value = str(value or "").strip().lower()
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise HandoffError(f"{field} inválido no handoff.")
    return value


def _validate_identifier(value: Any, field: str, *, max_length: int = 200) -> str:
    text = str(value or "").strip()
    if not text or len(text) > max_length:
        raise HandoffError(f"{field} inválido no handoff.")
    return text


def _normalize_changed_fields(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise HandoffError("changed_fields inválido no handoff.")
    output: list[str] = []
    for raw in value:
        field = str(raw or "").strip()
        if field not in _ALLOWED_CHANGED_FIELDS:
            raise HandoffError("Campo de alteração não permitido no handoff.")
        if field not in output:
            output.append(field)
    if not output:
        raise HandoffError("O handoff não contém nenhuma alteração.")
    return tuple(output)


def _package_from_dict(body: dict[str, Any], *, now: int | None = None) -> HandoffPackage:
    current = int(time.time() if now is None else now)
    if str(body.get("version", "")) != HANDOFF_VERSION:
        raise HandoffError("Versão de handoff incompatível.")

    issued_at = int(body.get("issued_at", 0) or 0)
    expires_at = int(body.get("expires_at", 0) or 0)
    if issued_at <= 0 or expires_at <= issued_at:
        raise HandoffError("Validade do handoff é inválida.")
    if expires_at - issued_at > HANDOFF_MAX_TTL_SECONDS:
        raise HandoffError("Validade do handoff excede o limite permitido.")
    if issued_at > current + 60:
        raise HandoffError("Data de emissão do handoff está no futuro.")
    if expires_at < current:
        raise HandoffError("Este handoff expirou. Gere uma nova análise.")

    proposed = body.get("proposed")
    if not isinstance(proposed, dict):
        raise HandoffError("Payload proposto inválido no handoff.")
    if str(proposed.get("video_id", "")).strip() != str(body.get("video_id", "")).strip():
        raise HandoffError("O alvo interno do handoff não corresponde ao vídeo assinado.")

    proposed_digest = _validate_digest(str(body.get("proposed_digest", "")), "proposed_digest")
    if canonical_digest(proposed) != proposed_digest:
        raise HandoffError("O payload do handoff foi alterado.")

    return HandoffPackage(
        version=HANDOFF_VERSION,
        ticket_id=_validate_identifier(body.get("ticket_id"), "ticket_id", max_length=120),
        tenant_id=_validate_identifier(body.get("tenant_id"), "tenant_id"),
        channel_id=_validate_identifier(body.get("channel_id"), "channel_id", max_length=120),
        video_id=_validate_identifier(body.get("video_id"), "video_id", max_length=120),
        baseline_digest=_validate_digest(str(body.get("baseline_digest", "")), "baseline_digest"),
        proposed_digest=proposed_digest,
        proposed=dict(proposed),
        changed_fields=_normalize_changed_fields(body.get("changed_fields")),
        playlist_id=str(body.get("playlist_id", "") or "").strip()[:200],
        source=str(body.get("source", "chatgpt") or "chatgpt").strip()[:40],
        issued_at=issued_at,
        expires_at=expires_at,
    )


def seal_handoff(
    *,
    tenant_id: str,
    channel_id: str,
    video_id: str,
    baseline_digest: str,
    proposed: dict[str, Any],
    changed_fields: list[str],
    playlist_id: str = "",
    source: str = "chatgpt",
    ttl_seconds: int = HANDOFF_DEFAULT_TTL_SECONDS,
    now: int | None = None,
    secret: str | bytes | None = None,
) -> tuple[str, HandoffPackage]:
    timestamp = int(time.time() if now is None else now)
    ttl = max(60, min(HANDOFF_MAX_TTL_SECONDS, int(ttl_seconds)))
    body = {
        "version": HANDOFF_VERSION,
        "ticket_id": secrets.token_urlsafe(18),
        "tenant_id": str(tenant_id).strip(),
        "channel_id": str(channel_id).strip(),
        "video_id": str(video_id).strip(),
        "baseline_digest": str(baseline_digest).strip().lower(),
        "proposed_digest": canonical_digest(proposed),
        "proposed": proposed,
        "changed_fields": list(changed_fields),
        "playlist_id": str(playlist_id or "").strip(),
        "source": str(source or "chatgpt").strip(),
        "issued_at": timestamp,
        "expires_at": timestamp + ttl,
    }
    package = _package_from_dict(body, now=timestamp)
    raw = json.dumps(package.as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > HANDOFF_MAX_DECOMPRESSED_BYTES:
        raise HandoffError("O pacote de handoff excede o limite seguro.")
    compressed = zlib.compress(raw, level=9)
    nonce = os.urandom(12)
    encrypted = AESGCM(_handoff_key(secret)).encrypt(nonce, compressed, HANDOFF_AAD)
    return f"v1.{_b64url_encode(nonce + encrypted)}", package


def open_handoff(
    ticket: str,
    *,
    now: int | None = None,
    secret: str | bytes | None = None,
) -> HandoffPackage:
    raw_ticket = str(ticket or "").strip()
    if not raw_ticket.startswith("v1.") or len(raw_ticket) > 120_000:
        raise HandoffError("Ticket de handoff inválido.")
    encrypted = _b64url_decode(raw_ticket[3:])
    if len(encrypted) < 12 + 16:
        raise HandoffError("Ticket de handoff inválido.")
    nonce, ciphertext = encrypted[:12], encrypted[12:]
    try:
        compressed = AESGCM(_handoff_key(secret)).decrypt(nonce, ciphertext, HANDOFF_AAD)
    except Exception as exc:
        raise HandoffError("Assinatura criptográfica do handoff é inválida.") from exc
    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(compressed, HANDOFF_MAX_DECOMPRESSED_BYTES + 1)
        if decompressor.unconsumed_tail or len(raw) > HANDOFF_MAX_DECOMPRESSED_BYTES:
            raise HandoffError("O pacote de handoff excede o limite seguro.")
        raw += decompressor.flush()
        body = json.loads(raw.decode("utf-8"))
    except HandoffError:
        raise
    except Exception as exc:
        raise HandoffError("Conteúdo do handoff é inválido.") from exc
    if not isinstance(body, dict):
        raise HandoffError("Conteúdo do handoff é inválido.")
    return _package_from_dict(body, now=now)


def build_handoff_url(ticket: str, public_origin: str) -> str:
    origin = str(public_origin or "").strip().rstrip("/")
    if not origin.startswith("https://"):
        raise RuntimeError("YCA_ONBOARDING_PUBLIC_URL deve usar HTTPS para handoff.")
    # The ticket stays in the URL fragment. Browsers do not send fragments in
    # the initial HTTP request, keeping the opaque package out of proxy logs and
    # referrer headers.
    return f"{origin}/handoff/v1#ticket={ticket}"
