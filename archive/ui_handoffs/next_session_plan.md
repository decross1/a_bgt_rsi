> ARCHIVED 2026-06-14 — executed/ superseded work order, kept for the record. Current UI handoffs live in the session note (human/sessions/), current state in LOOP_V0.md.

# Next-session plan (handoff from the 2026-06-09 validation session)

**Status:** plan/handoff. Authored at the close of the 2026-06-09 validation session
(see [`human/sessions/2026-06-09-validation.md`](../../human/sessions/2026-06-09-validation.md)
and commits `d655da0`/`e1e2bb2`/`9886ccc`). Run it as one or more Dynamic Workflows
(build/probe limbs → serial integrator validates + commits), per the Dynamic Workflow
discipline in [`CLAUDE.md`](../../CLAUDE.md).

This session must address **all three** threads below. **Thread 1 is foundational** —
the apparatus's core capability (novelty + falsification) is currently unreliable, and
both Thread 2 (autonomous runs) and Thread 3 (promotion) are only as trustworthy as the
literature pipe. Suggested order: **T1 first**, then T2 and T3 (which are independent of
each other and can run in parallel).

## What the validation session established (grounding)
- **β write-capable seam PROVEN.** From inside nara-sandbox, `run_loop_iteration` drives a
  full host LOOP_V0 iteration (`iter-2026-06-09-003`, `seed.source=nemoclaw_agent`). Tool
  plane: `orchestrator/tool_plane.py` on `:8077` (`get_apparatus_state` + `run_loop_iteration`).
- **Literature pipe needs refinement** (battery: 50% verdict accuracy, off-domain gate
  recall 0/2). Instrument: [`experiments/lit_falsification_battery/`](../../experiments/lit_falsification_battery/)
  (13 labelled cases + `battery.py`; real run `env -u MOCK_LLM .venv-chroma/bin/python -m experiments.lit_falsification_battery.battery`).
- **Full in-sandbox agent autonomy blocked** on native-tool wiring (the agent has no shell
  tool; needs MCP registration). SKILL.md persona already installed in the sandbox.

---

## THREAD 1 (foundational) — refine the literature pipe so it falsifies accurately

**Hypothesis under repair:** the 2026-06-09 retrieval-relevance gate is lexical-overlap-only
and is defeated by (a) off-domain hypotheses carrying on-domain vocabulary and (b) corpus
drift; and the critic only down-ranks on a *direct contradiction* (never on restatement or
off-domain irrelevance). Evidence: `fase_off_01` overlap 0.127, `fase_off_02` 0.193 (vs the
real bug's 0.043); 3/3 on-domain rediscoveries scored `survives` not `restated`.

**T1a — relevance gate: add a SEMANTIC topicality signal** (`workers/retrieval_relevance.py`).
Lexical overlap alone is gameable; raw neighbor cosine doesn't separate (BGE-M3 cosines
cluster 0.53–0.74 — the module docstring already notes this). The missing signal is **cosine
of the hypothesis to a GT-DOMAIN ANCHOR** (not to the retrieved neighbors): embed the
hypothesis and compare against a centroid of the *curated foundational GT corpus* (or a small
fixed set of GT anchor sentences/terms). An off-domain hypothesis (code quality, DB tuning)
sits far from the GT-domain anchor even when it shares surface vocabulary. Gate fires
low-confidence when EITHER the lexical overlap is thin OR the domain-anchor cosine is low.
Keep the thresholds calibrated against the battery, not a single instance (see P-009 in the
framework brain).

**T1b — critic: restatement-detection + off-domain-temper** (`workers/critic_loop_v0.py`,
`workers/novelty_classify.py`). The critic must: (1) return `restated` when retrieved
literature *restates* the claim (not just `survives` when it finds no contradiction —
"absence of contradiction" ≠ "survives"); (2) never assert `survives`/`novel` when the
relevance gate flags low_confidence (hard rule, not a soft prompt nudge). Consider routing
the verdict through the cross-model Qwen skeptic (obtainable now — see the human-decision
note) so "survives" requires surviving an independent attack.

**T1c — corpus de-drift** (`workers/retrieve_literature.py`). Constrain the default
novelty/critic retrieval to **curated GT collections**; exclude/down-weight `ml_intern_fetched`
+ the `day3_*` fixture pollution (`fase_off_02` retrieved Belief Engine / MUSE-Autoskill / ATOM
— non-GT arXiv). Tag `source_layer` provenance and have the relevance gate treat non-curated
neighbors as weak evidence.

**T1d — regression** (`experiments/lit_falsification_battery/`). Re-run the battery after each
change; **bar: ≥80% verdict accuracy AND gate recall 1.0 on off-domain AND 0 ungated
novel/survives**. EXPAND the case set with more adversarial off-domain variants (vocabulary-
camouflaged, drifted-corpus-adjacent) so the gate can't be over-fit again. Log a
`DECISIONS.md` entry for the finding + the fix direction (references P-009).

**Limbs:** T1a, T1b, T1c are largely disjoint files (parallel build limbs); T1d (re-run +
expand battery) is the serial integrator's verification. Real measurement is serial, `env -u
MOCK_LLM`, one at a time (memory).

---

## THREAD 2 — wire full in-sandbox agent autonomy (path-a MCP)

**Goal:** Nara (the in-sandbox OpenClaw `main` agent, local Gemma) calls the host tools
*itself* — assess → form ONE thesis → `run_loop_iteration` → report — completing the
autonomous end-state. DEMO 2a already proved the seam; this is the agent-autonomy layer.

**Blocker (resolved diagnosis):** the agent has only `tool_search_code` natively (no
shell/exec), so the path-b SKILL.md `curl` can't execute. Path-a is required:
1. **Confirm the v2026.5.18 `openclaw.json` MCP-server block schema** — do NOT guess into a
   live config. Sources: `nemoclaw nara-sandbox exec -- openclaw config file` (find the config),
   `openclaw config get/validate`, the NemoClaw/openclaw clone under `clones/`, docs.openclaw.ai.
   Find how `tool_search_code` is registered as the template.
2. **Register the host tool plane** (`http://host.openshell.internal:8077`, tools
   `get_apparatus_state` + `run_loop_iteration`) as an MCP/HTTP tool server for the `main`
   agent. Egress preset `nara-host-tool-plane` is already applied (policy v15); `/usr/bin/curl`
   and the alias are allow-listed.
3. **Re-drive** `nemoclaw nara-sandbox exec --no-tty --timeout 580 -- openclaw agent --agent main
   --json --message "<assess→thesis→run→report>"`. Verify the 6 PASS criteria in
   [`docs/nemoclaw_agent_run_runbook.md`](../../docs/nemoclaw_agent_run_runbook.md) §"PASS criteria"
   (esp. the H1 tool-plane terminal logging BOTH inbound POSTs, and an honestly-reported
   verdict — a coerced `survives` on thin retrieval is a FAIL).

**Caution:** sandbox-mutating steps (`onboard`/`rebuild`) stay human-gated; the current
runtime needs none. The `nara-research-cycle` SKILL.md (persona) is already installed.

**Trust dependency:** an autonomous agent run is only as trustworthy as Thread 1 — land T1
before trusting T2's autonomous verdicts.

---

## THREAD 3 — build the reverse-path thesis → classical-game → semi-synthetic constructor

**Design is done:** [`docs/thesis_to_experiment_construction.md`](../../docs/thesis_to_experiment_construction.md)
(the missing REVERSE arrow; the one-directional `experiment_outcome` bridge into the loop
already exists). Build the smallest slice:
1. **`orchestrator/thesis_to_experiment.py`** — deterministic dispatcher: a surviving thesis
   (novelty∈{novel,unclear} + critic `survives` + `low_confidence` false) → a classical game
   over the fixed table (PD / public goods / stag hunt / Cournot / Vickrey / VCG) + a
   pre-registered experiment spec (mirror `exp003`'s `VERDICT_THRESHOLD` pattern).
2. **`experiments/exp001_repeated_pd/loop_bridge.py`** (add the missing bridge) + a new
   **`experiments/exp00X_cournot/{run,analyze,loop_bridge}.py`** for the worked example
   (`iter-2026-06-06-001` Cournot). Reuse `autoresearch.py` + the `experiment_outcome` bridge.
3. **Spine touch (integrator):** add the new experiment id to
   `orchestrator/tier_registry.py::_TIER_MAP` under `"synthetic"`.
4. **Worked examples** in the design doc: `iter-2026-06-06-001` (Cournot), `iter-2026-05-27-001`
   (PD narrative-vs-list — testable with NO new experiment). Validate/invalidate → bridge the
   `experiment_outcome` back → promote to semi-synthetic (`exp006` LLM-as-designer path).

**Note:** per the human's framing, it is fine if no current thesis survives to promotion — the
deliverable is the validated construction PATH. Autonomous *promotion* is **D-041-gated**.

---

## Cross-cutting human decisions (carry into the session; some gate the work)
- **Independent skeptic (gates T1b's strongest form + T3's promotion):** the Qwen cross-model
  signal is **obtainable now** (root cause was token starvation; `finding_promotion.py` already
  uses `max_tokens=3072` — see `docs/thesis_to_experiment_construction.md` Part 2). But promoting
  on it autonomously is **D-041**-gated, and the off-box **Claude** skeptic alternative is the
  **D-014/ToS** decision. Decide the cross-model-trust mechanism as one unit.
- **Ratify the still-pending decisions** from the 2026-06-09 morning: D-039 (exp008 SHELVE),
  D-031/D-008 ("mechanical NemoClawRuntime swap" amendment — now empirically settled), and
  confirm the D-041 reservation.
- **P-009** (framework brain) is open: "calibrate a discriminative gate against a varied set,
  not a single instance" — the methodology lesson behind T1.

## Discipline reminders (Dynamic Workflow)
- Check `git worktree list` for a live `ui-session` first — **no workflow agent writes `ui/`**
  (render work routes via `docs/ui_validation_handoff.md`). T1/T2/T3 don't touch `ui/`.
- Build limbs: disjoint NEW files only; the spine (`nara.py`, `tool_registry.py`,
  `schema/*.json`) is integrator-only (DRAFT edits for limbs). Spawn ledger + run-log per rules
  3/6; framework `code-review` (not the GitHub builtin) per rule 4; `narrate` at synthesize.
- All real-model runs serial, `env -u MOCK_LLM`, `.venv-chroma/bin/python` (no bare `python`);
  watch the unified memory pool (gemma + qwen + an iteration).
