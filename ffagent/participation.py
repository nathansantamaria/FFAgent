"""Play-level participation: route rate, and separating a back from his line.

This is the best data in the project and I had not been using it. Earlier work
leaned on snap share as the role signal, which is a proxy. `pbp_participation`
lists the actual player ids on the field for every play, so route
participation — the share of his team's dropbacks a receiver was on the field
for — can be computed directly rather than approximated.

Why it matters more than snap share: a receiver can lead his team in snaps
while running routes on two-thirds of them, because run-blocking snaps count
the same in a snap-share number and are worth nothing in PPR. Route rate is
the denominator that target share should actually be measured against, and it
moves before targets do.

The second thing here is `pfr_advstats/rush`, which splits rushing yards into
before and after contact. That distinguishes a back producing behind a good
line from one creating on his own — the first regresses when the line changes,
the second travels. Ranking backs without it means treating those as the same
player.

Both are expensive to compute (45k plays a season), so this runs on the weekly
refresh rather than every job.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
DATA = Path(__file__).resolve().parent.parent / "data"

# A dropback is where routes happen. Rushing plays tell you nothing about a
# receiver's role, and including them is what makes snap share a blunt signal.
PASS_TYPES = {"pass"}


@dataclass
class RouteRate:
    gsis_id: str
    routes: int
    team_dropbacks: int
    targets: int = 0

    @property
    def rate(self) -> float:
        return self.routes / self.team_dropbacks if self.team_dropbacks else 0.0

    @property
    def tprr(self) -> float:
        """Targets per route run.

        The cleanest measure of how much the offence wants to throw to a player,
        because it divides out both team pace and his own availability. A high
        route rate with low TPRR is a decoy; the reverse is someone whose role
        is about to grow.
        """
        return self.targets / self.routes if self.routes else 0.0


def load_participation(season: int) -> pd.DataFrame | None:
    try:
        return pd.read_parquet(
            f"{BASE}/pbp_participation/pbp_participation_{season}.parquet")
    except Exception:
        return None


def route_rates(season: int, through_week: int | None = None) -> dict[str, RouteRate]:
    """Route participation per player, from actual on-field personnel."""
    pp = load_participation(season)
    if pp is None or not len(pp):
        return {}
    if through_week is not None and "week" in pp.columns:
        pp = pp[pp["week"] <= through_week]

    # A play with a recorded route is a dropback. `route` is populated on
    # essentially every pass play in this dataset (45,175 of 45,184).
    drops = pp[pp["route"].notna()] if "route" in pp.columns else pp
    if not len(drops):
        return {}

    # Denominator must be his team's dropbacks IN THE GAMES HE PLAYED, not the
    # season total. Dividing by the season put Tyreek Hill at a 13% route rate
    # when he had simply missed most of the year -- a number that reads as
    # "decoy" and means "injured". Role and availability are different
    # questions and this is exactly where they get conflated.
    gcol = "nflverse_game_id" if "nflverse_game_id" in drops.columns else "old_game_id"
    game_drops = drops.groupby([gcol, "possession_team"]).size().to_dict()

    counts: dict[str, int] = {}
    denom: dict[str, int] = {}
    seen_games: dict[str, set] = {}
    for gid, team, ids in zip(drops[gcol], drops["possession_team"], drops["offense_players"]):
        if not isinstance(ids, str):
            continue
        for pid in ids.split(";"):
            if not pid:
                continue
            counts[pid] = counts.get(pid, 0) + 1
            key = (gid, team)
            sg = seen_games.setdefault(pid, set())
            if key not in sg:
                sg.add(key)
                denom[pid] = denom.get(pid, 0) + game_drops.get(key, 0)

    return {pid: RouteRate(pid, n, denom.get(pid, 0)) for pid, n in counts.items()
            if denom.get(pid)}


def attach_targets(rates: dict[str, RouteRate], season: int) -> dict[str, RouteRate]:
    try:
        st = pd.read_parquet(f"{BASE}/stats_player/stats_player_week_{season}.parquet")
    except Exception:
        return rates
    st = st[st["week"] <= 18]
    tg = st.groupby("player_id")["targets"].sum().to_dict()
    for pid, r in rates.items():
        r.targets = int(tg.get(pid, 0) or 0)
    return rates


def rushing_efficiency(season: int) -> pd.DataFrame:
    """Yards before and after contact, per back.

    Before-contact yards are mostly the offensive line. After-contact yards are
    mostly the runner. A back whose production is nearly all before contact is
    a bet on his line staying healthy, which is a different and worse bet.
    """
    try:
        df = pd.read_parquet(f"{BASE}/pfr_advstats/advstats_week_rush_{season}.parquet")
    except Exception:
        return pd.DataFrame()
    g = df.groupby(["pfr_player_id", "pfr_player_name"]).agg(
        carries=("carries", "sum"),
        ybc=("rushing_yards_before_contact", "sum"),
        yac=("rushing_yards_after_contact", "sum"),
        broken=("rushing_broken_tackles", "sum")).reset_index()
    g = g[g["carries"] >= 40]
    # Quarterbacks dominate yards-before-contact by construction — a scramble is
    # all before contact — and they were topping the "line-dependent" list,
    # which is meaningless. Restrict to actual backs.
    try:
        xw = pd.read_parquet(f"{BASE}/players/players.parquet")[["pfr_id", "position"]]
        g = g.merge(xw, left_on="pfr_player_id", right_on="pfr_id", how="left")
        g = g[g["position"].isin(["RB", "FB"])]
    except Exception:
        pass
    g["ybc_per"] = (g["ybc"] / g["carries"]).round(2)
    g["yac_per"] = (g["yac"] / g["carries"]).round(2)
    # Share of total yardage the runner created himself.
    g["self_created"] = (g["yac"] / (g["ybc"] + g["yac"]).replace(0, 1)).round(3)
    g["broken_per"] = (g["broken"] / g["carries"]).round(3)
    return g.sort_values("self_created", ascending=False)


def summarise(season: int, top: int = 12) -> str:
    rates = attach_targets(route_rates(season), season)
    xw = pd.read_parquet(f"{BASE}/players/players.parquet")
    name = dict(zip(xw["gsis_id"].astype(str), xw["display_name"]))
    pos = dict(zip(xw["gsis_id"].astype(str), xw["position"]))
    rows = [(name.get(k, k), pos.get(k, "?"), v.rate, v.routes, v.tprr)
            for k, v in rates.items()
            if pos.get(k) in ("WR", "TE", "RB") and v.routes >= 150]
    rows.sort(key=lambda r: -r[4])
    out = [f"Targets per route run, {season} (min 150 routes)"]
    for n, p, rate, routes, t in rows[:top]:
        out.append(f"  {p:<4}{n:<24}route rate {rate:5.0%}  {routes:>4} routes  TPRR {t:.3f}")
    return "\n".join(out)
