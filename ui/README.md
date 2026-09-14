# UI — orchestrator dashboard + call-chain inspector

Observability layer for the week-1 research apparatus. Companion to
`plan.yaml`; the authoritative spec is `ui_plan.md` at the repo root.

Three pieces, three directories:

| Dir | What | Status |
|---|---|---|
| `sampler/` | 1 Hz daemon → `ui/logs/telemetry.jsonl` | **built** (step 6.1) |
| `backend/` | FastAPI: reads JSONL logs, serves HTTP + WebSocket | **built** (steps 6.2, 6.4) |
| `frontend/` | React SPA: dashboard + chain inspector | **built** (steps 6.3, 6.5-6.7) |

Everything lives under `ui/`. The sampler is read-only with respect to
the apparatus and depends on nothing the week-1 build produces, so it
can run now. The backend/frontend consume the apparatus's call logs and
are built against fixtures until those schemas land — see `ui_plan.md`
§10.

## Benchmark progress

Open **Operations → Benchmark progress** at `/benchmarks` (also available in
the command palette). The page reads `GET /api/weekly_upgrade/progress` and
refreshes once a minute; **Refresh records** requests an immediate refresh.

Select a recorded week to inspect frontier review activity, trial completion,
graded task results, transport failures, and the shared Spark allowance. Expand
a family for its uncertainty, configuration, and artifact hashes. Task scores
keep their original denominators, including failed attempts. Missing evidence
is displayed explicitly.

Week-over-week history appears when two or more weeks share a frozen benchmark
contract. Changes in fixtures, grading, baseline, seed cohort, or evaluation
budgets can break comparability. One week establishes a baseline. Recorded
operator summaries alone do not establish a scientific upgrade.

The Sunday review-only job adds review activity; measured progress requires
separately executed, recorded benchmark trials. Opening or refreshing this page
does not run a benchmark or promote a model. See
[`notes/benchmark_progress_mvp.md`](notes/benchmark_progress_mvp.md) for the
evidence contract and acceptance criteria.

## Layout

```
ui/
├── README.md
├── requirements-ui.txt          # python deps for sampler + backend
├── conftest.py                  # puts ui/ on sys.path for pytest
├── .gitignore
├── schema/
│   └── telemetry.jsonl.schema.json
├── logs/                        # sampler output (gitignored)
└── sampler/                     # see sampler/README.md
```

## Run

```sh
pip install -r ui/requirements-ui.txt
ui/sampler/run.sh                 # start the telemetry sampler
ui/backend/run.sh                 # start the backend API on :8700

# Backend tests run under the PINNED harness venv `ui/.venv-ui` — it is the one
# with pytest + fastapi installed (the repo's other venvs lack one or the
# other). Prefix with MOCK_LLM=1 so the suite never makes a real model call.
MOCK_LLM=1 ui/.venv-ui/bin/python -m pytest ui/sampler/tests ui/backend/tests
```
