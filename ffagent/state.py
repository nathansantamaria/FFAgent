"""Assembles everything the jobs reason about into one object.

Kept separate from the jobs themselves so the whole system can be tested
without network access: `build()` takes an optional `fetch` shim, so a fixture
can stand in for Sleeper. Every bug I found in this project came from testing
against real data, and a world-builder that can only run online is one you
stop testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import sleeper, sources, usage
from .config import LeagueConfig, load as load_config
from .lineup import Lineup, Player, optimise, project
from .waivers import Candidate


@dataclass
class World:
    cfg: LeagueConfig
    week: int
    season: int
    my_user_id: str
    my_roster: list[Player]
    league_rosters: dict[str, list[Player]]     # manager display name -> roster
    free_agents: list[Candidate]
    signals: usage.Signals
    practice: dict[str, str] = field(default_factory=dict)   # gsis_id -> practice status
    source_report: object | None = None
    lineup: Lineup | None = None          # what is set right now
    current: Lineup | None = None         # same, but None if Sleeper gave us nothing
    notes: list[str] = field(default_factory=list)

    @property
    def signal_confidence(self) -> float:
        return self.signals.confidence


def current_lineup(roster: list[Player], starter_ids: list[str], cfg: LeagueConfig) -> Lineup | None:
    """Reconstruct the lineup as Sleeper has it.

    Sleeper returns `starters` positionally, aligned to `roster_positions`, with
    "0" for an empty slot. Order is the source of truth for which slot a player
    occupies -- there are no slot labels in the payload.
    """
    if not starter_ids:
        return None
    by_id = {p.player_id: p for p in roster}
    assignment: dict[str, Player] = {}
    unfilled: list[str] = []
    seen: dict[str, int] = {}
    for slot, pid in zip(cfg.starters, starter_ids):
        seen[slot] = seen.get(slot, 0) + 1
        label = f"{slot}{seen[slot]}" if cfg.starters.count(slot) > 1 else slot
        p = by_id.get(pid)
        if p is None:
            unfilled.append(label)
        else:
            assignment[label] = p
    started = {p.player_id for p in assignment.values()}
    bench = [p for p in roster if p.player_id not in started]
    return Lineup(assignment, bench, round(sum(p.proj for p in assignment.values()), 2), unfilled)


def _proj_table(sig: usage.Signals) -> dict[str, dict[str, float]]:
    """gsis_id -> the inputs `project()` needs."""
    out: dict[str, dict[str, float]] = {}
    for _, r in sig.frame.iterrows():
        out[str(r["gsis_id"])] = {
            "recent": float(r.get("ppr_recent", 0.0)),
            "season": float(r.get("ppr_prior", 0.0)) or float(r.get("ppr_recent", 0.0)),
            "games": int(r.get("games_recent", 0) or 0),
        }
    return out


def build(
    league_id: str,
    my_user_id: str | None = None,
    fetch: dict[str, Callable[..., Any]] | None = None,
) -> World:
    f = fetch or {}
    get_state = f.get("nfl_state", sleeper.nfl_state)
    get_rosters = f.get("rosters", sleeper.rosters)
    get_users = f.get("users", sleeper.users)
    get_players = f.get("players", sleeper.players)
    get_cfg = f.get("config", load_config)

    state = get_state()
    season, week = int(state["season"]), int(state.get("week") or 0)
    cfg = get_cfg(league_id)

    plyrs = get_players()
    users = {u["user_id"]: (u.get("display_name") or u["user_id"]) for u in get_users(league_id)}
    rosters = get_rosters(league_id)

    sig = usage.build(season, cfg=cfg)
    try:
        pf = sources.practice_flags(season, week=week or None)
        practice = dict(zip(pf["gsis_id"].astype(str), pf["practice_status"].fillna("")))
    except Exception:
        practice = {}
    ptab = _proj_table(sig)
    edges = {
        str(r["gsis_id"]): float(r["edge"])
        for _, r in usage.watchlist(sig, top=200).iterrows()
    } if len(sig.frame) else {}

    def to_player(pid: str) -> Player | None:
        meta = plyrs.get(pid)
        if not meta:
            # DEF entries key on team abbreviation, not a numeric id
            return Player(pid, pid, "DEF", 7.0) if len(pid) <= 4 and pid.isalpha() else None
        gsis = meta.get("gsis_id") or ""
        t = ptab.get(gsis, {})
        proj = project(
            t.get("recent", 0.0), t.get("season", 0.0),
            edges.get(gsis, 0.0), sig.confidence, t.get("games", 0),
        )
        status = (meta.get("injury_status") or "").strip()
        # Practice participation overrides a stale official tag. Sleeper's
        # injury_status lags the beat reporting; two DNPs is a stronger signal
        # of a Sunday absence than a status field nobody has updated.
        if not status and gsis in practice:
            pr = practice[gsis]
            if "Did Not Participate" in pr:
                status = "Doubtful"
            elif "Limited" in pr:
                status = "Questionable"
        return Player(
            pid,
            meta.get("full_name") or f"{meta.get('first_name','')} {meta.get('last_name','')}".strip(),
            meta.get("position") or "",
            proj,
            status,
            meta.get("team") or "",
        )

    league_rosters: dict[str, list[Player]] = {}
    mine: list[Player] = []
    my_starters: list[str] = []
    rostered: set[str] = set()
    for r in rosters:
        owner = users.get(r.get("owner_id") or "", f"roster {r.get('roster_id')}")
        squad = [p for p in (to_player(pid) for pid in (r.get("players") or [])) if p]
        rostered |= {p.player_id for p in squad}
        if my_user_id and r.get("owner_id") == my_user_id:
            mine = squad
            my_starters = [p for p in (r.get("starters") or []) if p]
        else:
            league_rosters[owner] = squad

    # Free agents worth surfacing: usage divergence, not yet on a roster.
    gsis_to_sleeper = {
        (m.get("gsis_id") or ""): pid for pid, m in plyrs.items() if m.get("gsis_id")
    }
    free: list[Candidate] = []
    for _, row in usage.watchlist(sig, top=60).iterrows():
        pid = gsis_to_sleeper.get(str(row["gsis_id"]))
        if not pid or pid in rostered:
            continue
        t = ptab.get(str(row["gsis_id"]), {})
        free.append(
            Candidate(
                pid, str(row["display_name"]), str(row["position"]),
                project(t.get("recent", 0.0), t.get("season", 0.0),
                        float(row["edge"]), sig.confidence, t.get("games", 0)),
                float(row["edge"]),
            )
        )

    w = World(cfg, week, season, my_user_id or "", mine, league_rosters, free, sig,
              practice=practice, source_report=sources.probe(season))
    if mine:
        # The baseline must be the lineup ACTUALLY SET on Sleeper, not a fresh
        # optimum. Optimising the baseline benches the injured players for you,
        # so the Sunday sweep compares optimal against optimal, finds nothing,
        # and the highest-value job in the system silently does no work.
        w.current = current_lineup(mine, my_starters, cfg)
        w.lineup = w.current or optimise(mine, cfg)
    if not sig.is_current_season:
        w.notes.append(
            f"Cold start: usage from {sig.season_used}, confidence {sig.confidence:.2f}. "
            "Treat every claim as provisional until live games land."
        )
    if not mine and my_user_id:
        w.notes.append(f"No roster found for user {my_user_id} in this league.")
    return w
