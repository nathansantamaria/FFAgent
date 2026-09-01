# Status — 1 September 2026

Draft is **Tuesday 8 September, 16:30 ET**, slot 9 of 10, 120-second clock.

## Works, tested

| Module | What it does |
|---|---|
| `myboard` | The board. 196 players, ensemble projection, pooled flex VOR, tiers |
| `objective` | Playoff weighting — weeks 15-17 at 2.6x, real schedules, availability |
| `live` / `draft_live.py` | On-the-clock recommendations, drift, fallers |
| `mock` | Full drafts vs bots, self-grading |
| `participation` | Route rate and TPRR — the strongest signal measured (0.918) |
| `units` / `defense` | All 32 defences and 31 kickers, scored under league rules |
| `matchups` | Points allowed by defence by position |
| `decide` | 0-100 confidence with cost netted out, falsifiable conditions |
| `feed` / `news` | Categorised news, auto-ingest, relevance starring |
| `gamelog` | Weekly anomalies with causes, cross-linked players |
| `rankings` | Cumulative snapshots, movement tracking |
| `lineup` | Exact assignment (Hungarian), incumbency, slot-type diffs |
| `waivers` / `trades` | Claim and trade logic with gates |
| `schedule` | 13 refresh windows, DST-correct |
| `calibration` | Backtested signal weights, outcome tracking |

## Not working yet

**`write.py` has never executed a click.** Selectors are probed against the real DOM and
the addressing scheme (row index, not label) is solved. The interaction is unproven
because the roster is empty pre-draft. First test: after the draft, on a lineup change.

**Nothing is scheduled.** `python run.py --crontab | crontab -` on an always-on machine.
Every refresh so far has been manual.

**No read on the nine managers.** Largest available edge and no data buys it.

## Known data limits

- Zero 2026 games played. Signal confidence 0.25 until week 1.
- FFC's `teams=` parameter is ignored; ADP is blended-format with a correction.
- ADP snapshot is from 31 Aug — **re-pull the morning of the draft**.
- QB scoring diverges from nflverse on 44% of rows, mean +0.45. Bounded, unexplained.
- Route-rate 0.918 is one season, WR/TE only, n=178. Ordering trusted, magnitude held loosely.
- Only the Rams defence is personnel-verified; others sit at market.
- Game logs cover 53 of 59 players, career table 39 — name-matching, needs an ID join.
- 2026 in-season schedule unpublished, so `matchups.schedule()` is empty.

## Run it

```bash
pip install -r requirements.txt
python build_dash.py                                    # rebuild dashboard.html
python draft_live.py --draft-id 1400160157035446272     # on the clock
python run.py --agenda                                  # what fires next
python test_e2e.py                                      # offline end-to-end
```
