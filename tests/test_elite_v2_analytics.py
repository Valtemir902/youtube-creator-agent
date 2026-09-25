from __future__ import annotations

from elite_v2_analytics import read_analytics_timeseries


class FakeAnalyticsClient:
    def __init__(self, *, payload=None, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error
        self.calls = []

    def _get(self, url, params):
        self.calls.append((url, params))
        if self.error:
            raise self.error
        return self.payload


def test_timeseries_uses_official_daily_analytics_and_never_estimates() -> None:
    client = FakeAnalyticsClient(
        payload={
            "rows": [
                ["2026-09-11", 120, 180.0, 4, 1],
                ["2026-09-12", 150, 210.0, 3, 2],
            ]
        }
    )
    result = read_analytics_timeseries(client, 28)
    assert result["available"] is True
    assert result["source"] == "youtube_analytics_api"
    assert result["estimated"] is False
    assert result["row_count"] == 2
    assert result["rows"][0] == {
        "date": "2026-09-11",
        "views": 120,
        "watch_time_hours": 3.0,
        "subscribers_gained": 4,
        "subscribers_lost": 1,
        "subscribers_net": 3,
    }
    _, params = client.calls[0]
    assert params["dimensions"] == "day"
    assert params["sort"] == "day"
    assert "views" in params["metrics"]
    assert "estimatedMinutesWatched" in params["metrics"]


def test_timeseries_reports_unavailable_instead_of_fabricating_zero_series() -> None:
    result = read_analytics_timeseries(FakeAnalyticsClient(error=RuntimeError("analytics unavailable")), 28)
    assert result["available"] is False
    assert result["estimated"] is False
    assert result["rows"] == []
    assert "analytics unavailable" in result["error"]


def test_timeseries_clamps_requested_period() -> None:
    short = read_analytics_timeseries(FakeAnalyticsClient(), 1)
    long = read_analytics_timeseries(FakeAnalyticsClient(), 999)
    assert short["period_days"] == 7
    assert long["period_days"] == 365
