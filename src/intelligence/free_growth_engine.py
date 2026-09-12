from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Any, Iterable


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _score(value: float) -> int:
    return int(round(_clamp(value) * 100))


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[\wÀ-ÿ]{3,}", str(text or "").casefold(), flags=re.UNICODE)
    stop = {
        "para", "com", "sem", "uma", "uns", "das", "dos", "que", "por", "como", "mais",
        "menos", "meu", "minha", "seu", "sua", "nos", "nas", "the", "and", "you", "your",
        "video", "videos", "youtube", "shorts", "this", "that", "from", "with", "about", "into",
    }
    return [word for word in words if word not in stop]


def _ratio(value: float, target: float) -> float:
    if target <= 0:
        return 0.0
    return _clamp(value / target)


def _log_ratio(value: float, target: float) -> float:
    if value <= 0 or target <= 0:
        return 0.0
    return _clamp(math.log1p(value) / math.log1p(target))


def _overlap(left: Iterable[str], right: Iterable[str]) -> float:
    a = set(left)
    b = set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _grade(score: int) -> str:
    if score >= 85:
        return "excelente"
    if score >= 70:
        return "bom"
    if score >= 50:
        return "atenção"
    return "crítico"


@dataclass(frozen=True)
class Recommendation:
    code: str
    priority: str
    title: str
    action: str
    why: str
    evidence: dict[str, Any]
    confidence: int
    estimated_impact: str


class FreeGrowthEngine:
    """Deterministic YouTube growth engine for the free product tier.

    The engine never calls an LLM. Every score and recommendation must be
    reproducible from YouTube, YouTube Analytics, transcript or measured search
    evidence supplied by the caller.
    """

    VERSION = "free-growth-v1"

    @staticmethod
    def _recommendation(
        code: str,
        priority: str,
        title: str,
        action: str,
        why: str,
        evidence: dict[str, Any],
        *,
        confidence: int = 80,
        impact: str = "médio",
    ) -> dict[str, Any]:
        return asdict(Recommendation(
            code=code,
            priority=priority,
            title=title,
            action=action,
            why=why,
            evidence=evidence,
            confidence=max(0, min(100, int(confidence))),
            estimated_impact=impact,
        ))

    def channel_report(self, profile: dict[str, Any], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        profile = dict(profile or {})
        evidence = dict(evidence or {})
        search_share = _clamp(_num(profile.get("search_share")))
        period_views = max(0, int(_num(profile.get("total_analytics_views"))))
        search_views = max(0, int(_num(profile.get("search_views"))))
        subscribers = max(0, int(_num(profile.get("subscribers"))))
        video_count = max(0, int(_num(profile.get("video_count"))))
        top_terms = [row for row in (profile.get("top_search_terms") or []) if isinstance(row, dict)]
        top_videos = [row for row in (profile.get("top_videos") or []) if isinstance(row, dict)]
        weak_videos = [row for row in (profile.get("weak_videos") or []) if isinstance(row, dict)]
        topic_terms = [str(x) for x in (profile.get("topic_terms") or []) if str(x).strip()]

        discovery = _score(search_share / 0.20) if search_share > 0 else 0
        search_term_depth = _score(len(top_terms) / 10.0)
        consistency = _score(1.0 - min(1.0, len(weak_videos) / max(len(top_videos) + len(weak_videos), 1)))
        topic_clarity = _score(len(topic_terms) / 12.0)

        engagement_values = [_num(row.get("engagement_rate_28d")) for row in top_videos]
        engagement_avg = sum(engagement_values) / len(engagement_values) if engagement_values else 0.0
        engagement = _score(engagement_avg / 0.06)

        velocity_values = [_num(row.get("velocity_28d")) for row in top_videos]
        velocity_avg = sum(velocity_values) / len(velocity_values) if velocity_values else 0.0
        momentum = _score(_log_ratio(velocity_avg, 10000.0))

        coverage_count = sum([
            bool(period_views), bool(video_count), bool(top_videos), bool(topic_terms), bool(top_terms) or search_views == 0,
        ])
        confidence = _score(coverage_count / 5.0)
        overall = round(
            discovery * 0.24
            + search_term_depth * 0.10
            + consistency * 0.18
            + topic_clarity * 0.14
            + engagement * 0.18
            + momentum * 0.16
        )

        recommendations: list[dict[str, Any]] = []
        if search_share < 0.05:
            recommendations.append(self._recommendation(
                "low_search_share", "alta", "Aumentar descoberta pela busca",
                "Priorize vídeos e metadados alinhados aos termos reais de busca do canal e valide novas consultas antes de alterar títulos.",
                "A participação de visualizações vindas da busca está baixa no período medido.",
                {"search_share": round(search_share, 6), "search_views": search_views, "period_views": period_views},
                confidence=95 if period_views else 60, impact="alto",
            ))
        if len(top_terms) < 3:
            recommendations.append(self._recommendation(
                "thin_search_terms", "média", "Ampliar cobertura de consultas relevantes",
                "Pesquise variações específicas dos temas do canal e priorize termos com demanda observável e competição compatível.",
                "Há poucos termos de busca com sinal suficiente no período.",
                {"top_search_terms_count": len(top_terms), "topic_terms_count": len(topic_terms)},
                confidence=85, impact="médio",
            ))
        if weak_videos:
            recommendations.append(self._recommendation(
                "weak_video_cluster", "alta", "Revisar vídeos com baixa tração recente",
                "Comece pelos vídeos fracos que tenham transcrição disponível e compare o assunto real com título, descrição, tags e consultas recentes antes de propor mudanças.",
                "O perfil identificou vídeos abaixo do desempenho relativo recente.",
                {"weak_video_count": len(weak_videos), "sample_video_ids": [str(v.get("video_id", "")) for v in weak_videos[:5]]},
                confidence=90, impact="alto",
            ))
        if topic_clarity < 50:
            recommendations.append(self._recommendation(
                "weak_topic_clarity", "média", "Reforçar coerência temática",
                "Agrupe os próximos vídeos em pilares recorrentes que já apareçam nos dados do canal e evite temas desconectados apenas por tendência.",
                "A amostra recente contém poucos termos temáticos recorrentes para formar um posicionamento forte.",
                {"topic_terms": topic_terms[:12]}, confidence=75, impact="médio",
            ))
        if engagement < 45 and top_videos:
            recommendations.append(self._recommendation(
                "low_engagement", "média", "Melhorar resposta do público",
                "Compare abertura, promessa do título e conteúdo entregue nos vídeos de melhor e pior desempenho. Preserve o tema e teste mudanças uma por vez.",
                "O engajamento relativo dos vídeos de melhor desempenho ainda está abaixo da referência interna do motor.",
                {"average_engagement_rate": round(engagement_avg, 6), "reference_rate": 0.06},
                confidence=80, impact="médio",
            ))

        recommendations.sort(key=lambda row: ({"alta": 0, "média": 1, "baixa": 2}.get(row["priority"], 3), -row["confidence"]))
        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "grounded": True,
            "writes_performed": 0,
            "overall_score": overall,
            "grade": _grade(overall),
            "confidence": confidence,
            "scores": {
                "search_discovery": discovery,
                "search_term_depth": search_term_depth,
                "content_consistency": consistency,
                "topic_clarity": topic_clarity,
                "engagement": engagement,
                "momentum": momentum,
            },
            "facts": {
                "period_days": int(_num(profile.get("period_days"), 28)),
                "period_views": period_views,
                "search_views": search_views,
                "search_share": round(search_share, 6),
                "subscribers": subscribers,
                "video_count": video_count,
                "top_search_terms": top_terms[:10],
                "topic_terms": topic_terms[:16],
                "weak_video_count": len(weak_videos),
            },
            "recommendations": recommendations[:10],
            "methodology": "Scores derived only from supplied YouTube/Analytics facts; thresholds are explicit product heuristics, not claimed YouTube ranking factors.",
        }

    def video_report(
        self,
        current: dict[str, Any],
        *,
        transcript: str = "",
        keyword_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        current = dict(current or {})
        title = str(current.get("title") or "").strip()
        description = str(current.get("description") or "").strip()
        tags = [str(x).strip() for x in (current.get("tags") or []) if str(x).strip()]
        transcript = str(transcript or "").strip()
        title_tokens = _tokens(title)
        description_tokens = _tokens(description)
        transcript_tokens = _tokens(transcript)
        transcript_counts = Counter(transcript_tokens)
        dominant = [token for token, _ in transcript_counts.most_common(30)]

        title_length = len(title)
        title_length_score = _score(1.0 - min(1.0, abs(title_length - 62) / 62.0)) if title else 0
        description_score = _score(min(1.0, len(description) / 600.0))
        transcript_coverage = _score(_overlap(title_tokens + description_tokens, dominant)) if dominant else 0
        tag_coverage = _score(_overlap((_tokens(" ".join(tags))), dominant)) if dominant and tags else 0
        metadata_score = round(title_length_score * 0.25 + description_score * 0.20 + transcript_coverage * 0.40 + tag_coverage * 0.15)

        measured = [row for row in (keyword_results or []) if isinstance(row, dict)]
        measured.sort(key=lambda row: int(_num(row.get("opportunity_score"), _num((row.get("opportunity") or {}).get("score")))), reverse=True)
        best = measured[:8]
        opportunity_values = [int(_num(row.get("opportunity_score"), _num((row.get("opportunity") or {}).get("score")))) for row in best]
        opportunity_score = round(sum(opportunity_values) / len(opportunity_values)) if opportunity_values else 0
        confidence = 95 if transcript_tokens and measured else (80 if transcript_tokens else 55)

        recommendations: list[dict[str, Any]] = []
        if not transcript_tokens:
            recommendations.append(self._recommendation(
                "missing_transcript", "alta", "Obter transcrição antes de alterar SEO",
                "Não reescreva título ou descrição apenas por tendência. Primeiro obtenha a transcrição ou legenda para confirmar o assunto realmente tratado.",
                "Sem transcrição, a aderência semântica entre conteúdo e metadata não pode ser verificada com alta confiança.",
                {"transcript_tokens": 0}, confidence=100, impact="alto",
            ))
        elif transcript_coverage < 35:
            recommendations.append(self._recommendation(
                "metadata_content_mismatch", "alta", "Alinhar metadata ao conteúdo real",
                "Reescreva a proposta de título e descrição usando os temas dominantes da transcrição e somente keywords medidas que também tenham aderência ao conteúdo.",
                "Título e descrição cobrem pouco dos principais termos observados na transcrição.",
                {"transcript_alignment_score": transcript_coverage, "dominant_terms": dominant[:12]},
                confidence=90, impact="alto",
            ))
        if title_length < 30 or title_length > 90:
            recommendations.append(self._recommendation(
                "title_length_risk", "média", "Tornar o título mais direto",
                "Teste um título claro que descreva a promessa real do vídeo sem cortar o tema principal ou inserir termos sem relação com a transcrição.",
                "O tamanho atual do título está fora da faixa editorial preferida pelo motor para clareza móvel.",
                {"title_length": title_length, "preferred_editorial_range": "30-90"},
                confidence=75, impact="médio",
            ))
        if len(description) < 120:
            recommendations.append(self._recommendation(
                "thin_description", "média", "Enriquecer a descrição",
                "Inclua um resumo natural do conteúdo, termos realmente presentes no vídeo e contexto útil. Evite repetição artificial de keywords.",
                "A descrição atual oferece pouco contexto textual para o usuário e para sistemas de recuperação.",
                {"description_length": len(description)}, confidence=85, impact="médio",
            ))
        if measured and opportunity_score >= 55:
            recommendations.append(self._recommendation(
                "measured_keyword_opportunity", "alta", "Priorizar oportunidades medidas",
                "Use apenas os termos de maior oportunidade que também correspondam semanticamente à transcrição. Preserve o idioma original do vídeo.",
                "A pesquisa encontrou consultas com sinal observável de demanda/frescor e competição utilizável.",
                {"average_top_opportunity_score": opportunity_score, "keywords": [row.get("keyword") or row.get("query") for row in best[:5]]},
                confidence=90, impact="alto",
            ))

        overall = round(metadata_score * 0.65 + opportunity_score * 0.35) if measured else metadata_score
        return {
            "engine": self.VERSION,
            "mode": "deterministic_free",
            "uses_external_ai": False,
            "grounded": True,
            "writes_performed": 0,
            "overall_score": overall,
            "grade": _grade(overall),
            "confidence": confidence,
            "scores": {
                "metadata": metadata_score,
                "title_clarity": title_length_score,
                "description_depth": description_score,
                "transcript_alignment": transcript_coverage,
                "tag_alignment": tag_coverage,
                "measured_keyword_opportunity": opportunity_score,
            },
            "content_evidence": {
                "transcript_available": bool(transcript_tokens),
                "transcript_token_count": len(transcript_tokens),
                "dominant_transcript_terms": dominant[:20],
                "title_length": title_length,
                "description_length": len(description),
                "tag_count": len(tags),
            },
            "keyword_evidence": best,
            "recommendations": recommendations[:10],
            "methodology": "No LLM. Metadata is compared with transcript terms and optional YouTube search evidence. Scores are explainable heuristics, not promises of ranking or views.",
        }
