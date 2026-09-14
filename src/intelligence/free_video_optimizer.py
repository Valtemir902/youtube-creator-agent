from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .free_growth_engine import FreeGrowthEngine, _num, _tokens


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _contains_term(text: str, term: str) -> bool:
    return _compact(term).casefold() in _compact(text).casefold()


def _keyword_score(row: dict[str, Any]) -> float:
    return float(_num(row.get("opportunity_score"), _num(row.get("market_opportunity_score"))))


def _keyword_fit(keyword: str, transcript_tokens: list[str]) -> float:
    kt = _tokens(keyword)
    if not kt or not transcript_tokens:
        return 0.0
    transcript_set = set(transcript_tokens)
    return sum(1 for token in kt if token in transcript_set) / len(kt)


def _accepted_keywords(rows: list[dict[str, Any]], transcript_tokens: list[str], limit: int = 8) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for row in sorted((r for r in rows if isinstance(r, dict)), key=_keyword_score, reverse=True):
        keyword = _compact(row.get("keyword") or row.get("query"))
        if not keyword:
            continue
        fit = _keyword_fit(keyword, transcript_tokens)
        opportunity = _keyword_score(row)
        confidence = float(_num(row.get("confidence"), 70))
        if fit < 0.60 or opportunity < 35 or confidence < 40:
            continue
        normalized = dict(row)
        normalized["keyword"] = keyword
        normalized["semantic_fit"] = round(fit, 4)
        accepted.append(normalized)
        if len(accepted) >= limit:
            break
    return accepted


def _sentence_candidates(transcript: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(transcript or "")).strip()
    if not text:
        return []
    chunks = [part.strip(" -|•") for part in re.split(r"(?<=[.!?])\s+|\s*[\r\n]+\s*", text)]
    chunks = [part for part in chunks if 35 <= len(part) <= 420]
    if chunks:
        return chunks
    return [text[:420]] if len(text) >= 35 else []


def _extract_grounded_excerpt(transcript: str, *, max_chars: int = 520) -> str:
    tokens = _tokens(transcript)
    if not tokens:
        return ""
    common = {token for token, _ in Counter(tokens).most_common(16)}
    ranked: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(_sentence_candidates(transcript)):
        st = _tokens(sentence)
        if not st:
            continue
        relevance = len(common & set(st)) / max(1, len(set(st)))
        ranked.append((relevance, -index, sentence))
    ranked.sort(reverse=True)
    chosen: list[str] = []
    size = 0
    for _, _, sentence in ranked:
        addition = len(sentence) + (1 if chosen else 0)
        if chosen and size + addition > max_chars:
            continue
        chosen.append(sentence)
        size += addition
        if len(chosen) >= 2 or size >= max_chars * 0.72:
            break
    return " ".join(chosen)[:max_chars].strip()


def _title_quality(title: str, transcript_tokens: list[str], keywords: list[str]) -> float:
    title = _compact(title)
    if not title:
        return 0.0
    length = len(title)
    if 42 <= length <= 72:
        length_score = 1.0
    elif 30 <= length <= 90:
        length_score = 0.82
    elif 18 <= length <= 100:
        length_score = 0.55
    else:
        length_score = 0.20
    title_tokens = _tokens(title)
    semantic = _keyword_fit(title, transcript_tokens)
    primary = 1.0 if keywords and _contains_term(title, keywords[0]) else 0.0
    secondary = 0.0
    if len(keywords) > 1:
        secondary = sum(1 for keyword in keywords[1:4] if _contains_term(title, keyword)) / min(3, len(keywords) - 1)
    repeated = max(0, len(title_tokens) - len(set(title_tokens))) / max(1, len(title_tokens))
    return length_score * 35 + semantic * 35 + primary * 22 + secondary * 8 - repeated * 18


def _compose_title(current_title: str, keywords: list[str], transcript_tokens: list[str]) -> tuple[str, list[dict[str, Any]]]:
    current = _compact(current_title)[:100]
    if not keywords:
        return current, []
    primary = keywords[0]
    base = current
    if _contains_term(base, primary):
        candidates = [base]
    else:
        candidates = [base, f"{primary} | {base}", f"{base} | {primary}"]
    clean: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        value = _compact(value)
        if len(value) > 100:
            value = value[:97].rsplit(" ", 1)[0].rstrip(" -|:,.!") + "…"
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            clean.append(value)
    scored = [
        {"title": value, "score": round(_title_quality(value, transcript_tokens, keywords), 2)}
        for value in clean
    ]
    scored.sort(key=lambda row: row["score"], reverse=True)
    winner = str(scored[0]["title"]) if scored else current
    current_score = _title_quality(current, transcript_tokens, keywords)
    winner_score = _title_quality(winner, transcript_tokens, keywords)
    if current and winner_score < current_score + 6:
        winner = current
    return winner, scored[:3]


def _compose_description(current_description: str, transcript: str, keywords: list[str]) -> str:
    current = str(current_description or "").strip()
    excerpt = _extract_grounded_excerpt(transcript)
    if not excerpt:
        return current[:5000]
    current_tokens = _tokens(current)
    excerpt_tokens = _tokens(excerpt)
    if current_tokens and excerpt_tokens:
        overlap = len(set(current_tokens) & set(excerpt_tokens)) / max(1, len(set(excerpt_tokens)))
        if overlap >= 0.55:
            return current[:5000]
    keyword_line = " • ".join(keyword for keyword in keywords[:4] if keyword)
    parts = [excerpt]
    if keyword_line and not all(_contains_term(excerpt, keyword) for keyword in keywords[:2]):
        parts.append(keyword_line)
    if current and current.casefold() not in excerpt.casefold():
        parts.append(current)
    return "\n\n".join(parts)[:5000].rstrip()


def _compose_tags(current_tags: list[str], accepted: list[dict[str, Any]], transcript_tokens: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = _compact(value)
        if not text or len(text) > 100:
            return
        key = text.casefold()
        if key in seen:
            return
        projected = sum(len(item) + 1 for item in output) + len(text) + 1
        if projected > 480 or len(output) >= 12:
            return
        seen.add(key)
        output.append(text)

    for row in accepted:
        add(row.get("keyword"))
    transcript_set = set(transcript_tokens)
    for tag in current_tags:
        tag_tokens = _tokens(tag)
        if tag_tokens and sum(1 for token in tag_tokens if token in transcript_set) / len(tag_tokens) >= 0.60:
            add(tag)
    for token, count in Counter(transcript_tokens).most_common(20):
        if count >= 2:
            add(token)
    return output


class FreeVideoOptimizer:
    """Builds a deterministic, evidence-gated metadata proposal without an LLM.

    It never writes to YouTube. Search-oriented changes are produced only when
    transcript evidence and measured keyword evidence agree semantically.
    """

    VERSION = "free-video-optimizer-v1"

    def build(
        self,
        current: dict[str, Any],
        *,
        transcript: str,
        keyword_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        current = dict(current or {})
        transcript = str(transcript or "").strip()
        transcript_tokens = _tokens(transcript)
        rows = [row for row in (keyword_results or []) if isinstance(row, dict)]
        accepted = _accepted_keywords(rows, transcript_tokens)
        current_normalized = {
            "video_id": str(current.get("video_id") or current.get("id") or ""),
            "title": _compact(current.get("title"))[:100],
            "description": str(current.get("description") or "")[:5000],
            "tags": [str(tag).strip() for tag in (current.get("tags") or []) if str(tag).strip()][:12],
            "categoryId": str(current.get("categoryId") or ""),
            "defaultLanguage": current.get("defaultLanguage"),
        }
        baseline = FreeGrowthEngine().video_report(current_normalized, transcript=transcript, keyword_results=rows)

        blocked_reason = ""
        if len(transcript_tokens) < 40:
            blocked_reason = "Transcrição insuficiente para gerar uma alteração de SEO segura."
        elif not rows:
            blocked_reason = "Nenhuma pesquisa de palavra-chave foi medida; o motor não fará SEO baseado em tendência sem evidência de busca."
        elif not accepted:
            blocked_reason = "As palavras-chave medidas não tiveram aderência semântica suficiente com a transcrição."

        if blocked_reason:
            return {
                "engine": self.VERSION,
                "mode": "deterministic_free",
                "uses_external_ai": False,
                "writes_performed": 0,
                "optimization_ready": False,
                "blocked_reason": blocked_reason,
                "current": current_normalized,
                "proposed": dict(current_normalized),
                "changed": {"title": False, "description": False, "tags": False, "categoryId": False},
                "target_keywords": [],
                "keyword_evidence": accepted,
                "title_candidates": [],
                "baseline_score": baseline.get("overall_score"),
                "projected_score": baseline.get("overall_score"),
                "projected_score_delta": 0,
                "confidence": baseline.get("confidence", 0),
                "category_policy": "preserve_without_high_confidence_classifier",
                "language_policy": "preserve_current_language",
                "requires_explicit_user_confirmation": True,
                "methodology": "No LLM. No optimization proposal is emitted unless transcript and measured search evidence agree.",
            }

        keywords = [str(row["keyword"]) for row in accepted]
        title, title_candidates = _compose_title(current_normalized["title"], keywords, transcript_tokens)
        description = _compose_description(current_normalized["description"], transcript, keywords)
        tags = _compose_tags(current_normalized["tags"], accepted, transcript_tokens)
        proposed = {
            **current_normalized,
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": current_normalized["categoryId"],
            "defaultLanguage": current_normalized["defaultLanguage"],
        }
        projected = FreeGrowthEngine().video_report(proposed, transcript=transcript, keyword_results=accepted)
        changed = {
            key: current_normalized.get(key) != proposed.get(key)
            for key in ("title", "description", "tags", "categoryId")
        }
        score_delta = int(_num(projected.get("overall_score"))) - int(_num(baseline.get("overall_score")))
        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "writes_performed": 0,
            "optimization_ready": any(changed.values()),
            "blocked_reason": "" if any(changed.values()) else "O metadata atual já é competitivo dentro das heurísticas e evidências disponíveis.",
            "current": current_normalized,
            "proposed": proposed,
            "changed": changed,
            "target_keywords": keywords[:8],
            "keyword_evidence": accepted,
            "title_candidates": title_candidates,
            "baseline_score": baseline.get("overall_score"),
            "projected_score": projected.get("overall_score"),
            "projected_score_delta": score_delta,
            "confidence": min(95, int(_num(baseline.get("confidence"), 80))),
            "category_policy": "preserve_without_high_confidence_classifier",
            "language_policy": "preserve_current_language",
            "requires_explicit_user_confirmation": True,
            "methodology": "No LLM. Title, description and tags are derived from current metadata, transcript text and measured YouTube search evidence. Projected score is a product heuristic, not a promise of ranking or views.",
        }
