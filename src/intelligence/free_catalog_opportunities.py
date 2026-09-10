from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _age_days(value: str) -> int:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).days)
    except Exception:
        return 0


class FreeCatalogOpportunityDetector:
    VERSION = "free-catalog-opportunities-v1"

    def detect(self, video_reports: list[dict[str, Any]] | None, *, limit: int = 12) -> dict[str, Any]:
        rows = []
        for report in video_reports or []:
            if not isinstance(report, dict):
                continue
            optimization = dict(report.get("optimization") or {})
            current = dict(report.get("current") or {})
            published_at = str(current.get("publishedAt") or report.get("published_at") or "")
            age = _age_days(published_at)
            score = _num(report.get("overall_score"))
            delta = max(0.0, _num(optimization.get("projected_score_delta")))
            search_opportunity = max([_num(item.get("decision_score")) for item in (report.get("keyword_intelligence", {}).get("positive_keywords") or []) if isinstance(item, dict)] or [0.0])
            stale_bonus = min(20.0, age / 18.0) if age else 0.0
            opportunity = round(min(100.0, (100 - score) * 0.35 + delta * 1.4 + search_opportunity * 0.28 + stale_bonus), 2)
            if opportunity < 35:
                continue
            rows.append({
                "video_id": str(report.get("video_id") or current.get("video_id") or ""),
                "title": str(current.get("title") or ""),
                "age_days": age,
                "current_score": round(score, 2),
                "projected_gain": round(delta, 2),
                "search_opportunity": round(search_opportunity, 2),
                "catalog_opportunity_score": opportunity,
                "optimization_ready": bool(optimization.get("optimization_ready")),
                "reason": "Vídeo antigo com lacuna mensurável de SEO/pesquisa." if age >= 90 else "Vídeo com lacuna mensurável de SEO/pesquisa.",
            })
        rows.sort(key=lambda row: (-row["catalog_opportunity_score"], -row["age_days"], row["video_id"]))
        return {
            "engine": self.VERSION,
            "uses_external_ai": False,
            "writes_performed": 0,
            "opportunities": rows[:max(1, min(30, int(limit)))],
            "methodology": "Ranks owned videos using current score gap, projected deterministic gain, measured search opportunity and catalog age. No ranking guarantees.",
        }
