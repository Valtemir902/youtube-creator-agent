from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


_PRIORITY_WEIGHT = {"alta": 3, "média": 2, "baixa": 1}


class FreeActionPlanner:
    """Prioritizes grounded channel/video actions without an LLM."""

    VERSION = "free-action-planner-v1"

    def build(
        self,
        *,
        channel_report: dict[str, Any],
        video_reports: list[dict[str, Any]] | None = None,
        max_actions: int = 12,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for rec in channel_report.get("recommendations") or []:
            if not isinstance(rec, dict):
                continue
            priority = str(rec.get("priority") or "média")
            confidence = int(_num(rec.get("confidence"), 60))
            impact = str(rec.get("estimated_impact") or "médio")
            impact_weight = {"alto": 1.0, "médio": 0.7, "baixo": 0.4}.get(impact, 0.6)
            rank_score = round(_PRIORITY_WEIGHT.get(priority, 1) * 30 + confidence * 0.5 + impact_weight * 20)
            rows.append({
                "scope": "channel",
                "video_id": None,
                "code": rec.get("code"),
                "title": rec.get("title"),
                "action": rec.get("action"),
                "why": rec.get("why"),
                "evidence": rec.get("evidence") or {},
                "confidence": confidence,
                "estimated_impact": impact,
                "priority": priority,
                "rank_score": rank_score,
                "optimization_ready": False,
            })

        for report in video_reports or []:
            if not isinstance(report, dict):
                continue
            video_id = str(report.get("video_id") or "")
            optimization = dict(report.get("optimization") or {})
            projected_delta = int(_num(optimization.get("projected_score_delta")))
            overall = int(_num(report.get("overall_score")))
            ready = bool(optimization.get("optimization_ready"))
            base_priority = 3 if overall < 45 else (2 if overall < 65 else 1)
            if ready and projected_delta > 0:
                base_priority = max(base_priority, 3 if projected_delta >= 12 else 2)
            confidence = int(_num(optimization.get("confidence"), _num(report.get("confidence"), 60)))
            rank_score = round(base_priority * 30 + confidence * 0.4 + max(0, min(25, projected_delta)) * 1.2)
            rows.append({
                "scope": "video",
                "video_id": video_id,
                "code": "video_optimization" if ready else "video_review",
                "title": "Otimizar vídeo" if ready else "Revisar vídeo",
                "action": "Revisar a proposta determinística e gerar preview antes de aplicar." if ready else optimization.get("blocked_reason") or "Revisar evidências antes de alterar metadata.",
                "why": f"Score atual {overall}/100; ganho heurístico projetado {projected_delta:+d} pontos.",
                "evidence": {
                    "overall_score": overall,
                    "projected_score": optimization.get("projected_score"),
                    "projected_score_delta": projected_delta,
                    "target_keywords": list(optimization.get("target_keywords") or [])[:5],
                },
                "confidence": confidence,
                "estimated_impact": "alto" if projected_delta >= 12 else ("médio" if projected_delta > 0 else "baixo"),
                "priority": "alta" if base_priority == 3 else ("média" if base_priority == 2 else "baixa"),
                "rank_score": rank_score,
                "optimization_ready": ready,
            })

        rows.sort(key=lambda row: (-int(row["rank_score"]), str(row.get("video_id") or ""), str(row.get("code") or "")))
        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "writes_performed": 0,
            "actions": rows[: max(1, min(30, int(max_actions)))],
            "action_count": min(len(rows), max(1, min(30, int(max_actions)))),
            "requires_explicit_user_confirmation_for_writes": True,
            "methodology": "Actions are ranked from explicit priority, confidence, measured impact and video score gaps. No LLM is used.",
        }
