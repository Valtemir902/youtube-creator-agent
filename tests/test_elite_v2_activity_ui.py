from __future__ import annotations

from elite_v2_activity_ui import ACTIVITY_CSS, ACTIVITY_JS, activity_ui_webengine_source


def test_activity_workspace_is_read_only_audit_surface() -> None:
    source = activity_ui_webengine_source()
    for token in (
        "data-v2-activity",
        "Activity & Audit",
        "/api/v2/activity?limit=100",
        "Write Gateway",
        "Nenhuma alteração passou",
    ):
        assert token in source
    assert "method:" not in ACTIVITY_JS.lower()
    assert "POST" not in ACTIVITY_JS
    assert "DELETE" not in ACTIVITY_JS
    assert ".v2-activity" in ACTIVITY_CSS
