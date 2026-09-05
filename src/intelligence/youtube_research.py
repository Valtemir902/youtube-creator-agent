from __future__ import annotations

import math
import re
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

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


def _competition_label(score: int) -> str:
    if score >= 70:
        return "baixa"
    if score >= 45:
        return "média"
    return "alta"


def _demand_label(score: int) -> str:
    if score >= 70:
        return "alta"
    if score >= 45:
        return "média"
    return "baixa"


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
    engagement_rate: float
    exact_query_in_title: bool


@dataclass(frozen=True)
class KeywordResearchResult:
    query: str
    measured_at: str
    opportunity: OpportunityResult
    result_count: int
    median_views: int
    median_views_per_day: float
    p75_views_per_day: float
    median_channel_subscribers: int
    exact_title_match_rate: float
    fresh_7d_rate: float
    fresh_30d_rate: float
    fresh_90d_rate: float
    small_channel_breakout_rate: float
    dominant_channel_rate: float
    median_engagement_rate: float
    estimated_daily_demand_index: int
    demand_label: str
    competition_label: str
    evidence: tuple[VideoEvidence, ...]
    methodology: str = "YouTube Data API observable-result proxies; daily demand is an index, not exact search count"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["opportunity"] = asdict(self.opportunity)
        return data


class YouTubeResearchEngine:
    """Measures opportunity from observable YouTube result-set data.

    The public YouTube Data API does not expose exact daily/monthly search volume
    for arbitrary keywords. This engine therefore computes an honest demand index
    from recent-result prevalence, view velocity, title-query match and breakout.
    """

    def __init__(self, token_file: str, youtube_client=None, now_provider=None):
        self.token_file = token_file
        self._youtube = youtube_client
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

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

        now = self._now_provider()
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
            likes = int(stats.get("likeCount", 0) or 0)
            comments = int(stats.get("commentCount", 0) or 0)
            channel_stats = channels.get(snippet.get("channelId", ""), {})
            subscribers = int(channel_stats.get("subscriberCount", 0) or 0)
            title = snippet.get("title", "")
            engagement = ((likes + comments) / views) if views > 0 else 0.0
            evidence.append(VideoEvidence(
                video_id=item.get("id", ""),
                title=title,
                channel_id=snippet.get("channelId", ""),
                published_at=published_raw,
                views=views,
                likes=likes,
                comments=comments,
                subscribers=subscribers,
                age_days=age_days,
                views_per_day=views / age_days,
                engagement_rate=engagement,
                exact_query_in_title=normalized_query in _norm(title),
            ))

        return self._score(query, evidence, max_results, now)

    def _score(self, query: str, evidence: list[VideoEvidence], requested: int, now: datetime) -> KeywordResearchResult:
        if not evidence:
            return self._empty(query)
        views = [v.views for v in evidence]
        velocity = [v.views_per_day for v in evidence]
        subs = [v.subscribers for v in evidence]
        engagements = [v.engagement_rate for v in evidence]
        median_views = int(statistics.median(views))
        median_velocity = float(statistics.median(velocity))
        ordered_velocity = sorted(velocity)
        p75_index = max(0, math.ceil(len(ordered_velocity) * 0.75) - 1)
        p75_velocity = float(ordered_velocity[p75_index])
        median_subs = int(statistics.median(subs))
        median_engagement = float(statistics.median(engagements))
        fresh_7 = sum(v.age_days <= 7 for v in evidence) / len(evidence)
        fresh_30 = sum(v.age_days <= 30 for v in evidence) / len(evidence)
        fresh_90 = sum(v.age_days <= 90 for v in evidence) / len(evidence)
        exact_rate = sum(v.exact_query_in_title for v in evidence) / len(evidence)
        breakout = sum((v.subscribers <= 100_000 and v.views_per_day >= max(median_velocity, 1.0)) for v in evidence) / len(evidence)
        dominant = sum(v.subscribers >= 500_000 for v in evidence) / len(evidence)

        freshness_signal = min(1.0, fresh_7 * 0.45 + fresh_30 * 0.35 + fresh_90 * 0.20)
        trend_strength = min(1.0, freshness_signal * 0.58 + _ratio(median_velocity, 50_000) * 0.42)
        view_velocity = _ratio(median_velocity, 100_000)
        competition_pressure = min(1.0, _ratio(median_subs, 2_000_000) * 0.58 + exact_rate * 0.22 + dominant * 0.20)
        intent_strength = min(1.0, 0.25 + exact_rate * 0.75)
        coverage = min(1.0, len(evidence) / requested)

        opportunity = calculate_opportunity_score(OpportunityInput(
            trend_strength=trend_strength,
            recent_view_velocity=view_velocity,
            small_channel_breakout=breakout,
            freshness=freshness_signal,
            channel_fit=0.5,
            intent_strength=intent_strength,
            competition_pressure=competition_pressure,
            dominant_channel_concentration=dominant,
            evidence_coverage=coverage,
        ))

        daily_index = round(max(0.0, min(1.0,
            _ratio(median_velocity, 80_000) * 0.40
            + _ratio(p75_velocity, 150_000) * 0.20
            + fresh_30 * 0.15
            + exact_rate * 0.10
            + breakout * 0.10
            + min(1.0, median_engagement / 0.08) * 0.05
        )) * 100)

        return KeywordResearchResult(
            query=query,
            measured_at=now.isoformat(),
            opportunity=opportunity,
            result_count=len(evidence),
            median_views=median_views,
            median_views_per_day=round(median_velocity, 2),
            p75_views_per_day=round(p75_velocity, 2),
            median_channel_subscribers=median_subs,
            exact_title_match_rate=round(exact_rate, 4),
            fresh_7d_rate=round(fresh_7, 4),
            fresh_30d_rate=round(fresh_30, 4),
            fresh_90d_rate=round(fresh_90, 4),
            small_channel_breakout_rate=round(breakout, 4),
            dominant_channel_rate=round(dominant, 4),
            median_engagement_rate=round(median_engagement, 5),
            estimated_daily_demand_index=daily_index,
            demand_label=_demand_label(daily_index),
            competition_label=_competition_label(opportunity.competition_score),
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
        return KeywordResearchResult(
            query=query,
            measured_at=datetime.now(timezone.utc).isoformat(),
            opportunity=opportunity,
            result_count=0,
            median_views=0,
            median_views_per_day=0.0,
            p75_views_per_day=0.0,
            median_channel_subscribers=0,
            exact_title_match_rate=0.0,
            fresh_7d_rate=0.0,
            fresh_30d_rate=0.0,
            fresh_90d_rate=0.0,
            small_channel_breakout_rate=0.0,
            dominant_channel_rate=1.0,
            median_engagement_rate=0.0,
            estimated_daily_demand_index=0,
            demand_label="baixa",
            competition_label="alta",
            evidence=tuple(),
        )
