from intelligence.free_channel_trend import FreeChannelTrend
from intelligence.free_publication_strategy import FreePublicationStrategy


def test_channel_trend_compares_equal_period_metrics_without_fake_baseline():
    current = {"views": 1200, "estimatedMinutesWatched": 3000, "subscribersGained": 24, "likes": 90, "comments": 20, "shares": 10}
    previous = {"views": 1000, "estimatedMinutesWatched": 2500, "subscribersGained": 20, "likes": 80, "comments": 25, "shares": 8}
    report = FreeChannelTrend().compare(current, previous)
    assert report["metrics"]["views"]["delta_pct"] == 20.0
    assert report["status"] == "growing"
    assert report["uses_external_ai"] is False
    assert report["writes_performed"] == 0


def test_channel_trend_zero_previous_does_not_invent_percentage():
    report = FreeChannelTrend().compare({"views": 100}, {"views": 0})
    assert report["metrics"]["views"]["delta_pct"] is None


def test_publication_strategy_requires_own_channel_sample():
    report = FreePublicationStrategy().analyze([
        {"published_at": "2026-09-01T12:00:00Z", "velocity_28d": 10, "engagement_rate_28d": 0.02, "subscribers_gained_28d": 1},
        {"published_at": "2026-09-02T12:00:00Z", "velocity_28d": 9, "engagement_rate_28d": 0.02, "subscribers_gained_28d": 1},
    ])
    assert report["recommendation_ready"] is False
    assert report["writes_performed"] == 0


def test_publication_strategy_ranks_only_measured_channel_history():
    rows = [
        {"published_at": "2026-08-03T18:00:00Z", "velocity_28d": 50, "engagement_rate_28d": 0.03, "subscribers_gained_28d": 6},
        {"published_at": "2026-08-10T18:30:00Z", "velocity_28d": 55, "engagement_rate_28d": 0.04, "subscribers_gained_28d": 7},
        {"published_at": "2026-08-17T19:00:00Z", "velocity_28d": 52, "engagement_rate_28d": 0.03, "subscribers_gained_28d": 5},
        {"published_at": "2026-08-05T09:00:00Z", "velocity_28d": 10, "engagement_rate_28d": 0.01, "subscribers_gained_28d": 1},
        {"published_at": "2026-08-12T09:30:00Z", "velocity_28d": 12, "engagement_rate_28d": 0.01, "subscribers_gained_28d": 1},
        {"published_at": "2026-08-19T09:30:00Z", "velocity_28d": 11, "engagement_rate_28d": 0.01, "subscribers_gained_28d": 1},
    ]
    report = FreePublicationStrategy().analyze(rows)
    assert report["recommendation_ready"] is True
    assert report["sample_size"] == 6
    assert report["best_windows"][0]["weekday"] == 0
    assert report["best_windows"][0]["hour_start"] == 18
    assert "no generic best-time claims" in report["methodology"]
