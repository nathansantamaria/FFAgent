# Status — 22 September 2026, week 3

**Artificial Domination, 1-1, 276.90 PF (4th of 10).** Lost week 1 with the league's
lowest score, won week 2 with 159.34.

## Works

| Module | What it does |
|---|---|
| `myboard` | The board — ensemble projection, pooled flex VOR, tiers |
| `perception` | What OTHER managers think a player is worth. Gates every trade |
| `roster` | Fetches and verifies the roster; never hardcoded |
| `livedata` | Reads Sleeper data committed by the GitHub Action |
| `objective` | Playoff weighting — weeks 15-17 at 2.6x |
| `matchups` | Points allowed by defence by position |
| `units` / `defense` | All 32 defences and 31 kickers under league scoring |
| `participation` | Route rate and TPRR — strongest measured signal, 0.918 |
| `feed` / `news` | Categorised news, 10 most recent, relevance starring |
| `gamelog` | Weekly anomalies with causes, cross-linked players |
| `decide` | 0-100 confidence with cost netted out |
| `lineup` | Exact assignment, incumbency, slot-type diffs |

## Not working

**Sandbox cannot reach Sleeper or ESPN** — 403 `host_not_allowed`. Browser tool,
GitHub Action, or screenshots. See HANDOFF.

**GitHub Action probably not enabled** — one click in the Actions tab.

**Dashboard from a local file** has origin `null`; live fetch blocked, uses a build
snapshot. Also breaks photos and the unranked drill-down.

**`docs/index.html` never pushed** — Pages link 403s.

**`write.py` has never executed a click.**

## Known model limits, updated

- **Team pass attempts move a lot week to week.** NO went 56 to 34, HOU 38 to 56,
  CLE 22 to 30. The volume adjustment needs a rolling average, not one game. This
  is the most likely cause of the Freiermuth-over-Fannin miss.
- In-season blend weights two games at 33% (`games/(games+4)`).
- Route-rate 0.918 is one season, WR/TE only, n=178.
- Only the Rams defence is personnel-verified.
- 2026 in-season schedule unpublished, so `matchups.schedule()` is empty.
