"""Drafting.

Three things the module has to get right, in descending order of how much
they matter and ascending order of how much attention they usually get.

**Replacement level.** Everything else is downstream of it. In a 10-team
league with one TE slot, the ninth-best tight end is a startable tight end
somewhere, so the gap between TE1 and TE10 is what you are buying -- and it is
much smaller than the gap between RB1 and RB25. Value over replacement is not
a ranking, it is the only number that makes positions comparable.

**Durability.** Asked for and rarely computed. Everyone has an opinion about
who is injury-prone; almost nobody checks. nflverse publishes weekly injury
reports back to 2022, so "games missed" is a fact rather than a vibe. It
belongs in the projection as an availability multiplier, not as a vague
tie-breaker applied when you already dislike a player.

**Position uncertainty.** You do not know your slot yet, which is fine,
because a good board is slot-agnostic. What changes with slot is only *when*
tier breaks fall relative to your picks. `plan_for_slot` handles that; the
board does not need to.

Upside is deliberately last. It matters in rounds 11-14 and almost nowhere
else, and treating it as a season-long philosophy is how people end up with a
bench full of lottery tickets and no starting running back.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import LeagueConfig

INJURY_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.parquet"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet"


# --- durability ---------------------------------------------------------

@dataclass
class Durability:
    gsis_id: str
    name: str
    seasons: int
    weeks_out: int
    weeks_dnp: int
    weeks_tracked: int
    games_played: int = 0      # weeks with a real stat line
    games_possible: int = 0    # weeks the player's season was under way

    @property
    def miss_rate(self) -> float:
        return self.weeks_out / self.weeks_tracked if self.weeks_tracked else 0.0

    @property
    def availability(self) -> float:
        """Expected share of games available.

        Built on GAMES PLAYED, not on the injury report.

        The injury report alone is badly wrong for exactly the players you most
        need it for. A player placed on IR stops appearing on the weekly report,
        so a season-ending injury registers as *fewer* Out designations than a
        month of ankle tweaks. Verified: McCaffrey played 4 games in 2024 and the
        report-based rate called him 94% available and "durable".

        Games played catches that, because a missed game is a missing stat line
        whatever the paperwork says. The report is kept as a secondary signal --
        it distinguishes a healthy scratch from a knee.

        Shrunk toward the league mean either way: one missed week in one tracked
        season is not a measurement, and unshrunk rates make small samples look
        like strong signals.
        """
        prior_games, prior_rate = 16.0, 0.10
        if self.games_possible >= 8:
            missed = self.games_possible - self.games_played
            rate = (missed + prior_games * prior_rate) / (self.games_possible + prior_games)
        else:
            rate = (self.weeks_out + 20.0 * 0.08) / (self.weeks_tracked + 20.0)
        return round(max(0.0, 1.0 - rate), 3)

    @property
    def flag(self) -> str:
        a = self.availability
        if a >= 0.93:
            return "durable"
        if a >= 0.87:
            return "average"
        if a >= 0.80:
            return "some risk"
        return "fragile"


def durability(seasons: tuple[int, ...] = (2022, 2023, 2024, 2025)) -> dict[str, Durability]:
    """Games missed per player, with injury-report context.

    Two sources because neither is sufficient alone. Games played is the ground
    truth for availability; the injury report says whether an absence was an
    injury at all. A player's first tracked season starts at his first stat
    line, so a rookie drafted in 2024 is not charged for missing 2022.
    """
    played: dict[str, tuple[int, int]] = {}
    for y in seasons:
        try:
            st = pd.read_parquet(STATS_URL.format(season=y))
        except Exception:
            continue
        st = st[(st["week"] <= 18) & st["player_id"].notna()]
        weeks_in_season = int(st["week"].max())
        for pid, g in st.groupby("player_id"):
            first = int(g["week"].min())
            gp, poss = played.get(str(pid), (0, 0))
            played[str(pid)] = (gp + int(g["week"].nunique()),
                                poss + (weeks_in_season - first + 1))

    frames = []
    for y in seasons:
        try:
            d = pd.read_parquet(INJURY_URL.format(season=y))
            d["season"] = y
            frames.append(d)
        except Exception:
            continue
    if not frames:
        return {}
    df = pd.concat(frames)
    df = df[df["gsis_id"].notna()]
    out: dict[str, Durability] = {}
    for gsis, g in df.groupby("gsis_id"):
        gp, poss = played.get(str(gsis), (0, 0))
        out[str(gsis)] = Durability(
            str(gsis),
            str(g["full_name"].iloc[0]) if "full_name" in g else str(gsis),
            int(g["season"].nunique()),
            int((g["report_status"] == "Out").sum()),
            int((g["practice_status"] == "Did Not Participate In Practice").sum()),
            int(len(g)), gp, poss,
        )
    # Players who never appear on an injury report still have a games-played
    # record, and leaving them out would silently treat the healthiest players
    # as unknown.
    for pid, (gp, poss) in played.items():
        if pid not in out:
            out[pid] = Durability(pid, pid, 0, 0, 0, 0, gp, poss)
    return out


# --- value over replacement --------------------------------------------

def replacement_ranks(cfg: LeagueConfig) -> dict[str, int]:
    return {p: cfg.replacement_rank(p) for p in ("QB", "RB", "WR", "TE")}


@dataclass
class Prospect:
    name: str
    pos: str
    team: str
    adp: float
    proj_ppg: float
    gsis_id: str = ""
    dur: Durability | None = None
    vor: float = 0.0
    tier: int = 0
    upside: float = 0.0

    @property
    def adjusted(self) -> float:
        """Projection discounted by expected availability."""
        a = self.dur.availability if self.dur else 0.92
        return round(self.proj_ppg * a, 2)

    def line(self) -> str:
        d = f"{self.dur.flag}" if self.dur else "unknown"
        return (f"{self.name:<24}{self.pos:<4}{self.team:<5}"
                f"adp {self.adp:>6.1f}  vor {self.vor:>6.2f}  t{self.tier}  {d}")


def build_board(prospects: list[Prospect], cfg: LeagueConfig) -> list[Prospect]:
    """Value over replacement, then tiers from the gaps within each position."""
    ranks = replacement_ranks(cfg)
    by_pos: dict[str, list[Prospect]] = {}
    for p in prospects:
        by_pos.setdefault(p.pos, []).append(p)

    for pos, group in by_pos.items():
        group.sort(key=lambda x: -x.adjusted)
        idx = min(ranks.get(pos, len(group)), len(group)) - 1
        baseline = group[idx].adjusted if group else 0.0
        for p in group:
            p.vor = round(p.adjusted - baseline, 2)
        # Tier breaks where the drop between consecutive players is unusually
        # large. Tiers matter more than ranks on the clock: inside a tier you
        # take the cheaper player, across one you reach.
        gaps = [group[i].adjusted - group[i + 1].adjusted for i in range(len(group) - 1)]
        if gaps:
            cut = pd.Series(gaps).quantile(0.80)
            tier = 1
            for i, p in enumerate(group):
                p.tier = tier
                if i < len(gaps) and gaps[i] >= cut:
                    tier += 1
    return sorted(prospects, key=lambda p: -p.vor)


def upside_score(p: Prospect, board: list[Prospect]) -> float:
    """How much more than his cost a player could return.

    Defined against ADP, not in the abstract: a high-ceiling player at his
    ceiling price is not upside, he is fair value. This is the gap between
    where the market has him and where his tier says he belongs -- which is why
    it is only worth acting on in the late rounds, where the gaps are widest
    and the cost of being wrong is a bench spot.
    """
    same = [q for q in board if q.pos == p.pos]
    same.sort(key=lambda q: q.adp)
    market_rank = same.index(p) + 1
    value_rank = sorted(same, key=lambda q: -q.vor).index(p) + 1
    return round((market_rank - value_rank) / max(1, len(same)) * 10, 2)


# --- pick logic ---------------------------------------------------------

@dataclass
class PickAdvice:
    take: Prospect
    reason: str
    alternatives: list[tuple[Prospect, str]] = field(default_factory=list)
    run_warning: str = ""


def detect_run(recent_picks: list[str], window: int = 6, threshold: int = 4) -> str | None:
    """Four of the last six at one position is a run.

    Runs are where people panic-reach. Knowing you are inside one is worth a
    round of value, because the correct response is usually to sit it out and
    take the position everyone just stopped drafting.
    """
    if len(recent_picks) < window:
        return None
    tail = recent_picks[-window:]
    for pos in set(tail):
        if tail.count(pos) >= threshold:
            return pos
    return None


def advise(
    available: list[Prospect],
    my_roster: list[Prospect],
    cfg: LeagueConfig,
    pick_no: int,
    next_pick_no: int | None,
    recent_picks: list[str] | None = None,
) -> PickAdvice:
    """Who to take, and why, in a form you can read in ninety seconds."""
    board = sorted(available, key=lambda p: -p.vor)
    counts: dict[str, int] = {}
    for p in my_roster:
        counts[p.pos] = counts.get(p.pos, 0) + 1

    rounds_left = 15 - len(my_roster)
    need: dict[str, float] = {}
    for pos in ("QB", "RB", "WR", "TE"):
        required = cfg.starting_slots(pos)
        have = counts.get(pos, 0)
        # Urgency rises only when the slot is still unfilled and the draft is
        # running out. Drafting for need early is how you reach.
        need[pos] = 1.0 + (0.35 * max(0, required - have) if rounds_left <= 7 else 0.0)

    # Survival: will this player still be here at my next pick? A player who
    # certainly survives is not worth spending this pick on.
    gap = (next_pick_no - pick_no) if next_pick_no else 0
    scored = []
    for p in board[:40]:
        survives = max(0.0, min(1.0, (p.adp - pick_no) / max(1, gap))) if gap else 0.0
        scarcity = 1.0 - 0.5 * survives
        scored.append((p.vor * need.get(p.pos, 1.0) * scarcity, p, survives))
    scored.sort(key=lambda t: -t[0])

    if not scored:
        raise ValueError("no players available")

    _, take, surv = scored[0]
    run = detect_run(recent_picks or [])
    alts = []
    for _s, p, sv in scored[1:4]:
        alts.append((p, f"likely available at {next_pick_no}" if sv > 0.6
                     else f"tier {p.tier}, vor {p.vor:+.1f}"))

    reason = f"Tier {take.tier} {take.pos}, {take.vor:+.1f} over replacement"
    if surv < 0.35:
        reason += "; unlikely to last to your next pick"
    if take.dur and take.dur.flag in ("some risk", "fragile"):
        reason += f"; durability {take.dur.flag} ({take.dur.availability:.0%} available)"

    warn = ""
    if run:
        warn = (f"{run} run in progress ({run} taken 4 of the last 6). "
                f"Runs are where people reach — the value is usually in the position "
                f"everyone just stopped taking.")
    return PickAdvice(take, reason, alts, warn)
