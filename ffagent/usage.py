"""Usage signals from nflverse. This is the edge.

Thesis: usage leads production by 1-3 weeks. Snap share, route participation
and target share move *before* the box score does, and the box score is what
your leaguemates read. We are not trying to beat the global market -- we are
trying to notice a role change before seven specific people do.

Cold-start reality (verified 2026-08-31): nflverse publishes one file per
season and the current-season file does not exist until games are played.
Weeks 1-3 are therefore the weakest part of this system, which is unfortunate
because that is when the wire matters most. See `Signals.confidence`.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import pandas as pd

BASE = "https://github.com/nflverse/nflverse-data/releases/download"
SKILL = ("QB", "RB", "WR", "TE")


def _try_parquet(url: str) -> pd.DataFrame | None:
    try:
        return pd.read_parquet(url)
    except Exception:
        return None


def load_stats(season: int) -> tuple[pd.DataFrame, int]:
    """Weekly player stats. Falls back to the prior season if the current
    file has not been published yet. Returns (df, season_actually_used)."""
    for s in (season, season - 1):
        df = _try_parquet(f"{BASE}/stats_player/stats_player_week_{s}.parquet")
        if df is not None and len(df):
            return df, s
    raise RuntimeError("no nflverse stats available")


def load_snaps(season: int) -> tuple[pd.DataFrame | None, int | None]:
    for s in (season, season - 1):
        df = _try_parquet(f"{BASE}/snap_counts/snap_counts_{s}.parquet")
        if df is not None and len(df):
            return df, s
    return None, None


def load_crosswalk() -> pd.DataFrame:
    """gsis_id <-> pfr_id <-> name. Needed because snap counts key on
    pfr_player_id while stats key on gsis. Sleeper carries gsis_id, so
    gsis is our spine."""
    p = _try_parquet(f"{BASE}/players/players.parquet")
    if p is None:
        return pd.DataFrame(columns=["gsis_id", "pfr_id", "display_name", "position"])
    return p[["gsis_id", "pfr_id", "display_name", "position", "latest_team"]]


@dataclass
class Signals:
    """Per-player usage deltas: recent window vs the window before it."""
    frame: pd.DataFrame
    season_used: int
    is_current_season: bool
    weeks_available: int

    @property
    def confidence(self) -> float:
        """How much to trust these signals at all.

        Prior-season data tells you nothing about a role change that happened
        in September, so it is heavily discounted. Within the current season,
        two games is noise and six is signal.
        """
        if not self.is_current_season:
            return 0.25
        return min(1.0, 0.20 + 0.13 * self.weeks_available)


def _weighted(df: pd.DataFrame, col: str) -> pd.Series:
    return df.groupby("gsis_id")[col].mean()


def build(season: int, window: int = 3, cfg=None) -> Signals:
    """`cfg` is a LeagueConfig. Pass it and points are recomputed under the
    league's own scoring rules instead of nflverse's hardcoded 1.0 PPR column.
    Omitting it keeps the old behaviour, which is wrong for any league that is
    not full PPR."""
    stats, s_used = load_stats(season)
    snaps, _ = load_snaps(season)
    xwalk = load_crosswalk()

    stats = stats[stats["position"].isin(SKILL)].copy()
    stats = stats.rename(columns={"player_id": "gsis_id"})
    stats = stats[stats["week"] <= 18]  # drop postseason

    max_wk = int(stats["week"].max())
    recent = stats[stats["week"] > max_wk - window]
    prior = stats[(stats["week"] <= max_wk - window) & (stats["week"] > max_wk - 2 * window)]

    base_cols = ["targets", "carries", "target_share", "air_yards_share"]
    for c in base_cols:
        if c not in stats.columns:
            stats[c] = 0.0

    out = pd.DataFrame({"gsis_id": stats["gsis_id"].unique()}).set_index("gsis_id")
    # Games actually played in each window. Without this, a player who missed
    # the prior window entirely shows a huge "delta" that is really just the
    # difference between playing and not playing. Availability != role change.
    out["games_recent"] = recent.groupby("gsis_id")["week"].nunique()
    out["games_prior"] = prior.groupby("gsis_id")["week"].nunique()
    for c in base_cols:
        out[f"{c}_recent"] = _weighted(recent, c)
        out[f"{c}_prior"] = _weighted(prior, c)
        out[f"{c}_delta"] = out[f"{c}_recent"].fillna(0) - out[f"{c}_prior"].fillna(0)

    # fantasy production, for the "usage up / points not yet" gap
    if cfg is not None:
        from .scoring import score_frame
        stats = stats.copy()
        stats["_pts"] = score_frame(stats, cfg)
        recent = stats[stats["week"] > max_wk - window]
        prior = stats[(stats["week"] <= max_wk - window) & (stats["week"] > max_wk - 2 * window)]
        ppr_col = "_pts"
    else:
        ppr_col = "fantasy_points_ppr" if "fantasy_points_ppr" in stats.columns else None
    if ppr_col:
        out["ppr_recent"] = _weighted(recent, ppr_col)
        out["ppr_prior"] = _weighted(prior, ppr_col)
        out["ppr_delta"] = out["ppr_recent"].fillna(0) - out["ppr_prior"].fillna(0)
    else:
        out["ppr_recent"] = out["ppr_prior"] = out["ppr_delta"] = 0.0

    # snap share via pfr crosswalk
    if snaps is not None and len(xwalk):
        snaps = snaps[snaps["position"].isin(SKILL)].copy()
        snaps = snaps.merge(
            xwalk[["gsis_id", "pfr_id"]], left_on="pfr_player_id", right_on="pfr_id", how="left"
        )
        snaps = snaps[snaps["gsis_id"].notna()]
        s_recent = snaps[snaps["week"] > max_wk - window].groupby("gsis_id")["offense_pct"].mean()
        s_prior = snaps[
            (snaps["week"] <= max_wk - window) & (snaps["week"] > max_wk - 2 * window)
        ].groupby("gsis_id")["offense_pct"].mean()
        out["snap_pct_recent"] = s_recent
        out["snap_pct_prior"] = s_prior
        out["snap_pct_delta"] = out["snap_pct_recent"].fillna(0) - out["snap_pct_prior"].fillna(0)
    else:
        out["snap_pct_recent"] = out["snap_pct_prior"] = out["snap_pct_delta"] = 0.0

    meta = xwalk.drop_duplicates("gsis_id").set_index("gsis_id")[
        ["display_name", "position", "latest_team"]
    ]
    out = out.join(meta, how="left").reset_index()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = out.fillna(0.0)

    return Signals(
        frame=out,
        season_used=s_used,
        is_current_season=(s_used == season),
        weeks_available=max_wk,
    )


def watchlist(
    sig: Signals,
    top: int = 25,
    min_snap_pct: float = 0.35,
    min_touches: float = 2.0,
    min_games_each_window: int = 2,
) -> pd.DataFrame:
    """Players whose *role* grew but whose *box score* has not caught up.

    That divergence is the whole thesis. A player with rising snaps, rising
    targets and flat points is one the market has not repriced yet. A player
    whose points already jumped is one everybody can see.

    The floors matter more than the scoring. Without them the list fills with
    fourth-stringers who played 90% of snaps in one blowout -- a huge delta off
    a base of zero, and completely meaningless. Anything that cannot hold a
    third of the snaps is not a real role.
    """
    df = sig.frame.copy()
    touches = df["targets_recent"] + df["carries_recent"]
    df = df[
        (df["snap_pct_recent"] >= min_snap_pct)
        & (touches >= min_touches)
        & (df["games_recent"] >= min_games_each_window)
        & (df["games_prior"] >= min_games_each_window)
    ]

    # normalise each signal so one unit is roughly one standard move
    def z(col: str) -> pd.Series:
        s = df[col]
        sd = s.std()
        return (s - s.mean()) / sd if sd and sd > 0 else s * 0.0

    # Weights are measured, not chosen. See calibration.BACKTEST: predicting
    # weeks 5-17 from weeks 1-4 across 2022-2025, target share scores 0.697,
    # targets 0.686, air-yards share 0.299, carries 0.264. The hand-set weights
    # this replaces gave air yards 0.7 and carries 0.6 against target share's
    # 1.2 -- roughly twice too generous for the two weakest signals.
    from .calibration import signal_weights
    W = signal_weights()
    df["role_score"] = (
        1.20 * z("snap_pct_delta")                       # no clean backtest; capped at target-share level
        + 1.20 * W["target_share"] / W["target_share"] * z("target_share_delta")
        + 1.20 * (W["targets"] / W["target_share"]) * z("targets_delta")
        + 1.20 * (W["air_yards_share"] / W["target_share"]) * z("air_yards_share_delta")
        + 1.20 * (W["carries"] / W["target_share"]) * z("carries_delta")
    )
    df["production_score"] = z("ppr_delta")

    # the gap: role moved more than production did
    df["edge"] = (df["role_score"] - df["production_score"]) * sig.confidence
    df = df[df["role_score"] > 0]
    return df.nlargest(top, "edge")[
        [
            # gsis_id must survive: it is the only key that joins this back to
            # Sleeper. Dropping it made the watchlist unusable by every caller.
            "gsis_id", "display_name", "position", "latest_team",
            "games_recent", "games_prior",
            "snap_pct_recent", "snap_pct_delta",
            "target_share_delta", "targets_delta", "carries_delta",
            "ppr_recent", "ppr_delta",
            "role_score", "production_score", "edge",
        ]
    ]


def fadelist(
    sig: Signals,
    top: int = 25,
    min_snap_pct: float = 0.35,
    min_touches: float = 2.0,
    min_games_each_window: int = 2,
) -> pd.DataFrame:
    """Players whose SCORING has outrun their usage.

    The same divergence as `watchlist`, read in the other direction, and the
    backtest says this is the stronger half by a factor of about 2.5. Points
    running ahead of role is usually touchdown luck, and it reverts: across
    2022-2025 this group underperformed a points-only model by 1.05 PPG a
    season, every season.

    Practical uses: who to bench in a close start/sit call, who to shop in a
    trade while their name still carries weight, and who NOT to claim off
    waivers just because the box score looks good.
    """
    df = sig.frame.copy()
    touches = df["targets_recent"] + df["carries_recent"]
    df = df[
        (touches >= min_touches)
        & (df["games_recent"] >= min_games_each_window)
        & (df["games_prior"] >= min_games_each_window)
    ]

    def z(col: str) -> pd.Series:
        s = df[col]
        sd = s.std()
        return (s - s.mean()) / sd if sd and sd > 0 else s * 0.0

    from .calibration import signal_weights
    W = signal_weights()
    df["role_score"] = (
        1.20 * z("snap_pct_delta")
        + 1.20 * z("target_share_delta")
        + 1.20 * (W["targets"] / W["target_share"]) * z("targets_delta")
        + 1.20 * (W["carries"] / W["target_share"]) * z("carries_delta")
    )
    df["production_score"] = z("ppr_delta")
    df["fade"] = (df["production_score"] - df["role_score"]) * sig.confidence
    df = df[df["production_score"] > 0]
    return df.nlargest(top, "fade")[
        [
            "gsis_id", "display_name", "position", "latest_team",
            "snap_pct_recent", "snap_pct_delta", "target_share_delta",
            "ppr_recent", "ppr_delta", "role_score", "production_score", "fade",
        ]
    ]
