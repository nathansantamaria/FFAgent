"""News overrides.

The structural problem this exists to solve: **ADP cannot know today's news.**

Fantasy Football Calculator's numbers are a trailing average over a window --
verified 2026-08-31, the window was Aug 24-31 across 8,161 drafts. So a player
whose situation changed on Aug 30 still carries an ADP built almost entirely
from drafts that happened before it. The market has not repriced him yet, and
in a slow-moving league it may not reprice him before your draft.

That cuts both ways and both are worth money:

- **Downside**: Josh Jacobs sat at ADP 31.6 the day after being placed on the
  Commissioner's Exempt List, where he cannot practise or play and only the
  Commissioner can reinstate him. The simulator happily listed him at 73%
  available for pick 29 as though he were a normal option. Anyone drafting off
  ADP alone takes him in the third round.
- **Upside**: his backup is not in the ADP at a meaningful price at all,
  because the data predates the news.

So availability is a hard gate applied *before* value, never a modifier
blended into it. A player who cannot play is not a cheap player -- he is not a
player. `BLOCKED` statuses remove him from the board entirely rather than
discounting his projection, because a 30% discount on someone who might miss
the whole season is a rounding error dressed up as analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Statuses that mean "cannot play", not "might play worse".
BLOCKED = {"exempt", "suspended", "ir", "pup", "nfi", "retired", "holdout", "released"}
DEGRADED = {"questionable", "doubtful", "limited", "committee", "timeshare"}


@dataclass
class NewsItem:
    player: str
    status: str                 # one of BLOCKED / DEGRADED, or "note"
    as_of: str                  # ISO date
    source: str
    detail: str
    beneficiary: str = ""       # who gains from this, if anyone
    returns: str = "unknown"    # ISO date, "unknown", or "week N"

    @property
    def blocks(self) -> bool:
        return self.status.lower() in BLOCKED

    def line(self) -> str:
        tag = "BLOCKED" if self.blocks else self.status.upper()
        return f"[{tag}] {self.player} — {self.detail} ({self.source}, {self.as_of})"


# Hand-maintained until an automated feed is wired. Kept explicit and dated so
# a stale entry is obvious rather than silently wrong.
OVERRIDES: list[NewsItem] = [
    NewsItem(
        "Josh Jacobs", "exempt", "2026-08-30", "NFL / ESPN / NFL.com",
        "Placed on Commissioner's Exempt List. Cannot practise or attend games. "
        "Only the Commissioner can remove him; first court date Nov 17 (Week 11). "
        "NFL discipline may follow independently of the legal process.",
        beneficiary="MarShawn Lloyd", returns="unknown"),
    NewsItem(
        "MarShawn Lloyd", "note", "2026-08-30", "NBC Sports",
        "Atop the Green Bay backfield with Jacobs exempt. Priority add in drafted "
        "leagues; middle-round upside back where drafts have not happened.",
        returns="active"),
    NewsItem(
        "Aaron Donald", "note", "2026-08-30", "NFL.com / ESPN / CBS",
        "Unretired on a one-year, $20M deal to rejoin the Rams after two seasons "
        "away, pairing with Myles Garrett (traded from Cleveland in June, reigning "
        "DPOY, record 23 sacks). Rams DEF is now the strongest unit on the board "
        "and its ADP of ~108 predates the signing by one day.",
        beneficiary="LA Rams Defense", returns="active"),
    NewsItem(
        "Kaleb Johnson", "note", "2026-08-30", "FOX Sports",
        "Traded from Pittsburgh to Green Bay the same day Jacobs was exempted. "
        "Muddies the Lloyd projection — this is a committee until proven otherwise.",
        returns="active"),
]


@dataclass
class NewsReport:
    blocked: list[NewsItem] = field(default_factory=list)
    degraded: list[NewsItem] = field(default_factory=list)
    beneficiaries: list[tuple[str, str]] = field(default_factory=list)
    stale_days: int = 0

    def __str__(self) -> str:
        out = []
        for i in self.blocked:
            out.append(i.line())
        for i in self.degraded:
            out.append(i.line())
        for who, why in self.beneficiaries:
            out.append(f"[GAINS]   {who} — {why}")
        return "\n".join(out) or "no overrides active"


ESPN_NEWS = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=50"

# Phrases that change availability, ranked so the most severe wins. Ordering
# matters: "placed on IR" also contains "placed on", and a headline about a
# player returning from IR must not be read as a blocking event.
BLOCK_PATTERNS = [
    ("exempt", r"commissioner'?s? exempt|exempt list"),
    ("suspended", r"suspend(?:ed|s|ing)"),
    ("ir", r"injured reserve|placed on IR"),
    ("pup", r"PUP list|physically unable to perform"),
    ("nfi", r"non-football injury"),
    ("retired", r"retir(?:es|ed|ing)"),
    ("released", r"releas(?:ed|es)|waived|cut"),
]
UNBLOCK = r"activat(?:ed|es)|return(?:s|ing|ed) (?:to practice|from)|reinstat|off the (?:PUP|exempt)"
MOVE_PATTERNS = [
    ("trade", r"trade[ds]?|acquir(?:e|ed|es)|blockbuster"),
    ("signing", r"sign(?:s|ed|ing)|unretir|ends? retirement|comes? out of retirement"),
    ("depth", r"starter|starting job|depth chart|promot|demot|benched"),
]


def fetch_espn(fetcher=None) -> list[dict]:
    """Pull the ESPN news feed. Returns raw articles; classification is separate
    so a change in their schema cannot silently alter my player statuses."""
    import json as _json
    import urllib.request
    if fetcher:
        return fetcher()
    try:
        with urllib.request.urlopen(ESPN_NEWS, timeout=20) as r:
            data = _json.loads(r.read())
    except Exception:
        return []
    out = []
    for a in data.get("articles", []):
        out.append({
            "headline": a.get("headline", ""),
            "summary": (a.get("description") or "")[:400],
            "published": (a.get("published") or "")[:10],
            "url": ((a.get("links") or {}).get("web") or {}).get("href", ""),
            "players": [c.get("description") or (c.get("athlete") or {}).get("displayName")
                        for c in (a.get("categories") or [])
                        if c.get("type") == "athlete"],
            "teams": [(c.get("team") or {}).get("description")
                      for c in (a.get("categories") or [])
                      if c.get("type") == "team"],
        })
    return out


def classify(article: dict) -> list[NewsItem]:
    """Turn an article into zero or more status overrides.

    Conservative by design. An article only produces a BLOCKED item when it
    names a player AND matches a blocking phrase AND does not read as a return.
    Everything else becomes a note, because the cost of wrongly benching
    someone all season is far higher than the cost of a missed flag I can
    catch on the next refresh.
    """
    import re
    text = f"{article.get('headline','')} {article.get('summary','')}"
    low = text.lower()
    if re.search(UNBLOCK, low):
        status = "note"
    else:
        status = "note"
        for name, pat in BLOCK_PATTERNS:
            if re.search(pat, low):
                status = name
                break
    if status == "note":
        for name, pat in MOVE_PATTERNS:
            if re.search(pat, low):
                status = "note"
                break
    out = []
    for pl in article.get("players", []) or []:
        if not pl:
            continue
        out.append(NewsItem(pl, status, article.get("published", ""),
                            "ESPN", article.get("headline", ""),
                            returns="unknown"))
    return out


def ingest(fetcher=None) -> tuple[list[dict], list[NewsItem]]:
    """Fetch, classify, and merge with the hand-maintained overrides.

    Hand-written entries win on conflict. An automated classifier reading a
    headline is weaker evidence than a human who read the story, and the
    Jacobs entry is more precise than anything a regex will produce.
    """
    arts = fetch_espn(fetcher)
    auto: list[NewsItem] = []
    for a in arts:
        auto.extend(classify(a))
    manual = {i.player.lower() for i in OVERRIDES}
    merged = list(OVERRIDES) + [i for i in auto if i.player.lower() not in manual]
    return arts, merged


def index(items: list[NewsItem] | None = None) -> dict[str, NewsItem]:
    return {i.player.lower(): i for i in (items if items is not None else OVERRIDES)}


def apply(board: list[dict], items: list[NewsItem] | None = None) -> tuple[list[dict], NewsReport]:
    """Remove unavailable players from a board and report what changed.

    `board` is a list of dicts with at least a "name" key -- the ADP rows the
    simulator uses.
    """
    idx = index(items)
    rep = NewsReport()
    kept = []
    for row in board:
        it = idx.get(row["name"].lower())
        if it and it.blocks:
            rep.blocked.append(it)
            if it.beneficiary:
                rep.beneficiaries.append(
                    (it.beneficiary, f"inherits work with {it.player} unavailable"))
            continue
        if it and it.status.lower() in DEGRADED:
            rep.degraded.append(it)
            row = {**row, "adp": row["adp"] + 6.0, "news": it.detail}
        kept.append(row)
    return kept, rep


def adp_staleness(window_end: str, today: str | None = None) -> int:
    """How many days of news the ADP cannot possibly contain.

    Worth printing on every draft run. It is the size of the window in which
    you know something the market does not.
    """
    t = date.fromisoformat(today) if today else date.today()
    return (t - date.fromisoformat(window_end)).days


def unpriced_news(items: list[NewsItem] | None = None, window_end: str = "",
                  today: str | None = None) -> list[NewsItem]:
    """News that broke after the ADP window closed -- the exploitable set."""
    if not window_end:
        return []
    cutoff = date.fromisoformat(window_end)
    out = []
    for i in (items if items is not None else OVERRIDES):
        if date.fromisoformat(i.as_of) >= cutoff:
            out.append(i)
    return out
