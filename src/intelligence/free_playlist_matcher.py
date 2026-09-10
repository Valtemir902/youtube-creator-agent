from __future__ import annotations

from typing import Any

from .free_growth_engine import _tokens


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _coverage(query_tokens: list[str], content_tokens: set[str]) -> float:
    unique = set(query_tokens)
    if not unique:
        return 0.0
    return len(unique & content_tokens) / len(unique)


class FreePlaylistMatcher:
    """Ranks existing playlists against real video content without an LLM."""

    VERSION = "free-playlist-matcher-v1"

    def match(
        self,
        *,
        title: str,
        transcript: str,
        playlists: list[dict[str, Any]] | None,
        limit: int = 3,
    ) -> dict[str, Any]:
        title_tokens = _tokens(title)
        transcript_tokens = _tokens(transcript)
        content = set(title_tokens + transcript_tokens)
        rows: list[dict[str, Any]] = []
        for playlist in playlists or []:
            if not isinstance(playlist, dict):
                continue
            name = _clean(playlist.get("title"))
            description = _clean(playlist.get("description"))
            p_title = _tokens(name)
            p_desc = _tokens(description)[:30]
            if not p_title:
                continue
            title_coverage = _coverage(p_title, content)
            description_coverage = _coverage(p_desc, content) if p_desc else 0.0
            video_title_fit = _coverage(p_title, set(title_tokens)) if title_tokens else 0.0
            score = round((title_coverage * 0.62 + description_coverage * 0.18 + video_title_fit * 0.20) * 100)
            if score < 38 or title_coverage < 0.50:
                continue
            rows.append({
                "playlist_id": str(playlist.get("id") or ""),
                "title": name,
                "score": score,
                "title_coverage": round(title_coverage, 4),
                "description_coverage": round(description_coverage, 4),
                "video_title_fit": round(video_title_fit, 4),
                "privacy_status": playlist.get("privacy_status"),
                "item_count": playlist.get("count"),
                "evidence": {
                    "playlist_terms": p_title[:12],
                    "matched_terms": sorted(set(p_title) & content),
                },
            })
        rows.sort(key=lambda row: (-row["score"], row["title"].casefold(), row["playlist_id"]))
        top = rows[: max(1, min(5, int(limit)))]
        winner = top[0] if top and top[0]["score"] >= 52 else None
        return {
            "engine": self.VERSION,
            "uses_external_ai": False,
            "writes_performed": 0,
            "recommended_playlist": winner,
            "candidates": top,
            "recommendation_ready": winner is not None,
            "requires_explicit_user_confirmation": True,
            "methodology": "Existing playlist title/description terms are matched against the real video title and transcript. No playlist is created or modified automatically.",
        }
