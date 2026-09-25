from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .free_growth_engine import _num, _tokens


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _tail_class(keyword: str) -> str:
    count = len(_tokens(keyword))
    if count <= 1:
        return "short_tail"
    if count == 2:
        return "mid_tail"
    return "long_tail"


def _fit(keyword: str, source_tokens: list[str]) -> float:
    kt = _tokens(keyword)
    if not kt or not source_tokens:
        return 0.0
    source = set(source_tokens)
    return sum(1 for token in kt if token in source) / len(kt)


def _intent(keyword: str) -> str:
    text = _compact(keyword).casefold()
    patterns = {
        "how_to": ("como ", "tutorial", "passo a passo", "como fazer", "how to"),
        "comparison": (" vs ", "versus", "melhor", "comparativo", "review", "vale a pena"),
        "problem_solution": ("erro", "problema", "resolver", "consertar", "não funciona", "nao funciona"),
        "transactional": ("comprar", "preço", "preco", "barato", "desconto", "onde comprar"),
        "freshness": ("hoje", "agora", "2026", "novo", "novidade", "atualizado"),
    }
    for label, needles in patterns.items():
        if any(needle in text for needle in needles):
            return label
    return "informational"


def _risk_flags(keyword: str, source_tokens: list[str], row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    fit = _fit(keyword, source_tokens)
    competition = float(_num(row.get("competition_score")))
    confidence = float(_num(row.get("confidence")))
    demand = float(_num(row.get("demand_index")))
    if fit < 0.50:
        flags.append("low_content_fit")
    if competition >= 85 and demand < 65:
        flags.append("high_competition_low_demand")
    if confidence < 45:
        flags.append("low_measurement_confidence")
    if len(_tokens(keyword)) <= 1 and competition >= 75:
        flags.append("generic_short_tail")
    return flags


class FreeKeywordIntelligence:
    """Deterministic keyword classifier built only from measured search rows.

    It does not claim exact YouTube search volume. Demand, competition and trend
    scores are normalized product indices derived from observed search results.
    """

    VERSION = "free-keyword-intelligence-v1"

    def analyze(
        self,
        rows: list[dict[str, Any]],
        *,
        source_text: str = "",
        current_title: str = "",
        current_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        source_tokens = _tokens(source_text)
        title_tokens = _tokens(current_title)
        tag_tokens = _tokens(" ".join(str(x) for x in (current_tags or [])))
        context_tokens = source_tokens or (title_tokens + tag_tokens)
        normalized: list[dict[str, Any]] = []

        for raw in rows:
            if not isinstance(raw, dict):
                continue
            keyword = _compact(raw.get("keyword") or raw.get("query"))
            if not keyword:
                continue
            demand = max(0.0, min(100.0, float(_num(raw.get("demand_index")))))
            competition = max(0.0, min(100.0, float(_num(raw.get("competition_score")))))
            opportunity = max(0.0, min(100.0, float(_num(raw.get("opportunity_score"), _num(raw.get("personalized_opportunity_score"), _num(raw.get("market_opportunity_score")))))))
            confidence = max(0.0, min(100.0, float(_num(raw.get("confidence"), 50))))
            fresh7 = max(0.0, min(1.0, float(_num(raw.get("fresh_7d_rate")))))
            fresh30 = max(0.0, min(1.0, float(_num(raw.get("fresh_30d_rate")))))
            fresh90 = max(0.0, min(1.0, float(_num(raw.get("fresh_90d_rate")))))
            velocity = max(0.0, float(_num(raw.get("median_views_per_day"))))
            breakout = max(0.0, min(1.0, float(_num(raw.get("small_channel_breakout_rate")))))
            fit = _fit(keyword, context_tokens)
            trend_score = min(100.0, round(fresh7 * 42 + fresh30 * 28 + fresh90 * 10 + min(1.0, math.log1p(velocity) / math.log1p(10000)) * 15 + breakout * 5, 2))
            fit_score = round(fit * 100, 2)
            weighted = round(opportunity * 0.34 + demand * 0.18 + (100 - competition) * 0.13 + fit_score * 0.20 + confidence * 0.10 + trend_score * 0.05, 2)
            risks = _risk_flags(keyword, context_tokens, raw)
            positive = fit >= 0.60 and confidence >= 50 and opportunity >= 35 and "high_competition_low_demand" not in risks
            normalized.append({
                **raw,
                "keyword": keyword,
                "tail": _tail_class(keyword),
                "intent": _intent(keyword),
                "semantic_fit": fit_score,
                "trend_index": trend_score,
                "decision_score": weighted,
                "classification": "positive" if positive else "negative_or_avoid",
                "risk_flags": risks,
                "evidence_complete": bool(raw.get("evidence")) and confidence >= 40,
            })

        normalized.sort(key=lambda row: (row["decision_score"], row.get("confidence", 0)), reverse=True)
        positives = [row for row in normalized if row["classification"] == "positive"]
        negatives = [row for row in normalized if row["classification"] != "positive"]
        tails = Counter(row["tail"] for row in positives)
        intents = Counter(row["intent"] for row in positives)

        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "writes_performed": 0,
            "exact_search_volume_available": False,
            "demand_metric": "normalized_observed_search_index",
            "competition_metric": "normalized_observed_result_competition",
            "keywords_evaluated": len(normalized),
            "positive_keywords": positives[:20],
            "negative_keywords": negatives[:20],
            "tail_distribution": {
                "short_tail": tails.get("short_tail", 0),
                "mid_tail": tails.get("mid_tail", 0),
                "long_tail": tails.get("long_tail", 0),
            },
            "intent_distribution": dict(intents),
            "charts": {
                "demand_vs_competition": [
                    {
                        "keyword": row["keyword"],
                        "demand": round(float(_num(row.get("demand_index"))), 2),
                        "competition": round(float(_num(row.get("competition_score"))), 2),
                        "opportunity": round(float(_num(row.get("opportunity_score"), _num(row.get("personalized_opportunity_score"), _num(row.get("market_opportunity_score"))))), 2),
                        "trend": row["trend_index"],
                        "fit": row["semantic_fit"],
                    }
                    for row in normalized[:20]
                ]
            },
            "methodology": (
                "No LLM. Every keyword must originate from measured YouTube search evidence supplied by the caller. "
                "Demand and competition are normalized observed indices, never presented as exact monthly search volume."
            ),
        }
