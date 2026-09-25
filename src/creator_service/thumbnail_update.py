from __future__ import annotations

import hashlib
import io
import ipaddress
import socket
import time
import warnings
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image, UnidentifiedImageError

from .mcp_errors import CreatorToolError, tool_error
from .security import signer_from_env


YOUTUBE_THUMBNAIL_MAX_BYTES = 50 * 1024 * 1024
YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH = 640
YOUTUBE_THUMBNAIL_RECOMMENDED_WIDTH = 3840
YOUTUBE_THUMBNAIL_RECOMMENDED_HEIGHT = 2160
YOUTUBE_THUMBNAIL_RECOMMENDED_RATIO = 16 / 9
THUMBNAIL_MAX_PIXELS = 100_000_000
THUMBNAIL_DOWNLOAD_CONNECT_TIMEOUT = 5
THUMBNAIL_DOWNLOAD_READ_TIMEOUT = 10
THUMBNAIL_MAX_REDIRECTS = 3
THUMBNAIL_VERIFY_DELAYS = (0.0, 1.0, 2.0, 4.0)

_ALLOWED_ACTUAL_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
}
_ALLOWED_HEADER_MIME = {
    "image/jpeg",
    "image/png",
    "application/octet-stream",
}
_EXTENSION_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_https_url(raw: str) -> str:
    value = str(raw or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise tool_error("thumbnail_validation_failed", "A URL da thumbnail é inválida.") from exc
    if parsed.scheme.lower() != "https":
        raise tool_error("thumbnail_validation_failed", "A fonte da thumbnail deve usar HTTPS.")
    if parsed.username or parsed.password:
        raise tool_error("thumbnail_validation_failed", "Credenciais embutidas na URL da thumbnail não são permitidas.")
    host = str(parsed.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise tool_error("thumbnail_validation_failed", "A URL da thumbnail não possui host válido.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise tool_error("thumbnail_validation_failed", "A porta da URL da thumbnail é inválida.") from exc
    if port not in (None, 443):
        raise tool_error("thumbnail_validation_failed", "Somente HTTPS na porta padrão é permitido para thumbnails remotas.")
    netloc = host if port is None else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit(("https", netloc, path, parsed.query, ""))


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
        raise tool_error("thumbnail_validation_failed", "Não foi possível resolver o host HTTPS da thumbnail.") from exc
    addresses = {str(info[4][0]) for info in infos if info and info[4]}
    if not addresses or any(not _is_public_ip(address) for address in addresses):
        raise tool_error(
            "thumbnail_validation_failed",
            "A URL da thumbnail resolve para uma rede privada, local ou não permitida.",
        )


def _url_extension(url: str) -> str:
    return PurePosixPath(urlsplit(url).path).suffix.casefold()


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


def _inspect_image(data: bytes, *, source_url: str, header_content_type: str | None) -> dict[str, Any]:
    if not data:
        raise tool_error("thumbnail_validation_failed", "A imagem da thumbnail está vazia.")
    if len(data) > YOUTUBE_THUMBNAIL_MAX_BYTES:
        raise tool_error(
            "thumbnail_validation_failed",
            "A thumbnail excede o limite oficial de upload da API do YouTube.",
            details={"file_size_bytes": len(data), "file_size_limit": YOUTUBE_THUMBNAIL_MAX_BYTES},
        )

    header_mime = str(header_content_type or "").split(";", 1)[0].strip().casefold()
    if header_mime and header_mime not in _ALLOWED_HEADER_MIME:
        raise tool_error(
            "thumbnail_validation_failed",
            "O Content-Type remoto não é compatível com os formatos aceitos para thumbnail.",
            details={"content_type": header_mime},
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            width, height = image.size
            image_format = str(image.format or "").upper()
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise tool_error("thumbnail_validation_failed", "A imagem está corrompida, insegura ou não pôde ser validada.") from exc

    mime_type = _ALLOWED_ACTUAL_MIME.get(image_format)
    if not mime_type:
        raise tool_error(
            "thumbnail_validation_failed",
            "O formato real da imagem não é suportado por este fluxo seguro. Use JPEG ou PNG.",
            details={"detected_format": image_format or None},
        )

    if width <= 0 or height <= 0 or width * height > THUMBNAIL_MAX_PIXELS:
        raise tool_error(
            "thumbnail_validation_failed",
            "As dimensões da thumbnail são inválidas ou excessivas.",
            details={"width": width, "height": height, "max_pixels": THUMBNAIL_MAX_PIXELS},
        )

    extension = _url_extension(source_url)
    extension_supported = extension in _EXTENSION_TO_MIME if extension else True
    extension_consistent = not extension or (_EXTENSION_TO_MIME.get(extension) == mime_type)
    if not extension_supported or not extension_consistent:
        raise tool_error(
            "thumbnail_validation_failed",
            "A extensão explícita da URL não corresponde ao formato real JPEG/PNG.",
            details={
                "extension": extension or None,
                "detected_mime_type": mime_type,
                "extension_supported": extension_supported,
                "extension_consistent": extension_consistent,
            },
        )

    dimensions_valid = width >= YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH
    aspect_ratio = width / height
    ratio_delta = abs(aspect_ratio - YOUTUBE_THUMBNAIL_RECOMMENDED_RATIO)
    aspect_ratio_recommended = ratio_delta <= 0.02
    validation = {
        "mime_type": mime_type,
        "file_size_bytes": len(data),
        "file_size_limit": YOUTUBE_THUMBNAIL_MAX_BYTES,
        "width": width,
        "height": height,
        "aspect_ratio": round(aspect_ratio, 6),
        "recommended_aspect_ratio": "16:9",
        "recommended_resolution": {
            "width": YOUTUBE_THUMBNAIL_RECOMMENDED_WIDTH,
            "height": YOUTUBE_THUMBNAIL_RECOMMENDED_HEIGHT,
        },
        "minimum_video_width": YOUTUBE_THUMBNAIL_MIN_VIDEO_WIDTH,
        "format_supported": True,
        "extension_supported": extension_supported,
        "extension_consistent": extension_consistent,
        "dimensions_valid": dimensions_valid,
        "aspect_ratio_recommended": aspect_ratio_recommended,
        "file_size_valid": True,
        "thumbnail_valid": dimensions_valid,
    }
    if not dimensions_valid:
        raise tool_error(
            "thumbnail_validation_failed",
            "A thumbnail está abaixo da largura mínima recomendada pelo YouTube para vídeos.",
            details=validation,
        )
    return validation


def _download_https_thumbnail(url: str) -> tuple[bytes, dict[str, Any]]:
    current = _canonical_https_url(url)
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
                raise tool_error("thumbnail_validation_failed", "Timeout ao baixar a thumbnail HTTPS.") from exc
            except requests.RequestException as exc:
                raise tool_error("thumbnail_validation_failed", "Falha ao baixar a thumbnail HTTPS.") from exc

            if response.is_redirect or response.is_permanent_redirect:
                location = str(response.headers.get("Location", "")).strip()
                response.close()
                if not location or redirect_count >= THUMBNAIL_MAX_REDIRECTS:
                    raise tool_error("thumbnail_validation_failed", "A cadeia de redirects da thumbnail não é permitida.")
                current = _canonical_https_url(urljoin(current, location))
                continue

            if response.status_code < 200 or response.status_code >= 300:
                status = response.status_code
                response.close()
                raise tool_error(
                    "thumbnail_validation_failed",
                    "A URL da thumbnail não retornou uma imagem com status HTTP de sucesso.",
                    details={"http_status": status},
                )

            raw_length = str(response.headers.get("Content-Length", "")).strip()
            if raw_length:
                try:
                    announced = int(raw_length)
                except ValueError:
                    announced = 0
                if announced > YOUTUBE_THUMBNAIL_MAX_BYTES:
                    response.close()
                    raise tool_error(
                        "thumbnail_validation_failed",
                        "A thumbnail remota excede o limite oficial antes do download.",
                        details={"file_size_bytes": announced, "file_size_limit": YOUTUBE_THUMBNAIL_MAX_BYTES},
                    )

            chunks: list[bytes] = []
            total = 0
            try:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > YOUTUBE_THUMBNAIL_MAX_BYTES:
                        raise tool_error(
                            "thumbnail_validation_failed",
                            "A thumbnail excedeu o limite durante o download em streaming.",
                            details={"file_size_bytes": total, "file_size_limit": YOUTUBE_THUMBNAIL_MAX_BYTES},
                        )
                    chunks.append(bytes(chunk))
            finally:
                response.close()

            data = b"".join(chunks)
            validation = _inspect_image(
                data,
                source_url=current,
                header_content_type=response.headers.get("Content-Type"),
            )
            validation["source_url_sha256"] = _sha256_text(current)
            validation["redirect_count"] = redirect_count
            validation["final_url"] = current
            return data, validation
    finally:
        session.close()
    raise tool_error("thumbnail_validation_failed", "Não foi possível obter a thumbnail HTTPS.")


class ThumbnailUpdateMixin:
    """High-assurance, single-write YouTube custom-thumbnail workflow."""

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
                "A thumbnail só pode ser alterada por este fluxo quando o vídeo está completamente processado.",
                details={"upload_status": upload_status or None},
            )

    def preview_video_thumbnail_update(self, *, video_id: str, thumbnail_url: str) -> dict[str, Any]:
        self.context.validate_youtube()
        video_id = str(video_id or "").strip()
        if not video_id:
            raise tool_error("invalid_request", "video_id é obrigatório.")
        self.memory.assert_not_recently_edited(video_id)
        baseline = self._thumbnail_snapshot(video_id)
        self._assert_thumbnail_editable(baseline)

        image_bytes, validation = _download_https_thumbnail(thumbnail_url)
        image_sha256 = _sha256_bytes(image_bytes)
        source_url = str(validation["final_url"])
        proposed = {
            "video_id": video_id,
            "image_sha256": image_sha256,
            "mime_type": validation["mime_type"],
            "file_size_bytes": validation["file_size_bytes"],
            "width": validation["width"],
            "height": validation["height"],
            "source": {
                "kind": "https_url",
                "url": source_url,
                "url_sha256": _sha256_text(source_url),
            },
        }
        baseline_digest = signer_from_env().payload_digest(baseline)
        approval_payload = {
            "baseline_digest": baseline_digest,
            "baseline": baseline,
            "proposed": proposed,
        }
        token = signer_from_env().issue("update_video_thumbnail", video_id, approval_payload)
        return {
            "ok": True,
            "video_id": video_id,
            "current": baseline,
            "proposed": proposed,
            "validation": validation,
            "baseline_digest": baseline_digest,
            "approval_payload": approval_payload,
            "approval_token": token,
            "expires_in_seconds": 900,
            "requires_explicit_user_confirmation": True,
            "rollback_supported": False,
            "recent_edit_protection": self.video_memory_state(video_id),
        }

    @staticmethod
    def _approved_source(proposed: dict[str, Any]) -> str:
        source = dict(proposed.get("source", {}) or {})
        if source.get("kind") != "https_url":
            raise tool_error("approval_invalid", "A fonte aprovada da thumbnail não é suportada.")
        url = _canonical_https_url(str(source.get("url", "")))
        if _sha256_text(url) != str(source.get("url_sha256", "")):
            raise tool_error("payload_mismatch", "A origem HTTPS da thumbnail foi alterada após a aprovação.")
        return url

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

        source_url = self._approved_source(proposed)
        image_bytes, validation = _download_https_thumbnail(source_url)
        actual_sha256 = _sha256_bytes(image_bytes)
        comparisons = {
            "image_sha256": actual_sha256 == str(proposed.get("image_sha256", "")),
            "mime_type": validation["mime_type"] == proposed.get("mime_type"),
            "file_size_bytes": validation["file_size_bytes"] == proposed.get("file_size_bytes"),
            "width": validation["width"] == proposed.get("width"),
            "height": validation["height"] == proposed.get("height"),
        }
        if not all(comparisons.values()):
            raise tool_error(
                "payload_mismatch",
                "A imagem HTTPS mudou depois do preview; nenhuma escrita foi enviada.",
                details={"comparisons": comparisons},
            )

        media = MediaIoBaseUpload(
            io.BytesIO(image_bytes),
            mimetype=str(validation["mime_type"]),
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
                    "verification_attempts": attempts,
                    "elapsed_ms": elapsed_ms,
                },
            )
            raise tool_error(
                "thumbnail_verification_failed",
                "thumbnails.set retornou, mas o readback oficial não confirmou mudança da thumbnail dentro da janela limitada. Nenhum retry foi executado.",
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
                "image_sha256": actual_sha256,
                "mime_type": validation["mime_type"],
                "file_size_bytes": validation["file_size_bytes"],
                "width": validation["width"],
                "height": validation["height"],
                "verification_attempts": attempts,
                "elapsed_ms": elapsed_ms,
            },
        )
        return {
            "ok": True,
            "state": "success_verified",
            "video_id": video_id,
            "persisted_verified": True,
            "verification_attempts": attempts,
            "elapsed_ms": elapsed_ms,
            "thumbnail": {
                "image_sha256": actual_sha256,
                "mime_type": validation["mime_type"],
                "width": validation["width"],
                "height": validation["height"],
                "file_size_bytes": validation["file_size_bytes"],
                "readback": observed.get("thumbnails", {}),
                "verification": signal,
            },
            "rollback_supported": False,
            "recent_edit_protection": self.video_memory_state(video_id),
        }
