"""The decision log.

Every decision is recorded whether or not it executes, with the factors that
drove it and the alternatives it rejected. Two fields do the real work and are
the ones people skip: `outcome_check_at` and `actual_result`. Without a
scheduled look-back you never learn whether the agent is good -- you just
remember the calls that worked.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB = Path(__file__).resolve().parent.parent / "data" / "decisions.db"

# Fantasy weeks are event-driven, not daily. These are the moments that matter.
WINDOWS = {
    "waiver_submit": "Tue 23:00 ET, claims lock",
    "waiver_process": "Wed 03:00 ET, pool reopens",
    "tnf_lock": "Thu 17:00 ET",
    "inactives": "Sun 11:30 ET, inactives drop",
    "main_lock": "Sun 13:00 ET",
}


@dataclass
class Factor:
    name: str
    value: float | str
    weight: float
    source: str
    as_of: str


@dataclass
class Decision:
    type: str                      # start_sit | waiver | trade | drop | draft
    player: str
    action: str
    thesis: str                    # one sentence, plain English
    confidence: float              # 0-1, calibrated later against outcomes
    execute_at: str
    expires_at: str
    factors: list[Factor] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    window: str = ""
    status: str = "proposed"       # proposed|queued|executed|expired|overridden
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    outcome_check_at: str = ""
    actual_result: float | None = None

    def __post_init__(self) -> None:
        if not self.outcome_check_at:
            self.outcome_check_at = (
                datetime.now(timezone.utc) + timedelta(weeks=3)
            ).isoformat()


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute(
        """CREATE TABLE IF NOT EXISTS decisions (
            decision_id TEXT PRIMARY KEY, created_at TEXT, type TEXT,
            player TEXT, action TEXT, thesis TEXT, confidence REAL,
            execute_at TEXT, expires_at TEXT, window TEXT, status TEXT,
            factors TEXT, alternatives TEXT,
            outcome_check_at TEXT, actual_result REAL)"""
    )
    return c


def record(d: Decision) -> str:
    row = asdict(d)
    row["factors"] = json.dumps(row["factors"])
    row["alternatives"] = json.dumps(row["alternatives"])
    with _conn() as c:
        cols = ", ".join(row)
        c.execute(
            f"INSERT OR REPLACE INTO decisions ({cols}) VALUES ({', '.join('?' * len(row))})",
            list(row.values()),
        )
    return d.decision_id


def pending() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM decisions WHERE status IN ('proposed','queued') "
            "AND expires_at > ? ORDER BY execute_at",
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def rejected(limit: int = 50) -> list[dict]:
    """The panel you learn the most from."""
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM decisions WHERE status IN ('expired','overridden') "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def calibration(bins: int = 5) -> list[dict]:
    """When it said 0.7, was it right 70% of the time?

    An agent that is systematically overconfident needs to be caught in
    October, not January. Requires actual_result to be backfilled.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT confidence, actual_result FROM decisions "
            "WHERE actual_result IS NOT NULL"
        ).fetchall()
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [r for r in rows if lo <= r[0] < hi]
        if sel:
            out.append(
                {
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "n": len(sel),
                    "predicted": round(sum(r[0] for r in sel) / len(sel), 3),
                    "actual": round(sum(r[1] for r in sel) / len(sel), 3),
                }
            )
    return out
