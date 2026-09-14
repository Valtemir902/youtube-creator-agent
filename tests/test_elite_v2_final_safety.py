from __future__ import annotations

from pathlib import Path


def test_final_desktop_boot_is_local_and_does_not_auto_call_sensitive_services() -> None:
    shell = Path("src/desktop_web_shell.py").read_text(encoding="utf-8")
    reach = Path("src/elite_v2_reach_ui.py").read_text(encoding="utf-8")
    ai_ui = Path("src/elite_v2_ai_execution_ui.py").read_text(encoding="utf-8")
    management = Path("src/elite_v2_management_ui.py").read_text(encoding="utf-8")

    assert "start_elite_v2_final_server" in shell
    assert 'self.local_base + "/dashboard"' in shell
    assert "creator.silvadigitaltech.com" not in shell

    # Reporting is nested behind the user's explicit click.
    assert reach.index("button.addEventListener('click'") < reach.index("fetch('/api/v2/reporting/reach")
    assert "create_reach_job" not in reach
    assert "jobs.create" not in reach

    # External/local model execution is also explicit, never a boot side effect.
    assert ai_ui.index("button.addEventListener('click'") < ai_ui.index("fetch('/api/v2/ai/propose")

    # Mutation apply is explicit and cannot precede preview in the UI contract.
    assert management.index("/api/v2/manage/preview") < management.index("/api/v2/manage/apply/")
    assert "confirmed:true" in management


def test_reporting_backend_never_implicitly_creates_admin_job() -> None:
    server = Path("src/elite_v2_server.py").read_text(encoding="utf-8")
    reporting = Path("src/intelligence/free_reach_reporting.py").read_text(encoding="utf-8")
    assert "fetch_latest" in server
    assert "create_reach_job(" not in server
    assert "def create_reach_job" in reporting
    assert "ensure_reach_job" in reporting
    # The compatibility alias is intentionally read-only.
    alias = reporting[reporting.index("def ensure_reach_job"):]
    assert "return self.reach_job_state()" in alias


def test_final_control_plane_revalidates_ownership_before_adapter_selection() -> None:
    source = Path("src/elite_v2_final_server.py").read_text(encoding="utf-8")
    adapter = source.index("def _management_adapter")
    ownership = source.index("require_proposal_ownership", adapter)
    parent_adapter = source.index("super()._management_adapter", adapter)
    assert adapter < ownership < parent_adapter
    assert "require_owned_video" in source
    assert "require_owned_playlist" in source
    assert "require_owned_playlist_item" in source


def test_automation_handoff_cannot_apply_youtube_write() -> None:
    source = Path("src/elite_v2_automation.py").read_text(encoding="utf-8")
    assert "Approval never performs a YouTube write" in source
    assert '"youtube_write_performed": False' in source
    assert "create_write_gateway" not in source
    assert "session.request" not in source
