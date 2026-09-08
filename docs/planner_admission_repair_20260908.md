# Planner escalation admission repair

Purpose: reject unsupported bubble escalation kinds and human-resolution menus at planning admission, before handlers run. Reuse the existing A/B/C taxonomy and six literal resolution outcomes; do not alias finding_review, finding_id or promote_findings into other operations.

Scope: orchestrator/coordinator_actions.py, orchestrator/coordinator.py, tests/test_coordinator_actions.py, tests/test_coordinator_escalation.py, and this plan. Preserve all UI, schemas, business ledgers, runtime roles, budgets and persistence/lifecycle behavior. Public source base is a20f090f9b6767e6573279d006bf3adeb559c694. Private canonical ancestry is excluded from publication.

Implementation: move the existing admissibility definition to the pure action module, expose it through the planner menu, and reuse it for admission and defensive handler checks. Preserve legitimate legacy omission, A/B/C semantics and all six resolutions. Empty or malformed input must not become a fabricated escalation. Keep the bounded rejection/replan opportunity.

Validation: reproduce unsupported kind and kind-only invalid-menu cases before repair. Test legitimate A/B/C, all six resolutions, legacy requests and shared nonempty-payload rules. An isolated injected driver must show invalid plans reach no handler, action charge or bubble persistence. Preserve attempted execution versus success; receipt persistence is a separately scoped future task. Pin the unchanged escalation schema. Run the complete relevant coordinator suites with qualified private inputs and no network/models/subprocess or live artifacts.

Delivery: one initial implementation plus one evidence-driven correction, source deadline 2026-09-08T07:57:06Z, terminal 08:57:06Z. Freeze exact candidate and public base, independent whole-range source/effect review, parent reconciliation, native source-only PR/merge. Qualify cron fresh-interpreter reads and persistent imported modules before canonical adoption; hold adoption if effects are unqualified. Never trigger a live cycle or restart services for validation. Preserve failed checks and recover through retained candidate history.
