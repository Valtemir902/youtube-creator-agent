from __future__ import annotations

from collections import Counter
from typing import Any

from .free_growth_engine import _tokens


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _dedupe(values: list[str], limit: int = 12) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _compact(raw)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= limit:
            break
    return out


class FreeChannelOptimizer:
    """Deterministic channel-profile optimizer with conservative write policy.

    The engine proposes only text changes supported by observed channel topics or
    search terms. It never writes and it preserves fields it cannot infer safely.
    """

    VERSION = "free-channel-optimizer-v1"

    def build(self, current: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        current = dict(current or {})
        profile = dict(profile or {})
        title = _compact(current.get("title") or profile.get("channel_title"))
        description = str(current.get("description") or "").strip()
        keywords = _compact(current.get("keywords"))
        country = current.get("country")
        default_language = current.get("default_language") or current.get("defaultLanguage")

        topic_terms = _dedupe([str(x) for x in (profile.get("topic_terms") or []) if str(x).strip()], 12)
        search_terms = []
        for item in profile.get("top_search_terms") or []:
            if isinstance(item, dict):
                term = _compact(item.get("term") or item.get("query") or item.get("keyword"))
                if term:
                    search_terms.append(term)
        search_terms = _dedupe(search_terms, 10)
        evidence_terms = _dedupe(topic_terms + search_terms, 12)

        confidence_components = [bool(title), bool(topic_terms), bool(search_terms), bool(profile.get("video_count"))]
        confidence = round(sum(confidence_components) / len(confidence_components) * 100)
        blocked_reason = ""
        if len(evidence_terms) < 3:
            blocked_reason = "Há poucos sinais temáticos reais para propor alteração segura do perfil."

        proposed_description = description
        if not blocked_reason and len(description) < 120:
            topic_phrase = ", ".join(evidence_terms[:6])
            proposed_description = (
                f"{title} publica conteúdo sobre {topic_phrase}. "
                "Acompanhe os vídeos e playlists do canal para conteúdos relacionados a esses temas."
            )[:1000]

        proposed_keywords = keywords
        if not blocked_reason:
            proposed_keywords = ", ".join(evidence_terms[:10])[:500]

        proposed = {
            "title": title,
            "description": proposed_description,
            "keywords": proposed_keywords,
            "country": country,
            "default_language": default_language,
        }
        current_normalized = {
            "title": title,
            "description": description,
            "keywords": keywords,
            "country": country,
            "default_language": default_language,
        }
        changed = {key: current_normalized.get(key) != proposed.get(key) for key in proposed}
        recommendations = []
        if len(description) < 120:
            recommendations.append({
                "code": "thin_channel_description",
                "priority": "alta",
                "title": "Fortalecer a descrição do canal",
                "why": "A descrição atual oferece pouco contexto temático.",
                "evidence": {"description_length": len(description), "topic_terms": evidence_terms[:8]},
                "confidence": confidence,
            })
        if evidence_terms and proposed_keywords != keywords:
            recommendations.append({
                "code": "channel_keywords_alignment",
                "priority": "média",
                "title": "Alinhar palavras-chave do canal aos temas observados",
                "why": "Os termos propostos vêm do conteúdo e das consultas observadas no próprio canal.",
                "evidence": {"terms": evidence_terms[:10]},
                "confidence": confidence,
            })

        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "writes_performed": 0,
            "optimization_ready": not blocked_reason and any(changed.values()),
            "blocked_reason": blocked_reason,
            "current": current_normalized,
            "proposed": proposed if not blocked_reason else current_normalized,
            "changed": changed if not blocked_reason else {key: False for key in changed},
            "confidence": confidence,
            "evidence_terms": evidence_terms,
            "recommendations": recommendations,
            "preserved_fields": ["country", "default_language"],
            "requires_explicit_user_confirmation": True,
            "methodology": (
                "No LLM. Profile suggestions are derived only from existing channel metadata, "
                "observed topic terms and real channel search terms. Country and language are preserved."
            ),
        }
