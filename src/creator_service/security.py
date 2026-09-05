from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalPayload:
    action: str
    subject: str
    digest: str
    expires_at: int


class ApprovalTokenSigner:
    """Stateless HMAC approvals for exact write payloads.

    A preview signs the action + target + normalized payload hash. The write
    endpoint must present the same token and exact payload before it can run.
    """

    def __init__(self, secret: str | bytes, ttl_seconds: int = 900):
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if len(secret) < 24:
            raise ValueError("Approval secret must have at least 24 bytes.")
        self.secret = secret
        self.ttl_seconds = max(60, int(ttl_seconds))

    @staticmethod
    def payload_digest(payload: dict) -> str:
        normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @staticmethod
    def _encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    def issue(self, action: str, subject: str, payload: dict, now: int | None = None) -> str:
        now = int(time.time() if now is None else now)
        body = {
            "action": action,
            "subject": subject,
            "digest": self.payload_digest(payload),
            "expires_at": now + self.ttl_seconds,
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self.secret, raw, hashlib.sha256).digest()
        return f"{self._encode(raw)}.{self._encode(signature)}"

    def verify(
        self,
        token: str,
        *,
        action: str,
        subject: str,
        payload: dict,
        now: int | None = None,
    ) -> ApprovalPayload:
        try:
            raw_part, sig_part = token.split(".", 1)
            raw = self._decode(raw_part)
            provided = self._decode(sig_part)
        except Exception as exc:
            raise ValueError("Approval token is malformed.") from exc

        expected = hmac.new(self.secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(provided, expected):
            raise ValueError("Approval token signature is invalid.")

        try:
            body = json.loads(raw.decode("utf-8"))
            parsed = ApprovalPayload(
                action=str(body["action"]),
                subject=str(body["subject"]),
                digest=str(body["digest"]),
                expires_at=int(body["expires_at"]),
            )
        except Exception as exc:
            raise ValueError("Approval token payload is invalid.") from exc

        current = int(time.time() if now is None else now)
        if parsed.expires_at < current:
            raise ValueError("Approval token has expired. Generate a new preview.")
        if parsed.action != action or parsed.subject != subject:
            raise ValueError("Approval token does not authorize this action/target.")
        if parsed.digest != self.payload_digest(payload):
            raise ValueError("The write payload changed after approval.")
        return parsed


def signer_from_env() -> ApprovalTokenSigner:
    secret = os.environ.get("YCA_APPROVAL_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "YCA_APPROVAL_SECRET is required for write operations. "
            "Set a random secret with at least 24 characters on the server."
        )
    return ApprovalTokenSigner(secret)
