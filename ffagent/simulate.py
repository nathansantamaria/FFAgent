"""Monte Carlo draft simulation.

The question every pick comes down to is not "who is best" but "who will still
be here next turn". ADP gives a mean; it does not give you a probability. This
samples each player's draft position from his own ADP distribution a few
thousand times and counts how often he survives to a given pick.

Two modelling choices worth stating, because they are where this could be
wrong:

**Sampling is per-player and independent.** Real drafts are correlated -- one
manager taking a quarterback makes the next one more likely to. Independent
sampling therefore understates run risk and slightly overstates survival for
the positions that run (QB, TE). Treated as a known bias rather than corrected,
because correcting it properly needs league-specific behaviour we do not have.

**FFC's `teams` parameter is ignored.** Verified 2026-08-31: teams=10 and
teams=12 return byte-identical payloads from the same 8,161 drafts. So this is
blended-format ADP. In a 10-team league the practical effect is that QB, TE, K
and DEF go LATER than these numbers imply (fewer teams, same starters), while
RB and WR hold roughly true. `format_shift` applies a crude correction and
flags it rather than hiding it.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data" / "adp10.csv"

# Positions that go later in a 10-team league than blended ADP suggests.
FORMAT_SHIFT = {"QB": 4.0, "TE": 3.0, "K": 8.0, "DEF": 6.0}


@dataclass
class Pick:
    round: int
    overall: int


def pick_numbers(slot: int, teams: int, rounds: int = 15) -> list[Pick]:
    out = []
    for r in range(1, rounds + 1):
        p = (r - 1) * teams + (slot if r % 2 == 1 else teams - slot + 1)
        out.append(Pick(r, p))
    return out


def load_adp(path: Path = DATA, format_shift: bool = True,
             apply_news: bool = True) -> list[dict]:
    """Load ADP, then remove anyone the news says cannot play.

    News is applied BEFORE simulation, not after. Simulating a player who
    cannot take the field produces a survival probability, which looks like
    information and is worse than nothing -- it is a confident number about a
    non-option.
    """
    rows = []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            adp = float(r["adp"])
            if format_shift:
                adp += FORMAT_SHIFT.get(r["pos"], 0.0)
            rows.append({"name": r["name"], "pos": r["pos"], "team": r["team"],
                         "adp": adp, "stdev": max(0.5, float(r["stdev"]))})
    if apply_news:
        from . import news
        rows, _rep = news.apply(rows)
    return rows


def simulate(players: list[dict], n: int = 20000, seed: int = 11) -> np.ndarray:
    """Sample each player's draft slot n times. Returns (n_players, n) matrix.

    Lognormal-ish skew: a player can slide a long way further than he can rise,
    because rising is capped by pick 1 and sliding is not. A symmetric normal
    puts real mass on impossible picks for the top of the board.
    """
    rng = np.random.default_rng(seed)
    adp = np.array([p["adp"] for p in players])[:, None]
    sd = np.array([p["stdev"] for p in players])[:, None]
    draws = rng.normal(adp, sd, size=(len(players), n))
    skew = rng.exponential(sd * 0.45, size=(len(players), n))
    return np.maximum(1.0, draws + skew - sd * 0.45)


def survival(players: list[dict], draws: np.ndarray, pick: int) -> list[tuple[str, str, float, float]]:
    """P(still available at `pick`) for every player."""
    avail = (draws > pick).mean(axis=1)
    return [(p["name"], p["pos"], p["adp"], float(a)) for p, a in zip(players, avail)]


def board_at(players, draws, pick: int, lo: float = 0.15, hi: float = 0.97, top: int = 14):
    """Players genuinely in play: likely enough to be there, good enough to want.

    Filters out both the unreachable (survival near zero) and the guaranteed
    (survival near one). A player who is certainly available is not a decision
    -- he is a fallback, and spending an early pick on him wastes the pick.
    """
    s = survival(players, draws, pick)
    live = [r for r in s if lo <= r[3] <= hi]
    live.sort(key=lambda r: r[2])
    return live[:top]


def report(slot: int, teams: int = 10, rounds: int = 8, n: int = 20000) -> str:
    players = load_adp()
    draws = simulate(players, n=n)
    picks = pick_numbers(slot, teams, rounds)
    out = [f"Monte Carlo, {n:,} simulated drafts — slot {slot} of {teams}", ""]
    for pk in picks:
        live = board_at(players, draws, pk.overall)
        out.append(f"ROUND {pk.round} — pick #{pk.overall}")
        if not live:
            out.append("  nothing in the 15-97% band; board is either picked over or wide open")
        for name, pos, adp, p in live:
            bar = "#" * int(round(p * 18))
            out.append(f"  {p:5.0%} {bar:<18} {name:<24}{pos:<4}adp {adp:.1f}")
        out.append("")
    return "\n".join(out)
