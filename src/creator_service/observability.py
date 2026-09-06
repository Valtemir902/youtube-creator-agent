from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

from fastapi import Request, Response


LOGGER_NAME = "youtube_creator_agent"


def configure_json_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger
    level_name = os.environ.get("YCA_LOG_LEVEL", "INFO").upper().strip()
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(event: str, **fields: Any) -> None:
    logger = configure_json_logging()
    payload = {
        "ts": int(time.time()),
        "event": event,
        **{key: value for key, value in fields.items() if value is not None},
    }
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))


def request_id_from(request: Request) -> str:
    incoming = request.headers.get("x-request-id", "").strip()
    if incoming and len(incoming) <= 80 and all(ch.isalnum() or ch in "-_." for ch in incoming):
        return incoming
    return uuid.uuid4().hex


async def production_http_middleware(request: Request, call_next) -> Response:
    request_id = request_id_from(request)
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        status_code = 500
        raise
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        log_event(
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=status_code,
            elapsed_ms=elapsed_ms,
        )
        response_obj = locals().get("response")
        if response_obj is not None:
            response_obj.headers["X-Request-ID"] = request_id
            response_obj.headers["X-Content-Type-Options"] = "nosniff"
            response_obj.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response_obj.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response_obj.headers["X-Frame-Options"] = "DENY"
            response_obj.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
                "connect-src 'self' https://challenges.cloudflare.com; "
                "frame-src https://challenges.cloudflare.com; "
                "frame-ancestors 'none'; base-uri 'self'",
            )
