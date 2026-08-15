# The self-improvement loop — operator manual (D-066)

The lab plans its own next fix. Telemetry the apparatus already emits becomes
a Gemma proposal; two opposed frontier falsifiers debate it; what survives is
emitted as a **red-first task packet**; the packet is dispatched to a builder
(local Qwen by default) inside an isolated worktree; the **dispatcher** — never
the builder — decides whether it is done; and the **primary session** merges.

Nothing in this chain merges, pushes, or touches the spine. Every stage is
runnable by hand, and the whole loop is off by default.

```
run_state telemetry ──▶ self_improve.gather_evidence()      [pure reads]
        │
        ▼
   Gemma proposal ─────▶ self_improve.propose()             [ONE small Tier-P change]
        │
        ▼
   frontier debate ────▶ self_improve.review()              [feasibility × risk/scope,
        │                  ≤ MAX_IMPROVE_ROUNDS = 3          revise → re-review]
        ▼
   red-first packet ───▶ self_improve.emit_packet()         [writes the acceptance test,
        │                                                     RUNS it, emits only if RED]
        ▼
   dispatch ───────────▶ packet_dispatcher.dispatch_packet(
        │                    packet, agent_cmd=["bash","tools/qwen_builder.sh"])
        ▼
   build ──────────────▶ tools/qwen_builder.sh              [Qwen writes in-scope files,
        │                                                     COMMITS on pkt/<id>]
        ▼
   verdict ────────────▶ dispatcher re-runs the acceptance test
        │                + tools/premerge_check.sh          [decided_by:"dispatcher"]
        ▼
   MERGE ──────────────▶ the primary session, by hand       [agents never merge]
```

| Stage | Artifact | Decides | Recorded in |
|---|---|---|---|
| evidence | `orchestrator/self_improve.py::gather_evidence` | — (pure reads) | — |
| proposal | `propose()` (Gemma, strict JSON) | Gemma | plan report |
| debate | `review()` (claude=feasibility, codex=risk/scope) | frontier, **inconclusive = veto** | plan report transcript |
| emit | `emit_packet()` | scope gate + the test's own exit code | `tasks/packets/PKT-SELF-*.json`, `memory/authorize_fix_queue.jsonl`, run log |
| dispatch | `orchestrator/packet_dispatcher.py` | dispatcher | `run_state/packets.jsonl` |
| build | `tools/qwen_builder.sh` | nothing — it only proposes file writes | its stdout (see `QWEN_BUILDER_LOG`) |
| merge | the human's primary session | human | git history, DECISIONS.md |

## Running each stage by hand

Everything below runs from the repo root with the absolute venv interpreter.

**1. See what the lab would propose (writes nothing).**

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.self_improve --dry-run
```

`--dry-run` gathers evidence, proposes, and debates, then prints the report —
no acceptance test, no packet, no queue row, no run-log row. Under `MOCK_LLM=1`
the proposer returns a deterministic stub and an un-injected frontier reviewer
**raises** rather than spawning a real CLI; use it to exercise plumbing, never
to judge a proposal.

**2. Emit the packet (the first stage that writes).**

```bash
env -u MOCK_LLM .venv-chroma/bin/python -m orchestrator.self_improve --emit
```

On a frontier `pass` this writes `tests/test_<name>.py`, **runs it**, and emits
`tasks/packets/PKT-SELF-<slug>.json` plus an `authorize_fix` row in
`memory/authorize_fix_queue.jsonl` **only if pytest exits 1** (real test
failures). Exit 0 (already passes), 2 (collection error), or 5 (nothing
collected) deletes the test and returns `{"emitted": false, "reason": ...}`.
Red-first is *proven*, not asserted.

**3. Commit the emitted artifacts — mandatory before dispatch.**

The acceptance test and the packet land **uncommitted in the main checkout**.
The dispatcher's worktree forks from `HEAD`, so an uncommitted test does not
exist in the worktree and the packet is undispatchable.

```bash
git add tests/test_<name>.py tasks/packets/PKT-SELF-<slug>.json
git commit -m "packet(PKT-SELF-<slug>): red acceptance test + packet"
```

Committing the packet JSON too is what lets `tools/qwen_builder.sh` resolve the
`test_cmd` on its own (see the env contract below).

**4. Dispatch.**

```bash
env -u MOCK_LLM .venv-chroma/bin/python - <<'PY'
import json
from pathlib import Path
from orchestrator.packet_dispatcher import dispatch_packet

packet = json.loads(Path("tasks/packets/PKT-SELF-<slug>.json").read_text())
print(json.dumps(dispatch_packet(
    packet, agent_cmd=["bash", "tools/qwen_builder.sh"]), indent=2))
PY
```

Set `QWEN_BUILDER_LOG=/home/decross1/projects/a_bgt_rsi/logs/qwen_builder.log`
first — see "Known gaps". The dispatcher creates `../worktree-pkt-PKT-SELF-<slug>`
on branch `pkt/PKT-SELF-<slug>`, runs the builder there, then decides.

To dispatch everything the planner has queued instead of one packet by name,
`packet_dispatcher.consume_authorize_fix_queue(Path("memory/authorize_fix_queue.jsonl"))`
returns the emitted packets verbatim (the queue row carries the whole packet).

**5. Merge — the primary session, by hand.**

```bash
cd ../worktree-pkt-PKT-SELF-<slug> && git log --oneline -1   # inspect the commit
cd /home/decross1/projects/a_bgt_rsi
git merge --no-ff pkt/PKT-SELF-<slug>
```

Only after the stage-3/4 gates of `docs/packet_sdlc.md`: the framework
`code-review` skill on `git diff <merge-base>..HEAD`, the full suite green, and
one real `env -u MOCK_LLM` smoke. A `done` verdict from the dispatcher is the
*entry* condition for review, not a substitute for it.

Cleanup after either outcome:

```bash
git worktree remove --force ../worktree-pkt-PKT-SELF-<slug>
git branch -D pkt/PKT-SELF-<slug>      # on abandonment only
```

## The builder's env contract

`tools/qwen_builder.sh` runs with cwd = the packet worktree and consumes:

| Variable | Source | Required | Meaning |
|---|---|---|---|
| `PKT_TASK_ID` | dispatcher | **yes** | packet id; names the commit |
| `PKT_OBJECTIVE` | dispatcher | **yes** | what to accomplish |
| `PKT_FILES_IN_SCOPE` | dispatcher | **yes** | JSON array — the write fence |
| `PKT_FILES_OUT_OF_SCOPE` | dispatcher | no (`[]`) | shown to the model verbatim |
| `PKT_FORBIDDEN_ACTIONS` | dispatcher | no (`[]`) | shown to the model verbatim |
| `PKT_TEST_CMD` | **operator** | no | the acceptance `test_cmd`. Fallback: `tasks/packets/<PKT_TASK_ID>.json` in the worktree. Absent ⇒ loud warning, advisory run skipped |
| `PKT_ACCEPTANCE_TEST` | operator | no | extra read-only file to show the model; otherwise any existing path named in the `test_cmd` is used |
| `QWEN_ENDPOINT` | operator | no | default `http://127.0.0.1:8001/v1/chat/completions`; **the test-injection seam** |
| `QWEN_MODEL` | operator | no | default `qwen3.6-27b-nvfp4-mtp` |
| `QWEN_TEMPERATURE` / `QWEN_MAX_TOKENS` / `QWEN_TIMEOUT_SEC` | operator | no | `0.2` / `6144` / `600` |
| `QWEN_PROMPT_CHAR_CAP` | operator | no | `20000`; file bodies over budget are head-truncated and marked |
| `QWEN_PYTHON` | operator | no | `python3` (stdlib only — the worktree has no relative `.venv-chroma`) |
| `QWEN_BUILDER_LOG` | operator | no | absolute path **outside** the worktree; appends the phase log |

The first three missing ⇒ exit 1 with the variable named. The builder never
guesses a packet's bounds.

What it does: assembles the objective + in-scope file contents + the acceptance
test (read-only) + the forbidden actions into one bounded prompt; demands a
JSON array of `{"path", "content"}` full-file writes; **refuses any path outside
`files_in_scope`** (all-or-nothing — a violating plan writes nothing); writes;
runs the acceptance test once for its own feedback; then **commits** as
`qwen-builder <qwen-builder@a-bgt-rsi.local>`. One retry on an unparseable
reply, then it gives up loudly. `MOCK_LLM` is irrelevant to it — it talks to
`:8001` directly, so the model must actually be up (`docker ps | grep vllm-qwen`).

## Scope: Tier P only

The planner may propose changes **only** under `workers/ tools/ tests/ docs/
bench/ experiments/` (Tier P). `emit_packet()` refuses, naming every offending
path, when a proposal touches:

- **Tier S** — `orchestrator/nara.py`, `orchestrator/tool_registry.py`,
  `schema/`, `run_state/`, `agent/`, `ui/`, `cron/`, `CLAUDE.md`,
  `DECISIONS.md`, `ARCHITECTURE.md`, or any pinned version string;
- **untiered** paths (e.g. `orchestrator/` generally) — refused too. A
  self-proposer that may widen its own blast radius is precisely what this gate
  exists to prevent.

Tier S is human-ratified (D-062, ratified as G4 on 2026-08-15, recorded in
`run_state/overrides.jsonl`; table in `docs/packet_sdlc.md`) because it holds
the things that make results *comparable across time*: the spine every worker
calls, the schemas records are validated against, the version pins that make a
finding reproducible, and the operating contract itself. A model that can edit
the ruler it is measured with produces numbers that mean nothing — so no agent,
workflow, packet, or primary acting alone entrenches Tier S. `tools/premerge_check.sh`
enforces the same list mechanically on the packet branch, and `tools/qwen_builder.sh`
enforces `files_in_scope` a third time at write. Three independent fences,
because each catches what the others cannot: the planner catches intent, the
builder catches the model's output, premerge catches the committed diff.

## Arming and disarming

The loop is **off unless a human runs a command**. There is no cron entry, no
coordinator action, and no daemon path that reaches `dispatch_packet` — LOOP_V1's
continuous-running clause (D-063) covers the coordinator, not this.

- **Armed** = a human runs stage 2 with `--emit` and then stage 4. Stage 1
  (`--dry-run`) is always safe.
- **Disarmed** = do not run them. To harden further: `chmod -x tools/qwen_builder.sh`
  and/or move the packet out of `tasks/packets/`. `dispatch_packet` has no
  default agent — `agent_cmd=None` raises, so nothing dispatches by accident.
- **Kill a run in flight**: `touch run_state/pause_coordinator` stops the
  coordinator, but a hand-run dispatch is a foreground process — Ctrl-C it, then
  `git worktree remove --force ../worktree-pkt-<id>`. A killed builder leaves an
  open `{"status":"dispatched"}` ledger line with no closing line; that
  asymmetry is the signal, not noise.
- **Frontier vendors**: `SELF_IMPROVE_FEASIBILITY_VENDOR` (default `claude`)
  and `SELF_IMPROVE_RISK_VENDOR` (default `codex`); review timeout
  `SELF_IMPROVE_REVIEW_TIMEOUT_S`. An `inconclusive` verdict blocks emission
  (the deliberate inverse of `workers/frontier_review.py`'s fail-open posture —
  this screen guards the apparatus modifying itself).

## Failure modes and what they look like

`run_state/packets.jsonl` carries **two lines per attempt**: an open line
written *before* the builder is invoked, and the dispatcher's closing verdict.

```jsonl
{"ts":"...","status":"dispatched","packet_id":"PKT-SELF-x","attempt":1}
{"ts":"...","status":"done","packet_id":"PKT-SELF-x","attempt":1,"test_output_digest":"…","decided_by":"dispatcher"}
```

| Failure | What happens | Ledger signature |
|---|---|---|
| **Model writes out of scope** | the builder refuses before writing anything, exits non-zero, commits nothing | closing `"status":"failed"` with a `verify_tail` of the still-failing test and **no** `agent_error` — the refusal itself is only in the builder's stdout |
| **Model reply unparseable** | one retry with a corrective, then a loud give-up; nothing written | same as above — `failed` with the red `verify_tail` |
| **Model changed nothing** | staged diff empty; the builder dies rather than making an empty commit | same as above |
| **Dirty tree** | work uncommitted (an in-scope path is git-ignored so `git add` failed) **or** the acceptance test left an untracked artifact that `.gitignore` does not cover — `git status --porcelain` counts untracked files, and `__pycache__/`+`.pytest_cache/` are the only ones ignored today | `"status":"failed"` + `"agent_error":"agent left uncommitted changes (N paths) — done requires a committed branch"`; the builder also logs `WARNING: tree is NOT clean after commit` with the paths |
| **Premerge violation** | test green, but the diff touches a protected path / exceeds `max_diff_lines` | `"status":"failed"`, report `premerge_ok:false`; **terminal** — no retry, because a later attempt cannot un-commit the violation |
| **Budget exhaustion** | every attempt failed | last closing line `"status":"budget_exhausted"`; report carries `rollback_hint` |
| **Agent timeout** | builder exceeded `wall_clock_minutes` | `"agent_error":"agent timed out after Ns"` |
| **`:8001` down** | curl fails, builder dies immediately | `failed` / `budget_exhausted` with a red `verify_tail`; confirm with `docker ps` and `cron/watchdog.sh` |
| **Context window blown** | vLLM returns HTTP 400 (`maximum context length is 16384 tokens`) — it does **not** clamp. Only reachable by raising `QWEN_PROMPT_CHAR_CAP`/`QWEN_MAX_TOKENS` past the served `--max-model-len` | `failed`; the 400 body is in the builder's log, nowhere else |
| **Refusal (never dispatched)** | precondition failed, acceptance test already green (`nothing_to_do`), or it hung | **no `packets.jsonl` line at all** — refusals precede the attempt loop and appear only in `run_state/week1.run.jsonl` as `{"task_id":"packet:<id>","status":"refused"}` |

Two traps worth naming, both learned the hard way (2026-08-14 e2e):

- **Relative interpreter paths die in the worktree.** `test_cmd` re-runs inside
  `../worktree-pkt-<id>`, where `.venv-chroma/bin/python` does not exist. Use the
  absolute path — `self_improve.emit_packet()` already does.
- **Attempts share one worktree.** Attempt 2 sees attempt 1's commit. That is
  deliberate (the builder can build on partial progress) but it means a bad
  attempt-1 commit is *in the diff* premerge finally judges.

## "An organization of developers" — swapping the builder

`agent_cmd` is an injected argv, and the dispatcher does not care what is behind
it. The packet contract — `PKT_*` env in, committed work on `pkt/<id>` out — is
the whole interface. Any of these is a drop-in replacement:

```python
agent_cmd=["bash", "tools/qwen_builder.sh"]        # local Qwen (default)
agent_cmd=["claude", "-p", "Read $PKT_OBJECTIVE…"] # a frontier CLI
agent_cmd=["codex", "exec", "…"]                   # another vendor's CLI
agent_cmd=["bash", "tools/dev_team.sh"]            # a fan-out of several agents
```

The requirements on any builder are exactly four: read the `PKT_*` env instead
of guessing; write only `files_in_scope`; **commit** on the packet branch (a
green test over a dirty tree is scored `failed`); never merge or push. A "team"
is therefore just an `agent_cmd` that fans out internally and commits once at
the end — the dispatcher still re-runs the acceptance test and premerge, and the
primary still merges. Note that any frontier builder inherits a spawn env with
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, and
`SEMANTIC_SCHOLAR_API_KEY` **stripped**; a CLI needing credentials must get them
some other way, deliberately.

Roles stay fixed regardless (CLAUDE.md §Out-of-scope guardrails, D-061): Gemma
is the sole generator, frontier CLIs are falsifiers in the *planning* debate,
and a builder — Qwen or otherwise — writes code to a plan it did not author.

## Known gaps

- **The dispatcher drops the builder's output.** It runs the agent with
  `capture_output=True` and never stores the result, so a scope refusal or an
  unparseable-reply give-up is invisible in the ledger. Until that changes,
  always set `QWEN_BUILDER_LOG` to an absolute path (`logs/*.log` is
  git-ignored, so the main checkout's `logs/` is a safe home).
- **The dispatcher does not export `test_cmd`.** The builder resolves it from
  `PKT_TEST_CMD` or the committed packet file; with neither, it works blind and
  says so. Exporting it is a one-line dispatcher change, and the dispatcher is
  Tier S — a human ratifies that, not this loop.
- **No coordinator wiring.** Emission and dispatch are hand-run by design.
  Automating either is its own gated decision.
