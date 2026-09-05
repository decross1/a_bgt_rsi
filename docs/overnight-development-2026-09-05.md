# Overnight development: evidence integrity and bounded execution

This branch consolidates the September 5 development work into a code-only
review candidate based on public revision `d1c4a6e3505e53d065c37ab4e100dd3248e83ca8`.
Its 28 source, test and documentation files were frozen at
`b9096ac9f809cd41791c02362f53155b0ca632c3`; this synopsis is an additional
documentation change. Publication of the branch is not runtime activation or
a claim that the combined integration gates have passed.

## What changed and why

| Area | Problem addressed | Implementation |
| --- | --- | --- |
| Claim and attempt identity | Results could be associated with stale or different claims, and a late receipt could displace current evidence. | `workers/claim_binding.py` and `workers/attempt_store.py` add canonical immutable claim identities, transactional attempt/receipt recording, rejection of new stale-claim receipts, exact historical replay, and a unique-current-claim check. |
| Candidate admission | A distinct empty commit could appear admissible with a matching empty diff and green receipts. | `workers/packet_checks.py` validates the observed raw diff, exact scope and receipt identity, and requires an actual validated change. Empty parsing remains valid for abstention; valid mode-only changes remain supported. |
| Evidence audit | A historical result's association with its original claim and execution envelope was difficult to verify. | `tools/claim_binding_audit.py` and `tools/audit_claim_binding.py` provide a read-only audit and content-addressed exposure manifest with reproducible source locators. Classification is about evidence binding, not whether a hypothesis is true. |
| Bounded execution | Generated Python required explicit limits, runtime identity checks and truthful failure evidence. | `tools/contained_python.py` and `tools/contained_worker.py` provide a narrowly scoped finite execution profile with pinned runtime files and restrictions. Parent-side finalization records terminal input/raw evidence after confirmed reap, including timeout and partial-result failures. |
| Local development adapter | A local-model task needed a bounded request/response path with auditable candidate bytes. | `tools/qwen_packet_agent.py` binds a finite Qwen request to its packet, API and source artifacts. The separate generated research worker remains held and is excluded from this branch. |
| Research inventory | Progress views could obscure source identity and trust incorrect declared record counts. | `tools/research_inventory_view.py` renders a read-only evidence inventory, verifies source bytes/hashes and declared line counts, and rejects invalid row references. It does not promote research or authenticate the input producer. |
| Historical validation | Tests compared evolving live inputs with locked historical expectations, making failures misleading. | `tests/pinned_inputs.py`, `tests/conftest.py` and affected tests separate exact historical fixtures from independently captured current inputs. Dispatcher unit tests use explicit inert adapters; original scientific assertions and locked pins remain intact. |
| Improvement protocol model | Queue, lease, retry, acknowledgment and rollback behavior needed falsifiable tests before live adoption. | `bench/self_improve_archive/simulator.py` models fencing, immutable history, negative-result retention and rollback rules without activating a runtime queue or research experiment. |

## Validation evidence and its limits

The overnight work retained failing cases and subsequently demonstrated:

- 296 passes in the committed six-module integrity/packet/archive component
  suite after the empty-candidate and ambiguous-claim-head repairs.
- 160 focused passes for the historical-fixture, renderer and dispatcher-unit
  recovery work. Historical and current-input replay results remain separate.
- 60 passes at the committed finite-profile revision after parent-side receipt
  finalization repairs. An earlier 48-pass/1-fail result remains historical
  evidence of the failure that motivated that repair.

These counts describe different scoped runs and must not be added into a
single full-suite total. Exact file hashes were checked when assembling this
branch. A combined qualified full suite and real integrated smoke remain
outstanding. Existing builder integration tests have real shell, Git and
loopback-server effects requiring appropriate execution isolation.

## Remaining work

- Integrate the pure claim/attempt checks through trusted runtime adapters;
  caller-supplied identities and receipts do not authenticate their producers.
- Preserve the documented trusted-directory and lifecycle assumptions. Static
  path checks do not establish race-free OS confinement or arbitrary-store
  corruption safety.
- Qualify any broader shell/worker use separately from the finite Python
  profile. Component review does not establish a general-purpose sandbox.
- Finish the combined validation, integration smoke and exact-range review
  before merging or adopting the runtime changes.
- Complete the separately retained observability proposals for action errors,
  persistence failures, action/step association and projection freshness.

The separate generated research-progress worker passed 33 fixed examples, but
source review found invalid enum values could raise `TypeError` instead of the
required `ValueError`, and a timestamp with a final newline could be accepted.
That worker is not included or represented as an accepted API implementation.
Private ledgers, model transcripts, research data, operator notes and private
ancestor commits are also excluded from this public range.
