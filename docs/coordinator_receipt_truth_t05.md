# Coordinator step and append receipt truth

A coordinator cycle marked `executed` means execution was attempted. It does not
mean every handler passed or every escalation was written. T05 separates those
facts without changing the escalation kinds, resolution menu, or human authority.

## Prospective evidence

After admission, each normalized plan step receives a deterministic
`<run_id>:step:<zero-based-index>` identity and a pre-dispatch request snapshot.
`request_digest` is `sha256:` plus the SHA256 of the UTF-8 JSON representation of
`{action, args}`, with sorted keys, compact separators and `ensure_ascii=False`.
The digest identifies request content; the step identity distinguishes repeated,
identical requests. The handler receives a separate deep copy of the arguments.
These fields are consistency evidence, not authenticated actor identity.

Execution collection requires a unique matching plan and outcome, exact request
and digest, and affirmative outer and handler success. Failed, skipped, ambiguous,
or mismatched steps remain in the execution outcomes and produce no bubble row.
There is no action-name or positional fallback. Dry-run bubbles remain previews;
they do not trigger persistence or qualify a durable bubble ID.

New appended rows retain the existing `run_id`, timestamp, finding IDs, note and
optional generic escalation fields, with additive request/step metadata. Legacy
helper inputs without association retain their old row shape; no historical
association is synthesized. The unchanged escalation schema allows these fields.
Existing acknowledgement readers continue to use `run_id`.

## Append receipts

`bubble_receipts` carries ordered persistence observations. `persisted` means the
complete encoded row was written, explicitly flushed, file-fsynced and closed
successfully. Only that receipt includes `bubble_run_id`. An append-boundary
failure records `error`, its message and `durability: unknown`; a pre-write
metadata rejection can report `not_persisted`. A failed write may have left bytes
behind. The batch stops after uncertainty, marking later entries `not_attempted`
without retrying. Earlier confirmed receipts remain evidence of their own rows.

This is not an atomic batch, an exactly-once guarantee, directory-entry durability,
or proof against every power-loss mode. No live ledger is backfilled or repaired.

The cycle projection preserves receipt errors. Its existing `bubble_run_ids`
contains only IDs supported by a unique exact current-run plan/outcome/receipt
association. Nonempty summaries alone are insufficient. Missing legacy receipt
metadata remains unknown; it is not proof that no historical row exists. The
cycle lifecycle remains `executed` even when an individual action or append fails.

The existing cycles API passes additive fields through. The current frontend
ignores detailed receipt errors; this change does not claim new UI visibility.
The independent cycle-log writer's own append policy is unchanged.

## Validation and delivery boundary

The fixed regression contract covers duplicate equal actions with mixed outcomes
in both orders, failed/skipped handlers, append failures, dry-run, exact successful
rows under the unchanged schema, and legacy/unrelated-action compatibility.
Private injected tests use copied source and synthetic data, never live models,
endpoints or a live cycle. The proportionate suite is:

- `tests/test_coordinator_actions.py`
- `tests/test_coordinator_escalation.py`
- `tests/test_coordinator.py`
- `tests/test_coordinator_beta_bounds.py`
- `tests/test_coordinator_cycle_log.py`
- `tests/test_emit_join_contract.py`

At the initial source freeze, all 130 tests in the six modules passed. Sixteen
additional parent-owned private checks passed, including conflicting receipts,
partial-batch close uncertainty and nested argument mutation. Baseline failures
were retained; these are offline component checks, not a live runtime smoke test.

T05 starts from public `28ed6b88bc29c1e05fbc920e7c4677b92402fe65`. Its only source
paths are the coordinator, cycle-log serializer, their two specified regression
modules, and this document. It admits one implementation and one correction;
actual acceptance was 2026-09-08 07:45:53 UTC, source stop 09:15:53 and terminal
stop 10:15:53. Distinct source/effect review precedes native code-only delivery.

Canonical source adoption requires current effect/process checks and one
nonblocking attempt at the existing cycle lock. A busy/missing/incompatible lock
holds adoption without retry. New cron interpreters may later load disk source;
a resident daemon is not reloaded by a merge. No service, model, experiment,
scientific status, budget or action-policy change is part of this repair.
