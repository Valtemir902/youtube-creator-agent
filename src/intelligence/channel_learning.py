from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[\wÀ-ÿ]{3,}", text.casefold(), flags=re.UNICODE)
    stop = {
        "para", "com", "sem", "uma", "uns", "das", "dos", "que", "por", "como",
        "mais", "menos", "meu", "minha", "seu", "sua", "nos", "nas", "the", "and",
        "you", "video", "shorts", "youtube",
    }
    return [word for word in words if word not in stop]


def _normalize(text: str) -> str:
    return " ".join(_tokens(text))


def _duration_seconds(iso_duration: str) -> int:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        iso_duration or "",
    )
    if not match:
        return 0
    values = {key: int(value or 0) for key, value in match.groupdict().items()}
    return values["days"] * 86400 + values["hours"] * 3600 + values["minutes"] * 60 + values["seconds"]


@dataclass(frozen=True)
class SearchTermSignal:
    term: str
    views: int
    estimated_minutes_watched: float
    share_of_search_views: float


@dataclass(frozen=True)
class VideoPerformance:
    video_id: str
    title: str
    published_at: str
    duration_seconds: int
    format: str
    views_total: int
    views_28d: int
    estimated_minutes_watched_28d: float
    average_view_duration_28d: float
    likes_28d: int
    comments_28d: int
    shares_28d: int
    subscribers_gained_28d: int
    velocity_28d: float
    engagement_rate_28d: float


@dataclass(frozen=True)
class ChannelProfile:
    measured_at: str
    channel_id: str
    channel_title: str
    subscribers: int
    total_views: int
    video_count: int
    period_days: int
    search_views: int
    total_analytics_views: int
    search_share: float
    top_search_terms: tuple[SearchTermSignal, ...]
    top_videos: tuple[VideoPerformance, ...]
    weak_videos: tuple[VideoPerformance, ...]
    topic_terms: tuple[str, ...]
    shorts_share_of_recent_views: float
    long_share_of_recent_views: float
    country: str = "GLOBAL"
    default_language: str = "und"

    def to_dict(self) -> dict:
        return asdict(self)

    def channel_fit(self, keyword: str) -> float:
        query_tokens = set(_tokens(keyword))
        if not query_tokens:
            return 0.5
        weighted: Counter[str] = Counter()
        for index, term in enumerate(self.top_search_terms):
            weight = max(1, 12 - index)
            for token in _tokens(term.term):
                weighted[token] += weight
        for index, term in enumerate(self.topic_terms):
            weighted[term] += max(1, 8 - index // 2)
        if not weighted:
            return 0.5
        matched = sum(weighted[token] for token in query_tokens)
        possible = sum(sorted(weighted.values(), reverse=True)[: max(1, len(query_tokens))])
        lexical = min(1.0, matched / max(possible, 1))
        normalized_keyword = _normalize(keyword)
        phrase_hits = sum(
            1
            for item in self.top_search_terms
            if normalized_keyword in _normalize(item.term)
            or _normalize(item.term) in normalized_keyword
        )
        phrase = min(1.0, phrase_hits / 3.0)
        return round(max(0.05, min(1.0, 0.25 + lexical * 0.55 + phrase * 0.20)), 4)


class ChannelSnapshotStore:
    """Local, short-retention cache for derived channel profiles.

    Raw Analytics rows are not persisted. Profiles older than 29 days are purged
    automatically to keep the desktop cache intentionally short-lived.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS channel_profiles ("
                "measured_at TEXT PRIMARY KEY, channel_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save(self, profile: ChannelProfile) -> None:
        self.purge()
        payload = json.dumps(profile.to_dict(), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO channel_profiles(measured_at, channel_id, payload) VALUES (?, ?, ?)",
                (profile.measured_at, profile.channel_id, payload),
            )

    def latest(self, channel_id: str | None = None) -> dict | None:
        self.purge()
        with self._connect() as conn:
            if channel_id:
                row = conn.execute(
                    "SELECT payload FROM channel_profiles WHERE channel_id=? ORDER BY measured_at DESC LIMIT 1",
                    (channel_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT payload FROM channel_profiles ORDER BY measured_at DESC LIMIT 1"
                ).fetchone()
        return json.loads(row[0]) if row else None

    def purge(self, max_age_days: int = 29) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM channel_profiles WHERE measured_at < ?", (cutoff,))


class ChannelLearningEngine:
    def __init__(self, token_file: str, youtube_client=None, analytics_client=None):
        self.token_file = token_file
        self._youtube = youtube_client
        self._analytics = analytics_client

    def _clients(self):
        if self._youtube is not None and self._analytics is not None:
            return self._youtube, self._analytics
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        if self._youtube is None:
            self._youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        if self._analytics is None:
            self._analytics = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
        return self._youtube, self._analytics

    def collect(self, period_days: int = 28, max_videos: int = 50) -> ChannelProfile:
        period_days = max(7, min(90, int(period_days)))
        max_videos = max(10, min(50, int(max_videos)))
        yt, analytics = self._clients()
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=period_days)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")

        channel_resp = yt.channels().list(part="snippet,statistics,contentDetails,brandingSettings", mine=True).execute()
        items = channel_resp.get("items", [])
        if not items:
            raise RuntimeError("Nenhum canal associado à conta conectada.")
        channel = items[0]
        channel_id = channel["id"]
        snippet = channel.get("snippet", {})
        stats = channel.get("statistics", {})
        branding = channel.get("brandingSettings", {}).get("channel", {})
        country = str(snippet.get("country") or branding.get("country") or "").upper()
        default_language = str(snippet.get("defaultLanguage") or branding.get("defaultLanguage") or "").strip()
        uploads = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads:
            raise RuntimeError("Não foi possível localizar a playlist de uploads do canal.")

        video_ids: list[str] = []
        page_token = None
        while len(video_ids) < max_videos:
            response = yt.playlistItems().list(
                part="contentDetails",
                playlistId=uploads,
                maxResults=min(50, max_videos - len(video_ids)),
                pageToken=page_token,
            ).execute()
            video_ids.extend(
                item.get("contentDetails", {}).get("videoId")
                for item in response.get("items", [])
                if item.get("contentDetails", {}).get("videoId")
            )
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        if not video_ids:
            raise RuntimeError("O canal conectado ainda não possui vídeos analisáveis.")

        video_resp = yt.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(video_ids),
            maxResults=len(video_ids),
        ).execute()
        base_by_id = {item["id"]: item for item in video_resp.get("items", [])}

        analytics_rows = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics="views,estimatedMinutesWatched,averageViewDuration,likes,comments,shares,subscribersGained",
            dimensions="video",
            filters=f"video=={','.join(video_ids)}",
            maxResults=len(video_ids),
            sort="-views",
        ).execute().get("rows", []) or []

        analytics_map = {}
        for row in analytics_rows:
            analytics_map[str(row[0])] = {
                "views": int(row[1] or 0),
                "minutes": float(row[2] or 0),
                "avg_duration": float(row[3] or 0),
                "likes": int(row[4] or 0),
                "comments": int(row[5] or 0),
                "shares": int(row[6] or 0),
                "subs": int(row[7] or 0),
            }

        search_rows = analytics.reports().query(
            ids="channel==MINE",
            startDate=start,
            endDate=end,
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceDetail",
            filters=f"video=={','.join(video_ids)};insightTrafficSourceType==YT_SEARCH",
            maxResults=25,
            sort="-views",
        ).execute().get("rows", []) or []

        search_views = sum(int(row[1] or 0) for row in search_rows)
        search_terms = tuple(
            SearchTermSignal(
                term=str(row[0]),
                views=int(row[1] or 0),
                estimated_minutes_watched=float(row[2] or 0),
                share_of_search_views=round(int(row[1] or 0) / max(search_views, 1), 4),
            )
            for row in search_rows
            if str(row[0]).strip()
        )

        performances: list[VideoPerformance] = []
        topics: Counter[str] = Counter()
        for video_id in video_ids:
            item = base_by_id.get(video_id)
            if not item:
                continue
            v_snippet = item.get("snippet", {})
            v_stats = item.get("statistics", {})
            title = str(v_snippet.get("title", ""))
            for token in _tokens(title):
                topics[token] += 1
            duration = _duration_seconds(item.get("contentDetails", {}).get("duration", ""))
            format_name = "short" if 0 < duration <= 180 else "long"
            a = analytics_map.get(video_id, {})
            views_28d = int(a.get("views", 0))
            engagement = (
                int(a.get("likes", 0))
                + int(a.get("comments", 0)) * 2
                + int(a.get("shares", 0)) * 3
            ) / max(views_28d, 1)
            performances.append(
                VideoPerformance(
                    video_id=video_id,
                    title=title,
                    published_at=str(v_snippet.get("publishedAt", "")),
                    duration_seconds=duration,
                    format=format_name,
                    views_total=int(v_stats.get("viewCount", 0) or 0),
                    views_28d=views_28d,
                    estimated_minutes_watched_28d=round(float(a.get("minutes", 0)), 2),
                    average_view_duration_28d=round(float(a.get("avg_duration", 0)), 2),
                    likes_28d=int(a.get("likes", 0)),
                    comments_28d=int(a.get("comments", 0)),
                    shares_28d=int(a.get("shares", 0)),
                    subscribers_gained_28d=int(a.get("subs", 0)),
                    velocity_28d=round(views_28d / period_days, 2),
                    engagement_rate_28d=round(engagement, 5),
                )
            )

        ranked = sorted(
            performances,
            key=lambda video: (
                video.velocity_28d,
                video.engagement_rate_28d,
                video.subscribers_gained_28d,
            ),
            reverse=True,
        )
        active = [video for video in ranked if video.views_28d > 0]
        weak = sorted(
            active,
            key=lambda video: (
                video.velocity_28d,
                video.engagement_rate_28d,
            ),
        )[:8]
        total_analytics_views = sum(video.views_28d for video in performances)
        short_views = sum(video.views_28d for video in performances if video.format == "short")
        long_views = sum(video.views_28d for video in performances if video.format == "long")
        format_total = max(short_views + long_views, 1)

        for signal in search_terms:
            for token in _tokens(signal.term):
                topics[token] += max(1, int(math.sqrt(signal.views + 1)))

        return ChannelProfile(
            measured_at=now.isoformat(),
            channel_id=channel_id,
            channel_title=str(snippet.get("title", "Canal")),
            country=country or "GLOBAL",
            default_language=default_language or "und",
            subscribers=int(stats.get("subscriberCount", 0) or 0),
            total_views=int(stats.get("viewCount", 0) or 0),
            video_count=int(stats.get("videoCount", 0) or 0),
            period_days=period_days,
            search_views=search_views,
            total_analytics_views=total_analytics_views,
            search_share=round(search_views / max(total_analytics_views, 1), 4),
            top_search_terms=search_terms,
            top_videos=tuple(ranked[:10]),
            weak_videos=tuple(weak),
            topic_terms=tuple(token for token, _ in topics.most_common(20)),
            shorts_share_of_recent_views=round(short_views / format_total, 4),
            long_share_of_recent_views=round(long_views / format_total, 4),
        )
