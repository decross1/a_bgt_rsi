# LAB015 UI consumer safety

LAB014 is CLOSED/HOLD after completed whole-range review. Preserve64b5be1 and all old artifacts; extend its owned branch linearly and update PR5. No parallel source branch, force push, merge or live adoption.

P1: FrontierReviews decision controls and submit guard require certified current proposed status plus complete, readable agenda/status integrity. Unknown/invalid/legacy status is view-only; observed ruling status/note remains historical evidence. Revoke an open form when latest integrity becomes unavailable. Preserve legitimate human accept/dismiss behavior; no actual POST/CLI/ledger writes in tests.

P2: Carry structured framing/recorded-label metadata from channel API to Channel render. Legacy or malformed responses must never become trusted Nara/model-voice rows. Keep string message bytes and existing action semantics. Recorded labels are not authenticated identities. This fixes inherited consumer debt, not a newly introduced LAB014 defect.

Exact allowed paths:
- ui/frontend/src/components/FrontierReviews.tsx
- ui/frontend/src/api/channel.ts
- ui/frontend/src/routes/Channel.tsx
- ui/frontend/tests/test_frontier_reviews.tsx
- ui/frontend/tests/test_channel.tsx
- ui/frontend/tests/test_channel_integrity.tsx
- ui/frontend/docs/UI_CONSUMER_SAFETY_20260906_015.md

Accepted2026-09-06T00:36:42+00:00; code target2026-09-06T00:56:42+00:00; terminal2026-09-06T01:06:42+00:00. At most2 repair iterations per issue. Focused/full frontend/typecheck-build commands each <=120s. One optional read-only preparation lane <=8minutes. Backend, Development, pollhub, action writers and all other source frozen. No models, research, raw ledgers, dependencies, services/network/security or sibling repository changes. Fresh HQ whole-range review before merge.


## Implemented behavior and limits

FrontierReviews requires explicit complete, error-free agenda and status reads, a supported effective ruling, an active read, and writer availability before offering a human decision. An open form keeps its draft but its submit button and handler refuse when those conditions disappear. Unknown history never falls back to the proposal's raw status. Observed ruling notes and accepted/dismissed labels remain historical evidence when current status is uncertified.

Channel validates the exact structured-envelope metadata and original row shapes before allowing recorded actor labels, model Markdown or event presentation. Legacy and malformed responses remain neutral raw text, preserving string message bytes. The human label says “human”; recorded labels explicitly are not authenticated identities. Turn/delegate action semantics are unchanged. Deduplication conservatively retains the first observed copy: a later envelope does not retroactively certify an already displayed legacy record. Remounting refetches the current envelope. No controller or pollhub rewrite was made.

## Validation and delivery disposition

New private mocked-fetch regression tests reproduce the unknown-ruling POST and unframed model styling before repair. Tests cover invalid/legacy metadata, open-form integrity/status loss, historical accepted evidence, exact message bytes, malformed records, valid recorded labels and original decision/delegation behavior. All tests use fixtures; no real ruling, model call, backend reader invocation or raw-ledger write occurred.

The full frontend run on September 6, 2026 returned 1,330 passed and one failed: the previously recorded session-thread test “a poll that pushes the session off the live page keeps its turns” expected four turns but observed two (test_session_thread.tsx:809). The failure is retained and was not retried or suppressed. An initial typecheck failure for an unused new test-fixture parameter was corrected. See the delivery handoff for final focused/build results and exact revision hashes.

This candidate is for fresh independent whole-range review on PR5. It is not merged, adopted by the running frontend, or a backend restart. The existing backend remains older; these consumers deliberately show uncertified inputs without decision controls or actor-specific trust. Earlier LAB013/LAB014 source, tests, held results and evidence remain preserved. No scientific or worker acceptance follows from this UI repair.
