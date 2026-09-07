from __future__ import annotations

import json
import sqlite3
import traceback
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

try:
    from googleapiclient.errors import HttpError
except Exception:  # pragma: no cover - dependency is present in cloud runtime
    HttpError = ()  # type: ignore[assignment]

from .observability import configure_json_logging


T = TypeVar("T")


@dataclass(frozen=True)
class CreatorToolError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


ERROR_MESSAGES: dict[str, str] = {
    "confirmation_required": "Explicit user confirmation is required.",
    "write_scope_missing": "The authenticated session does not have yca:write permission.",
    "read_scope_missing": "The authenticated session does not have yca:read permission.",
    "channel_not_found": "The requested channel is not connected to this account.",
    "video_not_found": "The requested video was not found.",
    "video_not_owned": "The requested video does not belong to the authorized channel.",
    "approval_expired": "The approval token has expired.",
    "approval_invalid": "The approval token is invalid.",
    "payload_mismatch": "The payload does not match the signed approval.",
    "approval_replayed": "This approval token has already been used.",
    "external_change_detected": "The video changed after the preview; a new preview is required.",
    "recent_edit_protected": "This video is protected against another recent edit.",
    "youtube_api_error": "YouTube rejected or could not complete the requested operation.",
    "caption_not_available": "No usable caption track is available for this video.",
    "transcription_failed": "The video could not be transcribed safely.",
    "unsupported_ai_model": "The selected AI model is incompatible with the configured API operation.",
    "database_error": "The operation could not be completed because of a database error.",
    "rate_limited": "The operation was temporarily rate limited.",
    "invalid_request": "The request is invalid.",
    "internal_error": "An internal error occurred while executing the tool.",
}


def tool_error(code: str, message: str | None = None) -> CreatorToolError:
    return CreatorToolError(code=code, message=message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["internal_error"]))


def _message(exc: BaseException) -> str:
    return " ".join(str(exc).strip().split()).casefold()


def classify_exception(exc: BaseException) -> CreatorToolError:
    if isinstance(exc, CreatorToolError):
        return exc

    text = _message(exc)
    if isinstance(exc, sqlite3.DatabaseError):
        return tool_error("database_error")
    if HttpError and isinstance(exc, HttpError):  # type: ignore[arg-type]
        return tool_error("youtube_api_error")

    if "confirmation" in text or "confirmação explícita" in text:
        return tool_error("confirmation_required")
    if "escopo obrigatório ausente: yca:write" in text or "yca:write" in text and "ausente" in text:
        return tool_error("write_scope_missing")
    if "escopo obrigatório ausente: yca:read" in text or "yca:read" in text and "ausente" in text:
        return tool_error("read_scope_missing")
    if "já utilizada" in text or "already been used" in text or "replay" in text:
        return tool_error("approval_replayed")
    if "expired" in text or "expir" in text:
        return tool_error("approval_expired")
    if "changed after approval" in text or "payload changed" in text or "payload foi alterado" in text:
        return tool_error("payload_mismatch")
    if "signature is invalid" in text or "malformed" in text or "does not authorize" in text:
        return tool_error("approval_invalid")
    if "mudou desde" in text or "changed since" in text or "baseline" in text and "digest" in text:
        return tool_error("external_change_detected")
    if "proteção de memória ativa" in text or "recently edited" in text:
        return tool_error("recent_edit_protected")
    if "não pertence" in text or "does not belong" in text:
        return tool_error("video_not_owned")
    if "vídeo não encontrado" in text or "video not found" in text:
        return tool_error("video_not_found")
    if "canal não" in text and "conect" in text or "channel not" in text and "connect" in text:
        return tool_error("channel_not_found")
    if "no_caption_track" in text or "caption_download_unavailable" in text or "legenda" in text and "indispon" in text:
        return tool_error("caption_not_available")
    if "transcri" in text or "recognition" in text and "speech" in text:
        return tool_error("transcription_failed")
    if "only supports interactions api" in text or "not supported for generatecontent" in text or "unsupported model" in text:
        return tool_error("unsupported_ai_model")
    if "limite temporário" in text or "rate limit" in text:
        return tool_error("rate_limited")
    if isinstance(exc, (ValueError, TypeError)):
        return tool_error("invalid_request", str(exc)[:500] or ERROR_MESSAGES["invalid_request"])
    return tool_error("internal_error")


def error_response(exc: BaseException) -> dict[str, Any]:
    mapped = classify_exception(exc)
    return {"success": False, "error": {"code": mapped.code, "message": mapped.message}}


def success_response(payload: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"success": True}
    if payload:
        result.update(payload)
    result.update(extra)
    return result


def log_tool_exception(operation: str, exc: BaseException, *, tenant_id: str | None = None) -> None:
    """Log stack frames without serializing request payloads, tokens or credentials."""
    mapped = classify_exception(exc)
    frames = [
        {"file": frame.filename, "line": frame.lineno, "function": frame.name}
        for frame in traceback.extract_tb(exc.__traceback__)
    ]
    logger = configure_json_logging()
    logger.error(
        json.dumps(
            {
                "event": "mcp_tool_exception",
                "operation": operation,
                "tenant_id": tenant_id,
                "error_code": mapped.code,
                "exception_type": type(exc).__name__,
                "traceback": frames,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def structured_call(operation: str, callback: Callable[[], T], *, tenant_id: str | None = None) -> T | dict[str, Any]:
    try:
        return callback()
    except Exception as exc:
        log_tool_exception(operation, exc, tenant_id=tenant_id)
        return error_response(exc)
