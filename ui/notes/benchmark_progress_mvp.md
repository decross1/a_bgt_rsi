# Benchmark Progress MVP

Prepared 2026-09-14. The owner requested concurrent implementation, adversarial
review, and live deployment in the existing Spark UI. This is a read-only
observation surface; it does not authorize a benchmark run or a model promotion.

## User outcome

Answer: what was reviewed this week, what was actually measured, and what
evidence supports a change in scientific or coding capability?

The page at `/benchmarks` is reachable through Operations and the command
palette. It uses the existing Atlas typography, spacing, surfaces, status colors,
and light/dark themes. It links back to Research for evidence about actual
scientific claims, which is separate from agent capability.

## Initial scope

- An explicit recorded automation mode and source timestamp.
- Week selection, review activity, and the shared GPU allowance.
- Benchmark families with visible arm scores, task denominators, completion,
  timeouts, and semantic verdicts where the source supports them.
- Evidence expansion with configuration and artifact identities.
- Comparable history only when suite, grading, and configuration contracts
  support it. A single measured week is a baseline, not a rising trend.
- Missing, incomplete, invalid, and stale evidence remain visible. No
  measurement is never displayed as a score of zero.
- Refresh and filtering are functional; no control starts a trial or deploys a
  policy. The activated weekly job remains review-only.

## Data contract

`GET /api/weekly_upgrade/progress` projects bounded, local artifacts. It reads
canonical weekly trial journals, operator summaries, budget records, cycle
reports, and activation receipts. It does not call frontier/local models or
modify those files. Raw prompts, responses, hidden grading answers, credentials,
and arbitrary file downloads are outside this interface.

Trial completion and scientific success are separate. Hash consistency proves
that artifacts belong together, not that operator annotations are ground truth.
Warnings name missing, malformed, or mismatched evidence without presenting it
as a verified result. Cross-panel averages are not a performance score.

## Parallel ownership

- Backend agent: new projection and backend tests.
- Frontend agent: new route, scoped styling, API/types, and component tests.
- Independent adversary: evidence fidelity, bounds, comparison logic, and UX.
- Integrator: existing API/router/navigation wiring, preview/browser checks,
  delivery, canonical adoption, and live verification.

## Acceptance

1. Actual W38 artifacts appear without hardcoded scores: eight terminal trials,
   negative/incomplete outcomes, recorded review-only activation, and the
   correctly attributed shared budget.
2. Multiple-week fixtures demonstrate selection and honest comparability;
   missing weeks do not fabricate measurements.
3. Invalid/missing data degrades to a useful warning without losing unrelated
   valid evidence. Network failure cannot leave stale data looking fresh.
4. Desktop/mobile layout, keyboard navigation, filtering, details, and refresh
   work. Loading and failure states are legible.
5. Relevant tests and production build pass; adversarial blockers are resolved.
6. The reviewed public change is adopted without publishing private history or
   overwriting unrelated work. Only the necessary UI service is reloaded.
7. The live route and API are browser-verified and the deployment has a durable
   receipt. The user receives a working URL for further iteration.

Actual deployment identities and verification results are recorded outside the
public source commit, in the canonical weekly-upgrade state and the sibling
`benchmark_progress_mvp_artifacts/2026-09-14/` directory.
