"""Client football-data.org (free tier có competition World Cup). Key global qua env.

Lỗi/giới hạn/thiếu key -> trả [] (KHÔNG raise), giống web_search. Map status FINISHED/IN_PLAY/
SCHEDULED -> finished/in_play/scheduled; trả list dict khớp WCMatchRepository.upsert.
"""

import logging
from datetime import datetime

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

_BASE = "https://api.football-data.org/v4"
_STATUS = {"FINISHED": "finished", "IN_PLAY": "in_play", "PAUSED": "in_play"}


def _map(raw: dict) -> dict:
    ft = (raw.get("score") or {}).get("fullTime") or {}
    return {
        "id": raw["id"],
        "competition": "WC",
        "stage": raw.get("stage"),
        "matchday": raw.get("matchday"),
        "home_team": (raw.get("homeTeam") or {}).get("name") or "?",
        "home_code": (raw.get("homeTeam") or {}).get("tla"),
        "away_team": (raw.get("awayTeam") or {}).get("name") or "?",
        "away_code": (raw.get("awayTeam") or {}).get("tla"),
        "kickoff_at": datetime.fromisoformat(raw["utcDate"].replace("Z", "+00:00")),
        "status": _STATUS.get(raw.get("status"), "scheduled"),
        "home_score": ft.get("home"),
        "away_score": ft.get("away"),
    }


async def fetch_wc_matches() -> list[dict]:
    """Lấy toàn bộ trận World Cup (lịch + kết quả). Lỗi/thiếu key -> []."""
    if not settings.FOOTBALL_DATA_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                f"{_BASE}/competitions/WC/matches",
                headers={"X-Auth-Token": settings.FOOTBALL_DATA_API_KEY},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:  # noqa: BLE001 — lỗi API không được làm hỏng tick
        log.warning("football_api: fetch_wc_matches failed")
        return []
    out = []
    for raw in data.get("matches") or []:
        try:
            out.append(_map(raw))
        except (KeyError, ValueError):
            continue  # bỏ trận parse hỏng, không chặn cả lô
    return out
