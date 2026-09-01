"""Entry point. Shadow mode by default: proposes, records, renders. Never writes.

  python run.py --league-id X --user-id Y                 # whatever window is due
  python run.py --league-id X --user-id Y --window inactives
  python run.py --agenda                                  # what fires next
  python run.py --crontab                                 # install lines
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ffagent import decisions, orchestrator, schedule, state


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id")
    ap.add_argument("--user-id", help="your Sleeper user_id")
    ap.add_argument("--window", help="force a window instead of using the clock")
    ap.add_argument("--agenda", action="store_true")
    ap.add_argument("--crontab", action="store_true")
    ap.add_argument("--live", action="store_true", help="disable shadow mode (not wired yet)")
    a = ap.parse_args()

    if a.agenda:
        print(schedule.agenda()); return
    if a.crontab:
        print(schedule.crontab()); return
    if not a.league_id:
        ap.error("--league-id required")

    if a.window:
        windows = [w for w in schedule.WINDOWS if w.key == a.window]
        if not windows:
            ap.error(f"unknown window; try: {', '.join(w.key for w in schedule.WINDOWS)}")
    else:
        windows = schedule.due()
        if not windows:
            print("No window is due. Next up:\n" + schedule.agenda()); return

    w = state.build(a.league_id, a.user_id)
    print(w.cfg.summary())
    print(f"\nWeek {w.week} · {len(w.my_roster)} on roster · "
          f"{len(w.free_agents)} wire candidates · confidence {w.signal_confidence:.2f}")
    for n in w.notes:
        print(f"  ! {n}")

    made = []
    for win in windows:
        print(f"\n[{win.key}] {win.why}")
        ds = orchestrator.run_window(w, win.job)
        made += ds
        for d in ds:
            print(f"  ({d.confidence:.2f}) {d.action} — {d.thesis[:100]}")
        if not ds:
            print("  nothing to do")

    for n in w.notes[len(w.notes):]:
        print(f"  ! {n}")

    # build_dash.py is the dashboard generator. ffagent/dashboard.py was the
    # original and is superseded -- leaving this call here meant a scheduled
    # run would quietly overwrite the working dashboard with the obsolete one,
    # which is the kind of failure nobody notices until they open it.
    import subprocess
    subprocess.run(["python3", "build_dash.py"], check=False,
                   cwd=str(Path(__file__).resolve().parent))
    path = Path(__file__).resolve().parent / "dashboard.html"
    print(f"\n{len(made)} decisions recorded · {len(decisions.pending())} pending")
    print(f"dashboard: {path}")
    if a.live:
        print("--live is not wired: capture selectors first "
              "(python -m ffagent.write --league-id X --probe --live)")


if __name__ == "__main__":
    main()
