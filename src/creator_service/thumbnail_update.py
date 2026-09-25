from __future__ import annotations

import base64
import binascii
import hashlib
import io
import ipaddress
import json
import logging
import math
import socket
import time
import warnings
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import requests
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image, ImageOps, UnidentifiedImageError

from .mcp_errors import CreatorToolError, tool_error
from .security import signer_from_env
from .thumbnail_staging import ThumbnailAssetStore, ThumbnailStagingStore


YOUTUBE_THUMBNAIL_LIMITS = {
    "max_upload_bytes": 50 * 1024 * 1024,
    "accepted_output_mime_types": ("image/jpeg", "image/png"),
    "api_media_mime_types": ("image/jpeg", "image/png", "application/octet-stream"),
    "recommended_video_width": 3840,
    "recommended_video_height": 2160,
    "recommended_video_ratio": 16 / 9,
    "minimum_video_width": 640,
}
YOUTUBE_THUMBNAIL_MAX_BYTES = int(YOUTUBE_THUMBNAIL_LIMITS["max_upload_bytes"])
YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH = int(YOUTUBE_THUMBNAIL_LIMITS["minimum_video_width"])
YOUTUBE_THUMBNAIL_RECOMMENDED_WIDTH = int(YOUTUBE_THUMBNAIL_LIMITS["recommended_video_width"])
YOUTUBE_THUMBNAIL_RECOMMENDED_HEIGHT = int(YOUTUBE_THUMBNAIL_LIMITS["recommended_video_height"])
YOUTUBE_THUMBNAIL_RECOMMENDED_RATIO = float(YOUTUBE_THUMBNAIL_LIMITS["recommended_video_ratio"])

THUMBNAIL_MAX_SOURCE_BYTES = 64 * 1024 * 1024
THUMBNAIL_MAX_PIXELS = 100_000_000
THUMBNAIL_NORMALIZED_MAX_LONG_EDGE = 3840
THUMBNAIL_DOWNLOAD_CONNECT_TIMEOUT = 5
THUMBNAIL_DOWNLOAD_READ_TIMEOUT = 10
THUMBNAIL_MAX_REDIRECTS = 3
THUMBNAIL_VERIFY_DELAYS = (0.0, 1.0, 2.0, 4.0)
THUMBNAIL_APPROVAL_TTL_SECONDS = 900

_INPUT_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
}
_OUTPUT_FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
}
_ALLOWED_REMOTE_HEADER_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
    "application/octet-stream",
}
_EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
_ALLOWED_FILE_SOURCE_TYPES = {"generated_file", "uploaded_file"}
_LOGGER = logging.getLogger("youtube_creator_agent.thumbnail")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_hash_prefix(value: str) -> str:
    return str(value or "")[:12]


def _log_thumbnail_event(event: str, **details: Any) -> None:
    safe = {
        key: value
        for key, value in details.items()
        if key not in {"approval_token", "thumbnail_bytes", "thumbnail_url", "url"}
    }
    _LOGGER.info(json.dumps({"event": event, **safe}, ensure_ascii=False, separators=(",", ":")))


def _canonical_https_url(raw: str) -> str:
    value = str(raw or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise tool_error("thumbnail_source_invalid", "A URL da thumbnail é inválida.") from exc
    if parsed.scheme.lower() != "https":
        raise tool_error("thumbnail_source_invalid", "A fonte remota da thumbnail deve usar HTTPS.")
    if parsed.username or parsed.password:
        raise tool_error("thumbnail_source_invalid", "Credenciais embutidas na URL da thumbnail não são permitidas.")
    host = str(parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise tool_error("thumbnail_source_invalid", "A URL da thumbnail não possui host válido.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise tool_error("thumbnail_source_invalid", "A porta da URL da thumbnail é inválida.") from exc
    if port not in (None, 443):
        raise tool_error("thumbnail_source_invalid", "Somente HTTPS na porta padrão é permitido para thumbnails remotas.")
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))


def _validated_authorized_https_url(raw: str) -> str:
    """Validate an authorized host URL without rewriting its signed representation."""
    value = str(raw or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise tool_error("thumbnail_source_invalid", "A URL autorizada do arquivo é inválida.") from exc
    if parsed.scheme.lower() != "https":
        raise tool_error("thumbnail_source_invalid", "O download autorizado do arquivo deve usar HTTPS.")
    if parsed.username or parsed.password:
        raise tool_error("thumbnail_source_invalid", "Credenciais embutidas na URL autorizada não são permitidas.")
    host = str(parsed.hostname or "").strip().rstrip(".")
    if not host:
        raise tool_error("thumbnail_source_invalid", "A URL autorizada não possui host válido.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise tool_error("thumbnail_source_invalid", "A porta da URL autorizada é inválida.") from exc
    if port not in (None, 443):
        raise tool_error("thumbnail_source_invalid", "Somente HTTPS na porta padrão é permitido para arquivos autorizados.")
    return value


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_public_host(url: str) -> None:
    host = str(urlsplit(url).hostname or "")
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise tool_error("thumbnail_source_unavailable", "Não foi possível resolver o host HTTPS da thumbnail.") from exc
    addresses = {str(info[4][0]) for info in infos if info and info[4]}
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise tool_error(
            "thumbnail_source_invalid",
            "A URL da thumbnail resolve para uma rede privada, local ou não permitida.",
        )


def _url_extension(url: str) -> str:
    return PurePosixPath(urlsplit(url).path).suffix.casefold()


def _safe_source_name(name: str | None, fallback: str) -> str:
    raw = str(name or "").replace("\\", "/").strip()
    leaf = PurePosixPath(raw).name if raw else fallback
    return leaf[:255] or fallback


def _decode_base64_payload(value: str, *, field_name: str) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        raise tool_error("thumbnail_source_invalid", f"{field_name} está vazio.")
    prefix = "base64,"
    if raw.startswith("data:"):
        if prefix not in raw:
            raise tool_error("thumbnail_source_invalid", "Data URI da thumbnail precisa usar base64.")
        raw = raw.split(prefix, 1)[1]
    max_encoded = math.ceil(THUMBNAIL_MAX_SOURCE_BYTES / 3) * 4 + 16
    if len(raw) > max_encoded:
        raise tool_error(
            "thumbnail_too_large",
            "A fonte binária da thumbnail excede o limite seguro de entrada.",
            details={"max_source_bytes": THUMBNAIL_MAX_SOURCE_BYTES},
        )
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise tool_error("thumbnail_source_invalid", "A fonte binária da thumbnail não contém base64 válido.") from exc
    if not data:
        raise tool_error("thumbnail_source_invalid", "A fonte binária da thumbnail está vazia.")
    if len(data) > THUMBNAIL_MAX_SOURCE_BYTES:
        raise tool_error(
            "thumbnail_too_large",
            "A fonte binária da thumbnail excede o limite seguro de entrada.",
            details={"source_size_bytes": len(data), "max_source_bytes": THUMBNAIL_MAX_SOURCE_BYTES},
        )
    return data


def _thumbnail_urls(thumbnails: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str((value or {}).get("url", "")).strip()
            for value in (thumbnails or {}).values()
            if isinstance(value, dict) and str((value or {}).get("url", "")).strip()
        }
    )


def _thumbnail_map_fingerprint(thumbnails: dict[str, Any]) -> str:
    compact = {
        str(key): {
            "url": str((value or {}).get("url", "")),
            "width": (value or {}).get("width"),
            "height": (value or {}).get("height"),
        }
        for key, value in sorted((thumbnails or {}).items())
        if isinstance(value, dict)
    }
    return signer_from_env().payload_digest(compact)


def _decode_image(data: bytes) -> tuple[Image.Image, dict[str, Any]]:
    if not data:
        raise tool_error("thumbnail_decode_failed", "A imagem da thumbnail está vazia.")
    if len(data) > THUMBNAIL_MAX_SOURCE_BYTES:
        raise tool_error(
            "thumbnail_too_large",
            "A imagem de origem excede o limite seguro de entrada.",
            details={"source_size_bytes": len(data), "max_source_bytes": THUMBNAIL_MAX_SOURCE_BYTES},
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            width, height = probe.size
            image_format = str(probe.format or "").upper()
            claimed_mode = str(probe.mode or "")
            has_alpha = claimed_mode in {"RGBA", "LA"} or "transparency" in probe.info
            if width <= 0 or height <= 0 or width * height > THUMBNAIL_MAX_PIXELS:
                raise tool_error(
                    "thumbnail_validation_failed",
                    "As dimensões da thumbnail são inválidas ou excessivas.",
                    details={"width": width, "height": height, "max_pixels": THUMBNAIL_MAX_PIXELS},
                )
            probe.verify()

            image = Image.open(io.BytesIO(data))
            exif_orientation = int(image.getexif().get(274, 1) or 1)
            image.load()
            if exif_orientation != 1:
                image = ImageOps.exif_transpose(image)
                width, height = image.size
    except CreatorToolError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise tool_error("thumbnail_decode_failed", "A imagem está corrompida, insegura ou não pôde ser decodificada.") from exc

    mime_type = _INPUT_FORMAT_TO_MIME.get(image_format)
    if not mime_type:
        raise tool_error(
            "thumbnail_format_unsupported",
            "O formato real da imagem não é suportado para normalização segura.",
            details={"detected_format": image_format or None, "supported_input_formats": sorted(_INPUT_FORMAT_TO_MIME)},
        )
    return image, {
        "format": image_format,
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "file_size_bytes": len(data),
        "has_alpha": bool(has_alpha),
        "exif_orientation": exif_orientation,
    }


def _inspect_source_image(
    data: bytes,
    *,
    source_name: str,
    claimed_mime_type: str | None = None,
    header_content_type: str | None = None,
) -> dict[str, Any]:
    image, info = _decode_image(data)
    image.close()
    detected_mime = str(info["mime_type"])
    claimed = str(claimed_mime_type or "").split(";", 1)[0].strip().casefold()
    header = str(header_content_type or "").split(";", 1)[0].strip().casefold()
    if claimed and claimed not in {detected_mime, "application/octet-stream"}:
        raise tool_error(
            "thumbnail_validation_failed",
            "O MIME declarado não corresponde ao formato real da imagem.",
            details={"claimed_mime_type": claimed, "detected_mime_type": detected_mime},
        )
    if header:
        if header not in _ALLOWED_REMOTE_HEADER_MIME:
            raise tool_error(
                "thumbnail_validation_failed",
                "O Content-Type remoto não é permitido para uma thumbnail.",
                details={"content_type": header},
            )
        if header != "application/octet-stream" and header != detected_mime:
            raise tool_error(
                "thumbnail_validation_failed",
                "O Content-Type remoto não corresponde ao formato real da imagem.",
                details={"content_type": header, "detected_mime_type": detected_mime},
            )
    extension = PurePosixPath(str(source_name or "")).suffix.casefold()
    if extension:
        expected = _EXTENSION_TO_MIME.get(extension)
        if expected is None or expected != detected_mime:
            raise tool_error(
                "thumbnail_validation_failed",
                "A extensão explícita da fonte não corresponde ao formato real da imagem.",
                details={"extension": extension, "detected_mime_type": detected_mime},
            )
    return {
        **info,
        "source_name": source_name,
        "sha256": _sha256_bytes(data),
    }


def _inspect_image(data: bytes, *, source_url: str, header_content_type: str | None) -> dict[str, Any]:
    """Backward-compatible URL validation helper retained for existing callers/tests."""
    source_name = PurePosixPath(urlsplit(source_url).path).name or "thumbnail"
    info = _inspect_source_image(
        data,
        source_name=source_name,
        header_content_type=header_content_type,
    )
    ratio = info["width"] / info["height"]
    valid = info["width"] >= YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH
    result = {
        "mime_type": info["mime_type"],
        "file_size_bytes": info["file_size_bytes"],
        "file_size_limit": YOUTUBE_THUMBNAIL_MAX_BYTES,
        "width": info["width"],
        "height": info["height"],
        "aspect_ratio": round(ratio, 6),
        "recommended_aspect_ratio": "16:9",
        "recommended_resolution": {
            "width": YOUTUBE_THUMBNAIL_RECOMMENDED_WIDTH,
            "height": YOUTUBE_THUMBNAIL_RECOMMENDED_HEIGHT,
        },
        "minimum_video_width": YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH,
        "format_supported": True,
        "extension_supported": True,
        "extension_consistent": True,
        "dimensions_valid": valid,
        "aspect_ratio_recommended": abs(ratio - YOUTUBE_THUMBNAIL_RECOMMENDED_RATIO) <= 0.02,
        "file_size_valid": info["file_size_bytes"] <= YOUTUBE_THUMBNAIL_MAX_BYTES,
        "thumbnail_valid": valid and info["file_size_bytes"] <= YOUTUBE_THUMBNAIL_MAX_BYTES,
    }
    if not valid:
        raise tool_error("thumbnail_validation_failed", "A thumbnail está abaixo da largura mínima configurada.", details=result)
    return result


def _safe_sas_validity_details(url: str, response_headers: dict[str, Any]) -> dict[str, Any]:
    """Classify SAS timing/permission without exposing signed query values."""
    fields = {name.casefold(): value for name, value in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
    response_time = None
    raw_date = str(response_headers.get("Date", "") or "").strip()
    if raw_date:
        try:
            response_time = parsedate_to_datetime(raw_date)
            if response_time.tzinfo is None:
                response_time = response_time.replace(tzinfo=timezone.utc)
            response_time = response_time.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            response_time = None

    def parse_sas_time(name: str):
        value = str(fields.get(name, "") or "").strip()
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    expires_at = parse_sas_time("se")
    starts_at = parse_sas_time("st")
    return {
        "azure_sas_has_read_permission": "r" in str(fields.get("sp", "") or ""),
        "azure_sas_expired_at_response": (
            response_time >= expires_at if response_time is not None and expires_at is not None else None
        ),
        "azure_sas_not_yet_valid_at_response": (
            response_time < starts_at if response_time is not None and starts_at is not None else False
        ),
    }


def _download_https_bytes(url: str, *, source_kind: str) -> tuple[bytes, dict[str, Any]]:
    """Download bounded HTTPS bytes with SSRF/redirect protections shared by all remote sources."""
    authorized_file = source_kind == "chatgpt_file"
    current = _validated_authorized_https_url(url) if authorized_file else _canonical_https_url(url)
    session = requests.Session()
    try:
        for redirect_count in range(THUMBNAIL_MAX_REDIRECTS + 1):
            _validate_public_host(current)
            try:
                response = session.get(
                    current,
                    stream=True,
                    allow_redirects=False,
                    timeout=(THUMBNAIL_DOWNLOAD_CONNECT_TIMEOUT, THUMBNAIL_DOWNLOAD_READ_TIMEOUT),
                    headers={"User-Agent": "YouTubeCreatorAgent/thumbnail-fetch"},
                )
            except requests.Timeout as exc:
                code = "thumbnail_file_resolution_failed" if source_kind == "chatgpt_file" else "thumbnail_source_unavailable"
                raise tool_error(code, "Timeout ao resolver a fonte HTTPS da thumbnail.") from exc
            except requests.RequestException as exc:
                code = "thumbnail_file_resolution_failed" if source_kind == "chatgpt_file" else "thumbnail_source_unavailable"
                raise tool_error(code, "Falha ao resolver a fonte HTTPS da thumbnail.") from exc

            if response.is_redirect or response.is_permanent_redirect:
                location = str(response.headers.get("Location", "")).strip()
                response.close()
                if not location or redirect_count >= THUMBNAIL_MAX_REDIRECTS:
                    code = "thumbnail_file_resolution_failed" if source_kind == "chatgpt_file" else "thumbnail_source_invalid"
                    raise tool_error(code, "A cadeia de redirects da fonte da thumbnail não é permitida.")
                redirected = urljoin(current, location)
                current = _validated_authorized_https_url(redirected) if authorized_file else _canonical_https_url(redirected)
                continue

            if response.status_code < 200 or response.status_code >= 300:
                status = int(response.status_code)
                response_headers = dict(response.headers)
                response.close()
                if source_kind == "chatgpt_file":
                    if status in {401, 403}:
                        raise tool_error(
                            "thumbnail_file_unauthorized",
                            "O download temporário do arquivo não está autorizado para este contexto.",
                            details={
                                "http_status": status,
                                "download_host": str(urlsplit(current).hostname or ""),
                                "content_type": str(response_headers.get("Content-Type", "") or "") or None,
                                "server": str(response_headers.get("Server", "") or "") or None,
                                "www_authenticate_present": bool(response_headers.get("WWW-Authenticate")),
                                "x_ms_error_code": str(response_headers.get("x-ms-error-code", "") or "") or None,
                                "authorized_url_has_query": bool(urlsplit(current).query),
                                "azure_sas_fields_present": {
                                    key: key in {name.casefold() for name, _ in parse_qsl(urlsplit(current).query, keep_blank_values=True)}
                                    for key in ("sv", "se", "sp", "sr", "sig", "spr", "st")
                                },
                                **_safe_sas_validity_details(current, response_headers),
                            },
                        )
                    if status in {404, 410}:
                        raise tool_error(
                            "thumbnail_file_not_found",
                            "O arquivo autorizado não existe mais ou o download temporário expirou.",
                            details={"http_status": status},
                        )
                    raise tool_error(
                        "thumbnail_file_resolution_failed",
                        "O arquivo autorizado não pôde ser resolvido para bytes.",
                        details={"http_status": status},
                    )
                raise tool_error(
                    "thumbnail_source_unavailable",
                    "A URL da thumbnail não retornou status HTTP de sucesso.",
                    details={"http_status": status},
                )

            raw_length = str(response.headers.get("Content-Length", "")).strip()
            if raw_length:
                try:
                    announced = int(raw_length)
                except ValueError:
                    announced = 0
                if announced > THUMBNAIL_MAX_SOURCE_BYTES:
                    response.close()
                    raise tool_error(
                        "thumbnail_too_large",
                        "A fonte da thumbnail excede o limite seguro antes do download.",
                        details={"source_size_bytes": announced, "max_source_bytes": THUMBNAIL_MAX_SOURCE_BYTES},
                    )

            chunks: list[bytes] = []
            total = 0
            headers = dict(response.headers)
            try:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > THUMBNAIL_MAX_SOURCE_BYTES:
                        raise tool_error(
                            "thumbnail_too_large",
                            "A fonte da thumbnail excedeu o limite seguro durante o download.",
                            details={"source_size_bytes": total, "max_source_bytes": THUMBNAIL_MAX_SOURCE_BYTES},
                        )
                    chunks.append(bytes(chunk))
            finally:
                response.close()

            return b"".join(chunks), {
                "headers": headers,
                "source_url_sha256": _sha256_text(current),
                "redirect_count": redirect_count,
                "final_url": current,
            }
    finally:
        session.close()
    code = "thumbnail_file_resolution_failed" if source_kind == "chatgpt_file" else "thumbnail_source_unavailable"
    raise tool_error(code, "Não foi possível resolver a fonte HTTPS da thumbnail.")


def _download_https_thumbnail(url: str) -> tuple[bytes, dict[str, Any]]:
    data, remote = _download_https_bytes(url, source_kind="https_url")
    final_url = str(remote["final_url"])
    source_name = PurePosixPath(urlsplit(final_url).path).name or "thumbnail"
    info = _inspect_source_image(
        data,
        source_name=source_name,
        header_content_type=dict(remote.get("headers", {})).get("Content-Type"),
    )
    return data, {**info, **{key: value for key, value in remote.items() if key != "headers"}}


def _resolve_chatgpt_file_param(thumbnail_file: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    """Resolve a ChatGPT-native file param exactly once during preview.

    ChatGPT file params provide both file_id and a short-lived authorized download_url.
    The server never dereferences file_id, sediment://, or filesystem paths directly.
    """
    file_id = str(thumbnail_file.get("file_id", "") or "").strip()
    download_url = str(thumbnail_file.get("download_url", "") or "").strip()
    content_location = str(thumbnail_file.get("content_location", "") or "").strip()

    if any(key in thumbnail_file for key in ("path", "file_path", "local_path")):
        raise tool_error("thumbnail_source_invalid", "Paths locais arbitrários não são aceitos.")

    if content_location:
        parsed = urlsplit(content_location)
        if parsed.scheme and parsed.scheme != "sediment":
            raise tool_error(
                "thumbnail_source_invalid",
                "content_location usa um scheme não permitido.",
                details={"scheme": parsed.scheme},
            )
        # sediment:// is an internal ChatGPT locator. It is accepted only as metadata;
        # the host must still provide the authorized HTTPS download_url file param.

    if not file_id:
        raise tool_error("thumbnail_source_invalid", "thumbnail_file.file_id é obrigatório para um arquivo do ChatGPT.")
    # ChatGPT file_id is an opaque host-issued identifier. Do not impose a
    # product-internal prefix or dereference it locally; authorization is
    # carried by the temporary download_url supplied by the host.
    if len(file_id) > 512 or any(ord(ch) < 32 or ord(ch) == 127 for ch in file_id):
        raise tool_error("thumbnail_source_invalid", "thumbnail_file.file_id contém valor inválido.")
    if not download_url:
        raise tool_error(
            "thumbnail_file_resolution_failed",
            "O host não forneceu download_url autorizado para este file_id. Use o arquivo como file param do ChatGPT.",
            details={"file_id_fingerprint": _safe_hash_prefix(_sha256_text(file_id))},
        )

    data, remote = _download_https_bytes(download_url, source_kind="chatgpt_file")
    file_name = _safe_source_name(
        str(thumbnail_file.get("file_name") or thumbnail_file.get("name") or ""),
        "thumbnail",
    )
    claimed_mime = str(thumbnail_file.get("mime_type", "") or "") or None
    info = _inspect_source_image(
        data,
        source_name=file_name,
        claimed_mime_type=claimed_mime,
        header_content_type=dict(remote.get("headers", {})).get("Content-Type"),
    )
    return data, {
        "type": "chatgpt_file",
        "source_type": "chatgpt_file",
        "source_id": file_id,
        "source_id_fingerprint": _safe_hash_prefix(_sha256_text(file_id)),
        "resolver": "openai_file_param_download_url",
        "source_name": file_name,
        "filename": file_name,
        "mime_type": info["mime_type"],
        "detected_mime_type": info["mime_type"],
        "width": info["width"],
        "height": info["height"],
        "file_size_bytes": len(data),
        "source_size_bytes": len(data),
        "sha256": _sha256_bytes(data),
        "source_sha256": _sha256_bytes(data),
        "download_url_sha256": remote.get("source_url_sha256"),
        "redirect_count": remote.get("redirect_count", 0),
    }


def resolve_thumbnail_source(
    *,
    data_dir: Any,
    thumbnail_url: str | None = None,
    thumbnail_file: dict[str, Any] | None = None,
    thumbnail_asset_id: str | None = None,
    thumbnail_bytes: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    sources = [
        bool(str(thumbnail_url or "").strip()),
        thumbnail_file is not None,
        bool(str(thumbnail_asset_id or "").strip()),
        bool(str(thumbnail_bytes or "").strip()),
    ]
    if sum(sources) != 1:
        raise tool_error(
            "thumbnail_source_invalid",
            "Informe exatamente uma fonte de thumbnail: thumbnail_url, thumbnail_file, thumbnail_asset_id ou thumbnail_bytes.",
            details={"source_count": sum(sources)},
        )

    if sources[0]:
        data, fetch = _download_https_thumbnail(str(thumbnail_url))
        sha = _sha256_bytes(data)
        name = str(fetch.get("source_name") or "thumbnail")
        return data, {
            "type": "https_url",
            "source_type": "https_url",
            "source_id": None,
            "resolver": "safe_https",
            "source_name": name,
            "filename": name,
            "mime_type": fetch["mime_type"],
            "detected_mime_type": fetch["mime_type"],
            "width": fetch["width"],
            "height": fetch["height"],
            "file_size_bytes": len(data),
            "source_size_bytes": len(data),
            "sha256": sha,
            "source_sha256": sha,
            "url_sha256": fetch.get("source_url_sha256"),
            "redirect_count": fetch.get("redirect_count", 0),
        }

    if sources[1]:
        if not isinstance(thumbnail_file, dict):
            raise tool_error(
                "thumbnail_source_invalid",
                "thumbnail_file deve ser um envelope de arquivo autorizado, nunca um path arbitrário.",
            )
        if str(thumbnail_file.get("file_id", "") or "").strip() or str(thumbnail_file.get("download_url", "") or "").strip():
            return _resolve_chatgpt_file_param(thumbnail_file)

        # Backward-compatible JSON envelope for non-ChatGPT MCP clients.
        if any(key in thumbnail_file for key in ("path", "file_path", "local_path")):
            raise tool_error("thumbnail_source_invalid", "Paths locais arbitrários não são aceitos.")
        source_type = str(thumbnail_file.get("source_type", "uploaded_file") or "uploaded_file").strip()
        if source_type not in _ALLOWED_FILE_SOURCE_TYPES:
            raise tool_error(
                "thumbnail_source_invalid",
                "source_type de thumbnail_file não é permitido.",
                details={"allowed_source_types": sorted(_ALLOWED_FILE_SOURCE_TYPES)},
            )
        data = _decode_base64_payload(
            str(thumbnail_file.get("content_base64", "") or ""),
            field_name="thumbnail_file.content_base64",
        )
        name = _safe_source_name(
            str(thumbnail_file.get("file_name") or thumbnail_file.get("name") or ""),
            "thumbnail",
        )
        info = _inspect_source_image(
            data,
            source_name=name,
            claimed_mime_type=str(thumbnail_file.get("mime_type", "") or "") or None,
        )
        sha = _sha256_bytes(data)
        return data, {
            "type": source_type,
            "source_type": source_type,
            "source_id": None,
            "resolver": "inline_content_base64",
            "source_name": name,
            "filename": name,
            "mime_type": info["mime_type"],
            "detected_mime_type": info["mime_type"],
            "width": info["width"],
            "height": info["height"],
            "file_size_bytes": len(data),
            "source_size_bytes": len(data),
            "sha256": sha,
            "source_sha256": sha,
        }

    if sources[2]:
        data, asset = ThumbnailAssetStore(data_dir).resolve(str(thumbnail_asset_id))
        name = _safe_source_name(asset.get("source_name"), "thumbnail")
        info = _inspect_source_image(data, source_name=name)
        sha = _sha256_bytes(data)
        source_type = str(asset.get("source_type", "internal_asset"))
        asset_id = str(asset.get("asset_id", ""))
        return data, {
            "type": source_type,
            "source_type": source_type,
            "source_id": asset_id,
            "resolver": "tenant_asset_store",
            "source_name": name,
            "filename": name,
            "asset_id": asset_id,
            "mime_type": info["mime_type"],
            "detected_mime_type": info["mime_type"],
            "width": info["width"],
            "height": info["height"],
            "file_size_bytes": len(data),
            "source_size_bytes": len(data),
            "sha256": sha,
            "source_sha256": sha,
        }

    data = _decode_base64_payload(str(thumbnail_bytes), field_name="thumbnail_bytes")
    info = _inspect_source_image(data, source_name="thumbnail")
    sha = _sha256_bytes(data)
    return data, {
        "type": "binary",
        "source_type": "binary",
        "source_id": None,
        "resolver": "inline_thumbnail_bytes",
        "source_name": "thumbnail",
        "filename": "thumbnail",
        "mime_type": info["mime_type"],
        "detected_mime_type": info["mime_type"],
        "width": info["width"],
        "height": info["height"],
        "file_size_bytes": len(data),
        "source_size_bytes": len(data),
        "sha256": sha,
        "source_sha256": sha,
    }


def _encode_png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    rgb = image.convert("RGB") if image.mode != "RGB" else image
    rgb.save(out, format="JPEG", quality=quality, optimize=True, progressive=True, subsampling=0)
    return out.getvalue()


def normalize_thumbnail_for_youtube(source_bytes: bytes, source: dict[str, Any]) -> tuple[bytes, dict[str, Any]]:
    image, decoded = _decode_image(source_bytes)
    try:
        source_width, source_height = image.size
        if source_width < YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH:
            raise tool_error(
                "thumbnail_validation_failed",
                "A thumbnail está abaixo da largura mínima configurada para vídeos.",
                details={"width": source_width, "minimum_video_width": YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH},
            )

        orientation_changed = int(decoded.get("exif_orientation", 1) or 1) != 1
        resized = False
        long_edge = max(source_width, source_height)
        if long_edge > THUMBNAIL_NORMALIZED_MAX_LONG_EDGE:
            scale = THUMBNAIL_NORMALIZED_MAX_LONG_EDGE / float(long_edge)
            target = (max(1, round(source_width * scale)), max(1, round(source_height * scale)))
            image = image.resize(target, Image.Resampling.LANCZOS)
            resized = True

        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        source_format = str(decoded["format"])
        passthrough = (
            source_format in _OUTPUT_FORMAT_TO_MIME
            and not orientation_changed
            and not resized
            and len(source_bytes) <= YOUTUBE_THUMBNAIL_MAX_BYTES
        )

        if passthrough:
            normalized_bytes = source_bytes
            output_format = source_format
            compressed = False
        else:
            output_format = "PNG" if has_alpha else "JPEG"
            if output_format == "PNG":
                normalized_bytes = _encode_png(image)
                compressed = len(normalized_bytes) < len(source_bytes)
                while len(normalized_bytes) > YOUTUBE_THUMBNAIL_MAX_BYTES and max(image.size) > YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH:
                    new_size = (max(1, int(image.width * 0.9)), max(1, int(image.height * 0.9)))
                    image = image.resize(new_size, Image.Resampling.LANCZOS)
                    resized = True
                    normalized_bytes = _encode_png(image)
                    compressed = True
            else:
                normalized_bytes = b""
                used_quality = 92
                for quality in (92, 88, 82, 76, 68):
                    used_quality = quality
                    normalized_bytes = _encode_jpeg(image, quality)
                    if len(normalized_bytes) <= YOUTUBE_THUMBNAIL_MAX_BYTES:
                        break
                while len(normalized_bytes) > YOUTUBE_THUMBNAIL_MAX_BYTES and max(image.size) > YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH:
                    new_size = (max(1, int(image.width * 0.9)), max(1, int(image.height * 0.9)))
                    image = image.resize(new_size, Image.Resampling.LANCZOS)
                    resized = True
                    normalized_bytes = _encode_jpeg(image, used_quality)
                compressed = len(normalized_bytes) < len(source_bytes) or used_quality < 92

        final_image, final_info = _decode_image(normalized_bytes)
        final_image.close()
        final_mime = _OUTPUT_FORMAT_TO_MIME.get(str(final_info["format"]))
        if final_mime not in YOUTUBE_THUMBNAIL_LIMITS["accepted_output_mime_types"]:
            raise tool_error("thumbnail_normalization_failed", "A normalização não gerou JPEG/PNG aceito pelo YouTube.")
        if len(normalized_bytes) > YOUTUBE_THUMBNAIL_MAX_BYTES:
            raise tool_error(
                "thumbnail_normalization_failed",
                "Não foi possível normalizar a thumbnail abaixo do limite oficial de 50 MB sem crop.",
                details={"file_size_bytes": len(normalized_bytes), "max_upload_bytes": YOUTUBE_THUMBNAIL_MAX_BYTES},
            )
        if int(final_info["width"]) < YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH:
            raise tool_error(
                "thumbnail_normalization_failed",
                "A normalização reduziria a thumbnail abaixo da largura mínima configurada.",
            )

        ratio = int(final_info["width"]) / int(final_info["height"])
        normalized_sha = _sha256_bytes(normalized_bytes)
        return normalized_bytes, {
            "mime_type": final_mime,
            "width": int(final_info["width"]),
            "height": int(final_info["height"]),
            "file_size_bytes": len(normalized_bytes),
            "sha256": normalized_sha,
            "converted": str(decoded["mime_type"]) != final_mime,
            "resized": bool(resized),
            "compressed": bool(compressed),
            "orientation_normalized": bool(orientation_changed),
            "aspect_ratio": round(ratio, 6),
            "recommended_aspect_ratio": "16:9",
            "aspect_ratio_recommended": abs(ratio - YOUTUBE_THUMBNAIL_RECOMMENDED_RATIO) <= 0.02,
            "minimum_video_width": YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH,
            "max_upload_bytes": YOUTUBE_THUMBNAIL_MAX_BYTES,
            "thumbnail_valid": True,
        }
    except Exception:
        raise
    finally:
        try:
            image.close()
        except Exception:
            pass


class ThumbnailUpdateMixin:
    """Multi-source, staged, single-write YouTube custom-thumbnail workflow.\n\n    Production verification marker: opaque ChatGPT file-id resolver v4.\n    """

    def _thumbnail_snapshot(self, video_id: str) -> dict[str, Any]:
        item = self._owned_video_item(video_id, part="snippet,status")
        snippet = dict(item.get("snippet", {}) or {})
        status = dict(item.get("status", {}) or {})
        thumbnails = dict(snippet.get("thumbnails", {}) or {})
        return {
            "video_id": str(item.get("id", video_id)),
            "channel_id": str(snippet.get("channelId", "")),
            "etag": str(item.get("etag", "") or ""),
            "upload_status": str(status.get("uploadStatus", "") or ""),
            "privacy_status": str(status.get("privacyStatus", "") or ""),
            "thumbnails": thumbnails,
            "thumbnail_urls": _thumbnail_urls(thumbnails),
            "thumbnail_fingerprint": _thumbnail_map_fingerprint(thumbnails),
        }

    @staticmethod
    def _assert_thumbnail_editable(snapshot: dict[str, Any]) -> None:
        upload_status = str(snapshot.get("upload_status", "")).strip().casefold()
        if upload_status != "processed":
            raise tool_error(
                "thumbnail_write_failed",
                "A thumbnail só pode ser alterada quando o vídeo está completamente processado.",
                details={"upload_status": upload_status or None},
            )

    def preview_video_thumbnail_update(
        self,
        *,
        video_id: str,
        thumbnail_url: str | None = None,
        thumbnail_file: dict[str, Any] | None = None,
        thumbnail_asset_id: str | None = None,
        thumbnail_bytes: str | None = None,
    ) -> dict[str, Any]:
        self.context.validate_youtube()
        video_id = str(video_id or "").strip()
        if not video_id:
            raise tool_error("invalid_request", "video_id é obrigatório.")
        self.memory.assert_not_recently_edited(video_id)
        baseline = self._thumbnail_snapshot(video_id)
        self._assert_thumbnail_editable(baseline)

        source_started = time.monotonic()
        source_bytes, source = resolve_thumbnail_source(
            data_dir=self.context.data_dir,
            thumbnail_url=thumbnail_url,
            thumbnail_file=thumbnail_file,
            thumbnail_asset_id=thumbnail_asset_id,
            thumbnail_bytes=thumbnail_bytes,
        )
        normalized_bytes, normalized = normalize_thumbnail_for_youtube(source_bytes, source)
        source_elapsed_ms = int((time.monotonic() - source_started) * 1000)
        staging = ThumbnailStagingStore(self.context.data_dir, ttl_seconds=THUMBNAIL_APPROVAL_TTL_SECONDS).create(
            video_id=video_id,
            data=normalized_bytes,
            sha256=str(normalized["sha256"]),
            mime_type=str(normalized["mime_type"]),
            width=int(normalized["width"]),
            height=int(normalized["height"]),
            source_type=str(source["type"]),
            source_sha256=str(source["sha256"]),
            source_size_bytes=int(source["file_size_bytes"]),
        )

        baseline_digest = signer_from_env().payload_digest(baseline)
        proposed = {
            "video_id": video_id,
            "source_type": str(source["type"]),
            "source_sha256": str(source["sha256"]),
            "source_size_bytes": int(source["file_size_bytes"]),
            "normalized_sha256": str(normalized["sha256"]),
            "image_sha256": str(normalized["sha256"]),
            "mime_type": str(normalized["mime_type"]),
            "normalized_mime_type": str(normalized["mime_type"]),
            "file_size_bytes": int(normalized["file_size_bytes"]),
            "normalized_size": int(normalized["file_size_bytes"]),
            "width": int(normalized["width"]),
            "height": int(normalized["height"]),
            "staging_id": str(staging["staging_id"]),
            "source": {
                "kind": str(source["type"]),
                "source_sha256": str(source["sha256"]),
            },
        }
        approval_payload = {
            "baseline_digest": baseline_digest,
            "baseline": baseline,
            "proposed": proposed,
        }
        token = signer_from_env().issue("update_video_thumbnail", video_id, approval_payload)

        _log_thumbnail_event(
            "thumbnail_preview_staged",
            video_id=video_id,
            source_type=source["type"],
            source_size=source["file_size_bytes"],
            source_sha256=_safe_hash_prefix(source["sha256"]),
            normalized_size=normalized["file_size_bytes"],
            normalized_sha256=_safe_hash_prefix(normalized["sha256"]),
            converted=normalized["converted"],
            resized=normalized["resized"],
            compressed=normalized["compressed"],
            staging_id_fingerprint=_safe_hash_prefix(_sha256_text(str(staging["staging_id"]))),
            resolver=source.get("resolver"),
            source_id_fingerprint=source.get("source_id_fingerprint"),
            detected_mime=source.get("detected_mime_type") or source.get("mime_type"),
            source_elapsed_ms=source_elapsed_ms,
        )
        return {
            "ok": True,
            "video_id": video_id,
            "current": baseline,
            "source": source,
            "normalized": normalized,
            "proposed": proposed,
            "validation": normalized,
            "thumbnail_valid": True,
            "staging_id": staging["staging_id"],
            "staging_expires_at": staging["expires_at"],
            "baseline_digest": baseline_digest,
            "approval_payload": approval_payload,
            "approval_token": token,
            "expires_in_seconds": THUMBNAIL_APPROVAL_TTL_SECONDS,
            "requires_explicit_user_confirmation": True,
            "rollback_supported": False,
            "recent_edit_protection": self.video_memory_state(video_id),
        }

    def _thumbnail_persistence_signal(
        self,
        *,
        baseline: dict[str, Any],
        current: dict[str, Any],
        set_response: dict[str, Any],
    ) -> dict[str, Any]:
        response_thumbnails = dict(set_response or {})
        if "items" in response_thumbnails:
            response_thumbnails = dict((response_thumbnails.get("items") or [{}])[0] or {})
        response_urls = _thumbnail_urls(response_thumbnails)
        current_urls = list(current.get("thumbnail_urls", []) or [])
        baseline_urls = list(baseline.get("thumbnail_urls", []) or [])
        changed_fingerprint = current.get("thumbnail_fingerprint") != baseline.get("thumbnail_fingerprint")
        changed_etag = bool(current.get("etag")) and current.get("etag") != baseline.get("etag")
        response_visible = bool(set(response_urls) & set(current_urls)) if response_urls else False
        changed_urls = current_urls != baseline_urls
        return {
            "provider_acknowledged": bool(response_thumbnails),
            "video_etag_changed": changed_etag,
            "thumbnail_fingerprint_changed": changed_fingerprint,
            "thumbnail_urls_changed": changed_urls,
            "provider_response_visible_in_readback": response_visible,
            "verified": bool(response_thumbnails) and (changed_fingerprint or changed_etag or response_visible),
        }

    def apply_video_thumbnail_update(self, *, approval_payload: dict[str, Any], approval_token: str) -> dict[str, Any]:
        self.context.validate_youtube()
        proposed = dict(approval_payload.get("proposed", {}) or {})
        video_id = str(proposed.get("video_id", "")).strip()
        if not video_id:
            raise tool_error("approval_invalid", "video_id ausente no payload aprovado.")

        self.memory.assert_not_recently_edited(video_id)
        signer_from_env().verify(
            approval_token,
            action="update_video_thumbnail",
            subject=video_id,
            payload=approval_payload,
        )

        baseline = dict(approval_payload.get("baseline", {}) or {})
        expected_baseline_digest = str(approval_payload.get("baseline_digest", ""))
        if not baseline or signer_from_env().payload_digest(baseline) != expected_baseline_digest:
            raise tool_error("approval_invalid", "O baseline aprovado da thumbnail é inválido.")

        current_before = self._thumbnail_snapshot(video_id)
        self._assert_thumbnail_editable(current_before)
        if signer_from_env().payload_digest(current_before) != expected_baseline_digest:
            raise tool_error(
                "baseline_changed",
                "O vídeo ou sua thumbnail mudou após o preview. Gere uma nova prévia antes de aplicar.",
            )

        staging_id = str(proposed.get("staging_id", "") or "").strip()
        expected_sha = str(proposed.get("normalized_sha256") or proposed.get("image_sha256") or "").strip()
        if not staging_id or not expected_sha:
            raise tool_error("approval_invalid", "O approval não contém staging/hash normalizado válido.")
        store = ThumbnailStagingStore(self.context.data_dir, ttl_seconds=THUMBNAIL_APPROVAL_TTL_SECONDS)
        image_bytes, staging = store.load(
            staging_id=staging_id,
            video_id=video_id,
            expected_sha256=expected_sha,
        )
        comparisons = {
            "source_type": str(staging.get("source_type")) == str(proposed.get("source_type")),
            "source_sha256": str(staging.get("source_sha256")) == str(proposed.get("source_sha256")),
            "source_size_bytes": int(staging.get("source_size_bytes", -1)) == int(proposed.get("source_size_bytes", -2)),
            "normalized_sha256": _sha256_bytes(image_bytes) == expected_sha,
            "mime_type": str(staging.get("mime_type")) == str(proposed.get("normalized_mime_type") or proposed.get("mime_type")),
            "file_size_bytes": int(staging.get("file_size_bytes", -1)) == int(proposed.get("normalized_size") or proposed.get("file_size_bytes") or -2),
            "width": int(staging.get("width", -1)) == int(proposed.get("width", -2)),
            "height": int(staging.get("height", -1)) == int(proposed.get("height", -2)),
        }
        if not all(comparisons.values()):
            raise tool_error(
                "thumbnail_hash_mismatch",
                "O staging não corresponde exatamente à thumbnail normalizada aprovada.",
                details={"comparisons": comparisons},
            )

        media = MediaIoBaseUpload(
            io.BytesIO(image_bytes),
            mimetype=str(staging["mime_type"]),
            chunksize=-1,
            resumable=False,
        )
        started = time.monotonic()
        try:
            response = self._youtube().thumbnails().set(
                videoId=video_id,
                media_body=media,
            ).execute()
        except Exception as exc:
            raise tool_error(
                "thumbnail_write_failed",
                "O YouTube rejeitou ou não concluiu thumbnails.set. Nenhum retry foi executado.",
                details={"provider_error_type": type(exc).__name__},
            ) from exc

        # The remote write has returned: the staged bytes are now one-use regardless
        # of later readback convergence. MCP approval replay protection is preserved too.
        store.mark_consumed(staging_id)

        response_thumbnails = dict((response or {}).get("items", [{}])[0] or {}) if isinstance(response, dict) else {}
        observed = current_before
        signal: dict[str, Any] = {}
        attempts = 0
        for attempts, delay in enumerate(THUMBNAIL_VERIFY_DELAYS, start=1):
            if delay:
                time.sleep(delay)
            observed = self._thumbnail_snapshot(video_id)
            signal = self._thumbnail_persistence_signal(
                baseline=current_before,
                current=observed,
                set_response=response_thumbnails,
            )
            if signal["verified"]:
                break

        elapsed_ms = int((time.monotonic() - started) * 1000)
        if not signal.get("verified"):
            self.memory.record_video_action(
                video_id=video_id,
                action_type="thumbnail_update_uncertain",
                surface="thumbnail_update",
                changed_fields=["thumbnail"],
                before=current_before,
                after=observed,
                details={
                    "tenant_id": self.context.tenant_id,
                    "normalized_sha256": expected_sha,
                    "verification_attempts": attempts,
                    "elapsed_ms": elapsed_ms,
                },
            )
            _log_thumbnail_event(
                "thumbnail_apply_unverified",
                video_id=video_id,
                source_type=proposed.get("source_type"),
                normalized_sha256=_safe_hash_prefix(expected_sha),
                staging_id_fingerprint=_safe_hash_prefix(_sha256_text(staging_id)),
                verification_attempts=attempts,
                elapsed_ms=elapsed_ms,
            )
            raise tool_error(
                "thumbnail_verification_failed",
                "thumbnails.set retornou, mas o readback oficial não confirmou a mudança dentro da janela limitada. Nenhum retry foi executado.",
                details={
                    "state": "thumbnail_verification_failed",
                    "verification_attempts": attempts,
                    "elapsed_ms": elapsed_ms,
                    "verification": signal,
                    "current": observed,
                },
            )

        self.memory.record_video_action(
            video_id=video_id,
            action_type="thumbnail_update",
            surface="thumbnail_update",
            changed_fields=["thumbnail"],
            before=current_before,
            after=observed,
            details={
                "tenant_id": self.context.tenant_id,
                "source_type": proposed.get("source_type"),
                "source_sha256": proposed.get("source_sha256"),
                "normalized_sha256": expected_sha,
                "mime_type": staging["mime_type"],
                "file_size_bytes": staging["file_size_bytes"],
                "width": staging["width"],
                "height": staging["height"],
                "verification_attempts": attempts,
                "elapsed_ms": elapsed_ms,
            },
        )
        _log_thumbnail_event(
            "thumbnail_apply_verified",
            video_id=video_id,
            source_type=proposed.get("source_type"),
            source_size=proposed.get("source_size_bytes"),
            source_sha256=_safe_hash_prefix(str(proposed.get("source_sha256", ""))),
            normalized_size=staging["file_size_bytes"],
            normalized_sha256=_safe_hash_prefix(expected_sha),
            staging_id_fingerprint=_safe_hash_prefix(_sha256_text(staging_id)),
            verification_attempts=attempts,
            elapsed_ms=elapsed_ms,
        )
        return {
            "ok": True,
            "state": "success_verified",
            "video_id": video_id,
            "persisted_verified": True,
            "verification_attempts": attempts,
            "elapsed_ms": elapsed_ms,
            "thumbnail": {
                "source_type": proposed.get("source_type"),
                "source_sha256": proposed.get("source_sha256"),
                "normalized_sha256": expected_sha,
                "image_sha256": expected_sha,
                "mime_type": staging["mime_type"],
                "width": staging["width"],
                "height": staging["height"],
                "file_size_bytes": staging["file_size_bytes"],
                "readback": observed.get("thumbnails", {}),
                "verification": signal,
            },
            "rollback_supported": False,
            "recent_edit_protection": self.video_memory_state(video_id),
        }
