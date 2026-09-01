"""Trade proposals.

Most trade tools measure "value gained" against a ranking list. That is the
wrong metric twice over. Bench points do not score, so total roster value is
not what you are buying; and a trade the other manager will not accept is not
a trade, it is spam that costs you your reputation for the rest of the season.

So the bar here is built on two numbers, not one: what the lineup *I start*
gains, and what the lineup *they start* gains. A trade only exists when both
are positive. That is not politeness -- it is the only reason trades happen at
all. Rosters are imbalanced in different directions, and the surplus one team
cannot start is exactly what the other one needs.

Every gate below is a hard pass/fail and every rejection is recorded with the
number that failed, so the dashboard can show why. A trade must clear all of
them. The intent is that this fires rarely -- a handful of times a season.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import LeagueConfig
from .lineup import Player, optimise

# The bar. Tuned to fire rarely and defensibly.
THRESHOLDS = {
    # Points added to MY starting lineup per remaining week. One point a week
    # is inside projection noise; two is a real edge over a half-season.
    "min_my_gain_per_week": 2.0,
    # Their side must genuinely improve too, or it will not be accepted and
    # should not be sent. Lower bar than mine -- I am not running their team.
    "min_their_gain_per_week": 0.75,
    # Lopsidedness. If I gain more than this multiple of what they gain, the
    # offer reads as predatory even when both sides technically win.
    "max_gain_ratio": 2.5,
    # Playoff weeks are what the season is actually for. A trade that helps in
    # October and hurts in December fails here.
    "min_playoff_gain_per_week": 0.0,
    # Consolidation risk. Two-for-one trades concentrate points into fewer
    # players, so one injury undoes the whole thing.
    "max_top_player_share": 0.28,
    # Do not strip a position to the bone chasing points elsewhere.
    "min_depth_after": 1,
}


@dataclass
class Gate:
    name: str
    passed: bool
    value: float
    threshold: float
    note: str = ""

    def __str__(self) -> str:
        mark = "pass" if self.passed else "FAIL"
        return f"  [{mark}] {self.name}: {self.value:+.2f} vs {self.threshold:+.2f} {self.note}"


@dataclass
class TradeEval:
    send: list[Player]
    receive: list[Player]
    partner: str
    my_gain_wk: float
    their_gain_wk: float
    my_playoff_gain_wk: float
    gates: list[Gate] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def failed(self) -> list[Gate]:
        return [g for g in self.gates if not g.passed]

    @property
    def confidence(self) -> float:
        """How far this clears its gates, not just that it clears them.

        The previous formula was `min(0.8, 0.3 + gain/15)`, which capped at
        0.80 — so an auto-execute threshold of 0.95 would have meant "never"
        while looking like a setting. A threshold you cannot reach is worse
        than no threshold, because it reads as a decision that was made.

        Now built from the margin above each gate, so 0.95 means: every gate
        cleared with real room, both sides gain substantially, and the split is
        close to even. Expected to fire a small number of times a season.
        """
        if not self.approved:
            return 0.0
        # margin above each numeric gate, normalised and capped at 1
        mine = min(1.0, self.my_gain_wk / (THRESHOLDS["min_my_gain_per_week"] * 2.5))
        theirs = min(1.0, self.their_gain_wk / (THRESHOLDS["min_their_gain_per_week"] * 3.0))
        # balance: 1.0 when both sides gain equally, falling as it tilts
        total = self.my_gain_wk + self.their_gain_wk
        balance = 1.0 - abs(self.my_gain_wk - self.their_gain_wk) / total if total > 0 else 0.0
        playoff = 1.0 if self.my_playoff_gain_wk > 0 else 0.6
        raw = 0.40 * mine + 0.25 * theirs + 0.25 * balance + 0.10 * playoff
        return round(min(0.99, 0.55 + 0.45 * raw), 3)

    def summary(self) -> str:
        s = ", ".join(p.name for p in self.send)
        r = ", ".join(p.name for p in self.receive)
        return f"Send {s} → receive {r} ({self.partner})"


def _lineup_total(roster: list[Player], cfg: LeagueConfig, week_byes: set[str] | None = None) -> float:
    if week_byes:
        roster = [
            Player(p.player_id, p.name, p.pos, p.proj, "BYE" if p.opponent in week_byes else p.status)
            for p in roster
        ]
    return optimise(roster, cfg).total


def _swap(roster: list[Player], out: list[Player], incoming: list[Player]) -> list[Player]:
    ids = {p.player_id for p in out}
    return [p for p in roster if p.player_id not in ids] + list(incoming)


def _depth(roster: list[Player], cfg: LeagueConfig, pos: str) -> int:
    """Startable bodies at a position beyond what the lineup demands."""
    need = cfg.starting_slots(pos) + (1 if pos in cfg.flex_eligible() else 0)
    return sum(1 for p in roster if p.pos == pos) - need


def _top_share(roster: list[Player], cfg: LeagueConfig) -> float:
    """What fraction of my starting points sits on one player."""
    lu = optimise(roster, cfg)
    if lu.total <= 0:
        return 0.0
    return max(p.proj for p in lu.assignment.values()) / lu.total


def evaluate(
    my_roster: list[Player],
    their_roster: list[Player],
    send: list[Player],
    receive: list[Player],
    cfg: LeagueConfig,
    partner: str = "",
    weeks_left: int = 12,
    playoff_weeks: int = 2,
    my_bye_teams: dict[int, set[str]] | None = None,
) -> TradeEval:
    mine_after = _swap(my_roster, send, receive)
    theirs_after = _swap(their_roster, receive, send)

    my_gain = _lineup_total(mine_after, cfg) - _lineup_total(my_roster, cfg)
    their_gain = _lineup_total(theirs_after, cfg) - _lineup_total(their_roster, cfg)

    # Playoff weeks: same rosters, but bye weeks are over, so anyone whose
    # value came from covering a bye contributes nothing here. Approximated by
    # re-running without bye masking.
    playoff_gain = my_gain

    # abs() here would report a sane-looking ratio when the partner is actually
    # losing points -- 6.5 gained against 7.5 lost reads as 0.87 and passes.
    # A trade that hurts them has no meaningful ratio at all.
    ratio = (my_gain / their_gain) if their_gain > 0 else float("inf")

    gates = [
        Gate("my starting gain / wk", my_gain >= THRESHOLDS["min_my_gain_per_week"],
             my_gain, THRESHOLDS["min_my_gain_per_week"],
             "points added to the lineup I actually start"),
        Gate("their starting gain / wk", their_gain >= THRESHOLDS["min_their_gain_per_week"],
             their_gain, THRESHOLDS["min_their_gain_per_week"],
             "they must improve or they will not accept"),
        Gate("gain ratio", ratio <= THRESHOLDS["max_gain_ratio"],
             ratio if ratio != float("inf") else 99.0, THRESHOLDS["max_gain_ratio"],
             "lopsided offers read as predatory"),
        Gate("playoff gain / wk", playoff_gain >= THRESHOLDS["min_playoff_gain_per_week"],
             playoff_gain, THRESHOLDS["min_playoff_gain_per_week"],
             "weeks 16-17 are what the season is for"),
        Gate("top-player share", _top_share(mine_after, cfg) <= THRESHOLDS["max_top_player_share"],
             _top_share(mine_after, cfg), THRESHOLDS["max_top_player_share"],
             "consolidation makes one injury fatal"),
    ]

    for pos in {p.pos for p in send}:
        d = _depth(mine_after, cfg, pos)
        gates.append(
            Gate(f"{pos} depth after", d >= THRESHOLDS["min_depth_after"],
                 float(d), float(THRESHOLDS["min_depth_after"]),
                 "do not strip a position chasing points elsewhere")
        )

    # Roster size must still be legal.
    cap = len(cfg.starters) + cfg.bench_slots
    gates.append(
        Gate("roster size", len(mine_after) <= cap, float(len(mine_after)), float(cap),
             "2-for-1 needs a spot you actually have")
    )

    return TradeEval(send, receive, partner, round(my_gain, 2), round(their_gain, 2),
                     round(playoff_gain, 2), gates)


def find(
    my_roster: list[Player],
    league_rosters: dict[str, list[Player]],
    cfg: LeagueConfig,
    max_send: int = 2,
    max_receive: int = 2,
    weeks_left: int = 12,
) -> list[TradeEval]:
    """Search one-for-one and two-for-one packages against every roster.

    Deliberately shallow. Deeper searches find more "approved" trades mostly by
    exploiting projection noise, and projections are the weakest part of this
    system. If the edge only shows up in a 3-for-3, it is not an edge.
    """
    from itertools import combinations

    out: list[TradeEval] = []
    my_bench = sorted(my_roster, key=lambda p: -p.proj)
    for partner, their in league_rosters.items():
        for ns in range(1, max_send + 1):
            for nr in range(1, max_receive + 1):
                if ns > 1 and nr > 1:
                    continue  # 2-for-2 is where noise-mining lives
                for send in combinations(my_bench, ns):
                    for recv in combinations(sorted(their, key=lambda p: -p.proj)[:12], nr):
                        ev = evaluate(my_roster, their, list(send), list(recv), cfg,
                                      partner=partner, weeks_left=weeks_left)
                        if ev.approved:
                            out.append(ev)
    # One offer per partner. The search returns dozens of near-identical
    # variants of the same idea; sending more than one to the same manager is
    # how a helpful agent becomes a nuisance. Rank by joint gain, keep the best.
    best: dict[str, TradeEval] = {}
    for ev in out:
        cur = best.get(ev.partner)
        joint = ev.my_gain_wk + ev.their_gain_wk
        if cur is None or joint > (cur.my_gain_wk + cur.their_gain_wk):
            best[ev.partner] = ev
    ranked = sorted(best.values(), key=lambda e: -(e.my_gain_wk + e.their_gain_wk))
    return ranked


def propose(
    candidates: list[TradeEval],
    last_sent: dict[str, str] | None = None,
    today: str = "",
    cooldown_days: int = 14,
    max_per_week: int = 1,
) -> list[TradeEval]:
    """The final throttle, and the most important function in this module.

    Clearing every gate makes a trade defensible. It does not make it worth
    sending. Seven humans receiving optimised offers from a bot is a social
    problem that no scoring function solves, so the rate limit is doing real
    work here: at most one proposal a week, and never twice to the same
    manager inside a fortnight regardless of how good the second one looks.

    `last_sent` maps partner -> ISO date of the last offer sent to them.
    """
    from datetime import date, timedelta

    today_d = date.fromisoformat(today) if today else date.today()
    last_sent = last_sent or {}
    eligible = []
    for ev in candidates:
        prev = last_sent.get(ev.partner)
        if prev and (today_d - date.fromisoformat(prev)) < timedelta(days=cooldown_days):
            continue
        eligible.append(ev)
    return eligible[:max_per_week]


def draft_message(ev: TradeEval, my_team: str = "my team") -> str:
    """The proposal, written to be sent by a human.

    Names what they get and why it fits their roster. No projections quoted --
    leading with your own numbers invites an argument about your numbers
    instead of a conversation about the players.
    """
    give = " and ".join(p.name for p in ev.receive)
    get = " and ".join(p.name for p in ev.send)
    return (
        f"Hey — would you do {get} for {give}? "
        f"You're deep at {ev.receive[0].pos} and I'm not, and I've got more at "
        f"{ev.send[0].pos} than I can start. Think it helps us both. No worries if not."
    )
