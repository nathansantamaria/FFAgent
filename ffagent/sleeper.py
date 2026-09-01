"""Read-only Sleeper client.

Everything here is a documented public GET endpoint. No auth, no writes.
Writes go through the Playwright layer (see write.py) -- never here.
Rate limit is 1000 calls/min; we stay far below that.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

BASE = "https://api.sleeper.app/v1"
CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)


def _get(path: str, timeout: int = 30) -> Any:
    r = requests.get(f"{BASE}/{path.lstrip('/')}", timeout=timeout)
    r.raise_for_status()
    return r.json()


# --- league state -------------------------------------------------------

def league(league_id: str) -> dict:
    return _get(f"league/{league_id}")


def users(league_id: str) -> list[dict]:
    return _get(f"league/{league_id}/users")


def rosters(league_id: str) -> list[dict]:
    return _get(f"league/{league_id}/rosters")


def matchups(league_id: str, week: int) -> list[dict]:
    return _get(f"league/{league_id}/matchups/{week}")


def transactions(league_id: str, week: int) -> list[dict]:
    return _get(f"league/{league_id}/transactions/{week}")


def drafts(league_id: str) -> list[dict]:
    return _get(f"league/{league_id}/drafts")


def draft_picks(draft_id: str) -> list[dict]:
    return _get(f"draft/{draft_id}/picks")


def draft(draft_id: str) -> dict:
    return _get(f"draft/{draft_id}")


def nfl_state() -> dict:
    """Current season + week. The agent's clock -- never hardcode the week."""
    return _get("state/nfl")


# --- player universe ----------------------------------------------------

def players(max_age_hours: int = 24) -> dict:
    """~5MB. Sleeper explicitly asks callers to fetch this at most once a day."""
    fp = CACHE / "players_nfl.json"
    if fp.exists() and (time.time() - fp.stat().st_mtime) < max_age_hours * 3600:
        return json.loads(fp.read_text())
    data = _get("players/nfl", timeout=120)
    fp.write_text(json.dumps(data))
    return data


def trending(kind: str = "add", lookback_hours: int = 24, limit: int = 50) -> list[dict]:
    """What the wider Sleeper market is claiming right now.

    Not an edge by itself -- it is the *consensus* we are trying to front-run.
    Useful as a "has this been noticed yet?" check on watchlist candidates.
    """
    return _get(f"players/nfl/trending/{kind}?lookback_hours={lookback_hours}&limit={limit}")
