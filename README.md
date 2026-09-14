# a_bgt_rsi

`a_bgt_rsi` is a self-hosted research apparatus for game theory,
behavioral game theory, learning in games, and strategic behavior among
model agents. It runs on one NVIDIA DGX Spark and keeps the human researcher
responsible for scientific validity, deployed runtime change, and scientific
publication.

> **V2 foundation — 2026-09-14:** explicit research campaigns, a verified v0/v1
> archive, and measured benchmark follow-through now have implementation and
> evidence contracts. The resident models and serving runtime remain the
> established baseline. `/benchmarks` shows campaign activation and progress;
> the separate canonical deployment receipt records adoption. A controlled model-game study is
> separate work and has not been registered for execution.

New contributors and agent sessions should begin with
[`START_HERE.md`](START_HERE.md).

## What is running

| Layer | Deployed state |
| --- | --- |
| Hardware | NVIDIA DGX Spark, GB10, 128 GB unified memory |
| Generator / PI | Gemma 4 26B-A4B NVFP4 on `:8000` |
| Independent skeptic / builder | Qwen3.8-27B NVFP4-MTP on `:8001` |
| Serving | `vllm/vllm-openai:v0.21.0`, CUDA 13.0 |
| Research scheduler | user service `nara-daemon.service`, with hourly cron as a gated backstop |
| Observatory | React/Vite on `:5173`, FastAPI on `:8700`, local telemetry sampler |
| Weekly maintenance | Sunday 05:30 UTC, review-only, at most two subscription frontier calls and 120 Spark minutes per ISO week |

The exact model launch flags live in
[`cron/serve-models.sh`](cron/serve-models.sh). A model name returned by
`/v1/models`, a validated launch receipt, and current code are stronger
operational evidence than an old prose claim.

## Research flow

```mermaid
flowchart LR
    Q[Research question] --> T[Topic attempt]
    T --> I[Bounded iteration]
    I --> E[Evidence ladder L0-L3]
    E --> S[Independent skeptic]
    S -->|survives| L4[L4 surfaced finding]
    S -->|fails| K[Rejected or refinement owed]
    L4 --> H{Human verdict}
    H -->|valid| L5[L5 human-validated]
    H -->|revise / reject| K
```

The loop preserves attempts and negative results. Missing evidence never counts
as a pass. Only explicit human feedback can produce L5. Frontier Claude and
Codex sessions are subscription-based falsifiers and maintenance analysts;
they are not the local generator and cannot promote their own recommendations.

## Use the system

On the Spark, open the local UI:

- `http://127.0.0.1:5173/` — current state and triage
- `http://127.0.0.1:5173/ladder` — research evidence and next test owed
- `http://127.0.0.1:5173/benchmarks` — weekly benchmark and selected-campaign progress
- `http://127.0.0.1:5173/development` — operational state
- `http://127.0.0.1:5173/cycles` — coordinator trace history

Read [`docs/v2/OPERATOR_GUIDE.md`](docs/v2/OPERATOR_GUIDE.md) before pausing,
resuming, or restarting a service. The safe first check is read-only:

```bash
ui/scripts/ui-services.sh status
systemctl --user status nara-daemon.service --no-pager
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8001/v1/models
curl -fsS http://127.0.0.1:8700/api/health
```

## Documentation map

| Document | Authority and purpose |
| --- | --- |
| [`START_HERE.md`](START_HERE.md) | Current orientation, reading order, and session checklist |
| [`CLAUDE.md`](CLAUDE.md) | Runtime and scientific operating constraints for Claude sessions |
| `AGENTS.md` (checkout-local) | Standing Codex repository-maintenance authority and its boundaries |
| `.codex/config.toml` (checkout-local) | Trusted project permission and approval defaults |
| [`DECISIONS.md`](DECISIONS.md) | Append-only rationale; later accepted decisions supersede earlier ones |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | System topology and implemented v2 boundary |
| [`LOOP_V2.md`](LOOP_V2.md) | V2 foundation, activation evidence, and subsequent study gates |
| [`docs/v2/OPERATOR_GUIDE.md`](docs/v2/OPERATOR_GUIDE.md) | UI, health, pause, weekly review, restart, and rollback procedures |
| [`docs/v2/IMPLEMENTATION_PLAN.md`](docs/v2/IMPLEMENTATION_PLAN.md) | Current bounded implementation and evaluation work |
| [`docs/v2/research/PRODUCT_ARCHITECTURE_AUDIT.md`](docs/v2/research/PRODUCT_ARCHITECTURE_AUDIT.md) | Evidence behind the v2 product and data-model direction |
| [`docs/v2/research/EXTERNAL_CONTEXT.md`](docs/v2/research/EXTERNAL_CONTEXT.md) | Bounded external research context for the next game-theory study |
| [`docs/v2/RESEARCH_ARCHIVE.md`](docs/v2/RESEARCH_ARCHIVE.md) | Verified v0/v1 archive identity and retrieval instructions |
| [`LOOP_V1.md`](LOOP_V1.md), [`LOOP_V0.md`](LOOP_V0.md) | Historical build records; useful for provenance, not current orientation |
| [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) | Historical program background; its dated runtime claims are not current state |

The v5 SVGs under [`docs/diagrams/`](docs/diagrams/) remain the canonical
conceptual snapshot adopted in May 2026. They predate several accepted runtime
and evidence-ladder decisions, so do not use them as a live deployment manifest.

## Repository map

```text
agent_wrapper/   model backends, request policy, tool-call handling, call logs
orchestrator/    Nara, coordinator, bounded actions, weekly upgrade controller
workers/         research workers, evidence ladder, ledger reduction
pipeline/        literature ingestion and embedding
bench/           checked-in evaluation tasks, graders, runners, receipts
experiments/     preregistrations, manifests, and retained experiment evidence
schema/          versioned schemas for core public records
memory/          append-only research/evidence ledgers and derived projections
run_state/       append-only operational receipts, locks, activation and budgets
logs/            model and service event streams
ui/              local React/FastAPI observatory and telemetry sampler
docs/v2/         v2 preparation, operator guidance, archive, and research audit
human/           researcher-owned notes, verdicts, and learning material
archive/         retired implementation material retained for provenance
```

## Boundaries

- The domain remains game theory and adjacent strategic-agent research.
- The system does not infer that model behavior generalizes to humans.
- A completed transport call is not a successful scientific task.
- L4 means the automatic evidence and adversarial gates passed; it is not human
  validation. L5 requires an explicit human `valid` verdict.
- Weekly frontier analysis is review-only by default. It does not schedule a
  benchmark rerun, change a model/runtime, or promote production automatically.
- Live trading, publication, model/runtime cutovers, and removal of a human
  pause remain separately governed actions.
- Production mutations must retain a validated rollback and preserve the
  unified-memory guard.

Prior front-door documents are preserved in Git at `3c443e6` and in the
verified archive described by [`docs/v2/RESEARCH_ARCHIVE.md`](docs/v2/RESEARCH_ARCHIVE.md).
