from datetime import datetime, timedelta, timezone

from src.intelligence.channel_learning import (
    ChannelProfile,
    ChannelSnapshotStore,
    SearchTermSignal,
    _duration_seconds,
)


def _profile(measured_at: str, channel_id: str = "channel-1") -> ChannelProfile:
    return ChannelProfile(
        measured_at=measured_at,
        channel_id=channel_id,
        channel_title="Canal Teste",
        subscribers=1000,
        total_views=100000,
        video_count=20,
        period_days=28,
        search_views=1000,
        total_analytics_views=5000,
        search_share=0.2,
        top_search_terms=(
            SearchTermSignal("vida na roça", 500, 1200.0, 0.5),
            SearchTermSignal("rotina no sítio", 250, 500.0, 0.25),
        ),
        top_videos=tuple(),
        weak_videos=tuple(),
        topic_terms=("roça", "sítio", "rotina", "chácara"),
        shorts_share_of_recent_views=0.35,
        long_share_of_recent_views=0.65,
    )


def test_duration_parser_supports_common_youtube_durations():
    assert _duration_seconds("PT59S") == 59
    assert _duration_seconds("PT2M30S") == 150
    assert _duration_seconds("PT1H2M3S") == 3723


def test_channel_fit_rewards_terms_proven_by_own_channel():
    profile = _profile(datetime.now(timezone.utc).isoformat())
    strong = profile.channel_fit("vida na roça")
    adjacent = profile.channel_fit("rotina na chácara")
    unrelated = profile.channel_fit("placa de vídeo gamer")
    assert strong > adjacent > unrelated
    assert 0 <= unrelated <= 1
    assert strong <= 1


def test_snapshot_store_purges_old_profiles(tmp_path):
    store = ChannelSnapshotStore(tmp_path / "channel.sqlite3")
    old = _profile((datetime.now(timezone.utc) - timedelta(days=40)).isoformat())
    recent = _profile(datetime.now(timezone.utc).isoformat())
    store.save(old)
    store.save(recent)
    latest = store.latest()
    assert latest is not None
    assert latest["measured_at"] == recent.measured_at
