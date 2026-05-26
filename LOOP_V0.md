# LOOP_V0 — literature-only loop slice

> **Status: active build plan.** Replaces the retired `plan.yaml`
> (archived under [`archive/plan/`](archive/plan/)). Reflects the
> 2026-05-26 direction change (see [`DECISIONS.md`](DECISIONS.md) D-030).

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

| Session | Build | Verification |
| --- | --- | --- |
| 1 | `schema/iteration_record.schema.json` + `workers/retrieve_literature.py` | Manual query: top-10 neighbors for a known textbook claim returns sensible chunks |
| 2 | `workers/hypothesize.py` | Type a seed topic → get 1–3 hypotheses; eyeball quality |
| 3 | `workers/novelty_classify.py` | Feed a known rediscovery in → returns `rediscovery` with correct nearest neighbor |
| 4 | `workers/critic.py` | Feed a hypothesis with a known contradicting paper → critic finds it |
| 5 | `workers/journal_writer.py` + `orchestrator/loop_v0_driver.py` | End-to-end single iteration writes a valid record and a markdown entry |
| 6 | Polish: 3 real iterations on real topics; human reads and reacts | Three records on disk; human says they're useful or what's wrong |

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
- **No dispatched sub-agents.** Workers are functions called by the
  driver, not separately-launched Claude Code sessions.

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
