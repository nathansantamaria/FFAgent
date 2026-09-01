"""On-the-clock assistant. Run during the draft.

  python draft_live.py --draft-id 1400160157035446272        # live from Sleeper
  python draft_live.py --picks "Gibbs,Bijan,..."             # manual, for testing

Prints one recommendation plus what it is passing on and why.
"""
from __future__ import annotations
import argparse
from ffagent import myboard as M, live as L


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft-id")
    ap.add_argument("--picks", help="comma-separated names already taken")
    ap.add_argument("--mine", help="comma-separated names I already hold")
    ap.add_argument("--slot", type=int, default=M.MY_SLOT)
    a = ap.parse_args()

    board = M.build()
    by = {x.name: x for x in board}

    if a.draft_id:
        st = L.from_sleeper(a.draft_id, board, a.slot)
    else:
        names = [n.strip() for n in (a.picks or "").split(",") if n.strip()]
        mine = {n.strip() for n in (a.mine or "").split(",") if n.strip()}
        st = L.LiveState(slot=a.slot)
        for i, n in enumerate(names, 1):
            p = L.Pick(i, n, by[n].pos if n in by else "?")
            st.picks.append(p)
            if n in mine:
                st.my_roster.append(p)

    r = L.recommend(st, board)
    print(f"\nPick #{r['overall']} · round {r['round']} · slot {st.slot}")
    print(f"roster {st.counts()} · unfilled {r['unfilled']} · {r['rounds_left']} rounds left")
    if r["drift"]:
        print("room drift (positive = going earlier than ADP): " +
              ", ".join(f"{k} {v:+.1f}" for k, v in sorted(r["drift"].items())))
    print(f"\n  TAKE  {r['take']}  ({r['pos']})")
    print(f"        {r['reason']}")
    if r["alternatives"]:
        print("\n  next best:")
        for n, p, why in r["alternatives"]:
            print(f"    {n:<24}{p:<5}{why}")
    if r.get("windows"):
        print("\n  positional windows (best available value, my next picks):")
        print(f"    {'pick':<7}{'RB':>7}{'WR':>7}{'TE':>7}   favours")
        for w in r["windows"]:
            print(f"    {w['pick']:<7}{w['RB']:>7.1f}{w['WR']:>7.1f}{w['TE']:>7.1f}   "
                  f"{w['favours']} by {abs(w['edge']):.2f}")
    if r["fallers"]:
        print("\n  falling past ADP:")
        for n, p, fall, verdict, costs, pts in r["fallers"]:
            print(f"    {n:<24}{p:<5}{fall:>4.0f} picks = {pts:>4.1f} pts   {verdict[:46]}")
            if costs:
                print(f"        costs: {costs}")
    print()


if __name__ == "__main__":
    main()
