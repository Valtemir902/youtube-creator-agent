from __future__ import annotations

import json
import re

import imageio_ffmpeg
import os
import shutil
import torch
import whisper
from PySide6.QtCore import QThread, Signal

from ai.runtime import AIRuntime
from intelligence.youtube_research import YouTubeResearchEngine


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    return json.loads(text)


class ModelDiscoveryWorker(QThread):
    success = Signal(list)
    error = Signal(str)

    def __init__(self, runtime: AIRuntime, settings, api_key: str | None):
        super().__init__()
        self.runtime = runtime
        self.settings = settings
        self.api_key = api_key

    def run(self):
        try:
            models = self.runtime.list_models(self.settings, self.api_key)
            self.success.emit([m.id for m in models])
        except Exception as exc:
            self.error.emit(str(exc))


class ResearchWorker(QThread):
    progress = Signal(str)
    success = Signal(str)
    error = Signal(str)

    def __init__(self, token_file: str, query: str):
        super().__init__()
        self.token_file = token_file
        self.query = query

    def run(self):
        try:
            self.progress.emit("Consultando resultados reais do YouTube...")
            result = YouTubeResearchEngine(self.token_file).research(self.query, 25)
            op = result.opportunity
            lines = [
                f"CONSULTA VALIDADA: {result.query}",
                f"Opportunity Score: {op.score}/100 | Confiança: {op.confidence}/100",
                f"Demanda observável: {op.demand_score}/100 | Competição relativa: {op.competition_score}/100",
                f"Resultados medidos: {result.result_count}",
                f"Mediana de views: {result.median_views:,}",
                f"Mediana de views/dia: {result.median_views_per_day:,.1f}",
                f"Mediana de inscritos dos concorrentes: {result.median_channel_subscribers:,}",
                f"Resultados recentes (<=45d): {result.recent_result_rate:.0%}",
                f"Canais menores rompendo: {result.small_channel_breakout_rate:.0%}",
                f"Consulta exata no título: {result.exact_title_match_rate:.0%}",
                "",
                "Por que recebeu essa nota:",
            ]
            lines.extend(f"- {reason}" for reason in op.reasons)
            lines.append("\nTop evidências por velocidade:")
            for video in result.evidence[:8]:
                lines.append(f"- {video.title} | {video.views:,} views | {video.views_per_day:,.0f}/dia | canal {video.subscribers:,} inscritos")
            lines.append("\nNota: 'demanda' é proxy derivada do conjunto de resultados; não é volume mensal de buscas.")
            self.success.emit("\n".join(lines))
        except Exception as exc:
            self.error.emit(f"Falha na pesquisa: {exc}")


class EliteSEOAgentWorker(QThread):
    progress = Signal(str)
    success = Signal(dict)
    error = Signal(str)

    def __init__(self, video_path: str, content_format: str, token_file: str, runtime: AIRuntime):
        super().__init__()
        self.video_path = video_path
        self.content_format = content_format
        self.token_file = token_file
        self.runtime = runtime

    def _transcribe(self) -> str:
        ffmpeg_original = imageio_ffmpeg.get_ffmpeg_exe()
        folder = os.path.dirname(ffmpeg_original)
        if os.name == "nt":
            ffmpeg_exe = os.path.join(folder, "ffmpeg.exe")
            if not os.path.exists(ffmpeg_exe):
                shutil.copy(ffmpeg_original, ffmpeg_exe)
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = whisper.load_model("small", device=device)
        result = model.transcribe(self.video_path)
        return str(result.get("text", "")).strip()

    def run(self):
        try:
            self.progress.emit("[1/4] Transcrevendo o conteúdo...")
            transcript = self._transcribe()
            if len(transcript) < 20:
                raise RuntimeError("A transcrição ficou vazia ou curta demais para uma estratégia confiável.")

            self.progress.emit("[2/4] IA extraindo hipóteses de pesquisa, ainda não validadas...")
            hypothesis_resp = self.runtime.generate([
                {"role": "system", "content": "Extraia consultas que descrevam fielmente o conteúdo. Não invente tendências. Retorne JSON."},
                {"role": "user", "content": f"Transcrição:\n{transcript[:7000]}\n\nRetorne exatamente: {{\"queries\":[\"consulta 1\",\"consulta 2\",\"consulta 3\"]}}"},
            ], temperature=0.1, response_format="json")
            hypotheses = _parse_json(hypothesis_resp.text).get("queries", [])[:3]
            hypotheses = [str(q).strip() for q in hypotheses if str(q).strip()]
            if not hypotheses:
                raise RuntimeError("A IA não conseguiu extrair consultas válidas do conteúdo.")

            self.progress.emit("[3/4] Validando cada hipótese contra métricas reais do YouTube...")
            engine = YouTubeResearchEngine(self.token_file)
            measured = [engine.research(query, 20) for query in hypotheses]
            measured.sort(key=lambda item: (item.opportunity.score, item.opportunity.confidence), reverse=True)
            winner = measured[0]
            if winner.result_count < 5:
                raise RuntimeError("Não há evidência suficiente no YouTube para gerar SEO confiável para este conteúdo.")

            evidence_summary = {
                "validated_query": winner.query,
                "opportunity": {
                    "score": winner.opportunity.score,
                    "confidence": winner.opportunity.confidence,
                    "demand": winner.opportunity.demand_score,
                    "competition": winner.opportunity.competition_score,
                    "reasons": winner.opportunity.reasons,
                },
                "metrics": {
                    "result_count": winner.result_count,
                    "median_views": winner.median_views,
                    "median_views_per_day": winner.median_views_per_day,
                    "median_channel_subscribers": winner.median_channel_subscribers,
                    "small_channel_breakout_rate": winner.small_channel_breakout_rate,
                    "recent_result_rate": winner.recent_result_rate,
                },
                "top_titles": [v.title for v in winner.evidence[:10]],
            }

            self.progress.emit("[4/4] Gerando metadata baseada somente nas evidências validadas...")
            is_short = "short" in self.content_format.lower()
            format_rule = "YouTube Short: título curto e direto; descrição concisa; não force #shorts." if is_short else "Vídeo longo: título claro e convincente; descrição útil e natural."
            seo_resp = self.runtime.generate([
                {"role": "system", "content": "Você otimiza metadata do YouTube usando somente fatos fornecidos. Nunca alegue volume de pesquisa inexistente, nunca invente keywords, nunca prometa viralização. Responda JSON válido."},
                {"role": "user", "content": f"{format_rule}\n\nEVIDÊNCIA VALIDADA:\n{json.dumps(evidence_summary, ensure_ascii=False)}\n\nTRANSCRIÇÃO:\n{transcript[:12000]}\n\nRetorne {{\"youtube\":{{\"titulos_virais\":[\"...\"],\"descricao_seo\":\"...\",\"tags\":[\"...\"],\"keyword_principal\":\"{winner.query}\",\"opportunity_score\":{winner.opportunity.score},\"confidence\":{winner.opportunity.confidence}}}}. Tags devem ser somente termos semanticamente presentes na transcrição ou na consulta validada; máximo 12."},
            ], temperature=0.15, response_format="json")
            payload = _parse_json(seo_resp.text)
            yt = payload.setdefault("youtube", {})
            yt["keyword_principal"] = winner.query
            yt["opportunity_score"] = winner.opportunity.score
            yt["confidence"] = winner.opportunity.confidence
            yt["evidence"] = evidence_summary
            tags = yt.get("tags", [])
            yt["tags"] = [str(t).strip() for t in tags if str(t).strip()][:12]
            self.success.emit(payload)
        except Exception as exc:
            self.error.emit(f"Erro no motor Elite: {exc}")
