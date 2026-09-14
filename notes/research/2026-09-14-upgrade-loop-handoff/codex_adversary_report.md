## 1. KILL LIST

1. **The draft assigns frontier models a forbidden role.**  
   **Flaw:** Codex/Claude propose and synthesize apparatus or research changes.  
   **Why here:** Frontier CLIs are falsifiers-only; they may veto or annotate, never generate research or write loop memory. The weekly agenda is a narrow exception whose outputs remain inert until accepted ([CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:262), [D-061](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3109)).  
   **Falsifier:** An owner-ratified decision explicitly authorizing frontier-authored, nonresearch experiment cards, plus tests proving they cannot emit packets, edit code, or enter research memory.

2. **It creates a second control plane instead of extending the two already present.**  
   **Flaw:** The proposed weekly proposer/adversary/synthesis loop duplicates weekly frontier agenda synthesis and the D-066 self-improvement path.  
   **Why here:** `frontier_agenda` already runs both vendors and records inert proposals; D-066 already turns telemetry into a bounded, red-first Tier-P packet and exits through the dispatcher ([frontier_agenda.py](/home/decross1/projects/a_bgt_rsi/orchestrator/frontier_agenda.py:168), [self_improvement_loop.md](/home/decross1/projects/a_bgt_rsi/docs/self_improvement_loop.md:1), [D-066](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3232)).  
   **Falsifier:** A responsibility matrix demonstrating a required state transition that neither mechanism can represent and cannot be added as a small extension.

3. **Its “everything runs at temperature 0” baseline is false.**  
   **Flaw:** It treats wrapper defaults as the apparatus’s effective inference policy.  
   **Why here:** The wrapper defaults to `0.0/1.0`, but call sites override them; the central hypothesis worker already uses `temperature=0.7, top_p=0.95` and generates 1–3 candidates ([wrapper.py](/home/decross1/projects/a_bgt_rsi/agent_wrapper/wrapper.py:178), [hypothesize.py](/home/decross1/projects/a_bgt_rsi/workers/hypothesize.py:141)). The verified census found 17 overriding call sites.  
   **Falsifier:** An AST census joined to seven days of `logs/calls.jsonl`, grouped by `caller_tag`, showing that material roles actually resolve to temperature zero.

4. **The proposed profiles are labels, not executable specifications.**  
   **Flaw:** Values such as `none_or_low` and `medium_or_high` are ambiguous, and the draft treats reasoning effort as portable across Gemma, Qwen, and frontier models.  
   **Why here:** Local wrapper calls expose temperature, top-p, seed, and token cap—not reasoning effort ([wrapper.py](/home/decross1/projects/a_bgt_rsi/agent_wrapper/wrapper.py:178)). Qwen’s repo note says the live default is effectively `xhigh`, and that its reasoning knob remains unproven locally ([qwen38_role_setups.md](/home/decross1/projects/a_bgt_rsi/docs/qwen38_role_setups.md:137)). Codex’s frontier effort is a separate CLI pin ([frontier_cli.py](/home/decross1/projects/a_bgt_rsi/agent_wrapper/frontier_cli.py:75)).  
   **Falsifier:** A live backend-by-backend probe showing the exact accepted wire parameter, recorded resolved value, nonempty output, and role-level quality delta.

5. **`N=3 + critic` is an unmeasured tax presented as policy.**  
   **Flaw:** It multiplies generation and selection work without controlling total tokens or wall time.  
   **Why here:** `hypothesize()` already asks for 1–3 candidates and chooses the most mechanism-specific one. Adding another critic risks duplicate selection, correlated judgment, and substantially more Qwen wall time ([hypothesize.py](/home/decross1/projects/a_bgt_rsi/workers/hypothesize.py:31), [qwen38_role_setups.md](/home/decross1/projects/a_bgt_rsi/docs/qwen38_role_setups.md:20)).  
   **Falsifier:** A paired trial on frozen topics where single-candidate and `N=3 + critic` receive identical total output-token and wall budgets, and the latter improves blinded downstream task success.

6. **The 32K/64K weekly context ladder cannot run against production as configured.**  
   **Flaw:** It proposes contexts beyond the current served limits.  
   **Why here:** Gemma serves 32,768 tokens; Qwen serves 16,384. A wider Qwen profile changes utilization and memory risk and is a gated serve configuration, not an ordinary request parameter ([serve-models.sh](/home/decross1/projects/a_bgt_rsi/cron/serve-models.sh:25), [serve-models.sh](/home/decross1/projects/a_bgt_rsi/cron/serve-models.sh:45)). The 30-GiB OS margin is inviolate.  
   **Falsifier:** A scratch-window 64K request that succeeds with full provenance, no OOM/swap growth, `MemAvailable ≥30 GiB`, and unchanged/restored production residents.

7. **Its logging requirements cannot be added casually.**  
   **Flaw:** It asks for profile, reasoning, completion-state, and cost fields as though `calls.jsonl` were open-ended.  
   **Why here:** The top-level call schema has `additionalProperties: false`; adding those fields requires a schema change. `schema/` is Tier S for the self-modification path ([calls.jsonl.schema.json](/home/decross1/projects/a_bgt_rsi/schema/calls.jsonl.schema.json:7), [D-066](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3260)). Temperature, top-p, seed, model, usage, latency, backend, and max tokens are already present and should not be duplicated.  
   **Falsifier:** A backward-compatible schema proposal validated against every historical row, with an owner-ratified Tier-S decision and explicit consumer migrations.

8. **The proposed benchmark portfolio is a research program, not a weekly test.**  
   **Flaw:** Hundreds of tool/coding tasks plus several external suites and four context lengths cannot plausibly fit the requested two-hour box budget.  
   **Why here:** One existing 22-case Qwen battery took roughly 58 minutes; Qwen timed out on 18/24 red-team calls at production budgets ([stage3a artifact](/home/decross1/projects/a_bgt_rsi/bench/critic_eval/runs/stage3a_qwen3.8-27b-nvfp4-mtp_20260817T093138Z.json), [D-076](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3745)). The repo’s successful pattern is small frozen manifests, sentinels first, hard stop conditions, then expansion.  
   **Falsifier:** A fully enumerated manifest whose clean serial dry run finishes under 115 elapsed minutes, including setup, scoring, logging, and failure paths.

9. **Its headline metrics and external-scan claims are not auditable.**  
   **Flaw:** CTT, SUH, and RSR lack exact denominators, scorers, thresholds, and variance treatment. `frontier_API_cost` and source validity are not observable through the current frontier seam.  
   **Why here:** `invoke_frontier` records vendor, CLI version, role, duration, exit code, verdict placeholder, and prompt hash—neither output tokens nor billing nor cited-source verification ([frontier_cli.py](/home/decross1/projects/a_bgt_rsi/agent_wrapper/frontier_cli.py:27)). Rule 4 forbids converting a vague near-miss or composite score into a pass ([CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:210)).  
   **Falsifier:** Versioned scorers with frozen fixtures, independent pass/fail signals, three-repeat variance, and a cached source manifest proving every load-bearing external claim.

10. **The challenger lane confounds runtime, model, and inference policy while underspecifying rollback.**  
    **Flaw:** “Try another runtime” is meaningless if weights, quantization, template, parser, MTP, KV type, sampling, or context also change.  
    **Why here:** The existing qualification design isolates one variable, uses `:8002`, records image/model digests and flags, runs sentinels first, enforces memory stops, and restores production exactly ([qwen_fp8_windows_plan.md](/home/decross1/projects/a_bgt_rsi/docs/qwen_fp8_windows_plan.md:25)). Production runtime/pin changes are human-gated ([CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:190), [D-074](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3650)).  
    **Falsifier:** A matched A/B using the identical Qwen 3.8 weights, request bytes, chat template, parser, MTP/KV configuration, and scoring, differing only in runtime implementation/version.

## 2. WHAT THE DRAFT GETS WRONG ABOUT THE REPO

- **Qwen 3.8 is already production.** D-072’s heading still says production stays 3.6 because it records the qualification stage; D-074 subsequently executed the 3.8 cutover ([D-072](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3483), [D-074](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3650)). Any handoff must use the later decision.

- **Two artifacts still encode the old model.** [`tools/qwen_builder.sh`](/home/decross1/projects/a_bgt_rsi/tools/qwen_builder.sh:59) and its operator documentation default to `qwen3.6-27b-nvfp4-mtp`, while `:8001` serves `qwen3.8-27b-nvfp4-mtp`. [`bench/critic_eval/qwen_ab.py`](/home/decross1/projects/a_bgt_rsi/bench/critic_eval/qwen_ab.py:1) is a historical/skeleton A/B, not the current production evaluator. The draft cannot treat either as current without correction.

- **Wrapper defaults are not role policy.** `0.0/1.0` is only the fallback at the wrapper boundary. `hypothesize` is already `0.7/0.95`, and numerous other callers use `0.2–0.4`. Profiles must preserve explicit call-site behavior rather than overwrite it globally.

- **Candidate plurality already exists.** The current PI prompt produces 1–3 candidates and chooses one. The proposed `N=3` mechanism is not new; only an additional critic/selection pass would be new.

- **There is no generic local reasoning-effort interface.** Adding a name to a profile does not cause either local backend to honor it. Qwen reasoning is template/runtime-specific; frontier Codex effort is pinned separately in `frontier_cli.py`.

- **The fixed role assignment is inviolate absent a new decision.** Gemma is the sole PI/generator, Qwen is the independent skeptic, and frontier models are falsifiers ([CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:262)). Qwen-as-PI, frontier-as-upgrade-proposer, or automatic role rotation requires owner ratification.

- **The weekly frontier runway already exists.** It uses both vendors, a 180-second timeout, strict JSON extraction, append-only/idempotent proposal IDs, and `memory/frontier_agenda.jsonl` ([frontier_agenda.py](/home/decross1/projects/a_bgt_rsi/orchestrator/frontier_agenda.py:46)). Reuse `invoke_frontier`, its ledger, the ToS sentinel, and the existing cron gate ladder.

- **The supplied verified brief reports the cron as already installed at Sunday 05:30 UTC.** The shell script’s comments still say “not installed” and recommend Monday 08:00, so the comments—not a new scheduler—need reconciliation ([VERIFIED_REPO_BRIEF.md](</tmp/claude-1000/-home-decross1-projects-a-bgt-rsi/113bdba2-ffaa-4e3f-a1c0-e00c03260205/scratchpad/upgrade_loop/VERIFIED_REPO_BRIEF.md>), [weekly-frontier-agenda.sh](/home/decross1/projects/a_bgt_rsi/cron/weekly-frontier-agenda.sh:73)).

- **The apparatus-improvement delivery loop already exists.** D-066 defines telemetry collection, Gemma proposal, two frontier affirmations, at most three revisions, red-first acceptance, Tier-P packet emission, isolated Qwen worktree, dispatcher verdict, and premerge checks. A weekly analysis should hand an accepted experiment card into that path, not create another builder or promotion system.

- **D-066 is dark and has no autonomous dispatcher wiring.** The operator guide explicitly says no cron/coordinator/daemon path reaches `dispatch_packet` ([self_improvement_loop.md](/home/decross1/projects/a_bgt_rsi/docs/self_improvement_loop.md:189)). A weekly proposal may be recorded automatically; packet emission and dispatch may not be inferred from that.

- **Direct Codex repository delivery and autonomous runtime authority are different.** `AGENTS.md` authorizes a direct Codex management session to commit, push, and integrate ordinary repository work. It does not expand a Nara/cron/packet process beyond its bounded runtime contract ([AGENTS.md](/home/decross1/projects/a_bgt_rsi/AGENTS.md:1)).

- **The call ledger already records most requested inference data.** It contains model/version, resolved temperature/top-p/seed, full prompt and completion, token usage, latency, caller, parent, backend, run ID, max tokens, and retrieval provenance ([calls.jsonl.schema.json](/home/decross1/projects/a_bgt_rsi/schema/calls.jsonl.schema.json:8)). Profile labels should initially live in experiment artifacts; changing the canonical schema is a separate Tier-S decision.

- **The frontier ledger cannot support monetary-cost claims.** `run_state/frontier_calls.jsonl` contains no tokens or charge. The Claude path deliberately strips API credentials to avoid unintended metered use, but “API cost” must remain `unknown/null`, not fabricated as zero.

- **Rule 6 is independent of specialist ledgers.** Every executable step—including gate refusals, snapshotting, benchmark stages, fallbacks, and frontier calls—must append the minimum seven-field row to `run_state/week1.run.jsonl` ([CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:220)). A new benchmark ledger does not replace this.

- **Failure semantics already differ by purpose.** Weekly agenda synthesis is per-vendor fail-open; D-066 apparatus modification treats either veto or inconclusive as blocking ([frontier_agenda.py](/home/decross1/projects/a_bgt_rsi/orchestrator/frontier_agenda.py:130), [self_improvement_loop.md](/home/decross1/projects/a_bgt_rsi/docs/self_improvement_loop.md:205)). An upgrade proposal must use the latter semantics for advancement.

- **Bench infrastructure should be copied, not reinvented.** `bench/critic_cal`, `bench/redteam_cal`, `bench/fp8_ab`, and `bench/judge_cal` already establish frozen JSONL fixtures, manifest hashes, per-arm artifacts, exact thresholds, independent bars, sentinel-first execution, and honest caveats.

- **The current tool probe is already a useful ten-turn core.** It fixes request bytes across arms and records structured calls, parseability, HTTP status, and latency ([tool_probe.py](/home/decross1/projects/a_bgt_rsi/bench/fp8_ab/tool_probe.py:1)). Its scorer needs exact expected-name/argument comparison; it does not need immediate expansion to 100–200 cases. Turn `t06` is deliberately spec-invalid and must remain diagnostic rather than silently counted as a normal failure.

- **The current long-context ceilings are 32K and 16K.** Any 64K test implies a different serve configuration. The repo already specifies the required scratch-window and memory discipline; request-level profile code cannot unlock it.

- **Guided JSON is specifically unsafe on pinned Qwen.** The repo records the MTP + reasoning-parser + guided-output trap and says not to adopt guided output on that backend while pinned ([qwen38_role_setups.md](/home/decross1/projects/a_bgt_rsi/docs/qwen38_role_setups.md:85)). “Strict JSON output” belongs in prompt-plus-parser validation, not a new Qwen guided-decoding switch.

- **Every metric must remain independently pass/fail.** Composite utility scores may be reported, but they cannot rescue a failed correctness, memory, provenance, or calibration gate. Fallbacks must be named, logged, and capped; real model runs must use `env -u MOCK_LLM` ([CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:210), [CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:232), [CLAUDE.md](/home/decross1/projects/a_bgt_rsi/CLAUDE.md:246)).

- **Runtime, schema, cron, role, and production-policy changes are owner-gated.** D-066 can emit only Tier-P changes; it refuses `schema/`, `cron/`, run-state semantics, decisions, and the spine rather than escalating them ([D-066](/home/decross1/projects/a_bgt_rsi/DECISIONS.md:3260)).

## 3. COUNTER-PROPOSAL: WEEKLY LOOP

Build no second autonomous agent. Add one dark, read-only operational-review pass behind the existing frontier cron. Its only output is an inert, falsifiable experiment card.

**Flow**

`existing lock/ToS/pause gates → deterministic snapshot → Codex proposal → Claude attack → local schema validator/reducer → inert ledger → owner`

There is no frontier synthesis call, rebuttal loop, packet emission, code generation, runtime launch, or automatic promotion.

**Required owner decision before implementation**

D-061 must receive a narrow amendment permitting a frontier model to author **operational, nonresearch experiment cards**. The amendment should state that these cards:

- never contain scientific hypotheses;
- never enter `loop_memory`, the brain, or the idea ledger;
- never emit or dispatch a packet;
- never alter files or runtime state;
- remain inert until owner acceptance.

Without that amendment, retain Gemma as proposer and use Codex plus Claude only as D-061 falsifiers.

**Input snapshot**

Hash every source file. Send full text only for small policy/code files; send deterministic, capped projections of large logs. Never transmit raw `logs/calls.jsonl` prompts/completions or an unbounded daemon log.

Policy and design inputs:

- `CLAUDE.md`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `DECISIONS.md`, extracting D-061, D-066, D-072, D-074, and D-076 while retaining the whole-file hash
- `docs/self_improvement_loop.md`
- `docs/qwen38_role_setups.md`
- `docs/qwen_fp8_windows_plan.md`

Implementation state:

- `orchestrator/frontier_agenda.py`
- `orchestrator/self_improve.py`
- `agent_wrapper/frontier_cli.py`
- `agent_wrapper/wrapper.py`
- `schema/calls.jsonl.schema.json`
- `cron/weekly-frontier-agenda.sh`
- `cron/serve-models.sh`
- `tools/qwen_builder.sh`
- `scripts/bench_tokens_per_sec.py`

Frozen evaluation inputs:

- `bench/critic_cal/manifest.jsonl`
- `bench/critic_cal/manifest_meta.json`
- `bench/redteam_cal/fixtures.jsonl`
- `bench/redteam_cal/revised_prompt.txt`
- `bench/judge_cal/set_v2.jsonl`
- `bench/critic_eval/stage3a_driver.py`
- `bench/fp8_ab/tool_probe.py`

Dynamic inputs, projected through bounded readers:

- `run_state/week1.state.json`
- `run_state/week1.run.jsonl`
- `run_state/health_signals.jsonl`
- `run_state/loop_alert.json`
- `run_state/coordinator_cycles.jsonl`
- `run_state/frontier_calls.jsonl`
- `run_state/overrides.jsonl`
- `memory/promotion_near_misses.jsonl`
- `memory/frontier_agenda.jsonl`
- `logs/calls.jsonl`
- `logs/nara-daemon.log`

The snapshot should also record `HEAD`, dirty-state paths, production `/v1/models` responses, container image digests, full serve flags, and `/proc/meminfo`. Dynamic logs become seven-day aggregates by backend/caller/sampling/cap/error/empty/latency/tokens, using the bounded-reading conventions already present in `self_improve.gather_evidence()`.

**Roles**

- **Local snapshotter:** pure deterministic reads, hashing, aggregation, redaction, and schema validation.
- **Codex `upgrade_proposer`:** returns exactly one smallest operational experiment answering a named repo signal.
- **Claude `upgrade_adversary`:** receives the identical snapshot plus Codex’s immutable proposal and tries to kill it.
- **Local reducer:** no LLM. It rejects malformed output, snapshot-hash mismatch, missing repo evidence, unbounded experiments, non-Tier-P scope, and any adversarial `kill` or `revise` verdict.

**Proposer output schema**

Strict JSON, `additionalProperties: false`:

```json
{
  "schema_version": "weekly-upgrade-v1",
  "week_id": "YYYY-Www",
  "snapshot_sha256": "sha256",
  "proposal_id": "wu-sha256prefix",
  "title": "string",
  "claim": "single falsifiable operational claim",
  "repo_evidence": [
    {
      "path": "repo-relative path",
      "locator": "line, field, or fixture id",
      "sha256": "sha256"
    }
  ],
  "external_claims": [
    {
      "claim": "string",
      "url": "string or null",
      "status": "SOURCE_VERIFIED or UNVERIFIED"
    }
  ],
  "change_surface": ["repo-relative path"],
  "tier": "P or S or unknown",
  "baseline": {
    "artifact": "repo-relative path",
    "metric": "string",
    "value": "number, string, or null"
  },
  "candidate": {
    "single_delta": "exactly one changed factor"
  },
  "experiment": {
    "fixture_ids": ["string"],
    "arms": ["baseline", "candidate"],
    "seeds": [0],
    "max_gpu_minutes": 0,
    "primary_metric": "string",
    "guardrails": ["independent pass/fail condition"],
    "pass_rule": "exact boolean rule"
  },
  "falsifier": "observation that kills the claim",
  "abort_conditions": ["string"],
  "owner_gate_required": true
}
```

Any model-originated external assertion without a source already present in the snapshot must carry `status: "UNVERIFIED"` and cannot be load-bearing.

**Adversary output schema**

Strict JSON, `additionalProperties: false`:

```json
{
  "schema_version": "weekly-upgrade-review-v1",
  "week_id": "YYYY-Www",
  "snapshot_sha256": "sha256",
  "proposal_id": "string",
  "verdict": "kill, revise, or survives_to_owner_review",
  "violated_rules": ["file and locator"],
  "objections": [
    {
      "claim": "specific defect",
      "repo_evidence": ["file and locator"],
      "falsifier": "evidence that would defeat this objection"
    }
  ],
  "cheapest_decisive_test": "string",
  "residual_risks": ["string"],
  "external_claims": [
    {
      "claim": "string",
      "url": "string or null",
      "status": "SOURCE_VERIFIED or UNVERIFIED"
    }
  ]
}
```

**Artifacts and ledger**

- Snapshot: `bench/weekly_upgrade/snapshots/<ISO-week>.json`
- Append-only review ledger: `bench/weekly_upgrade/ledger.jsonl`
- Frontier invocation ledger: existing `run_state/frontier_calls.jsonl`
- Mandatory execution audit: existing `run_state/week1.run.jsonl`

Ledger events should be `snapshot_created`, `proposal_received`, `adversary_reviewed`, `rejected`, `survives_to_owner_review`, `owner_accepted`, and `experiment_result`. Only the first five may be written by the weekly job. Store exact validated vendor outputs, snapshot hash, prompt hashes, vendor/CLI versions, and the deterministic disposition.

**Cron and kill switch**

Retain the verified installed line; do not add a second scheduler:

```cron
30 5 * * 0 /home/decross1/projects/a_bgt_rsi/cron/weekly-frontier-agenda.sh
```

After owner ratification, the existing script can invoke the operational review after its current agenda pass. This edit is Tier S because it touches `cron/`; it must not be hidden inside Session A or B.

Kill mechanisms:

- Feature remains dark unless `NARA_WEEKLY_UPGRADE=1`.
- `touch run_state/pause_frontier` halts both agenda and upgrade review.
- Only the owner removes the pause file.
- Removing `run_state/frontier_tos_ratified` darkens all real frontier calls.
- Preserve the existing single-instance `flock`.
- No automatic retries; a missing/failed proposer or adversary yields `inconclusive` and no advancing proposal.

**Automatic versus gated**

May run automatically after one explicit ratification:

- bounded reads, hashing, aggregation, and redaction;
- two frontier calls;
- strict parsing and deterministic reduction;
- inert ledger and Rule-6 rows;
- fixed, read-only weekly canaries against current endpoints, provided their exact ≤115-minute budget and thresholds are separately ratified.

Owner-gated:

- accepting an experiment card;
- emitting or dispatching a D-066 packet;
- changing call sites, profiles, schemas, prompts, roles, pins, cron semantics, or benchmark thresholds;
- downloading a model/runtime/dataset;
- stopping or replacing either production resident;
- launching a challenger runtime;
- interpreting benchmark output as a scientific result;
- promoting any candidate.

**Frontier call count and cost**

- New operational review: at most **2 calls/week**—one Codex proposal and one Claude adversarial review.
- Existing agenda: at most **2 calls/week**.
- Combined normal cap: **4 frontier calls/week**, with no retry loop and a 180-second per-call timeout.
- Monetary cost: **UNKNOWN**. The intended routes use subscriptions and the Claude seam strips metered API credentials, but `frontier_calls.jsonl` contains neither token usage nor billing. The ledger must record `cost_usd: null`, not claim zero.

## 4. COUNTER-PROPOSAL: BENCHMARKS

Run the current endpoints weekly. Candidate inference or runtime arms enter only through an owner-approved experiment. Preserve every signal independently; no composite score may rescue a failed gate.

| Function | Smallest frozen set | Measurements | Hard pass/fail rule | Elapsed cap |
|---|---|---|---|---:|
| Tool/transport | Existing ten-turn [`tool_probe.py`](/home/decross1/projects/a_bgt_rsi/bench/fp8_ab/tool_probe.py:82), once on Gemma and once on Qwen. Treat deliberately invalid `t06` as diagnostic; score the nine spec-valid turns. | HTTP completion, structured shape, parseability, exact tool name and arguments, replay survival, latency. | All nine valid requests return HTTP 200 and parse; ≥8/9 exact calls; zero malformed valid replays; candidate has no per-fixture regression versus same-run incumbent. | 15 min |
| Coding-builder | Two disposable fixtures: CB01 freezes `PKT-EXAMPLE`’s edit task; CB02 is a sanitized, self-contained generation task derived from the `research_progress` contract. Run current and candidate with explicit `QWEN_MODEL=qwen3.8-27b-nvfp4-mtp`. | Test result, out-of-scope writes, diff size, attempts, output tokens, wall-to-correct. | Both tasks pass their frozen tests; zero scope violations; no collection error; candidate solves at least as many and does not increase paired wall-to-correct by >10%. | 30 min |
| Skeptic/critic | Qwen’s six existing sentinels: `novel_on_01_quant_lockin`, `redisc_on_01_tft_reciprocity`, `canary_on_01_ultimatum_plain`, `falsifiable_01_finite_pd_cooperate`, `falsifiable_02_dominant_tft`, `camo_off_04_raft_punishment`; plus Gemma’s 24 frozen red-team fixtures. | Parse/liveness, empties, caps, verdict anchors; D-076 calibration bars. | Qwen 6/6 completes with correct pinned anchors and no empty-at-cap. Gemma: unscored ≤2, fatal on parsed bad ≥75%, fatal on parsed good ≤35%. Each bar stands alone. | 20 min |
| Hypothesis/PI | Twelve fixed known-good/known-bad claim pairs derived from `bench/redteam_cal/fixtures.jsonl`, plus four fixed generation topics with structural answer contracts. | Correct pair choice; schema validity; presence of intervention/condition, comparator, outcome, predicted direction; invented-source identifiers. | ≥10/12 pair choices; 4/4 parseable generation records; every generated claim meets all four structural fields; zero invented source IDs. Novelty remains human-scored and cannot auto-promote. | 15 min |
| Long-context synthesis | Four frozen packs in the new manifest: two approximately 8K and two approximately 14K tokens, built from `CLAUDE.md`, the five decisions, `self_improvement_loop.md`, and `qwen38_role_setups.md`; run both models. | Atomic fact recall, contradiction detection, file/decision attribution, unsupported assertions, latency. | All deliberately planted contradictions found; ≥95% answer-key facts; zero unsupported citations; all eight calls complete. No weekly 32K/64K lane. | 20 min |
| Runtime throughput | Existing streaming [`bench_tokens_per_sec.py`](/home/decross1/projects/a_bgt_rsi/scripts/bench_tokens_per_sec.py:1): one warmup plus five 256-token prompts/model; separate `max_tokens=1` prefill probes at 4K/8K/14K. | Median decode tok/s, TTFT, end-to-end tok/s, actual prompt tokens, server-metric cross-check, errors, memory floor. | Health: every request completes and `MemAvailable ≥30 GiB`. Challenger promotion: no correctness regression, ≥10% paired wall-to-correct or decode improvement, TTFT regression ≤10%, and all memory/provenance gates pass. | 10 min |

The stage caps total 110 minutes. A global 115-minute hard stop applies; hitting it produces `inconclusive` or `failed`, never silent fixture deletion. Promotion requires either three repeated paired runs or three clean weekly observations; one noisy week is only a health observation.

**Named external benchmarks**

- **ScienceAgentBench:** Its official repository describes 102 tasks derived from 44 papers, environment setup, and separately obtained evaluation artifacts. A one- or two-task smoke may be worth qualifying, but full weekly agent execution is not the minimal gate. Current-box dependency/runtime compatibility is **UNVERIFIED** until measured. [Official ScienceAgentBench repository](https://github.com/OSU-NLP-Group/ScienceAgentBench)

- **CORE-Bench:** The original suite has heavyweight reproducibility capsules and Docker-oriented execution; the maintained v1.1 benchmark is smaller but still a substantial agent-environment exercise. One preselected task could be a monthly qualification after an adapter exists; it should not be a first-week gate. Current-box container compatibility is **UNVERIFIED**. [Official CORE-Bench repository](https://github.com/siegelz/core-bench), [CORE-Bench v1.1 paper](https://arxiv.org/abs/2606.26158), [official evaluation collection](https://huggingface.co/collections/agent-evals/core-bench-v11)

- **ResearchBench:** Its official implementation includes a 12-sample tiny split and separates retrieval, hypothesis generation, and ranking. That makes the tiny split the most plausible external shadow benchmark, but generation scoring depends on a judge model; it cannot be promotion authority. Runtime under two hours on this box is **UNVERIFIED** until one measured pilot. [Official ResearchBench repository](https://github.com/ankitala/ResearchBench)

- **PaperBench:** The benchmark covers 20 paper-reproduction tasks and uses separate agent, reproduction, GPU, and grading environments. The official report budgets roughly 12 hours per paper, so it is categorically not a weekly two-hour suite; at most it is an occasional owner-approved campaign. [Official PaperBench repository](https://github.com/benchflow-ai/paperbench/blob/main/project/paperbench/README.md), [OpenAI PaperBench report](https://cdn.openai.com/papers/22265bac-3191-44e5-b057-7aaacd8e90cd/paperbench.pdf)

Therefore, **no named external benchmark belongs in the initial weekly promotion gate**. ResearchBench-tiny is the first shadow candidate; ScienceAgentBench gets a one-task qualification second. CORE and PaperBench remain occasional campaigns.

## 5. DISAGREEMENTS TO RESOLVE BY EXPERIMENT

1. `{claim: "Temperature-zero defaults are suppressing creativity", position: "False as a repo-wide diagnosis; the PI already runs at 0.7/0.95", cheapest local experiment: "Run 12 frozen PI topics at current 0.7/0.95 versus 0.0/1.0 with equal tokens; blind-score structural validity and downstream survival."}`

2. `{claim: "Named profiles will improve results", position: "Profiles may improve configuration hygiene, but no quality gain follows from naming parameters", cheapest local experiment: "First compare explicit parameters with profile-resolved parameters byte-for-byte in mocks; then run only a winning candidate profile against its unchanged explicit baseline."}`

3. `{claim: "Qwen reasoning effort should be low or medium", position: "Plausible but locally unproven and backend-specific", cheapest local experiment: "Run the six Qwen sentinels under xhigh/default, medium, and low with identical serve/request settings; compare empties, verdict anchors, tokens, and wall time."}`

4. `{claim: "Three candidates plus a critic beats one candidate", position: "Unsupported and likely expensive", cheapest local experiment: "Use 12 topics and equal total token/wall budgets; compare one long proposal against three short proposals plus selection using blinded downstream task success."}`

5. `{claim: "A warmer critic is more effective", position: "Calibration, not diversity, determines critic value", cheapest local experiment: "Run the 24 red-team fixtures at current sampling and one warmer arm; apply the existing D-076 bars unchanged."}`

6. `{claim: "64K context materially improves weekly synthesis", position: "Not established and impossible on current production Qwen", cheapest local experiment: "First compare 8K versus 14K full-context and retrieved/compacted variants on the four exact-answer packs; open a scratch 32K/64K window only if 14K loses required evidence."}`

7. `{claim: "Another serving runtime will improve the apparatus", position: "Only meaningful as a one-variable, same-weights A/B", cheapest local experiment: "Serve the current Qwen weights on :8002 with an immutable challenger image and matched flags; run smoke, tool probe, six sentinels, and throughput before any full battery."}`

8. `{claim: "MTP is always a throughput win", position: "Decode gain is insufficient if TTFT, correctness, or tool behavior regresses", cheapest local experiment: "Same runtime and weights, MTP on versus off, five streaming prompts plus the tool probe and six sentinels; compare wall-to-correct and independent correctness gates."}`

9. `{claim: "A frontier proposer/adversary rubber band produces better upgrade choices", position: "Unproven and currently outside D-061", cheapest local experiment: "For eight weeks, log inert frontier cards beside telemetry-derived Gemma cards; preregister outcomes and compare owner acceptance plus completed-experiment yield without auto-executing either."}`

10. `{claim: "CTT, SUH, and RSR are useful promotion metrics", position: "Reject until they preserve the underlying task vector and have fixed denominators", cheapest local experiment: "Compute them retrospectively on frozen historical artifacts, compare their rankings with raw correctness/latency/memory gates, and reject any metric that reverses a hard-gate failure."}`

11. `{claim: "External benchmark scores will predict this apparatus's quality", position: "UNVERIFIED; domain and harness transfer are unmeasured", cheapest local experiment: "Run ResearchBench-tiny as shadow-only and correlate its task-level outcomes with the private six-function panel before granting it any gate weight."}`

## 6. SESSION SCOPE

The inspected checkout was dirty and ahead of its remote. Both coding sessions should use separate worktrees from an explicitly recorded base commit and stage only their assigned paths.

**Session A — inference profiles and evaluation harness**

The dark harness can be coded without changing scientific policy. Production call-site activation and canonical logging changes cannot.

File order and write scope:

1. `experiments/PREREG_inference_policy_v1.md`  
   Freeze hypotheses, arms, fixtures, seeds, per-signal thresholds, 115-minute cap, and the rule that no role default changes during evaluation.

2. `bench/inference_policy/__init__.py`

3. `bench/inference_policy/manifest.jsonl`  
   Hold tool references, six critic sentinels, 12 PI pairs, four generation prompts, four context packs, expected atomic answers, hashes, and budgets.

4. `bench/inference_policy/fixtures/edit_before.py`

5. `bench/inference_policy/fixtures/edit_test.py`

6. `bench/inference_policy/fixtures/generate_spec.md`

7. `bench/inference_policy/fixtures/generate_test.py`

8. `tests/test_inference_policy_driver.py`  
   Write the red tests before the driver: manifest integrity, MOCK refusal, timeout behavior, per-signal scoring, cap enforcement, and artifact provenance.

9. `bench/inference_policy/score.py`  
   Pure scoring only; approximately 100 lines. No model calls and no composite promotion score.

10. `bench/inference_policy/driver.py`  
    Approximately 100–140 lines by delegating tool work to `bench.fp8_ab.tool_probe`, throughput to `scripts/bench_tokens_per_sec.py`, and critic work to existing drivers.

11. `tests/test_wrapper_profiles.py`  
    Pin byte-identical current defaults, explicit-parameter precedence, invalid-profile refusal, and sync/async/tool parity.

12. [`agent_wrapper/wrapper.py`](/home/decross1/projects/a_bgt_rsi/agent_wrapper/wrapper.py:178)  
    Net addition target: **≤45 lines**. Add one small sampling-profile map and resolver plus optional `profile=` on `call_sync`, `call_async`, and `call_with_tools`. Profiles should contain only resolved sampling values:
    - `deterministic`: `temperature=0.0`, `top_p=1.0`
    - `moderate`: `temperature=0.2`, `top_p=0.95`
    - `exploratory`: `temperature=0.7`, `top_p=0.95`

    Explicit arguments override a profile; no profile preserves current defaults exactly. Do not add a policy class, registry service, automatic role mapping, reasoning effort, or token caps to profiles.

13. `tests/test_qwen_builder_defaults.py`

14. [`tools/qwen_builder.sh`](/home/decross1/projects/a_bgt_rsi/tools/qwen_builder.sh:59) and [`docs/self_improvement_loop.md`](/home/decross1/projects/a_bgt_rsi/docs/self_improvement_loop.md:132)  
    Correct the stale default model name to the already-ratified production Qwen 3.8 name. The harness must still pass endpoint/model explicitly.

15. `docs/inference_profiles.md`  
    Document profiles as optional experimental resolution, not new role policy.

16. Generated results only under `bench/inference_policy/runs/`.

Do not edit in Session A:

- `schema/calls.jsonl.schema.json`
- production worker call sites
- `cron/serve-models.sh`
- `orchestrator/frontier_agenda.py`
- `run_state/`
- role assignments or decision entries

`reasoning_effort` remains an experimental request/serve arm until the live Qwen probe determines exact semantics. If the owner later requires the profile name or reasoning effort in every canonical call record, that is a separate Tier-S schema migration with a historical-row validation plan.

**Session B — challenger runtime**

Before writing runtime-specific launch code, the owner must select one challenger runtime/version, immutable image digest, exact Qwen weight compatibility, allowed acquisition, and window constraints. Do not build a generic multi-runtime abstraction or use a moving tag.

File order and write scope:

1. `experiments/PREREG_runtime_challenger_v1.md`  
   Freeze the single changed factor, current/challenger digests, identical weight revision, serve flags, sentinels, stop conditions, restoration procedure, and promotion rule.

2. `bench/runtime_ab/__init__.py`

3. `bench/runtime_ab/manifest.json`  
   Exact image digests, weight revision/hash, tokenizer/template hashes, ports, parser, MTP, KV type, memory target, request parameters, fixture hashes, and expected production restoration state. Missing values must fail validation; no placeholders at execution.

4. `tests/test_runtime_ab_manifest.py`

5. `bench/runtime_ab/score.py`  
   Pure independent gates: provenance, liveness, correctness, tool behavior, memory, TTFT, decode, and wall-to-correct.

6. `tests/test_runtime_ab_score.py`

7. `bench/runtime_ab/driver.py`  
   Approximately 100 lines. Orchestrate only: production baseline `:8001`, challenger `:8002`, smoke, tool probe, six sentinels, throughput, artifact write, Rule-6 status. Reuse existing drivers rather than copy their prompts or parsers.

8. `tests/test_runtime_ab_driver.py`  
   Pin sentinel-first behavior, stop-on-provenance/memory/error, no full battery after sentinel failure, MOCK refusal, and guaranteed restoration reporting.

9. `bench/runtime_ab/serve_scratch.sh`  
   Under approximately 100 lines; exactly one challenger. Require explicit `--execute`, `run_state/pause_coordinator` present, passing memory preflight, container name `vllm-runtime-ab`, and port `8002`. Record the immutable digest and complete flags. It must not silently stop a resident or modify production launch files.

10. `docs/runbooks/runtime_challenger.md`  
    Follow the existing window order: pause, preflight, launch scratch, verify model/digest, sentinels, remaining tests, stop scratch, restore via canonical launcher, verify Gemma MARLIN/Qwen identity, postflight, then owner removes pause.

11. Generated results only under `bench/runtime_ab/runs/`.

Reuse without editing:

- [`bench/fp8_ab/tool_probe.py`](/home/decross1/projects/a_bgt_rsi/bench/fp8_ab/tool_probe.py:1)
- [`bench/critic_eval/stage3a_driver.py`](/home/decross1/projects/a_bgt_rsi/bench/critic_eval/stage3a_driver.py:1)
- [`scripts/bench_tokens_per_sec.py`](/home/decross1/projects/a_bgt_rsi/scripts/bench_tokens_per_sec.py:1)
- `experiments/exp008_qat_eval/preflight_mem.sh`
- [`cron/serve-models.sh`](/home/decross1/projects/a_bgt_rsi/cron/serve-models.sh:1)

Do not edit in Session B:

- `cron/serve-models.sh`
- `agent_wrapper/wrapper.py`
- `schema/`
- production model names, roles, pins, or call sites
- `bench/critic_eval/qwen_ab.py`; it is historical, not the new runtime harness

Owner decisions required before code or execution:

- **Before weekly-loop code:** narrow D-061 operational-proposer exception; approval to edit `orchestrator/` and `cron/`; fixed automatic benchmark budget.
- **Before Session A production activation:** winning profiles, affected call sites, and whether canonical call-schema expansion is justified.
- **Before runtime-specific Session B code:** exact challenger runtime and immutable digest. An endpoint-agnostic scorer may be built earlier, but not a speculative launcher.
- **Before Session B live execution:** permission for image acquisition, container churn, any resident shutdown, the scratch window, and the 30-GiB memory plan.
- **Before promotion:** a new `DECISIONS.md` entry covering runtime/pin or inference-policy adoption. Evaluation success alone never authorizes cutover.
- **Before external-suite installation:** dataset/artifact acquisition, credentials or licenses, storage budget, and measured box compatibility.