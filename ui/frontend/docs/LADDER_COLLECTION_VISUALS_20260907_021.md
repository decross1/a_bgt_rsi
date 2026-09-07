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

## Implemented behavior

Each collection now has two compact classification bars outside its disclosure
button. Their visible caption says “All N records”; the header's “shown of total”
count remains the filter result. Text legends preserve each nonzero count without
requiring color. Accessible image descriptions include every known category and
its exact numerator/denominator, including zero categories; the disclosure also
references the summary. The hover title repeats these values. These are discrete
stage/status partitions, not cumulative stage achievement or progress indicators.

Segment widths use unrounded count/total ratios, with no minimum width assigned
to rare categories. Empty models retain the explicit no-matching-records state.
Missing/invalid stages remain unknown. The existing status display preserves
unknown values and explicitly labelled unrecognized producer values; this change
does not normalize or discard those existing count categories. Expanded records
retain their original producer labels and negative evidence.

Curated collections show their number of topics; the full topic names and claims
remain under expansion. A single exact-topic heading is not repeated inside the
same expanded collection. Disclosure names, identities, grouping, filters,
selection and dossier actions keep their existing semantics.

The source regression set covers filtered/all-record denominators, discrete
stages, missing/unrecognized values, zero categories, empty models, thirds,
100:1 proportions, a killed L4 record, accessible description and same-title
disclosures. Browser checks distinguish a private candidate preview from actual
served-source adoption. Exact validation/review/delivery receipts belong to the
owner's dated report; this portable note is not a live deployment status feed.
