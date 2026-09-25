from __future__ import annotations

from collections import Counter
from typing import Any

from .free_growth_engine import _tokens


class FreeCategoryClassifier:
    """Suggests a category only when channel evidence reaches strong consensus."""

    VERSION = "free-category-classifier-v1"

    def classify(
        self,
        *,
        current_category_id: str,
        transcript: str,
        peer_videos: list[dict[str, Any]] | None,
        min_peer_count: int = 5,
        min_consensus: float = 0.72,
    ) -> dict[str, Any]:
        current = str(current_category_id or "").strip()
        transcript_tokens = set(_tokens(transcript))
        weighted: Counter[str] = Counter()
        evidence: list[dict[str, Any]] = []
        for video in peer_videos or []:
            if not isinstance(video, dict):
                continue
            category_id = str(video.get("categoryId") or video.get("category_id") or "").strip()
            if not category_id:
                continue
            peer_tokens = set(_tokens(" ".join([str(video.get("title") or ""), str(video.get("description") or "")])))
            if not peer_tokens or not transcript_tokens:
                continue
            overlap = len(peer_tokens & transcript_tokens) / max(1, len(peer_tokens))
            if overlap < 0.18:
                continue
            weight = 1 + min(4, int(overlap * 10))
            weighted[category_id] += weight
            evidence.append({"video_id": str(video.get("id") or video.get("video_id") or ""), "categoryId": category_id, "semantic_overlap": round(overlap, 4), "weight": weight})
        if len(evidence) < min_peer_count or not weighted:
            return {
                "engine": self.VERSION,
                "suggestion_ready": False,
                "current_category_id": current,
                "suggested_category_id": current,
                "confidence": 0,
                "blocked_reason": "Poucos vídeos semanticamente semelhantes para classificar categoria com segurança.",
                "evidence": evidence,
                "writes_performed": 0,
            }
        category_id, best_weight = weighted.most_common(1)[0]
        total_weight = sum(weighted.values())
        consensus = best_weight / max(total_weight, 1)
        confidence = round(consensus * 100)
        ready = category_id != current and consensus >= min_consensus
        return {
            "engine": self.VERSION,
            "suggestion_ready": ready,
            "current_category_id": current,
            "suggested_category_id": category_id if ready else current,
            "confidence": confidence,
            "consensus": round(consensus, 4),
            "blocked_reason": "" if ready else ("A categoria atual já coincide com o consenso dos pares." if category_id == current else "O consenso entre vídeos semelhantes não atingiu o limiar de segurança."),
            "distribution": dict(weighted),
            "evidence": evidence[:20],
            "writes_performed": 0,
            "requires_explicit_user_confirmation": True,
            "methodology": "No LLM. Category changes are suggested only from semantically similar owned videos with strong weighted category consensus.",
        }
