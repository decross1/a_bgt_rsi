# Oracle ⇄ Nara mailbox

Owner direction 2026-09-22 (DECISIONS.md D-082): Oracle sets the plan and
develops the lab itself, the UI, Nara's capabilities and its own memory. Nara
runs the lab and implements Oracle's plan. This mailbox is how they talk.

## The log

`run_state/oracle_nara_mailbox.jsonl` — append-only, hash-chained, one row per
message. Every row names its actor. Attribution is honest but not authenticated:
the chain shows order and integrity, not identity. The mailbox never carries
approvals; owner authority stays with D-082 and the owner's own channels.

Since 2026-09-22 the mailbox is the shared coordination state for every
participant (owner direction). Post under your own name: `oracle`, `nara`,
`claude`, `codex`, `system`, or `human:<id>`. Address a party (`oracle`, `nara`,
`claude`, `codex`, `owner`) or `all`; `list --to <party>` includes broadcasts.

| Kind | Who posts | Purpose |
|---|---|---|
| `plan_item` | oracle | A work order for Nara (Oracle-only; widening it was refused as a permission grant) |
| `withdraw` | oracle | Cancel an open plan item |
| `receipt` | nara | `held`, `claimed`, `validated`, `failed` for a plan item |
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
  bench/, experiments/, workers/ or notes/. Fence files, preregistrations,
  campaign manifests, `bench/flash_*` and anything else are held.
- Limits: 3 attempts, 30 minutes, 8 KiB test, 48 KiB per file.

## What Nara does (the lane)

`python -m orchestrator.nara_lane run` processes every open item once:

1. Holds an inadmissible item with reasons (`held`).
2. Claims an admissible one, creates a worktree from HEAD on branch `nara/<msg_id>`,
   writes Oracle's test and confirms it fails.
3. Asks the local Flash builder for the allowed files (logged to `logs/calls.jsonl`
   as `nara_lane_builder`), and runs the test in a bubblewrap sandbox with no
   network, no home directory and only the worktree writable.
4. Checks that only allowed paths and the test changed, and that the test's bytes
   are Oracle's, then commits and posts `validated` with the branch and SHA.
   Otherwise it posts `failed` with the reason and the test output tail.

Nara never merges, pushes, or edits its own fence. Oracle's integrator reviews
each `nara/*` branch and merges through the normal verification gate.

## Kill switches

`run_state/pause_nara_lane` stops the lane; `run_state/pause_coordinator` stops
the lane and the research loop. Only the owner removes a pause. A claimed item
left by a crashed run is closed as `failed` on the next run.

## Not yet in place

Oracle-side use (the Oracle harness and Pi session reading this protocol), a UI
panel for the thread, work cards and accomplishments projected from receipts,
and authenticated attribution. See D-082 and
`notes/research/2026-09-22-oracle-nara-mailbox/`.
