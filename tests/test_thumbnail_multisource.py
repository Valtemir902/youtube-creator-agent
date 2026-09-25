from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from creator_service.mcp_errors import CreatorToolError
from creator_service.thumbnail_staging import ThumbnailAssetStore, ThumbnailStagingStore
import creator_service.thumbnail_update as thumbnail_module
from creator_service.thumbnail_update import (
    YOUTUBE_THUMBNAIL_MAX_BYTES,
    normalize_thumbnail_for_youtube,
    resolve_thumbnail_source,
)


def _image_bytes(fmt: str = "PNG", size: tuple[int, int] = (1672, 941), *, alpha: bool = False) -> bytes:
    stream = io.BytesIO()
    mode = "RGBA" if alpha or fmt == "PNG" else "RGB"
    image = Image.new(mode, size, (10, 20, 30, 180) if mode == "RGBA" else (10, 20, 30))
    image.save(stream, format=fmt)
    return stream.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _code(exc, expected: str):
    assert isinstance(exc.value, CreatorToolError)
    assert exc.value.code == expected
    return exc.value


def test_chatgpt_generated_png_1672x941_requires_no_public_url(tmp_path: Path):
    source_bytes = _image_bytes("PNG", (1672, 941))
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "name": "generated-thumbnail.png",
            "mime_type": "image/png",
            "source_type": "generated_file",
            "content_base64": _b64(source_bytes),
        },
    )
    normalized_bytes, normalized = normalize_thumbnail_for_youtube(resolved, source)

    assert resolved == source_bytes
    assert source["type"] == "generated_file"
    assert source["width"] == 1672
    assert source["height"] == 941
    assert source["sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert normalized["width"] == 1672
    assert normalized["height"] == 941
    assert normalized["thumbnail_valid"] is True
    assert normalized["sha256"] == hashlib.sha256(normalized_bytes).hexdigest()
    assert normalized["mime_type"] == "image/png"


def test_uploaded_file_is_accepted_without_filesystem_path(tmp_path: Path):
    data = _image_bytes("JPEG", (1280, 720))
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "name": "upload.jpg",
            "mime_type": "image/jpeg",
            "source_type": "uploaded_file",
            "content_base64": _b64(data),
        },
    )
    assert resolved == data
    assert source["type"] == "uploaded_file"


@pytest.mark.parametrize("key", ["path", "file_path", "local_path"])
def test_arbitrary_local_paths_are_rejected(tmp_path: Path, key: str):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_file={
                key: "/etc/passwd",
                "name": "thumb.png",
                "source_type": "generated_file",
                "content_base64": _b64(_image_bytes("PNG")),
            },
        )
    _code(caught, "thumbnail_source_invalid")


def test_zero_sources_is_rejected(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(data_dir=tmp_path)
    _code(caught, "thumbnail_source_invalid")


def test_multiple_sources_are_rejected(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_url="https://example.com/thumb.jpg",
            thumbnail_bytes=_b64(_image_bytes("JPEG")),
        )
    _code(caught, "thumbnail_source_invalid")


def test_binary_source_is_supported(tmp_path: Path):
    data = _image_bytes("JPEG")
    resolved, source = resolve_thumbnail_source(data_dir=tmp_path, thumbnail_bytes=_b64(data))
    assert resolved == data
    assert source["type"] == "binary"
    assert source["mime_type"] == "image/jpeg"


def test_false_declared_mime_is_rejected(tmp_path: Path):
    data = _image_bytes("PNG")
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_file={
                "name": "thumb.png",
                "mime_type": "image/jpeg",
                "source_type": "generated_file",
                "content_base64": _b64(data),
            },
        )
    _code(caught, "thumbnail_validation_failed")


def test_non_image_is_rejected(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(data_dir=tmp_path, thumbnail_bytes=_b64(b"this is not an image"))
    _code(caught, "thumbnail_decode_failed")


def test_webp_is_converted_to_youtube_output(tmp_path: Path):
    data = _image_bytes("WEBP", (1280, 720))
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "name": "thumb.webp",
            "mime_type": "image/webp",
            "source_type": "generated_file",
            "content_base64": _b64(data),
        },
    )
    normalized_bytes, normalized = normalize_thumbnail_for_youtube(resolved, source)
    assert normalized["converted"] is True
    assert normalized["mime_type"] in {"image/jpeg", "image/png"}
    assert len(normalized_bytes) <= YOUTUBE_THUMBNAIL_MAX_BYTES


def test_large_dimensions_resize_proportionally_without_crop(tmp_path: Path):
    data = _image_bytes("JPEG", (7680, 4320))
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "name": "large.jpg",
            "mime_type": "image/jpeg",
            "source_type": "generated_file",
            "content_base64": _b64(data),
        },
    )
    _, normalized = normalize_thumbnail_for_youtube(resolved, source)
    assert normalized["resized"] is True
    assert normalized["width"] == 3840
    assert normalized["height"] == 2160
    assert abs((normalized["width"] / normalized["height"]) - (7680 / 4320)) < 1e-9


def test_alpha_png_stays_png_when_normalization_is_needed(tmp_path: Path):
    data = _image_bytes("WEBP", (4200, 2363), alpha=True)
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "name": "alpha.webp",
            "mime_type": "image/webp",
            "source_type": "generated_file",
            "content_base64": _b64(data),
        },
    )
    _, normalized = normalize_thumbnail_for_youtube(resolved, source)
    assert normalized["mime_type"] == "image/png"


def test_internal_asset_must_exist_in_authorized_tenant_store(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(data_dir=tmp_path, thumbnail_asset_id="asset_1234567890123456")
    _code(caught, "thumbnail_asset_not_found")


def test_resolvable_internal_asset_is_hash_verified(tmp_path: Path):
    store = ThumbnailAssetStore(tmp_path)
    asset_id = "asset_1234567890123456"
    data = _image_bytes("PNG")
    (store.root / f"{asset_id}.bin").write_bytes(data)
    (store.root / f"{asset_id}.json").write_text(json.dumps({
        "sha256": hashlib.sha256(data).hexdigest(),
        "source_type": "internal_asset",
        "source_name": "asset.png",
    }), encoding="utf-8")

    resolved, source = resolve_thumbnail_source(data_dir=tmp_path, thumbnail_asset_id=asset_id)
    assert resolved == data
    assert source["type"] == "internal_asset"


def test_staging_preserves_exact_bytes_and_hash(tmp_path: Path):
    data = _image_bytes("JPEG", (1280, 720))
    sha = hashlib.sha256(data).hexdigest()
    store = ThumbnailStagingStore(tmp_path, ttl_seconds=900)
    staged = store.create(
        video_id="video-1",
        data=data,
        sha256=sha,
        mime_type="image/jpeg",
        width=1280,
        height=720,
        source_type="generated_file",
        source_sha256=sha,
        source_size_bytes=len(data),
        now=1000,
    )
    loaded, metadata = store.load(
        staging_id=staged["staging_id"],
        video_id="video-1",
        expected_sha256=sha,
        now=1001,
    )
    assert loaded == data
    assert hashlib.sha256(loaded).hexdigest() == sha
    assert metadata["sha256"] == sha


def test_staging_expiry_is_enforced(tmp_path: Path):
    data = _image_bytes("JPEG")
    sha = hashlib.sha256(data).hexdigest()
    store = ThumbnailStagingStore(tmp_path, ttl_seconds=60)
    staged = store.create(
        video_id="video-1", data=data, sha256=sha, mime_type="image/jpeg",
        width=1672, height=941, source_type="generated_file", source_sha256=sha, source_size_bytes=len(data), now=1000,
    )
    with pytest.raises(CreatorToolError) as caught:
        store.load(staging_id=staged["staging_id"], video_id="video-1", expected_sha256=sha, now=1061)
    _code(caught, "thumbnail_staging_expired")


def test_staging_video_swap_is_blocked(tmp_path: Path):
    data = _image_bytes("JPEG")
    sha = hashlib.sha256(data).hexdigest()
    store = ThumbnailStagingStore(tmp_path)
    staged = store.create(
        video_id="video-1", data=data, sha256=sha, mime_type="image/jpeg",
        width=1672, height=941, source_type="generated_file", source_sha256=sha, source_size_bytes=len(data),
    )
    with pytest.raises(CreatorToolError) as caught:
        store.load(staging_id=staged["staging_id"], video_id="video-2", expected_sha256=sha)
    _code(caught, "approval_invalid")


def test_staging_hash_swap_is_blocked(tmp_path: Path):
    data = _image_bytes("JPEG")
    sha = hashlib.sha256(data).hexdigest()
    store = ThumbnailStagingStore(tmp_path)
    staged = store.create(
        video_id="video-1", data=data, sha256=sha, mime_type="image/jpeg",
        width=1672, height=941, source_type="generated_file", source_sha256=sha, source_size_bytes=len(data),
    )
    with pytest.raises(CreatorToolError) as caught:
        store.load(staging_id=staged["staging_id"], video_id="video-1", expected_sha256="0" * 64)
    _code(caught, "thumbnail_hash_mismatch")


def test_consumed_staging_cannot_be_reused(tmp_path: Path):
    data = _image_bytes("JPEG")
    sha = hashlib.sha256(data).hexdigest()
    store = ThumbnailStagingStore(tmp_path)
    staged = store.create(
        video_id="video-1", data=data, sha256=sha, mime_type="image/jpeg",
        width=1672, height=941, source_type="generated_file", source_sha256=sha, source_size_bytes=len(data),
    )
    store.mark_consumed(staged["staging_id"])
    with pytest.raises(CreatorToolError) as caught:
        store.load(staging_id=staged["staging_id"], video_id="video-1", expected_sha256=sha)
    _code(caught, "thumbnail_staging_failed")


def test_decompression_bomb_is_rejected(tmp_path: Path, monkeypatch):
    data = _image_bytes("PNG", (1000, 1000))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_file={
                "name": "bomb.png",
                "mime_type": "image/png",
                "source_type": "generated_file",
                "content_base64": _b64(data),
            },
        )
    _code(caught, "thumbnail_decode_failed")


def test_large_input_is_recompressed_below_configured_upload_limit(tmp_path: Path, monkeypatch):
    data = _image_bytes("BMP", (1280, 720))
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "name": "large.bmp",
            "mime_type": "image/bmp",
            "source_type": "generated_file",
            "content_base64": _b64(data),
        },
    )
    monkeypatch.setattr(thumbnail_module, "YOUTUBE_THUMBNAIL_MAX_BYTES", 200_000)
    normalized_bytes, normalized = normalize_thumbnail_for_youtube(resolved, source)
    assert len(data) > 200_000
    assert len(normalized_bytes) <= 200_000
    assert normalized["mime_type"] == "image/jpeg"
    assert normalized["converted"] is True
    assert normalized["compressed"] is True
