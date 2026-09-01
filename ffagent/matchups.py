"""Matchup strength: how much each defence gives up, by position.

The spread is large enough to change a start/sit call on its own. Measured on
2025: 15.6 fantasy points a game separate the most and least generous defence
against receivers, 11.4 against backs. That is bigger than the gap between many
flex options, which is the whole reason this exists.

Two cautions that shape how it is used:

**Points allowed by position is partly a schedule artefact.** A defence that
happened to face three elite receiving corps looks generous and may not be. It
is shrunk toward the league mean by games played for that reason, and it is
weighted as one input rather than treated as an answer.

**It describes last season.** Personnel moves invalidate it — the Rams added
Myles Garrett and Aaron Donald, so their 2025 numbers understate them. Where a
verified change exists in `defense.OVERRIDES`, the rating is adjusted and the
adjustment is stated.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
POSITIONS = ("QB", "RB", "WR", "TE")


@dataclass
class Matchup:
    defense: str
    position: str
    allowed_pg: float          # fantasy points allowed per game, shrunk
    rank: int                  # 1 = most generous
    of: int
    league_avg: float
    note: str = ""

    @property
    def edge(self) -> float:
        """Points above or below an average matchup."""
        return round(self.allowed_pg - self.league_avg, 2)

    def describe(self) -> str:
        d = "above" if self.edge > 0 else "below"
        return (f"{self.defense} allowed {self.allowed_pg:.1f} to {self.position}s, "
                f"{abs(self.edge):.1f} {d} league average, rank {self.rank} of {self.of}")


def allowed_by_position(season: int = 2025, prior_games: float = 6.0) -> dict:
    """Fantasy points allowed per game, by defence and position.

    Shrunk toward the league mean by games observed. A defence with a short or
    lopsided sample is pulled back toward average rather than trusted, which is
    the same correction the durability and kicker ratings needed.
    """
    try:
        st = pd.read_parquet(f"{BASE}/stats_player/stats_player_week_{season}.parquet")
    except Exception:
        return {}
    st = st[(st["week"] <= 18) & st["position"].isin(POSITIONS)]
    if "opponent_team" not in st.columns:
        return {}

    g = (st.groupby(["opponent_team", "position"])
           .agg(pts=("fantasy_points_ppr", "sum"), wk=("week", "nunique"))
           .reset_index())
    g["raw"] = g["pts"] / g["wk"].clip(lower=1)

    out: dict = {}
    for pos in POSITIONS:
        sub = g[g["position"] == pos]
        if not len(sub):
            continue
        mean = float(sub["raw"].mean())
        rows = []
        for _, r in sub.iterrows():
            n = float(r["wk"])
            shrunk = (r["raw"] * n + mean * prior_games) / (n + prior_games)
            rows.append((str(r["opponent_team"]), round(shrunk, 2)))
        rows.sort(key=lambda t: -t[1])
        for i, (team, val) in enumerate(rows, 1):
            out[(team, pos)] = Matchup(team, pos, val, i, len(rows), round(mean, 2))
    return out


def schedule(season: int = 2026) -> dict:
    """team -> {week: opponent}. Falls back to empty if unpublished."""
    for src in (f"{BASE}/schedules/schedules.parquet",
                f"{BASE}/pbp/play_by_play_{season}.parquet"):
        try:
            df = pd.read_parquet(src)
        except Exception:
            continue
        cols = set(df.columns)
        if {"season", "week", "home_team", "away_team"} <= cols:
            df = df[df["season"] == season].drop_duplicates(["week", "home_team", "away_team"])
            out: dict = {}
            for _, r in df.iterrows():
                out.setdefault(str(r["home_team"]), {})[int(r["week"])] = str(r["away_team"])
                out.setdefault(str(r["away_team"]), {})[int(r["week"])] = str(r["home_team"])
            return out
    return {}


def rate(player_team: str, position: str, opponent: str,
         table: dict | None = None) -> Matchup | None:
    table = table if table is not None else allowed_by_position()
    return table.get((opponent, position))
