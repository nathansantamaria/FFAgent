"""Live draft adaptation.

The plan in `myboard.draft_plan` is computed from ADP and survival simulation
before anything happens. It is a prior, and the first time someone reaches two
rounds for a quarterback it is wrong. This module replaces it with something
that recomputes from what has actually occurred.

Four things it does that a static plan cannot:

**Re-simulates survival conditioned on reality.** Drafted players are removed
and every remaining ADP is shifted by the observed drift, so "who lasts to my
next pick" is answered against this draft rather than the average of eight
thousand others.

**Measures drift rather than assuming it.** If the room is taking receivers
eight picks ahead of ADP, receivers will keep going early; that is information
about the other nine managers, and it is the only read on them I can get.

**Detects fallers.** A player available well past his ADP is the single
clearest edge in a live draft, because the reason is usually nothing — ADP is
an average and somebody has to be below it.

**Refuses to take a faller that costs something.** This is the part that
matters. A great value at a position I already have four of, taken in a round
where I still need a starter elsewhere, is not value — it is a bench player
bought with a starting slot. Every faller is checked against what the pick
would otherwise have bought, and against whether the roster can still be
completed in the rounds remaining.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import simulate
from .myboard import (EARLIEST_ROUND, LEAGUE, MAX_COUNTS, MIN_COUNTS,
                      MUST_FILL_BY, MY_SLOT, marginal)

# A faller is measured in POINTS, not picks.
#
# The old version used a flat eight-pick threshold, which is wrong in both
# directions. Measured on this board, the points lost per pick of waiting:
#
#     region          RB      WR     DEF
#     rounds 1-2    0.312   0.342      --
#     rounds 3-6    0.077   0.049      --
#     rounds 11-15  0.032   0.118   0.061
#
# So a five-pick fall in round one is worth about 1.7 points, and a twenty-pick
# fall on a defence in round twelve is worth about 1.2. A flat pick threshold
# rated the second as the bigger opportunity. It is not: the gradient between
# adjacent players is five to ten times steeper early, which is the whole
# reason early picks matter more than late ones.
#
# Threshold is now projected points per game of surplus over the next man up.
FALLER_POINTS = 0.8

# Below this many points of gradient, waiting is close to free and no fall at
# that position is worth acting on. Kickers and defences live here nearly
# always, which is the point: matching their ADP is not a reason to draft one.
FLAT_GRADIENT = 0.09


@dataclass
class Pick:
    overall: int
    name: str
    pos: str
    by_slot: int | None = None


@dataclass
class Candidate:
    name: str
    pos: str
    adp: float
    vor: float
    tier: int
    survives_next: float
    fall: float                 # picks past ADP he is still available
    score: float
    marginal: float
    verdict: str = ""
    costs: str = ""
    gradient: float = 0.0        # points lost per pick of waiting, here
    fall_points: float = 0.0     # what the fall is worth in points/game


@dataclass
class LiveState:
    picks: list[Pick] = field(default_factory=list)
    my_roster: list[Pick] = field(default_factory=list)
    slot: int = MY_SLOT
    rounds: int = 15

    @property
    def next_overall(self) -> int:
        return len(self.picks) + 1

    @property
    def current_round(self) -> int:
        return (len(self.picks) // LEAGUE.teams) + 1

    def my_picks(self) -> list[int]:
        return [p.overall for p in simulate.pick_numbers(self.slot, LEAGUE.teams, self.rounds)]

    def my_next(self, after: int | None = None) -> int | None:
        after = after if after is not None else self.next_overall
        return next((p for p in self.my_picks() if p > after), None)

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for p in self.my_roster:
            c[p.pos] = c.get(p.pos, 0) + 1
        return c

    def rounds_left(self) -> int:
        return self.rounds - len(self.my_roster)

    def unfilled(self) -> dict[str, int]:
        c = self.counts()
        return {p: n - c.get(p, 0) for p, n in MIN_COUNTS.items() if c.get(p, 0) < n}


def drift(state: LiveState, board) -> dict[str, float]:
    """How far ahead of or behind ADP this room is drafting, per position.

    Positive means the position is going EARLIER than ADP. This is the closest
    thing to a read on nine strangers that the data allows, and unlike ADP it
    is about these nine specifically.
    """
    by_name = {x.name: x for x in board}
    out: dict[str, list[float]] = {}
    for p in state.picks:
        b = by_name.get(p.name)
        if not b or b.adp >= 160:
            continue
        out.setdefault(b.pos, []).append(b.adp - p.overall)
    return {k: round(sum(v) / len(v), 1) for k, v in out.items() if len(v) >= 3}


def gradient(board, pos: str, taken: set, from_pick: int, span: int,
             depth: int = 4) -> float:
    """Points per pick lost by waiting at this position, right now.

    Measured across the top few players still available at the position — the
    only ones any of this turns on — as the drop in projected points divided by
    the ADP distance between them.

    Two earlier attempts failed in opposite directions. A median across a wide
    ADP window reported 0.03 points per pick in round one, because a window
    that wide is mostly near-equal players. Then comparing "best now" against
    "best surviving my next turn" returned zero almost everywhere, because at a
    three-pick span the two are usually the same man. Narrow and local is what
    works: the question is what the next man up costs me.
    """
    grp = sorted([x for x in board if x.pos == pos and x.name not in taken],
                 key=lambda x: -x.value)[:depth]
    if len(grp) < 2:
        return 0.0
    drops = []
    for i in range(len(grp) - 1):
        dv = grp[i].value - grp[i + 1].value
        dp = max(1.0, abs(grp[i + 1].adp - grp[i].adp))
        drops.append(dv / dp)
    return round(sum(drops) / len(drops), 4)


def position_spread(board, pos: str, taken: set) -> float:
    """Total points between the best available at a position and replacement.

    The ceiling on what any fall at that position can be worth. For kickers and
    defences this is roughly two points; for early receivers it is ten or more,
    which is the entire reason the two are not comparable.
    """
    grp = sorted([x for x in board if x.pos == pos and x.name not in taken],
                 key=lambda x: -x.value)
    if len(grp) < 2:
        return 0.0
    starters = LEAGUE.starting_slots(pos) * LEAGUE.teams or LEAGUE.teams
    idx = min(len(grp) - 1, max(1, starters))
    return round(max(0.0, grp[0].value - grp[idx].value), 2)


def available(state: LiveState, board):
    taken = {p.name for p in state.picks}
    return [x for x in board if x.name not in taken]


def conditional_survival(state: LiveState, board, at_pick: int,
                         n: int = 8000) -> dict[str, float]:
    """P(available at `at_pick`) given what has already happened.

    Two adjustments over the preseason simulation: players already gone are
    excluded outright, and each remaining player's ADP is shifted by the drift
    measured at his position. A room that has taken five quarterbacks early is
    telling you the sixth will go early too.
    """
    d = drift(state, board)
    avail = available(state, board)
    rows = [{"name": x.name, "pos": x.pos, "team": x.team,
             "adp": max(1.0, x.adp - d.get(x.pos, 0.0)),
             "stdev": 6.0 if x.adp >= 160 else 4.5}
            for x in avail]
    if not rows:
        return {}
    draws = simulate.simulate(rows, n=n)
    return {r[0]: r[3] for r in simulate.survival(rows, draws, at_pick)}


def evaluate(state: LiveState, board, n: int = 8000) -> list[Candidate]:
    """Rank every available player for THIS pick, right now."""
    rd = state.current_round
    nxt = state.my_next()
    sv_next = conditional_survival(state, board, nxt, n) if nxt else {}
    counts = state.counts()
    left = state.rounds_left()
    short = state.unfilled()
    urgent = [p for p in short if MUST_FILL_BY.get(p, 99) <= rd]
    forced = sum(short.values()) >= left

    taken_names = {p.name for p in state.picks}
    out: list[Candidate] = []
    for x in available(state, board):
        if rd < EARLIEST_ROUND.get(x.pos, 0):
            continue
        if counts.get(x.pos, 0) >= MAX_COUNTS.get(x.pos, 99):
            continue
        m = marginal(x.pos, counts.get(x.pos, 0))
        sv = sv_next.get(x.name, 0.0)
        gone = 1.0 - sv
        fall = state.next_overall - x.adp
        span = (nxt - state.next_overall) if nxt else 12
        grad = gradient(board, x.pos, taken_names, state.next_overall, span)
        # What the fall is actually worth, in projected points per game — capped
        # at what the position can possibly deliver.
        #
        # Without the cap, a kicker twenty picks past ADP scored 5.3 points of
        # "value" when the entire spread from the best kicker to a replacement
        # one is about two. Extrapolating a local slope across a long fall
        # invents value that does not exist, and it does it worst at exactly
        # the positions where the least is at stake.
        span_pts = position_spread(board, x.pos, taken_names)
        fall_pts = round(min(max(0.0, fall) * grad, span_pts), 2)
        score = x.vor * m * (0.30 + 0.70 * gone)

        # A faller is worth something only if the value is real AND the pick is
        # not needed elsewhere. Both halves matter.
        verdict, costs = "", ""
        if grad < FLAT_GRADIENT and fall_pts < FALLER_POINTS:
            # Position is flat here — the next man up is nearly as good, so
            # being "available past ADP" means nothing.
            pass
        elif fall_pts >= FALLER_POINTS and x.vor > 0:
            if urgent and x.pos not in urgent:
                costs = (f"{'/'.join(urgent)} must be filled by round "
                         f"{min(MUST_FILL_BY[p] for p in urgent)}; taking him here "
                         f"spends the pick that has to do it")
                verdict = "value, but it costs a starter"
            elif forced and x.pos not in short:
                costs = f"{sum(short.values())} slots unfilled with {left} rounds left"
                verdict = "value, but the roster cannot absorb it"
            elif m < 0.4:
                costs = f"already hold {counts.get(x.pos,0)} at {x.pos}; he would be depth"
                verdict = "value, but marginal to this roster"
            else:
                verdict = (f"FALLER — {fall:.0f} picks past ADP, worth {fall_pts:.1f} "
                           f"pts/gm at this position's gradient ({grad:.2f}/pick)")
                score *= 1.15      # small, deliberate: the fall is already in `vor`
        out.append(Candidate(x.name, x.pos, x.adp, x.vor, x.tier, round(sv, 3),
                             round(fall, 1), round(score, 3), round(m, 2),
                             verdict, costs, grad, fall_pts))

    out.sort(key=lambda c: -c.score)
    return out


def _restrict(cands: list[Candidate], state: LiveState) -> list[Candidate]:
    """Apply the roster constraint. Returns the pickable subset."""
    rd = state.current_round
    short = state.unfilled()
    urgent = [p for p in short if MUST_FILL_BY.get(p, 99) <= rd]
    if urgent:
        pool = [c for c in cands if c.pos in urgent]
        if pool:
            return pool
    if sum(short.values()) >= state.rounds_left():
        pool = [c for c in cands if c.pos in short]
        if pool:
            return pool
    return cands


def positional_windows(state: LiveState, board, n: int = 6000) -> list[dict]:
    """Where each position is strong or weak across my remaining picks.

    Built because a fixed opening rule — "two backs early, receivers later" —
    is not supported by this league's board. Measured over eight mock drafts
    per strategy, forcing RB-RB scored 139.1 ESPN points and WR-WR 139.9, a
    gap of 0.8 against a standard deviation of about 3. Indistinguishable.
    Letting the agent take whoever is actually best scored 143.3, which is a
    real margin.

    What IS true is that the advantage moves between positions by round, and
    it moves enough to matter:

        pick 9/12   RB best-available exceeds WR by 0.83 / 0.46
        pick 29/32  WR exceeds RB by 0.74 / 0.59
        pick 49+    RB exceeds WR again by 0.4 to 0.8

    So the receiver advantage is real and it is narrow — concentrated in
    rounds three and four. A rule that says "always start RB" would take the
    round 1-2 edge and then miss the round 3-4 one. This function surfaces the
    window so the choice is made per pick, which is what the mocks say is worth
    the four points.
    """
    taken = {p.name for p in state.picks}
    my = [pk for pk in state.my_picks() if pk >= state.next_overall]
    rows = []
    for pk in my[:6]:
        sv = conditional_survival(state, board, pk, n) if pk != state.next_overall else {}
        best = {}
        for pos in ("RB", "WR", "TE"):
            cand = [x.value * (sv.get(x.name, 1.0) if sv else 1.0)
                    for x in board if x.pos == pos and x.name not in taken
                    and (not sv or sv.get(x.name, 0) >= 0.35)]
            best[pos] = round(max(cand), 2) if cand else 0.0
        rows.append({"pick": pk, **best,
                     "edge": round(best["RB"] - best["WR"], 2),
                     "favours": "RB" if best["RB"] > best["WR"] else "WR"})
    return rows


def recommend(state: LiveState, board, n: int = 8000) -> dict:
    all_cands = evaluate(state, board, n)
    cands = _restrict(all_cands, state)
    if not cands:
        return {"take": None, "reason": "no eligible players"}
    top = cands[0]

    # Fallers are drawn from the UNRESTRICTED list on purpose. When the roster
    # constraint rules out a genuine bargain, that is exactly the moment to say
    # so — silently filtering it out hides the most interesting decision on the
    # board and makes the agent look like it did not notice.
    pickable = {c.name for c in cands}
    fallers = []
    for c in all_cands:
        if c.fall_points < FALLER_POINTS or c.vor <= 0:
            continue
        if c.name not in pickable and not c.costs:
            c.costs = (f"roster needs {'/'.join(state.unfilled())} first with "
                       f"{state.rounds_left()} rounds left")
            c.verdict = "value, but passing him is correct"
        fallers.append(c)
        if len(fallers) >= 6:
            break
    d = drift(state, board)
    return {
        "round": state.current_round,
        "overall": state.next_overall,
        "take": top.name,
        "pos": top.pos,
        "reason": (top.verdict or
                   f"tier {top.tier} {top.pos}, {top.vor:+.1f} over replacement, "
                   f"{top.survives_next:.0%} to survive to pick {state.my_next()}"),
        "alternatives": [(c.name, c.pos, c.verdict or f"{c.vor:+.1f} VOR") for c in cands[1:4]],
        "fallers": [(c.name, c.pos, c.fall, c.verdict, c.costs, c.fall_points)
                    for c in fallers],
        "drift": d,
        "unfilled": state.unfilled(),
        "rounds_left": state.rounds_left(),
        "windows": positional_windows(state, board, n=3000),
    }


def from_sleeper(draft_id: str, board, my_slot: int = MY_SLOT,
                 fetch=None) -> LiveState:
    """Build state from the live Sleeper draft feed."""
    from . import sleeper
    raw = (fetch or sleeper.draft_picks)(draft_id)
    players = sleeper.players()
    st = LiveState(slot=my_slot)
    for p in sorted(raw, key=lambda r: r.get("pick_no", 0)):
        meta = players.get(str(p.get("player_id")), {})
        name = meta.get("full_name") or f"{meta.get('first_name','')} {meta.get('last_name','')}".strip()
        pick = Pick(int(p.get("pick_no", 0)), name, meta.get("position", ""),
                    p.get("draft_slot"))
        st.picks.append(pick)
        if p.get("draft_slot") == my_slot:
            st.my_roster.append(pick)
    return st
