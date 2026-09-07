# Ladder collection classification summaries

## Delivery plan

Scope is this note, `src/components/ladder/ThesisFamilies.tsx`, and
`tests/test_thesis_families.tsx`. The starting public revision is
`69e1ad07e6dca7d6d5907dee35a15be311d004b8`.

The existing disclosure-kind and individual-identity repair is already present
from PR #8. Preserve its counterexamples and behavior. Do not undo a completed
fix to manufacture a fresh red result.

Replace the collection header's classification prose with compact bars and
text values. Both distributions use **all records in that collection**, including
records hidden by filters and negative dispositions. The separate matched-record
count remains the filter result. Segment widths describe proportions of recorded
classifications, never transitions, scientific equivalence, eligibility or success.
Include exact counts and denominators in accessible text, keep unknown values,
and define zero/no-record behavior without division by zero or implied evidence.

Keep association explanations, full source IDs, independent claims, and existing
dossier links. Topic names remain available within the existing expansion; remove
redundant header previews only where that does not remove source distinctions.
Do not change grouping, API readers, backend, runtime, source ledgers or policy.

Before delivery: current actual Firefox screenshots, focused count/filter/unknown/
zero/accessibility regressions, unchanged kind/identity cases, complete frontend
suite, strict TypeScript/build, independent exact-source review, native code-only
PR/merge, then actual served-source and Firefox workflow verification. Preserve all
failed checks and historical timing dispositions. Source work is bounded to one
initial wave plus at most two corrections; no automatic extension or follow-on.

## Status

Plan committed before implementation. Validation and live adoption are pending.
