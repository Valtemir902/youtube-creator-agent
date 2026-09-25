from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
import requests
from PIL import Image

from creator_service.mcp_errors import CreatorToolError
import creator_service.thumbnail_update as thumbnail_module
from creator_service.thumbnail_update import resolve_thumbnail_source


def _png(size=(1672, 941)) -> bytes:
    out = io.BytesIO()
    image = Image.effect_noise(size, 64).convert("RGB")
    image.save(out, format="PNG", optimize=False)
    return out.getvalue()


def _jpeg(size=(1536, 864)) -> bytes:
    out = io.BytesIO()
    image = Image.effect_noise(size, 64).convert("RGB")
    image.save(out, format="JPEG", quality=92)
    return out.getvalue()


def _code(exc, expected):
    assert isinstance(exc.value, CreatorToolError)
    assert exc.value.code == expected
    return exc.value


def test_chatgpt_file_param_resolves_real_bytes_once(tmp_path: Path, monkeypatch):
    data = _png()
    calls = []

    def fake_download(url, *, source_kind):
        calls.append((url, source_kind))
        return data, {
            "headers": {"Content-Type": "image/png"},
            "source_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "redirect_count": 0,
            "final_url": url,
        }

    monkeypatch.setattr(thumbnail_module, "_download_https_bytes", fake_download)
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "download_url": "https://files.example.test/private/signed-token",
            "file_id": "file_test_generated_thumbnail",
            "mime_type": "image/png",
            "file_name": "app_da_roça_ia_e_gestão_agrícola.png",
        },
    )

    assert resolved == data
    assert calls == [("https://files.example.test/private/signed-token", "chatgpt_file")]
    assert source["type"] == "chatgpt_file"
    assert source["source_type"] == "chatgpt_file"
    assert source["source_id"] == "file_test_generated_thumbnail"
    assert source["resolver"] == "openai_file_param_download_url"
    assert source["width"] == 1672
    assert source["height"] == 941
    assert source["source_size_bytes"] == len(data)
    assert source["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert source["detected_mime_type"] == "image/png"


def test_chatgpt_file_id_is_treated_as_opaque_host_identifier(tmp_path: Path, monkeypatch):
    data = _png()
    calls = []

    def fake_download(url, *, source_kind):
        calls.append((url, source_kind))
        return data, {
            "headers": {"Content-Type": "image/png"},
            "source_url_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "redirect_count": 0,
            "final_url": url,
        }

    monkeypatch.setattr(thumbnail_module, "_download_https_bytes", fake_download)
    opaque_id = "chatgpt-native:01JQ8Z7A9B2C3D4E5F6G7H8J9K"
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "download_url": "https://files.example.test/private/signed-token",
            "file_id": opaque_id,
            "mime_type": "image/png",
            "file_name": "1000677688.png",
        },
    )

    assert resolved == data
    assert calls == [("https://files.example.test/private/signed-token", "chatgpt_file")]
    assert source["source_id"] == opaque_id
    assert source["source_type"] == "chatgpt_file"


def test_file_id_without_host_authorized_download_url_is_structured_error(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_file={"file_id": "file_0000000091c4820ea7e2f95390e72c18"},
        )
    _code(caught, "thumbnail_file_resolution_failed")


def test_sediment_metadata_is_not_dereferenced_and_still_requires_host_url(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_file={
                "file_id": "file_0000000091c4820ea7e2f95390e72c18",
                "content_location": "sediment://file_0000000091c4820ea7e2f95390e72c18",
            },
        )
    _code(caught, "thumbnail_file_resolution_failed")


@pytest.mark.parametrize("uri", [
    "file:///etc/passwd",
    "ftp://example.test/a.png",
    "gopher://example.test/a",
    "smb://server/share/a.png",
])
def test_non_sediment_content_location_schemes_are_rejected(tmp_path: Path, uri: str):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_file={
                "file_id": "file_test_generated_thumbnail",
                "download_url": "https://files.example.test/private/signed",
                "content_location": uri,
            },
        )
    _code(caught, "thumbnail_source_invalid")


def test_chatgpt_file_host_transcoding_uses_real_bytes_not_stale_metadata(tmp_path: Path, monkeypatch):
    data = _jpeg()
    monkeypatch.setattr(
        thumbnail_module,
        "_download_https_bytes",
        lambda _url, *, source_kind: (
            data,
            {"headers": {"Content-Type": "image/jpeg"}, "source_url_sha256": "x", "redirect_count": 0, "final_url": "https://files.example.test/x"},
        ),
    )
    resolved, source = resolve_thumbnail_source(
        data_dir=tmp_path,
        thumbnail_file={
            "download_url": "https://files.example.test/private/signed",
            "file_id": "file_test_generated_thumbnail",
            "mime_type": "image/png",
            "file_name": "1000677688.png",
        },
    )

    assert resolved == data
    assert source["detected_mime_type"] == "image/jpeg"
    assert source["declared_mime_type"] == "image/png"
    assert source["declared_mime_mismatch"] is True
    assert source["source_extension"] == ".png"
    assert source["source_extension_mismatch"] is True
    assert source["width"] == 1536
    assert source["height"] == 864


def test_chatgpt_file_path_traversal_fields_are_rejected(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_file={
                "download_url": "https://files.example.test/private/signed",
                "file_id": "file_test_generated_thumbnail",
                "path": "../../etc/passwd",
            },
        )
    _code(caught, "thumbnail_source_invalid")


def test_file_namespace_is_not_tenant_asset_namespace(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_asset_id="file_0000000091c4820ea7e2f95390e72c18",
        )
    _code(caught, "thumbnail_source_invalid")


def test_sediment_is_not_a_tenant_asset_id(tmp_path: Path):
    with pytest.raises(CreatorToolError) as caught:
        resolve_thumbnail_source(
            data_dir=tmp_path,
            thumbnail_asset_id="sediment://file_0000000091c4820ea7e2f95390e72c18",
        )
    _code(caught, "thumbnail_source_invalid")


def test_authorized_chatgpt_download_url_is_not_rewritten():
    raw = "https://FILES.Example.test:443/private/a%2Fb?X-Signature=AbC%2F123&Case=KeepMe"
    assert thumbnail_module._validated_authorized_https_url(raw) == raw


class _Response:
    def __init__(self, status):
        self.status_code = status
        self.headers = {
            "Content-Type": "application/xml",
            "Server": "fixture-edge",
            "x-ms-error-code": "AuthenticationFailed",
            "Date": "Fri, 25 Sep 2026 21:40:00 GMT",
        }
        self.is_redirect = False
        self.is_permanent_redirect = False

    def close(self):
        pass


class _Session:
    def __init__(self, status):
        self.status = status

    def get(self, *args, **kwargs):
        return _Response(self.status)

    def close(self):
        pass


@pytest.mark.parametrize(("status", "code"), [
    (401, "thumbnail_file_unauthorized"),
    (403, "thumbnail_file_unauthorized"),
    (404, "thumbnail_file_not_found"),
    (410, "thumbnail_file_not_found"),
    (500, "thumbnail_file_resolution_failed"),
])
def test_chatgpt_download_http_failures_are_structured(monkeypatch, status, code):
    monkeypatch.setattr(thumbnail_module.requests, "Session", lambda: _Session(status))
    monkeypatch.setattr(thumbnail_module, "_validate_public_host", lambda _url: None)
    with pytest.raises(CreatorToolError) as caught:
        thumbnail_module._download_https_bytes(
            "https://files.example.test/private/signed?sv=1&se=2026-09-25T22%3A00%3A00Z&sp=r&sr=b&sig=opaque&spr=https",
            source_kind="chatgpt_file",
        )
    exc = _code(caught, code)
    if status in {401, 403}:
        assert exc.details["download_host"] == "files.example.test"
        assert exc.details["content_type"] == "application/xml"
        assert exc.details["server"] == "fixture-edge"
        assert exc.details["www_authenticate_present"] is False
        assert exc.details["x_ms_error_code"] == "AuthenticationFailed"
        assert exc.details["authorized_url_has_query"] is True
        assert exc.details["azure_sas_fields_present"]["sig"] is True
        assert exc.details["azure_sas_fields_present"]["se"] is True
        assert exc.details["azure_sas_fields_present"]["sp"] is True
        assert exc.details["azure_sas_has_read_permission"] is True
        assert exc.details["azure_sas_expired_at_response"] is False
        assert exc.details["azure_sas_not_yet_valid_at_response"] is False


def test_chatgpt_download_timeout_is_structured(monkeypatch):
    class TimeoutSession:
        def get(self, *args, **kwargs):
            raise requests.Timeout("timeout")
        def close(self):
            pass

    monkeypatch.setattr(thumbnail_module.requests, "Session", lambda: TimeoutSession())
    monkeypatch.setattr(thumbnail_module, "_validate_public_host", lambda _url: None)
    with pytest.raises(CreatorToolError) as caught:
        thumbnail_module._download_https_bytes(
            "https://files.example.test/private/signed",
            source_kind="chatgpt_file",
        )
    _code(caught, "thumbnail_file_resolution_failed")
