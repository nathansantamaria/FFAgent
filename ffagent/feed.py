"""News, sorted into the categories that actually change a decision.

An undifferentiated feed is close to useless: the item that matters is buried
among thirty that do not. Every item here carries a category, a relevance star
if it touches my roster or my week, and a takeaway saying what I would do about
it. An item with no takeaway does not belong in the feed.

Categories:

    injury        availability changes, starred when they hit my roster
    projection    a ranking moved and why
    matchup       a defence that gives up unusual volume to a position
    trade         roster moves that change opportunity
    calendar      trade deadline, bye weeks, cutdowns, kickoff
    preseason     results and what they imply, with the caveat below

**Preseason results are weak evidence and are labelled as such.** Starters play
a series or two; scores are decided by players who will be cut. What preseason
IS good for is availability -- who practised, who was held out, who is on the
field with the first team. A blowout tells you nothing; a starter's snap count
tells you something.

Verified 2026 preseason: 33 games, all Final, pulled from ESPN's scoreboard at
`seasontype=1`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Real 2026 preseason results, ESPN scoreboard, seasontype=1.
PRESEASON = [
    (1, "CAR", 33, "ARI", 30), (2, "DET", 14, "CIN", 16), (2, "GB", 9, "PIT", 28),
    (2, "IND", 13, "NE", 13), (2, "ARI", 27, "LV", 14), (2, "LAC", 27, "HOU", 7),
    (2, "TEN", 19, "SF", 13), (2, "DEN", 27, "ATL", 7), (2, "TB", 24, "NYJ", 16),
    (2, "MIA", 7, "WSH", 20), (2, "CAR", 14, "BUF", 29), (2, "CLE", 10, "CHI", 34),
    (2, "MIN", 13, "NYG", 10), (2, "LAR", 20, "KC", 12), (2, "JAX", 24, "NO", 20),
    (2, "PHI", 7, "BAL", 24), (2, "DAL", 17, "SEA", 7), (3, "LV", 22, "HOU", 20),
    (3, "SF", 41, "LAC", 17), (3, "NYJ", 17, "PIT", 0), (3, "CAR", 34, "JAX", 17),
    (3, "GB", 33, "DEN", 13), (3, "WSH", 13, "DET", 17), (3, "BUF", 31, "CLE", 7),
    (3, "ATL", 34, "IND", 6), (3, "BAL", 13, "MIN", 3), (3, "NO", 0, "LAR", 34),
    (3, "NYG", 26, "MIA", 3), (3, "CHI", 9, "CIN", 27), (3, "PHI", 21, "NE", 24),
    (3, "KC", 15, "TB", 16), (3, "DAL", 34, "ARI", 13), (3, "SEA", 16, "TEN", 19),
]

# Dates that change what a decision is worth. All confirmed from the league
# settings or the NFL calendar.
CALENDAR = [
    ("2026-09-09", "Season opens", "Week 1 Thursday. nflverse begins publishing "
     "2026 usage files after this, and signal confidence rises from 0.25."),
    ("2026-10-11", "First bye weeks", "Week 5. Roster crunch begins; with two IR "
     "slots and five bench spots there is little room to stash."),
    ("2026-11-24", "Trade deadline", "Week 11 in this league. After it, the only "
     "roster tool left is waivers."),
    ("2026-12-15", "Fantasy playoffs", "Week 15, top 6 of 10. Week 14 byes are "
     "irrelevant; weeks 15-17 are what the season is for."),
]


# Team codes as they appear in prose, for relevance matching.
TEAM_HINTS = {
    "Packers": "GB", "Rams": "LA", "Bears": "CHI", "Steelers": "PIT",
    "Chiefs": "KC", "Bills": "BUF", "Cowboys": "DAL", "Eagles": "PHI",
    "Ravens": "BAL", "Bengals": "CIN", "Browns": "CLE", "Texans": "HOU",
    "Colts": "IND", "Jaguars": "JAX", "Titans": "TEN", "Broncos": "DEN",
    "Raiders": "LV", "Chargers": "LAC", "Dolphins": "MIA", "Patriots": "NE",
    "Jets": "NYJ", "Giants": "NYG", "Commanders": "WAS", "Lions": "DET",
    "Vikings": "MIN", "Falcons": "ATL", "Panthers": "CAR", "Saints": "NO",
    "Buccaneers": "TB", "Cardinals": "ARI", "49ers": "SF", "Seahawks": "SEA",
}


# The feed shows only the most recent items. Everything older is still in the
# override list and still affects rankings -- it just stops taking up screen.
FEED_LIMIT = 10


@dataclass
class Item:
    category: str
    headline: str
    detail: str
    takeaway: str = ""
    starred: bool = False          # touches my roster, league, or this week
    players: list = field(default_factory=list)
    teams: list = field(default_factory=list)
    source: str = ""
    url: str = ""
    date: str = ""

    def as_dict(self) -> dict:
        return {"category": self.category, "headline": self.headline,
                "detail": self.detail, "takeaway": self.takeaway,
                "starred": self.starred, "players": self.players,
                "teams": self.teams, "source": self.source, "url": self.url,
                "date": self.date}


def preseason_takeaways(my_teams: set | None = None) -> list[Item]:
    """What the preseason is and is not evidence for."""
    my_teams = my_teams or set()
    out: list[Item] = []

    margins = []
    for wk, away, asc, home, hsc in PRESEASON:
        margins.append((abs(asc - hsc), wk, away, asc, home, hsc))
    margins.sort(reverse=True)

    biggest = margins[:4]
    out.append(Item(
        "preseason", "Widest preseason margins",
        "; ".join(f"{a} {s1}-{s2} {h} (wk {w})" for _m, w, a, s1, h, s2 in biggest),
        takeaway="Ignore the scores. Starters played a series or two and these were "
                 "decided by players who have since been cut. Preseason is evidence "
                 "about availability and first-team snap counts, not about quality.",
        source="ESPN scoreboard, seasontype=1"))

    # Shutouts are worth one line because they usually mean a team rested everyone.
    shutouts = [(w, a, s1, h, s2) for _m, w, a, s1, h, s2 in margins if s1 == 0 or s2 == 0]
    if shutouts:
        w, a, s1, h, s2 = shutouts[0]
        held = a if s1 == 0 else h
        out.append(Item(
            "preseason", f"{held} shut out in week {w}",
            f"{a} {s1}-{s2} {h}.",
            takeaway=f"A preseason shutout almost always means the starters did not "
                     f"play. Check {held}'s week 3 snap counts before reading anything "
                     f"into it.",
            teams=[held], source="ESPN scoreboard"))

    return out


def calendar_items(today: str = "2026-08-31") -> list[Item]:
    from datetime import date
    t = date.fromisoformat(today)
    out = []
    for d, title, detail in CALENDAR:
        days = (date.fromisoformat(d) - t).days
        if days < -7:
            continue
        when = f"in {days} days" if days > 0 else "now"
        out.append(Item("calendar", f"{title} — {when}", detail,
                        takeaway="", date=d, source="league settings / NFL calendar"))
    return out


def matchup_items(table: dict, my_positions: set | None = None,
                  top: int = 3) -> list[Item]:
    """Defences worth targeting or avoiding."""
    out = []
    for pos in ("RB", "WR", "TE"):
        rows = [m for (t, p), m in table.items() if p == pos]
        if not rows:
            continue
        rows.sort(key=lambda m: -m.allowed_pg)
        best, worst = rows[0], rows[-1]
        out.append(Item(
            "matchup", f"{best.defense} is the softest matchup for {pos}s",
            best.describe(),
            takeaway=f"Start {pos}s facing {best.defense}; the spread between them and "
                     f"{worst.defense} is {best.allowed_pg - worst.allowed_pg:.1f} points "
                     f"a game, which is larger than the gap between most flex options.",
            teams=[best.defense], source="nflverse 2025, shrunk to league mean"))
    return out[:top]


def relevance(item: Item, my_players: set, my_teams: set,
              this_week_opponents: set) -> Item:
    """Star anything touching my roster, my opponent, or a team I face."""
    hit = ((set(item.players) & my_players)
           or (set(item.teams) & my_teams)
           or (set(item.teams) & this_week_opponents))
    item.starred = bool(hit)
    return item


def build(news_items=None, matchup_table=None, my_players=None, my_teams=None,
          opponents=None, today: str | None = None) -> list[dict]:
    # Default to the actual date. A hardcoded default meant the feed still said
    # "season opens in 9 days" the day after it opened.
    if today is None:
        from datetime import date as _d
        today = _d.today().isoformat()
    my_players = my_players or set()
    my_teams = my_teams or set()
    opponents = opponents or set()

    items: list[Item] = []
    for n in (news_items or []):
        cat = "injury" if n.blocks or n.status in ("questionable", "doubtful") else "trade"
        # Teams matter for relevance as much as players do. Without them the
        # Jacobs exempt-list story went unstarred for a manager holding two
        # Packers, which is exactly the item that should have been at the top.
        teams = sorted({abbr for word, abbr in TEAM_HINTS.items()
                        if word in (n.detail or "") or word in (n.player or "")})
        take = ""
        if n.blocks:
            take = ("Off the board entirely."
                    + (f" {n.beneficiary} inherits the work." if n.beneficiary else ""))
        elif n.beneficiary:
            take = f"Watch {n.beneficiary} — this is where the opportunity moves."
        elif "trade" in (n.detail or "").lower() or "unretired" in (n.detail or "").lower():
            take = "Changes the depth chart; re-check the affected players' role."
        # No takeaway is fine -- the item stays, unstarred. Cutting them means
        # the feed holds only what I already decided was actionable, which is how
        # you stop noticing what you did not think to look for. Four of week 1's
        # five box-score items were being dropped by this filter.
        # The beneficiary counts for relevance too. The Jacobs exempt-list item
        # went unstarred for a manager holding MarShawn Lloyd — and Lloyd is the
        # entire reason that story matters to him.
        who = [n.player] + ([n.beneficiary] if n.beneficiary else [])
        items.append(Item(cat, f"{n.player} — {n.status}", n.detail, takeaway=take,
                          players=who, teams=teams,
                          source=n.source, date=n.as_of))
    if matchup_table:
        items += matchup_items(matchup_table)
    items += preseason_takeaways(my_teams)
    items += calendar_items(today)

    items = [relevance(i, my_players, my_teams, opponents) for i in items]

    # The cap applies to NEWS only -- things that happened. Calendar entries are
    # dated in the FUTURE, so a plain recency sort put "fantasy playoffs, 106
    # days away" above an injury that happened this morning and pushed four of
    # today's five box-score items off the feed entirely. Context is not an
    # update and should not compete for the ten slots.
    NEWS_CATS = {"injury", "trade", "projection", "preseason"}
    news = [i for i in items if i.category in NEWS_CATS]
    context = [i for i in items if i.category not in NEWS_CATS]

    news.sort(key=lambda i: (i.date or "0000-00-00"), reverse=True)
    news = news[:FEED_LIMIT]

    order = {"injury": 0, "trade": 1, "projection": 2, "preseason": 3}
    news.sort(key=lambda i: (not i.starred, order.get(i.category, 9),
                             "" if not i.date else i.date), reverse=False)
    context.sort(key=lambda i: (i.date or "9999"))
    return [i.as_dict() for i in news + context[:4]]
