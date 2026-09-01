# ffagent

Autonomous Sleeper league manager. Reads through the public API, writes through
browser automation, logs every decision it considers.

## What's built

| Module | Status | Purpose |
|---|---|---|
| `sleeper.py` | working | Read-only client. League state, rosters, transactions, trending, player universe (cached 24h) |
| `config.py` | working | Bootstraps all league rules from `/league/<id>` — nothing hardcoded. Derives replacement level from team count + starter slots |
| `usage.py` | working, tested | The edge. nflverse usage deltas + watchlist scoring |
| `decisions.py` | working | Decision log with calibration tracking |
| `dashboard.py` | working | Static four-panel HTML, Sleeper structure / Claude palette |
| `lineup.py` | working, tested | Exact slot assignment (Hungarian) + projection blend |
| `schedule.py` | working, tested | Event-driven windows, DST-correct |
| `waivers.py` | working, tested | Claim logic for priority and FAAB |
| `trades.py` | working, tested | Gated proposals, mutual-benefit requirement, hard throttle |
| `calibration.py` | working, backtested | Measured signal weights, outcome tracking |
| `news.py` | working, tested | Hard availability gate for news ADP can't know |
| `simulate.py` | working, tested | Monte Carlo survival probabilities |
| `draft.py` | working, tested | VOR board, tiers, durability, pick logic |
| `scoring.py` | working, tested | Recomputes points under the league's own rules |
| `sources.py` | working, tested | Source registry, probing, league-aware weights |
| `state.py` | working, tested | Builds the world: rosters, projections, wire. Fixture-injectable |
| `orchestrator.py` | working, tested | Window → job dispatch |
| `write.py` | selectors probed, interaction unproven | Playwright layer — the only place that clicks. Selectors need capturing |

## The thesis — backtested, and partly wrong

I'd been asserting "usage leads production" throughout. Tested it on four seasons
(2022–2025, 972 player-seasons, weeks 1–4 predicting weeks 5–17, RB/WR/TE).

**Finding 1: raw usage does not beat raw points.**

| Signal | Spearman |
|---|---|
| early points | **0.784** |
| blended usage | 0.774 |
| target share | 0.697 |
| targets | 0.686 |
| air yards share | 0.299 |
| carries | 0.264 |

Usage is *nearly as* predictive, not more. The original claim was overstated.

**Finding 2:** usage adds real but modest information on top of points — +0.14
correlation with the residual after points are accounted for. Small, real, not
dominant.

**Finding 3, which changed the design: the signal is asymmetric.**

| Divergence group | vs points-only model |
|---|---|
| usage >> points (buy) | **+0.37 PPG** |
| points >> usage (fade) | **−1.02 PPG** |

The fade is **2.7× stronger**, and held in 4 of 4 seasons with a positive spread
every year. Points outrunning usage is touchdown luck, and it reverts hard.

This inverts the original build. The watchlist hunted buys; the better-evidenced use
of the same number is knowing who to bench, shop, or *not* claim. `usage.fadelist()`
now surfaces it. Both are weighted by measured strength rather than by which is more
interesting.

**Signal weights are now measured, not chosen.** The hand-set values gave air-yards
share 0.7 and carries 0.6 against target share's 1.2 — roughly twice too generous for
the two weakest signals.

**ADP recency:** `adp_recency_weight()` decays a snapshot with a ~10-day half-life.
Preseason ADP moves fast; a snapshot from before last season is worth almost nothing
for player value and is useful only for studying market behaviour.

**Learned weights** replace backtested ones per source once it has 25+ scored
outcomes. Below that it stays on the backtest — weighting on five observations is how
you confidently trust noise, the same mistake the watchlist made with one-game snap
spikes.

## The original thesis (superseded above)

Usage leads production by 1–3 weeks. Snap share, route participation and target
share move before the box score does, and the box score is what your leaguemates
read.

The edge is **not** beating the global market. It's beating seven specific
people whose failure modes you know. In a redraft league there is no price —
only acquisition order and whether someone will trade with you.

`watchlist()` ranks the divergence: role grew, production hasn't caught up yet.

## Three things the data actually taught us

**1. The 2026 season file doesn't exist yet.** nflverse publishes one file per
season, created after games are played. Verified 2026-08-31: `stats_player_week_2025`
and `snap_counts_2025` exist; the 2026 equivalents 404. The pipeline falls back to
the prior season and discounts confidence to 0.25.

Consequence: **weeks 1–3 are the weakest part of this system**, which is exactly
when the waiver wire matters most. Plan for a cold start — lean on depth-chart
reporting and beat writers early, not on this.

**2. Naive deltas surface garbage.** First run put a fourth-string receiver at the
top — 94% snap share, huge delta, completely meaningless. He'd played one blowout.

**3. The important fix wasn't a volume floor.** A volume floor didn't clear it.
The real bug: a 0.94 delta off a base of *zero* means the player didn't play in
the prior window at all. That's an **availability change, not a role change** —
different thing, different trade. `min_games_each_window` requires participation
in both windows before a delta counts.

After that fix the list is real. Amon-Ra St. Brown: 92% snaps, target share up,
fantasy points *down* — usage rising, production not repriced. That's the signal.

## ID chain

Sleeper `player_id` → `gsis_id` (in Sleeper's player payload) → nflverse
`player_id`. Snap counts key on `pfr_player_id`, so `players.parquet` provides the
`gsis_id` ↔ `pfr_id` crosswalk. **gsis is the spine.**

## Cadence

Daily is wrong. Fantasy is event-driven:

| When | Why |
|---|---|
| Tue 23:00 ET | Waiver claims lock — submit before |
| Wed 03:00 ET | Waivers process, pool reopens |
| Thu 17:00 ET | TNF lock |
| **Sun 11:30 ET** | **Inactives drop. Highest-value window of the week** |
| Sun 13:00 ET | Main slate lock |

Build the Sunday inactive sweep first. A starter ruled out at 11:45 and replaced
by 12:55 is worth more than every other automation combined.

## Build order

1. **Shadow mode, 2 weeks.** Log every decision, execute nothing. Find out if the
   logic is good before handing it the keys.
2. **Lineup setting only.** Idempotent, reversible, verifiable.
3. Waivers.
4. Trades last — and cap at one proposal/week. Autonomous trading is a social
   problem, not a technical one.

**Every write: act in the browser, confirm through the API.** Never trust the DOM
to tell you it worked.

## Setup

```bash
pip install pandas pyarrow requests scipy playwright

python run.py --agenda                                    # what fires next
python run.py --crontab                                   # install lines
python run.py --league-id YOUR_ID --user-id YOUR_USER_ID  # runs whatever is due
python run.py --league-id YOUR_ID --user-id YOU --window inactives
python test_e2e.py                                        # full run, no Sleeper needed
```

Shadow mode is the default and `--live` is not wired. Nothing writes.

`state.build()` takes an optional `fetch` dict of shims, so the whole system runs
against a fixture with no network. Every bug in this project was found by testing
against real data, and a world-builder that only runs online is one you stop testing.

## Dashboard

```bash
python -c "from ffagent import dashboard; dashboard.build('League name','8-team PPR')"
```

Writes `dashboard.html`. No server, no build step — open the file. Four tabs:
pending, watchlist, rejected, calibration.

Two things the screenshots caught that the code didn't:

**The role-gap bars were all pinned at 100%.** Scaled against a fixed multiplier
instead of the range on screen, so every bar maxed out and the column carried no
information. Now scaled to min/max of the visible set.

**Adjacent supporting factors were one flat coral** and unreadable as separate
things. Stepped shades for factors arguing *for* an action, sage for against.

## Lineup optimiser

Two jobs that get conflated and shouldn't be:

**Projection** is the weak link, and I'd rather say so than bury it. `project()`
blends recent and season-long scoring with a small usage tilt scaled by signal
confidence. Replace it with a real source when you have one; nothing else changes.

**Assignment** is exact and worth doing properly. Greedy fills lose points on flex
— your best remaining player in FLEX can strand a WR-only slot. Solved as
max-weight bipartite matching. This is the unglamorous, reliable value: it never
gets tired in week 13, and humans lose points to it weekly.

### Three bugs the tests caught

**Cascading slot shuffles.** With two starters out, the optimiser reported four
changes: "DJ Moore is unavailable" when he'd simply slid WR2→WR1. Same points,
wrong explanation, and two needless clicks against a deadline.

**Incumbency map collapsed duplicate slots.** First fix keyed on base slot name,
so WR1 and WR2 overwrote each other and only one player kept his stay-put bonus.

**Slot labels aren't identities.** RB1/RB2 are an artefact of numbering — Sleeper
doesn't distinguish them and the solver assigns them arbitrarily. `diff()` now
compares players *per slot type*. Two changes produce two writes; a stable lineup
produces zero.

## Write layer — probe results

Probed against the live logged-in DOM, 2026-08-31. **Every selector I'd guessed was
wrong, and wrong the same way:** I assumed Sleeper exposed `data-*` hooks for players
and slots. There is not a single `data-player-id` or `data-slot` on the page. The
markup is class-based.

Real structure:

| Element | Selector |
|---|---|
| Roster rows | `.team-roster-item` (exactly 15) |
| Slot label | `.league-slot-position-square` |
| Player name | `.cell-player-meta` |
| **Click target** | `.cell-position` |
| Session check | `.nav-league-item-wrapper` |
| Captcha | `[data-hcaptcha-widget-id]` |

**The structural finding that matters: a slot is identified by row index, not by a
label.** `.team-roster-item` returns 15 rows in the same order as `roster_positions`,
so index 6 is the first FLEX regardless of what the page displays (it renders "W R T",
not "FLEX"). That's the same positional scheme the API's `starters` array uses — so
the write path and the verification read agree by construction rather than by
translation.

`slot_index()` is now the single translation point between a human-readable slot and
the index both the DOM and the API use.

**hCaptcha is present on the page.** `ensure_logged_in` now fails closed if a
challenge appears. Solving it is out of bounds and retrying into one is how an account
gets flagged.

**What is still unproven:** the roster is empty pre-draft, so the click sequence for an
actual swap could not be exercised. Elements are located; the interaction is not. That
needs one real player on the roster to test against, which means after the draft.

## Write layer design

Three rules, and they're the whole design:

1. **Act in the browser, confirm through the API.** The DOM will report success
   when nothing happened. Only `/league/<id>/rosters` is proof. `WriteResult.verified`
   comes from a read-back with retry — Sleeper is eventually consistent, so a single
   immediate read makes good writes look failed.
2. **Deltas, not full state.** One player, one slot, verify, next. Stop on first
   failure. A half-applied lineup is recoverable; a blindly-continued one isn't.
3. **Selectors are guesses until proven.** Every DOM assumption is in `SELECTORS`.
   Run `python -m ffagent.write --league-id X --probe --live` against a logged-in
   session and paste the results back. Until then this module is a sketch.

Session persists via Playwright `storage_state`. `ensure_logged_in()` treats the
logged-out state as an explicit failure — the dangerous case isn't an exception,
it's a script cheerfully clicking nothing on a login wall.

## Scheduler

`python -c "from ffagent import schedule; print(schedule.agenda())"` prints the
week. `schedule.crontab()` emits real cron lines.

**The trap is timezones.** Every fantasy deadline is quoted in Eastern, and ET is
UTC-4 in September and UTC-5 in December. Hardcode an offset and every window slips
an hour on the first Sunday in November — during the playoff push, when a missed
inactive sweep costs most. Windows resolve through `America/New_York` each time;
verified 11:30 ET holds on both sides of the 2026 boundary while UTC shifts under it.

## Waivers

Two mechanics needing different logic:

**Rolling priority** is a single-use asset. The question isn't "is he good" but "is
he worth burning priority I may want in week 9." The agent proposes at most one
claim per week under priority, and says in plain words what it costs.

**FAAB** is a budget. Bid to value, scaled by weeks remaining — overpaying in
September for a week-3 flex is how you reach week 11 with $3.

`drop_score` isn't just lowest projection. A low-scoring backup behind your RB1 is
insurance; a mid-scoring fifth receiver isn't. Depth at a thin position counts.

**Bug caught in testing:** two FAAB claims both named the same drop. Each looked
fine alone; if both cleared, the second has no valid drop and the platform either
rejects it or cuts someone you didn't choose. Drops are now reserved across claims
and lower-priority ones re-solve against what's left.

**Known weakness, stated rather than hidden:** `faab_bid` takes `max(gain, edge)`,
mixing projected points with a normalised z-score. The direction is intended — bid
up on strong usage signals — but the magnitude isn't defensible. Revisit once the
decision log has real outcomes.

## Trades

Most trade tools measure value gained against a ranking list. Wrong metric twice:
bench points don't score, and a trade the other manager won't accept isn't a trade,
it's spam that costs your reputation for the season.

So the bar is built on **two** numbers. What my starting lineup gains, and what
theirs gains. Both must be positive — not out of politeness, but because that's the
only reason trades exist. Rosters are imbalanced in different directions, and the
surplus one team can't start is what the other one needs.

### The gates

| Gate | Threshold | Why |
|---|---|---|
| My starting gain | ≥ 2.0 pts/wk | 1 pt/wk is inside projection noise |
| Their starting gain | ≥ 0.75 pts/wk | They must improve or won't accept |
| Gain ratio | ≤ 2.5× | Lopsided offers read as predatory |
| Playoff gain | ≥ 0 | Helps in October, hurts in December = fail |
| Top-player share | ≤ 28% | Consolidation makes one injury fatal |
| Position depth after | ≥ 1 spare | Don't strip a position chasing points |
| Roster size | ≤ legal | 2-for-1 needs a spot you have |

All must pass. Every rejection records the number that failed, so the dashboard
shows why.

### Two bugs worth naming

**`abs()` in the gain ratio.** A trade where I gained 6.5 and the partner *lost*
7.5 reported a ratio of 0.87 and passed that gate. A trade that hurts them has no
meaningful ratio; it's now infinity.

**56 approved proposals.** The gates were right and the output discipline wasn't.
The search returns dozens of near-identical variants of one idea. Now: one offer per
partner, ranked by joint gain, then `propose()` caps it at **one proposal per week**
with a **14-day cooldown per manager** regardless of how good the second looks.

That throttle is doing more real work than any gate. Seven humans receiving
optimised offers from a bot is a social problem no scoring function solves.

### Search depth

Deliberately shallow — 1-for-1 and 2-for-1 only, no 2-for-2. Deeper searches find
more "approved" trades mostly by exploiting projection noise, and projections are
the weakest part of this system. If the edge only appears in a 3-for-3, it isn't one.

## Refresh cadence

Thirteen refresh windows a week, seven decision windows.

- **Daily 07:00 ET** — every source pulled, board rebuilt, news re-gated.
- **T-minus-60 on every deadline** — waiver lock, TNF, Sunday early, Sunday late, SNF, MNF.

The T-60 refreshes matter more than the daily. Data pulled at 07:00 is eight hours
stale by a 15:00 waiver lock, and stale data at a deadline is worse than no data
because it looks current. `refresh_all` proposes nothing — a refresh that also makes
decisions isn't one you can safely run unattended at 06:00.

## Sources — twelve registered

| Source | Unique contribution | Status |
|---|---|---|
| **espn_projections** | **2026 per-week projections, draft ranks, byes** | live, no auth |
| espn_news | Breaking news feed | live |
| ffc_adp | Market ADP + per-player variance | live |
| stats / snaps / injuries / depth / pfr_rec / players | nflverse | live |
| sleeper_trending | What the market is claiming now | live |
| weather | Wind above 15mph | live, no key |
| vegas | Implied team totals | needs key |

**The ESPN projections endpoint is the biggest single addition.** It's the only
*forward-looking* source — everything I compute from nflverse is derived from last
season and structurally cannot see a changed situation. It also carries bye weeks and
injury status, neither of which nflverse has before the season starts.

## The ensemble

Three views that fail in different directions, blended: my 2025-production model
(0.35), ESPN's 2026 projection (0.45), market-implied value from ADP (0.20). ESPN
gets the heaviest weight for being the only 2026 view.

`Ranked.disagreement` surfaces how far apart the sources are rather than averaging it
away. A player both sources like is safer than one with the same mean where they
differ by four points a game — and the disagreements are usually where the value is.

## News overrides — why ADP alone is dangerous

**ADP structurally cannot know today's news.** FFC's numbers are a trailing average;
verified 2026-08-31, the window was Aug 24–31 across 8,161 drafts. A player whose
situation changed on Aug 30 still carries an ADP built almost entirely from drafts
that happened before it.

**The case that proves it.** Josh Jacobs was placed on the Commissioner's Exempt List
on Aug 30 — cannot practise, cannot attend games, only the Commissioner can reinstate
him, first court date Nov 17. His ADP was still **31.6**, which is picks 29 and 32 for
draft slot 9. The simulator rated him **73% available at pick 29** and listed him as a
live option.

A confident probability about a player who cannot take the field is worse than no
number at all.

**Availability is a hard gate, applied before value — never a modifier blended into
it.** A 30% discount on someone who might miss the season is a rounding error dressed
up as analysis. `BLOCKED` statuses (exempt, suspended, IR, PUP, NFI, retired, holdout)
remove a player from the board entirely. News is applied *before* simulation, not after.

The same lag is the upside: MarShawn Lloyd inherits the Green Bay backfield and isn't
priced in at all, because the ADP predates the news. Kaleb Johnson was traded to Green
Bay the same day, so it's a committee — that caveat is in the override too.

`adp_staleness()` prints how many days of news the ADP cannot contain. That window is
exactly the size of your edge over anyone drafting off the number.

## Drafting

10-team, slot unknown. That's fine — a good board is slot-agnostic. What changes
with slot is only *when* tier breaks fall relative to your picks.

**Replacement levels (10-team, 1 flex):** QB11, RB24, WR24, TE14. Everything is
downstream of these. VOR isn't a ranking — it's the only number that makes positions
comparable, and it's why a tight end who looks elite by projection often isn't worth
an early pick.

**Tiers over ranks.** Tier breaks are computed from the 80th-percentile gap within
each position. Inside a tier take the cheaper player; across one you reach.

**Run detection.** Four of the last six at one position. The correct response is
usually to sit it out — runs are where people reach, and the value sits in the
position everyone just stopped drafting.

**Upside is defined against ADP, not in the abstract.** A high-ceiling player at his
ceiling price is fair value, not upside. It's the gap between where the market has
him and where his tier says he belongs — which is why it's only worth acting on late,
where gaps are widest and being wrong costs a bench spot.

### Durability — and the bug in the first version

Four seasons of nflverse injury reports, 2,629 players. First version counted weeks
listed "Out" and produced this:

> Christian McCaffrey — 2 weeks Out of 44 tracked, 94% available, **"durable"**

He played **4 games in 2024**.

The injury report is badly wrong for exactly the players you most need it for. A
player placed on IR *stops appearing on the weekly report*, so a season-ending injury
registers as **fewer** Out designations than a month of ankle tweaks. The metric was
inverted for catastrophic injuries.

Rebuilt on **games played** — a missed game is a missing stat line whatever the
paperwork says. The report is kept as a secondary signal, since it distinguishes a
healthy scratch from a knee.

| Player | Report-based | Games-based |
|---|---|---|
| McCaffrey | 94%, durable | **87%, some risk** |
| Olave | 86%, some risk | **79%, fragile** |
| Higgins | 88%, average | **78%, fragile** |
| Nabers | 89%, average | **64%, fragile** |

Rates are shrunk toward the league mean — one missed week in one season isn't a
measurement. A player's tracked window starts at his first stat line, so a 2024
rookie isn't charged for missing 2022.

Availability enters as a multiplier on projection, not as a vague tiebreaker applied
when you already dislike someone.

## Data sources

Nine registered, six verified live from nflverse. Each declares what it uniquely
contributes — a source earns its place by telling you something the others don't.

| Source | Unique contribution | Status |
|---|---|---|
| stats | Box score, target share | live |
| snaps | Snap share — best role signal available | live |
| **injuries** | **Practice participation** | live |
| depth | Depth rank and slot | live |
| pfr_rec | Drops, broken tackles | live |
| players | gsis ↔ pfr ↔ espn crosswalk | live |
| sleeper_trending | What the market is claiming now | needs network |
| vegas | Implied team totals | needs API key |
| weather | Wind above 15mph | needs network |

**Injuries is the important addition.** It's the only source that *leads* the box
score rather than describing it. Two DNPs on Wednesday and Thursday predict a Sunday
absence days before the inactive list, and Sleeper's own `injury_status` lags beat
reporting. Practice status now overrides a stale official tag.

Unavailable sources degrade to a note, never an exception. A Sunday sweep must run
when a feed is down.

### League setup changes which sources matter

`source_weights(cfg)` isn't cosmetic. In PPR, receptions are the currency and target
share carries the projection. In standard, touchdowns and carries dominate and
reception-heavy signals mislead. Superflex makes QB scoring track the game total, so
Vegas matters more. An 8-team league has a shallow wire, so consensus data matters less.

## Scoring: the quiet bug

I was using nflverse's `fantasy_points_ppr`, which hardcodes 1.0 per reception and
ignores everything a commissioner can change — half-PPR, TE premium, 6-point passing
TDs, first-down bonuses. Every projection, waiver gain and trade gate inherited it.

`scoring.py` recomputes from raw stats against `league.scoring_settings`. Sleeper
returns those for every league, so it's free correctness.

**Sub-bug found while validating:** `fum_lost` mapped to a column that doesn't exist.
nflverse splits fumbles across rushing, receiving and sacks, so the penalty was never
being subtracted and failed silently. `STAT_MAP` values can now be a list of columns
to sum, and unmappable rules are reported in `pts.attrs["unscored"]` rather than
swallowed.

**Validation, honestly:** against nflverse's own PPR column, RB/WR/TE agree on 97-99%
of rows. **QBs diverge on 44%, mean +0.45 points, cause not isolated.** Special-teams
TDs explain 20 rows; passing 2-pointers explain 8; the rest is unexplained. Ours is
the number to trust since it uses the league's actual rules, but the residual is an
open item, not a solved one.

**Where it matters and where it doesn't:** format changes production by 1.2 pts/game
on average and up to 9 for high-volume receivers (Nacua, Olave). But the watchlist
ordering barely moves — Spearman 0.99 between formats — because the edge score
z-normalises both role and production, which washes out scale. So this fixes
projections, lineup decisions and trade math; it does not change who gets flagged.

## The bug that mattered most

`inactive_sweep` — the highest-value job in the system — returned **zero decisions
with two starters ruled out**, and did so silently.

Cause: the baseline lineup was built by *optimising* the roster. The optimiser
already benches unavailable players, so the sweep was comparing optimal against
optimal and correctly finding nothing to change. It would have run every Sunday all
season and never fired.

Fix: the baseline is now the lineup **as actually set on Sleeper**, reconstructed
from `roster["starters"]`, which is positional against `roster_positions` with `"0"`
for empty. Only players in the current lineup trigger the sweep — a benched player
being Out is not news.

Two smaller ones from the same run:

**`watchlist()` dropped `gsis_id`** from its output columns. That's the only key
joining usage signals back to Sleeper, so the watchlist was unusable by every caller
downstream.

**Six decisions, one thesis.** The sweep emitted a row per slot, each repeating the
full explanation. A lineup change is one thing you approve once; the write layer
still executes it as N separately verified writes.

## Open question

Disclosure. Easier said up front than discovered in November. Worth checking the
platform's terms on automation before you're eight weeks in.
