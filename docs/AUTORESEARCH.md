# AUTORESEARCH — the tier ladder and how to drive the (single-shot) loop

How a single experiment is promoted into a LOOP_V0 iteration. This is the
operator's reference for the autoresearch driver: the tier ladder it walks, the
one command that drives it, and the guardrails that keep it single-shot.

Canonical code:
- `orchestrator/autoresearch.py` — the driver (CLI entry point below).
- `orchestrator/tier_registry.py` — maps `(tier, experiment)` to that
  experiment's `run` / `analyze` / `loop_bridge` modules.
- per-experiment `run.py` / `analyze.py` / `loop_bridge.py` under
  `experiments/<exp>/` — the actual experiment + bridge logic. The driver
  REUSES these; it reimplements none of them.

> Status note: both `orchestrator/autoresearch.py` and
> `orchestrator/tier_registry.py` are present and verified (a real `--live` run
> bridged `iter-2026-06-05-004` end-to-end). They are the single-shot front door
> over the per-experiment chain (run → analyze → loop_bridge), which they REUSE
> — see `experiments/exp003_vickrey_rediscovery/loop_bridge.py` for the reference
> bridge. You can still drive a per-experiment `loop_bridge.py` directly with the
> same `--dry-run` / `--live` convention when you want just one experiment.

## 1. The three-tier ladder (and current status)

The sandbox spectrum from `docs/sources/research_program_v2.md`. Be honest about
what runs versus what is only designed:

| Tier | What it is | Experiments | Status |
|---|---|---|---|
| `synthetic` | Classical games with known equilibria; the loop rediscovers or characterizes what's known, and success is cleanly measurable. | `exp001_repeated_pd`, `exp003_vickrey_rediscovery`, `exp004_combinatorial_auction`, `exp005_mechanism_aware` | **Real runs.** exp003 has a working results → `experiment_outcome` bridge (Slice-1). |
| `semi_synthetic` | LLM-as-designer / multi-agent scenarios with structure but no single ground truth; scored against a benchmark (e.g. VCG). | `exp006_mechanism_design` | **Exists, LLM-as-designer seed.** Real `run.py`/`analyze.py`/`loop_bridge.py`; needs a live Gemma backend to produce designs. |
| `applied` | Polymarket (and possibly other prediction markets). | none | **NOT built.** Design-only, CFTC-gated per CLAUDE.md out-of-scope guardrails. No live trading, no experiment dir. Do not run. |

The loop's value is strongest when a finding generalizes across tiers; its
failure modes are most diagnostic when it succeeds in one tier and fails in
another. That cross-tier evidence is what the bridge carries up.

## 2. How to run

One command drives one experiment through to one bridged iteration:

```
python -m orchestrator.autoresearch --tier <t> --experiment <e> [--run] [--replicate] [--live]
```

- `--tier` — `synthetic` | `semi_synthetic` (`applied` is rejected; not built).
- `--experiment` — the experiment id, e.g. `exp003_vickrey_rediscovery`.
- `--run` — (re)execute the experiment's `run.py` before analyzing. Omit to
  reuse the existing `results/` artifacts.
- `--replicate` — run via `experiments/replication_driver.py` for a
  replication pass instead of a single fresh run.
- `--live` — see below.

**Default (dry-run, reuse-results, no model).** With none of the flags above,
the driver reuses the experiment's committed `results/`, builds the
`experiment_outcome` payload + topic seed via that experiment's `loop_bridge.py`,
and PRINTS what it would thread — it makes **no LLM call**. This is the
`--dry-run` path of `loop_bridge.py` and is safe under the default `MOCK_LLM=1`
shell (which stubs embedders). Use it for smoke checks and in tests.

**`--live` (real Gemma).** Calls `orchestrator.nara.run_iteration` with the
`experiment_outcome`, running a full LOOP_V0 iteration: novelty + critic engage
with the experimental finding alongside the literature. This needs a real model:

```
env -u MOCK_LLM python -m orchestrator.autoresearch \
    --tier synthetic --experiment exp003_vickrey_rediscovery --live
```

Per CLAUDE.md rule 10, `--live` MUST be prefixed with `env -u MOCK_LLM` and
requires a live vLLM/Gemma backend. Forgetting the prefix silently stubs the
embedder and the iteration is meaningless.

## 3. Single-shot guardrail (inviolate)

CLAUDE.md forbids a continuous-running orchestrator: LOOP_V0 is single-shot,
human-triggered iterations. **One invocation = one experiment → one bridged
iteration, then exit.** The driver does not loop, schedule, poll, or
"keep iterating." There is no daemon and no watch mode. To run another
experiment, a human issues another command. Any auto-looping behavior would
violate the out-of-scope guardrails and must not be added here.

## 4. No new UI-facing data shape

The driver introduces **no new data shape**. It reuses the existing
`experiment_outcome` bridge: results flow into the iteration via the optional
`experiment_outcome` block on `iteration_record`
(`schema/iteration_record.schema.json`), exactly as `exp003`'s `loop_bridge.py`
already does. The UI already renders that block.

The shape contract is `docs/DATA_SHAPES.md`:
- `experiment_outcome` = `{ experiment_id, metric, value: number|object,
  trials?, summary?, results_path? }` (DATA_SHAPES §1).
- per-experiment `results/summary.*` shapes (DATA_SHAPES §2) are heterogeneous;
  each `loop_bridge.py` knows how to read its own.

If a future change alters any of these shapes, append a dated entry to the
`docs/DATA_SHAPES.md` changelog in the same commit (its standing rule). As long
as the driver only threads `experiment_outcome`, there is nothing new for the
UI session to reconcile.
