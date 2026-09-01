"""The objective: make the playoffs, then win them.

This is not the same as maximising points, and the difference is large enough
to change picks.

Six of ten qualify from week 15. Getting in is the likely outcome for a roster
of even average strength, which means the regular season is mostly a
qualification exercise and weeks 15-17 are what the season is actually for.
Two consequences:

**Playoff weeks are worth more than regular ones.** A player who is excellent
in September and unavailable in December is worth less than his season average
says. Weights below put roughly a third of a player's value in three weeks.

**Ceiling matters more once you are in.** Making the playoffs rewards
consistency — you need to bank wins. Winning them rewards upside, because you
face the best remaining teams and an average week loses. The weighting shifts
across the season for that reason rather than being fixed.

Playoff-week schedules are real, pulled from ESPN for weeks 15, 16 and 17 of
2026 — 48 games, all confirmed. Combined with points-allowed-by-position, that
gives a genuine playoff-schedule rating rather than a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PLAYOFF_WEEKS = (15, 16, 17)
QUALIFY_WEEK = 15
TEAMS_QUALIFYING = 6
LEAGUE_TEAMS = 10

# Weight per fantasy week. Regular weeks earn a playoff berth; playoff weeks
# decide the title. Sum of playoff weights is ~0.33 of the total, against three
# of fourteen scoring weeks -- roughly 1.5x a regular week each.
WEEK_WEIGHT = {w: 1.0 for w in range(1, 15)}
WEEK_WEIGHT.update({15: 2.6, 16: 2.6, 17: 2.6})

# 2026 weeks 15-17, from ESPN. away|home.
PLAYOFF_SCHEDULE_RAW = [
    (15, "SF", "LAC"), (15, "SEA", "PHI"), (15, "CHI", "BUF"), (15, "MIA", "GB"),
    (15, "IND", "TEN"), (15, "CLE", "NYG"), (15, "BAL", "PIT"), (15, "NO", "TB"),
    (15, "ATL", "WSH"), (15, "CIN", "CAR"), (15, "JAX", "HOU"), (15, "NYJ", "ARI"),
    (15, "DEN", "LV"), (15, "DAL", "LAR"), (15, "DET", "MIN"), (15, "NE", "KC"),
    (16, "HOU", "PHI"), (16, "GB", "CHI"), (16, "BUF", "DEN"), (16, "LAR", "SEA"),
    (16, "TB", "ATL"), (16, "CIN", "IND"), (16, "WSH", "MIN"), (16, "CAR", "PIT"),
    (16, "LAC", "MIA"), (16, "ARI", "NO"), (16, "NE", "NYJ"), (16, "CLE", "BAL"),
    (16, "TEN", "LV"), (16, "SF", "KC"), (16, "JAX", "DAL"), (16, "NYG", "DET"),
    (17, "BAL", "CIN"), (17, "DEN", "NE"), (17, "KC", "LAC"), (17, "LAR", "TB"),
    (17, "WSH", "JAX"), (17, "NO", "ATL"), (17, "IND", "CLE"), (17, "NYG", "DAL"),
    (17, "PIT", "TEN"), (17, "BUF", "MIA"), (17, "MIN", "NYJ"), (17, "SEA", "CAR"),
    (17, "LV", "ARI"), (17, "DET", "CHI"), (17, "PHI", "SF"), (17, "HOU", "GB"),
]


def playoff_opponents() -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    for wk, away, home in PLAYOFF_SCHEDULE_RAW:
        out.setdefault(away, {})[wk] = home
        out.setdefault(home, {})[wk] = away
    return out


@dataclass
class PlayoffProfile:
    team: str
    position: str
    opponents: dict = field(default_factory=dict)     # week -> opponent
    allowed: dict = field(default_factory=dict)       # week -> pts allowed to pos
    league_avg: float = 0.0

    @property
    def mean_allowed(self) -> float:
        vals = [v for v in self.allowed.values() if v]
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    @property
    def edge(self) -> float:
        """Points per game above an average playoff schedule."""
        return round(self.mean_allowed - self.league_avg, 2) if self.mean_allowed else 0.0

    def describe(self) -> str:
        if not self.opponents:
            return "playoff schedule unknown"
        legs = ", ".join(f"wk{w} {self.opponents[w]}"
                         + (f" ({self.allowed[w]:.0f})" if self.allowed.get(w) else "")
                         for w in sorted(self.opponents))
        d = "above" if self.edge >= 0 else "below"
        return (f"{legs} — {self.mean_allowed:.1f} allowed to {self.position}s on "
                f"average, {abs(self.edge):.1f} {d} league average")


def profile(team: str, position: str, matchup_table: dict) -> PlayoffProfile:
    opps = playoff_opponents().get(team, {})
    allowed, avg = {}, 0.0
    for wk, opp in opps.items():
        m = matchup_table.get((opp, position))
        if m:
            allowed[wk] = m.allowed_pg
            avg = m.league_avg
    return PlayoffProfile(team, position, opps, allowed, avg)


def season_value(weekly: dict[int, float]) -> float:
    """Weight a week-by-week projection toward the weeks that decide the season."""
    num = sum(weekly.get(w, 0.0) * WEEK_WEIGHT.get(w, 1.0) for w in weekly)
    den = sum(WEEK_WEIGHT.get(w, 1.0) for w in weekly) or 1.0
    return round(num / den, 3)


def playoff_adjust(base_ppg: float, prof: PlayoffProfile,
                   bye_week: int | None = None,
                   availability: float = 1.0) -> tuple[float, list[str]]:
    """Adjust a season-long projection for what the playoff weeks look like.

    Three terms, in order of how much they move the number:

    **A bye in a playoff week is close to disqualifying.** Byes normally end by
    week 14 so this should not fire, but if the schedule ever puts one in 15-17
    it costs a third of the player's playoff value and no amount of talent
    compensates.

    **Playoff schedule.** Averaged points allowed to his position across his
    three opponents. Worth up to about a point a game either way, which is
    real but smaller than people assume.

    **Availability.** Charged harder here than in the season-long number: a
    player with a 15% miss rate misses a playoff game roughly one year in seven,
    and that is the game you cannot replace him for.
    """
    notes: list[str] = []
    adj = base_ppg

    if bye_week in PLAYOFF_WEEKS:
        adj *= 0.67
        notes.append(f"bye in week {bye_week}, inside the playoff window — "
                     f"a third of his playoff value is gone before he plays")

    if prof.opponents:
        adj += prof.edge * 0.35
        if abs(prof.edge) >= 1.5:
            good = "favourable" if prof.edge > 0 else "difficult"
            notes.append(f"{good} playoff schedule, {prof.edge:+.1f} pts/gm vs average")

    # Availability compounds over three must-win weeks.
    miss = 1.0 - availability
    if miss > 0.08:
        penalty = base_ppg * miss * 0.9
        adj -= penalty
        notes.append(f"{availability:.0%} availability costs {penalty:.1f} against "
                     f"three weeks you cannot afford to lose him")

    return round(adj, 2), notes


def phase_weight(week: int) -> tuple[float, str]:
    """How much to favour ceiling over floor, by point in the season.

    Qualifying rewards banking wins, so consistency. Once qualified, you face
    the best remaining teams and an average week loses — upside is what wins.
    A fixed preference gets one half of the season wrong.
    """
    if week <= 6:
        return 0.5, "early: floor and ceiling matter equally, the table is not formed"
    if week <= 13:
        return 0.35, "qualifying: consistency banks wins, favour floor"
    return 0.75, "playoffs: an average week loses, favour ceiling"
