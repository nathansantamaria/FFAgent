"""Read live data from the repo, because the APIs are unreachable from here.

The sandbox cannot reach api.sleeper.app or ESPN -- both return 403 with
`x-deny-reason: host_not_allowed`. Verified, not assumed. The allowlist covers
GitHub, PyPI and npm.

GitHub *is* allowlisted. So a scheduled Action fetches from Sleeper and ESPN,
commits the JSON here, and this module reads it from raw.githubusercontent.com.
That turns an unreachable API into a reachable one with a few minutes of lag,
and it works when nobody is at a keyboard -- which the browser path does not.

**Staleness is surfaced, never hidden.** Every payload carries `fetched_at` and
every read reports its age. The failure this whole project keeps hitting is a
snapshot that goes quietly wrong; a cached file that cannot tell you how old it
is would be the same mistake again with extra steps.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = "https://raw.githubusercontent.com/nathansantamaria/FFAgent/main/data"

FILES = ("rosters", "matchups", "trending", "scoreboard", "espn_news")

# Older than this and the caller is warned. Six hours spans the gap between the
# daily 07:00 refresh and the Sunday-noon sweep without crying wolf, while still
# catching a workflow that has actually stopped running.
STALE_HOURS = 6.0


@dataclass
class Payload:
    name: str
    data: dict
    source: str          # "remote" | "local" | "missing"
    age_hours: float | None = None

    @property
    def stale(self) -> bool:
        return self.age_hours is None or self.age_hours > STALE_HOURS

    def note(self) -> str:
        if self.source == "missing":
            return f"{self.name}: NOT AVAILABLE — has the Action run yet?"
        age = "unknown age" if self.age_hours is None else f"{self.age_hours:.1f}h old"
        flag = "  [STALE]" if self.stale else ""
        return f"{self.name}: {self.source}, {age}{flag}"


def _age(payload: dict) -> float | None:
    ts = payload.get("fetched_at")
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - t).total_seconds() / 3600, 2)
    except Exception:
        return None


def fetch(name: str, prefer_remote: bool = True, timeout: int = 25) -> Payload:
    """Remote first, local fallback.

    Remote is preferred because the Action refreshes it on a schedule while the
    local copy is only as new as the last clone. If the network fails we fall
    back rather than erroring -- stale data with its age stated is more useful
    than nothing, as long as the age is stated.
    """
    if prefer_remote:
        try:
            with urllib.request.urlopen(f"{RAW}/{name}.json", timeout=timeout) as r:
                d = json.loads(r.read())
            return Payload(name, d, "remote", _age(d))
        except Exception:
            pass
    p = DATA / f"{name}.json"
    if p.exists():
        d = json.loads(p.read_text())
        return Payload(name, d, "local", _age(d))
    return Payload(name, {}, "missing")


def fetch_all(prefer_remote: bool = True) -> dict[str, Payload]:
    return {n: fetch(n, prefer_remote) for n in FILES}


def status() -> str:
    return "\n".join(p.note() for p in fetch_all().values())


def roster(prefer_remote: bool = True) -> tuple[list[str], Payload]:
    p = fetch("rosters", prefer_remote)
    return list(p.data.get("my_roster", [])), p


def scores(prefer_remote: bool = True) -> tuple[list[dict], Payload]:
    p = fetch("scoreboard", prefer_remote)
    return list(p.data.get("games", [])), p


def finals(prefer_remote: bool = True) -> list[dict]:
    g, _ = scores(prefer_remote)
    return [x for x in g if (x.get("status") or "").lower() == "final"]
