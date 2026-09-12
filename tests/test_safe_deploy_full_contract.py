from __future__ import annotations

from pathlib import Path

import pytest

from creator_service import full_mcp_contract
from creator_service.cloud_mcp_server_responsible import create_server as create_responsible_server
from creator_service.cloud_mcp_server_v1_compat import create_server as create_public_server


def _env(monkeypatch) -> None:
    monkeypatch.setenv("YCA_AUTH_ISSUER_URL", "https://auth.example.com")
    monkeypatch.setenv("YCA_MCP_PUBLIC_URL", "https://creator.example.com/mcp")
    monkeypatch.setenv("YCA_ONBOARDING_PUBLIC_URL", "https://creator.example.com")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_URL", "https://auth.example.com/oauth/introspect")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_ID", "test-client")
    monkeypatch.setenv("YCA_AUTH_INTROSPECTION_CLIENT_SECRET", "test-secret")


def _names(server) -> set[str]:
    return {tool.name for tool in server._tool_manager.list_tools()}


def _resource_uris(server) -> set[str]:
    return {str(resource.uri) for resource in server._resource_manager.list_resources()}


def test_standalone_wrapper_factory_is_exact_full_contract(monkeypatch) -> None:
    _env(monkeypatch)
    wrapper = Path("deploy/remote_update.sh").read_text(encoding="utf-8")
    assert "from creator_service.cloud_mcp_server_responsible import create_server" in wrapper

    server = create_responsible_server()
    assert _names(server) == full_mcp_contract.EXPECTED_TOOL_NAMES
    assert len(_names(server)) == 47
    assert _resource_uris(server) == {full_mcp_contract.EXPECTED_RESOURCE_URI}


def test_public_v1_compat_surface_remains_exactly_47_plus_one(monkeypatch) -> None:
    _env(monkeypatch)
    server = create_public_server()
    assert _names(server) == full_mcp_contract.EXPECTED_TOOL_NAMES
    assert len(_names(server)) == 47
    assert _resource_uris(server) == {full_mcp_contract.EXPECTED_RESOURCE_URI}


def test_responsible_factory_fails_closed_on_contract_drift(monkeypatch) -> None:
    _env(monkeypatch)
    monkeypatch.setattr(
        full_mcp_contract,
        "EXPECTED_TOOL_NAMES",
        set(full_mcp_contract.EXPECTED_TOOL_NAMES) - {"creator_status"},
    )
    with pytest.raises(AssertionError, match="unexpected"):
        create_responsible_server()
