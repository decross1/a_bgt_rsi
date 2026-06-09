# Thesis → classical-game experiment → semi-synthetic promotion

Status: DESIGN + DIAGNOSIS (read-only limb L5). No spine edits; no code
written. Part 1 is a construction spec naming concrete build points; Part 2
is a read-only diagnosis of the Qwen independent-skeptic gate with the exact
fix and an obtainable-vs-carryover verdict.

Authored against: `docs/sources/research_program_v2.md` (the sandbox
spectrum), `orchestrator/autoresearch.py`, `orchestrator/tier_registry.py`,
`orchestrator/finding_promotion.py`, `experiments/replication_driver.py`,
`experiments/exp001_repeated_pd/`, `experiments/exp003_vickrey_rediscovery/`,
`experiments/exp006_mechanism_design/`,
`schema/iteration_record.schema.json`, `schema/surfaced_finding.schema.json`,
`workers/novelty_skeptic.py`, and a survivor scan of
`memory/loop_memory.jsonl` (49 rows, 22 survivors as of 2026-06-09).

---

## PART 1 — Surviving thesis → classical-game experiment → semi-synthetic

### 0. The gap, stated precisely

Today the data flow is **one-directional**:

```
experiment (run.py)
  → analyze.py (results/summary.{md,json}, pre-registered verdict)
  → loop_bridge.build_experiment_outcome()  (experiment_outcome payload)
  → autoresearch.run_autoresearch(..., live=True)
  → nara.run_iteration(experiment_outcome=...)  (the LOOP_V0 chain)
  → loop_memory row with an experiment_outcome field
```

A finding that *starts* as an experiment gets its literature evaluation
(novelty + critic) grounded in real evidence. But a finding that *starts* as
a **literature thesis** — the dominant case: 22 of 49 loop_memory rows are
literature-only survivors with `novelty.class ∈ {novel, unclear}`,
`critique.verdict == "survives"`, `low_confidence` false, and **no
`experiment_outcome`** — never gets experimentally tested. The loop's verdict
on it is *literature-only*: "no neighbor refutes it" is not "an experiment
supports it."

The human's missing piece is the **reverse arrow**:

```
surviving literature thesis (loop_memory row)
  → CONSTRUCT a synthetic-tier classical game that could validate/invalidate it
  → run.py + analyze.py (pre-registered verdict)
  → loop_bridge → experiment_outcome → BACK into run_iteration
  → (then) PROMOTE to semi-synthetic (exp006 LLM-as-designer)
```

Nothing in the apparatus walks a thesis *down* the sandbox spectrum into an
experiment. That single constructor is the smallest build that closes the
gap. Per the human's framing, **it is fine if no current thesis survives all
the way to promotion** — the deliverable here is the construction PATH,
validated as sound against the real survivors.

### (a) Decision procedure: thesis → classical game

The constructor is a **dispatcher over a small, fixed table** of classical
games with known equilibria — not a general game synthesizer (resist
abstraction). It reads a loop_memory row and routes on game-theoretic
keywords already present in the thesis text + retrieval neighbors, picking
the *cheapest synthetic game whose known equilibrium the thesis makes a
prediction about*.

| Thesis names / implies… | Classical game | Known equilibrium (the anchor) | Reuses |
|---|---|---|---|
| cooperation, defection, repeated PD, tit-for-tat, reciprocity, history framing | **repeated PD** | folk-theorem cooperation vs reciprocators; defect vs all-D | `exp001_repeated_pd/` (run.py, llm_agent.py, strategies.py) |
| contribution, free-riding, conditional cooperation, public goods | **public goods game** | MPCR-dependent Nash contribution (interior/0) | *(no exp yet — see (c): genuinely missing)* |
| coordination, risk-dominance, payoff-dominance, stag hunt, equilibrium selection | **stag hunt** | risk-dominant vs payoff-dominant pure equilibria | *(no exp yet — adapt exp001 2×2 harness)* |
| quantity competition, duopoly, oligopoly, Cournot, marginal cost | **Cournot** | symmetric Cournot–Nash quantity q\* = (a−c)/((n+1)b) | *(no exp yet — genuinely missing)* |
| sealed-bid, second-price, Vickrey, truthful bidding, dominant strategy | **second-price / Vickrey auction** | truthful bidding is dominant | `exp003_vickrey_rediscovery/` (full set) |
| combinatorial bids, bundles, VCG, complementarity | **combinatorial VCG auction** | VCG strategyproof truthful | `exp004_combinatorial_auction/` |

Routing rule (deterministic, ranked): match thesis text + neighbor titles
against each row's keyword set; pick the **first matching row that already
has a built experiment** (cheapest path — reuse run.py/analyze.py unchanged
with a thesis-derived condition); if the only match has no built experiment,
emit a **design-only stub** that names the missing experiment rather than
silently mapping to the wrong game (inviolate rule 4 — never coerce). No
match → return `None` with a logged reason; that thesis is not constructible
in the synthetic tier yet, which is itself a recordable finding.

#### Worked example (REAL survivor)

`iter-2026-06-06-001` (loop_memory, 2026-06-06):

> "The convergence of LLM agents to the Nash quantity in a Cournot duopoly is
> modulated by the presence of few-shot prompting examples that explicitly
> define the marginal cost parameter, which reduces the variance of the
> agents' quantity-selection logits."
>
> novelty.class = `novel` (low_confidence absent/false); critique.verdict =
> `survives`; no `experiment_outcome`.

This is a textbook reverse-gap survivor: it survived the *literature* loop
(no neighbor covers Cournot-convergence under few-shot marginal-cost priming)
but has **never been run**. The loop "believes" it only because nothing
refuted it.

- **Routing:** keywords *Cournot / duopoly / Nash quantity / marginal cost* →
  **Cournot** row. No built Cournot experiment exists → the constructor emits
  the experiment SPEC below and flags it `design_only=True` (buildable-now,
  small).
- **The classical game + known equilibrium:** symmetric Cournot duopoly,
  linear inverse demand P(Q) = a − bQ, constant marginal cost c. Known
  unique Nash quantity per firm q\* = (a − c)/(3b) (n = 2). This is the
  *validation anchor*: the thesis is a claim about deviation-from-q\* and its
  **variance** under a prompting manipulation.

A clean second REAL example, for the PD path that reuses an existing
experiment unchanged: `iter-2026-05-27-001`:

> "LLM agents in a repeated Prisoner's Dilemma will exhibit significantly
> higher cooperation rates when the history of interactions is presented as a
> cohesive **narrative** compared to a structured **list** of move
> sequences." (novel + survives, no experiment_outcome)

- **Routing:** *repeated Prisoner's Dilemma / cooperation / history* → **PD**
  row, which HAS `exp001_repeated_pd/`. The manipulation (narrative vs list
  history rendering) is exactly the `--rules-variant` axis exp001's run.py
  already exposes (`llm_agent.RULES_VARIANTS`). This thesis is testable with
  **no new experiment code** — only two run.py invocations and a paired
  analysis. This is the cheapest possible construction and the one to
  validate the path on first.

### (b) The experiment spec the constructor must emit

A small JSON/dict the constructor produces from the thesis — the contract the
run gets driven from. It deliberately mirrors the **pre-registered-threshold**
pattern the apparatus already uses (exp003 `analyze.py`:
`VERDICT_THRESHOLD = 0.75`, a constant committed in the analyzer *before* the
run; the archived `notes/day7_expected_range.md` is the same discipline for
exp001). Fields:

```jsonc
{
  "source_iteration_id": "iter-2026-06-06-001",
  "game": "cournot",                       // table key from (a)
  "claim": "<verbatim thesis text>",
  "treatment": {                           // the manipulation under test
    "factor": "few_shot_marginal_cost",    // named, from the thesis
    "levels": ["absent", "explicit"]        // control vs treatment arm
  },
  "opponent_classes": ["self_play", "fixed_nash_responder"],  // PD: tft/all_d/...
  "metric": "mean_abs_deviation_from_nash_quantity",  // + "quantity_variance"
  "n_trials": 50,                          // ≥ MIN_TRIALS (30) — see (d)
  "expected_range": {                      // PRE-REGISTERED, before the run
    "primary": [0.0, 0.15],                // |q − q*| / q* band if thesis holds
    "directional": "variance(explicit) < variance(absent)"
  },
  "equilibrium_anchor": "q_star = (a - c) / (3 b)",
  "design_only": true                      // false when run.py exists (PD path)
}
```

The `expected_range` + `directional` fields are the **pre-registration** that
makes validate/invalidate honest: the analyzer compares the observed metric
to a band fixed *before* the data exist, and "below band but close" is a FAIL
(inviolate rule 4), not a nudge into a pass. For the PD example the spec is
identical in shape: `factor: "history_framing"`, `levels: ["list",
"narrative"]`, `metric: "coop_rate"`, `expected_range.directional:
"coop(narrative) > coop(list)"`, with the per-arm coop-rate band taken from
the archived Horton-style range (~0.60–0.95 vs reciprocators).

### (c) The wiring — exact new build points vs already-present

**Already present (reuse, do NOT reimplement):**
- `experiments/exp001_repeated_pd/run.py` — already takes `--rules-variant`
  (the narrative-vs-list axis) and `--temperature`; analysis under
  `analysis/` + `quicklook.py`.
- `experiments/exp003_vickrey_rediscovery/{run.py,analyze.py,loop_bridge.py}`
  — the canonical run → pre-registered-verdict → `build_experiment_outcome()`
  template. **Copy this trio's shape for any new game.**
- `orchestrator/autoresearch.py::run_autoresearch(tier, experiment_id, ...,
  live=True)` — already resolves an experiment via the tier registry, builds
  the `experiment_outcome` via the experiment's `loop_bridge`, and threads it
  through **exactly one** `run_iteration`. The constructor's output plugs in
  here unchanged: it produces a (tier, experiment_id) the driver already
  knows how to run.
- `orchestrator/tier_registry.py` — filesystem-inspection registry; a new
  experiment dir with run.py/analyze.py/loop_bridge.py is auto-discovered
  once its id is added to `_TIER_MAP` (a one-line spine edit — see drafts).
- `schema/iteration_record.schema.json::experiment_outcome` — **no new field
  needed**; the reverse path reuses the same `{experiment_id, metric, value,
  trials, summary, results_path}` the forward path uses.

**Genuinely missing — the smallest build that closes the gap:**

1. **`orchestrator/thesis_to_experiment.py`** (NEW; ~120–180 lines, matches
   worker norms). One module:
   - `select_game(row: dict) -> str | None` — the deterministic dispatcher of
     (a) over the fixed keyword table. Pure Python, no model call.
   - `build_experiment_spec(row: dict) -> dict` — emits the (b) spec,
     including the pre-registered `expected_range` (derived from the game's
     known equilibrium constant, not from any model).
   - `resolve_or_design(spec: dict) -> dict` — if the game's experiment is
     built (`tier_registry.get_experiment` succeeds + `has_run`), return
     `{buildable_now: True, experiment_id, run_args}`; else return
     `{design_only: True, missing: <what to build>}`.
   - a `main()` CLI mirroring loop_bridge's `--dry-run` (default, no model)
     vs `--emit-spec` so it is testable under `MOCK_LLM`.
   This module is **pure dispatch + spec emission** — it does NOT run the
   model and does NOT touch the spine.

2. **Per-game experiment dirs** (NEW, only the ones a real survivor needs):
   - Cournot (`exp00X_cournot/`): `run.py` + `analyze.py` + `loop_bridge.py`,
     copying exp003's shape. `run.py` plays N Cournot rounds (self-play +
     a fixed-Nash responder) at each treatment level; `analyze.py` computes
     `mean_abs_deviation_from_nash_quantity` + `quantity_variance` per arm
     and emits a pre-registered YES/NO verdict against `expected_range`;
     `loop_bridge.build_experiment_outcome()` reads the summary into the
     standard payload. This is the buildable-now closer for the Cournot
     survivor.
   - Public goods / stag hunt: design-only stubs for now (the constructor
     emits `design_only=True`); build on demand when a survivor routes there.
   - **PD path needs NO new experiment** — exp001 already supports the
     narrative-vs-list treatment via `--rules-variant`; it only lacks a
     `loop_bridge.py` (exp001 predates the convention, per tier_registry).
     Adding `experiments/exp001_repeated_pd/loop_bridge.py` (NEW, ~90 lines,
     copy exp003's) makes the cheapest survivor (`iter-2026-05-27-001`)
     end-to-end runnable. **This is the single highest-leverage new file.**

3. **Constructor → autoresearch hand-off** (NO new orchestrator code).
   `thesis_to_experiment.resolve_or_design()` returns a (tier,
   experiment_id); a human (or a thin CLI) passes those to
   `autoresearch.run_autoresearch(tier, experiment_id, run_experiment=True,
   live=True)`. The single-shot/human-triggered guardrail is preserved — the
   constructor only *proposes*; the human triggers the run. No loop, no
   scheduler.

**Flagging:** build point 1 (the constructor) + the exp001 loop_bridge (2,
third bullet) are **buildable-now** and together validate the whole path on a
real survivor with one experiment that already exists. The Cournot dir is
buildable-now but is net-new experiment code. Public goods / stag hunt dirs
are **design-only** until a survivor demands them.

### (d) validate/invalidate → experiment_outcome bridge back in

Once the constructed experiment runs, the verdict re-enters the loop through
the **existing** bridge, so the iteration's verdict becomes
experiment-grounded rather than literature-only:

1. `analyze.py` writes `results/summary.{md,json}` with the pre-registered
   verdict (`Verdict=YES` validates the thesis; `Verdict=NO` invalidates it —
   and `NO` is the *more* valuable signal: it is a literature survivor the
   experiment refutes).
2. `loop_bridge.build_experiment_outcome()` produces
   `{experiment_id, metric, value, trials, summary, results_path}`. Crucially
   the `summary` string carries `Verdict=YES|NO` — the **same token**
   `finding_promotion._SURPRISE_RE` (`/Verdict=NO|signed_residual/i`) keys on.
3. `autoresearch.run_autoresearch(..., live=True)` threads it into
   `run_iteration(experiment_outcome=...)`. The *new* iteration's
   `experiment_outcome` field now holds the experimental test of the thesis,
   alongside a fresh novelty + critic pass.

Downstream this directly upgrades promotion (`finding_promotion.py`):
`_passes_threshold` gives a `novelty ∈ {novel, unclear}` + `Verdict=NO`
result the **surprising-vs-theory** pass (a refuted literature thesis becomes
exactly the "unclear but experimentally surprising" candidate worth a human's
attention), while the trials floor (`MIN_TRIALS = 30`) is why (b)'s `n_trials`
is 50. A literature-only survivor that the experiment refutes is *more*
promotable than one nobody tested — the reverse arrow turns "unfalsified" into
"tested."

### (e) Promote to semi-synthetic (the exp006 LLM-as-designer path)

The semi-synthetic rung already exists: `exp006_mechanism_design` — the LLM
DESIGNS the mechanism (allocation + payments) rather than playing a fixed one,
scored against the VCG benchmark (`designer_mean_efficiency`,
`feasibility_rate`), with its own `loop_bridge.build_experiment_outcome()`.
Promotion of a *synthetic* finding to semi-synthetic means: take a thesis that
survived as a **bidder/player** result and re-pose it as a **designer**
question.

- **Promotion criteria (proposed):** a synthetic-tier construction is
  promotion-eligible when (i) its synthetic experiment returned a clean
  pre-registered verdict at `trials ≥ 30`, (ii) `novelty.class ∈ {novel,
  unclear}` and `critique.verdict == survives` on the bridged iteration, and
  (iii) the game has a **designer-side analogue** — i.e. the equilibrium the
  player rediscovered is one a designer could be asked to *construct*
  (auctions → mechanism design is the existing path; Cournot → designing the
  demand/cost regime is a stretch and stays design-only).
- **The mechanism:** reuse exp006 wholesale. exp006 already turns "LLM as
  VCG bidder" (exp003/exp004, synthetic) into "LLM as mechanism designer"
  (semi-synthetic) for the auction family. A promoted auction-family thesis
  routes to a new `propose_*` trial in exp006's pattern; the same
  `loop_bridge → experiment_outcome → run_iteration` bridge carries it back.
- **What blocks it today:**
  1. **No promotion trigger wired.** Promotion is a manual human decision;
     there is no `synthetic → semi_synthetic` promoter analogous to
     `finding_promotion.py`. The replication_driver is honest that there is
     "no semi-synthetic rung" in its *cross-tier* comparison even though
     exp006 exists — i.e. the rungs are not yet linked by an automated
     promote step. Design-only for now (and correctly so: it must not
     auto-fire past a human gate).
  2. **Designer analogue only exists for the auction family.** exp006 is
     auction-specific (reuses exp004's `bundles` + `mechanism_designer`). PD /
     public goods / stag hunt / Cournot have **no** designer-side experiment;
     promoting those is design-only until a designer harness exists for them.
  3. **The cross-model trust gate (Part 2) must be real first.** Promotion to
     a human's scarce attention rides on `finding_promotion.py`'s independent
     Qwen vote (the anti-D-036 lever). That gate is currently degraded — see
     Part 2 — and its activation is **D-041-gated**. A semi-synthetic
     promotion should not outrun a working independent skeptic.

**Smallest sound promotion step:** none needed to *prove the path* — exp006
already demonstrates synthetic→semi-synthetic for auctions end-to-end. The
honest statement is: the **construction path down (Part 1 a–d) is the build;
the promotion up (e) is already demonstrated for one game family and is
design-only for the rest**, correctly gated behind a human decision and a
working Part-2 skeptic.

### Part 1 minimal-build summary

| Build point | File | Status | Closes |
|---|---|---|---|
| Thesis→game dispatcher + spec emitter | `orchestrator/thesis_to_experiment.py` (NEW) | buildable-now, ~150 lines | the reverse arrow (a)(b) |
| PD loop_bridge (cheapest survivor path) | `experiments/exp001_repeated_pd/loop_bridge.py` (NEW) | buildable-now, ~90 lines | validates path on `iter-2026-05-27-001` w/ no new experiment |
| Cournot experiment trio | `experiments/exp00X_cournot/{run,analyze,loop_bridge}.py` (NEW) | buildable-now, net-new | closes `iter-2026-06-06-001` |
| Tier-registry entry for new games | `orchestrator/tier_registry.py::_TIER_MAP` | SPINE — draft only | discovery |
| Public goods / stag hunt | dirs | design-only | future survivors |
| Synthetic→semi promotion trigger | — | design-only (human-gated) | (e) |

Nothing in autoresearch.py, nara.py, or the iteration_record schema's
`experiment_outcome` needs to change — the reverse path reuses the forward
path's machinery.

---

## PART 2 — Qwen independent-skeptic diagnosis (read-only)

### Why this matters

`finding_promotion.py`'s stage 2 — the **cross-model adversarial multi-vote**
— is the apparatus's trust mechanism for promotion and the substance of the
D-041 beta-gate: `n_skeptics` independent Qwen skeptics (a *different* model
family than the Gemma that generated the finding — the anti-D-036 lever
against a model grading its own novelty) each attack the claim and evidence.
If Qwen emits nothing, every survivor hits `qwen_failures`, the quorum is
unmet, and promotion yields a `near_miss (inconclusive)` — never a real
independent signal. The same dependency sits under `novelty_skeptic.py`
(D-033 mitigation).

### Observed state (read-only probes, 2026-06-09)

`:8001` is **UP**: `curl localhost:8001/v1/models` →
`qwen3.6-27b-nvfp4-mtp`, `max_model_len = 16384`.

Three live `curl` probes against `:8001/v1/chat/completions` (the same MTP
model the skeptics use):

| Prompt | max_tokens | finish_reason | content | reasoning_content | completion_tokens |
|---|---|---|---|---|---|
| trivial ("reply `{"ok":true}`") | 512 | `stop` | `'\n\n{"ok": true}'` | **absent** | 135 |
| adversarial-skeptic (Cournot claim) | 512 | **`length`** | **`''` (empty)** | **absent** | 512 |
| adversarial-skeptic (same) | 3072 | `stop` | full 1541-char body **ending in valid JSON** (`"confidence": 0.9`) | absent | 2068 |

### Root cause (diagnosed, not guessed)

**Token starvation, NOT a missing reasoning channel.** The model is served
**without `--reasoning-parser`**: even the trivial prompt returns its answer
directly in `content` and there is **no `reasoning_content` field at all**
(confirmed in all three probes). The MTP/reasoning model emits its chain of
thought **inline in the `content` channel**, then the final JSON. The
adversarial-skeptic prompt provokes ~2000 tokens of inline reasoning before
the closing `{verdict, attack, confidence}`. At `max_tokens=512` the
generation is truncated mid-reasoning (`finish_reason=length`) **before** the
JSON is reached → `content` is the truncated reasoning, the balanced-brace
extractor finds no complete object, and the call is counted as a
`qwen_failure`. (The "`content=None`" in the original report is the same
phenomenon — an OpenAI client surfaces a length-truncated, JSON-less
completion as empty/None.)

This also explains why `subagent.py`'s reasoning-slot fallback (lines
357–367, reading `reasoning_content`/`reasoning` from `model_extra`) does
**not** rescue it: the server emits no such field, so there is nothing in the
reasoning slot to parse. The fallback was written for a `--reasoning-parser`
deployment that is not the current one.

### The exact fix

**Primary fix (sufficient, and ALREADY in place for the promotion path):
raise `max_tokens` ≥ 2048.** The third probe proves a real, parseable,
schema-valid skeptic verdict is obtained at `max_tokens=3072` (well within
`max_model_len=16384`).

- `orchestrator/finding_promotion.py` **already** sets
  `budget = SubAgentBudget(max_turns=4, max_wall_seconds=240.0,
  max_tokens_per_turn=3072)` (lines 261–264) and `subagent.py` passes
  `max_tokens=budget.max_tokens_per_turn` per turn (line 296). **The
  promotion path's Qwen budget is already correct.** No edit needed there for
  the token issue.
- `workers/novelty_skeptic.py` is **partially fixed**: it already raises the
  Qwen route to `2048` (`skeptic_max_tokens = 512 if backend_name ==
  DEFAULT_BACKEND else 2048`, line 342), keeping `512` only for the default
  **gemma** self-check route. Given the probes, `2048` is on the edge (the
  Cournot skeptic used 2068 completion tokens); **recommend bumping the
  non-default route to 3072** to match finding_promotion and leave headroom.
  This is a one-line change inside an allowed-elsewhere worker (NOT this
  limb's file) and is the only outstanding token edit.

**Optional serving change (cleaner, not required this session): launch the
:8001 vLLM container with `--reasoning-parser` (Qwen3 family).** That routes
the inline CoT to a separate `reasoning_content` field, leaving `content` as
just the final JSON — which is what `subagent.py`'s fallback (lines 357–367)
was built to consume. Benefits: smaller `content`, cheaper extraction, the
existing fallback starts earning its keep. **Not needed to obtain a signal**
(the token bump already works) and it is a serving-side restart, so it is a
human/ops action, not a code edit. `max_model_len=16384` is already ample;
no max-model-len change is warranted.

**Do NOT** lower the schema bar or treat a truncated/empty completion as a
"stands" vote (inviolate rule 4) — `subagent.py` correctly counts it as a
`qwen_failure`, and finding_promotion correctly turns an unmet quorum into an
inconclusive `near_miss` rather than a silent promote. Keep that.

### The ollama-label provenance bug

`vllm-qwen` is registered (in `agent_wrapper/wrapper.py` lines 96–99) by
**reusing the `OllamaBackend` class** (it is an OpenAI-compatible wrapper, and
vLLM exposes the same API) pointed at `http://127.0.0.1:8001/v1` with
`model="qwen3.6-27b-nvfp4-mtp"`. Consequence: `OllamaBackend.host_metadata`
returns `{"backend": "ollama", "ollama_base_url": ...}`, so every wrapper call
on the Qwen route is **provenance-stamped `backend: "ollama"`** even though it
is a **vLLM** container on :8001. The model is not Ollama-served at all.

- **Impact is bounded but real.** The promoted-finding record
  (`finding_promotion.py` lines 619–620) stamps `adversarial.model =
  resolved_be.default_model` and `adversarial.backend = resolved_be.name` —
  both correct here (`"qwen3.6-27b-nvfp4-mtp"` and `"vllm-qwen"`, since
  `OllamaBackend` was constructed with explicit `name=`/`model=`). So the
  *surfaced_finding* provenance is fine. The mislabel lives in
  `host_metadata` (the per-call log provenance), where the Qwen route claims
  `backend: "ollama"`. Anyone auditing `logs/calls.jsonl` for "what served
  this skeptic vote" gets a false "ollama" answer.
- **Exact fix (design-only here; not this limb's file):** give the `:8001`
  registration an honest host_metadata. Cheapest: add a `host_metadata`
  override hook to `OllamaBackend.__init__` (a `host_label="vllm"` kwarg
  threaded into `host_metadata`), or register `:8001` via a thin `VLLMBackend`
  variant parameterized with a base_url instead of reusing `OllamaBackend`.
  Either is a small edit to `agent_wrapper/backends/` + `wrapper.py` (outside
  L5's `files_allowed`); flagged for the integrator / a backend-owning limb.
  It does **not** block obtaining a skeptic signal.

### Verdict: obtainable THIS session, or carryover?

**A real cross-model skeptic signal is OBTAINABLE this session** — proven by
the third live probe (valid `{verdict, attack, confidence}` JSON,
`finish_reason=stop`, at `max_tokens=3072`). The promotion path
(`finding_promotion.py`) already carries the correct `max_tokens_per_turn=3072`
budget, so it is **not blocked on the token issue** and would collect real
Qwen votes on a live `env -u MOCK_LLM` promotion run today.

Two genuine gates remain, neither a code blocker:

1. **D-041 ratification (human).** Activating the cross-model adversarial
   gate as the beta promotion trust mechanism is **D-041-gated**; per the
   inviolate human-gate rule, the *automated promotion-as-trust* use awaits
   the human's explicit ratification. The signal is obtainable now; promoting
   *on it autonomously* is not, until D-041 is cleared.
2. **The off-box Claude-skeptic alternative is a separate human decision.**
   Using an Anthropic-API skeptic instead of (or alongside) on-box Qwen is
   blocked on the Claude ToS / D-014 firewall decision (the runtime never
   touching off-box services) and credit/auth — that path is **carryover**,
   not resolvable this session by a probe.

**Bottom line for Part 2:** the on-box Qwen skeptic is *technically*
unblocked this session by the already-present `max_tokens=3072` budget (with a
recommended one-line bump of `novelty_skeptic.py`'s non-default route from
2048→3072, and an optional `--reasoning-parser` serving restart as cleanup).
The provenance mislabel ("ollama" on a vLLM route) is real, bounded to
host_metadata/logs (not the surfaced_finding), and fixable in
`agent_wrapper/backends/`. What is *carryover* is the human-gated
**activation** (D-041) and the off-box Claude-skeptic ToS/D-014 decision —
not the ability to get a signal.
