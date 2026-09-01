"""My board for Public Randoms 2026. Not a copy of anyone's rankings.

Built for this league's actual shape, which is unusual enough that generic
rankings mislead:

    10 teams | QB RB RB WR WR TE FLEX FLEX K DEF | 5 bench | ZERO IR
    rolling waiver priority | 6 of 10 make playoffs from week 15

Three consequences that drive everything below.

**Two flex slots, both TE-eligible.** Seventy skill starting spots across the
league. Replacement runs to RB28 / WR28 / TE18 / QB11. That TE18 is the number
generic rankings get most wrong for this league: with a TE-eligible flex in a
shallow league, the eighteenth tight end starts somewhere, so the surplus of an
elite TE over replacement is small. Elite tight ends are worth *less* here, not
more.

**Two IR slots** (changed from zero on 2026-08-31). An injured player can be
parked without eating one of the five bench spots, which partially restores the
injured-stash play -- but only twice, and only for players Sleeper marks
IR-eligible. Durability still discounts value; it just no longer has to be
priced as "this man will occupy a bench seat while contributing nothing".

**Six of ten make the playoffs.** A soft field. Getting in is likely; winning
it is the job. That argues for ceiling over floor -- you need to be dangerous
in week 15, not merely alive.

Projection method, stated plainly because it is the weakest link: 2025 PPG,
shrunk toward positional mean by games played, blended with the market's own
view via ADP. Backward-looking by construction. It will be wrong about second-
year leaps and situation changes, and the ADP blend is what stops it being
catastrophically wrong about rookies it has never seen.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import news, simulate
from .config import LeagueConfig

DATA = Path(__file__).resolve().parent.parent / "data"

LEAGUE = LeagueConfig(
    league_id="1400160155982639104", name="Public Randoms 2026", season="2026",
    teams=10,
    roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX",
                      "K", "DEF", "BN", "BN", "BN", "BN", "BN"],
    scoring={"rec": 1, "rec_yd": 0.1, "rec_td": 6, "rush_yd": 0.1, "rush_td": 6,
             "pass_yd": 0.04, "pass_td": 4, "pass_int": -1, "fum_lost": -2},
    waiver_type=1, waiver_budget=100, playoff_teams=6, playoff_start_week=15,
    bench_slots=5, ir_slots=2,
    starters=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"],
)

MY_SLOT = 9

# A 15-round draft must end with a legal starting lineup. Every position has a
# round by which it MUST be taken, derived from where the position dries up
# rather than from convention. Missing a K or DEF entirely is a guaranteed zero
# every week -- the single most avoidable way to lose a league.
MUST_FILL_BY = {
    "QB": 12,   # QB11 replacement; the drop-off is flat, so wait, but not past 12
    "RB": 8,    # need 2 + flex bodies; RB28 replacement dries up around then
    "WR": 8,
    "TE": 13,   # TE18 replacement -- the shallowest need on the board
    "K": 15,
    "DEF": 14,
}
MIN_COUNTS = {"QB": 1, "RB": 4, "WR": 5, "TE": 1, "K": 1, "DEF": 1}

# Earliest round a position may be taken. Only K and DEF need one, and the
# reason is specific: giving them real projections put value-over-replacement
# on the same scale as skill players, and the planner promptly took the Rams
# defence at pick 49 against an ADP of 114. The projection was right — they are
# the best unit on the board — but the pick was wrong, because they will still
# be there sixty picks later. Scarcity, not quality, is what makes an early
# pick correct, and there is no scarcity at either position.
EARLIEST_ROUND = {"DEF": 11, "K": 13}
MAX_COUNTS = {"QB": 2, "RB": 6, "WR": 7, "TE": 2, "K": 1, "DEF": 1}

# Dedicated starting slots, before flex.
STARTING = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}
FLEX_SLOTS = 2


def marginal(pos: str, already: int) -> float:
    """What a player is actually worth to a roster that already holds `already`
    at his position.

    Value over replacement is an absolute measure and greedy drafting on it
    produced a roster with three tight ends -- each genuinely the best player
    available, and the second and third worth almost nothing because you start
    one. The fix is not a positional cap bolted on afterwards; it is that the
    value of the Nth player at a position depends on N.
    """
    need = STARTING.get(pos, 1)
    if already < need:
        return 1.0                      # fills a starting slot
    if pos in ("K", "DEF", "QB"):
        return 0.05                     # a second is nearly worthless
    if already < need + FLEX_SLOTS:
        return 0.62                     # competes for a flex spot
    if already < need + FLEX_SLOTS + 2:
        return 0.28                     # real bench depth, plays on byes
    return 0.08                          # roster clutter


def draft_plan(board: list["Ranked"], slot: int = MY_SLOT, rounds: int = 15) -> list[dict]:
    """A pick-by-pick plan that is guaranteed to field a legal lineup.

    Greedy on value, but with a hard constraint: at each pick, if the number of
    rounds remaining equals the number of positions still unfilled, the pick is
    forced. That is what stops a draft ending with no kicker because every round
    had a more exciting option -- which it always does.
    """
    from . import simulate
    picks = [p.overall for p in simulate.pick_numbers(slot, LEAGUE.teams, rounds)]
    # Availability has to come from the survival simulation, not from a crude
    # ADP margin. Filtering on `adp > pick - 8` let the planner "take" Jaxon
    # Smith-Njigba at pick 12 when he goes 5.5 on average and is gone from that
    # slot in roughly four drafts out of five. That produced a plan that looked
    # optimal and was unexecutable.
    adp_rows = simulate.load_adp()
    draws = simulate.simulate(adp_rows, n=12000)
    surv = {pk: {r[0]: r[3] for r in simulate.survival(adp_rows, draws, pk)}
            for pk in picks}
    pool = sorted(board, key=lambda x: -x.vor)
    taken: list[Ranked] = []
    counts: dict[str, int] = {}
    plan = []

    for rd, overall in enumerate(picks, 1):
        left = rounds - rd + 1
        # positions still short of the minimum
        short = {p: n - counts.get(p, 0) for p, n in MIN_COUNTS.items()
                 if counts.get(p, 0) < n}
        urgent = [p for p in short if MUST_FILL_BY.get(p, 99) <= rd]
        forced = sum(short.values()) >= left

        # anyone whose ADP is already well past this pick is gone
        sv = surv.get(overall, {})
        avail = [x for x in pool
                 if sv.get(x.name, 0.0) >= 0.30
                 and counts.get(x.pos, 0) < MAX_COUNTS.get(x.pos, 99)
                 and rd >= EARLIEST_ROUND.get(x.pos, 0)]
        if urgent:
            avail = [x for x in avail if x.pos in urgent] or avail
        elif forced:
            avail = [x for x in avail if x.pos in short] or avail

        if not avail:
            plan.append({"round": rd, "pick": overall, "take": None,
                         "reason": "board exhausted at this depth"})
            continue
        # Rank by what taking him NOW is worth over waiting.
        #
        # Value alone made the planner reach for Trey McBride at pick 9 — the
        # highest-VOR player available, and available again at 29 with 73%
        # probability. A pick spent on someone who was coming back anyway is a
        # pick wasted, however good he is.
        #
        # So each candidate is scored by his value multiplied by the chance he
        # is GONE by my next turn. Scarcity and value have to be multiplied,
        # not chosen between.
        nxt = picks[rd] if rd < len(picks) else None
        sv_next = surv.get(nxt, {}) if nxt else {}

        def score(x):
            base = x.vor * marginal(x.pos, counts.get(x.pos, 0))
            gone = 1.0 - sv_next.get(x.name, 0.0) if nxt else 1.0
            # floor so a certain-to-survive elite player is not scored at zero
            return base * (0.30 + 0.70 * gone)

        avail.sort(key=lambda x: -score(x))
        pick = avail[0]
        pick_surv = sv.get(pick.name, 0.0)
        pool.remove(pick)
        taken.append(pick)
        counts[pick.pos] = counts.get(pick.pos, 0) + 1

        if urgent:
            why = f"forced: {'/'.join(urgent)} must be filled by round {MUST_FILL_BY[urgent[0]]}"
        elif forced:
            why = f"forced: {left} rounds left, {sum(short.values())} slots unfilled"
        else:
            m = marginal(pick.pos, counts.get(pick.pos, 0) )
            why = (f"best available, {pick.vor:+.1f} over replacement"
                   + ("" if m >= 0.99 else f" (×{m:.2f} — {counts.get(pick.pos,0)} already at {pick.pos})"))
        plan.append({"round": rd, "pick": overall, "take": pick.name, "pos": pick.pos,
                     "adp": pick.adp, "vor": pick.vor, "tier": pick.tier, "reason": why,
                     "surv": round(pick_surv, 2), "roster": dict(counts)})
    return plan


def plan_check(plan: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in plan:
        if row.get("pos"):
            counts[row["pos"]] = counts.get(row["pos"], 0) + 1
    ok = all(counts.get(p, 0) >= n for p, n in MIN_COUNTS.items())
    return {"counts": counts, "legal": ok,
            "missing": {p: n - counts.get(p, 0) for p, n in MIN_COUNTS.items()
                        if counts.get(p, 0) < n}}


@dataclass
class Ranked:
    name: str
    pos: str
    team: str
    adp: float
    proj: float
    avail: float
    value: float
    vor: float = 0.0
    tier: int = 0
    note: str = ""
    own_proj: float = 0.0
    espn_proj: float = 0.0
    bye: int = 0
    espn_status: str = ""
    def_unit: object = None
    unit: object = None
    playoff_proj: float = 0.0
    playoff_notes: list = field(default_factory=list)
    playoff_sched: str = ""

    @property
    def disagreement(self) -> float:
        """How far the sources are apart, per game.

        Worth surfacing rather than averaging away. A player both sources like
        is a safer pick than one with the same mean where they disagree by four
        points a game -- and the disagreements are where the value usually is.
        """
        if not self.espn_proj:
            return 0.0
        return round(abs(self.own_proj - self.espn_proj), 2)

    def line(self) -> str:
        n = f"  {self.note}" if self.note else ""
        return (f"{self.name:<24}{self.pos:<4}{self.team:<5}"
                f"adp {self.adp:>5.1f}  proj {self.proj:>5.1f}  "
                f"avail {self.avail:>4.0%}  VOR {self.vor:>+6.2f}  T{self.tier}{n}")


def _production() -> dict[str, dict]:
    out = {}
    with open(DATA / "prod2025.csv") as fh:
        for r in csv.DictReader(fh):
            out[r["player_display_name"]] = {
                "ppg": float(r["ppg"]), "gm": int(r["gm"]), "pos": r["position"]}
    return out


def _espn() -> dict[str, dict]:
    """ESPN's own 2026 projections and PPR draft ranks.

    The most valuable addition to the board: genuinely forward-looking, where
    my 2025-production blend is backward-looking by construction. It also
    carries bye weeks and an injury status, both of which nflverse cannot give
    me before the season starts.
    """
    out = {}
    fp = DATA / "espn2026.csv"
    if not fp.exists():
        return out
    with open(fp) as fh:
        for r in csv.DictReader(fh):
            out[r["name"]] = {
                "rank": int(r["espn_rank"]), "proj": float(r["espn_proj"]),
                "bye": int(r["bye"]) if r["bye"] else 0, "status": r["status"]}
    return out


def _adp_implied(adp: float, pos: str) -> float:
    """Market's implied PPG from draft cost.

    A decay curve fitted by eye to where positions actually land -- steep at
    the top, flattening by the fourth round. Crude, and its job is only to stop
    the projection being nonsense for players with no 2025 sample.
    """
    base = {"RB": 21.0, "WR": 20.0, "TE": 14.0, "QB": 22.0}.get(pos, 8.0)
    return round(base * (adp ** -0.19), 2)


def build(apply_news: bool = True, in_season: dict | None = None,
          playoff_weighted: bool = True) -> list[Ranked]:
    """`in_season` maps name -> (ppg, games) from games actually played.

    Passing it re-tiers the whole board: projections blend toward live results
    as games accumulate (see rankings.BLEND_K), and tier breaks are recomputed
    from the new spread. So tiers are not a preseason artefact — a position
    that consolidates or fragments during the season shows it here.
    """
    rows = simulate.load_adp(apply_news=apply_news)
    prod = _production()
    dur = {}
    try:
        from .draft import durability
        dur = {v.name: v for v in durability().values()}
    except Exception:
        pass

    espn = _espn()
    ranked: list[Ranked] = []
    for r in rows:
        p = prod.get(r["name"])
        implied = _adp_implied(r["adp"], r["pos"])
        if p:
            # Shrink a short sample toward the market view rather than trusting
            # six games as though they were seventeen.
            w = min(1.0, p["gm"] / 14.0)
            mine = w * p["ppg"] + (1 - w) * implied
        else:
            mine = implied

        # Ensemble. Three views that fail in different directions: my own
        # backward-looking 2025 blend, ESPN's forward-looking projection, and
        # the market's implied value from ADP. Averaging correlated-but-not-
        # identical estimates beats any one of them, and the disagreement
        # between them is itself information -- see `disagreement`.
        e = espn.get(r["name"])
        parts, wts = [mine], [0.35]
        if e:
            parts.append(e["proj"] / 17.0)   # season total -> per game
            wts.append(0.45)                  # heaviest: it is the only 2026 view
        parts.append(implied)
        wts.append(0.20)
        proj = sum(v * w for v, w in zip(parts, wts)) / sum(wts)
        d = dur.get(r["name"])
        avail = d.availability if d else 0.90
        # Blend in live results once they exist.
        if in_season:
            ppg, games = in_season.get(r["name"], (None, 0))
            if ppg is not None and games:
                from .rankings import blend
                proj, _w = blend(proj, ppg, games)

        rk = Ranked(r["name"], r["pos"], r["team"], r["adp"],
                    round(proj, 2), avail, round(proj * avail, 2))
        if e:
            rk.espn_proj = round(e["proj"] / 17.0, 2)
            rk.bye = e["bye"]
            rk.espn_status = e["status"]
        rk.own_proj = round(mine, 2)
        ranked.append(rk)

    # Re-weight toward weeks 15-17 before any value maths runs.
    #
    # The objective is not points, it is winning the playoffs: six of ten
    # qualify, so getting in is likely and the three weeks that decide the
    # title are worth roughly 1.5x a regular one each. Two things move most:
    # a player's playoff schedule, and his availability -- a 76% availability
    # is a coin flip on missing one of three games you cannot replace him for.
    if playoff_weighted:
        try:
            from . import matchups as _mu, objective as _obj
            _tbl = _mu.allowed_by_position(2025)
            for x in ranked:
                if x.pos not in ("RB", "WR", "TE", "QB"):
                    continue
                prof = _obj.profile(x.team, x.pos, _tbl)
                adj, notes = _obj.playoff_adjust(x.proj, prof, x.bye, x.avail)
                x.playoff_proj = adj
                x.playoff_notes = notes
                x.playoff_sched = prof.describe()
                x.proj = adj
                x.value = round(adj, 2)
        except Exception:
            pass

    # Every defence and every kicker belongs on the board, not just the handful
    # the market bothers to draft. Nine defences had an ADP; there are 32. Three
    # kickers had one; there are far more. A unit with no ADP is not unrankable,
    # it is unpriced — and unpriced is where the value is, which is the whole
    # argument the rest of this project rests on.
    from . import defense, units
    try:
        _u = units.rank(2025)
        _have_def = {units.canon((x.team or "").upper()) for x in ranked if x.pos == "DEF"}
        _have_k = {x.name for x in ranked if x.pos == "K"}
        # ADP for an undrafted unit: past the last pick, so survival maths treats
        # it as freely available rather than as a mispriced bargain.
        UNDRAFTED_ADP = 165.0
        for u in _u["DEF"]:
            if u.team not in _have_def:
                ranked.append(Ranked(f"{u.team} Defense", "DEF", u.team, UNDRAFTED_ADP,
                                     u.adj_ppg, 1.0, u.adj_ppg))
        for u in _u["K"]:
            if u.team and u.team not in {x.team for x in ranked if x.pos == "K"}:
                ranked.append(Ranked(u.name or u.team, "K", u.team,
                                     UNDRAFTED_ADP, u.adj_ppg, 1.0, u.adj_ppg))
    except Exception:
        pass

    # Units added above bypassed the in-season blend, because that runs inside
    # the ADP loop. A defence or kicker whose season diverges from last year
    # would have stayed frozen at its preseason number all year.
    if in_season:
        from .rankings import blend
        for x in ranked:
            if x.pos in ("K", "DEF"):
                ppg, games = in_season.get(x.name, (None, 0))
                if ppg is not None and games:
                    x.proj, _ = blend(x.proj, ppg, games)
                    x.proj = round(x.proj, 2)
                    x.value = x.proj

    defense.apply(ranked, skip=set(in_season or {}))
    try:
        u = units.rank(2025)
        dmap = {x.team: x for x in u["DEF"]}
        kmap = {x.team: x for x in u["K"]}
        for x in ranked:
            # Attach the unit for its reasoning, but do NOT overwrite a
            # projection that has already been blended with live results.
            if x.pos == "DEF":
                hit = dmap.get(units.canon((x.team or "").upper()))
                if hit:
                    x.unit = hit
                    if not (in_season and x.name in in_season):
                        x.proj = hit.adj_ppg
                        x.value = hit.adj_ppg
            elif x.pos == "K":
                hit = kmap.get(units.canon((x.team or "").upper()))
                if hit:
                    x.unit = hit
                    if not (in_season and x.name in in_season):
                        x.proj = hit.adj_ppg
                        x.value = hit.adj_ppg
    except Exception:
        pass

    # VOR, with ONE baseline shared across every flex-eligible position.
    #
    # Per-position replacement is wrong when a flex accepts RB, WR and TE. The
    # flex is filled by whoever is best among the three, so they compete for
    # the same slots and must be measured against the same bar. Scoring them
    # separately gave tight ends a baseline of "TE18" -- a replacement-level TE
    # is genuinely dreadful, so every startable TE looked enormous, and the
    # planner wanted three of them. Measured against the pooled bar instead,
    # tight ends look like what they are here: fine, and not scarce.
    #
    # Pooled starting slots: 2 RB + 2 WR + 1 TE + 2 FLEX, times 10 teams = 70.
    flex_pos = {"RB", "WR", "TE"}
    pooled = sorted([x for x in ranked if x.pos in flex_pos],
                    key=lambda x: -x.value)
    n_slots = sum(LEAGUE.starting_slots(p) for p in ("RB", "WR", "TE")) * LEAGUE.teams
    n_slots += 2 * LEAGUE.teams          # the two FLEX slots
    idx = min(n_slots, len(pooled) - 1)
    flex_baseline = pooled[idx].value if pooled else 0.0

    for pos in {x.pos for x in ranked}:
        grp = sorted([x for x in ranked if x.pos == pos], key=lambda x: -x.value)
        if not grp:
            continue
        if pos in flex_pos:
            baseline = flex_baseline
        elif pos == "QB":
            r = LEAGUE.replacement_rank("QB")
            baseline = grp[min(r, len(grp)) - 1].value
        else:
            # K and DEF now have real projections from `units` — 2025 scored
            # under this league's own rules, adjusted for verified personnel.
            # They are ranked against their own replacement level (the 10th of
            # each, since ten teams start one apiece) rather than being zeroed.
            #
            # They stay OUT of the cross-position VOR comparison though. The
            # spread here is ~2 pts/gm against 10+ for a running back, and
            # letting that into the same scale put a kicker in round seven.
            # Ranked among themselves, taken in the last two rounds.
            r = LEAGUE.teams + 1
            baseline = grp[min(r, len(grp)) - 1].value if grp else 0.0
            for x in grp:
                x.vor = round(x.value - baseline, 2)
                x.tier = 1 if x.value >= baseline + 1.0 else 2
            continue
        for x in grp:
            x.vor = round(x.value - baseline, 2)
        gaps = [grp[i].value - grp[i + 1].value for i in range(len(grp) - 1)]
        if gaps:
            cut = float(np.quantile(gaps, 0.80))
            t = 1
            for i, x in enumerate(grp):
                x.tier = t
                if i < len(gaps) and gaps[i] >= cut:
                    t += 1
    return sorted(ranked, key=lambda x: -x.vor)


def annotate(board: list[Ranked]) -> list[Ranked]:
    """Flag where my board disagrees with the market, and why."""
    by_adp = sorted(board, key=lambda x: x.adp)
    for i, x in enumerate(by_adp):
        market = i + 1
        mine = board.index(x) + 1
        gap = market - mine
        bits = []
        if gap <= -12:
            bits.append(f"market {abs(gap)} spots high")
        elif gap >= 12:
            bits.append(f"value: {gap} spots cheap")
        if x.avail < 0.85:
            bits.append(f"durability {x.avail:.0%}")
        x.note = "; ".join(bits)
    return board
