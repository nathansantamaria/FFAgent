"""Score raw stats using THIS league's rules.

nflverse ships `fantasy_points_ppr`, which is convenient and wrong for most
leagues: it hardcodes 1.0 per reception and ignores everything else a
commissioner can change. Half-PPR, TE premium, 6-point passing touchdowns,
first-down bonuses, yardage bonuses -- all of it silently disappears if you
use the precomputed column, and every downstream projection, waiver claim and
trade gate inherits the error.

So we recompute from raw stats against `league.scoring_settings`. Sleeper
returns those settings for every league, so this is free correctness.
"""
from __future__ import annotations

import pandas as pd

from .config import LeagueConfig

# Sleeper scoring key -> nflverse stat column, or a list of columns to sum.
# Fumbles are the reason a list is needed: nflverse has no single
# `fumbles_lost` column, it splits them across rushing, receiving and sacks.
# Mapping to a name that does not exist fails silently and simply never
# subtracts the penalty, which is exactly the kind of quiet wrongness that
# makes projections drift without anyone noticing.
STAT_MAP: dict[str, str | list[str]] = {
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "passing_interceptions",
    "pass_2pt": "passing_2pt_conversions",
    "pass_fd": "passing_first_downs",
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rush_2pt": "rushing_2pt_conversions",
    "rush_fd": "rushing_first_downs",
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "rec_2pt": "receiving_2pt_conversions",
    "rec_fd": "receiving_first_downs",
    "fum_lost": ["rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost"],
    "fum": ["rushing_fumbles", "receiving_fumbles", "sack_fumbles"],
}

# Position-conditional bonuses (TE premium is the common one).
POSITION_BONUS = {"bonus_rec_te": ("TE", "receptions"),
                  "bonus_rec_rb": ("RB", "receptions"),
                  "bonus_rec_wr": ("WR", "receptions")}

# Yardage-threshold bonuses: key -> (column, threshold)
THRESHOLD_BONUS = {
    "bonus_rush_yd_100": ("rushing_yards", 100),
    "bonus_rec_yd_100": ("receiving_yards", 100),
    "bonus_pass_yd_300": ("passing_yards", 300),
    "bonus_rush_yd_200": ("rushing_yards", 200),
    "bonus_rec_yd_200": ("receiving_yards", 200),
}


def score_frame(df: pd.DataFrame, cfg: LeagueConfig) -> pd.Series:
    """Fantasy points per row under this league's rules.

    Missing columns are treated as zero rather than raising: nflverse renames
    things between seasons and a projection pipeline that dies because one
    bonus column vanished is worse than one that scores without it.
    """
    s = cfg.scoring or {}
    pts = pd.Series(0.0, index=df.index)
    applied: list[str] = []

    missing: list[str] = []
    for key, cols in STAT_MAP.items():
        w = s.get(key)
        if not w:
            continue
        names = [cols] if isinstance(cols, str) else cols
        present = [c for c in names if c in df.columns]
        if not present:
            missing.append(key)
            continue
        total = sum(df[c].fillna(0).astype(float) for c in present)
        pts = pts + total * float(w)
        applied.append(key)

    for key, (pos, col) in POSITION_BONUS.items():
        w = s.get(key)
        if not w or col not in df.columns or "position" not in df.columns:
            continue
        pts = pts + (df["position"] == pos) * df[col].fillna(0).astype(float) * float(w)
        applied.append(key)

    for key, (col, thresh) in THRESHOLD_BONUS.items():
        w = s.get(key)
        if not w or col not in df.columns:
            continue
        pts = pts + (df[col].fillna(0) >= thresh) * float(w)
        applied.append(key)

    pts.attrs["applied"] = applied
    # Surfaced rather than swallowed: a scoring rule the league uses that we
    # cannot compute is a known bias in every projection downstream.
    pts.attrs["unscored"] = missing
    return pts


def describe(cfg: LeagueConfig) -> str:
    """What actually differs from vanilla PPR, in plain words.

    Worth printing on every run. A league with 6-point passing TDs and a TE
    premium behaves nothing like the default, and it is the sort of thing you
    discover in week 6 if nobody surfaces it in week 1.
    """
    s = cfg.scoring or {}
    out = []
    rec = float(s.get("rec", 0))
    out.append({0.0: "standard (no PPR)", 0.5: "half PPR", 1.0: "full PPR"}.get(rec, f"{rec} per reception"))
    if s.get("pass_td", 4) != 4:
        out.append(f"{s['pass_td']}-point passing TDs")
    for k, label in (("bonus_rec_te", "TE premium"), ("bonus_rec_rb", "RB reception bonus"),
                     ("bonus_rec_wr", "WR reception bonus")):
        if s.get(k):
            out.append(f"{label} +{s[k]}/catch")
    for k in ("rec_fd", "rush_fd", "pass_fd"):
        if s.get(k):
            out.append(f"first-down bonus ({k.split('_')[0]}) +{s[k]}")
    for k, (_c, t) in THRESHOLD_BONUS.items():
        if s.get(k):
            out.append(f"+{s[k]} at {t} yards")
    return ", ".join(out)
