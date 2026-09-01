"""Offline end-to-end. Fixture Sleeper, real nflverse. Runs with no network to Sleeper."""
from ffagent import state, orchestrator, decisions, usage
from ffagent.config import LeagueConfig

def fixture():
    xw = usage.load_crosswalk().dropna(subset=["gsis_id"]).drop_duplicates("gsis_id")
    # use players with real 2025 usage so projections are non-zero
    sig = usage.build(2026)
    live = set(sig.frame[sig.frame.ppr_recent > 3].gsis_id)
    xw = xw[xw.position.isin(["QB","RB","WR","TE"]) & xw.gsis_id.isin(live)].head(400)
    players = {}
    for i,(_,r) in enumerate(xw.iterrows()):
        players[str(1000+i)] = {"full_name": r.display_name, "position": r.position,
                                "team": r.latest_team, "gsis_id": r.gsis_id,
                                "injury_status": "Out" if i in (3,7) else ""}
    ids=list(players)
    return players, ids[0:15], ids[15:30]

players, my_ids, opp_ids = fixture()
fetch = {
 "nfl_state": lambda: {"season":2026,"week":5},
 "users": lambda lid: [{"user_id":"me","display_name":"Goon Squad"},
                       {"user_id":"nick","display_name":"Nick"}],
 # Sleeper returns starters positionally against roster_positions
 "rosters": lambda lid: [{"owner_id":"me","roster_id":1,"players":my_ids,
                          "starters":my_ids[:9]},
                         {"owner_id":"nick","roster_id":2,"players":opp_ids,
                          "starters":opp_ids[:9]}],
 "players": lambda: players,
 "config": lambda lid: LeagueConfig(lid,"Test League","2026",10,[],{"rec":1.0},2,100,4,15,6,2,
              starters=["QB","RB","RB","WR","WR","TE","WRRB_FLEX","K","DEF"]),
}

w = state.build("TEST","me",fetch=fetch)
print(w.cfg.summary())
print(f"\nweek {w.week} | roster {len(w.my_roster)} | wire {len(w.free_agents)} | conf {w.signal_confidence:.2f}")
for n in w.notes: print("  !",n)
print("\nSTARTING LINEUP")
for s,p in (w.lineup.assignment.items() if w.lineup else []):
    print(f"   {s:<11}{p.name:<26}{p.proj:>6}{'  '+p.status if p.status else ''}")
print("   unfilled:", w.lineup.unfilled if w.lineup else None)
print("   total   :", w.lineup.total if w.lineup else 0)

for job in ["inactive_sweep","queue_claims","trade_scan","injury_scan"]:
    ds = orchestrator.run_window(w, job)
    print(f"\n[{job}] -> {len(ds)} decision(s)")
    for d in ds[:2]:
        print(f"   ({d.confidence:.2f}) {d.action}")
        print(f"       {d.thesis[:110]}")
print("\nnotes:")
for n in w.notes: print("  !",n)
print("pending in log:", len(decisions.pending()))
