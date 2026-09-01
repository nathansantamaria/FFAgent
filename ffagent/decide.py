"""Decisions: confidence with the cost already netted out, and a falsifiable
condition attached to each one.

Two changes from the previous design, both because the old one asked the reader
to do arithmetic the agent should have done.

**Confidence runs 0-100 and already includes what the move costs.** There is no
separate "cost if wrong" column. A waiver claim that costs a roster spot is not
"70% confident with a downside" — it is less confident than that, and the number
should say so. 100 means every consideration points the same way with nothing
given up, which is rare enough that it should be.

The costs, and how each is charged:

    waiver     a roster spot. Charged against the player being dropped: if he
               would top the wire himself, the claim is close to a wash.
    drop       the player will be claimed by someone else. Charged in full when
               he is startable anywhere in a ten-team league.
    trade      a player of similar value going the other way. Charged as their
               gain, because a trade that helps them more than me is not a good
               trade for me however defensible it looks.
    start/sit  points that week, and only that week. The cheapest mistake here
               and priced accordingly -- the reason its bar is lowest.

**Every decision states what has to happen next**, in a form that can be checked
against reality afterwards. "Confidence >= 0.55" is a restatement of the
confidence, not a condition. "He needs 12+ targets in week 3 for this to have
been right" is a prediction, and a prediction that can be scored is the only
kind worth logging.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Auto-execute thresholds, 0-100. Costs are already inside the number.
AUTO = {
    "start_sit": 60,     # cheapest to get wrong: one week of points
    "waiver": 65,        # costs a roster spot
    "drop": 80,          # permanent, he gets claimed
    "trade": 95,         # costs a real player, and credibility
}


@dataclass
class Condition:
    """A falsifiable statement about the future, with a date it resolves."""
    text: str
    resolves: str            # "week 3", "by the trade deadline"
    metric: str = ""         # what to measure
    target: float | None = None

    def as_dict(self) -> dict:
        return {"text": self.text, "resolves": self.resolves,
                "metric": self.metric, "target": self.target}


@dataclass
class Evidence:
    source: str
    says: str
    weight: float


@dataclass
class Decision:
    kind: str
    player: str
    action: str
    confidence: int                       # 0-100, cost already netted out
    thesis: str
    conditions: list[Condition] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    cost_charged: str = ""                # what was deducted and why
    matchup: str = ""

    @property
    def auto(self) -> bool:
        return self.confidence >= AUTO.get(self.kind, 100)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "player": self.player, "action": self.action,
            "confidence": self.confidence, "thesis": self.thesis,
            "auto": self.auto, "threshold": AUTO.get(self.kind, 100),
            "conditions": [c.as_dict() for c in self.conditions],
            "evidence": [{"source": e.source, "says": e.says, "weight": e.weight}
                         for e in self.evidence],
            "cost_charged": self.cost_charged, "matchup": self.matchup,
        }


# --- cost accounting ----------------------------------------------------

def waiver_cost(drop_is_startable: bool, drop_would_top_wire: bool) -> tuple[int, str]:
    """Points of confidence deducted for the roster spot."""
    if drop_would_top_wire:
        return 18, ("dropping a player who would top the wire himself — much of "
                    "the gain comes straight back off the board")
    if drop_is_startable:
        return 10, "dropping someone who starts on bye weeks"
    return 3, "dropping a bench body with no path to a start"


def drop_cost(rostered_pct: float, startable: bool) -> tuple[int, str]:
    if startable:
        return 22, "he starts somewhere in a ten-team league and will be claimed"
    if rostered_pct > 0.4:
        return 12, "widely rostered elsewhere, he will not clear"
    return 4, "unlikely to be claimed"


def trade_cost(their_gain_pg: float, my_gain_pg: float) -> tuple[int, str]:
    if their_gain_pg <= 0:
        return 40, "they lose points on this, so they will decline it"
    ratio = my_gain_pg / their_gain_pg if their_gain_pg else 9.0
    if ratio > 2.5:
        return 20, f"lopsided at {ratio:.1f}x in my favour — reads as predatory"
    if ratio < 0.8:
        return 15, f"they gain more than I do ({1/ratio:.1f}x)"
    return 6, "roughly even split, which is why it might be accepted"


def start_sit_cost(points_at_stake: float) -> tuple[int, str]:
    if points_at_stake < 1.5:
        return 12, f"only {points_at_stake:.1f} projected points separate them"
    return 3, f"{points_at_stake:.1f} projected points, and reversible until kickoff"


# --- builders -----------------------------------------------------------

def build_start_sit(player: str, over: str, gain: float, matchup=None,
                    base: int = 70) -> Decision:
    cost, why = start_sit_cost(gain)
    conf = max(0, min(100, base - cost))
    conds = [Condition(
        f"{player} outscores {over} this week",
        "this week", "fantasy_points_ppr")]
    ev = []
    m = ""
    if matchup:
        m = matchup.describe()
        ev.append(Evidence("matchup", m, 0.30))
        conf += 6 if matchup.edge > 2 else (-6 if matchup.edge < -2 else 0)
        if matchup.edge > 2:
            conds.append(Condition(
                f"the matchup edge should show up as volume, not just points",
                "this week", "targets"))
    return Decision("start_sit", player, f"start over {over}",
                    max(0, min(100, conf)),
                    f"{gain:+.1f} projected points.", conds, ev, why, m)


def build_waiver(player: str, drop: str, gain: float, edge: float,
                 drop_startable: bool, drop_tops_wire: bool,
                 weeks_of_evidence: int = 1, base: int = 72) -> Decision:
    cost, why = waiver_cost(drop_startable, drop_tops_wire)
    conf = max(0, min(100, base + int(edge * 4) - cost))
    # Conditions are comparative wherever a comparison exists. "Hold this role"
    # is a fact about one player; "outproduces the man I dropped" is the actual
    # question, because the alternative to this claim is keeping him.
    conds = [
        Condition(f"{player} outproduces {drop} from here — that is the trade "
                  f"this claim actually makes",
                  "rest of season", "ppg_difference"),
        Condition(f"{player} holds the role a third straight week",
                  "week +2", "route_rate", 0.65),
        Condition(f"his snap share stays above 55% next week, or this was noise",
                  "next week", "snap_pct", 0.55),
    ]
    if gain > 0:
        conds.append(Condition(
            f"{player} starts for me immediately, worth {gain:+.1f} a week",
            "this week", "starting_lineup_gain", gain))
    return Decision("waiver", player, f"claim, drop {drop}", conf,
                    f"Usage divergence {edge:.2f}; lineup gain {gain:+.1f}.",
                    conds, [], why)


def build_trade(send: str, receive: str, partner: str,
                my_gain: float, their_gain: float, base: int = 88) -> Decision:
    cost, why = trade_cost(their_gain, my_gain)
    conf = max(0, min(100, base + int(min(my_gain, their_gain) * 2) - cost))
    conds = [
        Condition(f"{receive} outproduces {send} by more than {my_gain:.1f} a week "
                  f"from here — otherwise this trade did not make sense",
                  "rest of season", "ppg_difference", my_gain),
        Condition(f"{partner} accepts; nothing moves otherwise",
                  "within 3 days", "accepted"),
    ]
    return Decision("trade", receive, f"send {send} to {partner}", conf,
                    f"My lineup {my_gain:+.1f}/wk, theirs {their_gain:+.1f}/wk.",
                    conds, [], why)
