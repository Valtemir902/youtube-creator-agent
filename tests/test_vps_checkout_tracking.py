from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (REPO_ROOT / "deploy" / "remote_update.sh").read_text(encoding="utf-8")
CORE = (REPO_ROOT / "deploy" / "remote_update_core.sh").read_text(encoding="utf-8")
BRANCH = "feat/web-dashboard-v1"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _git_run(cwd: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=cwd)


def _commit(repo: Path, message: str, filename: str) -> str:
    (repo / filename).write_text(message, encoding="utf-8")
    _git_run(repo, "add", filename)
    _git_run(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_wrapper_refreshes_production_remote_tracking_ref_before_core() -> None:
    refspec = (
        '"refs/heads/feat/web-dashboard-v1:'
        'refs/remotes/origin/feat/web-dashboard-v1"'
    )
    fetch_index = WRAPPER.index(refspec)
    core_index = WRAPPER.index('/tmp/yca-remote-update-core-patched.sh "$TARGET_SHA"')

    assert fetch_index < core_index
    assert 'git fetch --prune origin "$TARGET_SHA"' in WRAPPER


def test_core_preserves_exact_target_sha_and_previous_sha_rollback_contract() -> None:
    previous_index = CORE.index('PREVIOUS_SHA="$(git rev-parse HEAD)"')
    deploy_index = CORE.index('git reset --hard "$TARGET_SHA"')
    rollback_index = CORE.index('git reset --hard "$PREVIOUS_SHA"')

    assert previous_index < deploy_index
    assert rollback_index < deploy_index
    assert 'echo "Deploying commit $TARGET_SHA (previous: $PREVIOUS_SHA)"' in CORE


def test_tracking_ref_refresh_removes_artificial_ahead_state_and_keeps_exact_sha(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    vps = tmp_path / "vps"

    _git_run(tmp_path, "init", "--bare", str(origin))
    _git_run(tmp_path, "init", str(seed))
    _git_run(seed, "config", "user.email", "ci@example.invalid")
    _git_run(seed, "config", "user.name", "CI")

    first_sha = _commit(seed, "initial", "initial.txt")
    _git_run(seed, "branch", "-M", BRANCH)
    _git_run(seed, "remote", "add", "origin", str(origin))
    _git_run(seed, "push", "-u", "origin", BRANCH)

    _git_run(tmp_path, "clone", "--branch", BRANCH, str(origin), str(vps))
    _git_run(vps, "config", "user.email", "ci@example.invalid")
    _git_run(vps, "config", "user.name", "CI")
    assert _git(vps, "rev-parse", f"refs/remotes/origin/{BRANCH}") == first_sha

    target_sha = first_sha
    for index in range(6):
        target_sha = _commit(seed, f"runtime-{index}", f"runtime-{index}.txt")
    _git_run(seed, "push", "origin", BRANCH)

    # Reproduce the old production behaviour: fetch only the exact candidate SHA.
    _git_run(vps, "fetch", "--prune", "origin", target_sha)
    _git_run(vps, "reset", "--hard", target_sha)
    stale_status = _git(vps, "status", "--short", "--branch")
    assert "ahead 6" in stale_status
    assert _git(vps, "rev-parse", f"refs/remotes/origin/{BRANCH}") == first_sha

    previous_sha = _git(vps, "rev-parse", "HEAD")

    # New wrapper behaviour: refresh the named remote-tracking ref explicitly.
    _git_run(
        vps,
        "fetch",
        "--prune",
        "origin",
        f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}",
    )
    assert _git(vps, "rev-parse", f"refs/remotes/origin/{BRANCH}") == target_sha

    refreshed_status = _git(vps, "status", "--short", "--branch")
    assert "ahead" not in refreshed_status

    # The core still deploys exactly TARGET_SHA, independent of the tracking ref.
    _git_run(vps, "checkout", BRANCH)
    _git_run(vps, "reset", "--hard", target_sha)
    assert _git(vps, "rev-parse", "HEAD") == target_sha

    # Rollback semantics still restore the exact SHA captured before deployment.
    _git_run(vps, "reset", "--hard", first_sha)
    rollback_previous_sha = _git(vps, "rev-parse", "HEAD")
    _git_run(vps, "reset", "--hard", target_sha)
    _git_run(vps, "reset", "--hard", rollback_previous_sha)
    assert _git(vps, "rev-parse", "HEAD") == first_sha
    assert previous_sha == target_sha
