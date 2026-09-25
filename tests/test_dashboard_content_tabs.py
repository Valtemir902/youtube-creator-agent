from __future__ import annotations

from pathlib import Path

from creator_service.dashboard_routes import _dashboard_content_bucket, _iso8601_duration_seconds


def test_duration_parser_handles_youtube_iso8601_values() -> None:
    assert _iso8601_duration_seconds("PT59S") == 59
    assert _iso8601_duration_seconds("PT3M") == 180
    assert _iso8601_duration_seconds("PT3M1S") == 181
    assert _iso8601_duration_seconds("PT1H2M3S") == 3723
    assert _iso8601_duration_seconds("") is None
    assert _iso8601_duration_seconds("not-a-duration") is None


def test_content_bucket_prefers_official_live_state() -> None:
    item = {
        "snippet": {"liveBroadcastContent": "live"},
        "contentDetails": {"duration": "PT30S"},
    }
    assert _dashboard_content_bucket(item) == ("live", "official_live_state")


def test_content_bucket_uses_live_streaming_details_for_completed_streams() -> None:
    item = {
        "snippet": {"liveBroadcastContent": "none"},
        "contentDetails": {"duration": "PT2H"},
        "liveStreamingDetails": {"actualStartTime": "2026-09-20T12:00:00Z"},
    }
    assert _dashboard_content_bucket(item) == ("live", "official_live_state")


def test_content_bucket_marks_short_duration_as_candidate_not_certainty() -> None:
    item = {
        "snippet": {"liveBroadcastContent": "none"},
        "contentDetails": {"duration": "PT2M59S"},
    }
    assert _dashboard_content_bucket(item) == ("shorts", "duration_candidate")


def test_content_bucket_keeps_long_video_in_videos() -> None:
    item = {
        "snippet": {"liveBroadcastContent": "none"},
        "contentDetails": {"duration": "PT12M4S"},
    }
    assert _dashboard_content_bucket(item) == ("videos", "duration_or_default")


def test_dashboard_has_studio_style_content_navigation_without_fake_post_actions() -> None:
    html = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    assert 'data-tab="videos">▤ Conteúdo</button>' in html
    for tab in ("videos", "shorts", "live", "posts", "playlists"):
        assert f'data-content-tab="{tab}"' in html
    assert 'id="contentSearch"' in html
    assert 'id="contentMediaPanel"' in html
    assert 'id="postsPanel"' in html
    assert 'id="playlistManager"' in html
    assert "API pública não oferece atualmente um endpoint oficial para listar ou publicar Posts" in html
    assert "Nenhuma automação não oficial será executada." in html
    assert "function setContentTab(name)" in html
    assert "function normalizedContentBucket(v)" in html


def test_playlist_manager_is_no_longer_moved_into_overview() -> None:
    html = Path("src/creator_service/web/dashboard.html").read_text(encoding="utf-8")
    assert "Playlists now live inside Conteúdo > Playlists." in html
    assert 'id="playlistHomeSlot" class="hidden"' in html


def test_dashboard_video_inventory_requests_official_classification_fields() -> None:
    code = Path("src/creator_service/dashboard_routes.py").read_text(encoding="utf-8")
    assert 'part="snippet,statistics,status,contentDetails,liveStreamingDetails"' in code
    assert '"content_bucket": content_bucket' in code
    assert '"content_bucket_basis": bucket_basis' in code
    assert '"duration_seconds": _iso8601_duration_seconds' in code
