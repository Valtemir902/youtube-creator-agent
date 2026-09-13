from __future__ import annotations

from elite_v2_management_ui import MANAGEMENT_UI_JS, management_ui_webengine_source


def test_management_ui_exposes_supervised_actions_without_auto_apply() -> None:
    source = management_ui_webengine_source()
    for token in (
        "data-v2-management",
        "video_privacy",
        "video_delete",
        "playlist_create",
        "playlist_update",
        "playlist_delete",
        "playlist_item_add",
        "playlist_item_remove",
        "playlist_item_reorder",
        "thumbnail_replace",
        "/api/v2/manage/preview",
        "/api/v2/manage/apply/",
        "/api/v2/manage/rollback/",
        "readback_verified",
    ):
        assert token in source

    preview_pos = MANAGEMENT_UI_JS.index("/api/v2/manage/preview")
    apply_pos = MANAGEMENT_UI_JS.index("/api/v2/manage/apply/")
    assert preview_pos < apply_pos
    assert "confirmed:true" in MANAGEMENT_UI_JS
    assert "content_base64" in MANAGEMENT_UI_JS
    assert "crypto.subtle.digest('SHA-256'" in MANAGEMENT_UI_JS


def test_management_ui_does_not_call_apply_during_install() -> None:
    # Apply is nested under the user's explicit click handler, never the install path.
    click_pos = MANAGEMENT_UI_JS.index("apply.addEventListener('click'")
    apply_fetch_pos = MANAGEMENT_UI_JS.index("fetch(`/api/v2/manage/apply/")
    assert apply_fetch_pos > click_pos
