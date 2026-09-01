"""Weekly takeaways from games played, and what to watch in games to come.

A hard constraint that shaped this module: **as of 31 August 2026, zero games
of the 2026 season have been played.** Sleeper's state endpoint reports week 1,
season start 9 September; ESPN's scoreboard lists all sixteen week-1 games with
status "Scheduled". So there are no 2026 takeaways to write, and inventing
plausible ones would be the single worst thing this project could do.

What it does instead, and what it will do:

  BEFORE kickoff — the watch list is built from things that are actually
  known: implied team totals and spreads from the betting market, the role
  changes in the news overrides, and which of my targets are in which game.
  Every line is traceable to a source.

  AFTER games — takeaways are generated from the box score and the
  participation data: who gained or lost route share, whose scoring outran
  their usage (the fade signal, which the backtest found is 2.7x stronger than
  the buy signal), and which role changes actually showed up on the field.

The distinction the takeaways are built around is the one the backtest
supports: a player's *role* changing is signal, a player's *points* changing
mostly is not. So a takeaway about a 30-point week says what the usage did,
not how many touchdowns he scored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DATA_AS_OF = "2026-08-31"
SEASON_START = "2026-09-09"


@dataclass
class Takeaway:
    kind: str                 # "result" | "watch"
    headline: str
    detail: str
    players: list[str] = field(default_factory=list)
    source: str = ""
    confidence: str = "stated"   # stated | inferred | speculative

    def as_dict(self) -> dict:
        return {"kind": self.kind, "headline": self.headline, "detail": self.detail,
                "players": self.players, "source": self.source,
                "confidence": self.confidence}


# Week 1 lines, pulled from ESPN's scoreboard 31 Aug 2026. Over/under and
# spread are the market's view of game environment, which is the one thing
# that reliably moves fantasy scoring and that no amount of player data
# captures.
WEEK1_LINES = [
    ("NE @ SEA", 44.5, "SEA -3.5", "2026-09-10"),
    ("SF vs LAR", 48.5, "LAR -3.5", "2026-09-11"),
    ("TB @ CIN", 51.5, "CIN -3.5", "2026-09-13"),
    ("NO @ DET", 49.5, "DET -7", "2026-09-13"),
    ("NYJ @ TEN", 38.5, "TEN -1.5", "2026-09-13"),
    ("BAL @ IND", 48.5, "BAL -3.5", "2026-09-13"),
    ("ATL @ PIT", 42.5, "PIT -3", "2026-09-13"),
    ("CHI @ CAR", 47.5, "CHI -2.5", "2026-09-13"),
    ("CLE @ JAX", 40.5, "JAX -7.5", "2026-09-13"),
    ("BUF @ HOU", 44.5, "BUF -1.5", "2026-09-13"),
    ("MIA @ LV", 40.5, "LV -3.5", "2026-09-13"),
    ("GB @ MIN", 45.5, "MIN -1.5", "2026-09-13"),
    ("WSH @ PHI", 45.5, "PHI -4.5", "2026-09-13"),
    ("ARI @ LAC", 46.5, "LAC -10.5", "2026-09-13"),
    ("DAL @ NYG", 48.5, "DAL -2.5", "2026-09-14"),
    ("DEN @ KC", 42.5, "KC -3", "2026-09-15"),
]


def season_started(today: str | None = None) -> bool:
    t = date.fromisoformat(today) if today else date.today()
    return t >= date.fromisoformat(SEASON_START)


def watch_list(today: str | None = None) -> list[Takeaway]:
    """What to watch, built only from things that are known."""
    out: list[Takeaway] = []

    if not season_started(today):
        out.append(Takeaway(
            "watch", "No 2026 games have been played",
            "Sleeper reports week 1 with a season start of 9 September; ESPN lists all "
            "sixteen week-1 games as Scheduled. There are no results to summarise yet, "
            "so everything below is forward-looking and sourced. Takeaways from actual "
            "games appear here from 10 September.",
            source="Sleeper /state/nfl, ESPN scoreboard, 31 Aug 2026"))

    lines = sorted(WEEK1_LINES, key=lambda x: -x[1])
    hi = lines[:3]
    lo = lines[-3:]
    out.append(Takeaway(
        "watch", f"Highest-scoring games projected: {', '.join(g for g, *_ in hi)}",
        "Implied totals of " + ", ".join(f"{g} at {ou}" for g, ou, *_ in hi) +
        ". Game environment is the strongest thing the betting market knows that "
        "player data does not, and total is what drives passing volume.",
        source="ESPN scoreboard odds, 31 Aug 2026"))
    out.append(Takeaway(
        "watch", f"Lowest totals: {', '.join(g for g, *_ in lo)}",
        "Totals of " + ", ".join(f"{g} at {ou}" for g, ou, *_ in lo) +
        ". NYJ @ TEN at 38.5 is the lowest on the slate — the market expects roughly "
        "two touchdowns a side. Start receivers from these games only if you must.",
        source="ESPN scoreboard odds, 31 Aug 2026"))
    out.append(Takeaway(
        "watch", "ARI @ LAC is the widest spread at 10.5",
        "A double-digit favourite tends to run late and a double-digit underdog tends "
        "to throw. That inflates receiver volume for Arizona and rushing volume for the "
        "Chargers, regardless of what either does on early downs.",
        source="ESPN scoreboard odds, 31 Aug 2026"))
    out.append(Takeaway(
        "watch", "Green Bay backfield, GB @ MIN",
        "Josh Jacobs is on the Commissioner's Exempt List and cannot play. MarShawn "
        "Lloyd is atop the depth chart; Kaleb Johnson was traded in from Pittsburgh the "
        "same day. Whether this is Lloyd's backfield or a committee is the single "
        "biggest unresolved role question of week 1, and it is worth a waiver claim "
        "either way once it resolves.",
        players=["MarShawn Lloyd", "Kaleb Johnson"],
        source="NFL.com, ESPN, NBC Sports, 30 Aug 2026"))
    out.append(Takeaway(
        "watch", "Rams defence, SF vs LAR in Melbourne",
        "First look at Myles Garrett and Aaron Donald on the same line. Their ADP of "
        "~108 predates Donald's signing by one day, so this is the largest gap between "
        "personnel and draft cost on the board. A strong opener would close it fast.",
        source="NFL.com, CBS, PFF, 30 Aug 2026"))
    return out


def results_takeaways(week: int, usage_deltas=None, fades=None) -> list[Takeaway]:
    """Generated from played games. Empty until games exist.

    Deliberately built on role rather than scoring. The backtest in
    `calibration.py` found that points outrunning usage is a *fade* signal 2.7x
    stronger than the reverse, so a takeaway about a big week reports what the
    usage did, not how many touchdowns landed.
    """
    if not usage_deltas and not fades:
        return [Takeaway(
            "result", f"No results for week {week}",
            "Either the week has not been played or the participation data has not "
            "published yet — nflverse posts weekly files a day or two after games.",
            source="nflverse")]
    out = []
    for p in (usage_deltas or [])[:6]:
        out.append(Takeaway(
            "result", f"{p['name']}: route share {p['delta']:+.0%}",
            f"Now running routes on {p['rate']:.0%} of dropbacks. Route participation "
            f"was the strongest predictor measured in this project (0.918 against "
            f"rest-of-season scoring), and it moves before targets do.",
            players=[p["name"]], source="nflverse participation", confidence="stated"))
    for p in (fades or [])[:4]:
        out.append(Takeaway(
            "result", f"{p['name']}: scoring is ahead of role",
            f"{p['ppg']:.1f} points a game on a role that does not support it. Across "
            f"2022-25 this group underperformed a points-only model by 1.02 points a "
            f"game, every season. Bench or sell while the name still carries weight.",
            players=[p["name"]], source="nflverse", confidence="inferred"))
    return out


def build(week: int = 1, today: str | None = None, **kw) -> list[dict]:
    items = results_takeaways(week, **kw) if season_started(today) else []
    items += watch_list(today)
    return [t.as_dict() for t in items]
