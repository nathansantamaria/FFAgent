"""Source registry.

Two failure modes to design against, and they pull in opposite directions.

Adding sources indiscriminately is the first. Every extra feed is another
thing that can 404 mid-season, another schema that drifts, another set of ids
to reconcile. A source earns its place by telling you something the ones you
already have do not.

Relying on one is the second. nflverse publishes once a season and lags live
news by days; if the pipeline only knows what nflverse knows, a Wednesday
practice report never reaches it.

So: every source declares what it uniquely contributes, whether it is
reachable, and how stale it is. Anything unreachable degrades to a note rather
than an exception -- a Sunday sweep must still run when a feed is down.

Reachability was probed on 2026-08-31 from a sandbox with a restricted egress
allowlist. `available()` re-checks at runtime; do not trust the constants.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"


@dataclass
class Source:
    key: str
    contributes: str          # what this gives that nothing else does
    url: str = ""
    cadence: str = ""
    weight: float = 1.0       # confidence in this feed, not importance of the stat
    needs_key: bool = False
    note: str = ""
    loader: Callable[..., Any] | None = None

    def available(self, season: int | None = None) -> bool:
        if not self.loader:
            return False
        try:
            return self.loader(season) is not None
        except Exception:
            return False


def _parquet(path: str):
    def load(season: int | None = None):
        url = f"{NFLVERSE}/{path.format(season=season)}"
        try:
            return pd.read_parquet(url)
        except Exception:
            return None
    return load


# --- verified reachable -------------------------------------------------

REGISTRY: dict[str, Source] = {
    "stats": Source(
        "stats", "Weekly box score and target share. The spine.",
        f"{NFLVERSE}/stats_player/", "weekly in season", 1.0,
        loader=_parquet("stats_player/stats_player_week_{season}.parquet")),

    "snaps": Source(
        "snaps", "Snap share. The single best role signal we have.",
        f"{NFLVERSE}/snap_counts/", "weekly in season", 1.0,
        loader=_parquet("snap_counts/snap_counts_{season}.parquet")),

    "injuries": Source(
        "injuries", "Practice participation. The only source here that leads "
                    "the box score rather than describing it -- a DNP on "
                    "Wednesday is knowable days before the inactive list.",
        f"{NFLVERSE}/injuries/", "weekly, Wed-Fri", 0.9,
        loader=_parquet("injuries/injuries_{season}.parquet")),

    "depth": Source(
        "depth", "Team depth chart rank and slot. Weak on its own -- 3-WR "
                 "base means WR3 plays nearly every down -- but it catches a "
                 "demotion before usage does.",
        f"{NFLVERSE}/depth_charts/", "near-daily", 0.5,
        loader=_parquet("depth_charts/depth_charts_{season}.parquet")),

    "pfr_rec": Source(
        "pfr_rec", "Drops and broken tackles. Separates bad hands from bad usage.",
        f"{NFLVERSE}/pfr_advstats/", "weekly", 0.6,
        loader=_parquet("pfr_advstats/advstats_week_rec_{season}.parquet")),

    "players": Source(
        "players", "The gsis <-> pfr <-> espn crosswalk. Nothing joins without it.",
        f"{NFLVERSE}/players/", "static", 1.0,
        loader=lambda season=None: _parquet("players/players.parquet")(None)),

    # --- reachable from a normal network, not from the build sandbox ----

    "participation": Source(
        "participation", "Actual on-field personnel for every play, which yields "
                         "route participation and targets per route run. The "
                         "strongest predictor measured in this project (0.918 vs "
                         "0.787 for target share) and the only source that "
                         "separates a receiver's role from his snap count.",
        f"{NFLVERSE}/pbp_participation/", "weekly in season", 1.0,
        loader=_parquet("pbp_participation/pbp_participation_{season}.parquet")),

    "pfr_rush": Source(
        "pfr_rush", "Rushing yards split before and after contact. Separates a back "
                    "producing behind a good line from one creating on his own — the "
                    "first regresses when the line changes, the second travels.",
        f"{NFLVERSE}/pfr_advstats/", "weekly", 0.75,
        loader=_parquet("pfr_advstats/advstats_week_rush_{season}.parquet")),

    "ftn_charting": Source(
        "ftn_charting", "Play charting: motion, play action, screens, RPO, blitzers, "
                        "drops, contested catches. Context for why a week looked the "
                        "way it did.",
        f"{NFLVERSE}/ftn_charting/", "weekly", 0.6,
        loader=_parquet("ftn_charting/ftn_charting_{season}.parquet")),

    "espn_projections": Source(
        "espn_projections", "ESPN's own 2026 per-week projections, PPR draft ranks, "
                            "bye weeks and injury status. The only forward-looking "
                            "projection here -- everything else I compute is derived "
                            "from last season and cannot see a changed situation.",
        "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/"
        "segments/0/leaguedefaults/3?view=kona_player_info", "daily", 0.85,
        note="public, needs an x-fantasy-filter header; no auth"),

    "espn_news": Source(
        "espn_news", "Breaking NFL news feed. Catches exempt-list and roster moves "
                     "that ADP structurally cannot contain.",
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news", "hourly", 0.7,
        note="public, no auth"),

    "ffc_adp": Source(
        "ffc_adp", "Market consensus ADP with per-player variance, which is what "
                   "makes survival simulation possible at all.",
        "https://fantasyfootballcalculator.com/api/v1/adp/ppr", "daily", 0.8,
        note="public; NOTE the teams= parameter is ignored, payload is blended format"),

    "sleeper_trending": Source(
        "sleeper_trending", "What the wider Sleeper market is claiming right now. "
                            "Not an edge -- it is the consensus we are trying to "
                            "front-run, so it is a check on whether we are early.",
        "https://api.sleeper.app/v1/players/nfl/trending/add", "hourly", 0.7,
        note="public, no auth"),

    "espn_odds": Source(
        "espn_odds", "Over/under and spread per game, from ESPN's scoreboard. Game "
                     "environment is the one thing the market knows that player data "
                     "does not, and it drives passing volume directly. This replaces "
                     "the paid odds API I had listed as a gap — same numbers, no key.",
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
        "daily", 0.8, note="public, no auth; verified 31 Aug 2026"),

    "weather": Source(
        "weather", "Wind above 15mph craters passing volume. Cheap, narrow, real.",
        "https://api.open-meteo.com/v1/forecast", "daily", 0.4,
        note="verified reachable, no key required"),
}


@dataclass
class SourceReport:
    live: list[str] = field(default_factory=list)
    down: list[str] = field(default_factory=list)
    unconfigured: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        total = len(self.live) + len(self.down) + len(self.unconfigured)
        return len(self.live) / total if total else 0.0

    def __str__(self) -> str:
        lines = [f"sources: {len(self.live)} live, {len(self.down)} down, "
                 f"{len(self.unconfigured)} unconfigured ({self.coverage:.0%} coverage)"]
        for k in self.down:
            lines.append(f"  down: {k} — {REGISTRY[k].contributes.split('.')[0]}")
        for k in self.unconfigured:
            lines.append(f"  needs setup: {k} — {REGISTRY[k].note}")
        return "\n".join(lines)


def probe(season: int) -> SourceReport:
    """Check every source. Degrade, never raise."""
    r = SourceReport()
    for key, src in REGISTRY.items():
        if src.needs_key:
            r.unconfigured.append(key)
        elif src.loader is None:
            r.unconfigured.append(key)
        elif src.available(season):
            r.live.append(key)
        else:
            r.down.append(key)
    return r


def practice_flags(season: int, week: int | None = None) -> pd.DataFrame:
    """Practice participation, the leading injury signal.

    A player who did not practise Wednesday and Thursday is far more likely to
    sit than his official status suggests, and that is knowable on Thursday
    rather than at 11:30 on Sunday.
    """
    df = REGISTRY["injuries"].loader(season)
    if df is None or not len(df):
        return pd.DataFrame(columns=["gsis_id", "week", "report_status", "practice_status"])
    if week is not None:
        df = df[df["week"] == week]
    keep = ["gsis_id", "week", "full_name", "position", "team",
            "report_status", "practice_status", "report_primary_injury"]
    return df[[c for c in keep if c in df.columns]]


def source_weights(cfg) -> dict[str, float]:
    """League setup changes which signals matter.

    Not a cosmetic adjustment. In a PPR league receptions are the currency, so
    target share and route data carry the projection. In a standard league
    touchdowns and carries dominate and reception-heavy signals mislead. A
    superflex league makes quarterback signals matter far more than the same
    data would in a single-QB league.
    """
    w = {k: s.weight for k, s in REGISTRY.items()}
    ppr = float((cfg.scoring or {}).get("rec", 0.0))
    if ppr >= 0.5:
        w["stats"] *= 1.0 + 0.2 * ppr          # target share is the currency
    else:
        w["depth"] *= 1.3                       # goal-line role matters more
        w["pfr_rec"] *= 0.8
    if "SUPER_FLEX" in cfg.starters:
        w["vegas"] *= 1.2                       # QB scoring tracks game total
    if cfg.teams <= 8:
        w["sleeper_trending"] *= 0.6            # shallow wire, consensus matters less
    return {k: round(v, 2) for k, v in w.items()}
