from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _delta_pct(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100.0, 2)


class FreeChannelTrend:
    VERSION = "free-channel-trend-v1"

    def compare(self, current: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        metrics = {}
        for key in ("views", "estimatedMinutesWatched", "subscribersGained", "likes", "comments", "shares"):
            cur = _num(current.get(key))
            prev = _num(previous.get(key))
            metrics[key] = {"current": round(cur, 2), "previous": round(prev, 2), "delta": round(cur - prev, 2), "delta_pct": _delta_pct(cur, prev)}
        score_parts = []
        for key in ("views", "estimatedMinutesWatched", "subscribersGained"):
            pct = metrics[key]["delta_pct"]
            if pct is not None:
                score_parts.append(max(-100.0, min(100.0, pct)))
        momentum = round(50 + (sum(score_parts) / max(1, len(score_parts))) * 0.5, 2) if score_parts else 50.0
        momentum = max(0.0, min(100.0, momentum))
        if momentum >= 60:
            status = "growing"
        elif momentum <= 40:
            status = "declining"
        else:
            status = "stable"
        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "writes_performed": 0,
            "metrics": metrics,
            "momentum_score": round(momentum, 2),
            "status": status,
            "methodology": "Compares adjacent equal-length YouTube Analytics periods. Missing or zero baselines are not converted into fake percentages.",
        }
