from pathlib import Path


def _workflow() -> str:
    return Path('.github/workflows/deploy-production.yml').read_text(encoding='utf-8')


def _ci() -> str:
    return Path('.github/workflows/ci.yml').read_text(encoding='utf-8')


def test_manual_dispatch_resolves_feature_production_branch() -> None:
    workflow = _workflow()
    assert 'refs/heads/feat/web-dashboard-v1' in workflow
    assert 'git ls-remote' in workflow


def test_deploy_workflow_changes_force_validation_before_generic_github_skip() -> None:
    workflow = _workflow()
    special = '              .github/workflows/deploy-production.yml)\n                needed=true\n                break'
    generic = '              .github/*|tests/*|docs/*|README.md|*.md)'
    assert special in workflow
    assert generic in workflow
    assert workflow.index(special) < workflow.index(generic)


def test_deployed_runtime_verifier_targets_full_composed_surface() -> None:
    workflow = _workflow()
    assert 'from creator_service.cloud_mcp_server_v1_compat import HANDOFF_UI_URI, create_server' in workflow
    assert "assert len(names) == 47" in workflow
    assert 'production_full_mcp_discovery=ok count={len(names)} resources={len(uris)}' in workflow


def test_existing_public_security_checks_are_preserved() -> None:
    workflow = _workflow()
    assert 'Handoff page HTTP $handoff_code' in workflow
    assert 'auth_config=ok' in workflow
    assert 'Handoff security headers: OK' in workflow


def test_browser_audit_uses_patched_playwright_and_keeps_security_gate() -> None:
    workflow = _workflow()
    assert 'playwright@1.63.0' in workflow
    assert 'playwright@1.55.0' not in workflow
    assert 'npm audit --audit-level=high' in workflow
    assert 'npx playwright install --with-deps chromium' in workflow
    assert 'node tests/live_browser_smoke.js' in workflow


def test_github_actions_use_node24_capable_major_versions() -> None:
    workflow = _workflow()
    ci = _ci()
    assert 'actions/checkout@v4' not in workflow
    assert 'actions/setup-node@v4' not in workflow
    assert 'actions/upload-artifact@v4' not in workflow
    assert 'actions/checkout@v5' in workflow
    assert 'actions/setup-node@v5' in workflow
    assert 'actions/upload-artifact@v6' in workflow
    assert 'package-manager-cache: false' in workflow

    assert 'actions/checkout@v4' not in ci
    assert 'actions/setup-python@v5' not in ci
    assert 'actions/setup-node@v4' not in ci
    assert 'actions/checkout@v5' in ci
    assert 'actions/setup-python@v6' in ci
    assert 'actions/setup-node@v5' in ci
