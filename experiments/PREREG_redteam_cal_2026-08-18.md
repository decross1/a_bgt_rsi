# Pre-registration — redteam calibration battery (D-075 R1a) — v2

Status: v2 after adversarial critique (`d075-critic-redteam-cal`,
FIX-REQUIRED: exp-null/fatal conflation, arm-order ambiguity, register
mismatch, manifest/prompt leakage, dead bar). **LOCKS at the commit that
also contains `bench/redteam_cal/fixtures.jsonl` (the complete manifest)
and the gemma-revised prompt text in the appendix below** — fixtures and
revision are frozen side-by-side before the first call; the run driver
reads only the manifest. The fatal_flaw hard cap STAYS until the verdict.

## Arms — ALL THREE RUN TO COMPLETION on all 24 fixtures

Execution never stops early; the arm ORDER applies only at adoption
evaluation, after all data are in (the full 24×3 matrix and the first
Qwen-3.8-as-redteam timing data are required deliverables regardless).

1. **gemma-current** — production redteam as deployed
   (`CRITIC_BACKEND=vllm-gemma`, production budgets `max_turns=3`,
   `max_wall_seconds=45.0` — pinned here, not resolved at run time).
2. **gemma-revised** — the appendix prompt, same backend/budgets.
3. **qwen38** — the gemma-current prompt, `CRITIC_BACKEND=vllm-qwen`
   (qwen3.8-27b-nvfp4-mtp), same budgets.

## Fixtures (24; manifest frozen at lock, each row
`{id, hypothesis_text, label, provenance, label_rationale}` — every label
defended on its merits under the fatal-flaw definition, never by
provenance alone)

**Known-good (12):**
- (a) the 2 distinct genuine historical proceeds — resolution rule
  verbatim: `redteam.verdict=="proceed" AND subagent_status=="passed"` in
  loop_memory (yields iter-2026-06-09-005, iter-2026-06-09-006,
  iter-2026-06-19-012; **-006 is dropped** as a 0.998-similarity
  near-duplicate of -005 so one judgment cannot consume two slots);
- (b) the exp003 Vickrey claim (label_rationale: a confirming LOCKED
  experiment proves testability — the benign direction of
  outcome-labeling);
- (c) the 3 expected-survives battery cases (novel_on_01/02/03 —
  novel_on_02 is the historically R0-over-gated case, a usefully
  adversarial known-good);
- (d) **6 constructed sound claims, register-matched to current
  production output**: 25–45 words each, and ≥2 of 6 carrying a
  mechanism-attribution clause (because/via/rather-than) that IS
  rescuable by a reasonable design (e.g. states its own ablation).
**Known-bad (12):**
- (a) the iter-2026-08-18-005 attribution-confound claim (flagged in the
  report as NON-INDEPENDENT for arm 1 — its own 3-day-old catch);
- (b) **7 planted-flaw constructions** (day-9 pattern: circularity,
  unfalsifiable clause, undefined metric, unrescuable confound,
  theorem contradiction, + 2 more distinct classes), register-matched;
- (c) the 2 nonsense battery cases;
- (d) **2 historical claims killed for INTRINSIC flaws** recorded in
  `run_state/frontier_cluster_screen.jsonl`: cl-iter-2026-06-05-005
  (mischaracterizes RDP composition; double veto) and
  cl-iter-2026-05-27-004 (mechanism logically insufficient).
  **Explicitly EXCLUDED from known-bad:** novelty-only vetoes, L0
  no-evidence-record vetoes ("experiment_outcome is null" is true of
  every pre-experiment hypothesis), and empirical Verdict=NO refutations
  — **a cleanly refuted claim was demonstrably testable and is
  proceed-class by definition.**

A disputed label is removed before lock, never after.

## Protocol

One redteam call per fixture per arm; production seam
(`workers.redteam_critic` exactly as production invokes it —
hypothesis_text alone, verified as production-faithful at
orchestrator/nara.py:944); fresh interpreter per arm; per-arm calls-log
isolation; `env -u MOCK_LLM`; artifacts to `bench/redteam_cal/runs/` with
full provenance. Verdicts recorded as returned (fatal_flaw / proceed /
unscored).

## Bars (LOCKED; independent — rule 4)

1. **Parse health:** ≤ 2 unscored rows of the arm's 24 calls (integers,
   not percentages; unscored rows excluded from discrimination
   denominators and reported).
2. **Catches the bad:** fatal_flaw on ≥ 75% of parsed known-bad (≥9/12
   at full parse).
3. **Passes the good:** fatal_flaw on ≤ 35% of parsed known-good (≤4/12).
4. **Gap (REPORTED, not load-bearing):** bars 2∧3 at these thresholds
   already imply a ≥40-point good/bad gap — bar 4 is a reported
   diagnostic, stated as such (the critique showed it can never bind).

**Statistics on the record:** exact Clopper-Pearson 95% CIs per rate in
the report, plus the honest caveat: at n=12/class a zero-discrimination
coin passes bars 2∧3 with ≈1.4% probability per arm and a weak 60/40
instrument with ≈10% — this battery discriminates condemners and coins
from calibrated instruments, not strong from mediocre ones. The
known-good confusion row is split by provenance (real-historical /
battery / constructed) so a register-split pass is visible — an arm that
proceeds on June-register classics while condemning August-register
hypotheses has NOT passed in spirit and the split will show it.

## Adoption rule

The first arm in order [gemma-current, gemma-revised, qwen38] passing
bars 1–3 becomes the production redteam configuration. The backend
re-seat is pre-ratified by D-075; **the prompt swap (if gemma-revised
wins) is ratified by the LOCK COMMIT itself** (the revision text is in
this document at lock — cite the commit, not D-075). If NO arm passes:
the cap's disposition returns to the owner with the table — options
pre-stated: (i) keep cap knowing the instrument's character, (ii) demote
fatal_flaw to advisory-at-L1 while L4's `proceed` requirement still
blocks (must not recreate the D-053 advisory-ignored pathology),
(iii) commission a new instrument. No option auto-executes.

## Appendix — gemma-revised prompt (frozen at lock)

```
You are the RED-TEAM critic in the a_bgt_rsi research apparatus.

Your job: attack a research hypothesis BEFORE any experiment budget is
spent on it. Mount the strongest attack you can:
  - What is the STRONGEST counter-argument to this claim?
  - What KNOWN result (theorem, established finding) does it contradict?
  - Is it even TESTABLE as stated — or is it vague, circular, or
    unfalsifiable?

Then apply the ONE decision rule that separates the verdicts:

"fatal_flaw" means the claim CANNOT be rescued by ANY reasonable
experimental design. The defect lives in the claim itself, not in the
experiment someone might run on it. That standard is met when, and only
when, at least one of these holds:
  - it is logically incoherent, self-contradictory, or circular (it
    asserts nothing, or its cause is defined as its effect);
  - it contradicts a well-established theorem or finding, so the
    predicted outcome cannot occur as stated;
  - it is unfalsifiable as stated — every possible observation is
    consistent with it, or it turns on a construct that is unmeasurable
    in principle;
  - its central attribution cannot be identified by ANY design, because
    every available manipulation moves the claimed mechanism and its
    stated alternative together.

A FIXABLE weakness is NOT a fatal flaw. If a reasonable design choice —
a control condition, an ablation, a sharper operationalization, a
stated measurement — would rescue the claim, the verdict is "proceed",
and you MUST name that weakness and the design step that addresses it
in `critique`. Missing controls, definable-but-undefined details,
uncertain truth, likely-false predictions, interpretive ambiguity, and
lack of novelty are ALL proceed-class. A claim that looks wrong but is
cleanly testable PROCEEDS — the experiment is how it dies. Uncertainty
is why we experiment.

Do NOT run experiments. Do NOT be charitable for its own sake. But be
intellectually honest in both directions: condemning a rescuable claim
wastes a hypothesis just as surely as testing an unrescuable one wastes
the budget.

Return ONE of two verdicts:
  - "fatal_flaw" — unrescuable by any reasonable design; give the
                    killer critique and a suggested revision.
  - "proceed"    — testable as stated, or rescuable by a reasonable
                    design; name the strongest remaining weakness in
                    `critique`.

When you've judged, emit a FINAL assistant message that is STRICT JSON,
nothing else — no prose, no markdown fences, no channel markers. Schema:
{
  "verdict": "fatal_flaw" | "proceed",
  "critique": "<2-4 sentences: the strongest attack you could mount>",
  "suggested_revision": "<a reworded testable hypothesis>" | null,
  "confidence": <float 0.0-1.0, your confidence in the verdict>
}

`suggested_revision` is non-null ONLY for "fatal_flaw".
```
