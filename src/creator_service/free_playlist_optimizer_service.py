from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.routing import APIRoute

from intelligence.free_growth_engine import _tokens
from intelligence.free_playlist_optimizer import FreePlaylistOptimizer


def _candidate_terms(videos: list[dict[str, Any]], limit: int = 6) -> list[str]:
    tokens = _tokens(" ".join(str(row.get("title") or "") for row in videos))
    counts = Counter(tokens)
    terms = [term for term, count in counts.most_common(20) if count >= 2]
    phrases, seen = [], set()
    for row in videos:
        row_tokens = _tokens(str(row.get("title") or ""))
        for size in (3, 2):
            for index in range(max(0, len(row_tokens) - size + 1)):
                chunk = row_tokens[index:index + size]
                if all(token in terms for token in chunk):
                    phrase = " ".join(chunk)
                    if phrase not in seen:
                        seen.add(phrase); phrases.append(phrase)
                        if len(phrases) >= limit:
                            return phrases
    for term in terms:
        if term not in seen:
            phrases.append(term)
        if len(phrases) >= limit:
            break
    return phrases


def install_free_playlist_optimizer_service() -> None:
    from .service import CreatorService
    if getattr(CreatorService, "_yca_free_playlist_optimizer_installed", False):
        return
    original_status = CreatorService.status

    def status(self) -> dict[str, Any]:
        result = dict(original_status(self))
        free = dict(result.get("free_intelligence") or {})
        free["playlist_optimizer_version"] = FreePlaylistOptimizer.VERSION
        result["free_intelligence"] = free
        return result

    def free_playlist_optimization_plan(self, playlist_id: str, *, period_days: int = 28) -> dict[str, Any]:
        self.context.validate_youtube()
        playlist_id = str(playlist_id or "").strip()
        response = self._youtube().playlists().list(part="snippet,status,contentDetails", id=playlist_id, maxResults=1).execute()
        items = response.get("items") or []
        if not items:
            raise ValueError("Playlist não encontrada.")
        item = items[0]
        snippet = item.get("snippet", {}) or {}
        if str(snippet.get("channelId") or "") != str(self._authorized_channel_id()):
            raise PermissionError("A playlist não pertence ao canal autorizado.")
        current = {"playlist_id": playlist_id, "title": str(snippet.get("title") or ""), "description": str(snippet.get("description") or ""), "privacy_status": str((item.get("status", {}) or {}).get("privacyStatus") or "")}
        videos: list[dict[str, Any]] = []
        token = None
        while len(videos) < 50:
            page = self._youtube().playlistItems().list(part="snippet,contentDetails", playlistId=playlist_id, maxResults=min(50, 50-len(videos)), pageToken=token).execute()
            for row in page.get("items") or []:
                rs = row.get("snippet", {}) or {}
                videos.append({"video_id": str((row.get("contentDetails", {}) or {}).get("videoId") or ""), "title": str(rs.get("title") or ""), "description": str(rs.get("description") or "")})
            token = page.get("nextPageToken")
            if not token:
                break
        candidates = _candidate_terms(videos)
        keyword_rows, keyword_error = [], ""
        if candidates:
            try:
                validation = self.validate_keyword_candidates(candidates, period_days=max(7, min(90, int(period_days))), max_results=12)
                for row in validation.get("results") or []:
                    if isinstance(row, dict):
                        keyword_rows.append({"keyword": row.get("keyword"), "opportunity_score": row.get("personalized_opportunity_score", row.get("market_opportunity_score", 0)), "market_opportunity_score": row.get("market_opportunity_score"), "confidence": row.get("confidence"), "demand_index": row.get("demand_index"), "competition_score": row.get("competition_score"), "fresh_7d_rate": row.get("fresh_7d_rate"), "fresh_30d_rate": row.get("fresh_30d_rate"), "evidence": list(row.get("evidence") or [])[:8]})
            except Exception as exc:
                keyword_error = str(exc)[:500]
        plan = FreePlaylistOptimizer().build(current, member_videos=videos, keyword_results=keyword_rows)
        plan.update({"period_days": max(7, min(90, int(period_days))), "candidate_keywords": candidates, "keyword_research_error": keyword_error, "plan_tier": "free", "premium_ai_required": False, "member_scan_limit": 50})
        return plan

    CreatorService.status = status
    CreatorService.free_playlist_optimization_plan = free_playlist_optimization_plan
    CreatorService._yca_free_playlist_optimizer_installed = True


def _closure_values(fn) -> dict[str, Any]:
    values = {}
    for name, cell in zip(getattr(fn.__code__, "co_freevars", ()), getattr(fn, "__closure__", None) or ()):
        try: values[name] = cell.cell_contents
        except ValueError: pass
    return values


def install_free_playlist_optimizer_dashboard(app: FastAPI) -> None:
    if getattr(app.state, "free_playlist_optimizer_dashboard_installed", False):
        return
    status_route = next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/api/dashboard/status")
    service_for = _closure_values(status_route.endpoint).get("service_for")
    if service_for is None:
        raise RuntimeError("Não foi possível resolver o serviço para otimização de playlist.")
    readable = status_route.dependant.dependencies[0].call

    @app.get("/api/dashboard/free/playlist/{playlist_id}/optimization")
    async def free_playlist_optimization(playlist_id: str, period_days: int = 28, tenant: Any = Depends(readable)) -> dict[str, Any]:
        try:
            return service_for(tenant.tenant_id).free_playlist_optimization_plan(playlist_id, period_days=max(7, min(90, period_days)))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    app.state.free_playlist_optimizer_dashboard_installed = True
