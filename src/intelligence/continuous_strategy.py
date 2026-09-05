from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai.runtime import AIRuntime
from .channel_command_center import ChannelCommandCenterEngine


@dataclass(frozen=True)
class OpportunityMomentum:
    keyword: str
    current_score: int
    previous_score: int | None
    delta: int | None
    status: str
    samples: int


@dataclass(frozen=True)
class PublishTimingInsight:
    best_day: str
    confidence: int
    sample_size: int
    note: str


@dataclass(frozen=True)
class OutcomeObservation:
    action_id: int
    target_id: str
    status: str
    velocity_delta_pct: float | None
    engagement_delta_pct: float | None
    note: str


class StrategyHistoryStore:
    """Stores compact derived strategy history, not raw Analytics rows."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS strategy_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    measured_at TEXT NOT NULL,
                    channel_title TEXT NOT NULL,
                    health_score INTEGER NOT NULL,
                    search_share REAL NOT NULL,
                    dominant_format TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS opportunity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    measured_at TEXT NOT NULL,
                    keyword TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    demand_index INTEGER NOT NULL,
                    channel_fit INTEGER NOT NULL,
                    competition_label TEXT NOT NULL,
                    fresh_30d_rate REAL NOT NULL,
                    views_per_day REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES strategy_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_opportunity_keyword_time
                    ON opportunity_snapshots(keyword, measured_at);
                CREATE TABLE IF NOT EXISTS applied_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    baseline_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    evaluated_at TEXT,
                    outcome_json TEXT
                );
                """
            )

    def purge(self, retention_days: int = 365) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            run_ids = [row[0] for row in conn.execute(
                "SELECT id FROM strategy_runs WHERE measured_at < ?", (cutoff,)
            ).fetchall()]
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                conn.execute(f"DELETE FROM opportunity_snapshots WHERE run_id IN ({placeholders})", run_ids)
                conn.execute(f"DELETE FROM strategy_runs WHERE id IN ({placeholders})", run_ids)
            conn.execute("DELETE FROM applied_actions WHERE applied_at < ?", (cutoff,))

    def previous_run(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT measured_at, health_score, search_share, dominant_format "
                "FROM strategy_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {
            "measured_at": row[0],
            "health_score": int(row[1]),
            "search_share": float(row[2]),
            "dominant_format": row[3],
        }

    def keyword_history(self, keyword: str, limit: int = 8) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT measured_at, score, demand_index, channel_fit, competition_label, fresh_30d_rate, views_per_day "
                "FROM opportunity_snapshots WHERE lower(keyword)=lower(?) ORDER BY id DESC LIMIT ?",
                (keyword, limit),
            ).fetchall()
        return [
            {
                "measured_at": row[0],
                "score": int(row[1]),
                "demand_index": int(row[2]),
                "channel_fit": int(row[3]),
                "competition_label": row[4],
                "fresh_30d_rate": float(row[5]),
                "views_per_day": float(row[6]),
            }
            for row in rows
        ]

    def save_run(self, report) -> int:
        self.purge()
        measured_at = getattr(report, "measured_at", datetime.now(timezone.utc).isoformat())
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO strategy_runs(measured_at, channel_title, health_score, search_share, dominant_format) "
                "VALUES(?,?,?,?,?)",
                (
                    measured_at,
                    report.channel_title,
                    int(report.health_score),
                    float(report.search_share),
                    report.dominant_format,
                ),
            )
            run_id = int(cursor.lastrowid)
            for item in report.opportunities:
                conn.execute(
                    "INSERT INTO opportunity_snapshots(run_id, measured_at, keyword, score, demand_index, channel_fit, "
                    "competition_label, fresh_30d_rate, views_per_day) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        measured_at,
                        item.keyword,
                        int(item.score),
                        int(item.demand_index),
                        int(item.channel_fit),
                        item.competition_label,
                        float(item.fresh_30d_rate),
                        float(item.views_per_day),
                    ),
                )
        return run_id

    def record_action(self, action_type: str, target_id: str, baseline: dict, metadata: dict) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO applied_actions(action_type, target_id, applied_at, baseline_json, metadata_json) "
                "VALUES(?,?,?,?,?)",
                (
                    action_type,
                    target_id,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(baseline, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def pending_actions(self, min_age_hours: int = 24, limit: int = 30) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=min_age_hours)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, action_type, target_id, applied_at, baseline_json, metadata_json "
                "FROM applied_actions WHERE evaluated_at IS NULL AND applied_at <= ? ORDER BY id ASC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "action_type": row[1],
                "target_id": row[2],
                "applied_at": row[3],
                "baseline": json.loads(row[4]),
                "metadata": json.loads(row[5]),
            }
            for row in rows
        ]

    def mark_evaluated(self, action_id: int, outcome: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE applied_actions SET evaluated_at=?, outcome_json=? WHERE id=?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(outcome, ensure_ascii=False),
                    int(action_id),
                ),
            )


class EnhancedCommandReport:
    """Transparent wrapper so existing UI keeps working while v6 adds new fields."""

    def __init__(self, base, *, momentum, timing, previous_run, observations):
        self.base = base
        self.momentum = tuple(momentum)
        self.timing = timing
        self.previous_run = previous_run
        self.observations = tuple(observations)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


class ContinuousStrategyEngine:
    def __init__(self, token_file: str, ai_runtime: AIRuntime, history_file: str | Path | None = None):
        self.token_file = token_file
        self.ai_runtime = ai_runtime
        default_history = Path(token_file).parent / "strategy_history.sqlite3"
        self.store = StrategyHistoryStore(history_file or default_history)
        self.command = ChannelCommandCenterEngine(token_file, ai_runtime)

    @staticmethod
    def _momentum_status(delta: int | None, samples: int) -> str:
        if delta is None or samples <= 1:
            return "NOVA"
        if delta >= 8:
            return "ACELERANDO"
        if delta <= -8:
            return "PERDENDO FORÇA"
        if delta >= 3:
            return "SUBINDO"
        if delta <= -3:
            return "CAINDO"
        return "ESTÁVEL"

    def _momentum(self, report) -> list[OpportunityMomentum]:
        output: list[OpportunityMomentum] = []
        for item in report.opportunities:
            history = self.store.keyword_history(item.keyword, limit=8)
            previous = history[0]["score"] if history else None
            delta = int(item.score - previous) if previous is not None else None
            samples = len(history) + 1
            output.append(
                OpportunityMomentum(
                    keyword=item.keyword,
                    current_score=int(item.score),
                    previous_score=previous,
                    delta=delta,
                    status=self._momentum_status(delta, samples),
                    samples=samples,
                )
            )
        return output

    @staticmethod
    def _timing(report) -> PublishTimingInsight:
        day_names = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
        weighted: dict[int, list[float]] = {i: [] for i in range(7)}
        for item in report.top_videos:
            published = str(item.get("published_at", "")).strip()
            if not published:
                continue
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                continue
            velocity = float(item.get("velocity_28d", 0.0) or 0.0)
            if velocity > 0:
                weighted[dt.weekday()].append(velocity)
        available = {day: values for day, values in weighted.items() if values}
        sample_size = sum(len(values) for values in available.values())
        if not available:
            return PublishTimingInsight(
                best_day="dados insuficientes",
                confidence=0,
                sample_size=0,
                note="A API pública não fornece hora do dia; não há amostra suficiente para inferir um dia histórico.",
            )
        averages = {day: sum(values) / len(values) for day, values in available.items()}
        best_day = max(averages, key=averages.get)
        confidence = min(85, 25 + sample_size * 6 + len(available) * 3)
        return PublishTimingInsight(
            best_day=day_names[best_day],
            confidence=confidence,
            sample_size=sample_size,
            note=(
                "Dia inferido pela velocidade média dos vídeos recentes da própria amostra. "
                "Não representa audiência online por hora e não é garantia de desempenho."
            ),
        )

    @staticmethod
    def _video_index(report) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for item in list(report.top_videos) + list(report.weak_videos):
            video_id = str(item.get("video_id", "")).strip()
            if video_id and video_id not in index:
                index[video_id] = item
        return index

    @staticmethod
    def _pct_delta(current: float, baseline: float) -> float | None:
        if baseline <= 0:
            return None
        return round(((current - baseline) / baseline) * 100.0, 1)

    def _evaluate_pending_actions(self, report) -> list[OutcomeObservation]:
        current = self._video_index(report)
        observations: list[OutcomeObservation] = []
        for action in self.store.pending_actions(min_age_hours=24):
            item = current.get(action["target_id"])
            if not item:
                observations.append(
                    OutcomeObservation(
                        action_id=action["id"],
                        target_id=action["target_id"],
                        status="AGUARDANDO DADOS",
                        velocity_delta_pct=None,
                        engagement_delta_pct=None,
                        note="O vídeo não apareceu na amostra atual; a ação permanece sem avaliação conclusiva.",
                    )
                )
                continue
            baseline = action["baseline"]
            velocity_delta = self._pct_delta(
                float(item.get("velocity_28d", 0.0) or 0.0),
                float(baseline.get("velocity_28d", 0.0) or 0.0),
            )
            engagement_delta = self._pct_delta(
                float(item.get("engagement_rate_28d", 0.0) or 0.0),
                float(baseline.get("engagement_rate_28d", 0.0) or 0.0),
            )
            status = "OBSERVADO"
            note = (
                "Mudança observada após a ação. Isso não prova causalidade porque as métricas são janelas móveis e sofrem influência de outros fatores."
            )
            outcome = {
                "velocity_delta_pct": velocity_delta,
                "engagement_delta_pct": engagement_delta,
                "observed_video": item,
                "note": note,
            }
            self.store.mark_evaluated(action["id"], outcome)
            observations.append(
                OutcomeObservation(
                    action_id=action["id"],
                    target_id=action["target_id"],
                    status=status,
                    velocity_delta_pct=velocity_delta,
                    engagement_delta_pct=engagement_delta,
                    note=note,
                )
            )
        return observations

    def build(self) -> EnhancedCommandReport:
        previous_run = self.store.previous_run()
        base = self.command.build()
        momentum = self._momentum(base)
        timing = self._timing(base)
        observations = self._evaluate_pending_actions(base)
        self.store.save_run(base)
        return EnhancedCommandReport(
            base,
            momentum=momentum,
            timing=timing,
            previous_run=previous_run,
            observations=observations,
        )

    def record_metadata_actions(self, report) -> list[int]:
        audit = report.audit or {}
        videos = {str(item.get("video_id", "")): item for item in list(report.top_videos) + list(report.weak_videos)}
        ids: list[int] = []
        for change in audit.get("videos_para_otimizar", []):
            video_id = str(change.get("id_video", "")).strip()
            if not video_id:
                continue
            baseline = videos.get(video_id, {})
            ids.append(
                self.store.record_action(
                    "metadata_update",
                    video_id,
                    baseline,
                    {
                        "new_title": change.get("sugestao_novo_titulo_viral", ""),
                        "confidence": change.get("confidence", 0),
                    },
                )
            )
        return ids
