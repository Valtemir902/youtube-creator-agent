from pathlib import Path


def _workflow() -> str:
    return Path('.github/workflows/deploy-production.yml').read_text(encoding='utf-8')


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
