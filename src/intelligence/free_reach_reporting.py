from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.request import Request, urlopen

REACH_REPORT_TYPES = ("channel_reach_basic_a1", "channel_reach_combined_a1")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ReachMetric:
    video_id: str
    impressions: int
    ctr: float
    date: str


class YouTubeReachReporting:
    """Read-only adapter for YouTube Reporting API reach reports.

    Jobs are idempotently discovered/created. Reports are asynchronous, so a fresh
    account may legitimately return no rows until Google generates the first file.
    The adapter never fabricates CTR or impression values.
    """

    VERSION = "youtube-reach-reporting-v1"

    def __init__(self, token_file: str, reporting_client=None):
        self.token_file = token_file
        self._reporting = reporting_client

    def _client(self):
        if self._reporting is not None:
            return self._reporting
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(
            self.token_file,
            ["https://www.googleapis.com/auth/yt-analytics.readonly"],
        )
        self._reporting = build("youtubereporting", "v1", credentials=creds, cache_discovery=False)
        return self._reporting

    def ensure_reach_job(self) -> dict[str, Any]:
        client = self._client()
        jobs = client.jobs().list(pageSize=50).execute().get("jobs", []) or []
        for report_type in REACH_REPORT_TYPES:
            for job in jobs:
                if str(job.get("reportTypeId")) == report_type:
                    return {"job": job, "created": False}
        report_types = client.reportTypes().list(includeSystemManaged=False).execute().get("reportTypes", []) or []
        supported = {str(item.get("id")) for item in report_types}
        chosen = next((item for item in REACH_REPORT_TYPES if item in supported), None)
        if not chosen:
            return {
                "job": None,
                "created": False,
                "blocked_reason": "Nenhum report type de alcance do canal está disponível para esta conta.",
                "supported_report_types": sorted(supported),
            }
        job = client.jobs().create(body={"reportTypeId": chosen, "name": "YCA reach metrics"}).execute()
        return {"job": job, "created": True}

    def latest_report_descriptor(self, job_id: str) -> dict[str, Any] | None:
        client = self._client()
        response = client.jobs().reports().list(jobId=job_id, pageSize=50).execute()
        reports = [item for item in (response.get("reports") or []) if item.get("downloadUrl")]
        if not reports:
            return None
        reports.sort(key=lambda item: str(item.get("endTime") or item.get("createTime") or ""), reverse=True)
        return reports[0]

    @staticmethod
    def parse_csv(text: str) -> list[ReachMetric]:
        reader = csv.DictReader(io.StringIO(text or ""))
        rows: list[ReachMetric] = []
        for row in reader:
            video_id = str(row.get("video_id") or row.get("video") or "").strip()
            if not video_id:
                continue
            impressions = int(max(0, _num(row.get("video_thumbnail_impressions"))))
            ctr = max(0.0, _num(row.get("video_thumbnail_impressions_ctr")))
            rows.append(ReachMetric(video_id=video_id, impressions=impressions, ctr=ctr, date=str(row.get("date") or "")))
        return rows

    @staticmethod
    def summarize(rows: list[ReachMetric], *, video_id: str | None = None) -> dict[str, Any]:
        selected = [row for row in rows if not video_id or row.video_id == video_id]
        impressions = sum(row.impressions for row in selected)
        weighted_ctr = (
            sum(row.impressions * row.ctr for row in selected) / impressions
            if impressions > 0 else None
        )
        return {
            "engine": YouTubeReachReporting.VERSION,
            "source": "youtube_reporting_api",
            "official_metrics": ["video_thumbnail_impressions", "video_thumbnail_impressions_ctr"],
            "video_id": video_id,
            "rows": len(selected),
            "impressions": impressions,
            "ctr": round(weighted_ctr, 6) if weighted_ctr is not None else None,
            "data_available": bool(selected),
            "measured_at": datetime.now(timezone.utc).isoformat(),
            "writes_performed": 0,
            "methodology": "CTR is impression-weighted from official YouTube Reporting API reach rows. Missing data is returned as unavailable, never estimated.",
        }

    def fetch_latest(self, *, video_id: str | None = None, opener=None) -> dict[str, Any]:
        state = self.ensure_reach_job()
        job = state.get("job")
        if not job:
            return {
                "engine": self.VERSION,
                "source": "youtube_reporting_api",
                "data_available": False,
                "job_created": False,
                "pending": False,
                "blocked_reason": state.get("blocked_reason", "Reach report unavailable."),
                "writes_performed": 0,
            }
        descriptor = self.latest_report_descriptor(str(job.get("id")))
        if descriptor is None:
            return {
                "engine": self.VERSION,
                "source": "youtube_reporting_api",
                "data_available": False,
                "job_created": bool(state.get("created")),
                "pending": True,
                "job_id": str(job.get("id")),
                "report_type": str(job.get("reportTypeId")),
                "blocked_reason": "O job de alcance existe, mas o Google ainda não publicou um arquivo de relatório.",
                "writes_performed": 0,
            }
        download_url = str(descriptor.get("downloadUrl"))
        if opener is None:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request as GoogleRequest

            creds = Credentials.from_authorized_user_file(
                self.token_file,
                ["https://www.googleapis.com/auth/yt-analytics.readonly"],
            )
            creds.refresh(GoogleRequest())
            token = creds.token
            request = Request(download_url, headers={"Authorization": f"Bearer {token}"})
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8-sig", errors="replace")
        else:
            text = opener(download_url)
        result = self.summarize(self.parse_csv(text), video_id=video_id)
        result.update({
            "job_created": bool(state.get("created")),
            "pending": False,
            "job_id": str(job.get("id")),
            "report_type": str(job.get("reportTypeId")),
            "report_start_time": descriptor.get("startTime"),
            "report_end_time": descriptor.get("endTime"),
        })
        return result
