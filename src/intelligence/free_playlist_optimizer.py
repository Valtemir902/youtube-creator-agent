from __future__ import annotations

from collections import Counter
from typing import Any

from .free_growth_engine import _num, _tokens


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


class FreePlaylistOptimizer:
    VERSION = "free-playlist-optimizer-v1"

    def build(self, current: dict[str, Any], *, member_videos: list[dict[str, Any]] | None = None, keyword_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        current = dict(current or {})
        videos = [row for row in (member_videos or []) if isinstance(row, dict)]
        corpus = " ".join(" ".join([str(row.get("title") or ""), str(row.get("description") or "")]) for row in videos)
        tokens = _tokens(corpus)
        counts = Counter(tokens)
        core_terms = [term for term, count in counts.most_common(12) if count >= max(2, round(len(videos) * 0.2))]
        accepted = []
        core_set = set(tokens)
        for row in keyword_results or []:
            if not isinstance(row, dict):
                continue
            keyword = _compact(row.get("keyword") or row.get("query"))
            kt = _tokens(keyword)
            if not keyword or not kt:
                continue
            fit = sum(1 for token in kt if token in core_set) / len(kt)
            opportunity = _num(row.get("opportunity_score"), _num(row.get("market_opportunity_score")))
            confidence = _num(row.get("confidence"), 50)
            if fit >= 0.60 and opportunity >= 35 and confidence >= 40:
                accepted.append({**row, "keyword": keyword, "semantic_fit": round(fit * 100, 2)})
        accepted.sort(key=lambda row: (_num(row.get("opportunity_score"), _num(row.get("market_opportunity_score"))), _num(row.get("confidence"))), reverse=True)

        outliers = []
        core_reference = set(core_terms[:8])
        if core_reference:
            for row in videos:
                vt = set(_tokens(str(row.get("title") or "")))
                fit = len(vt & core_reference) / max(1, len(vt)) if vt else 0.0
                if fit < 0.12:
                    outliers.append({"video_id": str(row.get("video_id") or row.get("id") or ""), "title": str(row.get("title") or ""), "core_fit": round(fit * 100, 2)})

        title = _compact(current.get("title"))[:150]
        description = str(current.get("description") or "")[:5000]
        blocked = ""
        if len(videos) < 2:
            blocked = "Playlist com poucos vídeos para inferir um núcleo temático confiável."
        elif len(core_terms) < 2:
            blocked = "Os vídeos da playlist não formam um núcleo temático suficientemente claro."

        proposed_description = description
        if not blocked and len(description.strip()) < 120:
            phrases = [str(row.get("keyword")) for row in accepted[:3]] or core_terms[:5]
            examples = [str(row.get("title") or "").strip() for row in videos[:3] if str(row.get("title") or "").strip()]
            proposed_description = (
                f"Playlist sobre {', '.join(phrases)}. "
                + (f"Inclui conteúdos como: {'; '.join(examples)}." if examples else "")
            )[:1000].strip()

        proposed = {"playlist_id": str(current.get("playlist_id") or current.get("id") or ""), "title": title, "description": proposed_description, "privacy_status": current.get("privacy_status")}
        normalized = {"playlist_id": proposed["playlist_id"], "title": title, "description": description, "privacy_status": current.get("privacy_status")}
        changed = {key: proposed.get(key) != normalized.get(key) for key in ("title", "description", "privacy_status")}
        coherence = 0.0
        if videos and core_reference:
            fits = []
            for row in videos:
                vt = set(_tokens(str(row.get("title") or "")))
                fits.append(len(vt & core_reference) / max(1, len(vt)) if vt else 0.0)
            coherence = sum(fits) / len(fits)
        confidence = min(95, round(35 + min(30, len(videos) * 4) + min(30, len(core_terms) * 4)))
        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "writes_performed": 0,
            "optimization_ready": not blocked and any(changed.values()),
            "blocked_reason": blocked,
            "current": normalized,
            "proposed": proposed if not blocked else normalized,
            "changed": changed if not blocked else {key: False for key in changed},
            "member_count_analyzed": len(videos),
            "coherence_score": round(coherence * 100, 2),
            "core_terms": core_terms,
            "target_keywords": [row["keyword"] for row in accepted[:8]],
            "keyword_evidence": accepted[:8],
            "outlier_videos": outliers[:10],
            "confidence": confidence,
            "title_policy": "preserve_existing_title_without_strong_phrase_level_evidence",
            "privacy_policy": "preserve_existing_privacy",
            "requires_explicit_user_confirmation": True,
            "methodology": "No LLM. Playlist coherence and metadata proposal derive from owned member-video metadata plus measured keyword evidence. Title and privacy are preserved conservatively.",
        }
