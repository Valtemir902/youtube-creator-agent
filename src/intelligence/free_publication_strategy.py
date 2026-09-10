from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


class FreePublicationStrategy:
    VERSION = "free-publication-strategy-v1"

    def analyze(self, videos: list[dict[str, Any]] | None) -> dict[str, Any]:
        buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
        valid = 0
        for video in videos or []:
            if not isinstance(video, dict):
                continue
            dt = _parse(str(video.get("published_at") or video.get("publishedAt") or ""))
            if dt is None:
                continue
            velocity = _num(video.get("velocity_28d"))
            engagement = _num(video.get("engagement_rate_28d"))
            subs = _num(video.get("subscribers_gained_28d"))
            if velocity <= 0:
                continue
            score = velocity * (1 + min(0.5, engagement * 5)) + subs * 2
            hour_bucket = (dt.hour // 3) * 3
            buckets[(dt.weekday(), hour_bucket)].append(score)
            valid += 1
        if valid < 5 or not buckets:
            return {
                "engine": self.VERSION,
                "data_available": False,
                "recommendation_ready": False,
                "writes_performed": 0,
                "blocked_reason": "Poucos vídeos com histórico comparável para inferir janela de publicação do próprio canal.",
            }
        ranked = []
        for (weekday, hour), scores in buckets.items():
            avg = sum(scores) / len(scores)
            ranked.append({"weekday": weekday, "hour_start": hour, "hour_end": (hour + 3) % 24, "sample_size": len(scores), "performance_index": round(avg, 2)})
        ranked.sort(key=lambda row: (-row["performance_index"], -row["sample_size"], row["weekday"], row["hour_start"]))
        top = ranked[:3]
        confidence = min(95, round(40 + min(valid, 30) * 1.5 + min(sum(item["sample_size"] for item in top), 12) * 1.5))
        return {
            "engine": self.VERSION,
            "data_available": True,
            "recommendation_ready": True,
            "sample_size": valid,
            "confidence": confidence,
            "best_windows": top,
            "all_windows": ranked,
            "writes_performed": 0,
            "methodology": "No LLM and no generic best-time claims. Windows are ranked only from the connected channel's own publication timestamps, 28-day velocity, engagement and subscribers gained.",
        }
