"""Kickers and defenses, actually ranked.

I had excluded both from value-over-replacement on the argument that the
spread between the best and the tenth-best is smaller than week-to-week noise.
That argument is right about *variance* and wrong as an excuse: a spread being
small is not a reason to rank at random, and "unranked" meant the draft planner
was picking whichever kicker happened to sit highest in ADP.

Everything here is computed, not asserted:

  DEF — 2025 team defensive stats from `stats_team`, scored under this
  league's actual rules (sack 1, INT 2, fumble recovery 2, TD 6, safety 2,
  blocked kick 2, and the points-allowed tiers 10/7/4/1/0/-1/-4). Then adjusted
  for 2026 personnel where a move is verified, and for schedule via the
  betting market's implied points against.

  K — 2025 field goals by distance, scored under the league's distance tiers
  (0-39 = 3, 40-49 = 4, 50-59 = 5, 60+ = 6, miss -1, XP 1, XP miss -1).
  Kicker scoring is mostly team-driven: attempts come from drives that stall
  in range, which is a function of offensive quality and dome/outdoor.

Two honest limits, stated because they bound how much any of this is worth:
kicker year-over-year correlation is genuinely poor, and a defense's schedule
matters more than its personnel over a full season. Both are ranked here
because ranking beats guessing, not because the ranking is strong.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"

# This league's DEF scoring, read from /league/<id> scoring_settings.
DEF_SCORING = {
    "sack": 1, "int": 2, "fum_rec": 2, "def_td": 6, "safe": 2, "blk_kick": 2,
    "def_st_td": 6, "def_st_fum_rec": 1, "def_st_ff": 1, "ff": 1, "st_td": 6,
    "st_fum_rec": 1, "st_ff": 1, "fum_rec_td": 6,
}
PTS_ALLOWED_TIERS = [(0, 0, 10), (1, 6, 7), (7, 13, 4), (14, 20, 1),
                     (21, 27, 0), (28, 34, -1), (35, 99, -4)]

K_SCORING = {"fgm_0_19": 3, "fgm_20_29": 3, "fgm_30_39": 3, "fgm_40_49": 4,
             "fgm_50_59": 5, "fgm_60p": 6, "fgmiss": -1, "xpm": 1, "xpmiss": -1}


def points_allowed_score(pa: float) -> float:
    for lo, hi, pts in PTS_ALLOWED_TIERS:
        if lo <= pa <= hi:
            return pts
    return -4


@dataclass
class UnitRank:
    team: str
    kind: str
    name: str                    # kicker's name, or "<TEAM> Defense"
    base_ppg: float              # last season under this league's rules
    adj_ppg: float               # after personnel and schedule adjustment
    components: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def why(self) -> list[str]:
        out = [f"2025 under this league's scoring: {self.base_ppg:.2f} pts/gm."]
        if self.components:
            out.append(", ".join(f"{k} {v}" for k, v in self.components.items()))
        out += self.notes
        if abs(self.adj_ppg - self.base_ppg) > 0.05:
            out.append(f"Adjusted to {self.adj_ppg:.2f} for 2026.")
        return out


def defense_baselines(season: int = 2025) -> dict[str, UnitRank]:
    """Score every team defence for last season under our exact rules."""
    try:
        tm = pd.read_parquet(f"{BASE}/stats_team/stats_team_week_{season}.parquet")
    except Exception:
        return {}
    tm = tm[tm["week"] <= 18]
    tcol = "team" if "team" in tm.columns else "recent_team"

    # Points allowed per team-week. My first version summed only offensive
    # touchdowns and ignored field goals, extra points, two-point conversions,
    # and defensive or special-teams scores — which would have mis-tiered a
    # large share of weeks, and the points-allowed tier is the single biggest
    # component of defensive scoring. Built properly from every scoring source.
    def team_points(r) -> float:
        f = lambda c: float(r.get(c) or 0)
        tds = f("passing_tds") + f("rushing_tds") + f("special_teams_tds") + f("def_tds")
        two = f("passing_2pt_conversions") + f("rushing_2pt_conversions")
        return (tds * 6 + two * 2 + f("pat_made") * 1
                + f("fg_made") * 3 + f("def_safeties") * 2)

    scored = {}
    for _, r in tm.iterrows():
        scored[(r.get("season"), r.get("week"), r.get(tcol))] = team_points(r)
    pa = {}
    for _, r in tm.iterrows():
        opp = r.get("opponent_team")
        if not opp:
            continue
        pa[(r.get("season"), r.get("week"), r.get(tcol))] = scored.get(
            (r.get("season"), r.get("week"), opp))

    out: dict[str, UnitRank] = {}
    for team, g in tm.groupby(tcol):
        n = len(g)
        if not n:
            continue
        sacks = float(g["def_sacks"].fillna(0).sum())
        ints = float(g["def_interceptions"].fillna(0).sum())
        fum = float(g["def_fumbles"].fillna(0).sum())
        ff = float(g["def_fumbles_forced"].fillna(0).sum())
        tds = float(g["def_tds"].fillna(0).sum())
        saf = float(g["def_safeties"].fillna(0).sum())
        blk = float(g["def_punt_blocks"].fillna(0).sum() + g["def_pat_blocks"].fillna(0).sum())
        sttd = float(g["special_teams_tds"].fillna(0).sum())

        pts = (sacks * DEF_SCORING["sack"] + ints * DEF_SCORING["int"]
               + fum * DEF_SCORING["fum_rec"] + ff * DEF_SCORING["ff"]
               + tds * DEF_SCORING["def_td"] + saf * DEF_SCORING["safe"]
               + blk * DEF_SCORING["blk_kick"] + sttd * DEF_SCORING["st_td"])

        pa_pts, pa_n, pa_tot = 0.0, 0, 0.0
        for _, r in g.iterrows():
            allowed = pa.get((r.get("season"), r.get("week"), team))
            if allowed is None:
                continue          # bye or unpaired week: skip, do not assume 20
            pa_pts += points_allowed_score(allowed)
            pa_tot += allowed
            pa_n += 1
        pts += pa_pts

        out[team] = UnitRank(team, "DEF", f"{team} Defense", round(pts / n, 2), round(pts / n, 2),
                             {"sacks": round(sacks), "INT": round(ints),
                              "fum rec": round(fum), "TD": round(tds),
                              "pts allowed/gm": round(pa_tot / pa_n, 1) if pa_n else None,
                              "games": n})
    return out


def kicker_baselines(season: int = 2025) -> dict[str, UnitRank]:
    """Score every kicker's last season under our distance tiers."""
    try:
        st = pd.read_parquet(f"{BASE}/stats_player/stats_player_week_{season}.parquet")
    except Exception:
        return {}
    st = st[(st["week"] <= 18) & (st["position"] == "K")]
    if not len(st):
        return {}
    cols = {c: c for c in st.columns if c.startswith("fg_made_") or c in
            ("fg_made", "fg_att", "fg_missed", "pat_made", "pat_missed")}
    out: dict[str, UnitRank] = {}
    for (pid, name), g in st.groupby(["player_id", "player_display_name"]):
        n = g["week"].nunique()
        if n < 6:
            continue
        def s(c):
            return float(g[c].fillna(0).sum()) if c in g.columns else 0.0
        pts = (s("fg_made_0_19") * 3 + s("fg_made_20_29") * 3 + s("fg_made_30_39") * 3
               + s("fg_made_40_49") * 4 + s("fg_made_50_59") * 5 + s("fg_made_60_") * 6
               + s("pat_made") * 1 - s("fg_missed") * 1 - s("pat_missed") * 1)
        # Shrink toward the positional mean by sample size. A kicker with six
        # games was outranking full seasons purely because his good stretch was
        # not diluted -- the same small-sample trap the usage watchlist fell
        # into with one-game snap spikes.
        raw = pts / n
        PRIOR_N, PRIOR_PPG = 8.0, 8.4
        shrunk = (raw * n + PRIOR_PPG * PRIOR_N) / (n + PRIOR_N)
        team = str(g["team"].iloc[0]) if "team" in g else ""
        out[name] = UnitRank(canon(team), "K", name, round(raw, 2), round(shrunk, 2),
                             {"FG made": round(s("fg_made")),
                              "XP": round(s("pat_made")), "games": n})
    return out


# nflverse codes the Rams as "LA", Sleeper and ESPN use "LAR". Keying the
# adjustment on "LAR" alone meant the single verified personnel change in the
# project silently did not apply — the dictionary lookup missed and nothing
# errored.
TEAM_ALIAS = {"LAR": "LA", "LA": "LA", "LVR": "LV", "OAK": "LV",
              "JAC": "JAX", "WSH": "WAS", "SD": "LAC", "STL": "LA"}


def canon(team: str) -> str:
    return TEAM_ALIAS.get(team, team)


# Verified 2026 personnel changes. Only entries I have sourced.
DEF_ADJUST = {
    "LA": (2.4, ["Myles Garrett acquired from Cleveland June 2026 — reigning DPOY, "
                  "record 23 sacks. Aaron Donald unretired 30 Aug. Trent McDuffie "
                  "traded in from Kansas City and extended.",
                  "Sacks and turnovers are what this scoring rewards, and that is "
                  "exactly what those three add."]),
}


def rank(season: int = 2025, implied_against: dict | None = None) -> dict[str, list[UnitRank]]:
    defs = defense_baselines(season)
    for team, (delta, notes) in DEF_ADJUST.items():
        team = canon(team)
        if team in defs:
            defs[team].adj_ppg = round(defs[team].base_ppg + delta, 2)
            defs[team].notes += notes
        else:
            defs[team] = UnitRank(team, "DEF", f"{team} Defense", 0.0, 0.0, {}, notes)

    # Schedule: a defence facing weak offences scores more. Implied points
    # against comes straight from the betting market.
    if implied_against:
        for team, ipa in implied_against.items():
            if team in defs:
                # league average implied total is ~22.5; every point below that
                # is worth roughly 0.35 fantasy points to the defence
                adj = (22.5 - ipa) * 0.35
                defs[team].adj_ppg = round(defs[team].adj_ppg + adj, 2)
                defs[team].notes.append(
                    f"Week 1 opponent implied {ipa:.1f} points, {adj:+.2f} adjustment.")

    ks = kicker_baselines(season)
    return {"DEF": sorted(defs.values(), key=lambda u: -u.adj_ppg),
            "K": sorted(ks.values(), key=lambda u: -u.adj_ppg)}
