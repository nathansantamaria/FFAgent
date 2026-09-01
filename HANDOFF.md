# HANDOFF — everything another session needs

Last updated **1 September 2026**. Read this first; `STATUS.md` for what works,
`README.md` for why each decision was made.

---

## Identifiers

| Thing | Value |
|---|---|
| League | Public Randoms 2026 |
| Sleeper league_id | `1400160155982639104` |
| Sleeper draft_id | `1400160157035446272` |
| My user | SantaSleeper, user_id `1271917344913907712` |
| My draft slot | **9 of 10** |
| Draft | **Tue 8 Sep 2026, 16:30 ET**, snake, 120s clock, 15 rounds |
| Old league (reference) | Goon Squad, 8-team, `1396378344425009152` — **not this league** |

## League settings (pulled from API, confirmed against the UI)

```
10 teams, PPR (rec 1.0), snake
Starters: QB RB RB WR WR TE FLEX FLEX K DEF
Bench 5, IR 2, no taxi
Waivers: REVERSE STANDINGS (waiver_type 1), clear Wed 3am, 2-day hold
Playoffs: 6 of 10, from week 15
Trade deadline: week 11
Scoring: vanilla — 4pt pass TD, no bonuses, no TE premium
```

**`waiver_type: 1` is Reverse Standings, not FAAB.** `waiver_budget` reads 100 even in
non-FAAB leagues, so it is not a safe signal. Priority is your inverse record and cannot
be spent, so claims are close to free — claim whenever a player clears the bar.

**My pick numbers:** 9, 12, 29, 32, 49, 52, 69, 72, 89, 92, 109, 112, 129, 132, 149.
Gaps alternate 3 and 17 — you draft in pairs, then 17 players vanish.

## The objective

Not points. **Make and win the playoffs.** Six of ten qualify, so getting in is likely
and weeks 15-17 are what the season is for. `objective.py` weights playoff weeks 2.6x,
uses real week 15-17 schedules, and charges availability harder because three must-win
weeks compound.

## Derived numbers that everything depends on

```
Replacement:      QB11, RB28, WR28, TE18
Flex-eligible starting spots league-wide: 70
Board size:       196 (incl. all 32 defences, 31 kickers)
```

**Both flex slots accept TE**, so RB/WR/TE compete for the same 70 spots and share ONE
pooled VOR baseline. Scoring them per-position made replacement-level tight ends look
scarce and put McBride at #1 overall. This is the single most important modelling
decision in the project.

## Signal weights — measured, not chosen

Backtested 2022-25, weeks 1-4 predicting weeks 5-17:

| Signal | Spearman |
|---|---|
| **route rate x TPRR** | **0.918** (2025, WR/TE, n=178) |
| targets per route run | 0.839 |
| early points | 0.784 |
| blended usage | 0.774 |
| target share | 0.787 / 0.697 |
| air yards share | 0.299 |
| carries | 0.264 |

**The fade signal is 2.7x stronger than the buy signal.** Points outrunning usage
regresses hard: -1.02 PPG against a points-only model, in 4 of 4 seasons. `usage.fadelist()`
surfaces it. The original design hunted buys and had this backwards.

## Live news that must not go stale

- **Josh Jacobs — Commissioner's Exempt List, 30 Aug.** Cannot practise or play. First
  court date 17 Nov (week 11). MarShawn Lloyd inherits; Kaleb Johnson traded in from
  Pittsburgh same day, so treat as a committee.
- **Rams defence.** Myles Garrett traded from Cleveland June 2026 (reigning DPOY, record
  23 sacks); Aaron Donald unretired 30 Aug; Trent McDuffie in from KC. ADP ~108 predates
  the Donald signing by one day. Largest personnel-vs-price gap on the board.
- **Zero 2026 games played.** Season opens 9 Sep. Signal confidence 0.25 until then.

## Traps that have already bitten

1. **FFC's `teams=` parameter is ignored** — `teams=10` and `teams=12` return
   byte-identical payloads. ADP is blended-format with a crude correction applied.
2. **nflverse codes the Rams as `LA`, not `LAR`.** A lookup keyed on LAR silently misses.
3. **Sleeper name-matching needs a position guard.** "Josh Allen" matches an offensive
   guard before the Bills QB.
4. **`offense_pct` is a fraction (0.86), not a percentage.**
5. **Injury reports miss IR.** A player on IR stops appearing, so a season-ending injury
   registers as *fewer* Out designations than a month of tweaks. Durability is built on
   games played, not the report.
6. **Any file written once and read forever goes stale silently.** A pre-baked
   `dashboard.json` re-rendered an 88-player board for hours while appearing to update.
   Build fresh from functions.
7. **Never copy `dashboard.html` back over `dash_template.html`** — that is how the
   template ended up with two of everything and a syntax error killed every handler.
8. **A patch anchor that matches twice lands in the wrong place.** Removing a block by
   plain string search deleted the legitimate copy and left the broken one.

## Running it

```bash
pip install -r requirements.txt

python build_dash.py                                  # rebuild dashboard.html
python draft_live.py --draft-id 1400160157035446272   # on the clock, live
python draft_live.py --picks "Gibbs,Bijan,..."        # manual/testing
python run.py --agenda                                # what fires next
python run.py --crontab | crontab -                   # NOT YET INSTALLED
python test_e2e.py                                    # offline end-to-end
python -m ffagent.gamelog                             # regenerate weekly logs (slow)
```

## Before the draft — do these

1. **Re-pull ADP the morning of 8 Sep.** Current snapshot is 31 Aug. Preseason ADP moves
   fast and the whole faller-detection edge depends on it being current.
   `fantasyfootballcalculator.com/api/v1/adp/ppr?teams=10&year=2026&position=all`
2. **Probe write.py selectors** once a roster exists:
   `python -m ffagent.write --league-id 1400160155982639104 --probe --live`
3. **Install cron** on an always-on machine. The Sunday 11:30 inactive sweep is the
   highest-value job and it has never run.

## Open gaps

- `write.py` has never executed a click. Addressing scheme solved (row index, not label);
  interaction unproven because the roster is empty.
- No read on the nine managers. Largest available edge; no data buys it.
- QB scoring diverges from nflverse on 44% of rows, mean +0.45. Bounded, unexplained.
- Game logs cover 53/59 players, career table 39/59 — name matching, needs an ID join.
- 2026 in-season schedule unpublished, so `matchups.schedule()` returns empty.
- `ffagent/dashboard.py` is now a shim. The original generator was deleted 1 Sep and is
  not recoverable; nothing it did is missing from `build_dash.py`.

## Long-term goal

Turn this into a social platform: share with friends, make your own rankings, view
others', create and share short-form content (highlights, reposted fantasy videos),
across different sports leagues. Build the agent logic first, then port it.
