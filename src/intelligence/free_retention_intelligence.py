from __future__ import annotations

from statistics import median
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FreeRetentionIntelligence:
    VERSION = "free-retention-intelligence-v2"

    def analyze(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        clean = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ratio = max(0.0, min(1.0, _num(row.get("elapsedVideoTimeRatio"), _num(row.get("elapsed_video_time_ratio")))))
            # YouTube explicitly allows audienceWatchRatio > 1 when viewers rewatch a segment.
            audience = max(0.0, _num(row.get("audienceWatchRatio"), _num(row.get("audience_watch_ratio"))))
            relative = max(0.0, min(1.0, _num(row.get("relativeRetentionPerformance"), _num(row.get("relative_retention_performance")))))
            started = max(0.0, _num(row.get("startedWatching"), _num(row.get("started_watching"))))
            stopped = max(0.0, _num(row.get("stoppedWatching"), _num(row.get("stopped_watching"))))
            impressions = max(0.0, _num(row.get("totalSegmentImpressions"), _num(row.get("total_segment_impressions"))))
            stop_rate = stopped / impressions if impressions > 0 else None
            clean.append({
                "ratio": ratio,
                "audience_watch_ratio": round(audience, 6),
                "relative_retention_performance": round(relative, 6),
                "started_watching": round(started, 2),
                "stopped_watching": round(stopped, 2),
                "total_segment_impressions": round(impressions, 2),
                "stop_rate": round(stop_rate, 6) if stop_rate is not None else None,
            })
        clean.sort(key=lambda row: row["ratio"])
        if len(clean) < 4:
            return {"engine": self.VERSION, "data_available": False, "writes_performed": 0, "recommendations": [], "blocked_reason": "Curva de retenção insuficiente para diagnóstico confiável."}

        def nearest(target: float) -> dict[str, Any]:
            return min(clean, key=lambda row: abs(row["ratio"] - target))

        p10, p25, p50, p75 = (nearest(x) for x in (0.10, 0.25, 0.50, 0.75))
        steepest = None
        for before, after in zip(clean, clean[1:]):
            delta_x = max(0.0001, after["ratio"] - before["ratio"])
            drop = before["audience_watch_ratio"] - after["audience_watch_ratio"]
            slope = drop / delta_x
            if steepest is None or slope > steepest["slope"]:
                steepest = {"from_ratio": before["ratio"], "to_ratio": after["ratio"], "drop": round(drop, 4), "slope": round(slope, 4)}

        abandonment = [row for row in clean if row["stop_rate"] is not None]
        worst_abandonment = max(abandonment, key=lambda row: row["stop_rate"], default=None)
        relative_values = [row["relative_retention_performance"] for row in clean]
        relative_median = round(median(relative_values), 4) if relative_values else None
        recs = []
        if p10["audience_watch_ratio"] < 0.70:
            recs.append({"code": "weak_opening_retention", "priority": "alta", "title": "Fortalecer os primeiros segundos", "evidence": {"retention_near_10pct": p10["audience_watch_ratio"]}, "confidence": 90})
        if p50["audience_watch_ratio"] < 0.45:
            recs.append({"code": "mid_video_drop", "priority": "média", "title": "Revisar ritmo no meio do vídeo", "evidence": {"retention_near_50pct": p50["audience_watch_ratio"]}, "confidence": 85})
        if steepest and steepest["drop"] >= 0.08:
            recs.append({"code": "sharp_retention_drop", "priority": "alta", "title": "Investigar queda abrupta de retenção", "evidence": steepest, "confidence": 92})
        if worst_abandonment and worst_abandonment["stop_rate"] >= 0.08:
            recs.append({"code": "abandonment_hotspot", "priority": "alta", "title": "Investigar ponto de abandono", "evidence": {"ratio": worst_abandonment["ratio"], "stop_rate": worst_abandonment["stop_rate"], "stopped_watching": worst_abandonment["stopped_watching"], "segment_impressions": worst_abandonment["total_segment_impressions"]}, "confidence": 95})
        if relative_median is not None and relative_median < 0.35:
            recs.append({"code": "below_peer_retention", "priority": "média", "title": "Retenção abaixo de vídeos de duração semelhante", "evidence": {"relative_retention_median": relative_median}, "confidence": 88})

        capped = [min(1.0, p10["audience_watch_ratio"]), min(1.0, p25["audience_watch_ratio"]), min(1.0, p50["audience_watch_ratio"]), min(1.0, p75["audience_watch_ratio"])]
        score = round(max(0.0, min(100.0, (capped[0] * 30 + capped[1] * 25 + capped[2] * 25 + capped[3] * 20) * 100)))
        return {
            "engine": self.VERSION,
            "source": "youtube_analytics_api",
            "data_available": True,
            "writes_performed": 0,
            "retention_score": score,
            "checkpoints": {"10pct": p10, "25pct": p25, "50pct": p50, "75pct": p75},
            "relative_retention_median": relative_median,
            "steepest_drop": steepest,
            "worst_abandonment": worst_abandonment,
            "curve": clean,
            "recommendations": recs,
            "methodology": "Deterministic analysis of official YouTube retention and abandonment rows. Rewatch ratios above 1 are preserved; score contribution is capped only when scoring. No LLM and no inferred missing values.",
        }
