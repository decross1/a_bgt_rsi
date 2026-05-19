# Agent Plan — Week 1 (Days 31–37)

> This file tells **you** (the human researcher) how to orchestrate the
> Claude Code worktrees each day, and tells **each Claude session** what
> its file boundaries are. The canonical machine-readable plan is
> `plan.yaml`. Your human-only blocker list is `HUMAN_PLAN.md`. The
> source plan `week1_days_31-37_plan.md` is not yet committed to the
> repo; `plan.yaml` is canonical for task content.

## The three tracks

| Track | Worktree role | What it owns | What it must NEVER touch |
| --- | --- | --- | --- |
| **A — Main** | Critical-path Block 2 for the current day | `run_state/`, `logs/`, `bench/`, `chroma_db/`, `agent_wrapper/`, end-of-day commits | n/a — Main owns everything not explicitly delegated |
| **B — Tests & schemas** | Next-day(s) test scaffolds and JSON schemas, drafted ahead | `tests/`, `schema/`, draft files in `notes/` | `run_state/`, `agent_wrapper/`, `logs/`, `chroma_db/`, `localhost:8000` |
| **C — Pipeline & ops** | Self-contained scripts: ingest, scraper, cron, inspect_run, strategy stubs | `ingest/`, `pipeline/`, `cron/`, `scripts/`, `tools/`, `experiments/exp001_repeated_pd/strategies*.py`, `experiments/exp001_repeated_pd/quicklook.py`, `infra/` | `run_state/`, `agent_wrapper/`, `logs/`, `chroma_db/`, `localhost:8000` |

**Three hard rules that apply to every track:**

1. Only Track A writes to `run_state/week1.state.json` and
   `run_state/week1.run.jsonl`. Tracks B and C are read-only on those.
   If a side track needs to log scratch output, it writes to
   `notes/<branch-name>.log`.
2. Only Track A calls `LOCAL_LLM_BASE_URL` (the vLLM endpoint). Tracks
   B and C set `MOCK_LLM=1` in their environment and any test that
   would otherwise hit the endpoint stubs the response.
3. Track B and C **never** advance the day. They draft work for future
   days; Track A consumes that draft when its day arrives, validates
   it, and runs the day's gates.

## One-time setup (do before Day 2)

```bash
# In the main checkout, repo root:
echo ".claude/worktrees/" >> .gitignore

cat > .worktreeinclude <<'EOF'
.env
run_state/week1.state.json
run_state/week1.run.jsonl
EOF

# Verify Claude Code is recent enough for --worktree (≥ 2.1.50).
claude --version

# Verify worktrees work on this machine.
claude --worktree smoke-test
# In the spawned session, just `exit`. The worktree should auto-clean.
```

Confirm `claude --version` is ≥ 2.1.50; older versions do not have the
`--worktree` flag. If the version is too old, run `claude update` (or
re-install) before Day 2.

## How a day runs (template)

Each day's parallel schedule looks like this:

```
08:30  Block 1 starts. You only. No agents.
10:00  Block 1 ends.
10:30  ── Open Terminal 1 (Track A): claude --worktree dayN-main
        Track A reads plan.yaml + run_state, resumes at first
        incomplete task for the day, begins Block 2.

10:30  ── (If Day 2+) Open Terminal 2 (Track B): claude --worktree dayN-tests
        Track B receives its scoped prompt (see Section "Per-track
        prompts" below) and drafts the named scaffolds for day N+1
        (and N+2 where listed).

10:30  ── (If Day 3+) Open Terminal 3 (Track C): claude --worktree dayN-ops
        Track C receives its scoped prompt and drafts the named
        pipeline / ops scripts for day N+1.

10:30–
12:30  Track A executes Block 2 with [GATE] pauses for you.
        Tracks B/C run independently. If either finishes early,
        merge it back (see "Merging side branches" below) and exit
        that session.

12:30  Block 2 ends. All side worktrees that haven't merged remain
       paused. You go to lunch.

13:30  Block 3 — your reading and journal post. Track A is idle but
       open (it generates the journal stub on request).

14:30  Ambient listening (you only).

15:30  End-of-day. Track A commits, attests, and pre-stages tomorrow.
       Side worktrees: if any are unmerged and still useful, leave
       them; otherwise close them with `exit` and let cleanup happen.
```

## Per-track prompts (paste these into each session at launch)

### Track A — Main session prompt (paste at start of every day)

```
You are the Main session (Track A) for Week 1 of the research apparatus.
Read this in order:
  1. plan.yaml preamble + Appendix C
  2. CLAUDE.md
  3. run_state/week1.state.json
  4. Today's day section in plan.yaml

Resume at the first incomplete task in state.current_day. You own
run_state/, logs/, bench/, chroma_db/, agent_wrapper/, end-of-day
commits. Side worktrees (Tracks B and C) may draft files in tests/,
schema/, ingest/, pipeline/, scripts/, tools/, infra/, cron/, and
experiments/exp001_repeated_pd/strategies*.py + quicklook.py; you
merge their work via the procedure in AGENT_PLAN.md "Merging side
branches" when their day arrives.

Halt at every [GATE] task and wait for the human. Halt at every
hard_checkpoint failure and write day_aborted to the run log. Never
auto-publish Day 7 results.
```

### Track B — Tests & schemas prompt (paste when launching)

```
You are Track B (tests & schemas) for the Week 1 research apparatus.
You work in a git worktree isolated from the main session. Your job is
to draft test scaffolds and JSON schemas AHEAD of when Track A needs
them.

Allowed file writes:
  - tests/*.py
  - schema/*.json
  - notes/track-b-<topic>.md

Forbidden writes (never edit these):
  - run_state/*
  - agent_wrapper/*
  - logs/*
  - bench/*
  - chroma_db/*
  - any file Track A or Track C owns per AGENT_PLAN.md

Forbidden runtime behavior:
  - Do NOT call LOCAL_LLM_BASE_URL or any localhost:8000 endpoint. The
    GPU belongs to Track A. Stub all LLM responses in your scaffolds
    behind `if os.environ.get("MOCK_LLM"): ...`.
  - Do NOT modify run_state/. If you need to log progress, write to
    notes/track-b-<topic>.md.

Your specific task for today is at the end of this prompt. When the
task is complete:
  1. git add the files you wrote, in your worktree
  2. git commit with message "track-b dayN: <one-line summary>"
  3. Print "TRACK B COMPLETE — ready to merge" and exit.

Today's task:
{INSERT FROM THE PER-DAY TABLE BELOW}
```

### Track C — Pipeline & ops prompt (paste when launching)

```
You are Track C (pipeline & ops) for the Week 1 research apparatus.
You work in a git worktree isolated from the main session. Your job is
to draft self-contained pipeline, ingest, and ops scripts AHEAD of
when Track A needs them.

Allowed file writes:
  - ingest/*.py
  - pipeline/*.py
  - cron/*.sh
  - scripts/*.py
  - tools/*.py
  - infra/* (config files only, not /mnt/* on the host)
  - experiments/exp001_repeated_pd/strategies*.py
  - experiments/exp001_repeated_pd/quicklook.py
  - tests/test_chunking.py
  - tests/test_<your-module>.py (tests for files YOU own only)
  - notes/track-c-<topic>.md

Forbidden writes (never edit these):
  - run_state/*
  - agent_wrapper/*
  - logs/*
  - bench/*
  - chroma_db/*
  - schema/*.json (those belong to Track B)
  - tests/test_<not-your-module>.py

Forbidden runtime behavior:
  - Do NOT call LOCAL_LLM_BASE_URL or any localhost:8000 endpoint. The
    GPU belongs to Track A. Stub all LLM responses behind `if
    os.environ.get("MOCK_LLM"): ...`.
  - Do NOT install Python packages globally; create a venv inside your
    worktree if you need to test imports.
  - Do NOT touch ChromaDB at chroma_db/. If your script needs to
    exercise ChromaDB code paths, use a temporary in-memory client
    inside a unit test.
  - Do NOT modify run_state/. Scratch progress goes in notes/track-c-
    <topic>.md.

When the task is complete:
  1. git add the files you wrote
  2. git commit with message "track-c dayN: <one-line summary>"
  3. Print "TRACK C COMPLETE — ready to merge" and exit.

Today's task:
{INSERT FROM THE PER-DAY TABLE BELOW}
```

## Merging side branches (procedure)

When a Track B or C session prints `TRACK <X> COMPLETE — ready to
merge`, do this in your main checkout:

```bash
# From the main checkout, on the main branch (or current dev branch):
git fetch
git merge --no-ff worktree-dayN-tests   # or worktree-dayN-ops
# Resolve any conflicts (there should be none if file boundaries were
# respected). Run the agent's validation for the day; the merged files
# are inputs to Track A's next task.

# After merge succeeds and Track A has confirmed it can use the files:
git worktree remove .claude/worktrees/dayN-tests
git branch -d worktree-dayN-tests
```

If a conflict appears, that means a file-boundary rule was violated —
do not auto-resolve. Open both versions in a diff viewer and decide by
hand which side keeps its content. Most often the answer is: Track A's
version wins (Main owns the file), and the side track's edit was a
mistake.

## Per-day parallel schedule

### Day 1 — sequential only (no side tracks)

**Why no parallelism:** the entire day is hardware bring-up, firmware
gates, vLLM image pull, and NemoClaw onboarding. The repo is still
mostly empty. There's nothing for a side track to draft that wouldn't
just be speculation.

```
10:30  Terminal 1 only: claude --worktree day1-main
       (or just `claude` in the main checkout if you prefer; Day 1's
       state file is fresh so a worktree gives no benefit yet.)
```

### Day 2 — Track A + Track B (one side worktree)

**What Track B drafts today:** scaffolds for Day 3 and Day 4 tests that
consume the JSONL schema Track A locks in this morning.

```bash
# Terminal 1 — Track A
claude --worktree day2-main

# Terminal 2 — Track B (start AFTER Track A locks the JSONL schema,
#                       roughly 11:00; before that Track B has no
#                       schema to consume)
claude --worktree day2-tests
```

**Track B task prompt for Day 2:**

> Draft these files. Use the JSONL schema at
> `schema/calls.jsonl.schema.json` (Track A just committed it) and the
> wrapper docstring in `agent_wrapper/wrapper.py` for the function
> signatures you'll be testing.
>
> 1. `tests/needle_in_haystack.py` — args: `--collection`, `--needle`,
>    `--haystack-tokens`, `--output`. Inserts the needle into a haystack
>    of the specified token count, queries the named ChromaDB
>    collection, writes top-1 hit and score to the output JSON. Stub
>    the ChromaDB client at module level so tests can pass `--mock` and
>    return a deterministic fake hit. Day 3 will plug in the real
>    client.
> 2. `tests/test_tool_call_e2e.py` — runs `call_with_tools` (signature
>    in `agent_wrapper/wrapper.py` docstring) with the prisoner's
>    dilemma prompt. Writes 2 linked JSONL entries with matching
>    `parent_request_id`. Set `MOCK_LLM=1` mode that returns a
>    hardcoded tool call + summary so the test can be authored before
>    Day 4's tool implementation exists.
> 3. `tests/test_tool_call_robustness.py` — runs the same prompt N times
>    (default 5) at given temperature, computes invocation rate, writes
>    JSONL.
>
> Commit message: `track-b day2: draft Day 3+4 test scaffolds`.

**Merge order:** Track B merges Day 3 morning, before Track A starts
the Day 3 needle benchmark.

### Day 3 — Track A + Track B + Track C

**What Track B drafts today:** Day 5 retrieval test, Day 6 orchestrator
tests, Day 6 worker-contract schema (the shape is already in `plan.yaml`).

**What Track C drafts today:** the arXiv pipeline for Day 5 — biggest
single time-saver of the week.

```bash
# Terminal 1 — Track A
claude --worktree day3-main

# Terminal 2 — Track B (launch at start of Block 2)
claude --worktree day3-tests

# Terminal 3 — Track C (launch at start of Block 2)
claude --worktree day3-arxiv-pipeline
```

**Track B task prompt for Day 3:**

> Draft:
> 1. `tests/test_papers_retrieval.py` — args: `--query`, `--top-k`,
>    `--output`. Queries the `papers_recent` collection (will exist on
>    Day 5; for now use a mock that returns 3 fake papers when
>    `MOCK_LLM=1`). Writes results JSON with latency.
> 2. `tests/test_orchestrator_5_sequential.py` and
>    `tests/test_orchestrator_malformed_input.py` — args: `--output`.
>    Both expect an `OrchestratorClient` import from
>    `orchestrator/openclaw_runner.py` (won't exist until Day 6;
>    write the test against the contract in plan.yaml's
>    `day6_block2_worker_contract` task).
> 3. `schema/worker_contract.schema.json` — author from
>    `plan.yaml` task `day6_block2_worker_contract`. Input required
>    fields: `task_id, task_type, payload, parent_request_id`. Output
>    required fields: `task_id, status, result, errors, jsonl_log_path`.
>    Draft-2020-12 JSON Schema. Validate with
>    `jsonschema.Draft202012Validator.check_schema()`.
>
> Commit message: `track-b day3: draft Day 5+6 scaffolds`.

**Track C task prompt for Day 3:**

> Draft `pipeline/arxiv_scraper.py` and `pipeline/embed_and_store.py`:
> 1. `arxiv_scraper.py` — args: `--categories` (comma-separated),
>    `--since-days`, `--output` (JSONL path). Uses Semantic Scholar
>    API. **Required: exponential backoff** (1s → 2s → 4s → 8s → fail).
>    Reads `SEMANTIC_SCHOLAR_API_KEY` from env. Fields per paper:
>    `title, abstract, authors, arxiv_id, semantic_scholar_id,
>    citation_count`.
> 2. `embed_and_store.py` — args: `--input` (JSONL from scraper),
>    `--collection`, `--bge-m3-weights`. Embeds the `abstract` field
>    (NOT the full paper) with BGE-M3. Inserts into the named
>    ChromaDB collection. Dedupes on `arxiv_id`.
>
> Write a unit test `tests/test_arxiv_scraper.py` that runs the scraper
> against a mock Semantic Scholar response (use `responses` or
> `unittest.mock`) and asserts: exponential backoff fires on 429, dedup
> works, JSONL output is well-formed.
>
> Do NOT call BGE-M3 or ChromaDB for real — Track A owns those.
>
> Commit message: `track-c day3: draft Day 5 arxiv pipeline`.

**Merge order:** both side branches merge Day 5 morning, before Track A
starts pipeline implementation. Track A will validate them and may
amend.

### Day 4 — Track A + Track B + Track C

**What Track B drafts today:** none new — Track B from Day 3 should
still be unmerged (its files target Day 5–6). Skip Track B today
unless that's already merged.

**What Track C drafts today:** PD strategy stubs for Day 7.

```bash
# Terminal 1 — Track A
claude --worktree day4-main

# Terminal 2 — Track C
claude --worktree day4-pd-strategies
```

**Track C task prompt for Day 4:**

> Draft `experiments/exp001_repeated_pd/strategies.py` — implement TFT,
> grim trigger, all-C, and all-D as Game Reasoning Arena (GRA) agents.
> ~10 lines each per the source plan. Use the GRA agent interface from
> the cloned `game-reasoning-arena` repo (read its
> `agents/base_agent.py` or equivalent for the contract).
>
> Each strategy takes a `history` list of `(own_action, opp_action)`
> tuples and returns `'C'` or `'D'`. Do NOT include any strings like
> `tit-for-tat`, `grim trigger`, `all-C`, or `all-D` in any user-facing
> prompt — these are pure code, not prompts.
>
> Write `tests/test_strategies.py`: for each strategy, test the first 5
> rounds against a fixed opponent sequence and assert expected outputs.
>
> Commit message: `track-c day4: PD fixed strategies`.

**Merge order:** Track C from Day 3 (arxiv pipeline) merges first thing
Day 5 morning. Track C from Day 4 (PD strategies) merges Day 7 morning.

### Day 5 — Track A + Track C

**What Track C drafts today:** `tools/inspect_run.py` for Day 6.

```bash
# Terminal 1 — Track A
claude --worktree day5-main

# Terminal 2 — Track C
claude --worktree day5-inspect-run
```

**Track C task prompt for Day 5:**

> Draft `tools/inspect_run.py`:
> - CLI: `python3 tools/inspect_run.py --task-id <id>`
> - Reads `logs/orchestrator.jsonl` (will exist Day 6; for now your
>   tests use `logs/day2.jsonl` and `logs/day4_e2e.jsonl` which DO
>   exist).
> - Reconstructs the full causal chain via `parent_request_id` links:
>   orchestrator dispatch → worker invocation → wrapper request →
>   wrapper response.
> - Prints each level indented, with timestamps and durations.
>
> Write `tests/test_inspect_run.py` using fixture JSONL data you
> generate inline (a 4-link chain). Do NOT modify the real logs/
> directory.
>
> Commit message: `track-c day5: inspect_run CLI`.

**Merge order:** merges Day 6 morning, before Track A's inspect_run
task.

### Day 6 — Track A + Track C

**What Track C drafts today:** `experiments/exp001_repeated_pd/quicklook.py`
for Day 7.

```bash
# Terminal 1 — Track A
claude --worktree day6-main

# Terminal 2 — Track C
claude --worktree day6-quicklook
```

**Track C task prompt for Day 6:**

> Draft `experiments/exp001_repeated_pd/quicklook.py`:
> - CLI: `--input <results-dir>`, `--output-dir <plots-dir>`,
>   `--analysis-md <markdown-path>`.
> - Reads per-opponent CSV results (assume schema: rows are rounds,
>   columns are `own_action, opp_action, own_payoff, opp_payoff`, one
>   file per opponent).
> - Produces:
>   - 5 cumulative-payoff plots (one per opponent) in `--output-dir`.
>   - A markdown summary at `--analysis-md` with a table:
>     opponent | cooperation rate | mean payoff | switch points.
>
> Write `tests/test_quicklook.py` using a synthetic 5-opponent results
> directory you build in `tmp_path`. Assert: 5 plot files written,
> markdown table has 5 rows.
>
> Dependencies: pandas + matplotlib. Pin versions in the test (do not
> add to global requirements.txt — that's Track A's call).
>
> Commit message: `track-c day6: quicklook analysis`.

**Merge order:** merges Day 7 morning, before Track A's quicklook task.

### Day 7 — Track A only

**Why no side tracks:** the experiment uses the GPU for 20–40 minutes
and Track A is the only thing on the critical path. Side worktrees
would queue on inference. Stay single-threaded. The publication review
gate also halts everything; no parallel publication work.

```bash
# Terminal 1 only
claude --worktree day7-main
```

## Failure modes specific to parallel execution

### State-file collision

**Symptom:** `run_state/week1.run.jsonl` has a corrupted line; verify
returns malformed > 0; some entries are missing fields.

**Cause:** Two tracks tried to append simultaneously. Should be
impossible if the file-boundary rules were followed.

**Fix:** Restore from the most recent commit (`git checkout HEAD --
run_state/week1.run.jsonl`), re-run the affected task from Track A,
and audit which side track violated the rule. Strengthen its prompt.

### vLLM queue contention

**Symptom:** Track A's tokens/sec micro-bench produces inconsistent
numbers; determinism check fails because two callers interleaved.

**Cause:** A side track hit `localhost:8000` despite the rule.

**Fix:** Stop the side track. Set `MOCK_LLM=1` explicitly in its
worktree shell (`export MOCK_LLM=1`). Re-run Track A's bench. Audit the
side track's code for un-stubbed LLM calls.

### Stale-context drift

**Symptom:** A side branch drafted on Day 3 evening can't import a
helper that Track A added to `agent_wrapper/wrapper.py` on Day 4.

**Cause:** Side branch hasn't rebased on main.

**Fix:** In the side worktree, `git fetch && git rebase origin/main`
(or whichever branch Track A merges into). Reinstall the venv if
`requirements.txt` changed.

### Merge conflict on a "shared" file

**Symptom:** `git merge` reports a conflict in a file Track A also
edited.

**Cause:** A file-boundary rule was violated.

**Fix:** Track A's version always wins. Discard the side track's edit
to that file (`git checkout --ours <path>`), accept the merge, then
audit the side track's prompt and tighten the forbidden list.

## Daily orchestration cheat sheet

```
Day  | Track A worktree       | Track B worktree    | Track C worktree
-----|------------------------|---------------------|---------------------
1    | (none — main checkout) | none                | none
2    | day2-main              | day2-tests          | none
3    | day3-main              | day3-tests          | day3-arxiv-pipeline
4    | day4-main              | (Day 3 B unmerged)  | day4-pd-strategies
5    | day5-main              | (Day 3 B merged AM) | day5-inspect-run
                                                      (Day 3 C merged AM)
6    | day6-main              | none                | day6-quicklook
                                                      (Day 5 C merged AM)
7    | day7-main              | none                | none
                                                      (Day 4 + 6 C merged AM)
```

## What you gain, what you don't

**Gain:** Roughly 30–60 min/day on Days 3, 4, 5, and 6 by having the
next day's test scaffolds and prep scripts already drafted and waiting
for review at the start of Track A's Block 2 — instead of written under
time pressure inside Block 2. About 3 hours across the week. Enough to
absorb one bad day (a NemoClaw rabbit hole, a determinism debug
session) without losing the schedule.

**Don't gain:** Critical-path compression. Hard checkpoints and the
single GPU serialize Track A. Block 1 is sacred and human-only. Day 7's
experiment is sequential by nature.

**The discipline that makes this work:** file boundaries you actually
enforce. The moment a side track edits something it doesn't own, the
parallelism stops paying for itself and starts eating your evenings on
merge resolution. If you can't keep boundaries clean, drop back to
sequential (Track A only) — sequential single-track is faster than
parallel with conflicts.
