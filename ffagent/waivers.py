"""Waiver claims.

The part people over-engineer. In a shallow league the wire is deep, so being
*right* about a claim matters less than being *early* and not wrecking your
roster to make it. Most of this module is about the drop side, which is where
claims actually go wrong.

Two mechanics, and they need different logic:

- **Rolling priority**: a claim costs your position in the queue. The real
  question is not "is he good" but "is he worth burning priority I might want
  in week 9". Answer: usually no, and the bar rises the higher your priority.
- **Reverse standings** (what this league uses): priority is your inverse
  record, recalculated weekly. You cannot spend it away. That inverts the
  logic above -- claims are close to free, so the right policy is to claim
  whenever a player clears the bar rather than hoard position. It also means
  the agent should propose MORE than one claim a week, because there is no
  budget being consumed. The only real cost is the roster spot you drop.
- **FAAB**: a claim costs budget. Bid to value, not to win. Overpaying in
  September for a week-3 flex is how people arrive at week 11 with $3.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import LeagueConfig
from .lineup import Player, optimise


@dataclass
class Candidate:
    player_id: str
    name: str
    pos: str
    proj: float
    edge: float               # usage divergence from usage.watchlist
    rostered_pct: float = 0.0  # Sleeper trending, proxy for "has this been noticed"


@dataclass
class Claim:
    add: Candidate
    drop: Player | None
    gain: float               # projected starting-lineup improvement
    bid: int | None
    priority_cost: str
    rationale: str
    confidence: float


def starting_gain(roster: list[Player], add: Player, drop: Player, cfg: LeagueConfig) -> float:
    """Does this swap improve the lineup you actually *start*?

    The number that matters, and the one bench-depth arguments ignore. A great
    bench player adds zero until someone in front of him is hurt or on bye.
    """
    before = optimise(roster, cfg).total
    after_roster = [p for p in roster if p.player_id != drop.player_id] + [add]
    after = optimise(after_roster, cfg, current=None).total
    return round(after - before, 2)


def drop_score(p: Player, roster: list[Player], cfg: LeagueConfig) -> float:
    """How droppable is this player? Lower is safer to cut.

    Deliberately not just 'fewest projected points'. A low-scoring backup
    behind your RB1 is insurance; a mid-scoring fifth receiver is not. Depth
    at a position you are thin in counts for more than raw projection.
    """
    same_pos = [q for q in roster if q.pos == p.pos]
    rank = sorted(same_pos, key=lambda q: -q.proj).index(p) + 1
    starters_needed = cfg.starting_slots(p.pos) + (1 if p.pos in cfg.flex_eligible() else 0)
    # players inside the starting requirement are expensive to drop
    scarcity = 2.5 if rank <= starters_needed else 1.0
    bye_cover = 0.6 if rank == starters_needed + 1 else 0.0
    return round(p.proj * scarcity + bye_cover * 10, 2)


def faab_bid(cand: Candidate, gain: float, budget_left: int, weeks_left: int) -> int:
    """Bid to value, not to win.

    Anchored on projected starting-lineup gain rather than on excitement, then
    scaled by how much season is left to spend across. The floor of $1 exists
    because a $0 bid loses to any real interest, and the cap stops one week
    eating the budget.
    """
    if gain <= 0:
        return 0
    share = min(0.35, 0.06 + 0.02 * gain)          # fraction of remaining budget
    urgency = 1.0 + max(0.0, (10 - weeks_left) / 20)  # spend down late, not early
    bid = int(round(budget_left * share * urgency))
    return max(1, min(bid, int(budget_left * 0.5)))


def priority_note(gain: float, position: int, teams: int) -> str:
    """Rolling priority is a one-shot asset. Say what it costs in plain words."""
    if position <= max(2, teams // 4):
        return (f"You hold waiver priority {position} of {teams}. Using it drops you to last. "
                f"At +{gain:.1f} projected points that is probably not worth it — hold "
                f"unless he starts for you immediately.")
    return (f"Waiver priority {position} of {teams} is cheap to spend; "
            f"claiming costs you little you were likely to use.")


def build_claims(
    roster: list[Player],
    candidates: list[Candidate],
    cfg: LeagueConfig,
    priority_position: int = 1,
    budget_left: int | None = None,
    weeks_left: int = 14,
    signal_confidence: float = 1.0,
    max_claims: int = 3,
) -> list[Claim]:
    budget_left = cfg.waiver_budget if budget_left is None else budget_left
    droppables = sorted(roster, key=lambda p: drop_score(p, roster, cfg))
    claims: list[Claim] = []

    for cand in candidates:
        add = Player(cand.player_id, cand.name, cand.pos, cand.proj)
        best: tuple[float, Player] | None = None
        for d in droppables[:5]:
            g = starting_gain(roster, add, d, cfg)
            if best is None or g > best[0]:
                best = (g, d)
        if best is None:
            continue
        gain, drop = best

        # A claim that does not change the lineup you start is bench churn.
        # Worth making only when the usage signal is strong enough to be a bet
        # on next month rather than this week.
        speculative = gain <= 0
        if speculative and cand.edge < 1.5:
            continue

        conf = min(0.85, (0.25 + 0.10 * cand.edge + 0.03 * max(0.0, gain))) * signal_confidence
        # NOTE: gain is in projected points, edge is a normalised z-score. Taking
        # max() of the two mixes units and is a deliberate shortcut, not a model.
        # It biases speculative claims upward, which is the intended direction but
        # not a defensible magnitude -- revisit once outcomes are logged.
        bid = faab_bid(cand, max(gain, cand.edge), budget_left, weeks_left) if cfg.is_faab else None

        if speculative:
            why = (f"Does not improve this week's lineup. Claim is a bet on role: "
                   f"usage divergence {cand.edge:.2f} with production not yet repriced.")
        else:
            why = f"Improves the starting lineup by {gain:.1f} projected points."
        if cfg.waiver_type == 0:
            why += " " + priority_note(gain, priority_position, cfg.teams)
        elif cfg.waiver_priority_is_static:
            why += (f" Reverse-standings waivers: priority {priority_position} of "
                    f"{cfg.teams} is not consumed by claiming, so the only cost "
                    f"is the roster spot.")

        claims.append(Claim(cand, drop, gain, bid, 
                            f"priority {priority_position}/{cfg.teams}", why, round(conf, 2)))

    claims.sort(key=lambda c: (-c.gain, -c.add.edge))

    # Two claims naming the same drop is a FEATURE, not a bug -- I had this
    # backwards.
    #
    # When you do not hold waiver priority, the right play is a CHAIN: rank the
    # players you want, submit a claim for each, and point every one of them at
    # the SAME drop. The platform processes them in your stated order. The first
    # that clears consumes the drop, and every later claim in the chain then has
    # no valid drop and fails harmlessly. You get exactly one player -- your
    # highest-ranked one that survived to your turn -- instead of gambling the
    # whole claim on a name six teams ahead of you will take first.
    #
    # `chain=True` preserves that. The de-duplication below is for the other
    # case: several claims you genuinely want ALL of, where a shared drop really
    # would break the second one.
    if chain:
        # Ranked chain against one drop. Order is the preference order.
        drop = claims[0].drop if claims and claims[0].drop else None
        out = []
        for i, c in enumerate(claims[:max_claims], 1):
            out.append(Claim(c.add, drop, c.gain, c.bid, f"chain #{i}",
                             (f"chain position {i}. Fires only if every claim above it "
                              f"failed; they all release the same drop, so at most one "
                              f"lands." + (" " + c.why if c.why else "")),
                             c.confidence))
        return out

    spent: set[str] = set()
    resolved: list[Claim] = []
    for c in claims:
        if c.drop is None or c.drop.player_id not in spent:
            if c.drop is not None:
                spent.add(c.drop.player_id)
            resolved.append(c)
            continue
        pool = [d for d in droppables if d.player_id not in spent][:5]
        if not pool:
            continue
        add = Player(c.add.player_id, c.add.name, c.add.pos, c.add.proj)
        alt = max(((starting_gain(roster, add, d, cfg), d) for d in pool), key=lambda t: t[0])
        spent.add(alt[1].player_id)
        resolved.append(
            Claim(c.add, alt[1], alt[0], c.bid, c.priority_cost,
                  c.rationale + f" (drop reassigned to {alt[1].name}; "
                                f"{c.drop.name} already committed to a higher-priority claim)",
                  c.confidence)
        )
    claims = resolved
    # Rolling priority is single-use per week: proposing five claims implies a
    # budget you do not have.
    # Rolling priority is single-use per week, so one claim. FAAB and reverse
    # standings both allow several: FAAB because budget is divisible, reverse
    # standings because priority is not consumed at all.
    cap = 1 if cfg.waiver_type == 0 else max_claims
    return claims[:cap]
