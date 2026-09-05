from __future__ import annotations

import json
import re
from dataclasses import asdict

from ai.runtime import AIRuntime
from .channel_learning import ChannelLearningEngine, ChannelProfile
from .youtube_research import YouTubeResearchEngine


def _parse_json(text: str) -> dict:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I | re.S).strip()
    return json.loads(clean)


class ChannelAuditEngine:
    """Evidence-first audit using the selected AI provider.

    Analytics decides which videos deserve attention. The LLM explains and drafts
    metadata, but cannot override raw metrics or fabricate search-volume claims.
    """

    def __init__(self, token_file: str, ai_runtime: AIRuntime):
        self.token_file = token_file
        self.ai_runtime = ai_runtime
        self.learning = ChannelLearningEngine(token_file)
        self.research = YouTubeResearchEngine(token_file)

    @staticmethod
    def _profile_context(profile: ChannelProfile) -> dict:
        return {
            "channel": {
                "title": profile.channel_title,
                "subscribers": profile.subscribers,
                "video_count": profile.video_count,
                "period_days": profile.period_days,
                "search_share": profile.search_share,
                "shorts_share": profile.shorts_share_of_recent_views,
                "long_share": profile.long_share_of_recent_views,
            },
            "real_search_terms": [asdict(item) for item in profile.top_search_terms[:20]],
            "top_videos": [asdict(item) for item in profile.top_videos[:10]],
            "weak_videos": [asdict(item) for item in profile.weak_videos[:8]],
            "topic_terms": list(profile.topic_terms[:20]),
        }

    def audit(self, max_videos_to_recommend: int = 6) -> dict:
        profile = self.learning.collect(period_days=28, max_videos=50)
        weak = list(profile.weak_videos[:max_videos_to_recommend])
        if not weak:
            return {
                "diagnostico_geral": "Não há vídeos com atividade recente suficiente para uma auditoria corretiva confiável.",
                "videos_para_otimizar": [],
                "channel_profile": self._profile_context(profile),
            }

        validations = {}
        for video in weak:
            query = video.title.strip()[:90]
            try:
                validations[video.video_id] = self.research.research(query, 15).to_dict()
            except Exception:
                validations[video.video_id] = None

        context = self._profile_context(profile)
        context["market_validation_by_video"] = validations
        schema = {
            "diagnostico_geral": "diagnóstico técnico baseado nos dados",
            "videos_para_otimizar": [
                {
                    "id_video": "id exato fornecido",
                    "titulo_antigo": "título atual",
                    "motivo_do_flop": "diagnóstico sem inventar causa",
                    "sugestao_novo_titulo_viral": "novo título persuasivo sem promessa falsa",
                    "sugestao_nova_descricao": "descrição natural",
                    "sugestao_novas_tags": ["termos semanticamente comprovados"],
                    "confidence": 0,
                }
            ],
        }
        response = self.ai_runtime.generate(
            [
                {
                    "role": "system",
                    "content": (
                        "Você é um analista de crescimento de YouTube orientado por evidências. "
                        "Use somente os dados fornecidos. Não alegue causalidade quando os dados só mostram correlação. "
                        "Não invente CTR, impressões, volume de busca ou retenção. Não prometa viralização. "
                        "Só recomende alteração de metadata quando houver motivo mensurável. Retorne JSON válido."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"DADOS DO CANAL E VALIDAÇÕES:\n{json.dumps(context, ensure_ascii=False)}\n\n"
                        f"Retorne no formato: {json.dumps(schema, ensure_ascii=False)}. "
                        "No máximo 6 vídeos. Tags: máximo 12 e somente termos presentes no conteúdo fornecido, "
                        "nos títulos atuais, nos termos reais de busca do canal ou nas validações de mercado."
                    ),
                },
            ],
            temperature=0.15,
            response_format="json",
        )
        payload = _parse_json(response.text)
        allowed_ids = {video.video_id: video for video in weak}
        clean_recommendations = []
        for item in payload.get("videos_para_otimizar", []):
            video_id = str(item.get("id_video", "")).strip()
            if video_id not in allowed_ids:
                continue
            original = allowed_ids[video_id]
            item["titulo_antigo"] = original.title
            item["confidence"] = max(0, min(100, int(item.get("confidence", 0) or 0)))
            item["sugestao_novas_tags"] = [
                str(tag).strip()
                for tag in item.get("sugestao_novas_tags", [])
                if str(tag).strip()
            ][:12]
            clean_recommendations.append(item)

        return {
            "diagnostico_geral": str(payload.get("diagnostico_geral", "Auditoria concluída.")),
            "videos_para_otimizar": clean_recommendations,
            "channel_profile": context,
        }
