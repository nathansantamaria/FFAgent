"""Measuring whether the signals actually work, and weighting them by that.

Written after backtesting the system's own core assumption on four seasons of
nflverse data (2022-2025, 972 player-seasons, predicting weeks 5-17 PPG from
weeks 1-4). The results changed the design, so they are recorded here rather
than in a comment somewhere.

**Finding 0, added later and the most useful of the lot: route participation
beats everything else I have measured.** `pbp_participation` lists the actual
player ids on the field for every play, so route rate — the share of his team's
dropbacks a receiver was on the field for — is computable directly rather than
approximated by snap share. Combined with targets per route run it scores 0.918
against rest-of-season PPG, where target share scores 0.787 on the same players
over the same weeks.

The reason it beats snap share is mundane: run-blocking snaps count the same in
a snap-share number and are worth nothing in PPR. Route rate is the denominator
target share should have been measured against all along.

**Finding 1: raw usage does not beat raw points.** Predicting rest-of-season
PPG, early points score Spearman 0.784 against blended usage 0.774 and target
share 0.697. The claim that "usage leads production" is true in the sense that
usage is *nearly as* predictive, not in the sense that it is better. Anyone
who told you otherwise, including this project until now, was overstating it.

**Finding 2: usage adds real but modest information on top of points.** After
fitting rest-of-season points on early points, usage still correlates +0.14
with the residual. Small. Real. Not the dominant edge it was billed as.

**Finding 3, the one that matters: the signal is asymmetric.** Splitting on
usage-minus-points divergence:

    usage >> points  ->  beat the points model by only +0.42 PPG
    points >> usage  ->  UNDERPERFORMED it by -1.05 PPG

The fade is two and a half times stronger than the buy, and it held in 4 of 4
seasons with a positive spread every year. Players whose scoring has outrun
their usage regress hard -- touchdown luck reverting -- and that is far more
reliable than finding the next breakout.

This inverts the original design. The watchlist ranked players by
role-minus-production descending, hunting buys. The stronger, better-evidenced
use of the same number is identifying who to *avoid, bench, or sell*. Both are
now surfaced, weighted by measured strength rather than by which is more fun.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "calibration.db"

# Measured on 2022-2025, weeks 1-4 predicting weeks 5-17, RB/WR/TE, n=972.
BACKTEST = {
    # Measured on WR/TE only, 2025, weeks 1-4 -> weeks 5-17, n=178. Not
    # directly comparable to the RB/WR/TE numbers below (different sample), but
    # the comparison WITHIN that sample is clean and decisive: target share
    # scored 0.787 against the same players over the same weeks.
    "route_rate_x_tprr": {"spearman": 0.918, "n": 178, "seasons": "2025"},
    "tprr": {"spearman": 0.839, "n": 178, "seasons": "2025"},
    "early_points": {"spearman": 0.784, "n": 972, "seasons": "2022-2025"},
    "usage_blend": {"spearman": 0.774, "n": 972, "seasons": "2022-2025"},
    "target_share": {"spearman": 0.697, "n": 972, "seasons": "2022-2025"},
    "targets": {"spearman": 0.686, "n": 972, "seasons": "2022-2025"},
    "air_yards_share": {"spearman": 0.299, "n": 972, "seasons": "2022-2025"},
    "carries": {"spearman": 0.264, "n": 972, "seasons": "2022-2025"},
}

# Effect sizes in PPG, by season. Kept per-season so the stability is visible
# rather than hidden inside an average.
DIVERGENCE_EFFECT = {
    2022: {"buy": +0.59, "fade": -1.38},
    2023: {"buy": +0.12, "fade": -1.10},
    2024: {"buy": +0.37, "fade": -0.51},
    2025: {"buy": +0.41, "fade": -1.08},
}

BUY_EFFECT = sum(v["buy"] for v in DIVERGENCE_EFFECT.values()) / len(DIVERGENCE_EFFECT)
FADE_EFFECT = sum(v["fade"] for v in DIVERGENCE_EFFECT.values()) / len(DIVERGENCE_EFFECT)
FADE_MULTIPLE = round(abs(FADE_EFFECT) / max(0.01, BUY_EFFECT), 2)


def signal_weights() -> dict[str, float]:
    """Weights proportional to measured predictive power, not to intuition.

    Normalised so the strongest signal is 1.0. Carries and air-yards share are
    weak enough (0.26-0.30) that the original hand-set weights -- 0.6 and 0.7
    against target share's 1.2 -- were roughly twice too generous.
    """
    best = max(v["spearman"] for v in BACKTEST.values())
    return {k: round(v["spearman"] / best, 3) for k, v in BACKTEST.items()}


# --- ADP recency --------------------------------------------------------

def adp_recency_weight(window_end: str, today: str | None = None,
                       half_life_days: float = 10.0) -> float:
    """How much to trust an ADP snapshot given its age.

    ADP decays fast in August and barely at all in June, because the news that
    moves it is concentrated in camp and cutdowns. Half-life of ~10 days in
    season-approach; a snapshot from before last season is worth almost nothing
    for player *value* and is only useful for measuring how the market behaves.
    """
    t = date.fromisoformat(today) if today else date.today()
    age = max(0, (t - date.fromisoformat(window_end)).days)
    return round(0.5 ** (age / half_life_days), 3)


def stale_adp_warning(window_end: str, today: str | None = None) -> str | None:
    w = adp_recency_weight(window_end, today)
    if w >= 0.8:
        return None
    t = date.fromisoformat(today) if today else date.today()
    age = (t - date.fromisoformat(window_end)).days
    return (f"ADP snapshot is {age} days old (weight {w:.2f}). Preseason moves fast; "
            f"treat rankings as a prior and let news override them.")


# --- outcome tracking ---------------------------------------------------

@dataclass
class Prediction:
    source: str               # which signal or feed made the call
    subject: str              # player
    predicted: float
    horizon_weeks: int
    made_on: str
    actual: float | None = None
    scored_on: str = ""
    meta: dict = field(default_factory=dict)


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, subject TEXT,
        predicted REAL, horizon_weeks INT, made_on TEXT,
        actual REAL, scored_on TEXT, meta TEXT)""")
    return c


def record(p: Prediction) -> None:
    with _conn() as c:
        c.execute("INSERT INTO predictions (source,subject,predicted,horizon_weeks,"
                  "made_on,actual,scored_on,meta) VALUES (?,?,?,?,?,?,?,?)",
                  (p.source, p.subject, p.predicted, p.horizon_weeks, p.made_on,
                   p.actual, p.scored_on, json.dumps(p.meta)))


def score(subject: str, actual: float, on: str) -> int:
    with _conn() as c:
        cur = c.execute("UPDATE predictions SET actual=?, scored_on=? "
                        "WHERE subject=? AND actual IS NULL", (actual, on, subject))
        return cur.rowcount


def accuracy() -> dict[str, dict]:
    """Mean absolute error and bias per source, once outcomes exist.

    Bias matters as much as error. A source that is consistently 2 points high
    is fixable by subtracting 2; a source with the same MAE and no bias is not.
    """
    with _conn() as c:
        rows = c.execute("SELECT source, predicted, actual FROM predictions "
                         "WHERE actual IS NOT NULL").fetchall()
    by: dict[str, list[tuple[float, float]]] = {}
    for s, p, a in rows:
        by.setdefault(s, []).append((p, a))
    out = {}
    for s, vals in by.items():
        errs = [p - a for p, a in vals]
        out[s] = {
            "n": len(vals),
            "mae": round(sum(abs(e) for e in errs) / len(errs), 3),
            "bias": round(sum(errs) / len(errs), 3),
        }
    return out


def learned_weights(floor: float = 0.2, min_n: int = 25) -> dict[str, float]:
    """Re-weight sources by observed error once there is enough of it.

    Falls back to the backtested weights until a source has `min_n` scored
    predictions. Weighting on five observations is how you end up confidently
    trusting noise -- the same mistake the watchlist made with one-game
    snap-share spikes.
    """
    acc = accuracy()
    base = signal_weights()
    out = dict(base)
    usable = {s: v for s, v in acc.items() if v["n"] >= min_n}
    if not usable:
        return out
    best = min(v["mae"] for v in usable.values()) or 1.0
    for s, v in usable.items():
        out[s] = round(max(floor, best / v["mae"]), 3)
    return out


def summary() -> str:
    w = signal_weights()
    lines = [
        f"Backtest: 2022-2025, {BACKTEST['early_points']['n']} player-seasons, "
        f"weeks 1-4 -> weeks 5-17 (RB/WR/TE)",
        "",
        "  signal            spearman   weight",
    ]
    for k, v in sorted(BACKTEST.items(), key=lambda kv: -kv[1]["spearman"]):
        lines.append(f"  {k:<18}{v['spearman']:>7.3f}{w[k]:>9.3f}")
    lines += [
        "",
        f"  divergence buy signal : {BUY_EFFECT:+.2f} PPG",
        f"  divergence fade signal: {FADE_EFFECT:+.2f} PPG",
        f"  fade is {FADE_MULTIPLE}x stronger, and held in 4 of 4 seasons",
    ]
    scored = accuracy()
    lines.append("")
    lines.append(f"  live outcomes scored: {sum(v['n'] for v in scored.values())}"
                 f" — until this grows, weights are backtested, not learned")
    return "\n".join(lines)
