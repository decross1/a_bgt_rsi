# The research planning layer — the Docket

**Status:** DRAFT, awaiting owner ratification (would become D-077).
**Author:** primary session, 2026-08-19. **Supersedes:** nothing.
**Measured against live state at 2026-08-19T04:09Z** (commit `9cc9287`).

---

## The answer first

Your intuition is right and the thing you named is genuinely missing. But
the measurements say the cause is not what it looks like, and the fix you
described — a morning "what have I got going on" ritual — would not have
worked, because **there is nothing on the menu Nara could have chosen
instead.**

Three numbers carry the whole document:

- In **322 coordinator cycles over 71 days**, Nara has never once planned
  `run_experiment`, `refine_idea`, `mine_paper_gap`, or `forecast_markets`.
  Four of the eight menu actions have zero lifetime uses.
- Of the **20 open clusters, 0 are advanceable by any action Nara can
  take today.** Only 5 are even eligible for experiment construction; of
  those, 1 reaches a built experiment, and that one is L0 and owes a
  literature pass, not an experiment.
- **13 of the 20 open clusters are blocked on one thing:** the critic
  returning `undecidable`. On 2026-08-18 the critic returned `undecidable`
  14 times and `survives` once. **55 of the last 58 loop iterations ran
  the same topic string** — three distinct topics in five days.

So the loop is not choosing ideation over follow-up. It is choosing the
only action that exists, over and over, on the only topic it has, and the
work it produces is dying at one gate. The "ideation vs. follow-up"
framing describes the symptom correctly and the mechanism wrongly.

The second correction matters for what we build. You asked for compaction
because loop_memory is 3.5 MB. **The planner never sees loop_memory.** The
state blob Nara plans against is 4,414 bytes — about 1,100 tokens — and
most of it is counts with no nouns in them. The planner is starving, not
drowning. The layer to build is not a summarizer; it is a *router* that
converts counts into named, pre-validated, executable next actions, and
that refuses to invent one when none exists.

That refusal is the load-bearing part. On today's state the Docket's list
for Nara is nearly empty, and its list for you is not. That is the finding,
not a bug.

---

## 1. The diagnosis

### 1.1 The funnel, measured

Reduced from `memory/idea_ledger.jsonl` (329 events, 132 clusters):

| | count |
| --- | --- |
| clusters total | 132 |
| open | 20 (18 L0, 2 L1) |
| killed | 112 |
| — `redteam_fatal_flaw` | 89 |
| — `paper_prior_exists` | 15 |
| — `experiment_null_effect` | 3 |
| — `superseded_duplicate` | 3 |
| — `non_research_artifact` | 2 |
| lifetime `evidence_level_changed` events | **9** |

130 clusters created; nine rung changes ever, two of which were
*demotions*. That is the funnel: it is a chute, not a ladder.

All 89 `redteam_fatal_flaw` kills predate the D-076 prompt swap
(2026-08-18) — i.e. they were made by the instrument the R1a battery
measured condemning 18 of 19 parsed fixtures, including 6 of 7 parsed
known-*good* claims. The 08-19 session note already opened that as its own
lane (a paired re-adjudication battery). This document does not touch it,
but it is why "112 killed" should not be read as 112 bad ideas.

### 1.2 The two stranded L1s are real, and worse than reported

`cl-iter-2026-08-16-003` has sat at L1 for **3.4 days**;
`cl-iter-2026-08-17-014` for **2.3 days**.

A note on that measurement, because the existing board gets it wrong.
`memory/ideas.md` reports "last touched" from `last_event_ts`, which is
refreshed by consolidation and dedup-relink events that carry no
scientific content. `cl-iter-2026-05-26-001` renders as touched 0.8 days
ago; its only non-creation event was a `d075_r4_dup_relink` on 08-18. Time
*at rung* — measured from the last `evidence_level_changed`, or
`cluster_created` when there is none — is the honest signal, and the
existing board does not compute it. The Docket does.

### 1.3 Why they are stranded — measured twice, because the first measurement was wrong

I ran `thesis_to_experiment.dispatch()` on every open cluster, with claims
resolved through `refine_cycle.resolve_claim` against the live 3.65 MB
loop_memory. My first pass held novelty and critic fixed at
`("novel", "survives")` and measured only whether the *claim text* matches
a game:

| text routing outcome | clusters | experiment |
| --- | --- | --- |
| built experiment | 2 | `exp001_repeated_pd` |
| game matched, **not built** | 7 | `stag_hunt` |
| game matched, **not built** | 2 | `public_goods` |
| **no keyword match at all** | 9 | — |

That table is real but it is not the answer, and I nearly shipped a
recommendation built on it. `dispatch()` is gated by
`thesis_to_experiment.is_eligible`, which requires the critic verdict to be
**exactly** `"survives"`. Re-run with each cluster's *actual* novelty and
critic values:

| | clusters |
| --- | --- |
| eligible for construction at all | **5 / 20** |
| of those, `dispatch()` returns a spec | **3 / 20** |
| of those, spec names a **built** experiment | **1 / 20** (`cl-iter-2026-05-26-008` → `exp001_repeated_pd`) |
| — and that one is L0, so its owed test is not an experiment | |
| **advanceable by `run_experiment` today** | **0 / 20** |

So building `stag_hunt` would unblock **one** cluster
(`cl-iter-2026-06-05-002`), not seven. The other six that matched the text
are barred upstream by their critic verdict and would not reach the new
instrument.

I am reporting my own error because it is the exact failure mode the
design's `validate_plan` interlock (§3.5 step 4) exists to prevent:
assuming an action is available because the noun matched, without checking
that the gate would pass. A ranking layer without that interlock would have
handed you the seven-cluster recommendation, and you would have built the
wrong experiment.

Both L1 clusters *are* eligible — and `dispatch()` still returns `None` for
both. Their claims are delegation-graph and spectral-gap propositions in
liquid democracy; the routing table covers six classical games (repeated
PD, public goods, stag hunt, Cournot, Vickrey, combinatorial VCG) and has
no row for them.

The ladder is writing a check the action menu cannot cash. Nara's
preference for ideation is not a judgment error; it is the only edge out
of the current node.

### 1.4 The real clog: the critic returns `undecidable` on 13 of 20 open clusters

Running `derive_level(...)["missing_for_next"]` over every open cluster
gives the blocker frequency the existing board never computes:

| blocker | clusters |
| --- | --- |
| **`critique.verdict='undecidable'` (need `'survives'`)** | **13** |
| `retrieval.relevance is low_confidence` | 4 |
| `novelty.class='unclear'` | 4 |
| `retrieval.relevance absent` | 3 |
| `redteam.verdict=fatal_flaw` (hard cap below L1) | 2 |
| `experiment_outcome absent` (the two L1s) | 2 |
| other (absent / `rediscovery` / `restated`) | 4 |

`undecidable` fails closed everywhere downstream — the L1 rung, and
`is_eligible` by construction. It is the single largest reason the funnel
does not move, and it is getting worse:

| iteration date | undecidable | survives | restated |
| --- | --- | --- | --- |
| 2026-08-15 | 2 | 5 | 1 |
| 2026-08-16 | 14 | 5 | — |
| 2026-08-17 | 9 | 11 | 2 |
| **2026-08-18** | **14** | **1** | — |
| 2026-08-19 (partial) | 1 | — | 1 |

Lifetime: 59 `undecidable` vs 67 `survives` across 167 iterations — but 40
vs 22 in the last five days, and 14-vs-1 on 08-18.

This is the same shape as the defect R1a just measured in the redteam: an
instrument that has stopped discriminating and now returns one answer.
D-076 fixed the redteam by battery; nothing has been run on the critic.
`workers/critic_loop_v0.py` maps debate `round_cap`/`converged` outcomes to
`undecidable` as "legitimate uncertainty", and the D-075 debate changes
(6 rounds, refuted mapping) landed on 08-18 — the day the rate hit 93%.
**That is a hypothesis, not a finding**, and it is exactly the kind of
thing that should be measured rather than assumed. It is the top item on
the Docket's owner queue in §3.7.

Nobody noticed this for four days. A daily digest that ranks blockers by
frequency would have printed it on 08-16.

### 1.5 The routing table is also stale

Three experiments — `exp010_audit_collusion`, `exp011_matching_reconstruction`,
`exp012_lqg_spectral` — are built, have `loop_bridge.py`, and are
registered in `tier_registry`. None of them appear in the routing table.
So even where the apparatus *has* an instrument, `dispatch()` cannot find
it.

### 1.6 The pipeline does work — when a human builds the experiment

This is the most important positive finding, and it is why I am not
proposing to rebuild the loop.

Under `experiments/PREREG_l2block_2026-08-17.md`, a primary session built
those three experiments specifically to test three stranded L1 claims. All
three ran. All three produced honest null results. All three clusters were
closed with `experiment_null_effect` (`cl-iter-2026-07-13-001` at 120
trials, `cl-iter-2026-07-15-001` at 40, `cl-iter-2026-08-15-002` at 420).

That is the pipeline working end to end — hypothesis, instrument,
measurement, honest negative, ledger close. **Every rung advance past L1
in the apparatus's history came from a human dev session building a
bespoke experiment.** Zero came from a coordinator action.

So the missing step is not "Nara should think about its priorities in the
morning." It is: *the apparatus has no channel by which Nara tells the
owner which experiment to build next.* The escalation exists as an action
(`bubble_up`, cost 1) and has been used **once in five days**.

### 1.7 The ideation is degenerate, which nobody had noticed

58 loop iterations since 08-15, across **3 distinct topics**:

| runs | topic |
| --- | --- |
| 55 | Representation in Peer Selection: A Liquid Democracy Perspective |
| 2 | Joint Communication-Control Strategy Optimization… |
| 1 | Power in Liquid Democracy: A Network Centrality Approach |

This is the real engine behind the funnel numbers. The lab is not
exploring an idea space; it is re-deriving one topic fifty-five times,
minting near-duplicate L0 clusters, which the redteam then kills. It also
explains the three `superseded_duplicate` kills and the 08-18 duplicate
refill that D-075 R4 had to clean up.

`mine_paper_gap` — cost 1, explicitly built to propose a fresh deduped
topic when the suggestion queue is thin — has **never been used**.

### 1.8 A quarter of the daily budget is structurally unspendable

Live at 04:09Z today: 6 of 60 units spent, all six in ideation.

| class | share | spent | reachable? |
| --- | --- | --- | --- |
| ideation | 24 | 6 | yes |
| research | 21 | 0 | only via `promote_findings` / `bubble_up` |
| system | 9 | 0 | **no** — its only action `improve_system` is dark (`NARA_SELF_IMPROVE` unset in `systemd/nara-daemon.service`) |
| sdlc | 6 | 0 | **no** — no action maps to `sdlc` in `ACTIVITY_CLASS_OF` |

15 of 60 units per day cannot be spent by construction. Meanwhile
`promote_findings` has run 136 times lifetime for 26 promotions, and **0
promotions in the last 16 attempts**.

### 1.9 Unconsumed queues

Work has already been produced that nothing reads:

- `memory/frontier_agenda.jsonl` — **14 proposals, all `proposed`, zero
  consumed.** These are distilled from real frontier vetoes and name the
  exact missing controls.
- `memory/design_constraints.jsonl` — 112 rows, all `active`, no consumer.
- 6 iterations pending a human gate verdict
  (`iter-2026-08-18-012..015`, `iter-2026-08-19-001..002`).
- `memory/ideas.md` is a day stale (written 08-18T04:00) and lists four
  clusters that have since been killed.

### 1.10 Verdict on the observation

**Confirmed, with a corrected mechanism.** There is no reconciliation step,
and its absence is costing real work — measurably, in the form of an
instrument that has been failing 13 of 20 open clusters for four days
without anyone noticing.

But adding a ranking ritual on top of today's action menu would have
produced a ranked list of things Nara cannot do. The missing step is not a
prioritizer. It is a **router with an escalation channel**: something that
classifies every open item by whether any action can actually move it,
aggregates the ones that cannot by *cause*, and hands the biggest cause to
the person who can fix it. Its first output is not a plan for Nara. It is
a work order addressed to you.

---

## 2. What real researchers do

I looked for the structure, and separated what is empirically supported
from what is well-attested tradition. The distinction changes the design.

### 2.1 Evidence-backed

**Making the plan is what discharges the load — not finishing the work.**
Masicampo & Baumeister, *Consider It Done!* (J. Pers. Soc. Psych.
101(4):667–683, 2011): unfulfilled goals produce intrusive thoughts and
measurably degrade performance on *unrelated* tasks; allowing participants
to write a specific plan eliminated the interference **without the goal
being completed**. Gollwitzer & Sheeran (2006), meta-analysis over 94
tests / >8,000 participants, finds implementation intentions ("if X, then
Y") yield *d* = .65 on goal attainment — and lists *disengagement from
failing courses of action* among the mechanisms.

→ *Design consequence:* the value of the Docket is in every open cluster
carrying a written, specific next action — including "this is parked, and
here is what would unpark it." Closure is not required. This is the
warrant for naming blockers rather than hiding them.

**The daily ritual is not supported. The periodic one is.** Helen Sword,
*Write every day! A mantra dismantled* (Int. J. Academic Development,
2016): 100 interviews with peer-nominated exemplary academic writers
across 45 universities, plus 1,223 questionnaires. Only 12.8% of the
hand-picked exemplars write daily; "roughly seven out of eight academics
surveyed do not write every day; daily writing turns out to be neither a
reliable marker nor a clear predictor of overall academic success."

→ *Design consequence:* no daily standup. Build the board, run the
reconciliation weekly.

**Independent confirmation from inside a research org.** CECAN Scrum
adaptation study (Heliyon, 2019; 17 researcher interviews + participant
observation): the Kanban stage board survived; "daily standups and
retrospectives were not routinely followed," and fixed sprints were
rejected as "arbitrary" for research work.

→ *Design consequence:* the *board* generalizes to research; the
*fixed-length iteration ceremony* does not. Hence: a docket, not a
standup.

### 2.2 Prescriptive tradition — well-attested, not experimentally tested

These are canonical and operationally precise. They are not evidence. I
mark them as such and use them for *shape*, not justification.

- **GTD's threefold model of daily work** partitions time into (1) doing
  pre-defined work, (2) doing work as it appears, (3) **defining work**.
  Nara does (1) and (2) and has no allocation for (3). That is your
  observation in canonical form.
- **The four criteria for choosing in the moment, in this order:**
  context, time, energy, **priority last** — because the first three are
  feasibility filters and priority only breaks ties among what is
  *actually runnable now*. This is exactly the Docket's decision rule:
  routability gates first, ranking second.
- **GTD's Horizons of Focus** — actions / projects / areas of
  accountability (hard cap 4–7) / 1–2 yr goals / 3–5 yr vision — reviewed
  at *decreasing* frequency: actions daily, projects weekly, upper
  horizons "certainly not weekly, between quarterly and annually." Maps
  one-to-one onto your week/month/quarter/year ask.
- **The weekly review** (Talbert, *Intentional Academia*): 1–2 hrs,
  Sunday, three phases — get clear, get current, get creative. The
  load-bearing invariant is in phase 2: *every active project is verified
  to have a defined next action.* An active project without one is a
  defect the review catches.
- **The PI 1-1 agenda** (Wallace Lab handbook, Univ. of Edinburgh):
  fortnightly, 55 min, three steps — (1) progress on agreed priorities and
  action points from last time, (2) review the notebook/data, (3)
  **establish 1–3 priorities for the next fortnight.** That is literally
  your four-part morning question, with a hard cap of 1–3.
- **The weekly research report** (Soto-Valero, KTH): DONE (past-tense
  verb + link to artifact), TODO (**max 3**, infinitive verb, each
  yielding one deliverable artifact), QUESTIONS (**max 3**, yes/no
  answerable). The caps force triage instead of enumeration — which is
  precisely what a 132-cluster ledger needs.
- **The lab notebook** (NIH ELN guidance) is *not* a planning instrument.
  It is the complete append-only evidentiary record — "all data goes into
  the notebook, even bad data points, failed experiments." Its fixed
  schema ends with **"interpretations, conclusion, next steps"** and
  "ideas for future experiments." The notebook does not plan; it *emits*
  the planning input, and the weekly review harvests it.

### 2.3 What transfers

| practice | Nara today | verdict |
| --- | --- | --- |
| append-only notebook ending in "next steps" | `loop_memory.jsonl`, `idea_ledger.jsonl` | **have it** |
| per-project stage board | `memory/ideas.md`, `/api/lab_todo` | **have it, illegible** (§1.2, §1.9) |
| weekly reconciliation: every active project has exactly one defined next action | — | **missing** |
| horizon stack reviewed at decreasing frequency | — | **missing** |
| explicit ~10% "what are the important problems?" slot (Hamming) | `sdlc` share exists at 6 units/day and is unreachable | **missing, budget already reserved** |
| escalation to the PI with 1–3 priorities | `bubble_up`, used 1× in 5 days | **have it, unused** |

The apparatus already has the notebook and the board. It is missing the
reconciliation and the horizons. That is what this builds.

---

## 3. The design

**The Docket:** a deterministic, zero-LLM daily digest that classifies
every open cluster by whether any action can actually advance it, ranks
the ones that can, and routes the ones that cannot to the owner as a named
build request.

It is a router, not a prioritizer. Named a docket, not a standup,
deliberately (§2.1: the board survives, the ceremony does not).

### 3.1 Three choices, defended

**(a) It escalates as an *action*, not as a field in a file.** The
diagnosis says every rung advance ever came from a human dev session
building or repairing an instrument (§1.6). A blocked-items array in a
JSON file would be the fifth board nobody reads. So when the Docket finds
a bottleneck only a dev session can clear, it emits a `bubble_up` — an
existing menu action, cost 1, that already lands in the cockpit you are
test-driving. The escalation is a first-class plan item that costs budget
and gets logged, or it is nothing.

**(b) It does not build a new board.** `memory/ideas.md` and
`GET /api/lab_todo` already render the cluster board; `lab_todo` already
returns `{owed, agenda, refine_candidates}` keyed by cluster. The genuinely
new information is *claim text* and *routability*. Those become a fix to
`workers/idea_projection._stem` and two extra fields on the existing
`lab_todo` payload. The only new file is the dated digest itself.

**(c) It refuses to pad.** If nothing is advanceable, `today` is empty and
says why. An unroutable cluster is never recoded as "owed and pending" —
that is inviolate rule 4 applied to planning.

### 3.2 The artifact

`run_state/docket/YYYY-MM-DD.json`, with `run_state/docket/today.md`
rendered beside it. Date-stamped, never rewritten; staleness is visible in
the filename.

```
date, generated_at
generator: "docket/deterministic"     # literal marker: no model wrote this
ledger_hash                           # sha8 over ledger size+mtime — staleness interlock

counts: {clusters, open, killed, by_level, by_kill_code,
         advanceable, blocked, human_owed}

pipeline: {routed_built, routed_unbuilt: {game: n}, unrouted,
           topic_concentration: {distinct, top_topic, top_share},
           budget: {spent, cap, by_class}, unspendable_units}

today: [ ≤3 ]                         # Nara's list. advanceable only. never padded.
  cluster_id | claim (≤200 chars) | level | days_at_rung
  missing_for_next: [...]             # the SPECIFIC list from derive_level
  action, args                        # pre-resolved AND pre-validated
  why: str

owner_queue: [ ≤4 ]                   # your list. ranked by clusters unblocked.
  kind: build_experiment | verdict | disposition | consume_queue
  ask: str
  unblocks: [cluster_id]
  evidence: str
  options: [...]                      # disposition asks state options before you decide

horizons: {week, month, quarter, year, last_edited, stale}   # verbatim from human/horizons.md
```

Per-cluster classification carries `routing: {status, action, args,
matched_game, experiment_id, built}` and, when blocked, a concrete
`blocker` string — never a generic one.

### 3.3 The writer, and the schedule

`orchestrator/docket.py`, ~200 lines, no LLM calls (asserted in test).
Called **build-if-absent at the top of `coordinator_cycle()`**, so the
day's first cron cycle builds it. **No new cron entry, no new daemon, no
new process.** Also `python -m orchestrator.docket --today
[--dry-run|--pin ID|--defer ID]` for you.

Weekly reconciliation rides the **existing** Sunday 05:30 cron
(`cron/weekly-frontier-agenda.sh`) — one added line that writes
`run_state/docket/week-YYYY-Www.md`. No new schedule.

One run-log row per build, `agent: "docket"` (inviolate rule 6).

### 3.4 The readers

1. **The coordinator planner** — one new field on `assess_state()`, one
   paragraph in `_planner_system_prompt`. Gated on `NARA_DOCKET_PLAN`.
2. **You** — `today.md` and the CLI.
3. **The cockpit** — two extra fields on the existing `/api/lab_todo`
   payload plus a docket strip. Per CLAUDE.md §Dynamic Workflow discipline
   rule 2, this ships as a **spec in the session note's UI work order**,
   not as code from the primary session.

### 3.5 The decision rule

**Classify** each open cluster, deterministically:

1. Resolve the claim via `refine_cycle.resolve_claim`. Unresolvable →
   `blocked/claim_unresolvable`. Nara is never handed a claim it cannot read.
2. Derive the owed test from `derive_level(...)["missing_for_next"]` — the
   specific list, not the generic per-rung string the projection currently
   substitutes.
3. Resolve the owed test to a concrete action + args:
   - L1 owing an experiment → `thesis_to_experiment.dispatch()`.
     Hit with a **built** experiment → `run_experiment{tier, experiment_id}`
     via `tier_registry.get_experiment`. Hit with `experiment_id: None` →
     `blocked/experiment_not_built`, carrying the game name (this is the
     branch that would have crashed on 9 of 20 clusters). `None` →
     `blocked/no_synthetic_construction`.
   - killed near-miss whose `reopening_condition.evidence_kind ==
     "articulated_delta"` → `refine_idea{cluster_id}`.
   - owed test is a human verdict → `human_owed`, excluded from `today`,
     counted, and surfaced in `owner_queue`.
4. **Interlock:** run `coordinator_actions.validate_plan([{action,args}],
   budget=99)` on the candidate. If it does not validate, it is `blocked`,
   not `advanceable`. The planner is structurally incapable of receiving an
   unexecutable priority.

**Rank** the advanceable, lexicographically, no LLM:

1. `level` descending — advance what is furthest along.
2. `days_at_rung` descending — anti-starvation, computed from the last
   `evidence_level_changed` (§1.2), not `last_event_ts`.
3. `cluster_id` ascending — byte-stable tiebreak.

Take **top 3**. The cap is 3 because the PI 1-1 template says 1–3 and the
weekly-report template says max 3; the cap is the point (§2.2).
`NARA_DOCKET_CAP` overrides.

**Aggregate the blocked by cause, then rank.** This is the step that does
the real compaction, and it is why the worked example fits on one screen:
13 clusters sharing `critic_undecidable` become **one** owner-queue item
carrying its cluster list, not 13 items. A blocker shared by many clusters
is one problem, and reporting it 13 times is how a digest becomes a wall.

**Rank the owner queue** by `len(unblocks)` descending, then by
`max(days_at_rung)`. Cap 4. Because the ranking key is the number of
clusters a single fix would free, the queue automatically surfaces
instrument defects — which is how the critic finding in §1.4 reaches the
top without anyone having taught the Docket what a critic is.

**What it drives.** `assess_state()` gains one field, `docket`. One
planner paragraph, verbatim:

> The docket's `today` list is the day's priorities. Each carries a
> pre-resolved, pre-validated action and args — prefer one of these over
> minting a new idea. When `today` is empty, that is a real finding:
> nothing on the ladder is advanceable, and ideation or a `bubble_up` from
> `owner_queue` is the correct choice. When `today` is non-empty and you
> plan `run_loop_iteration` anyway, state why in the plan reason.

It never forbids ideation. It makes choosing ideation over a ready item an
explicit, logged act.

### 3.6 How it compacts state for a 26B context

The premise needs correcting before the answer (§0): the planner's state
blob is **4,414 bytes / ~1,100 tokens**. It has never been near a context
limit. `loop_memory.jsonl` (3.65 MB) is *never* loaded into the planner.

So the compaction rule is not summarization. It is **bounded projection**:

- The digest is **O(1) in context regardless of ledger size** — at most 3
  Nara items, 4 owner items, one counts block, four horizon lines. 132
  clusters and 1,320 clusters produce the same-size digest. Growth shows
  up in the counts, never in the token cost.
- **Claims are joined by id, not scanned.** loop_memory is opened, the ≤7
  needed member ids are looked up, ≤200 chars each are kept, the file is
  closed. Peak added context: ~1.4 KB / ~350 tokens.
- **Counts stay counts; nouns get names.** The existing gap strings ("2
  open cluster(s) at L1 awaiting…") stay for the aggregate picture; the
  Docket adds the specific ids and claims for exactly the items it wants
  acted on.
- **Blockers collapse by cause.** 20 clusters reduce to ~6 distinct
  blockers; the digest carries the 6, each with its cluster list. This is
  the difference between a digest and a dump, and it is what keeps the
  artifact O(1) as the ledger grows.
- **Ranking is arithmetic, done outside the model.** The 26B model is
  never asked to sort 20 clusters — it is handed 3 and asked to pick.

Net: `assess_state` goes from ~4.4 KB to ~5.8 KB, and the informative
fraction goes up by much more than the size.

### 3.7 Worked example — what `run_state/docket/2026-08-20.md` would literally say

Generated from today's real state. This is not illustrative; it is the
output of the decision rule in §3.5 run against the live ledger.

```
# Docket — 2026-08-20            generator: docket/deterministic
ledger: 132 clusters · 20 open (18 L0, 2 L1) · 112 killed
        kills: redteam_fatal_flaw 89 · paper_prior_exists 15 ·
               experiment_null_effect 3 · superseded_duplicate 3 ·
               non_research_artifact 2
budget: 6/60 spent — ideation 6/24 · research 0/21 · system 0/9 (dark)
        · sdlc 0/6 (no action mapped).  15 units/day unspendable.

BLOCKERS  (open clusters, by frequency — derive_level.missing_for_next)
  13  critique.verdict='undecidable' (need 'survives')   <-- dominant
   4  retrieval.relevance is low_confidence
   4  novelty.class='unclear'
   3  retrieval.relevance absent
   2  redteam.verdict=fatal_flaw (hard cap below L1)
   2  experiment_outcome absent  (the two L1s)

  critic verdict trend:  08-15  2 undec / 5 surv
                         08-16 14 / 5     08-17  9 / 11
                         08-18 14 / 1  <-- 93% undecidable

PIPELINE
  eligible for construction (critic=='survives')  5 / 20
  of those, dispatch() returns a spec ..........  3 / 20
  of those, names a BUILT experiment ...........  1 / 20  (and it is L0)
  ADVANCEABLE BY A MENU ACTION .................  0 / 20
  topic concentration ..........................  3 distinct topics /
                                                  58 iterations; 55 (95%)
                                                  on one string

TODAY — Nara (cap 3)
  1. mine_paper_gap  (cost 1, ideation 18 remaining)
     why: topic concentration 55/58 on a single string. This action has
          never been used. Cheapest available diversifier.
  2. bubble_up  (cost 1, research 21 remaining)  -> owner queue #1
     why: no cluster is advanceable, and the dominant blocker is an
          instrument only a dev session can measure.
  3. — none. 13 clusters are barred by one critic verdict; 2 owe an
        experiment that does not exist.

OWNER QUEUE (cap 4)
  1. MEASURE the critic                     blocks 13 of 20 open clusters
     critique.verdict='undecidable' is the single dominant blocker, and
     its rate went 2 -> 14 -> 9 -> 14 over four days while 'survives'
     went 5 -> 5 -> 11 -> 1. 'undecidable' fails closed at the L1 rung
     AND in thesis_to_experiment.is_eligible, so these clusters cannot
     advance and cannot be constructed against.
     This is the same shape R1a measured in the redteam; D-076 fixed that
     instrument by battery and nothing has been run on this one.
     HYPOTHESIS, NOT A FINDING: critic_loop_v0 maps debate round_cap /
     converged to 'undecidable' as legitimate uncertainty, and the D-075
     debate changes landed 08-18 — the day the rate hit 93%.
     Ask: a calibration battery on the critic, on the R1a pattern.
     Clusters: cl-iter-2026-05-26-001, -002, -004, cl-iter-2026-08-16-009,
               -016, cl-iter-2026-08-17-001, -015, -020,
               cl-iter-2026-08-18-004, -006, -012, -013, -014

  2. VERDICT owed on 6 iterations                   blocks the L4 rung
     iter-2026-08-18-012, -013, -014, -015, iter-2026-08-19-001, -002.
     Oldest waiting 1.3d. One bubble_up was raised for four of them on
     08-18T21:00 and is still open.

  3. DISPOSE the two stranded L1s                   no instrument exists
     cl-iter-2026-08-16-003  L1, 3.4d at rung
       "smaller spectral gap in the delegation transition matrix -> higher
        transient variance of the Gini coefficient"
     cl-iter-2026-08-17-014  L1, 2.3d at rung
       "high local clustering coefficients decrease effective representation
        of minority nodes by concentrating delegated weight"
     dispatch() returns None for both; no routing-table row covers
     delegation graphs. exp012_lqg_spectral is adjacent but its own prereg
     scopes it as a linear belief-contraction surrogate, NOT a delegation
     model — routing these onto it would be coercion (rule 4).
     Options: (a) build a delegation-graph experiment; (b) close as
     L1-terminal with an honest code; (c) accept as parked and stop
     counting them as owed.

  4. CONSUME the frontier agenda                    14 proposals, 0 consumed
     memory/frontier_agenda.jsonl has 14 rows, all status "proposed",
     each naming the exact controls a frontier veto found missing.
     memory/design_constraints.jsonl has 112 active rows with no consumer.

ALSO TRUE, NOT ACTIONABLE BY NARA
  - building exp013_stag_hunt would unblock exactly 1 open cluster
    (cl-iter-2026-06-05-002), not 7: the other 6 whose TEXT routes to
    stag_hunt are barred upstream by critic='undecidable'. Worth doing
    after queue item 1, not before.
  - routing table is stale: exp010, exp011, exp012 are built and bridged
    but appear in no _GAMES row, so dispatch() cannot reach them.
  - promote_findings: 0 promotions in its last 16 runs (26 lifetime / 136).
  - all 89 redteam_fatal_flaw kills predate the D-076 prompt swap.

HORIZONS  (human/horizons.md — not yet created)
  week/month/quarter/year: unset. Not injected into the planner.
```

That is the whole product. Note what it did: it turned "20 open clusters,
ideation still running" into one named instrument defect blocking 13 of
them, with the clusters enumerated and the ordering against the
stag_hunt build made explicit — and it did not pretend Nara had three
things to do.

---

## 4. Horizons

`human/horizons.md`, human-authored, four fixed sections (`## 1 week`,
`## 1 month`, `## 1 quarter`, `## 1 year`). **Nara reads it and never
writes it** (inviolate rule 9). The week bullets ride into the planner as
conditioning; month/quarter/year go to your view only.

I deliberately do **not** build an alignment scorer over it. Scoring
clusters against your quarterly goals with a 26B model is exactly the
hypothetical-future abstraction inviolate rule 8 calls a liability, and it
would produce a number nobody could audit.

### How revision happens without rotting

Rot is the default outcome for horizon documents, and pretending otherwise
would waste your time. Four mechanics, in increasing order of how much I
trust them:

1. **Decreasing review frequency, matched to the horizon** (§2.2). Week
   reviewed weekly, month monthly, quarter and year at the quarter
   boundary. Reviewing the year every week is how these documents die.
2. **The weekly rollup supplies receipts, you supply judgment.** Sunday
   05:30, the existing cron writes `run_state/docket/week-YYYY-Www.md`: a
   measured DONE column (clusters advanced, rung changes, experiments
   built, verdicts cleared, topics run, budget by class) diffed against
   last week's. You revise the horizons with evidence in front of you
   rather than from memory. This is the weekly-research-report shape from
   §2.2 with the DONE half automated and the TODO half left to you.
3. **The one hard invariant, borrowed from the weekly review:** every item
   in `## 1 week` must name a next action, and every open cluster must
   have a next action or an explicit blocker. The rollup prints the
   violations. An active project with no next action is a defect the
   review catches — that is the whole point of the ritual.
4. **Staleness fails to silence, not to stale guidance.** The Docket
   prints `last_edited` and days since. After **14 days** the week section
   is marked `stale: true` and **stops being injected into the planner.**
   Nara falls back to today's behavior rather than planning against a
   fortnight-old priority.

### Where this fails — honestly

**This half of the design is worth nothing without about 15 minutes of
your time per week.** The Docket cannot write horizons; rule 9 forbids it
and the content is genuinely yours. If `horizons.md` goes unedited it
auto-silences after 14 days, which is the correct failure mode but also
means you get exactly the current behavior plus a file.

Two more honest failure modes:

- **Aspirational drift.** If you write a quarter goal the apparatus has no
  instrument for, the horizon and the docket will disagree forever and the
  docket will be right. The rollup surfaces the disagreement; it cannot
  resolve it.
- **Ceremony decay.** The Sunday rollup is a file, not a meeting. Nothing
  forces you to read it. Given §2.1's evidence, I would rather ship a
  file you read half the time than a ritual you abandon in three weeks —
  but I am not going to claim the file solves adherence.

---

## 5. What it does not do

**Scope limits, stated so the ratification is honest:**

- **It does not advance any cluster by itself.** On today's state its Nara
  list is `mine_paper_gap` and a `bubble_up`. It cannot build an
  experiment, cannot change a rung, cannot reopen a killed cluster. It
  makes the bottleneck legible and addressed; you clear it.
- **It does not fix the routing table.** Adding rows for exp010/011/012 or
  a delegation-graph row is a separate, ratifiable change (§1.5). The
  Docket only reports that the table is stale.
- **It does not re-adjudicate the 89 redteam kills.** That is the 08-19
  session note's Lane 5 and stays there.
- **It does not touch the redteam, debate, novelty, or promotion gates.**
- **It does not score ideas.** No LLM call, no quality judgment, no
  ranking by interestingness. Ranking is `level`, then `days_at_rung`,
  then id; the owner queue ranks on clusters-unblocked.
- **It does not diagnose the instruments it indicts.** It can report that
  13 clusters died on `undecidable`; it cannot tell you why the critic
  changed. Naming the cause is a dev session's job, and the Docket's
  hypothesis line is explicitly labelled as one (rule 4).
- **It does not write `ui/`.** Spec only, per CLAUDE.md rule 2.
- **It does not write prose for you.** `horizons.md` and the
  retrospectives stay yours.

**Inviolate rules it respects, explicitly:**

- **Rule 4 (validations never silently coerced).** An unroutable cluster
  is `blocked`, never "owed and pending." A near-match claim is never
  coerced onto an adjacent experiment — see the exp012 refusal in the
  worked example. This is the design's spine.
- **Rule 6 (logging mandatory).** One run-log row per build, `agent:
  "docket"`; blocked-count and empty-today are logged values, not silence.
- **Rule 7 (fallbacks explicit, logged, time-capped).** Stale
  `ledger_hash` → `today: []` + `docket.stale=true` + a logged reason;
  degrades to today's behavior, never to a silent wrong answer. Horizon
  staleness is capped at 14 days.
- **Rule 8 (bounded codegen).** One new module (~200 lines, inside the
  120–390 worker norm), one new human-authored markdown file, three small
  hunks in `coordinator.py`. No framework, no abstraction layer, no new
  process.
- **Rule 9 (the human's prose is the human's).** Nara never writes
  `horizons.md`.
- **Rule 3 (human gates blocking).** `human_owed` clusters are excluded
  from Nara's list entirely and surfaced only to you.
- **Dynamic Workflow discipline rule 2 (parallel limbs, serial spine).**
  `orchestrator/coordinator.py` is spine; only the integrator touches it.
  `tool_registry.py` and `iteration_record.schema.json` are untouched.

---

## 6. Build phases

Each phase lands independently, reverts independently, and has its own
done-condition. Phase 1 alone is worth shipping.

### Phase 1 — Make the board legible (no new module)

The smallest thing that produces value, and it fixes a defect rather than
adding a surface.

- `workers/idea_projection._stem`: when `elite` is null, resolve the claim
  through the loop_memory join instead of degrading to the bare
  cluster_id. Today's `ideas.md` Live-work section is 18 lines that
  differ only in id and timestamp (16 L0 + 2 L1); all 18 become readable.
- Same module: add `days_at_rung` computed from the last
  `evidence_level_changed`, alongside the existing (contaminated)
  `last_touched` (§1.2).
- Extend `orchestrator.loop_health.ladder_gaps` to carry cluster ids
  alongside the counts.
- Two extra fields on the existing `/api/lab_todo`: `claim`, `days_at_rung`.

**Done when:** `memory/ideas.md` shows 20 distinct, readable claim lines
with honest ages; `lab_todo` tests green under `MOCK_LLM=1`.
**Revert:** one `git revert`; nothing else imports the change.

### Phase 2 — The classifier, report-only

- `orchestrator/docket.py` with `classify()`, `rank()`, `build()`,
  `render_md()`, and the `--today/--dry-run` CLI. Zero LLM calls, asserted.
- Handles all four routing outcomes including `experiment_id: None`
  (§3.5 step 3 — the branch a naive version crashes on).
- Build-if-absent at the top of `coordinator_cycle()`. **Writes the file;
  changes no behavior.** `assess_state` is not touched yet.
- `tests/test_docket.py`, pinning the diagnosis as regressions: the 13
  `undecidable` clusters classify `blocked/critic_undecidable` and are
  counted as one ranked blocker, not 13 items; the two L1 clusters
  classify `blocked/no_synthetic_construction`; a cluster whose text
  routes to an unbuilt game but whose critic verdict bars
  `is_eligible` classifies on the **upstream** blocker, not
  `experiment_not_built` (the §1.3 error, pinned so it cannot recur); an
  item failing `validate_plan` is never advanceable; `ledger_hash`
  mismatch empties `today`; ranking is byte-stable.

**Done when:** `run_state/docket/2026-08-20.json` exists, its worked
example matches §3.7, all tests green under `MOCK_LLM=1`, and one real
`env -u MOCK_LLM` build confirms the claim join survives the 3.65 MB
loop_memory.
**Revert:** delete two files, revert one hunk.

### Phase 3 — Horizons, read-only

- `human/horizons.md` stub, four sections, with a header line saying Nara
  reads but never writes it.
- Docket reads it, reports `last_edited` and `stale`, renders it into
  `today.md`. Still not injected into the planner.

**Done when:** the file renders in `today.md` and marks itself stale after
14 days in test.
**Revert:** delete one file, revert one function.

### Phase 4 — Arm the planner seam (dark by default)

- `docket` field on `assess_state()`, gated on `NARA_DOCKET_PLAN`.
- One paragraph in `_planner_system_prompt` (§3.5).
- Flag stays **unset** until you have read at least three days of dockets.

**Done when:** with the flag set in a test, the planner state carries ≤3
pre-validated actions; with it unset, `assess_state` is byte-identical to
today.
**Revert:** unset the env var — no code change needed.

### Phase 5 — Weekly rollup + cockpit strip

- One line in the existing `cron/weekly-frontier-agenda.sh` writing
  `week-YYYY-Www.md` with measured deltas and the next-action invariant
  violations.
- UI: **spec only**, into the session note's `## UI session work order`.

**Done when:** a rollup exists for the current week; the UI spec is in the
session note.
**Revert:** one line out of the cron script.

**Suggested stop point:** phases 1–3 are report-only and carry near-zero
behavioral risk. Phase 4 is the only one that changes what Nara does.

---

## 7. Risk / reward — the ratification ask

### What you gain

- A named bottleneck each morning instead of a count. Tomorrow's is:
  *the critic has returned `undecidable` on 13 of 20 open clusters, its
  rate hit 93% on 08-18, and nothing downstream can proceed until it is
  measured.* Nobody spotted that for four days.
- A readable board — 20 distinct claim lines instead of 18 that differ
  only in id and timestamp, on a file currently a day stale.
- Honest time-at-rung, replacing an age signal that consolidation
  contaminates.
- A standing channel for the thing that has actually moved this
  apparatus: Nara telling you which instrument to build or repair.
- **Instrument-drift detection you did not ask for.** Because the owner
  queue ranks on clusters-unblocked, a gate that starts mis-firing rises
  to the top by construction. That is how the critic finding surfaced;
  the redteam defect R1a caught by hand would have surfaced the same way.
- Detection of degenerate ideation. 55/58 on one topic went unnoticed for
  five days; the Docket prints topic concentration every day.
- Four horizon sections that fail safe when you stop maintaining them.

### What you give up

- **~15 minutes a week**, or the horizons half is inert. Non-negotiable —
  rule 9 means Nara cannot write it for you.
- **A dated file per day** in `run_state/docket/`. ~4 KB each, ~1.5 MB/yr,
  git-ignorable.
- **~1.4 KB of planner context** once phase 4 arms (4.4 KB → 5.8 KB, still
  far from any limit).
- **~200 lines of new code** plus three hunks in the coordinator spine.
- **Some ideation freedom**, once armed: choosing to mint a new idea while
  a ready item sits on the docket becomes an explicit, logged act. It is
  never forbidden.

### What could go wrong

| risk | likelihood | mitigation |
| --- | --- | --- |
| **The docket is empty for weeks** and reads as a broken feature. It is not broken — it is reporting that nothing is advanceable. | **High.** True today, and true until phase-1-of-your-queue lands. | The `owner_queue` is never empty when `today` is. The digest states the emptiness as a finding with a cause. If `today` is still empty a week after the top owner-queue item is cleared, the design has failed and should be reverted — that is a real falsification condition, and I am naming it now. |
| **Dark forever.** This repo has a pattern: D-065 debate, D-066 improve_system, both topicality gates — all shipped dark, some for months. | **High** | Phases 1–3 are not gated at all, so value lands regardless. Phase 4 carries an explicit review date: if `NARA_DOCKET_PLAN` is unset 14 days after phase 4 lands, the seam is removed rather than left rotting. |
| **Stale digest** — the 23:00 cycle plans against a 00:30 file and re-dispatches done work. | Medium | `ledger_hash` interlock: mismatch → `today: []`, `stale: true`, logged; falls back to today's behavior (rule 7). |
| **Alarm fatigue.** A permanently-blocked cluster set producing a permanent warning, in a repo that fixed two false-positive `loop_alert` REDs this week. | Medium | The Docket **raises no alert and sets no `loop_alert` level, ever.** It writes a file and, at most, plans one `bubble_up`. Escalation costs budget, which naturally rate-limits it. |
| **Claim-resolution join fails** on clusters whose members are missing from loop_memory. | Low–Medium | `blocked/claim_unresolvable`, counted and reported; never a crash, never a guess. |
| **A fifth board.** `ideas.md`, `lab_todo`, `frontier_agenda`, `human_todo` already exist. | Medium | Phase 1 *fixes* two of the existing surfaces rather than adding one. The only new artifact is the dated digest. If you would rather have the digest as a `lab_todo` field and no new file, say so — phase 2 collapses into phase 1. |
| **Ranking is too crude** (level, then age, then id — no notion of interestingness). | Low harm | Deliberate. A model-scored ranking is unauditable and would need calibration we have not done. Crude and inspectable beats clever and unfalsifiable. `--pin` lets you override. |

### What it costs per day

- **Compute:** zero LLM calls. One ledger reduction (329 events), one
  keyed loop_memory pass, ~1 s wall clock, inside an existing cycle.
- **Budget units:** zero for the build. Once armed, `mine_paper_gap` (1) or
  `bubble_up` (1) may be planned — both from budget already reserved and
  currently unspent (research sits at 0/21).
- **Your time:** ~2 minutes to read `today.md`; ~15 minutes on Sunday for
  horizons. That is the whole ongoing cost.

### The revert

- Phases 1, 3, 5: one `git revert` each.
- Phase 2: delete `orchestrator/docket.py`, `tests/test_docket.py`,
  `run_state/docket/`; revert one hunk.
- Phase 4: **unset `NARA_DOCKET_PLAN`.** No code change, no restart beyond
  a daemon bounce.

Nothing else in the apparatus imports any of it.

### The autonomy question, directly

**Nara decides on its own:**

- which of the ≤3 docket items to run this cycle, or none of them;
- whether to override the docket and mint a new idea instead — permitted,
  provided it states why in the plan reason;
- whether to spend a `bubble_up` on the top owner-queue item.

**Nara proposes; you decide:**

- which experiment gets built (the only lever that has ever moved a rung);
- disposition of an unroutable cluster — kill, park, or build for it;
- every human gate verdict (unchanged; rule 3);
- reopening any killed cluster;
- every word of `horizons.md`.

**Nara may never:**

- change an evidence level, write a kill or reopen event, edit the routing
  table, consume a frontier agenda proposal, or write `ui/`.

**What lands dark:** only the planner injection, behind
`NARA_DOCKET_PLAN`, in phase 4. Phases 1–3 land lit — the board fix, the
digest, and the horizons file all take effect on merge, because you cannot
evaluate an artifact you are not allowed to see. Phase 4 carries a
14-day arm-or-remove deadline so it does not join the dark-forever list.

### The ask

Ratify **phases 1–3** (report-only, no behavior change, ~1 day of build)
and **phase 4 as a seam that stays dark** until you have read three
dockets. Phase 5 follows only if the weekly rollup earns it.

Separately, and independent of this design: **the single highest-value
action available to the apparatus right now is a calibration battery on
the critic.** `undecidable` is blocking 13 of 20 open clusters, its rate
hit 93% on 2026-08-18, and it fails closed at both the L1 rung and
`is_eligible` — so nothing downstream of it can move regardless of what
else we build. R1a is the template and D-076 is the precedent. Building
`exp013_stag_hunt` is worth doing *after* that, not before: it unblocks
one cluster today, and six more only if the critic starts discriminating
again.

The Docket's job on day one is to tell you that, in one screen, before
you have to go looking. **It does not need to be built for you to act on
it — that finding is above, and it is yours now.** What ratifying this
buys is that the next one arrives without a five-day delay and without a
session spending an afternoon on probes.
