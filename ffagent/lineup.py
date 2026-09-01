"""Lineup optimisation.

Two separate jobs that get conflated and shouldn't be:

1. **Projection** -- how many points will this player score? This is the weak
   link in the whole system and I want that stated plainly rather than buried.
   We are not going to out-project the market. What we have is a usage prior
   that adjusts a baseline, which helps at the margin and nowhere near as much
   as the optimiser below.

2. **Assignment** -- given projections, which legal lineup maximises points?
   This part is exact and worth doing properly. Greedy fills fail on flex:
   putting your best remaining player in FLEX can strand a WR-only slot.
   We solve it as max-weight bipartite matching instead.

The assignment is where the reliable value is. It is unglamorous, it never
gets tired in week 13, and humans lose points to it every single week.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

from .config import FLEX_MAP, LeagueConfig

# Slots that accept exactly one position
DIRECT = {"QB", "RB", "WR", "TE", "K", "DEF", "DST"}


def slot_accepts(slot: str, pos: str) -> bool:
    if slot in FLEX_MAP:
        return pos in FLEX_MAP[slot]
    if slot in ("DEF", "DST"):
        return pos in ("DEF", "DST")
    return slot == pos


@dataclass
class Player:
    player_id: str
    name: str
    pos: str
    proj: float
    status: str = ""          # "", Out, Doubtful, Questionable, IR, BYE
    opponent: str = ""

    @property
    def playable(self) -> bool:
        return self.status.upper() not in ("OUT", "IR", "BYE", "DNP", "SUSP")


@dataclass
class Lineup:
    assignment: dict[str, Player]      # slot label -> player
    bench: list[Player]
    total: float
    unfilled: list[str]

    def _by_base(self) -> dict[str, list["Player"]]:
        g: dict[str, list[Player]] = {}
        for lab, p in self.assignment.items():
            g.setdefault(lab.rstrip("0123456789") or lab, []).append(p)
        return g

    def diff(self, other: "Lineup") -> list[tuple[str, str, str]]:
        """(slot, out, in) for every write the browser actually has to make.

        Compares players *per slot type*, not per label. RB1 and RB2 are an
        artefact of how we number duplicate slots -- Sleeper does not
        distinguish them, and the Hungarian solver assigns them in arbitrary
        order. Diffing on labels reports two writes every time two backs swap
        numbers, which is two needless clicks against a deadline.
        """
        mine, theirs = self._by_base(), other._by_base()
        out: list[tuple[str, str, str]] = []
        for base in mine.keys() | theirs.keys():
            now = {p.player_id: p for p in mine.get(base, [])}
            was = {p.player_id: p for p in theirs.get(base, [])}
            came = [p for i, p in now.items() if i not in was]
            went = [p for i, p in was.items() if i not in now]
            for k, p in enumerate(came):
                gone = went[k].name if k < len(went) else "(empty)"
                out.append((base, gone, p.name))
        return out

    def player_diff(self, other: "Lineup") -> tuple[list[Player], list[Player]]:
        """(entering, leaving) -- who actually joined or left the lineup.

        The honest unit of change. A player who slides from WR2 to WR1 has not
        entered or left anything, and reporting him as a change is how you end
        up telling someone their healthy receiver is unavailable.
        """
        mine = {p.player_id: p for p in self.assignment.values()}
        theirs = {p.player_id: p for p in other.assignment.values()}
        entering = [p for i, p in mine.items() if i not in theirs]
        leaving = [p for i, p in theirs.items() if i not in mine]
        return entering, leaving


def optimise(
    players: list[Player],
    cfg: LeagueConfig,
    current: dict[str, Player] | None = None,
) -> Lineup:
    """Exact max-weight assignment of players to starting slots.

    `current` is the lineup already set. Passing it adds a tiny bonus for
    leaving a player where he is, which breaks ties toward the incumbent.
    Without it the optimiser returns an equally-good-but-different assignment
    and every week looks like a cascade of changes: player A shuffles WR2->WR1,
    B takes WR2, C takes flex. Same points, three extra writes on a Sunday
    deadline, and an explanation that reads like nonsense.
    """
    slots: list[str] = list(cfg.starters)
    avail = [p for p in players if p.playable]

    if not slots:
        return Lineup({}, list(players), 0.0, [])

    # Rows = slots, cols = players. Pad with dummy players so the matrix is
    # square and unfillable slots simply take a zero-value dummy.
    n = max(len(slots), len(avail))
    cost = np.full((n, n), 0.0)
    NEG = -1e6
    # slot label -> incumbent player_id, for the stickiness bonus
    # Duplicate slots (WR1/WR2) share one base name, so this must be a set of
    # incumbents per base slot -- a dict overwrites and only the last player
    # keeps his bonus, which reintroduces the cascade this exists to prevent.
    incumbent: dict[str, set[str]] = {}
    if current:
        for lab, p in current.items():
            base = lab.rstrip("0123456789") or lab
            incumbent.setdefault(base, set()).add(p.player_id)
    EPS = 1e-3
    for i, slot in enumerate(slots):
        for j, p in enumerate(avail):
            if not slot_accepts(slot, p.pos):
                cost[i, j] = NEG
                continue
            stay = EPS if p.player_id in incumbent.get(slot, ()) else 0.0
            cost[i, j] = p.proj + stay
    # dummy columns stay 0 -> chosen only when nothing legal is available
    row, col = linear_sum_assignment(cost, maximize=True)

    assignment: dict[str, Player] = {}
    used: set[int] = set()
    unfilled: list[str] = []
    # label duplicate slots RB1/RB2 so the UI and the write layer can address them
    seen: dict[str, int] = {}
    for i, j in zip(row, col):
        if i >= len(slots):
            continue
        slot = slots[i]
        seen[slot] = seen.get(slot, 0) + 1
        label = f"{slot}{seen[slot]}" if slots.count(slot) > 1 else slot
        if j < len(avail) and cost[i, j] > NEG / 2:
            assignment[label] = avail[j]
            used.add(j)
        else:
            unfilled.append(label)

    bench = [p for k, p in enumerate(avail) if k not in used]
    bench += [p for p in players if not p.playable]
    total = sum(p.proj for p in assignment.values())
    return Lineup(assignment, bench, round(total, 2), unfilled)


def project(
    recent_ppr: float,
    season_ppr: float,
    usage_edge: float = 0.0,
    signal_confidence: float = 0.0,
    games: int = 0,
) -> float:
    """Baseline projection with a usage tilt.

    Honest about what this is: a blend of recent and season-long scoring,
    nudged by the usage divergence. The nudge is deliberately small and scaled
    by signal confidence -- during a cold start it does almost nothing, which
    is correct. If you later wire in a real projection source, replace this
    function and leave everything else alone.
    """
    if games <= 0:
        return 0.0
    w_recent = min(0.7, 0.25 + 0.08 * games)
    base = w_recent * recent_ppr + (1 - w_recent) * season_ppr
    tilt = 0.85 * usage_edge * signal_confidence
    return round(max(0.0, base + tilt), 2)


def explain(before: Lineup, after: Lineup) -> list[str]:
    """Plain sentences for the decision log. No jargon -- these end up on the
    dashboard and in a notification you read on a phone on Sunday morning."""
    out = []
    entering, leaving = after.player_diff(before)
    for gone in leaving:
        why = f" ({gone.status.lower()})" if gone.status else ""
        out.append(f"Bench {gone.name}{why}, {gone.proj:.1f} projected")
    for came in entering:
        slot = next((s for s, p in after.assignment.items() if p.player_id == came.player_id), "?")
        out.append(f"Start {came.name} at {slot}, {came.proj:.1f} projected")
    if entering or leaving:
        out.append(f"Net {after.total - before.total:+.1f} projected points")
    if after.unfilled:
        out.append(f"Cannot fill {', '.join(after.unfilled)} — no eligible healthy player.")
    return out
