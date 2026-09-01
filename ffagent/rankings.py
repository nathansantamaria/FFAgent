"""Cumulative rankings that get less wrong as the season goes on.

The core idea: a preseason projection is a *prior*, not an answer. Every week
of real football is evidence against it, and the weight should shift
accordingly — automatically, not because someone remembered to.

In week 1 an ESPN projection is nearly all we have and deserves most of the
weight. By week 8 a player has eight games of actual usage and scoring, and
continuing to lean on a projection written in August is the single most common
way ranking systems go stale. So the blend is a function of games played:

    w_season = games / (games + K)      with K = 4

which gives in-season data 20% weight after one game, 50% after four, 75%
after twelve. K = 4 is a judgement, not a fitted constant, and it is the one
number here most worth revisiting once outcomes are logged.

Three things beyond the blend:

**Role changes are applied as a multiplier on opportunity, not a nudge to the
output.** When Josh Jacobs went on the exempt list, MarShawn Lloyd did not
become 10% better — he inherited a backfield. Modelling that as a small bump
would be wrong in both directions: too small to matter if it is real, and
unjustifiable if it is not.

**Rankings are snapshotted every run**, so movement is a fact rather than an
impression. Without history you cannot tell a player who quietly climbed six
places over a fortnight from one who jumped today.

**Nothing is discarded.** Each ranking carries the evidence that produced it,
so the dashboard can explain a change rather than just show it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "rankings.db"

# Games needed before in-season evidence outweighs the preseason prior.
BLEND_K = 4.0

# How much a role change scales opportunity. These are multipliers on
# projected volume, deliberately coarse: the evidence for "he is now the
# starter" is categorical, and dressing it up as 1.37 would imply a precision
# the source does not have.
ROLE_MULTIPLIER = {
    "inherits_backfield": 1.85,
    "inherits_target_share": 1.45,
    "promoted_starter": 1.35,
    "committee_added": 0.72,
    "demoted": 0.55,
    "blocked": 0.0,
}


@dataclass
class Evidence:
    source: str
    value: float          # points per game implied
    weight: float
    note: str = ""

    def as_dict(self) -> dict:
        return {"source": self.source, "value": round(self.value, 2),
                "weight": round(self.weight, 3), "note": self.note}


@dataclass
class Ranking:
    name: str
    pos: str
    team: str
    proj: float
    evidence: list[Evidence] = field(default_factory=list)
    role: str = ""
    games: int = 0
    rank: int = 0
    prev_rank: int | None = None

    @property
    def movement(self) -> int | None:
        if self.prev_rank is None:
            return None
        return self.prev_rank - self.rank      # positive = moved up

    def explain(self) -> list[str]:
        out = []
        for e in sorted(self.evidence, key=lambda x: -x.weight):
            line = f"{e.source}: {e.value:.1f} pts/gm at {e.weight:.0%} weight"
            if e.note:
                line += f" — {e.note}"
            out.append(line)
        if self.role:
            m = ROLE_MULTIPLIER.get(self.role, 1.0)
            out.append(f"Role change '{self.role.replace('_',' ')}' applied as a "
                       f"×{m:.2f} multiplier on opportunity, not a nudge to the output.")
        if self.games:
            w = self.games / (self.games + BLEND_K)
            out.append(f"{self.games} games played this season, so live data carries "
                       f"{w:.0%} of the weight and the preseason projection {1-w:.0%}.")
        else:
            out.append("No games played yet — this is entirely projection, and should be "
                       "treated as a prior rather than a finding.")
        return out


def blend(preseason: float, in_season: float | None, games: int) -> tuple[float, float]:
    """Return (projection, in-season weight)."""
    if in_season is None or games <= 0:
        return preseason, 0.0
    w = games / (games + BLEND_K)
    return preseason * (1 - w) + in_season * w, w


def build(board, in_season: dict | None = None,
          roles: dict | None = None) -> list[Ranking]:
    """Compose today's rankings from every source available.

    `board` is myboard.build() output. `in_season` maps name -> (ppg, games)
    from actual games this season. `roles` maps name -> a ROLE_MULTIPLIER key.
    """
    in_season = in_season or {}
    roles = roles or {}
    out: list[Ranking] = []

    for x in board:
        ev = [
            Evidence("ESPN 2026 projection", x.espn_proj or x.proj, 0.45,
                     "the only forward-looking source"),
            Evidence("my 2025 production model", x.own_proj or x.proj, 0.35,
                     "backward-looking by construction"),
            Evidence("market ADP implied", x.adp and x.proj or x.proj, 0.20,
                     "what the field believes"),
        ]
        pre = x.proj
        ppg, games = in_season.get(x.name, (None, 0))
        proj, w = blend(pre, ppg, games)
        if ppg is not None and games:
            ev.append(Evidence(f"{games} games this season", ppg, w,
                               "live evidence, outweighs projection as it accumulates"))

        role = roles.get(x.name, "")
        if role:
            proj *= ROLE_MULTIPLIER.get(role, 1.0)

        # durability is a discount on availability, applied last so it does not
        # get diluted by the blend
        proj *= x.avail

        out.append(Ranking(x.name, x.pos, x.team, round(proj, 2), ev, role, games))

    out.sort(key=lambda r: -r.proj)
    for i, r in enumerate(out, 1):
        r.rank = i
    return out


# --- persistence --------------------------------------------------------

def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS snapshots (
        taken_on TEXT, name TEXT, pos TEXT, rank INT, proj REAL,
        role TEXT, games INT, evidence TEXT,
        PRIMARY KEY (taken_on, name))""")
    return c


def snapshot(rankings: list[Ranking], on: str | None = None) -> str:
    """Persist a run. Keyed on a full TIMESTAMP, not a date.

    Keying on the date meant the second refresh of a day overwrote the first,
    so `previous()` found nothing earlier and movement was always blank. With
    thirteen refresh windows a week that is most of them — the feature would
    have looked implemented and silently done nothing.
    """
    # Microseconds, not seconds: two refreshes inside the same second collided
    # on the primary key and the earlier one vanished. Real runs are hours
    # apart, but a system whose correctness depends on that is one bad cron
    # entry away from silently losing its own history.
    on = on or datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with _conn() as c:
        for r in rankings:
            c.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?)",
                      (on, r.name, r.pos, r.rank, r.proj, r.role, r.games,
                       json.dumps([e.as_dict() for e in r.evidence])))
    return on


def previous(before: str | None = None) -> dict[str, int]:
    """Most recent snapshot strictly before `before`. Returns name -> rank."""
    before = before or datetime.now(timezone.utc).isoformat(timespec="microseconds")
    with _conn() as c:
        row = c.execute("SELECT MAX(taken_on) FROM snapshots WHERE taken_on < ?",
                        (before,)).fetchone()
        if not row or not row[0]:
            return {}
        rows = c.execute("SELECT name, rank FROM snapshots WHERE taken_on = ?",
                         (row[0],)).fetchall()
    return dict(rows)


def with_movement(rankings: list[Ranking]) -> list[Ranking]:
    prev = previous()
    for r in rankings:
        r.prev_rank = prev.get(r.name)
    return rankings


def history(name: str, limit: int = 30) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT taken_on, rank, proj FROM snapshots "
                         "WHERE name = ? ORDER BY taken_on DESC LIMIT ?",
                         (name, limit)).fetchall()
    return [{"on": a, "rank": b, "proj": c_} for a, b, c_ in rows][::-1]


def biggest_moves(rankings: list[Ranking], n: int = 8) -> list[Ranking]:
    moved = [r for r in rankings if r.movement not in (None, 0)]
    moved.sort(key=lambda r: -abs(r.movement or 0))
    return moved[:n]


def run(board, in_season=None, roles=None) -> list[Ranking]:
    """One refresh: build, compare against the last run, persist.

    Order matters — movement is computed BEFORE persisting, otherwise the run
    compares against itself and every player shows no change.
    """
    rk = with_movement(build(board, in_season, roles))
    snapshot(rk)
    return rk
