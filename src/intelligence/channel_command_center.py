from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from ai.runtime import AIRuntime
from .channel_audit import ChannelAuditEngine
from .channel_learning import ChannelLearningEngine, ChannelProfile
from .youtube_research import KeywordResearchResult, YouTubeResearchEngine


def _parse_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I | re.S).strip()
    return json.loads(clean)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> int:
    return round(max(low, min(high, value)))


@dataclass(frozen=True)
class ValidatedPlanOpportunity:
    keyword: str
    score: int
    confidence: int
    demand_index: int
    competition_label: str
    channel_fit: int
    fresh_30d_rate: float
    views_per_day: float
    recommended_format: str
    evidence_titles: tuple[str, ...]


@dataclass(frozen=True)
class EditorialAction:
    priority: int
    day_slot: str
    format: str
    keyword: str
    working_title: str
    objective: str
    evidence_reason: str
    opportunity_score: int
    confidence: int


@dataclass(frozen=True)
class CommandCenterReport:
    measured_at: str
    channel_title: str
    health_score: int
    health_label: str
    search_share: float
    shorts_share: float
    long_share: float
    dominant_format: str
    top_search_terms: tuple[dict, ...]
    top_videos: tuple[dict, ...]
    weak_videos: tuple[dict, ...]
    topic_terms: tuple[str, ...]
    opportunities: tuple[ValidatedPlanOpportunity, ...]
    editorial_plan: tuple[EditorialAction, ...]
    audit: dict
    warnings: tuple[str, ...]


class ChannelCommandCenterEngine:
    """Builds an actionable channel strategy from measured YouTube evidence.

    Raw YouTube/Analytics metrics are collected first. AI may propose candidate
    topics and wording, but candidates must be validated against YouTube result
    data before they can appear in the final editorial plan.
    """

    def __init__(self, token_file: str, ai_runtime: AIRuntime):
        self.token_file = token_file
        self.ai_runtime = ai_runtime
        self.learning = ChannelLearningEngine(token_file)
        self.research = YouTubeResearchEngine(token_file)
        self.audit_engine = ChannelAuditEngine(token_file, ai_runtime)

    @staticmethod
    def _health(profile: ChannelProfile) -> tuple[int, str]:
        videos = list(profile.top_videos)
        if not videos:
            return 20, "dados insuficientes"
        active = sum(1 for video in videos if getattr(video, "views", 0) > 0)
        engagement_values = [float(getattr(v, "engagement_rate", 0.0) or 0.0) for v in videos]
        avg_engagement = sum(engagement_values) / max(1, len(engagement_values))
        search_signal = min(1.0, max(0.0, float(profile.search_share or 0.0)))
        active_signal = active / max(1, len(videos))
        engagement_signal = min(1.0, avg_engagement / 0.06)
        score = _clamp((active_signal * 0.40 + engagement_signal * 0.35 + search_signal * 0.25) * 100)
        if score >= 75:
            label = "forte"
        elif score >= 50:
            label = "saudável com oportunidades"
        elif score >= 30:
            label = "atenção"
        else:
            label = "crítico ou pouco dado recente"
        return score, label

    @staticmethod
    def _dominant_format(profile: ChannelProfile) -> str:
        shorts = float(profile.shorts_share_of_recent_views or 0.0)
        longs = float(profile.long_share_of_recent_views or 0.0)
        if shorts >= longs + 0.15:
            return "Shorts"
        if longs >= shorts + 0.15:
            return "Vídeo longo"
        return "Misto"

    def _candidate_queries(self, profile: ChannelProfile, limit: int = 8) -> list[str]:
        real_terms = [item.term for item in profile.top_search_terms[:12] if getattr(item, "term", "")]
        topic_terms = list(profile.topic_terms[:15])
        context = {
            "channel_title": profile.channel_title,
            "real_search_terms": real_terms,
            "topic_terms": topic_terms,
            "dominant_format": self._dominant_format(profile),
            "top_video_titles": [video.title for video in profile.top_videos[:8]],
        }
        response = self.ai_runtime.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "Você propõe hipóteses de pauta para um canal do YouTube. "
                        "Use apenas o histórico fornecido. Não alegue que algo está em alta. "
                        "As hipóteses serão validadas depois em dados reais. Retorne JSON válido."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"PERFIL REAL DO CANAL:\n{json.dumps(context, ensure_ascii=False)}\n\n"
                        f"Crie até {limit} consultas de pesquisa naturais e específicas que expandam temas já comprovados no canal, "
                        "incluindo caudas longas úteis. Evite duplicatas e clickbait falso. "
                        "Retorne {\"queries\":[\"...\"]}."
                    ),
                },
            ],
            temperature=0.2,
            response_format="json",
        )
        payload = _parse_json(response.text)
        candidates: list[str] = []
        for value in real_terms[:4] + list(payload.get("queries", [])):
            query = str(value).strip()
            if len(query) < 3:
                continue
            if query.casefold() not in {item.casefold() for item in candidates}:
                candidates.append(query)
        return candidates[:limit]

    def _validate_opportunities(self, profile: ChannelProfile) -> list[ValidatedPlanOpportunity]:
        results: list[tuple[KeywordResearchResult, int]] = []
        for query in self._candidate_queries(profile):
            try:
                measured = self.research.research(query, 20)
            except Exception:
                continue
            fit = self.learning.channel_fit(query, profile)
            if measured.result_count < 10 or measured.opportunity.confidence < 60:
                continue
            personalized = _clamp(measured.opportunity.score * 0.72 + fit * 28.0)
            results.append((measured, personalized))

        results.sort(
            key=lambda pair: (
                pair[1],
                pair[0].estimated_daily_demand_index,
                pair[0].opportunity.competition_score,
                pair[0].fresh_30d_rate,
            ),
            reverse=True,
        )
        dominant = self._dominant_format(profile)
        output: list[ValidatedPlanOpportunity] = []
        for measured, score in results[:6]:
            fit = _clamp(self.learning.channel_fit(measured.query, profile) * 100)
            if dominant == "Misto":
                recommended_format = "Shorts" if measured.fresh_7d_rate >= 0.35 else "Vídeo longo"
            else:
                recommended_format = dominant
            output.append(
                ValidatedPlanOpportunity(
                    keyword=measured.query,
                    score=score,
                    confidence=measured.opportunity.confidence,
                    demand_index=measured.estimated_daily_demand_index,
                    competition_label=measured.competition_label,
                    channel_fit=fit,
                    fresh_30d_rate=measured.fresh_30d_rate,
                    views_per_day=measured.median_views_per_day,
                    recommended_format=recommended_format,
                    evidence_titles=tuple(video.title for video in measured.evidence[:5]),
                )
            )
        return output

    def _editorial_plan(self, profile: ChannelProfile, opportunities: list[ValidatedPlanOpportunity]) -> list[EditorialAction]:
        if not opportunities:
            return []
        evidence = [asdict(item) for item in opportunities[:5]]
        schema = {
            "plan": [
                {
                    "priority": 1,
                    "day_slot": "Dia 1",
                    "format": "Shorts ou Vídeo longo",
                    "keyword": "keyword validada exata",
                    "working_title": "título de trabalho",
                    "objective": "objetivo mensurável/estratégico",
                    "evidence_reason": "por que essa pauta foi escolhida",
                }
            ]
        }
        response = self.ai_runtime.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "Monte um plano editorial de 7 dias para YouTube usando somente oportunidades validadas. "
                        "Não invente frequência histórica, volume de busca, CTR ou garantia de views. "
                        "Use exatamente as keywords fornecidas. Títulos devem gerar curiosidade legítima, sem promessa falsa. Retorne JSON."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Canal: {profile.channel_title}\n"
                        f"Formato dominante recente: {self._dominant_format(profile)}\n"
                        f"Oportunidades validadas: {json.dumps(evidence, ensure_ascii=False)}\n\n"
                        "Monte de 3 a 5 publicações distribuídas em 7 dias, equilibrando qualidade e formato. "
                        f"Retorne: {json.dumps(schema, ensure_ascii=False)}"
                    ),
                },
            ],
            temperature=0.25,
            response_format="json",
        )
        payload = _parse_json(response.text)
        by_keyword = {item.keyword.casefold(): item for item in opportunities}
        plan: list[EditorialAction] = []
        used_keywords: set[str] = set()
        for raw in payload.get("plan", [])[:5]:
            keyword = str(raw.get("keyword", "")).strip()
            source = by_keyword.get(keyword.casefold())
            if not source or source.keyword.casefold() in used_keywords:
                continue
            used_keywords.add(source.keyword.casefold())
            requested_format = str(raw.get("format", source.recommended_format)).strip()
            fmt = "Shorts" if "short" in requested_format.casefold() else "Vídeo longo"
            plan.append(
                EditorialAction(
                    priority=len(plan) + 1,
                    day_slot=str(raw.get("day_slot", f"Dia {len(plan) + 1}")),
                    format=fmt,
                    keyword=source.keyword,
                    working_title=str(raw.get("working_title", source.keyword)).strip()[:100],
                    objective=str(raw.get("objective", "Explorar oportunidade validada")).strip(),
                    evidence_reason=str(raw.get("evidence_reason", "Oportunidade validada por dados recentes.")).strip(),
                    opportunity_score=source.score,
                    confidence=source.confidence,
                )
            )
        if not plan:
            for index, source in enumerate(opportunities[:3], start=1):
                plan.append(
                    EditorialAction(
                        priority=index,
                        day_slot=f"Dia {1 + (index - 1) * 3}",
                        format=source.recommended_format,
                        keyword=source.keyword,
                        working_title=source.keyword,
                        objective="Explorar oportunidade validada",
                        evidence_reason="Fallback determinístico baseado no ranking medido.",
                        opportunity_score=source.score,
                        confidence=source.confidence,
                    )
                )
        return plan

    def build(self) -> CommandCenterReport:
        profile = self.learning.collect(period_days=28, max_videos=50)
        health_score, health_label = self._health(profile)
        opportunities = self._validate_opportunities(profile)
        plan = self._editorial_plan(profile, opportunities)
        audit = self.audit_engine.audit(max_videos_to_recommend=6)
        warnings: list[str] = []
        if len(profile.top_search_terms) == 0:
            warnings.append("O Analytics não retornou termos de busca suficientes no período analisado.")
        if not opportunities:
            warnings.append("Nenhuma nova pauta atingiu confiança mínima para entrar no plano editorial.")
        if health_score < 35:
            warnings.append("A saúde recente está baixa ou há poucos dados; evite mudanças agressivas sem acompanhar novos resultados.")
        return CommandCenterReport(
            measured_at=datetime.now(timezone.utc).isoformat(),
            channel_title=profile.channel_title,
            health_score=health_score,
            health_label=health_label,
            search_share=float(profile.search_share or 0.0),
            shorts_share=float(profile.shorts_share_of_recent_views or 0.0),
            long_share=float(profile.long_share_of_recent_views or 0.0),
            dominant_format=self._dominant_format(profile),
            top_search_terms=tuple(asdict(item) for item in profile.top_search_terms[:15]),
            top_videos=tuple(asdict(item) for item in profile.top_videos[:10]),
            weak_videos=tuple(asdict(item) for item in profile.weak_videos[:10]),
            topic_terms=tuple(profile.topic_terms[:20]),
            opportunities=tuple(opportunities),
            editorial_plan=tuple(plan),
            audit=audit,
            warnings=tuple(warnings),
        )
