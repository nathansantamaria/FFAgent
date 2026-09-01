"""Window -> job dispatch.

Each job reads the world, proposes decisions, and records them. Nothing here
executes: writes are the write layer's job and only run when explicitly taken
out of shadow mode. Keeping proposal and execution in different modules is
deliberate -- it means "what would it do" is always answerable without risk.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import decisions, trades, waivers
from .lineup import Player, optimise, explain
from .state import World

ET_NOTE = "times shown UTC"


def _log(d: decisions.Decision) -> decisions.Decision:
    decisions.record(d)
    return d


def _fac(name: str, value: float, weight: float, w: World) -> decisions.Factor:
    return decisions.Factor(name, round(float(value), 3), weight, "nflverse", str(w.signals.season_used))


# --- jobs ---------------------------------------------------------------

def inactive_sweep(w: World) -> list[decisions.Decision]:
    """Sunday 11:30. The highest-value window of the week.

    Compares the lineup as it stands against the lineup given who has been
    ruled out, and proposes only the swaps that actually change who starts.
    """
    if not w.my_roster or not w.lineup:
        return []
    # Only act if someone actually in the lineup is unavailable. A benched
    # player being Out is not news.
    out_now = [p for p in w.lineup.assignment.values() if not p.playable]
    if not out_now:
        return []

    after = optimise(w.my_roster, w.cfg, current=w.lineup.assignment)
    changes = after.diff(w.lineup)
    if not changes:
        return []

    now = datetime.now(timezone.utc)
    lines = explain(w.lineup, after)
    entering, leaving = after.player_diff(w.lineup)
    # One decision, not one per slot. A lineup change is a single thing you
    # approve; emitting six rows that each repeat the same thesis buries the
    # actual choice and makes the dashboard unreadable. The write layer still
    # executes it as N separate verified writes.
    return [_log(decisions.Decision(
        type="start_sit",
        player=", ".join(p.name for p in entering) or "lineup",
        action=f"{len(changes)} lineup change{'s' if len(changes) != 1 else ''}",
        thesis=" · ".join(lines),
        confidence=round(0.9 * min(1.0, 0.4 + w.signal_confidence), 2),
        execute_at=now.isoformat(),
        expires_at=(now + timedelta(hours=1, minutes=20)).isoformat(),
        window="inactives",
        factors=[_fac("projected point swing", after.total - w.lineup.total, 1.0, w),
                 _fac("starters unavailable", float(len(out_now)), 1.0, w)],
        alternatives=[{"action": "leave the lineup alone",
                       "why_rejected": f"{', '.join(p.name for p in out_now)} unavailable"}],
    ))]


def queue_claims(w: World) -> list[decisions.Decision]:
    """Tuesday 22:00. Claims lock at 23:00; we submit with slack."""
    if not w.my_roster or not w.free_agents:
        return []
    weeks_left = max(1, w.cfg.playoff_start_week - w.week)
    claims = waivers.build_claims(
        w.my_roster, w.free_agents, w.cfg,
        weeks_left=weeks_left, signal_confidence=w.signal_confidence,
    )
    now = datetime.now(timezone.utc)
    return [_log(decisions.Decision(
        type="waiver", player=c.add.name,
        action=f"claim, drop {c.drop.name if c.drop else '-'}"
               + (f", bid ${c.bid}" if c.bid else ""),
        thesis=c.rationale, confidence=c.confidence,
        execute_at=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(),
        window="waiver_submit",
        factors=[_fac("starting lineup gain", c.gain, 1.0, w),
                 _fac("usage divergence", c.add.edge, 0.8, w)],
        alternatives=[{"action": "no claim", "why_rejected": "would not change who starts"}],
    )) for c in claims]


def trade_scan(w: World) -> list[decisions.Decision]:
    """Runs with the weekend prep window. Fires rarely by design."""
    if not w.my_roster or not w.league_rosters:
        return []
    weeks_left = max(1, w.cfg.playoff_start_week - w.week)
    found = trades.find(w.my_roster, w.league_rosters, w.cfg, weeks_left=weeks_left)
    sent = trades.propose(found)
    now = datetime.now(timezone.utc)
    ds = []
    for ev in sent:
        ds.append(_log(decisions.Decision(
            type="trade", player=", ".join(p.name for p in ev.receive),
            action=ev.summary(),
            thesis=trades.draft_message(ev),
            confidence=ev.confidence,
            execute_at=now.isoformat(),
            expires_at=(now + timedelta(days=3)).isoformat(),
            window="weekend_prep",
            factors=[_fac("my gain per week", ev.my_gain_wk, 1.0, w),
                     _fac("their gain per week", ev.their_gain_wk, 0.6, w)],
            alternatives=[{"action": "send nothing",
                           "why_rejected": f"cleared all {len(ev.gates)} gates; "
                                           f"my gain {ev.my_gain_wk:+.1f}/wk, "
                                           f"theirs {ev.their_gain_wk:+.1f}/wk"}],
        )))
    if not sent and found:
        w.notes.append(f"{len(found)} trades cleared the gates but were held by the rate limit.")
    return ds


def injury_scan(w: World) -> list[decisions.Decision]:
    """Thursday. Surfaces questionable starters early rather than at 12:55."""
    if not w.lineup:
        return []
    flagged = [p for p in w.lineup.assignment.values()
               if p.status and p.status.upper() not in ("OUT", "IR", "BYE")]
    for p in flagged:
        w.notes.append(f"{p.name} is {p.status}; decide before Sunday, not during it.")
    return []


def reproject(w: World) -> list[decisions.Decision]:
    return trade_scan(w)


def read_results(w: World) -> list[decisions.Decision]:
    w.notes.append("Waivers processed. Wire re-scored on next run.")
    return []


def lock_check(w: World) -> list[decisions.Decision]:
    return inactive_sweep(w)


def final_check(w: World) -> list[decisions.Decision]:
    return inactive_sweep(w)


def refresh_all(w: World) -> list[decisions.Decision]:
    """Re-pull every source and rebuild the board. Proposes nothing.

    Separated from the decision jobs on purpose: a refresh that also proposes
    is a refresh you cannot run safely at 06:00 or sixty minutes before a
    deadline. This one only makes the world current.
    """
    from . import sources
    rep = sources.probe(w.season)
    w.notes.append(f"refresh: {len(rep.live)} live, {len(rep.down)} down "
                   f"({rep.coverage:.0%} coverage)")
    for k in rep.down:
        w.notes.append(f"  source down: {k} — decisions this cycle are on partial data")
    return []


JOBS = {
    "refresh_all": refresh_all,
    "inactive_sweep": inactive_sweep,
    "queue_claims": queue_claims,
    "injury_scan": injury_scan,
    "reproject": reproject,
    "read_results": read_results,
    "lock_check": lock_check,
    "final_check": final_check,
    "trade_scan": trade_scan,
}


def run_window(w: World, job: str) -> list[decisions.Decision]:
    fn = JOBS.get(job)
    if fn is None:
        raise KeyError(f"unknown job {job!r}; known: {sorted(JOBS)}")
    return fn(w)
