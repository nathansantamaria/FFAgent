# HANDOFF — read this first, then LOGIC.md

**22 September 2026, week 3. Artificial Domination is 1-1, 276.90 points for.**

This file is the state and the traps. `LOGIC.md` is every decision rule and why.
`STATUS.md` is what works and what does not.

---

## 1. The constraint that wastes the most time

**The sandbox cannot reach api.sleeper.app or ESPN.** Verified repeatedly:

```
403  api.sleeper.app        x-deny-reason: host_not_allowed
403  site.api.espn.com      x-deny-reason: host_not_allowed
200  raw.githubusercontent.com
200  github.com/nflverse
```

Allowlist is GitHub, PyPI, npm. Not changeable from either side.

**Three routes, in order:**

1. **Chrome browser tool** — navigate to any sleeper.com page, then `javascript_tool`
   to `fetch()` the API. Works, but drops out mid-session. A 4-minute timeout means a
   hung MCP server, not a slow request. **Two attempts maximum, then switch.**
2. **GitHub Action** — `.github/workflows/fetch-live-data.yml` fetches on a schedule
   and commits JSON to `data/`. Read with `ffagent/livedata.py`.
   **Status: probably never enabled. Check the Actions tab first thing.**
3. **Screenshots from Nathan** — never once failed.

### Endpoints that work (via browser)

```
/v1/state/nfl                               current week
/v1/league/<id>/users                       team names
/v1/league/<id>/rosters                     rosters, records, points
/v1/league/<id>/matchups/<week>             per-player points, starters
/v1/league/<id>/transactions/<week>         waivers and trades
/v1/players/nfl                             every player: team, position, depth chart, injury
/v1/stats/nfl/regular/2026/<week>           REAL stats: pts_ppr, rec_tgt, rush_att, off_snp, tm_off_snp
/v1/players/nfl/trending/add                what the market is claiming
```

**`/v1/stats/...` is the important one.** Snap share and targets live there. The
matchups endpoint only covers rostered players.

**Sleeper's news feed has NO public endpoint** — `/news/nfl` and `/v1/news/nfl` both
404. Screenshot it.

---

## 2. Identifiers

| | |
|---|---|
| League | Public Randoms 2026, 10-team PPR |
| league_id | `1400160155982639104` |
| My team | **Artificial Domination**, roster_id **1** |
| Sleeper user | SantaSleeper — **he is commissioner** |
| Repo | github.com/nathansantamaria/FFAgent |

```
Starters: QB RB RB WR WR TE FLEX FLEX K DEF   (both flex take RB/WR/TE)
Bench 5, IR 2  |  Playoffs 6 of 10 from week 15  |  Trade deadline week 11
Waivers: REVERSE STANDINGS — priority is NOT consumed by claiming, so claim freely
Scoring: 1.0 PPR, 4pt pass TD, no bonuses
```

---

## 3. Current roster and the outstanding lineup change

```
QB   Jayden Daniels
RB   De'Von Achane, Jacory Croskey-Merritt, Jadarian Price, Tony Pollard
WR   Jaxon Smith-Njigba, George Pickens, Chris Olave, Devaughn Vele,
     Jaylen Waddle, Jordan Addison
TE   Pat Freiermuth, Harold Fannin
K    Brandon Aubrey
DEF  Jacksonville
```

**Jadarian Price is still starting at RB2 and has scored 7.8 and 5.0.**
Croskey-Merritt is depth-chart 1 in Washington. That swap has been recommended twice
and not made. Raise it once, then drop it — it is his call.

---

## 4. What the first two weeks actually taught

| player | wk1 | wk2 | read |
|---|---|---|---|
| Jaxon Smith-Njigba | 26.2 | **42.5** | league-winning, untouchable |
| Chris Olave | 28.2 | 22.6 | role-supported both weeks, NOT a sell |
| **Jaylen Waddle** | **1.2** | **21.8** | **vindicated the hold** |
| George Pickens | 5.8 | 10.0 | still buy-low |
| Harold Fannin | 4.1 | **10.4** | 82% snaps paid off |
| Pat Freiermuth | 15.6 | 7.4 | **the waiver upgrade has not paid** |
| Devaughn Vele | 19.9 | 11.4 | fine, benched, NO fell 56 to 34 attempts |
| Jadarian Price | 7.8 | 5.0 | the hole |

**Two calls I got wrong and one I got right:**

- **RIGHT: holding Waddle.** He scored 1.2 and I refused to sell at his perception
  floor. He put up 21.8 the next week. Small-sample discipline works.
- **WRONG: Freiermuth over Fannin.** I projected +4.31/week. Fannin outscored him
  10.4 to 7.4. Cleveland's attempts rose 22 to 30 while Pittsburgh fell 41 to 40 —
  the team-volume input was noisier week to week than I assumed.
- **WATCH: Vele.** New Orleans threw 56 in week 1 and 34 in week 2. I flagged that
  exact risk when recommending him. The volume adjustment amplifies single-week
  outliers in both directions and needs a two-week average, not one game.

---

## 4b. Live situation as of 22 Sep, week 3

**Jayden Daniels dislocated his arm.** Length unknown, possibly ~5 weeks. Nathan is
keeping him for now — two IR slots are empty, so check whether Sleeper has marked him
IR-eligible; if so he costs nothing to hold.

**Waiver position is roughly 7 of 10**, not 1. Reverse standings recalculates weekly and
winning week 2 pushed him down. The Action now records the real number — read
`data/rosters.json` for `my_waiver_position` rather than inferring it.

**Pending claim chain** (his technique — several claims, same drop, first that clears
consumes it):

```
chain A, drop Jordan Addison:     Bryce Young QB CAR, Tyler Shough QB NO, Drew Lock QB SEA
chain B, drop Pat Freiermuth:     Jonah Coleman RB DEN, Emanuel Wilson RB SEA
```

I argued Shough first on volume (NO 45 att/gm vs CAR 36) plus the Olave/Vele stack.
Nathan rates Young's rushing. Unresolved, and the rushing point is a real gap in the
model — see LOGIC.md.

**Denzel Boston (WR, CLE)** — I read him as role-without-volume off week 1 alone.
Nathan says he is the new Cleveland WR1 and has produced two straight weeks. My read
was stale; verify week 2 before repeating it.

## 5. How Nathan thinks — corrections, each fixed a real bug

1. **Perceived value, not projections, decides trades.** A manager values what he has
   SEEN. `perception.py` models this — recent performance at 60% weight in week 2,
   decaying to 28% by week 9.
2. **A big perceived-vs-projected gap is NOT automatically a sell.** Check whether the
   ROLE supports the points first. Olave's 28.2 on 13 targets at 86% snaps meant my
   projection was wrong, not that he was inflated. `role_supported()` gates this.
3. **Draft capital matters.** He killed Olave (ADP 20) + Waddle (44) for Metcalf (64).
4. **One week is not a sample.** Do not sell or drop on one bad game. Do act on
   structural holes that predate the season.
5. **Snap share is the role; team pass attempts are what the role is worth.**
6. **A handcuff to another manager's starter is worthless.**
7. **Verify rosters against the API.** He caught a hardcoded roster going stale.

---

## 6. Rules I broke — do not repeat

**NEVER suggest a trade without running it first.** Broken three times: Waddle/Henry,
Waddle/Cook, Olave+Waddle/Metcalf. All three were declined-on-arrival or bad value.
Run `perception.acceptable()` AND the lineup delta BEFORE naming a player.

**NEVER copy `dashboard.html` over `dash_template.html`.** It duplicates the whole
template; a duplicate `const` kills every handler on the page.

**Any file written once and read forever goes stale silently.** Three times:
`dashboard.json`, `sleeper_meta.csv`, a hardcoded roster. Always fetch.

**A patch anchor matching in two places lands in the wrong one.** Remove by index
within the target function, not by string search.

---

## 7. Open items

- **Lineup**: Price still starting over Croskey-Merritt.
- **GitHub Action**: likely never enabled. One click in the Actions tab.
- **Dashboard from a local file** has origin `null` — live fetch blocked, falls back to
  a build snapshot. Also breaks player photos and the unranked drill-down. Serve over
  http or GitHub Pages.
- **`docs/index.html` never pushed** — `nathansantamaria.github.io/FFAgent/` returns 403.
- **`write.py` has never executed a click.**
- **10+ commits unpushed** as of this writing — Nathan pushes manually.

---

## 8. Run it

```bash
pip install -r requirements.txt --break-system-packages
python build_dash.py          # rebuild dashboard.html
python -m ffagent.gamelog     # weekly logs, slow, needs nflverse
```

Key modules: `myboard` (the board), `perception` (what others think), `roster`
(verification), `livedata` (repo-committed Sleeper data), `objective` (playoff
weighting), `matchups`, `units`, `participation`, `feed`, `news`, `gamelog`.

---

## 9. Long-term goal

A social platform: share rankings with friends, view others', create short-form content
across sports leagues. Agent logic first, then the app.
