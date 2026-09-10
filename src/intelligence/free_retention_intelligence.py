from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FreeRetentionIntelligence:
    VERSION = "free-retention-intelligence-v1"

    def analyze(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        clean = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ratio = max(0.0, min(1.0, _num(row.get("elapsedVideoTimeRatio"), _num(row.get("elapsed_video_time_ratio")))))
            audience = max(0.0, min(1.0, _num(row.get("audienceWatchRatio"), _num(row.get("audience_watch_ratio")))))
            relative = max(0.0, _num(row.get("relativeRetentionPerformance"), _num(row.get("relative_retention_performance"))))
            clean.append({"ratio": ratio, "audience_watch_ratio": audience, "relative_retention_performance": relative})
        clean.sort(key=lambda row: row["ratio"])
        if len(clean) < 4:
            return {
                "engine": self.VERSION,
                "data_available": False,
                "writes_performed": 0,
                "recommendations": [],
                "blocked_reason": "Curva de retenção insuficiente para diagnóstico confiável.",
            }
        def nearest(target: float) -> dict[str, float]:
            return min(clean, key=lambda row: abs(row["ratio"] - target))
        p10, p25, p50, p75 = (nearest(x) for x in (0.10, 0.25, 0.50, 0.75))
        steepest = None
        for before, after in zip(clean, clean[1:]):
            delta_x = max(0.0001, after["ratio"] - before["ratio"])
            drop = before["audience_watch_ratio"] - after["audience_watch_ratio"]
            slope = drop / delta_x
            if steepest is None or slope > steepest["slope"]:
                steepest = {"from_ratio": before["ratio"], "to_ratio": after["ratio"], "drop": round(drop, 4), "slope": round(slope, 4)}
        recs = []
        if p10["audience_watch_ratio"] < 0.70:
            recs.append({"code": "weak_opening_retention", "priority": "alta", "title": "Fortalecer os primeiros segundos", "evidence": {"retention_near_10pct": p10["audience_watch_ratio"]}, "confidence": 90})
        if p50["audience_watch_ratio"] < 0.45:
            recs.append({"code": "mid_video_drop", "priority": "média", "title": "Revisar ritmo no meio do vídeo", "evidence": {"retention_near_50pct": p50["audience_watch_ratio"]}, "confidence": 85})
        if steepest and steepest["drop"] >= 0.08:
            recs.append({"code": "sharp_retention_drop", "priority": "alta", "title": "Investigar queda abrupta de retenção", "evidence": steepest, "confidence": 92})
        score = round(max(0.0, min(100.0, (p10["audience_watch_ratio"] * 30 + p25["audience_watch_ratio"] * 25 + p50["audience_watch_ratio"] * 25 + p75["audience_watch_ratio"] * 20) * 100)))
        return {
            "engine": self.VERSION,
            "source": "youtube_analytics_api",
            "data_available": True,
            "writes_performed": 0,
            "retention_score": score,
            "checkpoints": {"10pct": p10, "25pct": p25, "50pct": p50, "75pct": p75},
            "steepest_drop": steepest,
            "curve": clean,
            "recommendations": recs,
            "methodology": "Deterministic analysis of official YouTube audience-retention rows. No LLM and no inferred missing values.",
        }
