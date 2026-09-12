from pathlib import Path


def test_deploy_workflow_changes_force_production_validation() -> None:
    workflow = Path('.github/workflows/deploy-production.yml').read_text(encoding='utf-8')
    special = '              .github/workflows/deploy-production.yml)\n                needed=true\n                break'
    generic = '              .github/*|tests/*|docs/*|README.md|*.md)'
    assert special in workflow
    assert generic in workflow
    assert workflow.index(special) < workflow.index(generic)


def test_ci_and_test_only_changes_still_can_skip_service_churn() -> None:
    workflow = Path('.github/workflows/deploy-production.yml').read_text(encoding='utf-8')
    assert 'Only CI/test/docs files changed; skipping production deploy to avoid needless service churn.' in workflow
