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

### Publishing a daily plan

Oracle publishes `PLAN READY` with `publish-plan-ready`, not a hand-written
note. The command accepts a local branch, its full committed head, an immutable
`run_state/daily_plans/YYYY-MM-DD-rN.json` revision, and the expected SHA-256
digests of that plan and its committed state packet. It reads both files through
Git at that exact head, verifies the plan's top-level `state_packet_sha256`, and
then appends one `note` under the existing mailbox lock.

```text
python -m orchestrator.oracle_mailbox publish-plan-ready \
  --branch oracle/2026-09-25-r8-replayable --head-sha <40-hex-sha1> \
  --plan-path run_state/daily_plans/2026-09-25-r8.json --plan-sha256 <64-hex> \
  --state-packet-path notes/ops/2026-09-25-loop-stall/STATE_PACKET_R8.md \
  --state-packet-sha256 <64-hex>
```

The exact same call is a retry receipt, not another note. A different binding
for the same revision/path is refused; publish a new revision instead. It does
not make the commit and mailbox append cross-file atomic, authenticate the
claimed actor, accept a plan, or approve work. A retry after a committed file
but before the note was appended is the supported recovery.

The canonical note retains `title: "PLAN READY: YYYY-MM-DD (rN)"` and
`ref: {path, sha256}` for the existing dashboard, mailbox list, and
meta-oracle runner; its typed `event`/`protocol` binding is reserved to this
publisher. Generic `post note` also refuses every `PLAN READY` title prefix,
so it cannot create a consumer-visible but unverified announcement. Historical
date-only, `-rN`, and `(rN)` title rows remain readable as legacy evidence and
block an ambiguous duplicate. No production daily-loop producer invokes this command yet, so this
source contract does not itself make the loop live or repair any prior plan.

The mailbox rejects a pre-existing symlink at the mailbox, adjacent lock, or
known parent component and opens the leaf files with `O_NOFOLLOW`. This is a
same-UID coordination control, not a hostile-same-UID filesystem boundary: a
concurrent parent-directory rename between inspection and open is outside this
source-only contract. Keep the mailbox directory owned and writable only by
the trusted lab account.

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
- Limits: 3 attempts, 30 minutes, 8 KiB test, 48 KiB per file. Each test run and
  builder call gets only the time left in the item's wall-clock budget.

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

## Kill switches

`run_state/pause_nara_lane` stops the lane; `run_state/pause_coordinator` stops
the lane and the research loop. The lane checks both before each item. Only the
owner removes a pause. A claimed item
left by a crashed run is closed as `failed` on the next run.

## Not yet in place

Oracle-side use (the Oracle harness and Pi session reading this protocol), a UI
panel for the thread, work cards and accomplishments projected from receipts,
and authenticated attribution. See D-082 and
`notes/research/2026-09-22-oracle-nara-mailbox/`.
