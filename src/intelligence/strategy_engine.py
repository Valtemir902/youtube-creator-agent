from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable

from ai.runtime import AIRuntime
from .youtube_research import KeywordResearchResult, YouTubeResearchEngine


def _parse_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I | re.S).strip()
    return json.loads(clean)


@dataclass(frozen=True)
class StrategyOpportunity:
    keyword: str
    research: KeywordResearchResult
    title_ideas: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class StrategyReport:
    seed: str
    opportunities: tuple[StrategyOpportunity, ...]
    rejected_queries: tuple[str, ...]


class StrategyEngine:
    """Turns a broad seed into measured opportunities.

    The LLM may propose candidate queries, but no candidate is exposed as an
    opportunity until it is checked against observable YouTube data.
    """

    def __init__(self, token_file: str, ai_runtime: AIRuntime):
        self.research = YouTubeResearchEngine(token_file)
        self.ai_runtime = ai_runtime

    def _candidate_queries(self, seed: str, limit: int = 8) -> list[str]:
        response = self.ai_runtime.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "Você cria somente hipóteses de consultas para serem verificadas depois. "
                        "Não diga que estão em alta. Preserve o assunto e a intenção do usuário. "
                        "Retorne JSON válido."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Assunto base: {seed}\n"
                        f"Crie até {limit} consultas naturais que pessoas poderiam digitar no YouTube, "
                        "misturando intenção informativa, curiosidade e problema/solução. "
                        "Não use clickbait falso. Retorne: {\"queries\":[\"...\"]}"
                    ),
                },
            ],
            temperature=0.25,
            response_format="json",
        )
        payload = _parse_json(response.text)
        raw = payload.get("queries", [])
        candidates = [seed.strip()]
        for value in raw:
            q = str(value).strip()
            if q and q.casefold() not in {x.casefold() for x in candidates}:
                candidates.append(q)
        return candidates[: limit + 1]

    def _title_ideas(self, seed: str, result: KeywordResearchResult) -> tuple[str, ...]:
        top_titles = [item.title for item in result.evidence[:8]]
        evidence = {
            "keyword_validada": result.query,
            "demanda_indice": result.estimated_daily_demand_index,
            "concorrencia": result.competition_label,
            "fresh_7d": result.fresh_7d_rate,
            "fresh_30d": result.fresh_30d_rate,
            "views_dia_mediana": result.median_views_per_day,
            "titulos_reais_que_estao_performando": top_titles,
        }
        response = self.ai_runtime.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "Você escreve títulos de YouTube claros e persuasivos. Use somente a evidência fornecida. "
                        "Não copie títulos existentes, não invente números, resultados ou promessas. "
                        "Priorize clareza, benefício, curiosidade legítima e correspondência com a busca. Retorne JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Assunto: {seed}\nEvidência:\n{json.dumps(evidence, ensure_ascii=False)}\n"
                        "Crie 5 títulos diferentes, até 72 caracteres quando possível. "
                        "Retorne {\"titles\":[\"...\"]}."
                    ),
                },
            ],
            temperature=0.35,
            response_format="json",
        )
        payload = _parse_json(response.text)
        titles = [str(x).strip() for x in payload.get("titles", []) if str(x).strip()]
        return tuple(titles[:5])

    def build_report(self, seed: str, candidate_limit: int = 8) -> StrategyReport:
        seed = seed.strip()
        if len(seed) < 2:
            raise ValueError("Informe um nicho, assunto ou consulta válida.")
        candidates = self._candidate_queries(seed, candidate_limit)
        measured: list[KeywordResearchResult] = []
        rejected: list[str] = []
        for query in candidates:
            result = self.research.research(query, 20)
            if result.result_count < 10 or result.opportunity.confidence < 60:
                rejected.append(query)
                continue
            measured.append(result)

        measured.sort(
            key=lambda r: (
                r.opportunity.score,
                r.estimated_daily_demand_index,
                r.opportunity.competition_score,
                r.fresh_30d_rate,
            ),
            reverse=True,
        )
        opportunities: list[StrategyOpportunity] = []
        for result in measured[:6]:
            reasons = list(result.opportunity.reasons)
            rationale = "; ".join(reasons) if reasons else (
                f"demanda {result.demand_label}, concorrência {result.competition_label}, "
                f"{result.fresh_30d_rate:.0%} dos resultados com até 30 dias"
            )
            opportunities.append(
                StrategyOpportunity(
                    keyword=result.query,
                    research=result,
                    title_ideas=self._title_ideas(seed, result),
                    rationale=rationale,
                )
            )
        return StrategyReport(seed=seed, opportunities=tuple(opportunities), rejected_queries=tuple(rejected))
