"""Rebuild dashboard.html from live data. Run after every refresh."""
import json
from datetime import datetime, timezone
from pathlib import Path
from ffagent import myboard as M, decisions
L = M.LEAGUE

# Build the board FRESH every run.
#
# This used to read a pre-baked data/dashboard.json that I generated once by
# hand. Every rebuild since then re-rendered that stale snapshot: 88 players
# from when the ADP file had 59 rows, two defences, no kickers at all. The
# dashboard looked like it was updating and was not. Any file that is written
# once and read forever will do this eventually — so there is no snapshot now,
# the board is composed here from the same functions everything else uses.
import csv as _csv
from ffagent import simulate as _sim

_rank = M.annotate(M.build())
_meta = {r["name"]: r for r in _csv.DictReader(open(Path("data") / "sleeper_meta.csv"))}
_picks = [x.overall for x in _sim.pick_numbers(M.MY_SLOT, L.teams, 15)]
_adp = _sim.load_adp()
_draws = _sim.simulate(_adp, n=20000)
_surv = {str(pk): {r[0]: round(r[3], 3) for r in _sim.survival(_adp, _draws, pk)}
         for pk in _picks[:8]}

board = []
for _i, _x in enumerate(_rank, 1):
    _m = _meta.get(_x.name, {})
    board.append(dict(
        rank=_i, name=_x.name, pos=_x.pos, team=_x.team, adp=_x.adp, proj=_x.proj,
        own=_x.own_proj, espn=_x.espn_proj, avail=_x.avail, vor=_x.vor, tier=_x.tier,
        bye=_x.bye, note=_x.note, disagree=_x.disagreement, status=_x.espn_status,
        sid=_m.get("sleeper_id", ""), num=_m.get("number", ""), age=_m.get("age", ""),
        exp=_m.get("exp", ""), ht=_m.get("height", ""), wt=_m.get("weight", ""),
        col=_m.get("college", "")))
picks, surv = _picks, _surv
L = M.LEAGUE

def why(r):
    """Plain-English reasoning for a ranking, from the numbers that drove it."""
    bits = []
    bits.append(f"Ensemble projection {r['proj']:.1f} pts/gm — my 2025-based model says "
                f"{r['own']:.1f}, ESPN's 2026 projection says {r['espn']:.1f}.")
    if r["disagree"] >= 2:
        bits.append(f"Sources disagree by {r['disagree']:.1f} pts/gm. Wide disagreement "
                    f"means the projection is doing less work than the number suggests.")
    if r["avail"] < 0.86:
        bits.append(f"Durability {r['avail']:.0%}, measured from games actually played "
                    f"2022–25 rather than injury reports. With zero IR slots this league, "
                    f"an unavailable player costs one of only five bench spots.")
    elif r["avail"] >= 0.92:
        bits.append(f"Durability {r['avail']:.0%} — clean availability record.")
    if r["pos"] in ("RB", "WR", "TE"):
        bits.append(f"Worth {r['vor']:+.1f} over replacement. Both flex slots accept RB, "
                    f"WR and TE, so those three compete for the same 70 starting spots "
                    f"league-wide and are measured against one shared bar — scoring them "
                    f"separately made replacement-level tight ends look scarce and inflated "
                    f"every TE on the board.")
    elif r["pos"] == "QB":
        bits.append(f"Worth {r['vor']:+.1f} over QB{L.replacement_rank('QB')}. One QB slot "
                    f"in ten teams, and the drop-off is flat, so waiting costs little.")
    else:
        bits.append("Kickers and defenses are not ranked by value — the spread between the "
                    "best and the tenth-best is smaller than week-to-week noise. They are "
                    "taken in the last two rounds, and only then.")
    bits.append(f"Tier {r['tier']} at {r['pos']}. Inside a tier, take the cheaper player; "
                f"across a tier break is the only time reaching is right.")
    if r["note"]:
        bits.append(r["note"][0].upper() + r["note"][1:] + " versus market ADP.")
    if r["status"] == "QUESTIONABLE":
        bits.append("ESPN currently lists him questionable.")
    return bits

from ffagent import rankings as _rk
rk = _rk.run(M.build())
mv = {r.name: r.movement for r in rk}
rkmap = {r.name: r for r in rk}
movers = [{"name": r.name, "pos": r.pos, "from": r.prev_rank, "to": r.rank,
           "d": r.movement, "why": r.explain()[:2]} for r in _rk.biggest_moves(rk, 8)]

logs = json.loads((Path("data")/"gamelogs.json").read_text()) if (Path("data")/"gamelogs.json").exists() else {}
career = json.loads((Path("data")/"career.json").read_text()) if (Path("data")/"career.json").exists() else {}
rows_json = json.dumps([{**r, "why": why(r), "logs": logs.get(r["name"], []),
                          "career": career.get(r["name"], []),
                          "mv": mv.get(r["name"]),
                          "ev": [e.as_dict() for e in rkmap[r["name"]].evidence]
                                if r["name"] in rkmap else []}
                         for r in board])
plan = M.draft_plan(M.build())
check = M.plan_check(plan)
pend = decisions.pending()

html = Path("dash_template.html").read_text()
html = html.replace("__DATA__", rows_json)
html = html.replace("__PICKS__", json.dumps(picks))
html = html.replace("__PLAN__", json.dumps(plan))
html = html.replace("__CHECK__", json.dumps(check))

from ffagent import news as _news, feed as _feed, matchups as _mu
arts, items = _news.ingest()
try:
    _mtbl = _mu.allowed_by_position(2025)
except Exception:
    _mtbl = {}
_feeditems = _feed.build(news_items=items, matchup_table=_mtbl,
                         my_players=set(), my_teams=set(), opponents=set())
html = html.replace("__NEWS__", json.dumps(_feeditems))
_unused_arts = arts
blockers = {i.player.lower(): i for i in items if i.blocks}
from ffagent import feed as _feed, matchups as _mu2
try:
    _mtbl = _mu2.allowed_by_position(2025)
except Exception:
    _mtbl = {}
categorised = _feed.build(news_items=items, matchup_table=_mtbl,
                          my_players=set(), my_teams=set(), opponents=set())


# The categorised feed IS the news feed. There is no second raw-article list —
# an article with no category and no takeaway was going into the same panel and
# competing with the items that had both.
feed = categorised

html = html.replace("__MOVERS__", json.dumps(movers))
from ffagent import takeaways as _tk
html = html.replace("__TAKE__", json.dumps(_tk.build(week=1, today="2026-08-31")))
html = html.replace("__UPDATED__", datetime.now(timezone.utc).strftime("%d %b %H:%M UTC"))

roster, posstr = [], {}
need = {"QB":1,"RB":2,"WR":2,"TE":1,"K":1,"DEF":1}
for p, n in need.items():
    have = sum(1 for r in roster if r["pos"] == p)
    posstr[p] = {"have": have, "need": n, "pct": 100*have/max(1,n),
                 "note": "fills after the draft" if not roster else ""}
html = html.replace("__ROSTER__", json.dumps(roster))
html = html.replace("__POSSTR__", json.dumps(posstr))
html = html.replace("__LEAGUE__", json.dumps({
    "matchups": [],
    "managers": [{"slot": s, "name": n} for s, n in [
        (1,"jaybeezy2ezy"),(2,"TestTickles"),(3,"zay4209"),(4,"Aidious"),
        (5,"Scorpiondemon90"),(6,"Ysa084"),(7,"BmoreKidd"),(8,"BobbiWasabi"),
        (9,"SantaSleeper"),(10,"ClearnceClaymor")]]}))
html = html.replace("__SURV__", json.dumps(surv))
# Sample decisions until rosters exist. Replaced by the live orchestrator
# output once the draft is done.
from ffagent import decide as _dec, matchups as _mu
try:
    _tbl = _mu.allowed_by_position(2025)
except Exception:
    _tbl = {}
_samples = [
    _dec.build_start_sit("Rome Odunze", "Jameson Williams", 3.4, _tbl.get(("DAL", "WR"))),
    _dec.build_waiver("MarShawn Lloyd", "Jadarian Price", 2.1, 2.4, False, False),
    _dec.build_waiver("MarShawn Lloyd", "Bhayshul Tuten", 2.1, 2.4, True, True),
    _dec.build_trade("Jaylen Waddle", "Derrick Henry", "Ysa084", 4.2, 4.0),
]
html = html.replace("__PENDING__", json.dumps([d.as_dict() for d in _samples]))
Path("dashboard.html").write_text(html)
print("wrote dashboard.html")
