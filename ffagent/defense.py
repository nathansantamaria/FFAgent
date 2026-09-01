"""Defenses ranked by personnel, not by draft cost.

Team defenses are the position where ADP is worst, because it lags roster
construction by months and nobody thinks hard about a round-13 pick. The
scoring is also mostly driven by two things — sacks and turnovers — which
follow from the pass rush and secondary rather than from anything mysterious.
That makes a personnel-based rating genuinely tractable here in a way it is
not for, say, a running back.

The live example this was built around: the Rams traded for Myles Garrett in
June (reigning Defensive Player of the Year, single-season sack record, 23),
and Aaron Donald came out of retirement to join him on 30 August. Their ADP on
31 August was 108.5 — round eleven — because the ADP window is a trailing
average and Donald signed one day before it closed. Seattle was going 27 picks
earlier.

Every override below is sourced and dated. Anything I have not verified stays
at market value rather than being adjusted on vibes, because a confidently
wrong defense rating is worth less than no rating at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DefUnit:
    team: str
    name: str
    rating: float               # projected fantasy points per game
    pass_rush: str = ""
    secondary: str = ""
    moves: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    verified: bool = False

    def why(self) -> list[str]:
        out = []
        if self.pass_rush:
            out.append(f"Pass rush: {self.pass_rush}")
        if self.secondary:
            out.append(f"Secondary: {self.secondary}")
        for m in self.moves:
            out.append(m)
        if not self.verified:
            out.append("No verified personnel change — held at market value.")
        return out


# Verified from multiple outlets, 30-31 Aug 2026.
OVERRIDES: dict[str, DefUnit] = {
    "LAR": DefUnit(
        "LAR", "LA Rams Defense", rating=11.4,
        pass_rush="Myles Garrett and Aaron Donald on the same line. Five combined "
                  "Defensive Player of the Year awards, 236.5 career sacks.",
        secondary="Trent McDuffie acquired from Kansas City and extended; "
                  "Jaylen Watson signed alongside him.",
        moves=[
            "Garrett traded from Cleveland in June 2026 — reigning DPOY, "
            "record 23 sacks last season.",
            "Donald unretired 30 Aug 2026 on a one-year deal after two seasons away.",
            "ADP of 108.5 is a trailing average whose window closed 31 Aug, so the "
            "Donald signing is essentially unpriced. This is the largest gap between "
            "personnel and draft cost anywhere on the board.",
        ],
        sources=["NFL.com", "ESPN", "CBS Sports", "PFF"], verified=True),
}

# Market baseline: rating implied by ADP, for teams with no verified override.
# Deliberately flat — the true spread between DEF1 and DEF10 is small, and
# pretending otherwise is how a kicker ends up drafted in round seven.
MARKET_BASE = 8.6
MARKET_SLOPE = 0.9      # points from best to worst of the drafted defenses


def rate(team: str, name: str, adp: float, all_def_adps: list[float]) -> DefUnit:
    o = OVERRIDES.get(team)
    if o:
        return o
    if not all_def_adps:
        return DefUnit(team, name, MARKET_BASE)
    lo, hi = min(all_def_adps), max(all_def_adps)
    frac = 0.0 if hi == lo else (adp - lo) / (hi - lo)
    return DefUnit(team, name, round(MARKET_BASE + MARKET_SLOPE * (1 - frac), 2))


def apply(board, skip: set | None = None) -> list:
    """Rewrite defense projections from personnel, then re-rank within DEF.

    `skip` holds names whose projection has already been blended with live
    results and must not be overwritten. Without it this ran after the blend
    and silently reset every defence to its preseason personnel rating — the
    in-season update looked implemented and did nothing for the position.
    """
    skip = skip or set()
    defs = [x for x in board if x.pos == "DEF" and x.name not in skip]
    adps = [x.adp for x in board if x.pos == "DEF"]
    for x in defs:
        team = x.team or x.name.split()[0][:3].upper()
        u = rate(team, x.name, x.adp, adps)
        x.proj = u.rating
        x.value = round(u.rating * 0.98, 2)     # defenses are volatile week to week
        x.def_unit = u
    return board
