"""League configuration, derived from Sleeper rather than hardcoded.

The whole point: joining a different league is a one-line change. Every
number the agent reasons with (replacement level, flex eligibility, waiver
mechanics) falls out of /league/<id>.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import sleeper

SKILL = {"QB", "RB", "WR", "TE"}
FLEX_MAP = {
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


@dataclass
class LeagueConfig:
    league_id: str
    name: str
    season: str
    teams: int
    roster_positions: list[str]
    scoring: dict
    # Sleeper waiver_type, confirmed against the league-settings UI rather than
    # inferred: 0 = Rolling Priority, 1 = Reverse Standings, 2 = FAAB.
    # `waiver_budget` is populated (100) even in non-FAAB leagues, so it is not
    # a safe signal on its own -- reading it that way is how you end up writing
    # bid logic for a league that never bids.
    waiver_type: int
    waiver_budget: int
    playoff_teams: int
    playoff_start_week: int
    bench_slots: int
    ir_slots: int
    starters: list[str] = field(default_factory=list)

    # -- derived ---------------------------------------------------------

    WAIVER_NAMES = {0: "rolling priority", 1: "reverse standings", 2: "FAAB"}

    @property
    def is_faab(self) -> bool:
        return self.waiver_type == 2

    @property
    def waiver_name(self) -> str:
        return self.WAIVER_NAMES.get(self.waiver_type, f"type {self.waiver_type}")

    @property
    def waiver_priority_is_static(self) -> bool:
        """Reverse standings: priority is your inverse record, refreshed weekly.

        Strategically the opposite of rolling priority. Under rolling, a claim
        is expensive -- you drop to last and stay there. Under reverse
        standings you cannot spend priority away; it simply reflects how badly
        you are doing. So claims are close to free, and the correct policy is
        to claim aggressively whenever a player clears the bar, rather than
        hoarding position for a hypothetical better claim later.
        """
        return self.waiver_type == 1

    @property
    def ppr(self) -> float:
        return float(self.scoring.get("rec", 0.0))

    def flex_eligible(self) -> set[str]:
        out: set[str] = set()
        for slot in self.starters:
            if slot in FLEX_MAP:
                out |= FLEX_MAP[slot]
        return out

    def starting_slots(self, pos: str) -> int:
        return sum(1 for s in self.starters if s == pos)

    def replacement_rank(self, pos: str) -> int:
        """How deep the position is startable league-wide.

        This is the number that stops you overvaluing TE in a shallow league.
        A dedicated slot counts once per team; flex slots are shared, so we
        spread them across the eligible positions rather than double-counting.
        """
        dedicated = self.starting_slots(pos) * self.teams
        flex_slots = sum(1 for s in self.starters if s in FLEX_MAP)
        eligible_for_flex = [p for p in SKILL if p in self.flex_eligible()]
        share = 0.0
        if pos in eligible_for_flex and eligible_for_flex:
            share = flex_slots * self.teams / len(eligible_for_flex)
        return int(round(dedicated + share)) + 1

    def summary(self) -> str:
        lines = [
            f"{self.name} ({self.season})",
            f"  {self.teams} teams | PPR {self.ppr} | "
            f"waivers: {'FAAB $' + str(self.waiver_budget) if self.is_faab else self.waiver_name}",
            f"  starters: {' '.join(self.starters)}",
            f"  bench {self.bench_slots} | IR {self.ir_slots}",
            f"  playoffs: {self.playoff_teams} teams from week {self.playoff_start_week}",
            "  replacement level: "
            + ", ".join(f"{p}{self.replacement_rank(p)}" for p in ("QB", "RB", "WR", "TE")),
        ]
        return "\n".join(lines)


def load(league_id: str) -> LeagueConfig:
    lg = sleeper.league(league_id)
    s = lg.get("settings", {}) or {}
    rp = lg.get("roster_positions", []) or []
    starters = [p for p in rp if p not in ("BN", "IR", "TAXI")]
    return LeagueConfig(
        league_id=league_id,
        name=lg.get("name", "?"),
        season=str(lg.get("season", "")),
        teams=int(lg.get("total_rosters") or len(starters) or 0),
        roster_positions=rp,
        scoring=lg.get("scoring_settings", {}) or {},
        waiver_type=int(s.get("waiver_type", 0)),
        waiver_budget=int(s.get("waiver_budget", 0)),
        playoff_teams=int(s.get("playoff_teams", 0)),
        playoff_start_week=int(s.get("playoff_week_start", 0)),
        bench_slots=sum(1 for p in rp if p == "BN"),
        ir_slots=sum(1 for p in rp if p == "IR"),
        starters=starters,
    )
