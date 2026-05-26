# Track B — Day 8 schema amendments (DRAFT for Day-42 lock)

Worktree `day8-schemas` (branch `worktree-day8-schemas`). Implements
the schema amendments queued for the Day-42 lock per
[`PHASE_1_ROADMAP.md`](../PHASE_1_ROADMAP.md) §5.1 Day-38 / Day-42 rows.

Track A is the reviewer. Until Track A merges, the proposed files live
under `schema/proposed/` and the existing `schema/*.json` continue to
govern. Existing Day-3.5 tests (`tests/test_events_schema.py`,
`tests/test_calls_schema_retrieval_context.py`) still pass unchanged
under the proposed files (verified Day 8 — 32/32).

## Deliverables

| File | Kind | What it changes |
|---|---|---|
| `schema/proposed/events.jsonl.schema.json` | extend (additive) | `human_intervention.subtype` enum gains `gate_clear`; D-028-shape fields added (decision_id / human_identity / disposition / decisions_ref / gate_name) and required when subtype=='gate_clear'. `calibration_entry` gains a `calibration_type` discriminator and an `auto_evaluator` shape (kappa / spearman / threshold / ground_truth_ref). |
| `schema/proposed/calls.jsonl.schema.json` | extend (additive) | `retrieval_context.items` gains 4 optional inner fields (score / collection / retrieved_for / embedder_version) for Week-2 critic + meta-review provenance. |
| `tests/test_events_schema_proposed.py` | new | 43 cases. Backwards-compat for both branches; new shapes; missing/malformed; discriminator boundary. |
| `tests/test_calls_schema_proposed.py` | new | 24 cases. Backwards-compat (incl. existing `logs/dayN.jsonl` revalidation); new field types/enum; unknown-field rejection still holds. |

All 67 new cases pass; both files run cleanly under `python3 -m
unittest` and `pytest`. No `LOCAL_LLM_BASE_URL` calls. No writes to
`run_state/week1.*`. No writes outside the Track-B zones.

## P1 / `human_intervention` — D-028 shape

The Day-8 prompt named D-028 (the Day-7 publication-review gate
clearance, 2026-05-24, no-publish-standalone disposition) as the
shape-test for this amendment. The D-028 entry surfaces six fields the
schema needs to capture:

| D-028 fact | New schema field |
|---|---|
| (a) decision ID — "D-028" | `decision_id` (pattern `^D-\d{3}$`) |
| (b) date — 2026-05-24 | already `timestamp` |
| (c) human identity — decross1 | `human_identity` |
| (d) disposition — no-publish-standalone | `disposition` |
| (e) DECISIONS.md cross-reference | `decisions_ref` (e.g. `DECISIONS.md#D-028`) |
| (f) gate-name — day7_publication_review | `gate_name` |

Each is OPTIONAL at the top level so Day-3.5-shape records (subtype ∈
`{edit_prompt, edit_code, reject, redirect, manual_decision}`) keep
validating. The fields are made REQUIRED by an `if/then` block: when
`subtype == "gate_clear"`, all five must be present.

### Design tension worth flagging to Track A

The 2026-05-19 adversarial-review memo (P1 prose,
`notes/research/2026-05-19-adversarial-review/5_frozen_plan_change_proposals.md`)
explicitly says:

> This is distinct from existing `human_only` task entries (which are
> *scheduled* human work) and from `gate_clear` events (which are
> human-gate clearance). This event captures human action *inside* an
> otherwise-agent task.

So the original P1 design pitched `gate_clear` as a SEPARATE event
type, not as a `human_intervention` subtype. The Day-8 prompt, written
after D-028 landed, instead asks the schema to capture D-028 *inside*
`human_intervention`. Two readings reconcile:

1. **Prompt overrides memo** (what I did). The Day-8 prompt is the
   later, more specific instruction. Track A consolidates all
   "human-took-action" events under one type, which is easier to
   filter in `inspect_run`. Drawback: the discriminator surface is
   broader and we lean on `if/then` for the new shape.
2. **Add a third `oneOf` member `gate_clear`.** Faithful to the memo;
   the new shape stands alone with its own additionalProperties:false.
   Drawback: two event types overlap in intent ("human did a thing")
   and downstream consumers need to remember both.

If Track A prefers option 2, the migration is one extra `oneOf` member
plus a re-targeted test file; the `human_intervention` branch would
revert to its Day-3.5 shape. The draft as-is implements option 1.

### context_hash semantics for gate_clear

The Day-3.5 schema's `context_hash` is documented as "hash of the task
state at the moment of intervention; enables N generated / M survived
/ K edits accounting in the preprint." For a `gate_clear` event the
natural interpretation is: hash of the gate's pending-state snapshot
at clearance time (so an auditor can reconstruct what was on the table
when the decision landed). The schema doesn't enforce a particular
hash content; Track A's wrapper emission code defines it.

## P3 / `calibration_entry` — Day-41 auto-evaluator shape

Two calibration shapes co-exist under one `event_type`:

| `calibration_type` | Required fields | Use case |
|---|---|---|
| absent or `"human_range_check"` | metric_name + pre_experiment_expected_range + post_experiment_observed + within_range + human_attestation (the Day-3.5 shape) | Day-7-style: human pre-commits a range; experiment runs; within_range computed. |
| `"auto_evaluator"` | kappa + spearman + threshold + ground_truth_ref | Day-41 auto-evaluator calibration. κ > 0.6 is the documented success bar (PHASE_1_ROADMAP.md §5.1). |

`human_attestation` is OPTIONAL in the auto_evaluator branch (still
allowed; the human attests the κ/threshold decision in practice) and
REQUIRED in the human_range_check branch (unchanged).

The branch selection happens via JSON-Schema `if/then/else` on
`calibration_type`. The top-level `required` list shrinks to
`[event_type, timestamp, experiment_id]`; the branch-specific
requirements take over. This is the only place where the Day-3.5
schema's `required` list is weakened. The behavioral guarantee is
preserved: any record valid under the Day-3.5 schema is also valid
here (verified by the legacy happy-path test).

### Why not a third `oneOf` member `evaluator_calibration`?

Same trade-off as the gate_clear case. The Day-8 prompt explicitly
named `calibration_entry` for both shapes, and PHASE_1_ROADMAP.md uses
the word "calibration" for both Day-7 and Day-41. Keeping them under
one event_type means `inspect_run --by-event-type` shows the
calibration timeline at once. If Track A prefers separating them, it's
a one-member-add migration.

## P2 / `retrieval_context` — Week-2 critic + meta-review provenance

Per `week2_plan_seed.md` #4 (critic) and #5 (meta-review), Week 2
consumers need richer retrieval provenance than the Day-3.5 four-field
shape provides:

| Need | New optional field |
|---|---|
| Critic's "why was this retrieved?" reasoning trace | `score` (BGE-M3 similarity, [0, 1]) |
| Meta-review's per-collection dedup against last-3 hypotheses | `collection` (ChromaDB collection name) |
| inspect_run attribution: "every chunk the critic cited" | `retrieved_for` (closed enum: generator / critic / meta_review / novelty_eval / summarize_paper) |
| Reproducibility hedge against embedder swap | `embedder_version` (e.g. `bge-m3@2024-01-30`) |

All four are OPTIONAL inner fields. The required four (doc_id +
content_hash + chunk_offset + chunk_length) are unchanged. Legacy
4-field items still validate (verified by
`LegacyRecordsStillValidateTest` and the `logs/day2.jsonl`
revalidation pass).

### Why `retrieved_for` is a closed enum

If Track A adds a new consumer (e.g. an `auto_evaluator` worker on
Day 41 that retrieves its own context), the schema must bump. The
closed enum prevents a downstream tool from silently writing
unattributable retrievals into the log — every consumer is explicit.
The downside is a small schema-version-bump treadmill; the upside is
that `tests.test_calls_schema_proposed.UnknownInnerFieldsStillRejectedTest`
catches accidental field additions.

If Track A would rather accept any string, drop the enum to
`{"type": "string", "minLength": 1}` and remove
`test_retrieved_for_unknown_value_fails` from the test file.

## Files NOT touched

- No edit to `schema/calls.jsonl.schema.json` or
  `schema/events.jsonl.schema.json` (the Day-3.5 contract). Track A
  promotes `schema/proposed/*.json` at the Day-42 lock by overwriting
  the canonical files (and updating `$id` URLs accordingly).
- No edit to `tests/test_events_schema.py` or
  `tests/test_calls_schema_retrieval_context.py` (the Day-3.5 test
  suites). They keep passing against the unchanged canonical schemas.
- No edit to `agent_wrapper/`, `run_state/`, `logs/`, `bench/`,
  `chroma_db/`, `CLAUDE.md`, `plan.yaml`, or any Track A/C/D file.
- No emission code. Track A wires `gate_clear` events when a human
  clears a hard-gate, and `auto_evaluator` calibration events when
  Day-41 runs. This PR ships only the schema + tests.

## Forward hooks (NOT in this PR)

1. **Wrapper emission for `gate_clear`.** When a human clears a
   hard-gate (e.g. by attesting in `human_gates_pending`), the
   wrapper or the state-file rectifier should emit a
   `human_intervention` event with subtype=='gate_clear' and the
   D-NNN cross-reference. D-028 is a retroactive case; future
   clearances should land the event live.
2. **Wrapper emission for `auto_evaluator` calibration.** Day-41's
   calibration script writes the κ/Spearman/threshold to the run
   log via a `calibration_entry` event with
   calibration_type=='auto_evaluator'.
3. **Critic + meta-review retrieval emission.** Workers built on Days
   39–40 should populate `score`, `collection`, `retrieved_for`,
   and `embedder_version` on every chunk in their `retrieval_context`.
4. **`$id` URL update on lock.** When Track A promotes
   `schema/proposed/*.json` to canonical, the `$id` URLs change from
   `/schema/proposed/...` to `/schema/...`. Tests reference the
   schema by file path so this rename is mechanical.

## Open questions for Track A review

1. **Combine gate_clear into human_intervention, or split into a
   third oneOf member?** Draft does the former; see "Design tension"
   above.
2. **Combine auto_evaluator into calibration_entry, or split into a
   third oneOf member?** Draft does the former; same trade-off.
3. **`decision_id` pattern — keep `^D-\d{3}$` strict?** If D-NNN
   numbering ever exceeds 999 (unlikely in Phase 1, possible in
   Phase 2+), the pattern needs to allow 4+ digits. Easy migration.
4. **`retrieved_for` enum — closed or open?** Draft is closed; see
   §"P2 — Why retrieved_for is a closed enum" for the trade-off.
5. **`embedder_version` format convention.** Draft uses
   `<model>@<version>` (e.g. `bge-m3@2024-01-30`). Track A may prefer
   a pinned hash or a different separator; the schema only requires
   `minLength: 1`.
