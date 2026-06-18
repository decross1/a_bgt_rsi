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
