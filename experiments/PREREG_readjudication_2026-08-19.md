# Pre-registration — graveyard re-adjudication battery (D-076 follow-on) — v2

Status: **v2 after adversarial critique** (verdict FIX-REQUIRED: six
verdict-selecting flaws F1–F6, nine further flaws L1–L9). DRAFT, awaiting
owner ratification. **No calls until LOCK.**

This document is written **before any re-adjudication call exists**. Its
purpose is to make post-hoc rationalization impossible: the target set,
the arms, the statistic, the interpretability bars, the reading gates and
the full menu of dispositions are all fixed here, in advance of any
number.

**LOCK conditions.** This prereg locks at the commit that also contains,
side-by-side:

| Lock artifact | sha256 |
| --- | --- |
| `bench/readjudication/manifest.jsonl` (114 rows + meta) | `7ec63389ca9a0a9f789f28631e9adb8b5360aaa0842590f84843d3a9664b64f0` |
| `bench/readjudication/old_prompt.txt` (file bytes) | `c36843132924758367bb79420d57c6de231d876f6e9909ce934f308a946546eb` |
| the OLD system prompt *string* it carries (UTF-8) | `3433ac5d862d9e749f00455b0ed1d0b422b743c50202cb6fe45774c1445ae0bc` |
| the NEW system prompt string, live in `workers.redteam_critic` | `7d44820d99f71485b0734ad4362cb95212c0f327481c7de043d8079cc3f52dba` |
| `bench/redteam_cal/fixtures.jsonl` (R1a manifest, unchanged) | `1f8b738c509528a3e56549c851b482bcc1d36ee8aea3f97961f628b14e31cce4` |
| `memory/idea_ledger.jsonl` at manifest build | `d277f9bc924f00f00814b0dca40959fc87eb816a1dd63f9cff1e51c9f62a87b0` |

plus `bench/readjudication/driver.py` and `tests/test_readjudication.py`
green under `MOCK_LLM=1`.

After lock, no statistic, split, bar, exclusion rule, threshold, reading
gate or disposition option in this document may be added, removed, or
re-thresholded. Any analysis not named here is labelled **EXPLORATORY**
in the report and cannot support a disposition.

Prior art this battery matches by construction:
`experiments/PREREG_redteam_cal_2026-08-18.md` (v2, locked) and
`bench/redteam_cal/driver.py` (arm structure, exact Clopper-Pearson CIs,
provenance-split confusion, artifact provenance block, refusal exits).

---

## v2 changelog — what the critique changed and why

Each entry names the flaw, the change, and where it lives. Nothing here
was resolved by rewording: every fix is a constant, a bar, a denominator,
a refusal, or a pre-stated reading gate that the driver enforces.

| Flaw | Resolution |
| --- | --- |
| **F1** — the control suite was one-sided: no bar on the NEW arm's known-good controls, so a silently reverted NEW arm passed C1 with probability 1.0000, passed C2 trivially, and (in exactly the "graveyard is real" branch) passed C3 — net detection ≈ 0. | **New hard bar C4** (§4.3): NEW-arm `fatal_flaw` on **≤ 35% of parsed known-good controls** — R1a adoption bar 3 **verbatim**, not a new invention. Computed power in Appendix C: detects a reverted NEW arm with **P = 0.9990 at 7 parsed / 0.9999 at 12 parsed**; false-voids a genuinely good run with **P = 0.0002** (5% true false-condemn rate, 12 parsed) to **0.0257** (10% rate, 7 parsed). Also: the per-row prompt sha is **promoted from RECORDED to ASSERTED** (§2, §6 exits 6/7) — checked before *every* call, not once before the first. |
| **F2** — exits 3 and 8 compared a process constant to itself (`subagent_model` = `resolved_be.default_model` = `wrapper.MODEL` = `os.environ.get("VLLM_MODEL", …)`), so "serving drift refuses" was false — the same "printing a belief, not an observation" failure `ui/backend/served_models.py` exists to fix. | **Serving is now observed** (§2, §6, §8): `/v1/models` is probed **before the first call and after the last** and the served id is pinned in provenance (exit 9); **each row asserts the SERVER-reported name** — the wrapper record's `model` field is `resp.model` (`agent_wrapper/wrapper.py:125`, `orchestrator/subagent.py:175`), joined to the row by `wrapper_request_id` (exit 8). The vLLM **image digest** (`run_state/vllm_image.digest` = `sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9`) is pinned too. The declared `subagent_model` is still recorded, renamed `subagent_model_DECLARED`, and is **never** a serving check. |
| **F3** — the OLD arm is prompt-faithful but not worker-faithful; the infidelity inverts the semantics of the biggest bucket, and κ_old's denominator was the gameable one. | Three changes. (a) §3.4 and §7.2 now **state the R1b polarity change** (pre-R1b `schema_mismatch` **fail-opened to `proceed`**; `6ddcce5`, 2026-08-18T05:28Z, remapped it to `unscored` — **after** the last target, whose founding ended 2026-08-18T05:07:09Z) and the **three-draw selection conditioning** (`retries_used == 2` on 88/88), and κ_old is labelled a retest **biased upward, toward the prompt-attribution reading**. (b) **κ_old's primary denominator is now all N rows with `unscored` counted as NON-reproduction** — the same polarity φ already uses; parsed-only is reported as the secondary **upper bound**, never the headline. (c) **U is decomposed by NEW verdict** in the artifact, and §7.6 carries a pre-stated line for the OLD-unscored bucket. |
| **F4** — nothing gave φ a number to beat, so any φ was reportable as a finding. | §7.1 makes it a **required primary statistic** that φ is reported against the **same-run** NEW-arm proceed rate on known-bad and on known-good controls, with CP95s and both differences; §7.6 adds a **hard reading gate**: the "prompt attribution / the graveyard was an artifact" reading is **UNAVAILABLE** when φ's CP95 overlaps the same-run known-bad proceed rate. The **post-swap production kill count** (0 kills in 6 iterations at lock; re-measured at report time) is required context printed alongside φ. |
| **F5** — C3 pooled 113 rows and could hide up to 17 missing *target* verdicts that silently reshape φ, the 2×2 and the reopen set. | C3 is **split** (§4.3): **C3a** targets — unscored ≤ **13 of 88** (15%); **C3b** controls — unscored ≤ **4 of 24**. Both hard. And φ is **always** reported as the honest bound pair `[proceeds/N, (proceeds+unscored)/N]`; above **4** unscored target rows the point estimate **may not be quoted alone** (§5). |
| **F6** — the disposition menu left an unranked, data-dependent region, mixed actions with modifiers, and its ordering key preferentially reopened the clusters the evidence covers least. | §9 partitions **R exhaustively as (A, B, U∩R)**, gives **U∩R an explicit rank** in option (ii) and an explicit **in/out** in option (iv); (v)/(vi) are relabelled **modifiers M1/M2** and the actions (i)–(iv) are exhaustive and non-overlapping; the member-count ordering key is **demoted below** the founding-text coverage caveat, which §9 and §10 now state: for a multi-member cluster the evidence covers **only the founding member's text**. |
| **L1** — one target already carries a refined claim that a frontier reviewer vetoed, and §3.3 had no rule for it. | New exclusion reason **`cluster_refined_since_kill`** (§3.1 criterion 7). It fires on **`cl-iter-2026-08-15-004`** — 1 of 89 — so **N = 88**. Both of that cluster's texts (founding **and** refined) still ride as **EXPLORATORY sidecar rows**, judged by both arms, entering **no** bar, **no** statistic and **not** R. |
| **L2** — C2's stated calibration was wrong at several parse counts. | §4.3 replaces the prose claim with the **exact table by parse count** (Appendix C): false-fail at the R1a-observed 0.857 runs **0.0233 at 5 parsed** down to 0.0005 at 12; a non-condemner at 0.25 passes with up to **0.169 at 6 parsed**. Stated as the true bounds, not rounded down. |
| **L3** — `row_id` was never defined, so the "deterministic" order was not determined by the document. | §4.2 defines it: **cluster_id** for a target, **fixture id** for a control, `sidecar:<cluster_id>:<variant>` for a sidecar; key = `sha256(row_id.encode("utf-8"))`, ascending, **tie-broken by `row_id`**; §7.3's replicate subsample uses the same key (not a second one). |
| **L4** — a free per-row fidelity check on both arms was unused. | §7.4 makes **row-level replication against R1a** (identical 24 fixtures, identical prompt shas, one day apart; n = 24 per arm, CP95) a **required reported statistic**, with the two reference artifacts pinned by sha256. Descriptive — it gates nothing, but it is a second independent detector for the F1 revert. |
| **L5** — the historically judged text is not independently recoverable. | §3.2 now **says so plainly**: `workers/redteam_critic.py` passes no `log_path`, so every historical redteam turn went to the in-memory `MEMORY_LOG` and `logs/calls.jsonl` contains **zero** `subagent.redteam_critic` records. Byte-identity therefore rests on a **code-path argument**, cited line by line, and the claim is scoped accordingly. This battery's own prompts **are** put on disk (per-run `MEMORY_LOG` dump, joinable by `wrapper_request_id`); history's cannot be. |
| **L6** — denominator ambiguity in the headline phrase. | §7.1 pins the phrase — **"of the 88 re-adjudicated redteam-code kills"** — and requires **all three denominators printed once** (88 re-adjudicated / 112 kills / 132 clusters). |
| **L7** — §9(ii)'s throughput assertion was contradicted by the ledger. | §9 replaces the assertion with the **measured figure**: 9 `evidence_level_changed` events in the ledger's entire history over 6 distinct clusters; **5 clusters ever advanced above L0** (4 → L1, one of those on to L2), **2 of them later returned to L0**. N is the owner's pick against that number, not against a claim of tractability. |
| **L8** — two mechanical consequences of a mass reopen were unstated. | §9 states them: reopened clusters **re-enter the D-075 R4 matching pool** (`workers/consolidate_memory.py:188` excludes killed clusters, so 88 reopens become 88 new attractors every fresh item is matched against **before** minting), and `ui/backend/lab_todo.py:121` already lists `redteam_fatal_flaw` in `REFINABLE_KILL_CODES`, so a reopen changes what the human lab queue shows. Two verified reassurances and one semantic caveat are also on the record. |
| **L9** — Appendix B verified exactly, but target-vs-control contamination was never checked. | It is now a **lock-time refusal in the builder** (§3.1, `bench/readjudication/build_manifest.py::contamination_scan`, exit 4): id collision, exact text identity, and token-Jaccard ≥ 0.60 across the two sets. Measured clean: max cross-set Jaccard **0.2857** (`rtc-good-hist-03` vs `cl-iter-2026-06-05-003`). |
| (design change forced by the build) | **The arms are BLOCKED, one per process** (§4.2), not interleaved within one process as v1 §4.2 specified. `agent_wrapper.wrapper.MEMORY_LOG` is process-global, so a one-process design cannot give per-arm calls-log isolation, and a fresh interpreter per arm is what makes the prompt injection unambiguous (R1a precedent). What blocking costs — row-level *temporal* pairing — is bought back by F2's serving observations, which is what the temporal pairing was there to protect. Claim-level pairing (what McNemar needs) is unaffected. |

---

## 1. The question

On 2026-08-18T06:45Z the production redteam prompt was swapped (D-076).
The instrument it replaced was measured, on the R1a frozen manifest, as a
**constant condemner**: arm `gemma-current` returned `fatal_flaw` on 6 of
7 *parsed* known-good claims (5 further known-good rows came back
`unscored`) and on 12 of 12 known-bad.

The idea ledger holds 132 clusters: 20 open (18 L0, 2 L1), 112 killed.
**89 of the 112 kills carry kill code `redteam_fatal_flaw`, and every one
of them was adjudicated before the swap** — i.e. by the instrument D-076
measured as a condemner. One of the 89 has since been refined (L1, §3.1
criterion 7), leaving **N = 88** re-adjudicable targets.

> **Q1 (primary).** How much of the 88-cluster re-adjudicable redteam
> graveyard is an artifact of the miscalibrated instrument rather than of
> bad ideas?

Q1 alone is not answerable by re-running the new instrument, because the
adopted replacement (`gemma-revised`) is **more permissive by
construction** — 0/12 fatal on known-good, 9/12 on known-bad. A high
proceed rate on re-adjudication is *expected* and is **not by itself
evidence the old kills were wrong**. Separating "the instrument changed"
from "the kills were wrong" is the whole design problem, and it is what
the paired arms, the spiked controls, and the §7.6 reading gate exist to
do. **v2 makes the "expected" explicit and quantitative** rather than
leaving it as prose: φ is read against same-run comparators (§7.1) and a
reading is withdrawn when it cannot be separated from them (§7.6).

Two secondary questions ride along — Q2 for free, Q3 for 20 extra calls:

> **Q2.** Does the *old* instrument even reproduce its own kills? Every
> target's kill was one recorded `fatal_flaw` judgment on the exact text
> we will re-send. Re-running the old prompt on that text is a
> test–retest of the historical instrument at n = 88. If it does not
> reproduce, the graveyard is partly a **stochasticity** artifact, not a
> **prompt** artifact — a different defect with a different remedy. **The
> retest is conditioned on the selecting draw and is biased upward; §7.2
> states by how much this matters.**

> **Q3.** Is the new instrument's verdict itself stable? Measured on a
> locked 20-row subsample (§7.3), descriptive only.

---

## 2. Arms

Two arms, **paired on the same claim text**, same seam, same budgets,
same locked row order, **run one arm per process** (§4.2). Pairing on the
text is what isolates the instrument from the claim: each claim is judged
by both instruments on identical bytes, so any difference between arms
cannot be a difference between claims.

| Arm | Prompt | sha256 of the system prompt in effect |
| --- | --- | --- |
| **OLD** | pre-swap constant, from `bench/readjudication/old_prompt.txt` | `3433ac5d862d9e749f00455b0ed1d0b422b743c50202cb6fe45774c1445ae0bc` |
| **NEW** | current production constant, read live from `workers.redteam_critic.REDTEAM_AGENT_SYSTEM_PROMPT` | `7d44820d99f71485b0734ad4362cb95212c0f327481c7de043d8079cc3f52dba` |

Both shas are **asserted before the first call** and **re-asserted before
every single call**, against the module global actually in effect at that
moment, and the observed value is written on the row
(`prompt_sha256_at_call`). **This is the F1 fix and it is the difference
between a self-verifying artifact and a hopeful one:** a seam that
silently reverts — module re-imported, a stale module reference, an
`importlib.reload` anywhere in the import graph — is otherwise invisible
to every bar that only binds in the too-permissive direction. A drift
mid-run is exit 6/7 with a PARTIAL artifact.

Deliberate asymmetry in how the two prompts are obtained, and why:
- **OLD** comes from a frozen file, because git history is the only
  source for a string that no longer exists in the working tree.
- **NEW** is read from the **live worker module**, not from
  `bench/redteam_cal/revised_prompt.txt`, so the NEW arm is literally
  production-as-deployed. If someone edits the production prompt between
  lock and run, the sha assertion fails and the run refuses — which is
  the correct outcome, not an inconvenience.

Shared configuration, pinned here and **not resolved at run time**:
- seam: `workers.redteam_critic.redteam_critic(hypothesis_text,
  iteration_id, parent_request_id=..., budget=...)` — hypothesis text
  alone, exactly as `orchestrator/nara.py` invokes it;
- budgets: `max_turns=3`, `max_wall_seconds=45.0` (the production
  values, passed explicitly). `SubAgentBudget`'s other defaults
  (`max_tokens_per_turn=1024`, `max_tokens_total=8000`) predate the
  earliest target and are unchanged since, so pinning these two
  reproduces production exactly;
- `CRITIC_BACKEND=vllm-gemma`; the resolved backend's `default_model`
  MUST be `gemma-4-26b-a4b` (exit 3);
- `env -u MOCK_LLM`; one call per (row, arm); **no retries and no
  re-prompting** — the production seam is one call, and Nara's
  re-hypothesize ladder is explicitly *not* reproduced here (§3.4).

**Serving is checked, never assumed (F2).** The worker's returned
`subagent_model` is `resolved_be.default_model`
(`workers/redteam_critic.py:263`) → `wrapper.MODEL`
(`agent_wrapper/backends/vllm_openai.py:20-21`) → `os.environ.get(
"VLLM_MODEL", "gemma-4-26b-a4b")` (`agent_wrapper/wrapper.py:44`): a
**process constant**, byte-identical on all rows by construction. It
cannot detect a serving change, and v1's exits 3 and 8 therefore compared
a constant to a constant. This is the precise failure this repo already
diagnosed once — `ui/backend/served_models.py` exists because the
dashboard "was printing a belief, not an observation" during the
Qwen-3.8 window. v2 replaces the belief with three observations:

1. **`/v1/models` is probed before the first call and after the last**
   (served_models.py's pattern; the served id is pinned in provenance),
   at `$VLLM_GEMMA_URL` — default `http://localhost:8000`, 5 s timeout.
   A failed probe, or an id ≠ `gemma-4-26b-a4b`, is exit 9.
2. **Every row asserts the server-reported name.** The wrapper record's
   `model` field is `resp.model` (`agent_wrapper/wrapper.py:125`,
   `orchestrator/subagent.py:175`) — what the server said, not what we
   configured — joined to the row by the worker's `wrapper_request_id`
   and written as `served_model_OBSERVED`. A mismatch is exit 8, abort,
   PARTIAL artifact.
3. **The image digest is pinned**:
   `vllm/vllm-openai@sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9`
   (`run_state/vllm_image.digest`). All 88 historical rows carry
   `model_version = "vllm/vllm-openai:v0.21.0/gemma-4-26b-a4b"`, so the
   comparison against history is exact.

---

## 3. Target set and claim-text sourcing

### 3.1 Selection rule (deterministic; resolved once, then frozen)

A cluster enters the target manifest iff **all** of the following hold
against `memory/idea_ledger.jsonl` reduced by
`workers.idea_ledger.load_state`:

1. its final reduced `kill_reason.code == "redteam_fatal_flaw"`;
2. its `reopening_condition` is exactly
   `{"requires": "new_evidence", "evidence_kind":
   "redteam_proceed_on_revision"}` — anything else and a proceed would
   not be admissible evidence for it (exclusion `reopen_kind_mismatch`);
3. `kill_reason.evidence_key` parses as `iteration:<iid>:redteam` and
   `<iid>` **equals the founding iteration** computed in §3.2 — the
   ledger's own record of *which* iteration's verdict caused the kill
   must agree with the join we use to fetch the text (exclusion
   `founding_evidence_mismatch`);
4. the founding iteration's `memory/loop_memory.jsonl` row has
   `redteam.verdict == "fatal_flaw"` (exclusion
   `historical_verdict_not_fatal`);
5. that row's `redteam.subagent_backend == "vllm-gemma"` and
   `subagent_model == "gemma-4-26b-a4b"` (exclusion
   `historical_backend_mismatch`);
6. that row's `ended_at` is **strictly before 2026-08-18T06:45:00Z**, the
   swap instant (exclusion `judged_post_swap`). This makes "judged by the
   old instrument" a **checked property of each row**, not a premise
   inherited from a summary;
7. **(new in v2, L1)** the reduced cluster carries **no `refined_claim`**
   (exclusion `cluster_refined_since_kill`). A cluster refined since its
   kill has a *different live claim*: `ui/backend/frontier_reviews.py::
   _claim_head_of` prefers `refined_claim`, so a NEW-arm proceed on the
   superseded founding text would be recorded as reopening evidence for a
   claim that is not the one now on file — and in the one case that
   exists, the live claim already carries an independent frontier veto
   (`cl-iter-2026-08-15-004`, D-064 round 2:
   `methods_reviewer[veto]: The claimed novel effect is confounded with
   its own antecedent…`). **The rule is fixed here, before the number
   mattered; it happens to be 1 row of 89.**

**Target/control contamination is a lock-time refusal (L9).** The builder
refuses (exit 4) if any control row shares an id with a target's
cluster_id or founding iteration, if any control text is byte-identical
to a target text, or if the maximum token-Jaccard across the two sets
reaches 0.60. A colliding row would make a known-bad **label** and a
reopen-eligibility **claim** refer to the same claim. Measured: **0 id
collisions, 0 exact collisions, max cross-set Jaccard 0.2857**.

The ledger is append-only and live (the loop iterates hourly), so
resolving targets at run time would be irreproducible. The manifest is
built once, written to `bench/readjudication/manifest.jsonl`, and pinned
by sha256; the ledger sha256 it was derived from is pinned in the
manifest's own meta record. **N is fixed at lock.** The builder is a pure
function of its inputs — it carries **no build timestamp** — so anyone can
rebuild it and get the same bytes; determinism under shuffled input order
and under three different `PYTHONHASHSEED`s is unit-tested (this repo
shipped a hash-seed ordering bug on 2026-08-18).

### 3.2 Claim text — and the honest limit on "byte-identical"

Clusters here carry **no elite claim text** (0/89 — all were
consolidation-created), so the text must come from the founding
iteration. The join is **not invented for this battery**; it is the one
`ui/backend/frontier_reviews.py` already uses:

- founding iteration = `_founding_iteration(cluster, cluster_id)`: the
  first `iter-*` member of the reduced cluster, else the id embedded in a
  `cl-iter-…` cluster_id, else `None`;
- claim text = `hypothesis.text` for that `iteration_id` in
  `memory/loop_memory.jsonl` — the same row lookup `_hypothesis_heads`
  performs.

**One deliberate departure:** the UI truncates to a 140-character head
(`_head`). That truncation is a *display* concern. A truncated claim is a
**different claim** to the instrument, so this battery sends the **full**
`hypothesis.text`, `.strip()`ed. Claim lengths run 6–170 words
(median 36).

**What cannot be verified, stated plainly (L5).** There is **no
call-level record of what the old critic was shown.**
`workers/redteam_critic.py:248` calls `run_subagent` **without**
`log_path`, so the default (`orchestrator/subagent.py:228`,
`log_path=None`) sends every redteam turn to
`agent_wrapper.wrapper.MEMORY_LOG` — in memory, discarded at process
exit. `logs/calls.jsonl` contains **zero** `subagent.redteam_critic`
records. The historical prompts are gone and this battery cannot recover
them.

What we have instead is a **code-path argument**, and the claim is scoped
to exactly what it supports:

- `orchestrator/nara.py:958-968` overwrites `captured['hypothesis']` in
  lockstep with `hyp_text` on **every** retry, and `nara.py:1174` builds
  the persisted record from `captured` — so `loop_memory.hypothesis.text`
  **is** the text of the **final** redteam call, which is the call whose
  verdict became the kill;
- the D-060 failure-match consult (`nara.py:369-373`) runs **before**
  red-team, so it does not sit between the stored text and the judged
  text;
- the OLD prompt constant is byte-stable at
  `3433ac5d…` from `0eaaa3b` (2026-06-05) through `7780898^`, verified by
  AST extraction at every revision touching the file (`0eaaa3b`,
  `6ddcce5^`, `6ddcce5`, `7780898^` — all identical);
- `orchestrator/subagent.py`'s only change in the target era (`3609da3`,
  2026-06-10) is observability-only: no parse or dispatch semantics.

**Therefore:** the claim this battery may make is *"the OLD arm re-sends
the text that the code path establishes was the final text judged, under
the byte-identical prompt constant and the same budgets"* — **not** *"we
replayed the recorded historical request"*. There is no recorded
historical request to replay. This battery does put **its own** prompts
on disk: the driver dumps `agent_wrapper.wrapper.MEMORY_LOG` per run next
to the artifact, joinable to rows by `wrapper_request_id`. (Passing
`log_path` through would require changing the production worker's
signature; the battery does not modify production code to measure it.)

### 3.3 What happens to a cluster with no claim text

A cluster whose founding iteration cannot be resolved, or whose
loop_memory row is missing, or whose `hypothesis.text` is absent, empty,
or whitespace-only, is **excluded at manifest-build time** with the
reason `no_founding_hypothesis_text`. Every exclusion — from this or any
criterion in §3.1 — is:

- **counted**, by reason, against the frozen reason enum;
- **listed by `cluster_id`** in the manifest's meta record and echoed
  into every run artifact;
- **reported next to every rate** in the report, as
  `N = <n> of <n + excluded> qualifying-by-kill-code clusters`;
- **never silently dropped**, and never re-included later.

An excluded cluster generated no admissible evidence and is therefore
**not eligible for reopening under any disposition option in §9**. It
stays killed by default. Silence toward exclusion is the conservative
direction and it is the direction we take.

**Sidecar rows (L1).** The one cluster excluded as
`cluster_refined_since_kill` still contributes **two EXPLORATORY rows** —
its founding text and its live refined claim — judged by both arms and
reported in the artifact's exploratory block. They enter **no bar, no
statistic, no 2×2, and not R**, and no disposition may cite them. They
exist so the one case is *visible* rather than *silently dropped*; they
cost 4 calls.

As built 2026-08-19 (ledger metadata only, no calls): **89 qualify by
kill code, 1 excluded (`cluster_refined_since_kill`), N = 88.**

### 3.4 Two properties of these texts that must be on the record

**(a) They are third drafts, and the target set is conditioned on the
selecting draw.** All 88 historical kills carry
`redteam.retries_used == 2`: Nara's hypothesize→redteam ladder had
already re-written the hypothesis twice, each time conditioned on the old
critic's own critique, and the critic still condemned the third text. The
stored `hypothesis.text` **is** that third text.

The consequence v1 missed: in the **pre-R1b worker**, a sub-agent
`schema_mismatch` **fail-opened to `proceed`** (`_proceed_fallback`). So a
parse failure at T0 or T1 would have broken the ladder
(`orchestrator/nara.py:949`) and **spared** the cluster. Every target
therefore survived *parse-and-condemn, three times running*. The target
set is **selected on the old instrument having parsed and condemned
repeatedly** — which biases Q2 (§7.2) upward.

**(b) The old worker's failure polarity was the opposite of today's.**
Commit `6ddcce5` (2026-08-18T05:28Z) remapped the `schema_mismatch` path
from `proceed` to `unscored` — **after** the latest target's founding
iteration ended (2026-08-18T05:07:09Z), so **none** of the 88 was judged
under today's polarity. In production, pre-swap, of 122 iterations
carrying a redteam block: **96 `fatal_flaw`** (all
`subagent_status='passed'`), **3 genuine proceeds**, and **23
`schema_mismatch` fail-opens recorded as `proceed`** — an **18.9%
parse-failure rate** for the old prompt in production.

This inverts the meaning of one bucket: **an OLD-arm `unscored` today is
the same event that historically meant "proceed, no kill".** §7.2 handles
it in the statistic (κ_old's primary denominator) and §7.6 gives it a
pre-stated reading; §9 gives the corresponding rows a rank.

Finally, these claims are **not pristine first drafts** — they were
rewritten to satisfy a miscalibrated critic. That could cut either way
(the rewrites may have sharpened the claim, or degraded it by chasing an
unsatisfiable standard), and this battery **cannot distinguish those**.
It is a limitation, stated now, not a caveat discovered later.

---

## 4. Spiked controls

### 4.1 What they are

The **complete 24-row R1a frozen manifest**
(`bench/redteam_cal/fixtures.jsonl`, 12 known-bad + 12 known-good),
spiked into the run and judged by **both arms**, interleaved with the
targets in the locked order.

**All 24 rows, not a subset, and not selected on outcome.** Picking the 9
known-bad rows `gemma-revised` happened to catch on 2026-08-18 would be
selection on the previous run's success — a rubber stamp. The frozen
manifest is taken whole.

Known-good rows are spiked as well as known-bad because they answer the
*other* half of interpretability — and in v2 they are **barred, not just
reported** (C4, §4.3). That is the F1 fix: in v1 the known-good rows were
spiked, described as answering half the question, and then never barred,
which left the run void-able only in the too-permissive direction.

### 4.2 Order, arm blocking, and why a control is indistinguishable

The seam's user prompt contains **only** the hypothesis text —
`iteration_id` is used for the return value and logging and is never
passed to `run_subagent`, so it never reaches the model (verified in
`workers/redteam_critic.py`). A control and a target are the same call
shape with the same budgets, the same system prompt, and the same
backend; nothing in the request distinguishes them.

**`row_id` and the locked order (L3).** `row_id` is: the **`cluster_id`**
for a target, the **fixture id** for a control, and
`sidecar:<cluster_id>:<variant>` for a sidecar. The order key is
`sha256(row_id.encode("utf-8"))` ascending, **tie-broken by `row_id`**
(UTF-8, lowercase hex). It is computed once at manifest build, written on
every row as `order_key`, and is identical for both arms. §7.3's
replicate subsample uses **the same key** — not a second one.

**The arms are BLOCKED: one arm per process.** v1 specified row-level
interleaving (OLD then NEW at each row) in a single process. That is not
buildable without giving up two things the design needs more:
`agent_wrapper.wrapper.MEMORY_LOG` is **process-global**, so a
single-process run cannot produce per-arm calls-log isolation; and a
fresh interpreter per arm is what makes the prompt injection
unambiguous (R1a precedent). So: `--arm old` runs the full locked order,
then `--arm new` runs it again in a fresh process.

What blocking costs is **temporal** pairing — the two arms are separated
by roughly 12 minutes, so a serving change between them would confound
with the arm. That is exactly the confound F2's fix now *observes*
instead of assuming away: `/v1/models` before and after **each** arm, the
server-reported model asserted on **every** row, the image digest pinned,
and every call's wall-clock timestamp recorded. Claim-level pairing —
what McNemar needs, and what isolates instrument from claim — is
unaffected: both arms judge byte-identical texts.

Residual risk accepted and stated: a serving change that occurs **and
reverts** entirely inside one arm's window, with the served id unchanged
across both probes and every row. Judged negligible; auditable after the
fact from the per-row timestamps and the calls dump.

### 4.3 The bars

Each bar stands on its own (inviolate rule 4). A near miss is a failure.
The driver evaluates the **run-validity bars first** and reports them
before any statistic. Full calibration arithmetic: **Appendix C**.

**Bar C1 — NEW catches the bad. HARD; failing it voids the run.**
The NEW arm must return `fatal_flaw` on **≥ 6 of the 12** known-bad
controls. Denominator is all 12: `unscored` counts against (§5).

Calibration: a degenerate instrument with a true catch rate ≤ 0.25 passes
with probability **0.0544**; a coin (0.50) passes with **0.6128** — so
this bar rejects *degeneracy*, the failure mode that matters, not
mediocrity. At the NEW instrument's R1a point estimate 0.75 it
false-voids a good run **1.43%** of the time. R1a's adoption bar (≥ 9/12)
was rejected for exactly this reason: at true p = 0.75 it would
false-void **35.1%** of valid runs.

**Bar C4 — NEW does not condemn the good. HARD; failing it voids the
run. (NEW IN v2 — F1.)**
The NEW arm must return `fatal_flaw` on **≤ 35% of parsed** known-good
controls — **R1a adoption bar 3 verbatim**, the bar this very prompt was
adopted on, not a fresh invention. `unscored` rows are excluded from both
numerator and denominator here (parsed-only), matching R1a exactly; the
all-rows figure is reported alongside as a secondary.

Why it is not optional: without it the run is void-able only in the
too-permissive direction, and a silently reverted NEW arm — the arm
running the *old* prompt — sails through. Do the arithmetic: the old
prompt scored 12/12 fatal on known-bad in R1a, so **P(pass C1) = 1.0000**;
C2 passes trivially because under a revert both arms are the old prompt;
and the old prompt's unscored rate was 5/12 on known-good but **0/12 on
known-bad**, so in exactly the branch where a harsh instrument reads the
graveyard as bad — the branch that produces low φ and the "kills survive
recalibration" reading — the unscored count stays low and C3 passes too.
Net detection under v1's bars: ≈ 0.

C4's computed power: **P(detect a reverted NEW arm) = 0.9990 at 7 parsed,
0.9999 at 12 parsed**. Its false-void rate on a genuinely good run:
**0.0002** (5% true false-condemn rate, 12 parsed) to **0.0257** (10%
rate, 7 parsed).

**Bar C2 — OLD still condemns the good. HARD for the attribution claim.**
The OLD arm must return `fatal_flaw` on **≥ 50% of parsed** known-good
controls. **Not evaluable below 5 parsed rows** (reported as such, and
the attribution decomposition inherits the caveat verbatim).

Calibration, restated correctly (L2 — v1's "≤ 0.02 across any plausible
parse count" and "≤ 0.10" were both wrong at several counts):

| parsed | passes iff fatal ≥ | P(false-fail at the R1a-observed 0.857) | P(a non-condemner at 0.25 passes) |
| ---: | ---: | ---: | ---: |
| 5 | 3 | 0.0233 | 0.1035 |
| 6 | 3 | 0.0049 | 0.1694 |
| 7 | 4 | 0.0102 | 0.0706 |
| 8 | 4 | 0.0023 | 0.1138 |
| 9 | 5 | 0.0045 | 0.0489 |
| 10 | 5 | 0.0011 | 0.0781 |
| 11 | 6 | 0.0021 | 0.0343 |
| 12 | 6 | 0.0005 | 0.0544 |

True bounds: false-fail **≤ 0.0233**; pass-through for a non-condemner
**up to 0.169 at 6 parsed**. Even parse counts are systematically weaker
because the ≥50%-of-parsed rule needs `ceil(n/2)`.

C2's scope is narrower than C1's and C4's, deliberately. C1 and C4 gate
*everything*: without them there is no interpretable measurement. C2
gates the **attribution decomposition** (§7.2) and Q2. If the OLD arm no
longer condemns sound claims today, the OLD arm is not a faithful
reconstruction of the historical instrument, and any statement of the
form "this flip is attributable to the prompt" is unsupported. The NEW
arm's verdicts survive C2's failure as a *fresh adjudication of the
graveyard* — still a real result, still feeding §9 — but the report must
then say plainly that the instrument-vs-claim question was not answered.

**Bars C3a / C3b — parse health, SPLIT. HARD. (F5.)**
- **C3a — targets:** NEW-arm `unscored` over the **88 target rows** must
  be **≤ 13 (15%)**.
- **C3b — controls:** NEW-arm `unscored` over the **24 control rows**
  must be **≤ 4**.

v1 pooled these into one 17/113 ceiling, which let a parse regression
concentrated on the targets — the likely shape, since the controls are
register-matched and the targets are thrice-rewritten claims — consume
**17 target verdicts and still pass**, while the report printed a point
estimate of φ with 19% of the target set carrying no verdict in either
direction.

Calibration: C3a false-voids with P < 1e-5 at a true 4% unscored rate and
0.0100 at 8%; it fires with P = 0.45 at 15% and 0.81 at 19% (the old
prompt's measured production rate). C3b false-voids with P = 0.0023 at 4%
and 0.0386 at 8%, and fires with P > 0.99 at the 42% rate the old prompt
showed on R1a known-good and P = 1.0000 at the qwen38 arm's 75%.

The bars can afford these rates precisely because `unscored` counts as
**non-proceed** in the primary statistic (§5) — but only if the missing
verdicts are also *visible*, which is why §5 requires φ's bound pair.

**If any hard run-validity bar (C1, C4, C3a, C3b) fails, the run is
void.** The flip rate is uninterpretable. Void means: report the failure,
report the control table, report the serving provenance, and **do not
report a flip rate at all** — not a provisional one, not a caveated one.
It does not mean re-thresholding, re-running until it passes, or
explaining it away as an unlucky fixture set. A voided run may be
re-attempted only after a stated, logged cause (e.g. a diagnosed serving
regression) is fixed, and the re-attempt is reported as a re-attempt.

**No bar is set on the OLD arm's parse health.** The old prompt
demonstrably fails parse on sound claims (5/12 known-good unscored in
R1a; 23/122 in production). That is a *property of the instrument under
study*, not a run failure, and barring it would be measuring our own
measuring stick. It is **reported**, never barred.

---

## 5. Verdict semantics

Verdicts are recorded exactly as the worker returns them —
`fatal_flaw` | `proceed` | `unscored` — and are never coerced (inviolate
rule 4).

**`unscored` is NEVER `proceed`.** The battery fails toward keeping the
kill. Formally, for arm *a* and row *i*:

```
proceed(a, i) = 1  iff  V_a(i) == "proceed"
              = 0  otherwise      # fatal_flaw AND unscored both → 0
```

A worker return of `status != "passed"` (invalid input) is recorded as
`error`, counted separately, and treated as `unscored` for all
statistics. An `error` should be impossible — empty text is excluded at
manifest-build time (§3.3) — so any occurrence is reported as a **driver
defect**, not as a finding.

### The flip statistic

Let **T** be the locked target set, |T| = **N = 88**. Define:

> **φ — the flip rate (PRIMARY)**
> ```
> φ = #{ i ∈ T : V_NEW(i) == "proceed" } / N
> ```

The denominator is **N, the full locked target set** — every `unscored`
row, every `error` row, and every `fatal_flaw` row is in it. **No row is
removed from the denominator after a call is made, for any reason.** All
exclusions happen before lock (§3.3).

φ is deliberately conservative: it is the fraction of the graveyard that
*would actually return to the queue*, since an unscored row produces no
admissible reopening evidence and stays killed.

**φ is always reported as a bound pair (F5):**
```
φ_bound = [ #proceed / N , (#proceed + #unscored_NEW) / N ]
```
When the NEW arm's **target-only** unscored count exceeds **4**, the
point estimate **may not be quoted alone** anywhere in the report — the
interval is the headline. This is pre-committed here rather than chosen
once the number is seen. The target-only unscored count is reported
separately from the control-only count, always.

> **φ_parsed — the parsed-only proceed rate (SECONDARY, an upper bound)**
> ```
> φ_parsed = #{proceed} / #{ i : V_NEW(i) ∉ {unscored, error} }
> ```

Labelled in the report as the optimistic bound, never as the headline.

**Eligibility is NEW-only.** The reopen-eligible set is
`R = { i : V_NEW(i) == "proceed" }`, |R| = φ·N. This does *not* depend on
the OLD arm: the ledger's reopening condition asks for "a redteam
proceed", and the redteam *is* the current instrument. The OLD arm exists
for attribution (§7.2), not for eligibility. **R is partitioned
exhaustively in §7.2 and §9 as (A, B, U∩R)** — v1 left the third part
without a cell and without a rank.

---

## 6. Protocol and refusals

Order of operations:

1. **Pause the coordinator** — write `run_state/pause_coordinator`. The
   apparatus is always-on (hourly cron + daemon, D-063) and ~25 minutes
   of continuous redteam calls will contend with live iterations for
   `vllm-gemma`. Contention inflates wall time, not verdicts, but it also
   perturbs the live loop. Pausing and **restoring** are each explicit
   logged steps; the risk to name is forgetting to restore.
2. Assert the manifest sha + row-kind counts; assert `fixtures.jsonl`'s
   sha; assert the resolved backend model; assert the arm's prompt sha;
   probe `/v1/models`.
3. `--arm old`: walk the 114 locked rows once. Then, in a **fresh
   process**, `--arm new`: walk the same 114 rows.
4. Run the NEW-arm replicate pass over the locked 20-row subsample
   (§7.3), in the same process as the NEW arm, as a separate final pass.
5. Probe `/v1/models` again; write the artifact; dump the calls log;
   restore the coordinator; append the run-log rows (inviolate rule 6,
   `agent: claude-code-main`, one row per phase).
6. Run `--evaluate-pair OLD NEW` — a pure, call-free cross-arm
   evaluation — to produce φ, the 2×2, κ_old, McNemar, the R partition
   and the reading gates.

Refusals — each is a hard exit before or at the first offending call,
never a coerced continuation:

| exit | condition |
| --- | --- |
| 2 | `MOCK_LLM` is set — a stubbed run is silently meaningless (rule 10) |
| 3 | resolved `vllm-gemma` `default_model` ≠ `gemma-4-26b-a4b` — registry drift is a driver bug, never a finding |
| 4 | `manifest.jsonl` sha ≠ the locked sha, or its row-kind counts ≠ `{target: 88, control: 24, sidecar: 2}` |
| 5 | `bench/redteam_cal/fixtures.jsonl` sha ≠ `1f8b738c…` |
| 6 | OLD prompt sha ≠ `3433ac5d…` — checked before the first call **and before every row** |
| 7 | NEW prompt sha (read from the live module) ≠ `7d44820d…` — same, per row |
| 8 | any row's **server-reported** model (`resp.model`, joined by `wrapper_request_id`) ≠ `gemma-4-26b-a4b` — a real mid-run serving change |
| 9 | the `/v1/models` probe (before the first call or after the last) fails or reports a different served id |
| 10 | mode misuse — exactly one of `--arm` / `--evaluate-pair` is required |
| 11 | the 75-minute wall cap fired |

Exits 6–8 and 11 are checked per row and abort on first occurrence,
writing a PARTIAL artifact **explicitly marked uninterpretable** — a
prompt or serving change mid-run breaks the pairing, and spending the
remaining calls into a broken pairing would be worse than stopping. A
PARTIAL NEW artifact has no same-run control rates, so `--evaluate-pair`
**refuses** rather than computing φ against invented comparators.

**Time cap and slip rule (inviolate rule 7).** Expected wall time is
~25 minutes for both arms (§11). If elapsed within an arm exceeds **75
minutes**, the driver aborts (exit 11). Extending is a `slip-ladder`
decision that returns to the owner with the elapsed number; it is not the
driver's to take.

---

## 7. Statistics

All intervals are **exact Clopper-Pearson 95%**, computed by the function
already unit-tested in `bench/redteam_cal/driver.py` and **imported**, not
reimplemented.

### 7.1 Primary — and the numbers φ must be reported against

φ and φ_bound and φ_parsed, each with its CP95 interval and its explicit
numerator and denominator. Precision at N = 88 is ±7 to ±11 points
(half-width ≈ 10.9 pts at φ ≈ 0.5, ≈ 6.9 pts at φ ≈ 0.1 or 0.9) — stated
now so the report cannot later present a 10-point difference as a
distinction.

**The reporting phrase is pinned (L6):** φ is *"of the 88 re-adjudicated
redteam-code kills"*. The report must print **all three denominators
once**, adjacent: 88 re-adjudicated / 112 total kills / 132 clusters. A
φ of 0.90 is simultaneously "90% of the re-adjudicated redteam kills",
"71% of all kills" and "60% of the ledger"; the number may not travel
with the largest denominator attached.

**Required same-run comparators (F4).** φ is meaningless in isolation
because the NEW instrument is more permissive by construction. It is
therefore a **required primary-section statistic** that φ is reported
beside, in the same table:

1. the **same-run** NEW-arm `proceed` rate on the **12 known-bad**
   controls, with CP95 (R1a's value was 3/12, CP95 0.055–0.572);
2. the **same-run** NEW-arm `proceed` rate on the **12 known-good**
   controls, with CP95 (R1a's value was 12/12, CP95 0.735–1.000);
3. both differences, `φ − p_bad` and `φ − p_good`;
4. the **post-swap production kill count**: at lock, since the
   2026-08-18T06:45Z swap the NEW instrument has run **6** production
   iterations and returned `proceed` on **6/6** with `retries_used = 0` —
   **0 kills in live production**. Re-measured at report time and printed
   as-of.

Without these, φ = 0.90 reads as "the graveyard was an artifact" and
φ = 0.20 reads as "the graveyard is real", and neither reading is
falsifiable by the design. With them, §7.6's gate can withdraw a reading.

### 7.2 The attribution decomposition — the core analysis

The 2×2 over rows where **both** arms returned a scored verdict:

| | NEW = proceed | NEW = fatal_flaw |
| --- | --- | --- |
| **OLD = fatal_flaw** | **A** — prompt-attributable flip | **C** — kill survives recalibration |
| **OLD = proceed** | **B** — kill not reproducible by its own instrument | **D** — reverse discordance (noise floor) |

Rows where either arm was `unscored`/`error` are excluded **from this
2×2 only**, counted as **U**, and reported. A + B + C + D + U = N always;
the report prints that identity.

**U is decomposed by NEW verdict (F3(iii)).** v1 made |U ∩ R|
unprintable even though it drives §9. The artifact now prints
`U_by_new_verdict = {proceed, fatal_flaw, unscored}` and, separately,
`U_old_unscored_and_new_proceed` — the bucket §3.4(b) says is the
strongest available evidence of non-reproduction, and which v1 discarded.

**A** is "the instrument changed". **B** is something else entirely: the
old instrument, re-run on the identical text, *does not reproduce its own
kill*. **C** is a kill that survives. Reporting a single "flip rate"
without this split would conflate a prompt defect with a reliability
defect, and they have different remedies (§9).

**Paired test.** Exact McNemar / sign test on the discordant pairs A and
D: two-sided exact binomial on A out of (A+D) at p = 0.5, plus CP95 on
A/(A+D). For scale: A=20, D=2 gives p ≈ 1.2e-4; A=10, D=3 gives
p ≈ 0.092 — i.e. this test has real teeth only when the discordance is
lopsided, stated in advance so a null result is not spun.

**Q2 — old-arm self-concordance, with the denominator fixed (F3(ii)).**

```
κ_old (PRIMARY)   = #{ i : V_OLD(i) == "fatal_flaw" } / N        # all 88
κ_old (SECONDARY) = #{ i : V_OLD(i) == "fatal_flaw" } / #{ scored }
```

The **primary** counts an OLD-arm `unscored` as **non-reproduction**.
That is not a convention, it is the historically faithful mapping: under
the pre-R1b worker a `schema_mismatch` **was** a `proceed`, i.e. **no
kill** (§3.4(b)) — so treating today's `unscored` as "no evidence" and
keeping the kill would treat the strongest available evidence of
non-reproduction as no evidence, in the direction that preserves the
graveyard. It is also the same polarity φ already uses; v1's asymmetry
(conservative all-rows denominator for φ, permissive parsed-only for
κ_old) was never justified and is removed. The parsed-only figure is
reported as the **secondary upper bound**.

Why this matters concretely: at a plausible ≥17 unscored, 60 fatal /
72 scored = **0.83** selects §7.6 row 1 ("prompt attribution"), while the
historically faithful 60 / 88 = **0.68** is neither ≥ 0.75 nor < 0.5 and
selects "mixed". A denominator choice was moving the headline reading by
a whole row of the interpretation table.

**κ_old's selection caveat, stated with the statistic (F3(a)).** Every
target carries `retries_used == 2`, so each survived T0-fatal → T1-fatal
→ T2-fatal, and a parse failure at T0 or T1 would have fail-opened to
`proceed` and **spared** the cluster (`orchestrator/nara.py:949`). κ_old
is therefore a test–retest **conditioned on the selecting draw** and
**biased upward** — i.e. biased *toward* the §7.6 row-1 prompt-attribution
reading. v1's "κ_old is a genuine test–retest of the historical
instrument" was an overclaim and is withdrawn. κ_old is meaningful only
if bar C2 passes.

### 7.3 Q3 — new-arm replicate (descriptive)

A second NEW-arm draw on a locked 20-row subsample of T (the first 20
targets by the **same** ascending `sha256(row_id)` key as §4.2, fixed at
lock), run as a **separate final pass** so the two draws are maximally
separated in time and the agreement estimate therefore *includes* any
within-run drift. Reported as a verdict-agreement rate with CP95. It is
**descriptive and never enters φ**: the primary statistic uses the
**first** NEW draw only, pre-stated here so the choice cannot be made
after seeing which draw is friendlier.

### 7.4 Pre-stated additional statistics

**(a) Row-level replication against R1a — REQUIRED, both arms (L4).**
`bench/redteam_cal/runs/gemma-current_20260818T060805Z.json` (sha
`d1cf0e3c…`) and `gemma-revised_20260818T061029Z.json` (sha `92e62822…`)
carry per-row verdicts on the **identical 24 fixtures**, with the
identical prompt shas and the same backend, one day earlier. This battery
re-runs those exact rows on both arms, so a **row-level agreement rate
(n = 24 per arm, CP95)** is available at zero extra cost — a far sharper
fidelity check than C1/C2/C4's aggregate thresholds, and a second,
independent detector for the F1 revert scenario. Reported for both arms
with the disagreeing row ids listed. Descriptive: it gates nothing.

**(b) Splits.** Descriptive, underpowered by construction, **no
multiplicity correction claimed and none implied** — named here so that
reporting them is not fishing, and their intervals are wide enough that
they cannot carry a disposition on their own.

1. **By era** (founding-iteration month; 2026-06: 17, 2026-07: 23,
   2026-08: 48). The hypothesize prompt, the topic portfolio and the
   coordinator all changed across that span. An era-flat flip rate
   supports "instrument"; an era-skewed one raises "claim quality changed
   too" — which this battery cannot resolve, and would say so. CP95
   half-widths at these n are 14–23 points.
2. **By historical `redteam.confidence`** (observed 0.85–1.0, median
   0.935). Pre-stated as a **calibration check on that confidence
   signal**, with the expectation on the record that it is
   near-degenerate and will likely discriminate nothing.
3. **By cluster member count** (71 × 1, 16 × 2, 1 × 4) — relevant to §9's
   ordering and to the founding-text coverage caveat.
4. **Controls by provenance class** (real-historical / battery /
   constructed), both arms — the same split R1a used, so a register-split
   pass is visible rather than hidden inside an aggregate.

### 7.5 The honest caveat

Inherited from R1a and non-negotiable: **at n = 12 per class, a
zero-discrimination coin passes R1a's bars 2∧3 with ≈1.4% probability and
a weak 60/40 instrument with ≈10%.** The battery that elected the NEW
prompt discriminates condemners and coins from calibrated instruments —
it does **not** establish that the NEW instrument is *good*. This
re-adjudication inherits that uncertainty in full and **cannot reduce
it**: every claim it makes is relative to an instrument whose quality is
bounded at n = 12/class. Nothing in this document should be read as
evidence about the NEW instrument's accuracy.

### 7.6 Pre-stated interpretation

Written before the numbers, so the reading is not chosen to fit them.
Thresholds are *reading aids*, not bars; no disposition follows
automatically from any cell.

**Gate, evaluated first (F4).** The **"prompt attribution / the graveyard
was an artifact"** reading — row 1 below — is **UNAVAILABLE** whenever
φ's CP95 **overlaps** the same-run NEW-arm `proceed` rate on **known-bad**
controls. In that case the instrument is proceeding on the graveyard at a
rate indistinguishable from its rate on claims we labelled bad, and the
report says exactly that instead. The gate is computed by the driver and
printed as `prompt_attribution_reading_available`.

| Pattern | Reading |
| --- | --- |
| φ high (≥ .75) **and** κ_old high (≥ .75) **and** the gate is open | Graveyard dominated by **prompt attribution** — cell A. The kills reproduce under the old prompt and dissolve under the new one. |
| φ high **and** κ_old low (< .5) | Graveyard dominated by **stochasticity** — cell B. The old instrument does not reproduce its own kills; a prompt swap alone does not explain, or fix, this. |
| φ low (≤ .25) | Kills largely **survive recalibration** — the graveyard is mostly real, subject to §7.5 **and** to C3a: a low φ driven by a high target-unscored count is a *parse* finding, not an *idea-quality* finding, and the φ bound pair must be quoted. |
| **OLD-arm `unscored` is the largest single bucket** (`U_old_unscored_and_new_proceed` ≥ A) | **Non-reproduction by parse failure.** Historically these rows would have fail-opened to `proceed` and never been killed (§3.4(b)). This is a *worker-polarity* finding: the kills that populate it were an artifact of a fail-open that no longer exists, and the remedy is the concordance requirement (modifier M1), not a prompt story. |
| φ's CP95 overlaps the same-run known-bad proceed rate | **The attribution reading is withdrawn.** Report φ, report the overlap, and state that the design cannot separate "the graveyard was an artifact" from "the new instrument proceeds on most things". |
| Mixed / intermediate | Reported as mixed. No cell is rounded toward a story. |

---

## 8. Artifacts and provenance

Written to `bench/readjudication/runs/<arm>_<stamp>.json`, mirroring the
R1a artifact's provenance block: prereg path; git commit; manifest path +
sha256 + its full meta record (exclusions, source shas, scans); fixtures
sha256; the arm's prompt sha + its source; **the per-row prompt sha
actually in effect at that call**; pinned budgets; the verbatim seam
string; backend + resolved model; **the `/v1/models` probes before and
after**; the **vLLM image digest**; `wrapper.MODEL_VERSION`;
started/ended; per-row
`{row_id, kind, order_key, cluster_id, founding_iteration, claim_sha256,
label, provenance_class, era, historical_confidence,
cluster_member_count, arm, prompt_sha256_at_call, verdict, worker_status,
confidence, critique_digest, wall_s, call_ts, wrapper_request_id,
subagent_status, subagent_backend, subagent_model_DECLARED,
served_model_OBSERVED, errors}`; the bars C1–C4 with run-validity first;
the per-arm evaluation; the §7.5 caveat verbatim; and the per-run
calls-log dump path.

The cross-arm evaluation (`--evaluate-pair`) writes φ and φ_bound, the
2×2 with U decomposed, κ_old in both polarities with its selection
caveat, McNemar, the R partition, the comparators and the reading gate,
and the splits.

**The battery writes nothing to `memory/idea_ledger.jsonl`.** Not a
draft event, not a dry-run event. Its only writes are its own artifact,
its calls-log dump, and its rows in `run_state/week1.run.jsonl`.

---

## 9. Pre-stated disposition options

**This section is the reason the document exists before the numbers.**
The menu is fixed now; the choice among it is the owner's, later.

**No option auto-executes.** Reopening is a **separate, owner-ratified
step**: a `cluster_reopened` event per cluster, carrying
`evidence = {evidence_kind: "redteam_proceed_on_revision", evidence_key:
<this run's artifact + row>, detail: <the NEW critique>}`. The reducer
accepts it because it matches each cluster's own recorded
`reopening_condition` and **refuses a mismatch**
(`workers/idea_ledger.py:231-238`, rule 4).

**One semantic caveat on the record (L8):** the ledger's `evidence_kind`
is literally `redteam_proceed_on_revision`, while this battery judges the
**unrevised** text. The reducer's check is **name-only**, so it will
accept — but the evidence is a **same-text re-adjudication, not a proceed
on a revision**, and the report and any reopen event must say so.

**Verified mechanical facts, stated so the options are chosen against
reality, not hope:**
- **No writer exists.** `workers/refine_cycle.py:74` hard-wires
  `_REOPENABLE_KIND = "articulated_delta"`; nothing in this repo writes a
  `redteam_proceed_on_revision` reopen. Building the writer is part of
  the disposition step. **This battery cannot reopen anything.**
- **Consolidation will not silently re-kill a reopened cluster**
  (`workers/consolidate_memory.py:434` skips member ids already in the
  ledger).
- **(L8a) A reopen changes the loop's clustering topology.**
  `workers/consolidate_memory.py:188 _existing_open_clusters` excludes
  killed clusters, so every reopened cluster becomes a **new attractor**
  that each future fresh item is matched against **before** minting.
  Reopening 80 clusters means 80 new attractors.
- **(L8b) A reopen changes the human lab queue.**
  `ui/backend/lab_todo.py:121` lists `redteam_fatal_flaw` in
  `REFINABLE_KILL_CODES`, so these clusters are already surfaced as
  refinable; reopening changes what that queue shows.
- **(L7) Measured throughput, replacing v1's assertion.** The ledger
  holds **9 `evidence_level_changed` events in its entire history**, over
  **6 distinct clusters**: **5 clusters have ever advanced above L0**
  (4 → L1, one of those on to L2) and **2 of those 5 were later returned
  to L0**. Today: 18 open L0 + 2 L1, against a 60-call daily budget cap
  (D-063). Any N the owner picks should be picked against that number.

**Coverage caveat that applies to every option (F6b):** for a
multi-member cluster, the evidence is a re-adjudication of the
**founding member's text only** — 16 clusters of size 2 and 1 of size 4.
A proceed on the founding text is not a proceed on the cluster.

### Actions — exhaustive and non-overlapping; choose exactly one

- **(i) Reopen all of R** — every cluster with `V_NEW == "proceed"`,
  i.e. **A ∪ B ∪ (U∩R)**. Maximum recovery; maximum queue shock. At
  φ ≈ 0.9 this adds ~80 L0 clusters against an open queue of 20, a
  60-call daily cap, and a measured historical throughput of 5 clusters
  ever advanced past L0. The realistic failure mode is that a mass reopen
  re-buries the same ideas under a queue no cadence can work through —
  and, per L8a, permanently reshapes the matching pool.

- **(ii) Reopen a bounded top-N, N = 12 by default**, under this
  **ordering, pre-stated in full and exhaustive over R**:
  1. **cell B first.** B-cases have *two* independent `proceed` draws
     (OLD and NEW) against one historical `fatal_flaw`; A-cases have one
     proceed against two fatals. The stated purpose is *recovering
     ideas*, so the stronger evidence goes first. (The opposite order is
     defensible under a *demonstration* purpose; recovery is the stated
     purpose.)
  2. **then U∩R restricted to `OLD = unscored`** — the rows where the old
     instrument, re-run, could not parse the claim at all. Historically
     these would have **fail-opened to `proceed` and never been killed**
     (§3.4(b)), which makes them evidentially closer to B than to A.
     **v1 left these rows unranked, which handed the executor a live
     discretionary choice after seeing the data; this is the F6 fix.**
  3. **then cell A.**
  4. within each band: ascending founding `iteration_id` — deterministic,
     no discretion. **Cluster member count is deliberately NOT an
     ordering key** (v1 ranked by it): member count preferentially
     promotes exactly the clusters where the single re-adjudicated
     founding text covers the *smallest* share of the cluster, which is
     backwards.
  5. NEW-arm confidence is **not** an ordering key either — historical and
     R1a confidences both cluster at 0.85–1.0, so it would function as
     noise dressed as a quality signal.
  N = 12 keeps the open queue ≤ 32. The owner may choose any N against
  the L7 throughput figure; 12 is the pre-stated default so the option is
  executable without a fresh judgment call.

- **(iii) Reopen none; record the finding.** The measurement stands as a
  calibration record on the instrument, and the graveyard stays. Correct
  if φ is low or if the §7.6 gate closed; available at any φ.

- **(iv) [the option I would argue for] Reopen B and U∩R(OLD=unscored)
  and A, as three separate decisions.** They are different failures with
  different remedies: **B** and the **OLD-unscored** bucket say the
  *kill procedure* was unreliable (a lottery, or a fail-open that no
  longer exists), and reopening those without fixing the procedure just
  feeds them back into the lottery; **A** says the prompt was wrong and a
  reopen is the whole fix. Splitting keeps the remedy attached to the
  defect. **Explicitly:** cell **C** stays killed; U rows whose NEW
  verdict is `unscored` or `fatal_flaw` stay killed; U∩R rows where the
  OLD arm returned `unscored` are **IN** (they are the §3.4(b) bucket);
  U∩R rows where the OLD arm errored are **OUT**. v1 discarded all of
  U∩R silently — that is the F6 fix.

### Modifiers — combinable with any action above

- **(M1) A concordance requirement instead of, or in addition to, any
  reopen.** If κ_old is low, or the OLD-unscored bucket is the largest,
  the durable fix is not a reopen but a rule change: a
  `redteam_fatal_flaw` kill requires *k*-of-*n* agreeing condemnations
  rather than a single draw. This is the only option that prevents the
  next graveyard. (v1 listed this as option (v) inside an "exhaustive and
  non-overlapping" menu, where it overlapped option (iii) outright.)
- **(M2) Escalate to a falsifier first.** Route a bounded sample of the
  chosen reopen set to the frontier tier for annotation **before** any
  reopen (D-061: falsifiers veto/annotate, never generate). Costs a day;
  buys an independent read on whether the NEW proceeds are substantively
  defensible. This is a pre-step, not an alternative.

---

## 10. What this result does NOT license

Stated in advance because these are the inferences a favourable number
will invite.

1. **A `proceed` is not evidence the idea is good.** It returns the
   cluster to the queue at L0 and **nothing more**. The reopened claim
   must still clear novelty, the evidence ladder, and promotion
   screening. "Reopened" is not "promising".
2. **A high φ does not prove the 88 ideas were good.** It proves the old
   instrument's condemnations **do not replicate under the adopted
   instrument** — and only if the §7.6 gate is open. Idea quality is not
   measured anywhere in this design.
3. **This cannot distinguish "the old prompt was wrong" from "the new
   prompt is too permissive"** on the graveyard alone. The spiked
   known-bad controls address that confound *partially*, their power is
   bounded by 12 rows, and when φ's CP95 overlaps their proceed rate the
   attribution reading is withdrawn outright (§7.6).
4. **It establishes nothing about the NEW instrument's accuracy** (§7.5).
5. **It does not overturn non-redteam kills** — `paper_prior_exists`,
   `superseded_duplicate` and every other kill code are out of scope, and
   their clusters carry different reopening conditions that a redteam
   proceed does not satisfy.
6. **It says nothing about post-swap kills.** There are none among the 88
   (criterion 3.1.6), and none exist in production either (0 kills in 6
   post-swap iterations at lock).
7. **It is not a verdict on the loop's idea generation.** The claims were
   already twice-rewritten under the old critic's pressure, and the
   target set is conditioned on the old instrument having parsed and
   condemned three times running (§3.4). What the loop would have
   produced under a calibrated critic is unmeasured and unmeasurable from
   this data.
8. **It does not license a claim about the historical request bytes.**
   The old critic's calls were never written to disk (§3.2, L5). The
   fidelity claim is a code-path argument about the *text*, plus a
   byte-identical *prompt constant* — not a replay of a recorded request.
9. **For multi-member clusters it covers the founding text only** (§9).
10. **A voided run yields no φ at all** — not a provisional one, not a
    caveated one.
11. **The one refined cluster is out of scope entirely.** Its sidecar
    rows are EXPLORATORY and cannot support any disposition.

---

## 11. Cost

| | calls |
| --- | --- |
| Targets, both arms | 88 × 2 = **176** |
| Spiked controls, both arms | 24 × 2 = **48** |
| Sidecars (EXPLORATORY), both arms | 2 × 2 = **4** |
| NEW-arm replicate subsample (§7.3) | **20** |
| **Total** | **248** |

Wall clock, grounded in the R1a gemma arms (24 calls in 143 s and 145 s
end-to-end → **5.96 and 6.04 s/call** including worker and wrapper
overhead; per-call median 5.7–5.9 s, max 8.9 s):

- **expected ≈ 25 minutes** (248 × 6.0 s ≈ 1488 s) across both arms,
  sequential, no parallelism;
- **range 24–33 minutes** (5.7–8.0 s/call). The OLD arm should run at the
  slower end on this population: in R1a the old prompt's slowest rows
  (8.0–8.9 s) were all on sound claims;
- **hard ceiling 3.1 hours** if every call saturates the 45 s wall cap.
  The 75-minute per-arm abort (§6) fires long before that.

Budget accounting: bench drivers run **out-of-band** with respect to the
coordinator's daily budget ledger (cap 60, D-063) — precedent: R1a spent
72 calls this way on 2026-08-18. Flagged as an open question for the
owner, not assumed silently: 248 calls is four times the daily cap and
the owner may want it debited or explicitly exempted.

---

## Appendix A — the OLD prompt: provenance and pinning

The pre-swap constant no longer exists in the working tree. It is
recovered and pinned by **code**, not by prose — the recovery is
`bench/readjudication/build_manifest.py::extract_old_prompt` and it is
unit-tested:

1. `git show 7780898^:workers/redteam_critic.py` — the worker source
   immediately before the D-076 swap commit (`7780898`, "feat(D-076): R1a
   verdict — battery elects gemma-revised; production redteam prompt
   swapped").
2. Walk that module's **AST** for the `REDTEAM_AGENT_SYSTEM_PROMPT`
   assignment and `ast.literal_eval` its value node. The constant is a
   parenthesised implicit concatenation of **31 quoted fragments**, which
   the parser folds into a single `Constant` — so `literal_eval` is
   exact. **Not regex:** a naive triple-quote pattern does not match this
   form at all, which would fail *open*. **Not `exec`/import:** that
   would pull in the pre-swap dependency graph.
3. Freeze the extracted text byte-for-byte into
   `bench/readjudication/old_prompt.txt` at the LOCK commit, with a
   single trailing newline that the loader strips — the same convention
   `bench/redteam_cal/driver.py::load_revised_prompt` uses, because the
   production constant carries no trailing newline.
4. Assert
   `sha256 == 3433ac5d862d9e749f00455b0ed1d0b422b743c50202cb6fe45774c1445ae0bc`
   over the **UTF-8 encoding** of the string (1468 characters, 1478
   UTF-8 bytes — the text contains em-dashes; a latin-1 or
   character-count check would silently disagree). The builder refuses to
   write the file if the sha does not match.

**Independent corroboration — this is the load-bearing step, not the git
path.** That sha is byte-identical to the `prompt_sha256` recorded in the
R1a artifact `bench/redteam_cal/runs/gemma-current_20260818T060805Z.json`
— i.e. it is provably the exact string the `gemma-current` arm ran when
D-076 measured it as a condemner. The git path alone would only prove
"some pre-swap revision"; the artifact match proves "the instrument that
produced the finding this battery is testing".

Injection seam: `rt_mod.REDTEAM_AGENT_SYSTEM_PROMPT = <text>`, the same
module-global override `bench/redteam_cal/driver.py::apply_prompt_variant`
documents — the worker reads the global at call time, no production code
change, no env var (the module supports none for the prompt). **Its
effect is asserted before every call** (§2).

---

## Appendix B — resolved inventory as built, 2026-08-19

Ledger metadata only. **No model calls were made to produce this**; it is
a read of `memory/idea_ledger.jsonl` + `memory/loop_memory.jsonl` +
`bench/redteam_cal/fixtures.jsonl`, reproduced by
`bench/readjudication/build_manifest.py` and carried verbatim in the
manifest's meta record.

| | |
| --- | --- |
| clusters in ledger | 132 (20 open — 18 L0, 2 L1; 112 killed) |
| kill code `redteam_fatal_flaw` | **89** |
| ledger sha256 at build | `d277f9bc924f00f00814b0dca40959fc87eb816a1dd63f9cff1e51c9f62a87b0` |
| **excluded** | **1** — `cl-iter-2026-08-15-004`, `cluster_refined_since_kill` |
| **targets (N)** | **88** |
| controls | 24 (12 known-good / 12 known-bad), fixtures sha `1f8b738c…` |
| sidecars (EXPLORATORY) | 2 (the refined cluster's founding + refined texts) |
| manifest rows | **114**, sha256 `7ec63389…` |
| reopening_condition matches exactly | 88 / 88 |
| `evidence_key` iteration == founding iteration | 88 / 88 |
| carry elite claim text | **0** / 88 (all consolidation-created) |
| founding hypothesis text present | 88 / 88 → `no_founding_hypothesis_text` exclusions: **0** |
| evidence level | L0 × 88 |
| historical redteam verdict | `fatal_flaw` × 88, `subagent_status = passed` × 88 |
| historical backend / model | `vllm-gemma` / `gemma-4-26b-a4b` × 88 |
| historical `model_version` | `vllm/vllm-openai:v0.21.0/gemma-4-26b-a4b` × 88 |
| historical `retries_used` | **2** × 88 (see §3.4) |
| historical confidence | min 0.85, median 0.935, max 1.0 |
| claim length (words) | min 6, p50 36, p90 45, max 170 |
| exact-duplicate claim texts | 0 |
| near-duplicate target pairs (token-Jaccard ≥ 0.60) | 0 (max pairwise 0.4324) |
| **target↔control contamination** | **clean**: 0 id collisions, 0 exact, max cross-set Jaccard **0.2857** |
| cluster size | 1 × 71, 2 × 16, 4 × 1 |
| founding-iteration era | 2026-06: 17, 2026-07: 23, 2026-08: 48 |
| latest founding iteration `ended_at` | 2026-08-18T05:07:09Z — **1h38m before the 06:45Z swap** |
| production redteam, pre-swap (context) | 122 iterations: 96 `fatal_flaw`, 3 genuine `proceed`, **23 `schema_mismatch` fail-opens recorded as `proceed`** (18.9%) |
| production redteam, post-swap (context) | 6 iterations, **6/6 `proceed`, `retries_used = 0`, 0 kills** |
| ledger event history | 329 events: 130 `cluster_created`, 111 `cluster_killed`, 71 `member_added`, **9 `evidence_level_changed`**, 2 `niche_seeded`, 2 `cluster_refined`, 2 `agenda_item_added`, 2 `agenda_item_consumed` |

The `ended_at` row is the check that matters: it is the per-row
verification that **all 88 were judged by the old instrument**, rather
than an assumption inherited from a summary.

---

## Appendix C — bar calibration, computed

Exact binomial arithmetic (`math.comb`), reproduced by
`tests/test_readjudication.py`. Every figure below is a computed
guarantee; where v1 stated one that does not hold, it is corrected here
rather than rounded (inviolate rule 4).

**C1 — NEW `fatal_flaw` ≥ 6 of 12 known-bad** (unscored counts against):

| true catch rate | P(pass) |
| ---: | ---: |
| 0.25 | 0.0544 |
| 0.50 | 0.6128 |
| 0.75 (R1a point est.) | 0.9857 → false-void **0.0143** |
| 0.90 | 0.9999 |

The rejected ≥ 9/12 adoption bar false-voids at true 0.75 with
probability **0.3512**.

**C4 — NEW `fatal_flaw` ≤ 35% of parsed known-good** (R1a adoption bar 3):

| parsed | passes iff fatal ≤ | P(detect a reverted arm, true 0.857) | false-void @ true 5% | @ true 10% |
| ---: | ---: | ---: | ---: | ---: |
| 5 | 1 | 0.9981 | 0.0226 | 0.0815 |
| 6 | 2 | 0.9951 | 0.0022 | 0.0158 |
| 7 | 2 | **0.9990** | 0.0038 | **0.0257** |
| 8 | 2 | 0.9998 | 0.0058 | 0.0381 |
| 10 | 3 | 0.9999 | 0.0010 | 0.0128 |
| 12 | 4 | **0.9999** | **0.0002** | 0.0043 |

**C2 — OLD `fatal_flaw` ≥ 50% of parsed known-good:** see the table in
§4.3. True bounds: false-fail ≤ **0.0233** (at 5 parsed); a non-condemner
at 0.25 passes with up to **0.169** (at 6 parsed).

**C3a — NEW unscored ≤ 13 of 88 targets:**

| true unscored rate | P(void) |
| ---: | ---: |
| 0.02 | < 1e-6 |
| 0.04 | 0.000011 |
| 0.08 | 0.0100 |
| 0.15 | 0.4506 |
| 0.19 (old prompt's production rate) | 0.8075 |

**C3b — NEW unscored ≤ 4 of 24 controls:**

| true unscored rate | P(void) |
| ---: | ---: |
| 0.04 | 0.0023 |
| 0.08 | 0.0386 |
| 0.15 | 0.2866 |
| 0.42 (old prompt on R1a known-good) | 0.9919 |
| 0.75 (R1a qwen38 arm) | 1.0000 |

**Precision at N = 88 (CP95 half-widths):** 10.9 points at φ ≈ 0.5,
6.9 points at φ ≈ 0.1 and at φ ≈ 0.9.

**McNemar exact, two-sided:** A=20, D=2 → p = 1.21e-4; A=10, D=3 →
p = 0.0923.

**R1a same-run anchors (CP95):** NEW proceed 12/12 known-good →
[0.735, 1.000]; NEW proceed 3/12 known-bad → [0.055, 0.572]; OLD fatal
6/7 parsed known-good → [0.421, 0.996].
