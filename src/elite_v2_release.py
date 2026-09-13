from __future__ import annotations

# Single release contract used as the exact certification marker for the final
# Elite V2 candidate. Changing this file intentionally triggers CI, visual
# screenshots, Local AI regression, and the packaged Windows EXE smoke at the
# same commit so evidence cannot be mixed across different heads.
ELITE_V2_RELEASE = {
    "version": "2.0.0-rc1",
    "desktop_mode": "local_first",
    "ui": "professional_cards_images_real_charts",
    "content_hub": True,
    "growth_analytics": "official_only",
    "reporting_api": "on_demand_read_only",
    "seo_provenance_required": True,
    "ai_execution": "explicit_proposal_only",
    "ai_providers": ["local", "api", "chatgpt_handoff", "internal"],
    "automation": "supervised_approval_queue",
    "manual_management": [
        "video_metadata",
        "video_privacy",
        "video_delete",
        "playlist_create",
        "playlist_update",
        "playlist_delete",
        "playlist_item_add",
        "playlist_item_remove",
        "playlist_item_reorder",
        "thumbnail_replace",
    ],
    "write_policy": "preview_approval_apply_readback_audit",
    "ownership_revalidation_before_mutation": True,
    "destructive_confirmation": "target_specific",
    "reporting_job_creation_at_boot": False,
    "external_ai_at_boot": False,
    "youtube_write_at_boot": False,
    "local_ai_required_semantic_state": "Ativa neste dispositivo",
    "stable_dashboard_replaced": False,
}
