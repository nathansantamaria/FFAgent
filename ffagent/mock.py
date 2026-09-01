"""Run a full mock draft and grade the result honestly.

The opponents matter more than the method here. Nine bots that draft strictly
by ADP would make my agent look brilliant, because its whole edge is
deviating from ADP where the data disagrees. So the bots get three behaviours
that real managers actually have:

  positional need   — they will not take a fifth running back in round 6
  reaching          — a normal-distributed deviation from ADP, so the board
                      does not unfold in the same order every time
  positional runs   — after two of a position go in three picks, the next
                      bot is more likely to follow. Runs are real and they
                      are what breaks static plans.

Grading is against things that cannot be gamed: projected points from the
starting lineup my roster can actually field, and draft capital measured as
ADP minus the pick spent. Both are reported against the other nine teams
drafted under the same rules, because a score with nothing to compare it to
is not a grade.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import live, myboard as M
from .myboard import LEAGUE

STARTERS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
FLEX_OK = {"RB", "WR", "TE"}
BOT_NEED = {"QB": 2, "RB": 5, "WR": 6, "TE": 2, "K": 1, "DEF": 1}


@dataclass
class Team:
    slot: int
    name: str
    roster: list = field(default_factory=list)

    def counts(self) -> dict:
        c = {}
        for p in self.roster:
            c[p.pos] = c.get(p.pos, 0) + 1
        return c

    def lineup(self, key=None) -> tuple[list, float]:
        """Best legal starting lineup and its projected points.

        `key` selects which projection to score with. This matters more than
        anything else in the grading: scoring my roster with the projections I
        drafted from is circular — the bots draft by ADP, I draft by my own
        numbers, and any disagreement between the two shows up as "edge"
        whether or not my numbers are better. The honest grade uses a
        projection I never optimised against.
        """
        key = key or (lambda p: p.proj)
        used, out = set(), []
        pool = sorted(self.roster, key=lambda p: -key(p))
        for slot in STARTERS:
            if slot == "FLEX":
                cand = [p for p in pool if p.pos in FLEX_OK and id(p) not in used]
            else:
                cand = [p for p in pool if p.pos == slot and id(p) not in used]
            if cand:
                used.add(id(cand[0]))
                out.append((slot, cand[0]))
            else:
                out.append((slot, None))
        total = sum(key(p) for _s, p in out if p)
        return out, round(total, 2)


def bot_pick(board, taken: set, team: Team, overall: int, recent: list[str],
             rng: random.Random):
    counts = team.counts()
    rounds_left = 15 - len(team.roster)
    short = {p: n for p, n in {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}.items()
             if counts.get(p, 0) < n}
    run_pos = None
    if len(recent) >= 3:
        tail = recent[-3:]
        for p in set(tail):
            if tail.count(p) >= 2:
                run_pos = p

    best, best_score = None, -1e9
    for x in board:
        if x.name in taken:
            continue
        if counts.get(x.pos, 0) >= BOT_NEED.get(x.pos, 99):
            continue
        # bots do not take K/DEF early
        if x.pos in ("K", "DEF") and len(team.roster) < 11:
            continue
        if sum(short.values()) >= rounds_left and x.pos not in short:
            continue
        noise = rng.gauss(0, 7.0)
        score = -(x.adp + noise - overall)
        if run_pos and x.pos == run_pos:
            score += 6.0
        if x.pos in short:
            score += 4.0
        if score > best_score:
            best, best_score = x, score
    return best


def run(seed: int = 7, my_slot: int = 9, verbose: bool = True,
        force_open: list[str] | None = None) -> dict:
    """`force_open` pins my first N picks to a position sequence, e.g.
    ["RB","RB"], so opening strategies can be compared on identical boards."""
    rng = random.Random(seed)
    board = M.build()
    by = {x.name: x for x in board}
    teams = {s: Team(s, "ME" if s == my_slot else f"bot{s}") for s in range(1, 11)}
    taken: set = set()
    picks: list = []
    recent: list[str] = []

    for rd in range(1, 16):
        order = range(1, 11) if rd % 2 == 1 else range(10, 0, -1)
        for slot in order:
            overall = len(picks) + 1
            t = teams[slot]
            if slot == my_slot:
                st = live.LiveState(slot=my_slot)
                st.picks = [live.Pick(i + 1, p.name, p.pos) for i, p in enumerate(picks)]
                st.my_roster = [live.Pick(0, p.name, p.pos) for p in t.roster]
                rec = live.recommend(st, board, n=3000)
                pick = by.get(rec.get("take"))
                if force_open and len(t.roster) < len(force_open):
                    want = force_open[len(t.roster)]
                    cands = live.evaluate(st, board, n=3000)
                    hit = next((c for c in cands if c.pos == want), None)
                    if hit:
                        pick = by[hit.name]
                if pick is None or pick.name in taken:
                    pick = next(x for x in board if x.name not in taken)
                if verbose:
                    print(f"  R{rd:<3}#{overall:<4} ME   {pick.name:<24}{pick.pos:<4}"
                          f"adp{pick.adp:>6.1f}  {rec.get('reason','')[:52]}")
            else:
                pick = bot_pick(board, taken, t, overall, recent, rng)
                if pick is None:
                    continue
            taken.add(pick.name)
            t.roster.append(pick)
            picks.append(pick)
            recent.append(pick.pos)

    return grade(teams, my_slot, picks)


# Independent scorer: ESPN's own 2026 projection, which my board consumes as
# one input of three but never fits to. Falls back to my number only where
# ESPN has none (undrafted defences and kickers), and those are reported
# separately so the fallback cannot quietly carry the result.
def espn_key(p):
    return p.espn_proj if getattr(p, "espn_proj", 0) else p.proj


def grade(teams: dict, my_slot: int, picks: list) -> dict:
    pick_of = {p.name: i + 1 for i, p in enumerate(picks)}
    rows = []
    for s, t in teams.items():
        _lineup, pts = t.lineup()
        _el, epts = t.lineup(key=espn_key)
        covered = sum(1 for _sl, pl in _el if pl and getattr(pl, "espn_proj", 0))
        # Draft capital: ADP minus pick spent, summed. Positive means the roster
        # was assembled below market cost. Undrafted-tier units (nominal ADP 165)
        # are excluded — "value" against a made-up ADP is not value.
        cap = sum(p.adp - pick_of[p.name] for p in t.roster if p.adp < 160)
        rows.append({"slot": s, "name": t.name, "points": pts,
                     "espn_points": epts, "espn_covered": covered,
                     "capital": round(cap, 1), "counts": t.counts(),
                     "lineup": [(sl, pl.name if pl else None) for sl, pl in _lineup]})
    rows.sort(key=lambda r: -r["points"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    me = next(r for r in rows if r["slot"] == my_slot)
    avg = sum(r["points"] for r in rows) / len(rows)
    cap_rank = sorted(rows, key=lambda r: -r["capital"]).index(me) + 1

    e_sorted = sorted(rows, key=lambda r: -r["espn_points"])
    e_rank = e_sorted.index(me) + 1
    e_avg = sum(r["espn_points"] for r in rows) / len(rows)
    return {"rows": rows, "me": me, "league_avg": round(avg, 2),
            "points_rank": me["rank"], "capital_rank": cap_rank,
            "edge_vs_avg": round(me["points"] - avg, 2),
            "espn_rank": e_rank, "espn_avg": round(e_avg, 2),
            "espn_edge": round(me["espn_points"] - e_avg, 2)}
