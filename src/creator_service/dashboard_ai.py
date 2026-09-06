from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from intelligence.youtube_research import YouTubeResearchEngine


CATEGORY_NAMES = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "19": "Travel & Events",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}


def _json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("A IA não retornou JSON válido.")
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError("A IA retornou uma resposta que não pôde ser validada.") from exc
    if not isinstance(value, dict):
        raise RuntimeError("A IA retornou um formato inesperado.")
    return value


def channel_identity(youtube) -> dict[str, Any]:
    response = youtube.channels().list(part="snippet,statistics,brandingSettings", mine=True).execute()
    items = response.get("items", [])
    if not items:
        return {}
    item = items[0]
    snippet = item.get("snippet", {})
    thumbs = snippet.get("thumbnails", {})
    thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url")
    branding = item.get("brandingSettings", {}).get("channel", {})
    stats = item.get("statistics", {})
    return {
        "id": str(item.get("id", "")),
        "title": str(snippet.get("title", "")),
        "description": str(snippet.get("description", "")),
        "country": snippet.get("country") or branding.get("country"),
        "default_language": snippet.get("defaultLanguage") or branding.get("defaultLanguage"),
        "thumbnail": thumb,
        "subscribers": int(stats.get("subscriberCount", 0) or 0),
        "views": int(stats.get("viewCount", 0) or 0),
        "videos": int(stats.get("videoCount", 0) or 0),
    }


def list_playlists(youtube, limit: int = 50) -> list[dict[str, Any]]:
    response = youtube.playlists().list(
        part="snippet,contentDetails,status",
        mine=True,
        maxResults=max(1, min(50, int(limit))),
    ).execute()
    output = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        thumbs = snippet.get("thumbnails", {})
        thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
        output.append({
            "id": str(item.get("id", "")),
            "title": str(snippet.get("title", "")),
            "description": str(snippet.get("description", "")),
            "thumbnail": thumb,
            "count": int(item.get("contentDetails", {}).get("itemCount", 0) or 0),
            "privacy_status": item.get("status", {}).get("privacyStatus", "private"),
        })
    return output


def list_live_broadcasts(youtube) -> list[dict[str, Any]]:
    response = youtube.liveBroadcasts().list(
        part="id,snippet,status,contentDetails",
        broadcastStatus="all",
        broadcastType="all",
        mine=True,
        maxResults=25,
    ).execute()
    output = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        output.append({
            "id": str(item.get("id", "")),
            "title": str(snippet.get("title", "")),
            "description": str(snippet.get("description", "")),
            "scheduled_start_time": snippet.get("scheduledStartTime"),
            "actual_start_time": snippet.get("actualStartTime"),
            "life_cycle_status": item.get("status", {}).get("lifeCycleStatus"),
            "privacy_status": item.get("status", {}).get("privacyStatus"),
        })
    return output


def _strip_srt(text: str) -> str:
    lines = []
    for raw in text.replace("\r", "").split("\n"):
        value = raw.strip()
        if not value or value.isdigit() or "-->" in value:
            continue
        value = re.sub(r"<[^>]+>", "", value)
        if value:
            lines.append(value)
    compact = " ".join(lines)
    return re.sub(r"\s+", " ", compact).strip()


def youtube_transcript(youtube, video_id: str, max_chars: int = 28000) -> dict[str, Any]:
    try:
        tracks = youtube.captions().list(part="id,snippet", videoId=video_id).execute().get("items", [])
    except Exception as exc:
        return {"available": False, "text": "", "reason": f"caption_list_failed:{type(exc).__name__}"}
    if not tracks:
        return {"available": False, "text": "", "reason": "no_caption_track"}
    tracks.sort(key=lambda item: (item.get("snippet", {}).get("trackKind") == "ASR", item.get("snippet", {}).get("isDraft", False)))
    for track in tracks:
        caption_id = str(track.get("id", ""))
        if not caption_id:
            continue
        try:
            payload = youtube.captions().download(id=caption_id, tfmt="srt").execute()
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            text = _strip_srt(str(payload))
            if text:
                snippet = track.get("snippet", {})
                return {
                    "available": True,
                    "text": text[:max_chars],
                    "language": snippet.get("language"),
                    "track_kind": snippet.get("trackKind"),
                    "truncated": len(text) > max_chars,
                }
        except Exception:
            continue
    return {"available": False, "text": "", "reason": "caption_download_unavailable"}


def _clean_candidates(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for raw in value:
        term = " ".join(str(raw).strip().split())
        if len(term) < 3:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(term)
        if len(output) >= 12:
            break
    return output


def grounded_seo_plan(
    service,
    *,
    source_text: str,
    original_title: str = "",
    user_context: str = "",
    max_age_days: int = 30,
    playlists: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    settings = service.ai_runtime.load_settings()
    if not settings.model:
        raise RuntimeError("Configure uma IA externa em Ajustes para usar a otimização automática dentro do painel.")
    source = " ".join(str(source_text or "").split())
    context = " ".join(str(user_context or "").split())
    if len(source) < 20 and len(context) < 10 and len(original_title) < 6:
        raise RuntimeError("Não há contexto suficiente para otimizar sem inventar. Forneça transcrição ou contexto real do conteúdo.")

    channel = channel_identity(service._youtube())
    candidate_prompt = f"""Você é um pesquisador de SEO para YouTube. Gere somente candidatos de busca coerentes com o conteúdo real abaixo. Não invente fatos. Não gere título ainda. Retorne JSON puro no formato {{\"keyword_candidates\":[...]}} com 8 a 12 frases de busca específicas e naturais no idioma e mercado do canal.\nCANAL: {json.dumps(channel, ensure_ascii=False)}\nTÍTULO ATUAL/ARQUIVO: {original_title}\nCONTEXTO DO USUÁRIO: {context}\nCONTEÚDO/TRANSCRIÇÃO: {source[:18000]}"""
    first = service.ai_runtime.generate(
        [{"role": "user", "content": candidate_prompt}],
        temperature=0.15,
        max_output_tokens=700,
    )
    candidates = _clean_candidates(_json_object(first.text).get("keyword_candidates"))
    if not candidates:
        raise RuntimeError("A IA não gerou candidatos de pesquisa válidos.")

    youtube = service._youtube()
    research = YouTubeResearchEngine(str(service.context.token_file), youtube_client=youtube)
    measured = []
    age = max(1, min(180, int(max_age_days)))
    for keyword in candidates:
        row = research.research(keyword, max_results=20, max_age_days=age)
        measured.append({
            "keyword": keyword,
            "opportunity_score": int(row.opportunity.score),
            "competition_score": int(row.opportunity.competition_score),
            "competition_label": row.competition_label,
            "demand_index": int(row.estimated_daily_demand_index),
            "demand_label": row.demand_label,
            "result_count": int(row.result_count),
            "fresh_7d_rate": row.fresh_7d_rate,
            "fresh_30d_rate": row.fresh_30d_rate,
            "fresh_90d_rate": row.fresh_90d_rate,
            "median_views_per_day": row.median_views_per_day,
            "small_channel_breakout_rate": row.small_channel_breakout_rate,
            "evidence": [asdict(item) for item in row.evidence[:5]],
        })
    qualified = [
        row for row in measured
        if row["result_count"] >= 5
        and row["demand_index"] >= 20
        and row["competition_label"] in {"baixa", "média"}
        and (row["fresh_7d_rate"] > 0 or row["fresh_30d_rate"] > 0 or row["fresh_90d_rate"] > 0)
    ]
    qualified.sort(key=lambda row: (row["opportunity_score"], row["demand_index"], row["median_views_per_day"]), reverse=True)
    if not qualified:
        raise RuntimeError("Nenhuma palavra-chave passou pelos critérios mínimos de demanda recente e competição baixa/média. A ferramenta recusou otimizar com termos fracos.")

    playlist_rows = playlists or []
    final_prompt = f"""Você é um estrategista sênior de YouTube. Monte uma proposta de SEO baseada SOMENTE no conteúdo e nas evidências verificadas fornecidas. Não invente fatos, números, marcas ou temas ausentes. Use apenas keywords da lista QUALIFICADAS. O título deve ser natural, forte e fiel ao vídeo, não um amontoado de palavras-chave. Retorne JSON puro com: title, description, tags (máx 12), hashtags (máx 5), category_id, playlist_id (ou string vazia), language, rationale.\nCANAL: {json.dumps(channel, ensure_ascii=False)}\nTÍTULO/ARQUIVO ORIGINAL: {original_title}\nCONTEXTO DO USUÁRIO: {context}\nCONTEÚDO/TRANSCRIÇÃO: {source[:18000]}\nKEYWORDS QUALIFICADAS E RECENTES (janela máxima {age} dias): {json.dumps(qualified[:8], ensure_ascii=False)}\nPLAYLISTS DISPONÍVEIS: {json.dumps(playlist_rows[:50], ensure_ascii=False)}\nCATEGORIAS VÁLIDAS: {json.dumps(CATEGORY_NAMES, ensure_ascii=False)}"""
    second = service.ai_runtime.generate(
        [{"role": "user", "content": final_prompt}],
        temperature=0.12,
        max_output_tokens=1800,
    )
    plan = _json_object(second.text)
    tags = _clean_candidates(plan.get("tags"))[:12]
    hashtags = _clean_candidates(plan.get("hashtags"))[:5]
    title = " ".join(str(plan.get("title", "")).split())[:100]
    description = str(plan.get("description", "")).strip()[:5000]
    category_id = str(plan.get("category_id", "22"))
    if category_id not in CATEGORY_NAMES:
        category_id = "22"
    valid_playlist_ids = {str(item.get("id", "")) for item in playlist_rows}
    playlist_id = str(plan.get("playlist_id", "")).strip()
    if playlist_id not in valid_playlist_ids:
        playlist_id = ""
    if not title or not description:
        raise RuntimeError("A IA não produziu um pacote de publicação completo e verificável.")
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "hashtags": hashtags,
        "category_id": category_id,
        "category_name": CATEGORY_NAMES[category_id],
        "playlist_id": playlist_id,
        "language": str(plan.get("language") or channel.get("default_language") or "").strip(),
        "rationale": str(plan.get("rationale", "")).strip(),
        "verified_keywords": qualified[:8],
        "rejected_keywords": [row for row in measured if row not in qualified],
        "max_age_days": age,
        "provider": second.provider,
        "model": second.model,
    }
