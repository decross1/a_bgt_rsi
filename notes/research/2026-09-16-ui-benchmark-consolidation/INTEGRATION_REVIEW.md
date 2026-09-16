# Integration review — in progress

This review applies the framework code-review checklist to the UI consolidation
and new benchmark program. It is an engineering review, not a scientific result.
The execution source and first registration have been published before inference;
the UI/backend delivery is being finalized. No resident stable-suite inference
has been issued.

## Blocking findings corrected before publication

1. **The dossier repeated its opening overview.** The retired TutorPanel and
   duplicated fetch were removed. One source-bound PipelineJourney now owns the
   question, observed outcome, recorded criticism and next step.
2. **An ID prefix could expose a verdict for a record absent from the queue.**
   Iteration dossiers now require a real typed gate-verdict item before showing
   verdict/defer controls. A preserved record remains readable. The coordinator
   now matches the inbox's experiment-stage eligibility rule; literature-only
   `gate_status=pending` no longer becomes an owed human verdict.
3. **Historical benchmark scores could authenticate themselves.** The new read
   model requires a source-controlled comparison registration with ordered
   reference/candidate arms, frozen manifest and source hashes, and an exact
   external lifecycle/replay/admission chain. Both copies of admission-gate
   receipts are checked. The GET path never runs graders or models.
4. **Reference/candidate direction was inferred from execution order.** Paired
   deltas now use preregistered roles. Executing a candidate first cannot invert
   the reported improvement. Different comparison cohorts never form a pair.
5. **Some new tasks expected undisclosed answer vocabulary.** Evidence reason
   codes, final artifact keys and literal options are now specified by the task
   prompts. Numeric precision is also explicit. These corrections preceded
   publication and all model execution; no completed score was changed.
6. **Draft system-game objectives were ambiguous.** The strategic canary now
   states an own-payoff objective, derives regret with trusted CPU arithmetic,
   and evaluates proper scoring against an ex ante belief. Separate mechanisms
   retain separate denominators and utility units.

## Interpretation constraints retained

- The 18 capability units and three actor–tool–critic micro-workflows are a small
  public regression canary. They do not establish broad scientific ability,
  repository engineering capability, or production research success.
- The Flash cap-closure attempt failed its registered runtime startup gate with
  no evaluator admission and zero model calls. It is not a scored model defeat.
- Historical fixtures, policies, source bundles and published scores remain in
  their original study lineages. They are not rebased onto this release.
- Missing, unissued or withheld attempts have no quality score. The proposed
  application agenda has not produced a market finding or authorized a trade.

## Additional integration checks

The complete core suite passed 3,594 tests and 41 subtests with five skips. The
frontend passed 1,598 tests, type checking and build. The final backend suite passed
1,221 tests after strict agenda-schema and comparison-bound live-status
hardening. An old lifecycle directory touched after a newer registration cannot
replace that comparison’s live status.

## Remaining acceptance work

Source review, tests and exact definition/arm/lifecycle publication are complete.
Next: merge and deploy the UI/backend, run the resident reference, verify replay
and restoration admission, and complete deployed browser checks. Runtime changes after
publication require a new manifest or release as their causal effect warrants.
