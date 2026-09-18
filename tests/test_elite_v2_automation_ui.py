from __future__ import annotations

from elite_v2_automation_ui import AUTOMATION_UI_JS, automation_ui_webengine_source


def test_automation_ui_only_approves_cancels_or_hands_off() -> None:
    source = automation_ui_webengine_source()
    for token in (
        "data-v2-automation",
        "/api/v2/automation?limit=100",
        "/api/v2/automation/approve/",
        "/api/v2/automation/cancel/",
        "/api/v2/automation/handoff/",
        "youtube_write_performed",
        "Write Gateway",
    ):
        assert token in source
    assert "/api/v2/manage/apply/" not in AUTOMATION_UI_JS
    assert "/api/dashboard/metadata/apply/" not in AUTOMATION_UI_JS
