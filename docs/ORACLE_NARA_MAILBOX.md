# Oracle ⇄ Nara mailbox

Owner direction 2026-09-22 (DECISIONS.md D-082): Oracle sets the plan and
develops the lab itself, the UI, Nara's capabilities and its own memory. Nara
runs the lab and implements Oracle's plan. This mailbox is how they talk.

## The log

`run_state/oracle_nara_mailbox.jsonl` — append-only, hash-chained, one row per
message. Every row names its actor. Attribution is honest but not authenticated.
The chain shows order and detects an edit in place. It cannot detect a truncated
tail or a chain re-hashed from the edit onward, and it does not prove identity.
The file is git-ignored, so it has no versioned backup. The mailbox never carries
approvals; owner authority stays with D-082 and the owner's own channels.

Since 2026-09-22 the mailbox is the shared coordination state for every
participant (owner direction). Post under your own name: `oracle`, `nara`,
`claude`, `codex`, `system`, or `human:<id>`. Address a party (`oracle`, `nara`,
`claude`, `codex`, `owner`) or `all`; `list --to <party>` includes broadcasts.

| Kind | Who posts | Purpose |
|---|---|---|
| `plan_item` | oracle | A work order for Nara (Oracle-only; widening it was refused as a permission grant) |
| `withdraw` | oracle | Cancel an open plan item (its state becomes `withdrawn`) |
| `receipt` | nara | `held`, `claimed`, `validated`, `failed` or `withdrawn` for a plan item |
| `review` | claude, codex | Meta-oracle verdict (`accept`, `amend`, `reject`) replying to a plan, plan item or branch note. The lane runs a plan item only after an `accept` unless `config/nara_lane.json` exempts it; `amend`/`reject` holds it. Not an owner approval. See `docs/META_ORACLE_DAILY_LOOP.md`. |
| `question` / `answer` | oracle, nara, claude, codex, human:* | Anyone asks; anyone answers |
| `note` | everyone | Context or status without a required reply |

```
python -m orchestrator.oracle_mailbox post --as oracle --kind plan_item --to nara --body-file item.json
python -m orchestrator.oracle_mailbox list --to oracle          # Nara's receipts and questions
python -m orchestrator.oracle_mailbox fold                      # every plan item and its state
python -m orchestrator.nara_lane status
```

## Writing a plan item (Oracle)

```json
{
  "title": "Add a word-frequency helper for lab notes",
  "objective": "Create tools/text_stats.py with word_frequencies(text) ...",
  "task_class": "tooling",
  "allowed_write_paths": ["tools/text_stats.py"],
  "acceptance": {
    "test_path": "tests/test_text_stats.py",
    "test_content": "<the complete pytest file; it must fail before the change>",
    "test_argv": ["python", "-m", "pytest", "-q", "tests/test_text_stats.py"]
  },
  "budget": {"attempts": 3, "wall_clock_minutes": 20}
}
```

- `task_class`: documentation, tests, tooling, experiment_code or lab_organization.
- Oracle writes the acceptance test. It must fail before Nara's change
  (red-first), and Nara may not modify it.
- `allowed_write_paths` are exact repo paths under docs/, tests/, tools/,
  bench/, experiments/, workers/ or notes/. Fence files, the lane's own tests
  (`tests/test_oracle_nara_mailbox.py`, `tests/test_flash_*`), preregistrations,
  campaign manifests, `bench/flash_*`, `.git*` paths and anything else are held.
- Field types are checked when the item is posted. An item that still cannot be
  read is held as malformed; it does not block the items behind it.
- Optional fixture declarations (`plan 2026-09-24 d3`). A plan item whose test data
  came from a live lab file declares it, so the lane can refuse the hand-copying
  mistake before the sandbox instead of after a build:
  `fixture_sources` {fixture name: repo-relative live path}, `fixtures` {fixture name:
  the object the test uses}, and `fixture_enums` {fixture name: [field, ...]} for the
  fields whose values must also occur in that file. Three rules follow. A fixture key no
  live row of the source holds is refused naming the key and the live keys; a declared
  enum field holding a value the file never holds is refused naming the value (enum
  fields are declared, never inferred, so an ordinary string field is not judged); and a
  source path must exist inside the repo root, so a path in a plan item means a file.
  The three maps must name the same fixtures, which is checked at posting: a bare
  `fixture_sources` with no `fixtures` behind it compares nothing and is refused.
  A fixture named in no source is unchecked, so a purely synthetic fixture is fine, and
  nested keys are not compared - top level only, which is where the drift showed.
  For JSONL sources, keys are the union over rows of the fixture's own `kind`.
- Limits: 3 attempts, 60 minutes, 8 KiB test, 48 KiB per file. Each test run and
  builder call gets only the time left in the item's wall-clock budget; a
  builder call is capped at 1800 s with no retries (a 12K-token build on a
  shared server runs at roughly 15-20 tok/s).

### What the builder can see (read this before you point at a file)

The builder is one model call. It receives the item's `title`, its `objective`,
the acceptance test file, the last test output, the current contents of the
writable paths (`writable_paths`) - plus, for each declared `input_paths` entry, its visibility
verdict in `input_visibility` and, if that verdict is PRESENT, its bytes in
`input_contents` (each capped at MAX_FILE_BYTES, 48 KiB). Beyond those there is
nothing else: it does not see the repository, the mailbox, the plan, your
session, or any file you did not declare.

The worktree it works in is the lane base checkout's HEAD plus your acceptance
test. So a path is in that worktree only if it is tracked at the lane base HEAD,
or because this item writes it. A path named only in the objective's prose is
never sent: the rule is that content which is not committed at the lane base
has to go inline in the objective itself, which is capped at 4000 characters
(and a `title` at 200).

What admission does with a declared `input_paths` entry, once
oracle/2026-09-24-lane-input-visibility is merged (this document describes the
merged behaviour; the code that refuses an unreadable entry is not on main
until then):

- a regular file tracked at the lane base HEAD is judged PRESENT and its bytes
  are sent as `input_contents`, capped at MAX_FILE_BYTES;
- an untracked entry - or a directory, or a symlink - is held with the reason
  `declared input path is not readable by the builder`;
- an entry the lane fence denies is held as `outside the lane fence`.

A held item never reaches the builder, so a wrong pointer costs a
withdraw-and-repost.

The cost of getting this wrong is not a held item but an invented one. In the
2026-09-24 plan an objective told its builder to "copy the titles" from a
reading list that existed nowhere; the builder sees a writable path it has not
written as nothing, so the instruction read as *write that file yourself*, which
is how a citation task ends up producing citations that were never read.

A shape or format test is not a citation check. A test can prove a document has
3-5 candidates, 12 filled fields and a well-formed `iter-YYYY-MM-DD-NNN` id; it
cannot prove a cited paper exists or that a quoted title is the title of that
id. Never let the objective imply that a passing test verified a reference: cite
only content the objective carries, and route citation reality to
`tools/citation_screen.py`, whose verdicts are the only citation claim the lab
cites.
In short, `builder()` hands the model exactly these and nothing beyond
them: `title`, `objective`, the acceptance test, the last test output, the current
contents of `writable_paths`, and the `input_paths` verdicts
(`input_visibility`) with the bytes of each PRESENT input (`input_contents`). A
path named only in the objective's prose is never sent, which is why uncommitted
content goes inline. Nothing beyond that list reaches the model.

## What Nara does (the lane)

`python -m orchestrator.nara_lane run` processes every open item once:

1. Holds an inadmissible item with reasons (`held`).
2. Claims an admissible one, creates a worktree from the main checkout's HEAD on
   branch `nara/<msg_id>` (the receipt records `base_sha`), writes Oracle's test
   and confirms it fails.
3. Asks the local Flash builder for the allowed files (logged to `logs/calls.jsonl`
   as `nara_lane_builder`), and runs the test in a bubblewrap sandbox with no
   network, no home directory, and only the worktree writable. The worktree's
   `.git` pointer stays read-only. A pass needs pytest's JUnit report to show the
   acceptance test passing and no failures or errors, not just exit code 0. That
   stops a test process that exits early, not code that forges the report: the
   verdict comes from inside the run, so Oracle's review of the branch is the real
   check. Anything the run leaves in the worktree, ignored by git or not, counts as
   a change and fails the scope check, so a plan item should not write stray files.
4. Treats the worktree as untrusted after each sandbox run. Host reads and writes
   refuse symlinks and non-regular files. Changes come from a stat walk of the
   tree, not `git status`. Git runs with fsmonitor and hooks disabled, only after
   the `.git` pointer is checked unchanged, and adds only the named files.
5. Checks that only allowed paths and the test changed, and that the test's bytes
   are Oracle's, then commits and posts `validated` with the branch and SHA.
   Otherwise it posts `failed` with the reason and the test output tail. Receipts
   are trimmed to fit the 16 KiB row limit.

Nara never merges, pushes, or edits its own fence. Oracle's integrator reviews
each `nara/*` branch and merges through the normal verification gate.

Concurrency: by default the lane runs one item at a time. Setting
`max_concurrent_items` in `config/nara_lane.json` (or `--max-concurrent` /
`NARA_LANE_MAX_CONCURRENT` for a single run) lets one run process up to that
many items at once. That number is capped at the server's
`max_running_requests` minus one from `config/model_deployment.json` and at 4,
and is never below one, so the lane always leaves the server a slot. At any
setting, a run stops claiming once the time it has run plus the next item's
budget would exceed its pass budget (`pass_budget_s` in the config or
`NARA_LANE_PASS_BUDGET_S`; default 5100 s, the service's 5400 s stop timeout
less a margin). Items it does not claim stay open for the next run. One run still holds `run_state/.nara_lane.lock`. It examines
and claims items one at a time in mailbox order, and every item gets steps 1-5
above, in its own worktree and branch. Each claim holds a per-item lock under
`run_state/nara_lane_claims/` from before its `claimed` receipt until after its
final receipt, so no item is claimed twice. A worker that crashes posts `failed`
for its own item only.

## Kill switches

`run_state/pause_nara_lane` stops the lane; `run_state/pause_coordinator` stops
the lane and the research loop. The lane checks both before each item; items
already running finish. Only the owner removes a pause. A claimed item left by
a crashed run (its claim lock is free) is closed as `failed` on the next run.

## Not yet in place

Oracle-side use (the Oracle harness and Pi session reading this protocol), a UI
panel for the thread, work cards and accomplishments projected from receipts,
and authenticated attribution. See D-082 and
`notes/research/2026-09-22-oracle-nara-mailbox/`.
