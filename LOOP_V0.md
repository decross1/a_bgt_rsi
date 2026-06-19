# LOOP_V0 — literature-only loop slice

> **Status: chain wired end-to-end; reference-passing refactor pending
> before reliable runs.** Replaces the retired `plan.yaml` (archived
> under [`archive/plan/`](archive/plan/)). Reflects the 2026-05-26
> direction change (see [`DECISIONS.md`](DECISIONS.md) D-030); Path-B
> sub-agent migration in progress (D-034).

## Current state (2026-06-18)

State spans four workstreams; this file's later sections carry the
lit-pipe detail.

- **Lit-pipe (the LOOP_V0 chain).** Chain wired end-to-end; the D-045
  robustness battery, D-050 residual skeptics, D-052 (topicality
  skeptic retired as a gate, kept as a dark non-gating advisory), and
  D-053 (both over-gating layers — the primary R0 topicality gate AND
  the adversarial promotion vote — demoted to non-gating advisories,
  env-gated dark; pre-registered cargo experiment to fill the empty
  `/todo` cockpit — see
  [`docs/overgating_promotion_analysis.md`](docs/overgating_promotion_analysis.md))
  have landed. **The reference-passing refactor SHIPPED (`39ba954`) and is
  verified live** — 3 real iterations on 2026-06-19
  (`iter-2026-06-19-001/002/003`) ran complete 5-step chains with no
  truncation. The 3-iteration exit criterion is materially met (pending the
  owner reading journals 076/077/078). Loops 1 (falsification) + 2
  (rediscovery) demonstrated; 019-003 is a novel surviving Loop-3 seed. The
  4-session roadmap to the full loop + applied tier:
  [`docs/roadmap_full_loop.md`](docs/roadmap_full_loop.md).
- **UI.** The 2026-06-10 observability overhaul shipped; the 2026-06-14
  dashboard reframe + `/todo` cockpit (stubbed) merged. **2026-06-17/18 (pushed,
  `b8ca85f`): the verdict-fenced tutor is live** — orchestrator tutor engine +
  per-turn `chat` CLI seam + `calibration_cli` writer (D-054/D-055), and the UI
  session's **U1** (tutor finding-overview + read-only `finding_detail` GET) +
  **U5** (kind-gated forms) landed. The authoritative wiring spec is
  [`docs/cockpit_seam_wiring.md`](docs/cockpit_seam_wiring.md). **Remaining: U2/U3/U4**
  (tutor chat pane, two-voice pane, cockpit seam execs) — work order in
  [`human/sessions/2026-06-18.md`](human/sessions/2026-06-18.md) §"UI session work
  order".
- **Autonomy.** D-049 (coordinator v2 + β bounds) is a **draft awaiting
  ratification**. The daily cadence is
  [`docs/daily_workstreams.md`](docs/daily_workstreams.md).
- **Applied.** Polymarket paper-strategy chain is closed (design-only,
  CFTC guardrail stands); pre-resolution snapshots are the next step.

## Why this exists

The diagrams in [`docs/diagrams/`](docs/diagrams/) describe an
eight-step intelligence loop. Eight days of work have produced the
substrate — wrapper, sequential orchestrator, two workers, arXiv
ingest, Chroma vector store, observability UI, one end-to-end repeated-PD
experiment — but the loop itself has never run as a chained iteration.
The hardest step (novelty evaluation) and the loop-memory layer have
no code.

LOOP_V0 is the smallest slice of the diagrams that closes the
cognitive half of the loop end-to-end. It deliberately skips the
sandbox tiers (synthetic / semi-synthetic / applied), which is the
next slice.

## What LOOP_V0 does

The loop, single-shot, human-triggered:

```
seed → hypothesize → retrieve → novelty-classify → critique → journal
                                                      ↑
                                       (literature only — no experiment)
                                                      ↓
                                              loop_memory.jsonl
```

A single iteration:

1. **Seed.** The human types a topic string at the start of the
   iteration. (Auto-seeding from latest arXiv ingest is a v0.5
   add-on, not v0.)
2. **Hypothesize.** A `hypothesize` worker generates 1–3 candidate
   hypotheses from the topic, conditioned on top-K nearest neighbors
   already in the knowledge base.
3. **Retrieve.** A `retrieve_literature` worker pulls top-K (K=10)
   most-similar prior results from Chroma — both foundational (Layer 1)
   and live-arXiv (Layer 2). Returns `[{doc_id, content_hash, chunk}]`
   for each.
4. **Classify novelty.** A `novelty_classify` worker, given the
   hypothesis + retrieved neighbors, returns a 4-way classification:
   `novel / rediscovery / nonsense / unclear`, with a nearest-neighbor
   trace.
5. **Critique (literature-only).** A `critic` worker, given the
   hypothesis + retrieved neighbors, attempts to falsify the
   hypothesis using only the retrieved literature: which paper most
   strongly contradicts? what known result does this restate? is the
   hypothesis well-formed? Returns a verdict: `survives / falsified /
   restated / malformed`.
6. **Journal.** A `journal_writer` worker emits one structured JSONL
   row to `memory/loop_memory.jsonl` AND one markdown entry under
   `journal/iterations/NNN.md`. The row is the minimal Layer-3 entry.

Step 8 of the diagram (human evaluation) is **out of scope for LOOP_V0**.
The journal entry is the artifact a human can read; in LOOP_V0 the
human simply reads it and decides whether the next iteration changes
direction. A formal Step-8 gate with feedback into loop memory is the
next slice.

## Files to create

| Path | What | Approx LOC |
| --- | --- | --- |
| `schema/iteration_record.schema.json` | JSON Schema for a single loop_memory.jsonl row | n/a |
| `workers/hypothesize.py` | Step 2 worker | ~120 |
| `workers/retrieve_literature.py` | Step 3 worker (Chroma query wrapper) | ~80 |
| `workers/novelty_classify.py` | Step 4 worker (4-way classifier) | ~140 |
| `workers/critic.py` | Step 5 worker (literature-only critic) | ~120 |
| `workers/journal_writer.py` | Step 6 worker (JSONL row + markdown entry) | ~100 |
| `orchestrator/loop_v0_driver.py` | Chains steps 1–6, logs run, writes record | ~150 |
| `memory/loop_memory.jsonl` | Append-only Layer-3 seed | 0 (starts empty) |
| `journal/iterations/` | Markdown entries, one per iteration | n/a |

Files to **reuse, not modify**: `agent_wrapper/wrapper.py`,
`orchestrator/openclaw_runner.py`, `pipeline/embed_and_store.py`,
existing Chroma collections.

## iteration_record schema (sketch)

```json
{
  "iteration_id": "iter-2026-05-27-001",
  "started_at": "2026-05-27T14:00:00Z",
  "ended_at":   "2026-05-27T14:03:42Z",
  "seed": {
    "topic": "<human-typed topic string>",
    "source": "human"
  },
  "hypothesis": {
    "text": "...",
    "candidates_considered": 3
  },
  "retrieval": {
    "k": 10,
    "neighbors": [
      {"doc_id": "...", "content_hash": "...", "score": 0.83, "title": "..."}
    ]
  },
  "novelty": {
    "class": "novel | rediscovery | nonsense | unclear",
    "rationale": "...",
    "top_neighbor_id": "..."
  },
  "critique": {
    "verdict": "survives | falsified | restated | malformed",
    "rationale": "...",
    "contradicting_paper_id": null
  },
  "journal_entry_path": "journal/iterations/001.md",
  "model_version": "gemma-4-26b-a4b-nvfp4",
  "wrapper_call_ids": ["...", "..."]
}
```

The schema is normative. `journal_writer` validates against it before
appending.

## Build order (sessions, not days)

Each session writes one component end-to-end with a tiny integration
test. The human decides session-by-session whether to keep going.

| Session | Build | Status | Verification |
| --- | --- | --- | --- |
| Part 1 | Runtime + tool registry + Nara hello-world + Chroma helper + schemas + UI substrate | **done** (2026-05-26) | hello-world Nara ran end-to-end via UI; one tool dispatch + journal stub |
| Part 2 | `workers/{retrieve_literature,hypothesize,novelty_classify,critic_loop_v0,journal_writer}.py` + `NARA_PROMPT_V0` full chain | **done** (2026-05-26) | iter-2026-05-26-008 ran the full 5-step chain on a real game-theory topic, novel-survives verdict, ~120s |
| Path B | SubAgent primitive + `critic_loop_v0` migrated to sub-agent dispatch + Gemma-tool-call fallback parser + chain re-prompt | **started** (2026-05-26) | unit tests passing; critic runs via SubAgent on PyRuntime; runtime swap-point preserved |
| Reference-passing | Workers fetch heavy payloads (neighbors, hypothesis text) by `iteration_id` from per-iteration cache rather than receive them in tool_call args | **next session** | iterations no longer truncate at 1024 tokens; full chain runs without parser truncation |
| Three real iterations | 3 real iterations on real topics; human reads and reacts | after reference-passing | Three records on disk; human says they're useful or what's wrong |
| Call-stack UI | Active iteration panel surfaces the parent→child call chain ("Nara → critic_loop_v0 sub-agent on hypothesis X") | UI session | Human can read the live UI and see which agent is acting on whose prompt |

There is no auto-progression. Each session ends with a human-reviewed
artifact and a working-note update at `human/sessions/YYYY-MM-DD.md`.

## What LOOP_V0 deliberately does NOT do

- **No continuous loop.** Each iteration is human-triggered.
- **No sandbox / experiment tiers.** No game runs, no training, no
  cross-tier replication. Step 5 of the v5 diagram is omitted entirely.
- **No meta-review synthesis** (v5 Phase-2 addition between steps 1
  and 2). Loop memory is written but not actively synthesized.
- **No automated Step-8 gate.** The human reads the journal entry and
  decides; nothing is auto-published.
- **No second-model scoring.** Single model (Gemma 4); a future slice
  separates generator from scorer once a second model lands.
- **No separately-launched Claude Code sessions as workers.** Workers
  are Python functions dispatched by Nara. The Path-B "sub-agent"
  primitive (see §"Path B — selective sub-agent migration" below) is
  a *bounded multi-turn LLM conversation* within the same process —
  not a forked Claude Code worktree. The runtime interface is what
  keeps a future Claude-Code-per-worker swap mechanical.

## What's needed from the UI session

The UI extension that runs in parallel (see
[`agent/prompts/ui_session.md`](agent/prompts/ui_session.md)) must
make a LOOP_V0 iteration visible while it runs and after it finishes:

- **Active panel.** Which iteration is running. Which step is current.
  Which worker is in flight. Live elapsed time per step.
- **Resolved panel.** List of past iterations: id, topic, novelty
  class, critique verdict, link to journal entry.
- **Live journal scroll.** Most-recent journal entries, newest first,
  with topic and verdict visible.
- **Source of truth.** `memory/loop_memory.jsonl` (append-only) for
  history; an in-process event stream (file-watched is fine) for the
  live state.

The UI session does not need to land before LOOP_V0 ships, but they
should ship close together. The dashboard is the only reliable way
the human will see what the loop is actually doing.

## Exit criterion

LOOP_V0 is done when:

1. A human can type a topic, run the driver, and get a journal entry
   plus a `loop_memory.jsonl` row within ~5 minutes.
2. Three real iterations have been run on three different topics and
   the human has read all three entries.
3. The UI shows active and resolved iterations correctly.
4. At least one of the three iterations was useful enough that the
   human wants to keep going.

If #4 is no, we redesign. If #1–#3 work but #4 is no, that itself is
a finding and goes in `DECISIONS.md`.

## Path B — selective sub-agent migration

The LOOP_V0 chain ships as one-shot Nara tool_calls (Path A). Some
steps benefit from bounded multi-turn reasoning with isolated context
— **selectively, not wholesale**. Path B is the mechanism for that
migration. See [`DECISIONS.md`](DECISIONS.md) D-034 for the rationale.

**The SubAgent primitive (`orchestrator/subagent.py`):**

`run_subagent(name, system_prompt, user_prompt, expected_output_schema,
tools, tool_dispatch, budget, parent_request_id) → SubAgentResult`

- Bounded multi-turn LLM conversation with isolated context window.
- Hard caps: turns, wall-seconds, tokens. Default 6 turns / 90s.
- Optional tool dispatch (sub-agent can call `query_chroma`, etc.).
- Output validated against `expected_output_schema` before return.
- Same `parent_request_id` chain so all wrapper calls stay
  observable under one iteration.
- Runtime-agnostic: today `PyRuntime` dispatches the LLM call. (β is a
  host-tool-plane PORT — `orchestrator/tool_plane.py` + an in-sandbox OpenClaw
  bundle — NOT a mechanical `NemoClawRuntime` swap; that framing was falsified
  2026-06-09, see DECISIONS D-031 amendment. `PyRuntime` stays the host default.)

**Migration rule (per-worker, not chain-wide):**

A worker stays on Path A unless multi-turn reasoning is justified by a
concrete failure mode on real iterations. The worker's contract
(input/output schema, return shape Nara consumes) is **identical**
across paths, so the caller doesn't change. Currently migrated:

- `workers/critic_loop_v0` (Path B). Budget 6 turns / 90s, optional
  `query_chroma` tool. Adds observability fields:
  `subagent_turns_used`, `subagent_wall_seconds`, `subagent_status`.

Still Path A: `hypothesize`, `retrieve_literature`, `novelty_classify`,
`journal_writer`.

**Future Nara → sub-agent fan-out.** Path B is the foundation for the
fan-in/fan-out architecture where Nara dispatches multiple sub-agents
in parallel (e.g., three critics from different angles) and merges
their results. Not built today; the primitive is what unblocks it.

## Reference-passing — the next architectural fix

> **Status: SHIPPED + verified 2026-06-19.** The refactor landed (`39ba954`);
> `workers/journal_writer.py` gathers all four substructures from the
> per-iteration cache (`run_state/iteration_cache/<id>/`); verified live by 3
> complete real iterations (`iter-2026-06-19-001/002/003`, no truncation). The
> text below is the original plan, kept for the record.

**Symptom.** Even with the Gemma inline-tool-call fallback parser
(`agent_wrapper/gemma_tool_parse.py`, 20 unit tests), some chain
steps truncate at the `max_tokens=1024` cap because Nara copies the
full `neighbors` array (chunk_text payloads) through every downstream
tool_call's args.

**Root cause.** Nara's current contract is "pass captured payloads
verbatim into the next tool_call." That works for cheap fields
(`hypothesis_text`, scalar metadata) but is fundamentally wrong for
heavy payloads (`neighbors` with chunk_text), because:

1. Long-context tool_call emissions cross the 1024-token cap.
2. Even without truncation, Gemma's inline-markup format makes long
   strings parser-fragile.
3. Heavy payloads in args are duplicate state — Nara already has them
   in conversation memory.

**Fix.** Workers fetch heavy payloads by `iteration_id` from a
per-iteration cache rather than receive them in args:

- `run_state/iteration_cache/<iteration_id>/` holds captured artifacts
  (neighbors.json, hypothesis.json, novelty.json).
- Tool schemas downstream of `retrieve_literature` accept
  `iteration_id` as a required field instead of `neighbors`. Workers
  load from cache.
- Nara's prompt is rewritten: "do not re-emit captured payloads; pass
  iteration_id and the new fields each step computes."
- `journal_writer` gathers everything from cache at the end.

**Impact.** Tool_call emissions stay short (well under 1024 tokens),
parser stochasticity stops mattering at scale, and the chain becomes
deterministic at the substrate level. This is the load-bearing
prerequisite for the three real iterations.

**Next-session plan.**

1. Reference-passing refactor (cache + worker signatures + Nara prompt).
2. End-to-end smoke on iter-009 / iter-010 topic — no truncation.
3. Three real iterations on three real topics; human reads journals.
4. Call-stack UI: surface the parent→child agent chain in the active
   iteration panel ("Nara → critic_loop_v0 sub-agent on hypothesis X
   with neighbor doc_id=...").
