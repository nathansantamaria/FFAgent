# LOGIC — every decision rule, with the reasoning

This is the document to paste into a context window. It carries the *why* behind every
number in the system. `HANDOFF.md` has the identifiers; this has the thinking.

Everything below is either measured (a backtest is cited) or derived from league
structure. Where a number is a judgement rather than a finding, it says so.

---

# PART 1 — THE OBJECTIVE

**Win the playoffs. Not maximise points.**

Six of ten qualify from week 15. A roster of even average strength probably makes it,
so the regular season is a qualification exercise and weeks 15-17 decide the season.

Consequences that change actual picks:

- **Playoff weeks weight 2.6x a regular week.** Three of fourteen scoring weeks hold
  about a third of a player's value.
- **Availability is charged harder than in a season-long projection.** Three must-win
  weeks compound. A player at 76% availability is near a coin flip to miss one of them,
  and that is the game you cannot replace him for. This costs Nico Collins 3.4 pts/gm,
  Jonathan Taylor 3.0, McCaffrey 2.9.
- **Ceiling-vs-floor preference moves with the calendar.** Qualifying rewards banking
  wins, so consistency. The playoffs reward upside, because you face the best remaining
  teams and an average week loses. `phase_weight()`: 0.5 through week 6, **0.35 weeks
  7-13** (favour floor), **0.75 from week 14** (favour ceiling). A fixed preference gets
  half the season wrong.

Playoff-schedule effect is real but smaller than people assume: worth about a point a
game either way, against 3+ for availability.

---

# PART 2 — HOW A RANKING IS BUILT

Order matters. Each step feeds the next.

### Step 1 — Availability gate (hard, before value)

News that blocks availability removes a player from the board **entirely**. Not
discounted — removed. A 30% discount on someone who might miss the season is a rounding
error dressed as analysis.

Blocking statuses: `exempt, suspended, ir, pup, nfi, retired, holdout, released`.

**Why this must come first:** ADP is a trailing average and cannot contain today's news.
Josh Jacobs sat at ADP 31.6 the day after going on the Commissioner's Exempt List. The
simulator rated him **73% available at pick 29** — a confident probability about a player
who cannot take the field, which is worse than no number.

### Step 2 — Ensemble projection

Three views that fail in different directions:

| Source | Weight | Fails how |
|---|---|---|
| ESPN 2026 projection | **0.45** | The only forward-looking view |
| My 2025-production model | 0.35 | Backward-looking by construction |
| Market-implied from ADP | 0.20 | Consensus, slow to update |

My own model shrinks a short sample toward the market: `w = min(1, games/14)`.

`disagreement` is surfaced, not averaged away. A player both sources like is safer than
one with the same mean where they differ by 4 pts/gm.

### Step 3 — In-season blend (once games exist)

```
w_season = games / (games + 4)
```

20% weight on live data after 1 game, 50% after 4, 75% after 12. **K = 4 is a judgement,
not a fitted constant** — the number most worth revisiting once outcomes are logged.

Role changes are **multipliers on opportunity, not nudges to output**. When Jacobs was
exempted, MarShawn Lloyd did not become 10% better — he inherited a backfield:

```
inherits_backfield 1.85 | inherits_target_share 1.45 | promoted_starter 1.35
committee_added 0.72 | demoted 0.55 | blocked 0.0
```

### Step 4 — Durability multiplier

**Built on games played, never on injury reports.**

The injury report is inverted for the players you most need it for: a player placed on
IR *stops appearing on the weekly report*, so a season-ending injury registers as FEWER
"Out" designations than a month of ankle tweaks.

Verified: report-based rated McCaffrey **94% available, "durable"**. He played 4 games in
2024.

| | report-based | games-based |
|---|---|---|
| McCaffrey | 94% durable | **87% some risk** |
| Olave | 86% | **79% fragile** |
| Higgins | 88% | **78% fragile** |
| Nabers | 89% | **64% fragile** |

Shrunk toward the mean: `rate = (missed + 16*0.10) / (possible + 16)`. Tracked window
starts at a player's first stat line, so a 2024 rookie is not charged for missing 2022.

### Step 5 — Playoff adjustment

`playoff_adjust()` applies, in order of magnitude:

1. **Bye inside weeks 15-17** → ×0.67. Should never fire (byes end ~week 14) but is
   disqualifying if it does.
2. **Playoff schedule** → `edge × 0.35`, from real week 15-17 opponents crossed with
   points-allowed-by-position.
3. **Availability** → `base × miss_rate × 0.9`. The largest term.

### Step 6 — VOR against ONE pooled flex baseline

**The single most important modelling decision in the project.**

Both flex slots accept RB, WR and TE. Those three compete for the same **70 starting
spots** league-wide (2 RB + 2 WR + 1 TE + 2 FLEX, × 10 teams). They must be measured
against one shared bar.

Scoring per-position gave TE a baseline of "replacement-level tight end" — genuinely
dreadful — so every startable TE looked enormous and the planner wanted three of them.
**McBride ranked #1 overall ahead of Gibbs and Bijan.** Pooled, he sits at #20.

- QB uses its own baseline (QB11) — one slot, no flex overlap.
- **K and DEF are excluded from cross-position VOR.** Their spread (~2-3 pts) against a
  RB's 10+ put a kicker in round 7. They rank among themselves only.

### Step 7 — Tiers

Computed **within position** from the 80th-percentile gap between consecutive players.
Inside a tier take the cheaper player; across a tier break is the only time reaching is
right.

A global tier heading is meaningless — the first render put Bijan, JSN, McBride and the
Seattle defense together in "Tier 1".

---

# PART 3 — MEASURED SIGNAL WEIGHTS

Backtested 2022-25, weeks 1-4 predicting weeks 5-17.

| Signal | Spearman | Sample |
|---|---|---|
| **route rate × TPRR** | **0.918** | 2025, WR/TE, n=178 |
| targets per route run | 0.839 | same |
| early points | 0.784 | 972 player-seasons |
| blended usage | 0.774 | same |
| target share | 0.787 / 0.697 | same |
| air yards share | 0.299 | same |
| carries | 0.264 | same |

**Route participation is the strongest thing measured.** `pbp_participation` lists the
actual player ids on the field for every play, so route rate — the share of his team's
dropbacks he was on the field for — is computed directly, not approximated by snap
share. Run-blocking snaps count the same in a snap-share number and are worth nothing in
PPR.

*Caveat: 0.918 is one season, WR/TE only. Ordering is trusted; magnitude held loosely.*

### The thesis was partly wrong, and the correction matters

**Raw usage does not beat raw points** (0.774 vs 0.784). Usage adds real but modest
information *on top of* points: +0.14 correlation with the residual.

**The signal is asymmetric, and that inverted the design:**

| divergence group | vs points-only model |
|---|---|
| usage >> points (buy) | **+0.37 PPG** |
| points >> usage (fade) | **−1.02 PPG** |

**The fade is 2.7× stronger, and held in 4 of 4 seasons.** Points outrunning usage is
touchdown luck and it reverts hard. The watchlist originally hunted buys; the
better-evidenced use of the same number is knowing who to bench, shop, or *not* claim.
`usage.fadelist()` surfaces it.

### Noise filters that were necessary

- **Volume floor:** ≥35% snaps, ≥2 touches.
- **Participation in BOTH windows** (≥2 games each). A 0.94 delta off a base of zero is
  an *availability* change, not a role change. Without this, a fourth-string receiver who
  played one blowout topped the list.

---

# PART 4 — LEAGUE-SPECIFIC SCORING

**Never use nflverse's `fantasy_points_ppr`.** It hardcodes 1.0/reception and ignores
everything a commissioner can change. Recompute from raw stats against
`league.scoring_settings` — Sleeper returns them, so it is free correctness.

Sub-bug: `fum_lost` mapped to a column that does not exist. nflverse splits fumbles
across rushing/receiving/sacks, so the penalty was **never subtracted** and failed
silently. `STAT_MAP` values can be a list of columns to sum; unmappable rules report in
`pts.attrs["unscored"]`.

*Known residual: QBs diverge from nflverse's column on 44% of rows, mean +0.45. Skill
positions agree on 97-99%. Bounded, not explained.*

Replacement levels for this league: **QB11, RB28, WR28, TE18**.

---

# PART 5 — DEFENSES AND KICKERS

Both are computed from `stats_team` / `stats_player`, scored under **this league's actual
rules** — sacks, INTs, fumble recoveries, defensive and ST touchdowns, safeties, blocked
kicks, points-allowed tiers; FGs by distance bracket for kickers.

All 32 defenses and all 31 kickers are on the board, not just the twelve the market
prices. **A unit with no ADP is not unrankable, it is unpriced** — and unpriced is where
value lives.

**Personnel overrides beat last season's numbers.** The Rams traded for Myles Garrett
(reigning DPOY, record 23 sacks) and Aaron Donald unretired 30 Aug. Their ADP of 108.5
predates the Donald signing by one day.

| Defense | 2025 base | 2026 adj | ADP |
|---|---|---|---|
| **LA Rams** | 7.41 | **9.81** | 114.5 |
| Seattle | 9.53 | 9.53 | 87.9 |

**Floors are mandatory even when the projection is right.** Giving them real projections
put their VOR on the skill-player scale and the planner took the Rams at **pick 49
against an ADP of 114**. The projection was right; the pick was wrong. Scarcity, not
quality, justifies an early pick. **DEF not before round 11, K not before round 13.**

Kickers shrink toward the mean by sample: `(raw*n + 8.4*8)/(n+8)`. A nine-game kicker was
outranking full seasons.

---

# PART 6 — DRAFT LOGIC

### Pick scoring

```
score = VOR × marginal(pos, already_held) × (0.30 + 0.70 × P(gone by next pick))
```

**Scarcity multiplies value, it does not compete with it.** Ranking on value alone
reached for McBride at pick 9 when he survives to 29 in 74% of simulations. A pick spent
on someone who was coming back anyway is wasted however good he is.

**Marginal value** — the Nth player at a position is worth less than the first:

```
fills a starting slot      1.00
competes for a flex        0.62
real bench depth           0.28
roster clutter             0.08
second QB/K/DEF            0.05
```

Absolute VOR is why the planner wanted three tight ends.

**Availability comes from the survival simulation**, not an ADP margin. The crude
`adp > pick − 8` filter let it "take" Jaxon Smith-Njigba at pick 12 when he goes 5.5 on
average — a plan that looked optimal and was unexecutable.

### Must-fill-by rounds

```
QB 12 | RB 8 | WR 8 | TE 13 | DEF 14 | K 15
```

If rounds remaining equals slots unfilled, the pick is **forced**. This is what stops a
draft ending without a kicker because every round had a more exciting option.

Min counts: QB1 RB4 WR5 TE1 K1 DEF1. Max: QB2 RB6 WR7 TE2 K1 DEF1.

### Fallers — measured in POINTS, not picks

A flat pick threshold is wrong in both directions. Points lost per pick of waiting:

| region | RB | WR | DEF |
|---|---|---|---|
| rounds 1-2 | 0.312 | **0.342** | — |
| rounds 3-6 | 0.077 | 0.049 | — |
| rounds 11-15 | 0.032 | 0.118 | **0.061** |

A **5-pick fall in round 1 is worth ~1.7 points**; a **20-pick fall on a defense in round
12 is worth ~1.2**. The old 8-pick threshold rated the second as bigger.

`fall_value = picks_past_adp × local_gradient`, **capped at the position's total spread**:

| RB | WR | TE | QB | DEF | K |
|---|---|---|---|---|---|
| 8.87 | 7.43 | 6.30 | 5.10 | **3.16** | **2.74** |

Without the cap a kicker 20 picks past ADP scored 5.3 points when the whole kicker spread
is 2.7. **Matching a kicker's ADP is not a reason to draft one.**

Threshold: **0.8 points**. Below a 0.09 gradient the position is flat and no fall matters.

**A faller is only taken if it costs nothing.** A bargain at a position I hold five of,
in a round where a starting slot is empty, is a bench player bought with a starter.
Rejected fallers are still *shown*, with the reason — silently filtering them hides the
most interesting decision on the board.

### Positional windows — no fixed opening rule

| pick | RB | WR | favours |
|---|---|---|---|
| 9 | 14.38 | 13.55 | RB +0.83 |
| 12 | 13.94 | 13.48 | RB +0.46 |
| **29** | 11.09 | 11.83 | **WR +0.74** |
| **32** | 11.04 | 11.63 | **WR +0.59** |
| 49 | 10.66 | 9.88 | RB +0.78 |

Forcing openings across 8 seeds, ESPN-scored: **RB-RB 139.1, WR-WR 139.9** (sd ~3 —
indistinguishable), **agent choosing freely 143.3**. Taking whoever is best is worth
about **four points** over either rule, because the advantage alternates. "Always start
RB" banks the round 1-2 edge and misses the round 3-4 one.

### Slot 9 structure

Picks: 9, 12, 29, 32, 49, 52, 69, 72, 89, 92, 109, 112, 129, 132, 149. Gaps alternate
**3 and 17**. You draft in pairs, then 17 players vanish — there is no coming back for
anyone in that band.

### Live adaptation

- **Drift per position** — if receivers go 8 picks ahead of ADP they will keep going
  early. The only read on nine strangers the data allows, and it is about *these* nine.
- **Conditional survival** — drafted players removed, remaining ADPs shifted by drift.

---

# PART 7 — IN-SEASON DECISIONS

### Confidence is 0-100 with cost already deducted

No separate "cost if wrong" column. A claim that costs a roster spot is not "70%
confident with a downside" — it is less than 70.

| move | auto at | charged |
|---|---|---|
| start/sit | **60** | one week of points, reversible until kickoff |
| waiver | **65** | a roster spot, charged against who is dropped |
| drop | **80** | he gets claimed |
| trade | **95** | a comparable player, plus credibility |

**Charges are specific, not flat:**

```
waiver:    drop tops the wire   −18   "much of the gain comes straight back off the board"
           drop is startable    −10
           drop is a bench body  −3
drop:      startable            −22
           widely rostered      −12
trade:     they lose points     −40   they will decline
           lopsided >2.5x       −20   reads as predatory
           they gain more       −15
           near-even             −6
start/sit: <1.5 pts apart       −12
           clear gap             −3
```

The same Lloyd claim scores **78** dropping a bench body and **63** dropping Tuten.

### Conditions must be falsifiable and comparative

"Confidence ≥ 65" restates the confidence. These are predictions that can be scored:

```
[rest of season] MarShawn Lloyd outproduces Jadarian Price from here — that is the
                 trade this claim actually makes
[next week]      his snap share stays above 55%, or this was noise
[rest of season] Derrick Henry outproduces Jaylen Waddle by more than 4.2 a week
```

### Waiver evaluation — three corrections from week 2

**Snap share is the role; team pass attempts are what the role is worth.** I ranked
Malik Washington a strong buy on a 98% snap share, the highest available at any
position. Miami threw **27 attempts** and no passing touchdowns. New Orleans threw
**56**. Ninety-eight percent of 27 is worth less than ninety-one percent of 56, and I
had been ranking on snap share alone.

Week 1 attempts, for reference: NO 56, PIT 41, WAS 34, DAL 34, DEN 28, MIA 27, PHI 25,
SEA 24, MIN 24, CLE 22.

**A handcuff to someone else's starter is worth nothing.** Blake Corum backs up Kyren
Williams — who is on another roster. When Kyren goes down, Corum becomes valuable to
*Kyren's owner*, and I would be bidding against him for a player I already hold.
Contingent value requires holding the starter. Same for Jordan Addison behind Jefferson.

**Stacking two starters from one offence is a phase decision.** Olave and Vele share 52
New Orleans targets. They rise and fall together: higher ceiling, lower floor. That is
right in the playoffs, where an average week loses anyway, and wrong while qualifying,
where the job is banking wins. Penalised 0.9 points per extra stacked starter during
the qualifying phase, zero in the playoffs.

**And usage-above-points still beats points-above-usage.** Harold Fannin played 82% of
Cleveland's snaps for 4.1 points; Mike Gesicki scored 18.8 on 33%. I nearly dropped
Fannin to chase Gesicki — which is the fade profile the backtest says regresses at
−1.02 PPG, against a buy profile worth +0.37.

### Quarterbacks are not receivers — rushing is missing from the model

I ranked three streamers purely on team pass attempts: Shough (NO, 45/gm), Young (CAR,
36), Lock (SEA, 25). Nathan pointed out that **Bryce Young runs a lot**, and rushing
never enters that number.

That is a real hole. A rushing quarterback carries floor no pass-volume figure captures
— yards on scrambles and, more importantly, goal-line touchdowns that a pocket passer
gives to a running back. Team pass attempts is the right lens for a receiver, because a
receiver only eats from that pool. A quarterback eats from two.

**Until this is measured, treat pass volume as necessary and not sufficient for QBs**,
and check rushing attempts before ranking streamers. The fix is to score quarterbacks on
projected passing points plus projected rushing points rather than on team attempts.

### A drop candidate can be an injured starter

When a starter is out multi-week, he is often the correct drop rather than the
worst player on the roster — a QB you cannot start is worth less than a WR6 you can.

Two caveats that decide it:

- **Never drop him before the replacement clears.** At waiver position 7, dropping your
  only quarterback and having both claims fail leaves the slot empty. Drop the fringe
  player for the claim and cut the injured starter next week, once the replacement is
  in hand.
- **Check IR eligibility first.** Two IR slots sit empty. Once Sleeper marks him
  IR-eligible he costs nothing to keep, and a five-week absence still leaves most of
  the season plus the playoff run.

**His trade value is also at its floor while he is out.** A returning starter is worth
more to a desperate manager in week 6 than the streamer who replaced him.

### Claim chaining when you do not hold priority

**Nathan's technique, and my model had it backwards.** `waivers.py` treated two claims
sharing a drop as a bug to be de-duplicated. It is a feature.

When you are not first in the waiver order, rank the players you want and submit a claim
for each — **all pointing at the same drop**. The platform processes them in your stated
order. The first that clears consumes the drop; every later claim then has no valid drop
and fails harmlessly.

You get exactly one player: your highest-ranked one that survived to your turn. The
alternative — a single claim on the name you want most — is a coin flip that returns
nothing when six teams pick ahead of you.

`claims(..., chain=True)` builds the ranked chain. The de-duplication path remains for
the other case: several claims you genuinely want *all* of, where a shared drop really
would break the second.

**Waiver position changes every week under reverse standings, and winning pushes you
down.** After week 1 Nathan was position 1 (last place); after winning week 2 he is
around 7th. Always check the current order before picking a target — a claim on the
most-added player in Sleeper is a lock from position 1 and a wasted slot from position 7.

### Waivers

**Reverse standings** (this league): priority is your inverse record and **cannot be
spent**. Claims are close to free — claim whenever a player clears the bar, propose
several a week. Only real cost is the roster spot.

Under *rolling* priority it inverts: one claim a week, hoard position.

`drop_score` is not "lowest projection". A low-scoring backup behind your RB1 is
insurance; a mid-scoring fifth receiver is not. Scarcity multiplier 2.5 inside the
starting requirement, bye-cover bonus for the next man.

**Each drop can only be spent once.** Two claims naming the same drop look fine
individually and break if both clear.

### Trades must pass TWO tests, not one

**Correction, week 2.** The seven gates below decide whether a trade helps *me*.
They say nothing about whether anyone will **accept** it, and I conflated those.

My numbers said Waddle-for-Derrick-Henry gained 5.74 points a week, so I proposed it.
In week 1 Henry scored **35.3** and Waddle scored **1.2**. No manager trades the 35 for
the 1 in September. That offer is declined in seconds and costs standing for the next
one.

**Perceived value is modelled separately** (`perception.py`), on what managers actually
look at:

| input | weight, week 2 | why |
|---|---|---|
| **Recent performance** | **60%** | Early on it is nearly all anyone has seen |
| Projection + draft capital | 40% | ADP anchors, especially for a player they drafted |
| Situation | ±2 pts | QB quality, offence, injuries read as narrative |

Recency weight decays — 60% through week 2, 50% to week 4, 38% to week 8, 28% after.
By week 8 a manager has enough games that one outlier stops defining a player.

**The gap between perceived and projected IS the edge.** Week 2 read:

| player | wk1 | my proj | perceived | gap | |
|---|---|---|---|---|---|
| Kenneth Walker | 34.1 | 11.19 | 26.70 | **+15.5** | SELL |
| Derrick Henry | 35.3 | 15.89 | 28.54 | **+12.7** | SELL |
| Chris Olave | 28.2 | 12.22 | 22.90 | **+10.7** | SELL |
| Javonte Williams | 24.2 | 11.29 | 20.42 | +9.1 | SELL |
| Jordan Addison | 0.0 | 8.95 | 3.58 | **−5.4** | BUY |
| Jaylen Waddle | 1.2 | 10.15 | 6.18 | **−4.0** | BUY |
| George Pickens | 5.8 | 14.15 | 10.19 | −4.0 | BUY |

This is the fade asymmetry from Part 3 expressed as a negotiating position. A manager
overvaluing a 35-point week is the same phenomenon as points outrunning usage
regressing at −1.02 PPG. **Sell the spike, buy the slump.**

**A trade is only sent if it passes both:** my lineup gain ≥ 1.5 points AND perceived
value within 1.5 points of even in their favour. Slightly against me is fine — managers
accept small losses for positional need. Two points against *them* reads as predatory.

### The seven gates — do they help me

| gate | threshold | why |
|---|---|---|
| my starting gain | ≥ 2.0/wk | 1/wk is inside projection noise |
| **their** starting gain | ≥ 0.75/wk | they must improve or they decline |
| gain ratio | ≤ 2.5× | lopsided reads as predatory |
| playoff gain | ≥ 0 | helps in October, hurts in December = fail |
| top-player share | ≤ 28% | consolidation makes one injury fatal |
| position depth after | ≥ 1 spare | do not strip a position |
| roster size | legal | 2-for-1 needs a spot |

Built on **two** numbers, not one. Bench points do not score, and a trade the other
manager will not accept is not a trade.

Confidence from **margin above** each gate: 40% my gain, 25% theirs, 25% how evenly it
splits, 10% playoff impact. **Non-monotonic in my own gain on purpose** — an 8-vs-2 trade
scores *below* a 5-vs-4, because a lopsided offer gets declined and costs standing.

Throttle: **one proposal per week, 14-day cooldown per manager.** Search is 1-for-1 and
2-for-1 only — deeper searches find "approved" trades by mining projection noise.

### Lineups

Exact max-weight assignment (Hungarian). Greedy fills lose points on flex — the best
remaining player in FLEX can strand a WR-only slot.

- **Incumbency tie-break** so a stable roster produces zero writes.
- **Diff on slot TYPE, not label.** RB1/RB2 are an artefact of numbering; Sleeper does
  not distinguish them.
- Baseline is the lineup **as set on Sleeper**, never a fresh optimum — optimising the
  baseline benches injured players for you, so the Sunday sweep compares optimal to
  optimal and silently never fires.

### Matchups

Points allowed per game by defense by position, shrunk toward the mean by games. Spread
is decision-sized: **15.6 pts/gm** between the most and least generous defense against
receivers, 11.4 against backs.

Two cautions: partly a schedule artefact, so weighted as one input; and it describes last
season, so personnel moves invalidate it.

---

# PART 8 — DASHBOARD, TAB BY TAB

### Draft
All 8 turn-picks with **survival probability from 20,000 simulated drafts**, plus the
full 15-round plan. Shows the pairing structure and the 17-pick drought. Percentages are
filtered to the 15-97% band: a player who certainly survives is not a decision, and one
who certainly does not is not an option.

### Rankings
196 players. **ALL** shows the ranked board in tiers. **Drilling into a position** adds
every other player at that position on an NFL roster — 772 fantasy-relevant players,
grouped by team, depth-chart ordered. Unranked means *unpriced*, not irrelevant; it is
where waiver claims come from.

Opens with **biggest movers since last refresh**. Every card shows ▲/▼ against the prior
snapshot.

**Player drawer:** photo, number, team, bye, six headline numbers, plain-English
reasoning (ensemble components, source disagreement, durability, VOR, tier logic),
week-by-week bars for 2024-25 with exact points on hover, a career table for older
seasons, and cross-links to any player named in a note.

### Pending
Confidence bar is **absolute 0-100** with the threshold as a marker on that scale. It was
scaled *to* the threshold, so 73 against a 60 bar filled the track and every approved
move looked identical.

Each card: what is charged, the matchup, and falsifiable conditions with resolve dates.

### Team
Roster with per-position depth against what the lineup demands. Empty until the draft —
Sleeper returns zero players pre-draft, and it says so rather than inventing data.

### League
Weekly matchups and positional strength. **Sleeper does not generate the schedule until
the draft completes** — verified by querying weeks 1, 2, 3 and 15, all empty.

### News
Six categories: **injury · roster move · projection · matchup · calendar · preseason**.

Starred = touches my roster, my opponent, or a team I face. **Relevance counts the
beneficiary**, not just the named player — Jacobs is a story about my roster because
Lloyd is on it.

Items with no takeaway stay in the feed, unstarred. Filtering them means the feed only
contains what I already decided was actionable.

**Preseason is labelled weak evidence.** All 33 games are real, but starters played a
series or two. It is evidence about availability and first-team snaps, not quality.

### Weekly game-log annotation

**Anomalies, not metric changes.** A week is annotated only if scoring departed from the
player's own average by **1.2 SD AND 4 fantasy points** — one without the other flags
noise.

**Causes must point the same direction as the anomaly.** A 12-point-above week explained
by "played fewer snaps" is a contradiction. Suppressive causes explain bad weeks only; a
good week on reduced snaps reads "efficiency, not volume".

**Facts, not conclusions.** `2 touchdowns`, not `2 touchdowns — the least repeatable part
of a big week`. The reader infers.

**When nothing explains it, say so:** "usage normal". Most single-week swings are
touchdown variance — real, invisible in usage, non-repeating.

---

# PART 9 — REFRESH CADENCE

13 refresh windows a week, 7 decision windows.

- **Daily 07:00 ET** — all sources, board rebuilt, news re-gated.
- **T-minus-60 on every deadline** — waiver lock, TNF, Sun early, Sun late, SNF, MNF.

T-60 matters more than the daily: data pulled at 07:00 is eight hours stale by a 15:00
waiver lock, and **stale data at a deadline is worse than no data because it looks
current**.

**Sunday 11:30 inactive sweep is the highest-value job in the system.** A starter ruled
out at 11:45 and replaced by 12:55 is worth more than every other automation combined.

DST is handled through the IANA zone, not a fixed offset — ET is UTC-4 in September and
UTC-5 in December, and a hardcoded offset slips an hour on the first Sunday in November,
inside the playoff push.

`refresh_all` proposes nothing. A refresh that also decides is not one you can run
unattended at 6am.

---

# PART 10 — DATA SOURCES

| Source | Unique contribution |
|---|---|
| **pbp_participation** | On-field personnel per play → route rate, TPRR. Strongest signal |
| stats_player / stats_team | Box score, target share, team defence |
| snap_counts | Snap share |
| **injuries** | Practice participation — the only source that *leads* the box score |
| pfr_advstats/rush | Yards before/after contact — separates back from line |
| ftn_charting | Motion, play action, screens, drops |
| players.parquet | gsis ↔ pfr ↔ espn crosswalk. **Nothing joins without it** |
| **espn_projections** | 2026 per-week projections, draft ranks, byes. Only forward-looking source |
| espn_odds | Over/under and spread, free, no key |
| espn_news | Breaking news |
| ffc_adp | Market ADP with per-player variance |
| sleeper_trending | What the market is claiming now |
| weather | Wind >15mph craters passing |

**Source weights shift with league setup.** In PPR, receptions are the currency so target
share carries the projection. In standard, touchdowns dominate and reception-heavy
signals mislead. Superflex makes QB scoring track the game total, so Vegas matters more.

**Learned weights** replace backtested ones per source after 25+ scored outcomes.
Weighting on five observations is how you confidently trust noise.

---

# PART 11 — TRAPS THAT HAVE ALREADY COST TIME

1. **FFC's `teams=` parameter is ignored.** `teams=10` and `teams=12` return
   byte-identical payloads from the same 8,161 drafts. ADP is blended-format.
2. **nflverse codes the Rams `LA`, not `LAR`.** A lookup keyed on LAR silently misses —
   the one verified personnel change in the project did not apply and nothing errored.
3. **Sleeper name-matching needs a position guard.** "Josh Allen" matches an offensive
   guard before the Bills QB; "Kenneth Walker" a WR before the RB.
4. **`offense_pct` is a fraction (0.86), not a percentage.** Printed with a % sign it
   produced "0% of snaps vs 1% typical" for a player taking 86%.
5. **Injury reports miss IR entirely.** Durability must be built on games played.
6. **Route rate must divide by dropbacks in games PLAYED**, not the season. Dividing by
   the season put Tyreek Hill at 13% when the truth was 56% and he had been injured —
   role and availability conflated.
7. **Any file written once and read forever goes stale silently.** A pre-baked
   `dashboard.json` re-rendered an 88-player board for hours while appearing to update.
8. **Never copy `dashboard.html` over `dash_template.html`.** The template ended up with
   two of everything; a duplicate `const` killed every handler on the page.
9. **A patch anchor matching twice lands in the wrong place.** Removing a block by string
   search deleted the legitimate copy and left the broken one.
10. **Timestamps need microseconds.** Snapshots keyed on date meant the second refresh of
    a day overwrote the first and movement was always blank.
11. **Points-allowed must count every scoring source** — FGs, XPs, 2-pointers, defensive
    and ST scores. Summing only offensive TDs mis-tiers most weeks.
12. **`run.py` calling the superseded dashboard generator** would have silently
    overwritten the working dashboard on the first scheduled run.

---

# PART 12 — HONEST LIMITS

- **Zero 2026 games played.** Signal confidence 0.25 until week 1.
- **ADP snapshot is 31 Aug.** Re-pull the morning of the draft.
- **QB scoring diverges** from nflverse on 44% of rows, mean +0.45. Bounded, unexplained.
- **Route-rate 0.918** is one season, WR/TE only, n=178.
- **Only the Rams defense is personnel-verified**; others sit at market.
- **Game logs cover 53/59 players, career 39/59** — name matching, needs an ID join.
- **2026 in-season schedule unpublished**, so `matchups.schedule()` is empty.
- **`write.py` has never executed a click.** Addressing solved, interaction unproven.
- **No read on the nine managers.** Largest available edge; no data buys it.
- **Mock-draft grade (1st in 6 of 6, +12.7) is against bots** that cannot trade or reach
  for a player they like. Real managers do both.
