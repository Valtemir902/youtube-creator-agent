from __future__ import annotations

import math
import re
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .opportunity_score import OpportunityInput, OpportunityResult, calculate_opportunity_score

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)).strip()


def _ratio(value: float, scale: float) -> float:
    if value <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log1p(value) / math.log1p(scale)))


@dataclass(frozen=True)
class VideoEvidence:
    video_id: str
    title: str
    channel_id: str
    published_at: str
    views: int
    likes: int
    comments: int
    subscribers: int
    age_days: float
    views_per_day: float
    exact_query_in_title: bool


@dataclass(frozen=True)
class KeywordResearchResult:
    query: str
    opportunity: OpportunityResult
    result_count: int
    median_views: int
    median_views_per_day: float
    median_channel_subscribers: int
    exact_title_match_rate: float
    recent_result_rate: float
    small_channel_breakout_rate: float
    evidence: tuple[VideoEvidence, ...]
    methodology: str = "YouTube Data API result-set proxies; not exact search volume"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["opportunity"] = asdict(self.opportunity)
        return data


class YouTubeResearchEngine:
    """Measures opportunity from observable YouTube result-set data.

    It deliberately does not claim exact monthly search volume because the public
    YouTube Data API does not expose that metric for arbitrary queries.
    """

    def __init__(self, token_file: str, youtube_client=None):
        self.token_file = token_file
        self._youtube = youtube_client

    def _client(self):
        if self._youtube is not None:
            return self._youtube
        creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        self._youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        return self._youtube

    def research(self, query: str, max_results: int = 25) -> KeywordResearchResult:
        query = query.strip()
        if len(query) < 2:
            raise ValueError("Informe uma consulta válida para pesquisa.")
        max_results = max(5, min(50, int(max_results)))
        yt = self._client()

        search = yt.search().list(
            part="snippet",
            q=query,
            type="video",
            order="relevance",
            maxResults=max_results,
            safeSearch="moderate",
        ).execute()
        items = search.get("items", [])
        ids = [item.get("id", {}).get("videoId") for item in items]
        ids = [vid for vid in ids if vid]
        if not ids:
            return self._empty(query)

        video_resp = yt.videos().list(
            part="snippet,statistics",
            id=",".join(ids),
            maxResults=len(ids),
        ).execute()
        videos = video_resp.get("items", [])
        channel_ids = sorted({v.get("snippet", {}).get("channelId") for v in videos if v.get("snippet", {}).get("channelId")})
        channels = {}
        if channel_ids:
            ch_resp = yt.channels().list(part="statistics", id=",".join(channel_ids), maxResults=len(channel_ids)).execute()
            channels = {c["id"]: c.get("statistics", {}) for c in ch_resp.get("items", [])}

        now = datetime.now(timezone.utc)
        normalized_query = _norm(query)
        evidence = []
        for item in videos:
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            published_raw = snippet.get("publishedAt", "")
            try:
                published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                age_days = max((now - published).total_seconds() / 86400.0, 0.25)
            except Exception:
                age_days = 3650.0
            views = int(stats.get("viewCount", 0) or 0)
            channel_stats = channels.get(snippet.get("channelId", ""), {})
            subscribers = int(channel_stats.get("subscriberCount", 0) or 0)
            title = snippet.get("title", "")
            evidence.append(VideoEvidence(
                video_id=item.get("id", ""),
                title=title,
                channel_id=snippet.get("channelId", ""),
                published_at=published_raw,
                views=views,
                likes=int(stats.get("likeCount", 0) or 0),
                comments=int(stats.get("commentCount", 0) or 0),
                subscribers=subscribers,
                age_days=age_days,
                views_per_day=views / age_days,
                exact_query_in_title=normalized_query in _norm(title),
            ))

        return self._score(query, evidence, max_results)

    def _score(self, query: str, evidence: list[VideoEvidence], requested: int) -> KeywordResearchResult:
        if not evidence:
            return self._empty(query)
        views = [v.views for v in evidence]
        velocity = [v.views_per_day for v in evidence]
        subs = [v.subscribers for v in evidence]
        median_views = int(statistics.median(views))
        median_velocity = float(statistics.median(velocity))
        median_subs = int(statistics.median(subs))
        recent_rate = sum(v.age_days <= 45 for v in evidence) / len(evidence)
        exact_rate = sum(v.exact_query_in_title for v in evidence) / len(evidence)
        breakout = sum((v.subscribers <= 100_000 and v.views_per_day >= max(median_velocity, 1.0)) for v in evidence) / len(evidence)
        dominant = sum(v.subscribers >= 500_000 for v in evidence) / len(evidence)

        trend_strength = min(1.0, recent_rate * 0.55 + _ratio(median_velocity, 50_000) * 0.45)
        view_velocity = _ratio(median_velocity, 100_000)
        competition_pressure = min(1.0, _ratio(median_subs, 2_000_000) * 0.70 + exact_rate * 0.30)
        intent_strength = min(1.0, 0.35 + exact_rate * 0.65)
        coverage = min(1.0, len(evidence) / requested)

        opportunity = calculate_opportunity_score(OpportunityInput(
            trend_strength=trend_strength,
            recent_view_velocity=view_velocity,
            small_channel_breakout=breakout,
            freshness=recent_rate,
            channel_fit=0.5,
            intent_strength=intent_strength,
            competition_pressure=competition_pressure,
            dominant_channel_concentration=dominant,
            evidence_coverage=coverage,
        ))
        return KeywordResearchResult(
            query=query,
            opportunity=opportunity,
            result_count=len(evidence),
            median_views=median_views,
            median_views_per_day=round(median_velocity, 2),
            median_channel_subscribers=median_subs,
            exact_title_match_rate=round(exact_rate, 4),
            recent_result_rate=round(recent_rate, 4),
            small_channel_breakout_rate=round(breakout, 4),
            evidence=tuple(sorted(evidence, key=lambda x: x.views_per_day, reverse=True)),
        )

    @staticmethod
    def _empty(query: str) -> KeywordResearchResult:
        opportunity = calculate_opportunity_score(OpportunityInput(
            trend_strength=0, recent_view_velocity=0, small_channel_breakout=0,
            freshness=0, channel_fit=0.5, intent_strength=0,
            competition_pressure=1, dominant_channel_concentration=1,
            evidence_coverage=0,
        ))
        return KeywordResearchResult(query, opportunity, 0, 0, 0.0, 0, 0.0, 0.0, 0.0, tuple())
