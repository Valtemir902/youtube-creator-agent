from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ai.runtime import AIRuntime
from .channel_learning import ChannelLearningEngine, ChannelProfile, ChannelSnapshotStore
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
    channel_fit: int
    personalized_score: int
    title_ideas: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class StrategyReport:
    seed: str
    opportunities: tuple[StrategyOpportunity, ...]
    rejected_queries: tuple[str, ...]
    channel_profile: ChannelProfile | None = None


class StrategyEngine:
    """Turns a broad seed into measured, channel-specific opportunities."""

    def __init__(
        self,
        token_file: str,
        ai_runtime: AIRuntime,
        snapshot_db: str | Path | None = None,
        *,
        youtube_client=None,
        analytics_client=None,
    ):
        self.token_file = token_file
        self.research = YouTubeResearchEngine(token_file, youtube_client=youtube_client)
        self.ai_runtime = ai_runtime
        self.channel_learning = ChannelLearningEngine(
            token_file,
            youtube_client=youtube_client,
            analytics_client=analytics_client,
        )
        if snapshot_db is None:
            snapshot_db = Path(token_file).with_name("channel_intelligence.sqlite3")
        self.snapshot_store = ChannelSnapshotStore(snapshot_db)

    def _load_channel_profile(self) -> ChannelProfile | None:
        try:
            profile = self.channel_learning.collect(period_days=28, max_videos=50)
            self.snapshot_store.save(profile)
            return profile
        except Exception:
            return None

    def _candidate_queries(self, seed: str, profile: ChannelProfile | None, limit: int = 8) -> list[str]:
        context = {}
        if profile is not None:
            context = {
                "top_search_terms": [{"term": item.term, "views": item.views} for item in profile.top_search_terms[:12]],
                "top_topics": list(profile.topic_terms[:15]),
                "top_videos": [item.title for item in profile.top_videos[:8]],
                "shorts_share": profile.shorts_share_of_recent_views,
                "long_share": profile.long_share_of_recent_views,
            }
        response = self.ai_runtime.generate(
            [
                {"role": "system", "content": (
                    "Você cria somente hipóteses de consultas para serem verificadas depois. "
                    "Não alegue que uma consulta está em alta. Preserve o assunto e use o histórico do canal "
                    "apenas para gerar hipóteses plausíveis. Retorne JSON válido."
                )},
                {"role": "user", "content": (
                    f"Assunto base: {seed}\nContexto real do canal: {json.dumps(context, ensure_ascii=False)}\n"
                    f"Crie até {limit} consultas naturais que pessoas poderiam digitar no YouTube. "
                    "Misture intenção informativa, curiosidade legítima, problema/solução e cauda longa. "
                    "Inclua oportunidades adjacentes aos termos que já trazem tráfego ao canal, sem sair do assunto. "
                    "Não use clickbait falso. Retorne: {\"queries\":[\"...\"]}"
                )},
            ], temperature=0.25, response_format="json",
        )
        payload = _parse_json(response.text)
        raw = payload.get("queries", [])
        candidates = [seed.strip()]
        seen = {seed.strip().casefold()}
        if profile is not None:
            for signal in profile.top_search_terms[:5]:
                term = signal.term.strip()
                if term and seed.casefold() in term.casefold() and term.casefold() not in seen:
                    candidates.append(term); seen.add(term.casefold())
        for value in raw:
            q = str(value).strip()
            if q and q.casefold() not in seen:
                candidates.append(q); seen.add(q.casefold())
        return candidates[: limit + 3]

    @staticmethod
    def _personalized_score(result: KeywordResearchResult, fit: float) -> int:
        market = result.opportunity.score / 100.0
        demand = result.estimated_daily_demand_index / 100.0
        competition = result.opportunity.competition_score / 100.0
        freshness = min(1.0, result.fresh_7d_rate * 0.45 + result.fresh_30d_rate * 0.35 + result.fresh_90d_rate * 0.20)
        score = market * 0.36 + fit * 0.28 + demand * 0.16 + competition * 0.12 + freshness * 0.08
        return round(max(0.0, min(1.0, score)) * 100)

    def _title_ideas(self, seed: str, result: KeywordResearchResult, profile: ChannelProfile | None) -> tuple[str, ...]:
        evidence = {
            "keyword_validada": result.query,
            "demanda_indice": result.estimated_daily_demand_index,
            "concorrencia": result.competition_label,
            "fresh_7d": result.fresh_7d_rate,
            "fresh_30d": result.fresh_30d_rate,
            "views_dia_mediana": result.median_views_per_day,
            "titulos_reais_mercado": [item.title for item in result.evidence[:8]],
            "titulos_do_proprio_canal_que_performaram": [item.title for item in profile.top_videos[:6]] if profile else [],
            "termos_reais_de_busca_do_canal": [item.term for item in profile.top_search_terms[:10]] if profile else [],
        }
        response = self.ai_runtime.generate(
            [
                {"role": "system", "content": (
                    "Você escreve títulos de YouTube claros e persuasivos usando somente a evidência fornecida. "
                    "Não copie títulos existentes, não invente números, resultados ou promessas. "
                    "Use padrões de linguagem que já funcionaram no próprio canal quando forem semanticamente adequados. "
                    "Priorize clareza, benefício, curiosidade legítima e correspondência com a busca. Retorne JSON."
                )},
                {"role": "user", "content": (
                    f"Assunto: {seed}\nEvidência:\n{json.dumps(evidence, ensure_ascii=False)}\n"
                    "Crie 5 títulos diferentes, até 72 caracteres quando possível. Retorne {\"titles\":[\"...\"]}."
                )},
            ], temperature=0.32, response_format="json",
        )
        payload = _parse_json(response.text)
        return tuple(str(x).strip() for x in payload.get("titles", []) if str(x).strip())[:5]

    def build_report(self, seed: str, candidate_limit: int = 8) -> StrategyReport:
        seed = seed.strip()
        if len(seed) < 2:
            raise ValueError("Informe um nicho, assunto ou consulta válida.")
        profile = self._load_channel_profile()
        candidates = self._candidate_queries(seed, profile, candidate_limit)
        measured = []; rejected = []
        for query in candidates:
            result = self.research.research(query, 20)
            if result.result_count < 10 or result.opportunity.confidence < 60:
                rejected.append(query); continue
            fit = profile.channel_fit(query) if profile is not None else 0.5
            measured.append((result, fit, self._personalized_score(result, fit)))
        measured.sort(key=lambda item: (item[2], item[0].opportunity.score, item[0].estimated_daily_demand_index, item[0].opportunity.competition_score, item[0].fresh_30d_rate), reverse=True)
        opportunities = []
        for result, fit, personal in measured[:6]:
            reasons = list(result.opportunity.reasons)
            rationale_parts = [f"aderência ao seu canal {round(fit*100)}/100", f"score personalizado {personal}/100"]
            rationale_parts.extend(reasons or [f"demanda {result.demand_label}, concorrência {result.competition_label}, {result.fresh_30d_rate:.0%} dos resultados com até 30 dias"])
            opportunities.append(StrategyOpportunity(result.query, result, round(fit*100), personal, self._title_ideas(seed, result, profile), "; ".join(rationale_parts)))
        return StrategyReport(seed, tuple(opportunities), tuple(rejected), profile)
