# Pre-registration — literature-critic replay battery + override-chain audit — v2

Status: **v2 after adversarial critique** (`d075-critic-critic-cal`,
verdict FIX-REQUIRED: seven verdict-selecting flaws + eleven others,
every one resolved below and named in the changelog). **DRAFT, not
locked.** Authored by a no-live-call subagent on 2026-08-19. **Zero model
calls were made in drafting, revising, or building this document or its
code**, per the hard constraint (a re-adjudication battery owns
`vllm-gemma`; contention would manufacture spurious timeouts in a locked
measurement).

**What locks, and when.** This prereg LOCKS at the commit that also
contains `bench/critic_cal/manifest.jsonl` (the complete frozen fixture
manifest, every fixture carrying its replayed retrieval envelope) and
`bench/critic_cal/manifest_meta.json` (build meta: exclusions by reason,
pool sizes, per-bar denominators, source shas). The run driver reads only
the manifest. Nothing below is resolved at run time.

Prior art matched deliberately, and now matched in the places v1 dropped
it: `experiments/PREREG_redteam_cal_2026-08-18.md` (v2, locked — arms,
Clopper-Pearson CIs, provenance-split confusion, `--out` anchored to
`REPO_ROOT`, an explicit adoption rule with a pre-stated "if no arm
passes" disposition) and `experiments/PREREG_readjudication_2026-08-19.md`
(locked — run-validity bars evaluated FIRST, hard-void bars, **void
semantics and the one-re-run cap**, **the determinism test under shuffled
order and three PYTHONHASHSEEDs**, artifact provenance blocks).

---

## CHANGELOG — v1 → v2

Every flaw the adversarial critique raised, and what changed. Where a
flaw could not be designed away, it is stated plainly and the battery's
claim is **reduced**, not defended. **The headline change: D1 no longer
claims to calibrate the critic. It claims to test the critic's
REPRODUCIBILITY and to rule out DEGENERACY. That is all the available
evidence supports.**

### Verdict-selecting flaws

**VS-1 — C3's threshold sat ~2× above the behavior it existed to detect,
so a C3 pass was pre-ordained and pre-declared an exoneration.**
CONFIRMED and FATAL to the v1 design. Measured (reproduced exactly by
`bench/critic_cal/audit_overrides.py`): the primary critic's NATIVE
undecidable rate on adequate packs is **7/52 = 0.135 in August** and
**10/120 = 0.083 all-time**. v1's C3 was "≤ 6 of 24" = 0.25.
**Resolution:** C3 is **DELETED**. The over-emission rate it was
supposed to estimate is already a **census**, exact, at zero call cost —
a 26-call battery cannot improve on it, and §10 says so. The production
reference rates are now pinned in the prereg (§0), in the driver
(`REF_NATIVE_UNDECIDABLE_ADEQUATE_ALLTIME`,
`..._AUGUST`), and are re-verified against the live ledger by a test
(`test_pinned_reference_rates_match_the_live_record`). Its replacement
`C2` is re-anchored, has its false-void at the reference rate computed
(0.0018), and is labelled a **DEGENERACY GUARD** in the artifact itself.
The sentence *"a C3 pass is strong evidence against H1"* is **deleted**;
§13's disposition table states in its place what a C2 pass does and does
not license.

**VS-2 — H1's target population was mis-scoped by ~3×.** CONFIRMED
exactly: of the 29 NATIVE undecidables, **19** sit on packs recorded
`(off_domain, low_confidence=True)` — where `critic_loop_v0.py:653-660`
put the RETRIEVAL RELEVANCE WARNING into the critic's own prompt, telling
it that absence of contradiction in an off-topic corpus is not
`survives`. A critic that says `undecidable` there is **correct**.
**Resolution:** the genuine population is **10 rows all-time / 7 in
August**, and it is now the battery's **S1 stratum — a CENSUS of all 10,
not a sample**. §1 and §2 are restated against it. H2 (the
prompt-under-specification hypothesis) is **withdrawn** with its arm
(see VS-6). D2 carries a first-class census of ALL 59 undecidables by
recorded pack state (`undecidable_census.by_class_and_pack_state`), and
every D1 artifact opens with a **mandatory attribution sentence**
carrying all three denominators, emitted by
`driver.ATTRIBUTION_SENTENCE` and asserted by a test.

**VS-3 — the seeded `relevance` block was an unpinned build-time free
parameter that alone moved both discrimination bars.** CONFIRMED as a
defect of v1's constructed-fixture design. The critique's fix — compute
every fixture's relevance with `workers.retrieval_relevance.relevance()`
— was **tested and found DESTRUCTIVE**, which is a v2 finding in its own
right: recomputing with `topicality=None` (the only option without a
model call) reclassifies **35 of the 36 recorded `off_domain` rows to
`ok`**, because 35 fired rule **R0, the LLM topicality judge**; and even
recomputing *with* the recorded topicality/anchor arguments still
diverges on **20 of 119** relevance-bearing rows, because **D-075 R2
(2026-08-18) demoted R0 for hypotheses matching a curated
`DOMAIN_ANCHOR_PHRASES` entry** and most of the record predates it.
Following the fix literally would have silently deleted the entire
insufficient-pack stratum. **Resolution:** there is no seeding at all.
Every fixture replays its **RECORDED** relevance block verbatim — the
block that actually shaped the production prompt — and the builder ALSO
computes the pure-function recomputation, records it per fixture with the
arguments passed (`anchor_cosine`, `topicality`, both stated, `None`
noted as legacy-equivalent), and reports the divergence
(`relevance_recompute_divergence`: 7 of 26 fixtures, ids listed). The
prompt-shape consequences (`relevance_warning_fires`,
`novelty_context_fires`, `coverage_override_would_fire_on_survives`) are
**derived from the replayed envelope and frozen in the manifest**, so
they are checkable before a single call. The detection-vs-obedience
separation the critique asked for is a **named, owner-elected probe arm**
(§7.2) with a pre-stated, executable reading rule — because §5.4 shows
no history-only fixture can separate them.

**VS-4 — `blocked_by_override` used the wrong, weaker predicate and
over-reported the override chain's cost by 2.6×.** CONFIRMED exactly,
including the 7 named ids. `bench/critic_cal/audit_overrides.py:downstream`
now computes **both** and names them apart:
`blocked_by_override` on the **real L1 rung**
(`workers.evidence_ladder.derive_level`, which
`orchestrator/finding_promotion.py:191-206` delegates to) = **7**; and
`t2e_blocked_loose` on `thesis_to_experiment.is_eligible` alone = **18**,
explicitly labelled *"a LOOSE UPPER BOUND: it ignores the L1 rung's
relevance and redteam terms"*, with the **11** rows already below L1 for
other reasons listed by id and by failing term. The 7 are exactly
`iter-2026-08-18-003/-004/-006/-012/-013/-014` and `iter-2026-08-19-001`
— all `debate verdict='inconclusive'` with `redteam=proceed`. A test
asserts the strict set is a subset of the loose one and that the
difference reconciles.

**VS-5 — the prereg's own open question C-4 was decidable from the record
at zero cost, and its answer contradicted the briefed premise.**
CONFIRMED. C-4 is **SETTLED IN THIS DOCUMENT** (§0.4) with the
computation printed and shipped as code
(`audit_overrides.cluster_impact`). The result: of 20 open clusters,
**2 are at L1 RIGHT NOW** (`cl-iter-2026-08-16-003`,
`cl-iter-2026-08-17-014`) with `missing_for_next = ['experiment_outcome
absent']` — they need an **experiment**, not a critic; **8** are
critic-only-blocked (flipping the verdict to `survives` lifts them to
L1); the remaining **10** fail terms the critic does not control. The
briefed premise "ZERO open clusters are advanceable by any coordinator
action" is **false as stated** and is corrected here rather than
inherited. D1's priority is re-derived from the settled answer in §21.
(My reconstruction differs in detail from the critique's on 3 clusters
because it takes each cluster's LATEST member rather than its seed
iteration; all three candidate orderings agree on every open cluster
(`reconstruction_disagreements: []`), and the load-bearing finding — the
2 L1 clusters — holds under both.)

**VS-6 — Arm B had no pre-stated adoption or comparison rule.**
CONFIRMED. **Resolution: Arm B is DELETED, on arithmetic, not on
convenience.** A prompt revision aimed at "emit `undecidable` less often
on adequate packs" can only demonstrate itself where the baseline has
room to fall — the **S2** stratum, 8 fixtures, whose reference
expectation at the measured production rate of 0.135 is **≈ 1
undecidable** (and lower still, since these 8 rows were already DECIDED
by this instrument on these packs). **An arm cannot demonstrate a
reduction of K ≥ 2 against a baseline of ≈ 1**, at any threshold, so an
adoption rule for it would be theatre. The other adequate-pack stratum,
S1, is a census of rows that all recorded `undecidable`; a revision that
moved them would be indistinguishable from the instability E1 already
measures. Saying this is cheaper than discovering it after 26 more calls.
H2 is withdrawn with it. A pre-stated disposition replaces it: **if Arm
A's S1 census replays ≥ 7 of 10 as still-undecidable AND C2's count is
≥ 3 of 8, a prompt-revision arm becomes worth commissioning as a
SEPARATE prereg with its own adoption rule and its own power
computation.** It does not auto-execute. The one arm that survives (the
warning-suppressed probe, §7.2) carries a fully pre-stated, **executable**
reading rule (`driver.paired_probe_comparison`), unit-tested at and
either side of its threshold.

**VS-7 — no void semantics and no re-run policy.** CONFIRMED; the cited
prior art's central anti-gaming sentence had been dropped. **Resolution:**
imported verbatim into §11 and into the driver constant
`VOID_SEMANTICS`, which rides on **every** evaluation object and is
asserted by a test: *"Void means: report the failure … It does not mean
re-thresholding, re-running until it passes, or explaining it away as an
unlucky fixture set."* Re-runs are **capped at exactly one**, permitted
only for a V2 serving-identity void or an infrastructure abort, and when
one happens **both runs and both artifacts are reported**.

### Other flaws

**O-1 — §4.1's replay envelope matched neither recorded shape.**
CONFIRMED and verified independently: `memory/loop_memory.jsonl`'s
`retrieval` block is FLATTENED (`{k, neighbors, latency_ms, escalation,
relevance}`, no `result` wrapper) across all 160 rows carrying it, while
`run_state/iteration_cache/<id>/retrieval.json` is the full worker
envelope `{status, result, errors, parent_request_id}` and
`critic_loop_v0.py:619` reads `retrieval['result']['neighbors']`.
**Resolution:** the canonical source is **named and pinned** — the
manifest copies the **cache** envelope verbatim (§4.1); a build-time gate
**refuses any fixture whose cache and loop_memory copies disagree by
sha256** on neighbors OR relevance; and two tests assert the seeded shape
against the reader
(`test_seeded_envelope_has_the_result_wrapper_the_critic_reads`,
`test_cache_and_loop_memory_packs_agree_by_sha256`). All 156
critique-bearing rows have a cache entry and all 156 agree.

**O-2 — the prompt truncates every neighbor's `chunk_text` to 600 chars,
which could make a `falsified` label unachievable by construction.**
CONFIRMED (`critic_loop_v0.py:199-201`; measured over 1600 recorded
neighbors: min 91, median 863.5, max 2521, **57.1% exceed 600**).
**Resolution: the hazard is DESIGNED OUT** — v2 constructs no
merit-labelled `falsified` fixture at all, so no label depends on a
sentence being inside the window. Historical replay inherits the
truncation exactly as production did, which is fidelity, not a defect.
The count of neighbors exceeding the window is recorded per fixture
(`pack.n_chunks_over_prompt_window`) with the window value beside it.

**O-3 — §11 claimed the battery writes nothing to `run_state/` while
§4.1 required seeding it.** CONFIRMED contradiction. **Resolution:** the
cache write is stated as a **NAMED EXCEPTION** in §11 and in the artifact
(`provenance.cache_write_exception`). The namespace `critcal-` is pinned;
verified the only cache-root enumerator is
`experiments/lit_falsification_battery/calibrate_anchor.py:80`, which
globs `iter-*` (no collision), and `ui/backend/iteration_journey.py` joins
on real iteration_ids. **The 26 synthetic directories are RETAINED after
the run as reproducibility artifacts** — stated, per the critique's ask.
A test asserts the namespace.

**O-4 — the fixture builder was not reproducible and had no prior art.**
CONFIRMED for v1's design. **Resolution: designed out.**
`bench/critic_cal/build_manifest.py` makes **zero retrieval calls, zero
embedding calls, zero model calls** — every pack is a recorded pack — so
a rebuild IS byte-identical and the builder genuinely mirrors R1a's
`build_fixtures.py`. It refuses loudly on any divergence
(`ResolutionError`, exit 1), pins an **ERA BOUND** (`2026-08-19T06:00:00Z`)
against a growing always-on ledger, records the `loop_memory` sha256 in
build meta, and is tested for byte-identity under shuffled input and
three PYTHONHASHSEEDs. Because it makes no calls it is MOCK_LLM-agnostic
by construction rather than by a guard. **The frozen manifest, not the
builder, is the reproducible artifact** — and here the builder is too.

**O-5 — §5.4's construction violated §5.2's own stated rule (author-chosen
query substitution is hand-planting by another mechanism).** CONFIRMED.
**Resolution:** adopted the critique's own recommended fix — the
insufficient-pack stratum is drawn **entirely from the recorded
`off_domain` rows** (pool 36, 8 selected), i.e. packs production genuinely
assembled *for that claim* and that the apparatus's own relevance
instrument genuinely flagged. No query substitution exists anywhere in
v2. The exact recorded relevance `reason` and `rule_fired` ride in each
fixture.

**O-6 — C3's denominator was ambiguous (readable as 24 or 22).**
CONFIRMED as exactly the near-miss coercion lever rule 4 exists to close.
**Resolution:** every bar's denominator is a **frozen explicit fixture-id
set**, written into `manifest_meta.json` at build time
(`bar_denominators`), reproduced in Appendix C, and computed by the
driver from `stratum` alone. No fixture appears in two strata (asserted:
`len({iteration_id}) == len(fixtures)`).

**O-7 — the 2 weak gate anchors carried a label answering a different
question and still landed in a bar denominator.** CONFIRMED; verified all
7 rows of `memory/loop_feedback.jsonl` independently. **Resolution:** the
human-gate ledger anchors **ZERO** fixtures and **ZERO** bars in v2. It
is reported in §6 and by the audit as a census, for the sole purpose of
stating honestly that it cannot anchor this battery. `not-falsified`
including `undecidable` is no longer a problem because no fixture is
labelled from it.

**O-8 — D2's determinism was asserted, not specified.** CONFIRMED, and
the tie-break hazard is real: `memory/idea_ledger.jsonl` has **37
duplicate-timestamp groups, one shared by 190 events**, so "timestamp
order" has no defined answer. **Resolution:** the audit does not
re-implement a fold — it uses `workers.idea_ledger.load_state`, the
canonical **file-order** (= append-order) reducer the UI and coordinator
already use, and the audit records that choice. Every emitted collection
is explicitly sorted. The readjudication determinism test is imported
verbatim: invariance under **shuffled input order** and under **three
PYTHONHASHSEEDs**, each in a fresh interpreter compared by artifact
sha256. Hard coverage invariants raise `AuditInvariantError` and write
nothing: rows read == rows emitted (167), class counts sum to the total,
undecidable-class counts sum to 59, `(class, pack_state)` counts sum to
59, **the single-level-override invariant is asserted per row** (and its
mechanism stated: the coverage override at `:738-762` precedes and
short-circuits the skeptic/debate seams at `:777+`, which are guarded on
`verdict == 'survives'`), and **any unmatched `override_reason` prefix
raises** rather than pooling into a silent OTHER.

**O-9 — D2's "pre-stated readings" had their antecedents already known
true.** CONFIRMED. **Resolution:** §18 marks every reading
**SETTLED-AT-DRAFT** or **GENUINELY-OPEN**, and the phrase "pre-stated"
is confined to the open ones. R-c is given a number. §19's M4 row loses
"the mapping the data most obviously suggests" from the neutral table;
that judgment is moved to a separately labelled analyst note.

**O-10 — D1 had no disposition table at all.** CONFIRMED.
**Resolution:** §13 is a full disposition table covering every bar
outcome including the null path and what it does **not** license, plus
the explicit clause **"No option auto-executes."**

**O-11 — minor factual cleanups.** All CONFIRMED and applied:
(a) the "12 rows carry no status" conflation is separated — **11 rows
have no `critique` block at all**, plus **exactly 1** critique row with
`subagent_status` `None` (`iter-2026-05-26-008`); both counts are emitted
separately by the audit.
(b) `timeout` has **never** fired; kept as a defensive category with one
line saying a first occurrence is itself a signal. Stronger, and new in
v2: the failure-sink→`undecidable` path has **never fired either** — the
record's only 2 `schema_mismatch` rows (`iter-2026-05-27-006/-008`) are
May-era and defaulted to **`survives`** under the pre-T1b code. All 59
recorded undecidables are `substantive`.
(c) the `override_class` prefix table now includes
`relevance low_confidence is true:` (a distinct RELEVANCE sub-branch,
`:750-754`) and `restatement skeptic (` (`:526-529`) as live-but-unfired
paths, so OTHER stays meaningful — and an OTHER match now **raises**.
(d) `NARA_RESTATE_SKEPTIC` dark in production re-verified (gate at
`critic_loop_v0.py:489` defaulting `"0"`; absent from
`cron/run-coordinator.sh` and `orchestrator/nara_daemon.py`); pinning it
to 0 is correct and costs nothing.

---

## 0. The verified record — every number below is reproducible

All figures computed by `bench/critic_cal/audit_overrides.py`, which is
deterministic, makes zero model calls, and writes
`bench/critic_cal/runs/override_audit_2026-08-19.json`. Sources:
`memory/loop_memory.jsonl` (167 rows), `memory/idea_ledger.jsonl` (329
events), `memory/loop_feedback.jsonl` (7 rows), sha256'd into the
artifact. **Nothing in this section is asserted from the brief; every
figure was recomputed, and the corrections are marked.**

### 0.1 The undecidable population — the census that scopes everything

167 rows; 156 carry a `critique` block; verdicts: `survives` 67,
`undecidable` **59**, `restated` 23, `falsified` 7, none 11.

| provenance class | reason prefix | n |
| --- | --- | ---: |
| NATIVE | *(no `verdict_overridden_from`)* | **29** |
| RELEVANCE | `relevance category '…' != 'ok'` | **12** |
| DEBATE | `debate verdict='…' after N round(s)` | **11** |
| SINGLE-SHOT SKEPTIC | `skeptic attack_verdict='…'` | **7** |
| | | **59** |

`12 + 11 + 7 = 30` = the survives-overrides. The brief's three-way split
folds away the fourth class; the fourth is reported alongside. Classing
keys on the reason **PREFIX**, never a substring: a substring test for
`"debate"` mis-sorts two 07-06 skeptic rows whose own prose contains the
word.

**THE SPLIT THAT SCOPES D1 (v2's central correction).** The 29 NATIVE
rows are not one population:

| NATIVE undecidable, by pack state recorded at the time | n |
| --- | ---: |
| **adequate** — no relevance warning was in the prompt | **10** |
| **flagged** — `(off_domain, low_confidence=True)`; the RETRIEVAL RELEVANCE WARNING WAS in the prompt | **19** |

On those 19, `critic_loop_v0.py:653-660` had told the critic verbatim:
*"Absence of contradiction in an off-topic corpus is NOT 'survives' — say
so and flag low confidence."* **A critic that says `undecidable` there is
obeying an instruction, not miscalibrated.** Only the **10** are a
calibration question at all.

> **THE MANDATORY ATTRIBUTION SENTENCE**, reproduced at the top of every
> D1 artifact and asserted by a test:
>
> *Of the 59 undecidable rows in the record, **10** are NATIVE on an
> adequate pack (this battery's S1 census — the ONLY population it speaks
> to), **19** are NATIVE on a pack the apparatus itself flagged, where the
> critic's own prompt instructs it to say undecidable, and **30** were
> OVERRIDDEN after the critic had already said 'survives'. Nothing in
> this report is a statement about the other 49.*

### 0.2 The production reference rate — a CENSUS, already exact

Numerator = critic calls on an adequate pack whose NATIVE verdict is
`undecidable`; denominator = ALL critic calls on an adequate pack
(overridden rows stay in the denominator — their native verdict was
`survives`, and dropping them would inflate the rate).

| period | k/n | rate | exact 95% CI |
| --- | ---: | ---: | --- |
| all time | **10/120** | 0.0833 | [0.0407, 0.1479] |
| 2026-05 | 0/28 | 0.0000 | — |
| 2026-06 | 2/25 | 0.0800 | — |
| 2026-07 | 1/15 | 0.0667 | — |
| **2026-08** | **7/52** | **0.1346** | [0.0559, 0.2579] |

**This is why v1's C3 had to go, and why v2 does not replace it with a
better-tuned bar.** There is nothing here to estimate: it is a complete
count of the population, free, deterministic, and reproducible. A
26-call battery cannot improve on a census. What the ledger *cannot*
tell you is whether those 10 verdicts are **stable** — that is the only
thing calls can buy, and it is what D1 now buys.

Companion reference for the flagged-pack stratum: across all **36**
recorded `off_domain` rows the sub-agent's **raw** verdict is
`undecidable` on **19** (0.528, CI [0.355, 0.696]), `survives` on 12
(then coverage-overridden), `restated` on 4, `falsified` on 1. **Obedience
to the warning is roughly a coin flip historically** — so a bar on that
stratum is not something the instrument clears by construction.

### 0.3 The 30 survives-overrides — what the overrider actually claimed

| what the override asserted | n |
| --- | ---: |
| **a refutation was asserted** | **6** (4 skeptic `refuted`; 2 debate `refuted`, both `defender_conceded`, at turns 2 and 4) |
| nobody refuted it — ran out of rounds | **7** (debate `inconclusive` at `round_cap`: 3 at cap 4, 4 at cap 6) |
| nobody refuted it — corpus-coverage statement | **12** |
| nobody refuted it — INFRA failure | **5** (3 `unparseable or off-enum skeptic output`; 2 `challenger_error` at turn 1) |

**24 of 30 blocked claims were never refuted by anything.** `rounds`
counts transcript TURNS, not exchanges: cap 4 = 2 exchanges, cap 6 = 3.

Debate anatomy (12 rows carrying a `debate` block, 11 of which override):
`inconclusive/round_cap/6` ×4, `inconclusive/round_cap/4` ×3,
`inconclusive/challenger_error/1` ×2, `refuted/defender_conceded/2` ×1,
`refuted/defender_conceded/4` ×1, `survives_debate/challenger_conceded/4`
×1 (no override).

`skeptic_infra_error` is genuinely **0** across the ledger — but it is
**not an infra census**: the flag was introduced by D-075 R3b and cannot
appear on rows written before it. **5** rows carry infra-flavored stop
reasons (ids: `iter-2026-07-05-001`, `iter-2026-07-06-002`,
`iter-2026-08-16-005`, `iter-2026-08-18-009`, `iter-2026-08-18-010`).
The audit reports the flag count and the `infra_flavored` count side by
side and says which is which. **The brief's conclusion — that infra is
not *the* explanation — survives; the stronger reading, that infra
contributes nothing, does not.**

### 0.4 SETTLED: "zero open clusters advanceable" is false as stated

The fail-closed mechanism is real and verified
(`thesis_to_experiment.py:150-159`; `finding_promotion.py:191-206`
delegating to `evidence_ladder.derive_level`). But running the ladder
over the 20 open clusters' latest members settles the question the v1
draft deferred to the owner. All three candidate reconstructions
(ledger append order, id sort, loop_memory file order) agree on **every**
open cluster, so there is no ambiguity to hide in:

| what blocks the cluster | n |
| --- | ---: |
| **nothing the critic controls — already at L1, `missing_for_next = ['experiment_outcome absent']`** | **2** (`cl-iter-2026-08-16-003`, `cl-iter-2026-08-17-014`) |
| `critique.verdict='undecidable'` alone | 8 |
| `undecidable` + `redteam fatal_flaw` (hard cap) | 1 |
| `low_confidence` + `novelty unclear` + `undecidable` (three terms; a critic fix moves none of them alone) | 4 |
| `retrieval.relevance absent` (legacy May/June rows) | 2 |
| `retrieval.relevance absent` + no novelty + no critique | 1 |
| `redteam fatal_flaw` alone | 1 |
| `novelty rediscovery` + `critique restated` | 1 |

**Counterfactual, computed: flipping the critic verdict to `survives`
lifts exactly 8 of 20 open clusters to L1.** Two clusters need an
**experiment**, not a critic. Ten are blocked by terms the critic does
not own. The critic is a **major** binding constraint (8 of 20), not the
**sole** one, and it is not the constraint at all for the two clusters
that are furthest along.

---

## 1. The two questions, correctly scoped

> **Q1 (an instrument question).** When the primary literature critic
> emits `undecidable` on a pack that was **not** flagged, is that verdict
> a JUDGMENT or is it NOISE? This bears on **10** rows — the S1 census.
> It does **not** bear on the 19 flagged-pack NATIVE rows (the critic was
> following its own prompt) or on the 30 overrides (the critic said
> `survives`).
>
> **Q2 (a semantics question, then a ruling).** The override chain maps
> 30 primary-critic `survives` verdicts onto `undecidable` — **24 of them
> without any refutation being asserted**. Should a bounded debate that
> ends UNREFUTED downgrade a `survives` into a rung-blocking
> `undecidable`? This bears on the **30 OVERRIDE** rows and on the
> **7** rows the override actually costs a rung.

**Q2 cannot be answered by any battery on the primary critic.** The
critic said `survives` on all 30. Running a better-calibrated critic
changes nothing about a mapping applied after it speaks. Q2 is settled by
the owner ruling on semantics; D2's only job is to put an honest,
complete, reproducible measurement in front of that ruling — at zero call
cost.

---

# DELIVERABLE 1 — CRITIC REPLAY BATTERY

## 2. What D1 measures — RESCOPED, and stated as a limitation first

**D1 does not calibrate the critic and does not claim to.** v1 did, and
could not: the rate a calibration bar would turn on is already a census
(§0.2), and **no non-circular correctness label exists at usable N**
(§6 — the human-gate ledger holds 7 rows, 6 distinct iteration_ids, and
exactly **1** merit-defensible positive critic label, all June-register).
A battery with no external labels cannot measure accuracy. Saying so is
the honest move; a bar that pretends otherwise is worse than no bar.

What 26 calls **can** buy, and what D1 therefore claims:

> **M1 (REPRODUCIBILITY).** Of the 10 NATIVE undecidables on adequate
> packs — replayed against the exact same claim and the exact same pack —
> how many come back `undecidable` again? An `undecidable` that does not
> reproduce was never a judgment; it was a coin flip whose cost is a
> blocked cluster.
>
> **M2 (DEGENERACY).** Is the instrument degenerate in either direction —
> a condemner that turns decided claims into `undecidable`, or a rubber
> stamp that never reaches for `undecidable` even on a pack the apparatus
> flagged? Both failure modes are fatal to the apparatus and both are
> detectable at this N with certainty.
>
> **M3 (SELF-CONSISTENCY).** On rows the same instrument already decided,
> on the same pack, does it decide the same way?

M1 is the load-bearing one, because it is **decision-relevant in both
directions**: an unstable `undecidable` points at a stability remedy
(self-consistency / retry), a stable one points at prompt semantics or
retrieval. Neither remedy is licensed by the ledger alone.

## 3. The production seam — VERIFIED, not assumed

Verified by reading `orchestrator/nara.py`, `orchestrator/tool_registry.py`,
`orchestrator/runtime.py`, `workers/critic_loop_v0.py`.

### 3.1 Invocation

`tool_registry.py:149-162` declares exactly two required parameters:
`critic_loop_v0(hypothesis_text=<str>, iteration_id=<str>)`, plus
`parent_request_id` injected by the runtime. **`budget` is never passed
by production**, so the worker default applies
(`critic_loop_v0.py:707`).

> **PIN.** The battery passes `SubAgentBudget(max_turns=6,
> max_wall_seconds=90.0)` **explicitly**. These are the CRITIC's budgets
> and differ from the redteam's `3 / 45.0` used in R1a — do not copy
> R1a's numbers.

### 3.2 Backend

`CRITIC_BACKEND` is unset by `cron/run-coordinator.sh` and
`orchestrator/nara_daemon.py`, so production resolves `DEFAULT_BACKEND` =
`WRAPPER_DEFAULT_BACKEND`, defaulting to **`vllm-gemma`**.

> **PIN.** `CRITIC_BACKEND=vllm-gemma`, set explicitly so the artifact
> records an asserted value rather than an inherited default.

### 3.3 Environment

`cron/run-coordinator.sh:110` launches with
`env -u MOCK_LLM NARA_SKEPTIC=1 NARA_DEBATE=1 NARA_FRONTIER_SCREEN=1`.
`NARA_RESTATE_SKEPTIC` appears nowhere in cron or daemon env — that seam
is **dark in production**.

> **PIN — the one deliberate divergence.** D1 runs with
> `NARA_SKEPTIC=0`, `NARA_DEBATE=0`, `NARA_RESTATE_SKEPTIC=0`, all three
> set explicitly and **asserted in the artifact** (`env_pins_asserted`
> beside `env_pins_expected`).
>
> Justification, pre-stated: D1's question is about the **primary
> critic**. The skeptic and debate seams ARE the override chain, which is
> D2's subject and is measured deterministically over 59 real rows at
> zero call cost. Running them here would spend 3–7× the calls, put
> `vllm-qwen` in the measurement loop, and confound Q1 with Q2 — the
> exact conflation §1 exists to prevent. A **named, logged departure**
> (inviolate rule 7), not a silent one; §14 states what it costs.
>
> The coverage override INSIDE `critic_loop_v0` (`:738-762`) still fires
> unconditionally. That is production behavior and stays on — which is
> why every row records **raw AND final** (§8).

### 3.4 The fail-closed path, confirmed

- `thesis_to_experiment.py:150-159` — `is_eligible` requires
  `critic_verdict == "survives"` exactly.
- `finding_promotion.py:191-206` — the cheap gate IS the evidence ladder;
  it delegates to `evidence_ladder.derive_level` and requires **≥ L1**,
  whose `_rung_l1` additionally requires `retrieval.relevance` present and
  not low_confidence, `novelty.class == "novel"` (or surprising-vs-theory),
  and `redteam.verdict != "fatal_flaw"`. **This is the real rung, and it
  is the predicate D2 measures on** (VS-4).
- `critic_loop_v0.py:801-848` — a sub-agent `schema_mismatch` or `timeout`
  defaults to `undecidable` with `status: "passed"`. So `undecidable` is
  simultaneously a substantive verdict and the failure sink. The battery
  separates them (§8). **Neither branch has ever fired**: the record's
  only 2 `schema_mismatch` rows are May-era and predate the change (they
  defaulted to `survives`); all 59 recorded undecidables are
  `substantive`. A first occurrence would itself be a signal.

## 4. Faithful replay

### 4.1 The mechanism, and the exact envelope shape

The critic is a function of the claim **and** the retrieved neighbors,
read from the per-iteration cache, never from the caller:

- `critic_loop_v0.py:610` — `iteration_cache.read_entry(iteration_id, "retrieval")`
- `:619` — `neighbors = retrieval["result"]["neighbors"]`
- `:653-660` — `retrieval["result"]["relevance"]["low_confidence"]` drives
  the `RETRIEVAL RELEVANCE WARNING` injected into the user prompt
- `:668-681` — `read_entry(iteration_id, "novelty")` drives the
  `NOVELTY CONTEXT` block, injected only on `class == "rediscovery"`

**Faithful replay = seed the cache, then call by id** — exactly the
staging pattern the worker's own `__main__` smoke uses (`:862-876`), so
the seam is production-faithful by construction rather than by
resemblance.

> **PINNED SOURCE AND SHAPE.** The manifest copies the **cache** file
> `run_state/iteration_cache/<id>/retrieval.json` **verbatim** — the full
> worker envelope `{status, result:{k, neighbors, latency_ms, escalation,
> relevance}, errors, parent_request_id}`. It does **not** copy the
> `loop_memory` block, which is FLATTENED (no `result` wrapper) and would
> make the worker return `status: "error"` at `:611-630` **after the
> calls were spent**. The novelty envelope is copied the same way where
> one exists — all 156 critique-bearing rows have a cache entry for both
> keys, and all 26 fixtures carry a novelty envelope.
>
> **Build-time cross-check, hard:** a fixture is REFUSED unless the cache
> copy and the loop_memory copy agree by sha256 on **neighbors** AND on
> **relevance**. All 156 agree. Two unit tests assert the seeded shape
> against `critic_loop_v0`'s reader.

### 4.2 Relevance is REPLAYED, never recomputed (VS-3)

`workers.retrieval_relevance.relevance()` is a pure function — no
embedding, no LLM — so recomputing it is free. The builder does recompute
it, **as a diagnostic only**, recording the result and the arguments
passed (`anchor_cosine`, `topicality`, taken from the recorded block;
`None` means the R0/R0b anchor rules cannot fire, which reduces exactly
to legacy behavior). It is **not** used to shape any replay, because it
disagrees with the record materially:

- recomputing with `topicality=None` reclassifies **35 of 36** recorded
  `off_domain` rows to `ok` (35 of them fired **R0**, the LLM topicality
  judge, whose input no offline recomputation has);
- recomputing with the **recorded** topicality and anchor still diverges
  on **20 of 119** relevance-bearing rows, because **D-075 R2** demoted
  R0 for hypotheses matching a curated `DOMAIN_ANCHOR_PHRASES` entry and
  most of the record predates it.

**7 of the 26 fixtures diverge** under recomputation; the ids are listed
in `manifest_meta.json`. The divergence is a first-class reported fact,
not a footnote: **the relevance instrument itself is not stable across
the record.**

The prompt-shape consequences are derived from the **replayed** envelope
and frozen per fixture, checkable before any call:
`relevance_warning_fires`, `novelty_context_fires`,
`coverage_override_would_fire_on_survives`. A build gate asserts
`relevance_warning_fires == (stratum == "S3")` for every fixture.

### 4.3 Fidelity hazards, stated

**Mid-flight retrieval.** `critic_loop_v0.py:641-648, 705-706` give the
sub-agent a live `query_chroma` tool, so replay is **NOT hermetic**: a
mid-flight query hits today's Chroma, which the arxiv cron mutates.
Historically: 1 turn on 113 calls, 2 turns on 42, never more against a
6-turn budget — so **≈27% of production critic calls retrieve
mid-flight**. Pre-stated handling: the driver records per row whether a
second turn occurred (`mid_flight_retrieval_inferred`), reports those
rows as a **separate split**, and **NEVER excludes them from any
denominator** — excluding them after seeing verdicts is exactly the move
the readjudication prereg forbids. If it fires on **> 50%** of an arm's
calls the drift exposure is material and goes in the headline
(`material_drift_exposure`, computed).

**Chunk truncation.** The prompt truncates every neighbor's `chunk_text`
to 600 chars (`:199-201`); 57.1% of recorded neighbors exceed it. For a
historical replay this is production behavior reproduced exactly, so it
is fidelity, not a hazard. Recorded per fixture as
`pack.n_chunks_over_prompt_window` beside `prompt_window_chars`.

### 4.4 Every exclusion happens at BUILD time

`build_manifest.py` refuses to emit any fixture that is outside the era
bound, lacks a `critique` block, has `subagent_status != "passed"`, has
empty hypothesis text, lacks a cache envelope, has empty/non-list
neighbors, or fails the cache↔loop_memory sha256 cross-check. **A
`status != "passed"` return at RUN time is therefore a DRIVER DEFECT, not
a finding**, and trips run-validity bar V1.

**Exclusions are never silent.** Every rejected candidate is recorded
with its reason and id; counts by reason are in `manifest_meta.json` and
reconcile to the total (tested). Actual build:

| reason | n |
| --- | ---: |
| `no critique block` | 11 |
| `critic subagent_status='schema_mismatch' (not 'passed')` | 2 |
| `critic subagent_status=None (not 'passed')` | 1 |
| S2 `survives` pool: not in the first 4 by sha256 | 60 |
| S2 `restated` pool: not in the first 2 by sha256 | 17 |
| S2 `falsified` pool: not in the first 2 by sha256 | 4 |
| S3 pool: not in the first 8 by sha256 | 28 |
| **total** | **123** |

153 of 167 rows are usable; 26 are selected.

## 5. Fixtures — 26, three strata, ALL historical (claim, pack) pairs

Selection rules are locked. Row order within an arm is `order_key` =
`sha256(fixture_id)` ascending, tie-broken by `fixture_id`, computed once
at build and identical across arms.

### 5.1 S1 — H1-POPULATION CENSUS (10). **Not a sample.**

Every row in the entire record whose critic verdict is NATIVE
`undecidable` on an adequate pack. `S1_EXPECTED_N = 10` is pinned: if the
population resolves to any other count the builder **refuses**, because a
census that quietly re-samples is not a census (tested).

These fixtures carry **NO label.** The battery measures whether the
recorded verdict **reproduces**, not whether it was **correct** — no
non-circular correctness label exists for these rows and none is
invented.

### 5.2 S2 — DECISIVE-ADEQUATE CONTROL (8)

Rows where the critic reached a decisive NATIVE verdict on an adequate
pack. Quota **4 `survives` / 2 `restated` / 2 `falsified`** so the two
rare classes are represented (pools: 64 / 19 / 6); within each class the
pick is `sha256(iteration_id)` ascending — **blind to content**.

The recorded verdict is a **self-consistency comparator, not ground
truth**: it is the same instrument's earlier output on the same pack.
Stated that way in every `label_rationale` and in the artifact.

### 5.3 S3 — FLAGGED-PACK CONTROL (8)

Rows whose recorded relevance is `category == 'off_domain'` with
`low_confidence == True`, so the replay carries the RETRIEVAL RELEVANCE
WARNING verbatim, exactly as production did. Pool 36; 8 picked blind by
`sha256(iteration_id)`.

Scored on **`verdict_raw`**, because the coverage override fires
unconditionally after the sub-agent speaks. Not pre-ordained: across all
36 such rows the sub-agent's raw verdict is `undecidable` on only **19**
(the 8 selected have recorded raw verdicts 5 `undecidable` / 2
`survives` / 1 `restated`).

### 5.4 The obedience limit, stated plainly — it cannot be designed away

**Every genuinely insufficient pack in the record carries the warning.**
There is not a single `off_domain` row with `low_confidence == False` (36
of 36 are True), and the warning fires iff `low_confidence` is true. So a
history-only fixture set **cannot** separate "the critic detected that
the pack does not bear on the claim" from "the critic obeyed an
instruction printed in its own prompt." S3 measures the two **jointly**
and the artifact says so.

The only separator is a **warning-suppressed probe** (§7.2), which is by
construction **not production-faithful**. It is offered as an
owner-elected arm with a pre-stated executable reading rule, and it is
underpowered — which is stated in the rule itself rather than discovered
afterwards.

## 6. Ground truth: the honest count, and why it anchors nothing

`memory/loop_feedback.jsonl` is the only non-model label source in the
apparatus. Using recorded **verdicts** as labels is legitimate; inviolate
rule 9 protects the human's reflective **prose**, which this battery does
not reproduce, summarize, or interpret. Complete census: **7 rows, 6
distinct `iteration_id`s** (`iter-2026-06-05-002` appears twice).

| iteration_id | verdict | what the note supports | usable as a critic label? |
| --- | --- | --- | --- |
| `iter-2026-06-05-003` | valid | names VCG strategyproofness as the rediscovered theorem | the only merit-defensible one → `restated` |
| `iter-2026-06-05-001` | valid | a chain-health attestation | weak: licenses `not-falsified` only — and `not-falsified` **includes** `undecidable` |
| `iter-2026-06-10-003` | valid | a plumbing acceptance test | same weakness |
| `iter-2026-06-10-002` | invalid | no stated reason | no |
| `iter-2026-06-05-004` | invalid | no stated reason | no |
| `iter-2026-06-05-002` | needs_revision | procedural | no |
| *(superseded row)* | invalid | UI test | no |

> **STATE IT PLAINLY, DO NOT INFLATE IT. N = 1.** One merit-defensible
> positive critic label exists in the entire human-gate ledger, plus 2
> weak exclusion-flavored anchors whose `not-falsified` reading **includes
> the very verdict under study**. All three are June-register; the ledger
> contains **zero** August-register labels, and August is where the
> blockage lives.
>
> **v2 consequence: the gate ledger anchors ZERO fixtures and ZERO bars.**
> v1 put 3 of 32 fixtures on it, two of which could be scored as errors
> for emitting a verdict their own anchor permits. That is removed
> entirely. A further limit even on the N=1: gate verdicts label
> **iterations**, not literature verdicts, and
> `valid`/`invalid`/`needs_revision` does not project onto
> `survives`/`falsified`/`restated`/`undecidable`.
>
> **Any report from this battery that describes itself as "validated
> against human ground truth" is overclaiming, and §14 forbids it.**

## 7. Arms

### 7.1 Arm `production` — MANDATORY, the whole battery

Production as deployed: `CRITIC_BACKEND=vllm-gemma`, the
`CRITIC_AGENT_SYSTEM_PROMPT` currently in `workers/critic_loop_v0.py`,
budgets `6 / 90.0`, override seams pinned off (§3.3). **26 calls, all 26
fixtures.**

**There is no prompt-revision arm** (VS-6). The only stratum where a
revision could show a reduction is S2, 8 fixtures with a reference
expectation of **≈ 1** undecidable at the measured production rate of
0.135 — and lower, since those rows were already decided. **No arm can
demonstrate a reduction of K ≥ 2 against a baseline of ≈ 1**, so any
adoption rule for such an arm would be unfalsifiable theatre. Stating the
arithmetic is cheaper than spending 26 more calls to discover it.

### 7.2 Arm `warning-suppressed-probe` — OWNER-ELECTED, 8 calls, a PROBE

The S3 fixtures only, replayed with the recorded relevance block mutated
so `low_confidence = False` and `category = "ok"` — every neighbor,
score, and `chunk_text` byte-identical to the recorded pack; only the
warning-triggering fields change. The mutation is stamped into the
replayed envelope (`probe_mutation`) and the envelope's sha256 is
recorded per row, so the difference is visible in the artifact.

**Labelled a PROBE everywhere it is reported.** It is NOT
production-faithful; it exists solely to separate DETECTION from
OBEDIENCE (§5.4). The driver **refuses** it (exit 5) without
`--probe-ratified`, which the owner supplies only after electing it at
lock.

**Pre-stated comparison rule — executable, not prose**
(`driver.paired_probe_comparison`, unit-tested at and either side of its
threshold): the two arms are compared **paired on the same 8 fixtures**;
an effect is read **ONLY** at p < 0.05 on the exact two-sided sign test
over **discordant** pairs. At 8 paired fixtures that requires **≥ 6
discordant pairs all moving the same way** (6-0 → p = 0.0313; 5-0 →
p = 0.0625, **not** an effect), and **any reversal kills it** (7-1 →
p = 0.0703, **not** an effect). **The probe is underpowered by
construction; a null result licenses nothing** — stated in the rule
itself.

Arms are **BLOCKED — one arm per process** (R1a / readjudication
precedent: `agent_wrapper.wrapper.MEMORY_LOG` is process-global, so
per-arm calls-log isolation requires a fresh interpreter).

## 8. Verdict recording semantics

Verdicts are recorded **exactly as returned** and never coerced
(inviolate rule 4). Every row records three fields:

| field | source | meaning |
| --- | --- | --- |
| `verdict_raw` | `verdict_overridden_from` if present, else `verdict` | **what the sub-agent itself said.** Scored by the bars. |
| `verdict_final` | `result.verdict` | what the worker returned, post-coverage-override. Reported alongside. |
| `undecidable_kind` | derived | `substantive` \| `schema_mismatch` \| `timeout` \| `worker_error` \| `unknown` |

`undecidable_kind` exists because `:801-848` makes `undecidable` both a
substantive verdict and the failure sink. **The discrimination bars score
SUBSTANTIVE rows only; a failure-sink row leaves the discrimination
denominator entirely and is charged to V1** (tested). A failure-sink
`undecidable` scored as a judgment would let a broken instrument look
merely cautious.

## 9. Bars — LOCKED, independent, integer thresholds

Each bar stands alone (inviolate rule 4). A near miss is a failure. **The
driver evaluates the run-validity bars FIRST and prints them before any
statistic.** Arithmetic: Appendix B. Denominators: Appendix C, frozen as
explicit fixture-id sets in `manifest_meta.json`.

### Run-validity bars — evaluated first; failing either VOIDS the arm

**V1 — parse health. HARD.** At most **2** of the arm's calls may be
non-substantive (`undecidable_kind ∉ {None, "substantive"}` OR worker
`status != "passed"`). Calibration: the historical base rate is 153
`passed` / 2 `schema_mismatch` / 1 null across 156 recorded critic calls,
so ≤ 2 of 26 is generous against production behavior while still catching
a serving regression. Any `worker_status != "passed"` is a **driver
defect** (§4.4), reported as such and never as a finding.

**V2 — serving identity. HARD.** A `/v1/models` probe **before and after
each arm**; the served-model list compared; the vLLM image digest
(`run_state/vllm_image.digest`) and `wrapper.MODEL_VERSION` recorded. Any
mismatch voids the arm. (Readjudication F2 precedent — a silently
re-seated backend is otherwise indistinguishable from a finding, and this
repo has been bitten by exactly that.)

### Discrimination bars — DEGENERACY GUARDS, scored on `verdict_raw`

**C1 — NOT a rubber stamp.** `undecidable` (raw) on **≥ 2 of the 8 S3**
fixtures. False-void at the recorded reference rate (19/36 = 0.528):
**0.0246**. Power: an instrument that never says `undecidable` fails with
probability **1.0000**.

**C2 — NOT a condemner.** `undecidable` (raw) on **≤ 4 of the 8 S2**
fixtures. These 8 rows were **decided** by this same instrument on this
same pack, so the reference expectation is near zero; false-void at 0.135
is **0.0018**. Power: an always-`undecidable` instrument fails with
probability **1.0000**.

> **C1 ∧ C2 is a DEGENERACY GUARD, never an endorsement.** Each degenerate
> instrument fails exactly one of them with certainty. But **a uniform
> 4-way guesser passes the pair with probability 0.62** — this pair does
> not separate a good instrument from a random one, and the driver's
> artifact says so in the same object as the result. There is no
> accuracy bar in this battery, because no non-circular label set exists
> (§6).

### Estimates — reported with exact CIs, NO pass/fail

**E1 — does a recorded `undecidable` reproduce?** On the **S1 census**:
the count of the 10 that replay to a **DECISIVE** raw verdict
(`survives`/`restated`/`falsified`/`refuted`), with an exact
Clopper-Pearson 95% CI.

Pre-stated readings, fixed now:

| E1 outcome | reading | remedy it points at |
| --- | --- | --- |
| **≥ 7 of 10 decisive** (CI at 7/10: [0.347, 0.933]) | the recorded undecidables are substantially **NOT STABLE** | a **stability** fix — self-consistency / retry-on-undecidable. NOT a prompt rewrite, NOT retrieval. |
| **≤ 3 of 10 decisive** (CI at 3/10: [0.067, 0.653]) | the recorded undecidables are the instrument's **STABLE position** | prompt semantics or retrieval. A retry would only re-confirm. |
| **4–6 of 10** | **INDETERMINATE at n = 10** | none. Report the interval and stop. |

> S1 is a **CENSUS**, so this interval expresses the critic's
> **call-level stochasticity**, not sampling error over rows. The 3-vs-7
> intervals overlap on [0.347, 0.653]: these are **directional readings,
> never significance claims**, and the report states that beside the
> number.

**E2 — self-consistency on already-decided rows.** Agreement between the
replayed raw verdict and the recorded raw verdict on S2, with CI.
Agreement with the **same instrument's** earlier output — self-consistency,
**not accuracy**.

**E3 — raw undecidable rate on flagged packs.** On S3, with CI, reported
**against the recorded reference 19/36 = 0.528, CI [0.355, 0.696]**, and
read in terms of **interval overlap** rather than point comparison.

### Reported, non-binding

The full `recorded_verdict_raw × replayed_verdict_raw` confusion matrix,
the per-stratum verdict distributions, the era split, and the mid-flight
retrieval split. **Declared non-binding here** because at 8–10 per
stratum the per-cell counts cannot bear a threshold — saying so now is
cheaper than discovering it after the calls are spent.

## 10. Statistics, and the honest caveat at this N

Exact **Clopper-Pearson 95% CIs** on every reported rate, computed by the
unit-tested `clopper_pearson` from `bench/redteam_cal/driver.py` —
**reused, not re-derived**, with spot checks against independently
computed reference values in the test suite.

> **THE CAVEAT, reproduced verbatim in every artifact
> (`driver.CAVEAT`).** This battery measures REPRODUCIBILITY and
> DEGENERACY, **not accuracy**. No non-circular correctness label exists
> at usable N: the human gate ledger holds 7 rows / 6 iteration_ids and
> exactly 1 merit-defensible positive critic label, all June-register.
> C1 and C2 together kill the two degenerate instruments with certainty
> (an always-undecidable instrument fails C2 with P = 1.0; a
> never-undecidable one fails C1 with P = 1.0) but a uniform 4-way
> guesser passes the pair with P = 0.62, so the pair is a DEGENERACY
> GUARD and never an endorsement. E1/E2/E3 are ESTIMATES with exact
> Clopper-Pearson intervals and carry no pass/fail.
>
> **What it cannot do:** estimate the production over-emission rate
> (already a census — 10/120 all-time, 7/52 August), distinguish a good
> instrument from a mediocre one, separate detection from obedience on
> flagged packs without the non-production-faithful probe, or say
> anything whatsoever about the 19 flagged-pack NATIVE rows or the 30
> override rows.

## 11. Artifacts, provenance, and operational rules

`bench/critic_cal/runs/<arm>_<stamp>.json`, mirroring R1a and
readjudication. Provenance block: prereg path; git commit; manifest path
+ sha256; prompt source + sha256; backend + `default_model` + resolved
`base_url`; pinned budgets (`6 / 90.0`); the **verbatim seam string**;
`/v1/models` probes **before and after**; vLLM image digest;
`wrapper.MODEL_VERSION`; the env-pin triple **asserted beside expected**;
`mock_llm_present`; the named cache-write exception; the verbatim
seam-divergence statement; started/ended.

Per row: `{fixture_id, iteration_id, stratum, order_key, era,
cache_iteration_id, pack_sha256, envelope_sha256_replayed,
neighbor_doc_ids, relevance_warning_fired, novelty_context_fired,
recorded_verdict_raw, recorded_verdict_final, worker_status, verdict_raw,
verdict_final, verdict_overridden_from, override_reason,
undecidable_kind, contradicting_paper_id, rationale_digest,
subagent_status, subagent_turns_used, subagent_wall_seconds,
subagent_backend, subagent_model_DECLARED, mid_flight_retrieval_inferred,
wall_s, wrapper_request_id, errors}`.

Then: the **mandatory attribution sentence**, bars **V1–V2 first**, C1–C2,
the estimates, both confusion views, the splits, the §10 caveat verbatim,
the void semantics, and the per-run calls-log dump path.

> **VOID SEMANTICS AND RE-RUN POLICY** (imported verbatim from
> `PREREG_readjudication_2026-08-19.md:535-539`; carried as
> `driver.VOID_SEMANTICS` on every evaluation):
>
> *Void means: report the failure, report the arm as VOID, and stop. It
> does NOT mean re-thresholding, re-running until it passes, or explaining
> it away as an unlucky fixture set.* **Re-runs are capped at EXACTLY
> ONE**, permitted only for a V2 serving-identity void or an
> infrastructure abort, and when a re-run happens **BOTH runs and BOTH
> artifacts are reported.** This matters concretely: the most likely void
> here is a contention-induced timeout whose obvious remedy is "run it
> again when the backend is free", at which point the reported arm would
> be the one that got lucky.

**Operational rules, all learned the hard way:**

- **`--out` is REQUIRED and anchored to `REPO_ROOT`** by a named function
  (`driver.anchor_out`) called first thing in `run_arm`, before the
  manifest is read. A relative `--out` crashed a battery *after* its calls
  were spent (R1a). Tested.
- The driver **refuses to start** (exit 2) if `MOCK_LLM` is set — before
  any repo import, so nothing capable of making a call is even loaded.
  Tested two ways, including an assertion that the wrapper calls log is
  empty.
- The driver **refuses** (exit 4) if the manifest fails its 26-row /
  10-8-8 shape check; (exit 3) if the vllm-gemma bench lock is held;
  (exit 5) for the probe arm without `--probe-ratified`.
- **Backend contention guard (exit 3).** There is today no repo-wide lock
  covering `vllm-gemma` — `cron/run-coordinator.sh:33` flocks the
  coordinator only, and bench drivers take none. So this driver
  **creates** one: `flock -n` on `run_state/.bench-vllm-gemma.lock` for
  the duration of its arm. **Stated as new work, not as an existing
  mechanism.** Until the other bench drivers adopt it, it protects
  against a second *critic* battery only — **the re-adjudication battery
  predates it, so D1 must be started by hand only after the integrator
  confirms readjudication has released the backend.**
- **CACHE WRITE — A NAMED EXCEPTION.** The battery writes nothing to
  `memory/loop_memory.jsonl`, `memory/idea_ledger.jsonl`, or any
  `run_state/` state file. It **does** write
  `run_state/iteration_cache/critcal-<fixture_id>/{retrieval,novelty}.json`
  — required by the production seam (§4.1). Namespace pinned and
  verified non-colliding (§O-3). **The 26 directories are RETAINED after
  the run as reproducibility artifacts.** Plus its artifact, its
  calls-log dump, and its rows in `run_state/week1.run.jsonl` (inviolate
  rule 6, `agent` field required).

## 12. Cost

| | calls |
| --- | ---: |
| `production` — 26 fixtures | **26** |
| `warning-suppressed-probe` (owner-elected, S3 only) | **8** |
| **Total** | **26 or 34** |

Wall clock, grounded in 155 recorded production critic calls: all —
median 2.7 s / mean 4.6 s / p90 5.5 s / max 68.7 s; **August only (n=73)
— median 2.8 / mean 3.5 / p90 5.7 / max 7.2**. August is the right
reference; the 68.7 s outlier is June-era.

- **Expected ≈ 90 seconds** for the production arm (26 × 3.5 s).
- **Range 1.2–2.5 minutes.** Hard ceiling 39 minutes if every call
  saturates the 90 s wall; a **15-minute per-arm abort** is set well
  below that, and tripping it is itself a finding about serving health.

This is a **cheap** battery — about a tenth of readjudication's 248
calls. The binding constraint is not cost but **`vllm-gemma`
contention**. Budget accounting: bench drivers run out-of-band w.r.t. the
coordinator's daily ledger (cap 60, D-063; precedent R1a's 72 calls on
2026-08-18). At 26–34 calls this is within the cap's spirit either way;
flagged for the owner in §21 rather than assumed.

## 13. D1 disposition table — pre-stated. **No option auto-executes.**

| outcome | what the report SAYS | what it LICENSES | what it does NOT license |
| --- | --- | --- | --- |
| **V1 or V2 fails** | the arm is **VOID**; the failure is reported with its cause | at most ONE re-run, only for a V2 void or infra abort, with both artifacts reported | any statement about the critic; any re-thresholding; a second re-run |
| **C1 fails** (< 2 of 8 raw undecidable on flagged packs) | the instrument is a **rubber stamp** on flagged retrieval: it does not reach for `undecidable` even when the apparatus flagged the pack and its own prompt told it to | commissioning a critic-instrument replacement; and it makes the coverage override at `:738-762` **load-bearing rather than belt-and-braces**, which the owner should know | any claim that the 10 S1 undecidables are wrong |
| **C2 fails** (> 4 of 8 raw undecidable on already-decided rows) | the instrument is a **condemner**: it turns claims it previously decided into `undecidable` on the same pack | treating recorded `undecidable` verdicts as low-information; prioritizing an instrument fix over a semantics ruling | adopting any specific replacement — none is specified here |
| **C1 and C2 both pass** | the instrument is **not degenerate in either direction** | nothing on its own. **A uniform 4-way guesser passes this pair with P = 0.62** | *any* reading as calibration, exoneration, or accuracy. The report must not use the words "well calibrated" |
| **E1 ≥ 7 of 10 decisive** | recorded undecidables are largely **unstable** | commissioning a **stability** remedy (self-consistency / retry-on-undecidable at the critic seam) as its own prereg | a prompt rewrite; a retrieval change; unblocking any cluster by fiat |
| **E1 ≤ 3 of 10 decisive** | recorded undecidables are the instrument's **stable position** | moving the diagnosis to prompt semantics or retrieval adequacy — **and, from §0.4, noting that a critic fix moves at most 8 of 20 open clusters** | a retry/self-consistency remedy; any claim the verdicts are *correct* |
| **E1 4–6** | **indeterminate at n = 10** | nothing | escalating n on this fixture set — the census is 10; there are no more rows |
| **E1 ≥ 7 still-undecidable AND C2 ≥ 3 of 8** | the instrument reaches for `undecidable` stably and also on decided rows | commissioning a **prompt-revision arm as a SEPARATE prereg**, with its own adoption rule and its own power computation against the then-measured baseline | running such an arm under this prereg — there is no headroom for it here (§7.1) |
| **the honest null** (all bars pass, E1 lands 4–6) | the battery **neither exonerates nor indicts** the critic; the 26 calls bought a degeneracy exclusion and an indeterminate stability estimate | reporting exactly that, and moving the next increment of effort to D2's ruling and to the 2 clusters that need an **experiment** | describing the battery as validating the critic; carrying any of its numbers into a claim about the 59 |

## 14. What D1 does NOT establish

1. **It does not answer Q2.** The primary critic said `survives` on all 30
   override rows. **A recalibrated critic would not unblock a single one
   of them.**
2. **It does not calibrate the critic.** It has no accuracy bar because
   it has no non-circular labels (§6). It measures reproducibility and
   degeneracy.
3. **It is not validated against human ground truth.** N = 1
   merit-defensible label, June-register, anchoring nothing. Any claim
   otherwise is overclaiming.
4. **It says nothing about 49 of the 59 undecidables** — not the 19
   NATIVE-on-flagged rows, not the 30 overrides. The attribution sentence
   is mandatory precisely so no reader can make that leap.
5. **It cannot separate detection from obedience** on flagged packs
   without the non-production-faithful probe, and the probe is
   underpowered (§7.2).
6. **It measures the critic with the override seams OFF** (§3.3), so it
   does not measure the production pipeline's end-to-end verdict
   distribution. That is D2's territory, over real rows.
7. **It does not establish that production retrieval is adequate.** The
   adequate/flagged split is the apparatus's own relevance instrument's
   judgment — and §4.2 shows that instrument is itself not stable across
   the record.
8. **Replay is not hermetic** (§4.3): ≈27% of calls retrieve mid-flight
   against a drifted corpus.
9. **It licenses no production change by itself.** §13 is the complete
   disposition set and **no option auto-executes.**

---

# DELIVERABLE 2 — OVERRIDE-CHAIN AUDIT

**Deterministic. ZERO model calls. Pure analysis over the existing
record.** Runnable immediately, in parallel with the re-adjudication
battery, with no backend contention whatsoever. **Already built and run:**
`bench/critic_cal/audit_overrides.py` →
`bench/critic_cal/runs/override_audit_2026-08-19.json`.

## 15. The decision question

> **DQ.** Should a bounded adversarial debate that ends **UNREFUTED** —
> `verdict='inconclusive'`, especially at `stop_reason='round_cap'` —
> downgrade a primary-critic `survives` into a rung-blocking
> `undecidable`? Or is a claim that **survived** literature review and
> then **survived** a bounded adversarial debate without being refuted
> evidence **FOR** advancing it?

**This prereg does not decide DQ and must not be read as leaning.** The
measurement is the deliverable; the owner rules on the semantics.

The question has force because of §0.3: **24 of the 30 downgrades
involved no assertion of refutation by anything** — 7 ran out of rounds,
12 were statements about corpus coverage, 5 were infrastructure failures.
Six asserted a refutation, and those six are not in dispute. And because
of §0.4: the override chain costs a rung on **7** rows, all
`debate inconclusive` with `redteam = proceed` — a sharper and more
defensible case than v1's 18.

## 16. Method — as built

`bench/critic_cal/audit_overrides.py`. Deterministic, no LLM, no network,
no writes outside its `--out` artifact (required; anchored to
`REPO_ROOT`). Unit-tested under `MOCK_LLM=1`.

### 16.1 Inputs (read-only), all sha256'd into the artifact

`memory/loop_memory.jsonl` (167), `memory/idea_ledger.jsonl` (329),
`memory/loop_feedback.jsonl` (7).

### 16.2 Per-row output — for EVERY row, not just undecidables

`{iteration_id, started_at, day, has_critique, override_class,
override_class_rollup, override_reason, asserted_refutation,
infra_flavored, skeptic_infra_error_flag, undecidable_kind, pack_state,
relevance_category, relevance_low_confidence, subagent_status,
subagent_turns_used, subagent_wall_seconds, debate_verdict, debate_rounds,
debate_stop_reason, skeptic_verdict, skeptic_backend, skeptic_model,
novelty_class, redteam_verdict, gate_status, verdict_raw, verdict_final,
l1_level_raw, l1_level_final, l1_missing_final, l1_raw, l1_final,
t2e_eligible_raw, t2e_eligible_final, blocked_by_override,
t2e_blocked_loose}`.

### 16.3 Classification rules — pinned

- **`override_class` keys on the `override_reason` PREFIX**, never a
  substring. Table: `relevance category ` → RELEVANCE_CATEGORY;
  `relevance low_confidence is true:` → RELEVANCE_LOWCONF (a live code
  path at `:750-754`, unfired in the record); `debate verdict=` → DEBATE;
  `skeptic attack_verdict=` → SKEPTIC; `restatement skeptic (` →
  RESTATE_SKEPTIC (live at `:526-529`, dark in production, unfired);
  absent `verdict_overridden_from` → NATIVE. **Anything unmatched is
  OTHER and OTHER RAISES**, so a new seam cannot pool into a silent
  bucket.
- **`pack_state`** ∈ `adequate | flagged | absent`, from the relevance
  block recorded at the time — the split that scopes everything (§0.1).
- **`asserted_refutation`** is True iff the overrider's own verdict was
  `refuted`. Coverage overrides and every `inconclusive` are False.
- **`infra_flavored`** is True iff `skeptic_infra_error` is set OR
  `debate.stop_reason == "challenger_error"` OR the reason contains
  `unparseable or off-enum`. Both the flag count (0) and the
  `infra_flavored` count (5) are reported side by side, with a note
  saying which is which and why they differ.

### 16.4 Downstream cost — BOTH predicates, named apart (VS-4)

```
l1_raw    = derive_level(row with critic's OWN verdict) >= L1
l1_final  = derive_level(row as recorded)               >= L1
blocked_by_override = l1_raw AND NOT l1_final            # THE quantity: 7

t2e_eligible_raw/final = is_eligible(novelty, verdict, low_confidence)
t2e_blocked_loose      = t2e_raw AND NOT t2e_final        # LOOSE BOUND: 18
```

`blocked_by_override` is defined on the **real L1 rung** — the one
`finding_promotion.py:191-206` gates on, which additionally requires
relevance ok and `redteam != fatal_flaw`. `t2e_blocked_loose` is reported
beside it, explicitly labelled a loose upper bound, with the **11** rows
already below L1 for other reasons listed by id **and by failing term**.

Cluster state is reconstructed with `workers.idea_ledger.load_state` —
the canonical **file-order** fold (the ledger has 37 duplicate-timestamp
groups, one shared by 190 events, so a timestamp sort has no defined
answer). The current iteration of a cluster is its LAST member present in
loop_memory; **agreement across three candidate orderings is computed and
reported** (`reconstruction_disagreements: []`). For each open cluster:
its level, its failing terms, and the **counterfactual** level if the
critic verdict were `survives`.

### 16.5 Determinism and coverage — enforced, not asserted

Every emitted collection is explicitly sorted; no dict/set iteration
order reaches the output. Tested: invariance under **shuffled loop_memory
order** and under **three PYTHONHASHSEEDs**, each in a fresh interpreter,
compared by artifact sha256. Hard invariants raise `AuditInvariantError`
and write nothing:

| invariant | status on the live record |
| --- | --- |
| rows read == rows emitted | **167** ✓ |
| `override_class` counts sum to total rows | ✓ |
| undecidable class counts sum to the undecidable total | **59** ✓ |
| undecidable `(class, pack_state)` counts sum to the total | ✓ |
| **single-level override** holds on every row | ✓ |
| no OTHER-class `override_reason` (prefix table complete) | ✓ |

The single-level-override invariant is asserted rather than assumed, and
its mechanism is stated: `verdict_raw = verdict_overridden_from or
verdict` is only correct because the coverage override (`:738-762`)
**precedes and short-circuits** the skeptic/debate seams (`:777+`, guarded
on `verdict == 'survives'`). A row violating it is flagged, not absorbed.

## 17. Reported outputs — with the ACTUAL numbers

1. **The four-way provenance census over time** (§0.1) — NATIVE 29 /
   RELEVANCE 12 / DEBATE 11 / SKEPTIC 7, by day, annotated with the
   regime marks. Per-day: NATIVE 8 (08-16) / 4 (08-17) / 4 (08-18);
   RELEVANCE 5 / 5 / 0; DEBATE 0 / 0 / 10, then 1 on 08-19; SKEPTIC
   scattered 07-05 → 08-16.
2. **The undecidable census by recorded pack state** (VS-2) — NATIVE
   **10 adequate / 19 flagged**; the mandatory attribution sentence.
3. **The production reference rates** (§0.2) — 10/120 all-time, 7/52
   August, by month.
4. **The assertion decomposition** (§0.3) — refutation asserted **6**;
   ran out of rounds **7**; corpus coverage **12**; infra **5**.
5. **Debate anatomy** — the `(verdict, stop_reason, turns)` joint
   distribution with the round-cap cohort split by cap value (4 at cap 6,
   3 at cap 4).
6. **`blocked_by_override`** — **7** on the real ladder (all
   debate-inconclusive with `redteam=proceed`), **18** on the loose
   predicate with the 11-row gap itemized.
7. **Cluster-level impact** — per open cluster, the failing terms and the
   counterfactual; **2 at L1 needing an experiment, 8 critic-only-blocked,
   10 blocked by other terms**.
8. **Infra** — flag 0 vs `infra_flavored` 5, side by side, with ids.
9. **Gate-ledger census** — 7 rows, 6 iteration_ids, and the statement
   that it anchors nothing.
10. **Regime-shift annotations** — D-071 (debate armed), D-075 R3a (cap
    4→6), D-075 R2 (phrase-anchor demotion), D-075 R3b (infra flag), all
    on 08-18. **Counts before and after a regime change are never pooled
    without the split being shown first.**

## 18. Readings — each marked SETTLED-AT-DRAFT or GENUINELY-OPEN (O-9)

v1 called these "fixed now, before the numbers are looked at" while
quoting its own computed answers. Marking them honestly:

| # | reading | status |
| --- | --- | --- |
| **R-a** | *Most survives-overrides asserted no refutation* → the override chain is not a refutation filter; it is an **uncertainty** filter that happens to share `undecidable`'s rung-blocking semantics. DQ is live and consequential. | **SETTLED AT DRAFT: 24 of 30 (80%).** Not a prediction. Reported as a finding. |
| **R-b** | *Most asserted a refutation* → the chain is doing what an adversarial gate should; `undecidable` is the wrong **label** for a refuted claim (the enum has `refuted`) and the fix is cosmetic. | **SETTLED AT DRAFT: FALSE (6 of 30).** |
| **R-c** | *`blocked_by_override` is small relative to the open-cluster stall* → the override chain is not the dominant binding constraint. **Threshold, stated now:** "small" means `blocked_by_override` accounts for **fewer than half** the open clusters that are below L1 (< 9 of 18). | **SETTLED AT DRAFT and TRUE: 7 rows, and only 7 of 20 open clusters carry a blocking override — under the stated half.** The diagnosis therefore must ALSO address the 8 critic-only-blocked clusters and the 2 that need an experiment. |
| **R-d** | *The round-cap cohort is concentrated at cap 6* → raising the cap 4→6 bought more turns and the same non-answer at higher cost; "raise the cap again" is not the remedy. | **SETTLED AT DRAFT: 4 of 7 at cap 6, 3 at cap 4.** Directional at n=7; reported as fractions with raw counts adjacent. |
| **R-e** | *The infra-flavored subset is non-trivial* → part of the blockage is not semantics at all and is fixed by making infra failures non-gating (the pattern D-075 R3b already established). **Severable from the DQ ruling.** | **SETTLED AT DRAFT: 5 of 30 (17%).** |
| **R-f** | **Do inconclusive-debate rows differ measurably from clean `survives` rows on any independent signal already on the row** (`redteam_verdict`, `novelty_class`, `gate_status`)? | **GENUINELY OPEN.** This is what selects between M2 and M3 in §19 and it is not answered by any count above. |
| **R-g** | **Which predicate term fails per open cluster**, and whether the failing-term distribution is stable as the ledger grows. | **GENUINELY OPEN** going forward; §0.4 settles the current snapshot only. |

**The genuinely pre-registered content of D2 is R-f and R-g.** Everything
else is a finding computed at draft time and is reported as such.

## 19. The alternative mappings — named, not chosen

For `debate verdict == 'inconclusive'` overriding a `survives`:

| # | mapping | what it does | what evidence selects it |
| --- | --- | --- | --- |
| **M1** | keep as-is — `inconclusive` → `undecidable` | status quo; blocks at L1 | R-b (**settled false**), or evidence that inconclusive debates track genuinely weak claims — i.e. **R-f resolving with a difference** |
| **M2** | `inconclusive` → `survives-with-caveat`, a new L1-eligible verdict carrying the debate transcript | unblocks; preserves the doubt as a durable annotation | R-a **plus R-f resolving with a difference**. Costs a schema-enum change and an `is_eligible` change: **spine edits, serial integrator only** |
| **M3** | `inconclusive` → `survives`, flagged with a non-gating `debate_advisory` | unblocks; cheapest; no enum change | R-a **plus R-f resolving with NO difference**. **Carries the D-053 risk explicitly: an advisory nobody reads is a fiction.** Selecting M3 requires naming who consumes the advisory and where it surfaces |
| **M4** | split by `stop_reason`: `defender_conceded` → `refuted`; `round_cap` → M2/M3; `challenger_error` → non-gating per D-075 R3b | treats the three debate endings as the different events they are | R-a **and** R-e together |

**ANALYST NOTE, separately labelled and NOT part of the neutral table
(O-9):** in my reading the three `stop_reason` values are plainly not the
same event, and M4 is the option the §0.3 decomposition most directly
supports. **This is an analyst opinion, not a finding, and the ruling is
the owner's.**

**One thing D2 cannot produce, stated plainly:** whether an unblocked
claim would have survived experimental contact. No amount of ledger
analysis reveals that. The only instrument that would is running some of
the blocked claims through to an experiment — a different, more expensive
study this prereg does not propose. **Note the coincidence worth acting
on: §0.4 shows 2 open clusters are already at L1 and blocked only by
`experiment_outcome absent`. That study has candidates waiting.**

## 20. What D2 does NOT establish

1. **It does not decide DQ.** It measures; the owner rules.
2. **It does not establish that the debate is wrong.** An inconclusive
   debate may correctly reflect a genuinely doubtful claim. D2 shows the
   mapping's **consequences**, not the debate's correctness.
3. **It does not establish that unblocked claims are good claims.**
4. **It cannot separate "the claim is hard" from "the debate is weak."**
   Both produce `inconclusive` at `round_cap`. Answering that needs a
   debate-quality instrument (transcripts judged against a rubric), out
   of scope here.
5. **It is observational and non-causal.** The 08-18 step change is
   confounded with everything else that shipped that day — D-071, D-075
   R2, R3a and R3b all landed together. The regime marks make the
   confound visible; they do not remove it.
6. **N is small in every cell.** 11 overriding debate rows, 7 round-cap,
   2 defender-conceded, 2 challenger-error. **Percentages over cells this
   small are reported as fractions with the raw counts adjacent** — "50%
   of defender_conceded" means "1 of 2". A formatting rule, not a
   suggestion.

---

## 21. Open questions for the owner — to settle AT LOCK

1. **Sequencing, re-derived from the settled C-4 (§0.4).** D2 is done and
   free. The critic is the binding constraint for **8 of 20** open
   clusters, not 20 — and **2 clusters need an experiment, not a
   critic**. Given that, is D1's 26 calls the right next increment, or do
   the 2 L1-ready clusters come first? My reading: run D2's result past
   the owner and start an experiment on the 2 L1 clusters; D1 is cheap
   enough to run alongside once readjudication releases the backend, but
   it is no longer the obvious first move. **The integrator's call.**
2. **The probe arm (§7.2):** elect it (+8 calls, `--probe-ratified`) or
   decline it and run single-arm? Declining leaves detection and
   obedience deliberately unseparated, which §5.4 already states.
3. **Budget:** 26 or 34 calls debited against the D-063 daily ledger
   (cap 60), or explicitly exempted as out-of-band bench work per the R1a
   precedent?
4. **The DQ ruling (§15/§19).** M2 would require edits to
   `schema/iteration_record.schema.json` and
   `orchestrator/thesis_to_experiment.py` — **shared-spine files, serial
   integrator only.** If M2 is a serious candidate, that constraint
   should shape who does the work.
5. **R-f (§18) is the one genuinely open question that selects between M2
   and M3** and it is answerable at zero call cost from the same ledger.
   Should it be added to D2 before lock, or is the M2/M3 choice being made
   on other grounds?
6. **Fixture review.** The 26 fixtures carry no author-supplied labels at
   all, so the "disputed label" risk is largely gone. What remains
   reviewable is the **stratum assignment** (which rests entirely on
   recorded fields) and the **S2 quota** (4/2/2). A disputed fixture is
   removed before lock, never after.

---

## Appendix A — verified counts (reproducible)

Computed by `bench/critic_cal/audit_overrides.py` at commit `dded258`
from `memory/loop_memory.jsonl` (167, sha256 `01ae8c7a542cf37d…`),
`memory/idea_ledger.jsonl` (329), `memory/loop_feedback.jsonl` (7). The
artifact carries all three shas so every figure below is reproducible
against a moving ledger.

**Verdicts (167 rows):** `survives` 67 · `undecidable` 59 · `restated` 23
· `falsified` 7 · no critique block 11.

**Undecidable provenance (59):** NATIVE 29 · RELEVANCE 12 · DEBATE 11 ·
SKEPTIC 7. Overridden from `survives`: **30**.

**NATIVE by recorded pack state (29):** adequate **10** · flagged **19**.

**Production reference (native undecidable / all adequate-pack calls):**
all-time **10/120 = 0.0833** [0.0407, 0.1479]; August **7/52 = 0.1346**
[0.0559, 0.2579]; 2026-05 0/28, 2026-06 2/25, 2026-07 1/15.

**Flagged-pack raw verdicts (36 rows):** `undecidable` 19 · `survives` 12
· `restated` 4 · `falsified` 1. Raw undecidable rate **19/36 = 0.528**
[0.3549, 0.6959].

**Survives-overrides by assertion (30):** refutation asserted 6 ·
round-cap inconclusive 7 (3 at cap 4, 4 at cap 6) · coverage 12 ·
infra-flavored 5.

**Downstream:** `blocked_by_override` (real L1 ladder) **7** ·
`t2e_blocked_loose` (is_eligible only) **18**, of which **11** were
already below L1 for other reasons.

**Open clusters (20):** at L1 already **2** · critic-only-blocked **8** ·
blocked by other terms **10** · reconstruction disagreements **0**.

**Critic telemetry (156 critique rows):** `subagent_status` — `passed`
153, `schema_mismatch` 2, `None` 1; **plus 11 rows with no critique
block** (the two populations v1 conflated as "12 rows carry no status").
`subagent_turns_used` — 1 turn on 113, 2 turns on 42, never more against
a 6-turn budget (**≈27% mid-flight retrieval**). Wall seconds — all:
median 2.7 / mean 4.6 / p90 5.5 / max 68.7; August (n=73): median 2.8 /
mean 3.5 / p90 5.7 / max 7.2.

**`undecidable_kind` over all 59:** `substantive` 59. `schema_mismatch` 0,
`timeout` 0. The failure-sink branches have **never fired** — the only 2
`schema_mismatch` rows are May-era and defaulted to `survives` under
pre-T1b code. A first occurrence of either is itself a signal.

**Neighbor chunk lengths (1600 recorded neighbors):** min 91, median
863.5, max 2521; **57.1% exceed the 600-char prompt window.**

**Relevance recomputation:** recomputing `relevance()` with
`topicality=None` moves **35 of 36** `off_domain` rows to `ok`;
recomputing with the recorded arguments still diverges on **20 of 119**
relevance-bearing rows; **7 of 26** manifest fixtures diverge.

**Human gate ledger:** 7 rows, 6 distinct `iteration_id`s, **1**
merit-defensible positive critic label, 2 weak exclusion anchors whose
`not-falsified` reading includes `undecidable`, **0** August-register
labels. **Anchors nothing.**

**Idea ledger:** 329 events; **37 duplicate-timestamp groups, largest
shared by 190 events** (why the fold is file-order, not timestamp-order).
`ts` is non-decreasing in file order across both ledgers.

## Appendix B — bar calibration, computed

Exact Clopper-Pearson 95% CIs:

| k/n | rate | 95% CI |
| --- | ---: | --- |
| 10/120 | 0.0833 | [0.0407, 0.1479] |
| 7/52 | 0.1346 | [0.0559, 0.2579] |
| 19/36 | 0.5278 | [0.3549, 0.6959] |
| 0/10 | 0.000 | [0.0000, 0.3085] |
| 3/10 | 0.300 | [0.0667, 0.6525] |
| 5/10 | 0.500 | [0.1871, 0.8129] |
| 7/10 | 0.700 | [0.3475, 0.9333] |
| 10/10 | 1.000 | [0.6915, 1.0000] |
| 0/8 | 0.000 | [0.0000, 0.3694] |
| 2/8 | 0.250 | [0.0319, 0.6509] |
| 4/8 | 0.500 | [0.1570, 0.8430] |
| 8/8 | 1.000 | [0.6306, 1.0000] |

**C1 (S3, n = 8, `undecidable_raw` ≥ 2) — false-void by true rate:**

| true rate | P(fail C1) |
| --- | ---: |
| 0.00 (never undecidable) | **1.0000** |
| 0.10 | 0.8131 |
| 0.25 | 0.3671 |
| **0.528 (the recorded reference)** | **0.0246** |
| 0.75 | 0.0004 |
| 1.00 | 0.0000 |

**C2 (S2, n = 8, `undecidable_raw` ≤ 4) — false-void by true rate:**

| true rate | P(fail C2) |
| --- | ---: |
| 0.083 (all-time reference) | 0.0002 |
| **0.135 (August reference)** | **0.0018** |
| 0.25 | 0.0273 |
| 0.50 | 0.3633 |
| 0.75 | 0.8862 |
| 1.00 (always undecidable) | **1.0000** |

**What the C1 ∧ C2 pair actually does:**

| instrument | C1 | C2 | passes pair? |
| --- | --- | --- | --- |
| always `undecidable` | pass (P=1.0) | **fail (P=1.0)** | no |
| never `undecidable` | **fail (P=1.0)** | pass (P=1.0) | no |
| uniform 4-way guesser (p=0.25) | pass P=0.633 | pass P=0.973 | **yes, P = 0.616** |
| behaves like the record | pass P=0.975 | pass P≈0.998 | yes |

**This is the honest headline: the pair excludes degeneracy with
certainty and excludes nothing else.** It is reported as a degeneracy
guard and never as an endorsement.

**Probe arm (§7.2), exact two-sided sign test over discordant pairs:**

| discordant split | p | effect read? |
| --- | ---: | --- |
| 5-0 | 0.0625 | no |
| 6-0 | 0.0313 | **yes** |
| 7-0 | 0.0156 | **yes** |
| 8-0 | 0.0078 | **yes** |
| 6-1 | 0.1250 | no |
| 7-1 | 0.0703 | no |

## Appendix C — frozen bar denominators (fixture-id sets)

Written into `bench/critic_cal/manifest_meta.json` at build time as
`bar_denominators`; reproduced here so no denominator can be re-read
after the numbers land (O-6). Manifest sha256
`0b992f536fbe07eab4a579f192a95aaac99125e081acf6caecd98fb346bceefc`.

**V1 — all 26 fixtures.**

**E1 (S1 census, 10):**
`S1-iter-2026-06-10-002`, `S1-iter-2026-06-19-011`,
`S1-iter-2026-07-05-002`, `S1-iter-2026-08-03-001`,
`S1-iter-2026-08-16-015`, `S1-iter-2026-08-16-016`,
`S1-iter-2026-08-17-002`, `S1-iter-2026-08-18-002`,
`S1-iter-2026-08-18-007`, `S1-iter-2026-08-18-015`.

**C2 and E2 (S2, 8):**
`S2-iter-2026-05-27-011`, `S2-iter-2026-05-27-023`,
`S2-iter-2026-06-05-006`, `S2-iter-2026-07-10-002`,
`S2-iter-2026-07-23-001`, `S2-iter-2026-08-16-003`,
`S2-iter-2026-08-17-012`, `S2-iter-2026-08-17-013`.
(recorded verdicts: 4 `survives`, 2 `restated`, 2 `falsified`)

**C1 and E3 (S3, 8):**
`S3-iter-2026-07-22-001`, `S3-iter-2026-07-23-002`,
`S3-iter-2026-07-26-001`, `S3-iter-2026-08-16-012`,
`S3-iter-2026-08-16-018`, `S3-iter-2026-08-17-001`,
`S3-iter-2026-08-17-018`, `S3-iter-2026-08-17-019`.
(recorded raw verdicts: 5 `undecidable`, 2 `survives`, 1 `restated`)

No `iteration_id` appears in two strata; asserted at build time and
tested.

## Appendix D — code and artifacts

| what | path |
| --- | --- |
| fixture manifest builder (0 calls, deterministic) | `bench/critic_cal/build_manifest.py` |
| frozen manifest + build meta | `bench/critic_cal/manifest.jsonl`, `bench/critic_cal/manifest_meta.json` |
| D1 run driver (one arm per process) | `bench/critic_cal/driver.py` |
| D2 override-chain audit (0 calls, deterministic) | `bench/critic_cal/audit_overrides.py` |
| D2 artifact (already run, read-only) | `bench/critic_cal/runs/override_audit_2026-08-19.json` |
| tests | `tests/test_critic_cal.py` |
