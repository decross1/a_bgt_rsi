# Post-hoc audit of Qwen effort pilot seed 17 graders

**Date:** 2026-09-14 UTC
**Status:** **POST-HOC DIAGNOSTIC ONLY**
**Artifact:** `qwen-effort-seed-17/evaluation/run.json`
**Artifact SHA-256:** `06cbcbeb59a0178bee799a5f6e81a3a8b84f2d7c06a4cc94aa5237445d29b2bb`

## Verdict

The seed-17 artifact contains five non-passing cells. Their diagnostic
classification is:

| Task / arm | Frozen result | Post-hoc audit |
| --- | --- | --- |
| `critic_fatal_circular` / B | incorrect answer | **Justified substantive failure** |
| `critic_proceed_theorem` / A | timeout | **Justified failure-inclusive timeout; no answer to grade** |
| `critic_proceed_theorem` / B | incorrect answer | **Exact-code contract failure, but substantive scientific pass** |
| `evidence_attrition` / A | incorrect answer | **Likely fixture/grader false negative** |
| `evidence_attrition` / B | incorrect answer | **Likely fixture/grader false negative** |

The frozen official result remains **A 4/6 and B 3/6**, with run status
`incomplete_transport`. Nothing in this audit changes the artifact, grader,
remaining seed runs, or locked decision rule.

For diagnosis only, a semantic reading would count **A 5/6 and B 5/6**:
A still fails the timed-out theorem cell; B still fails the circular-claim
cell. These post-hoc counts must not be substituted into the preregistered
three-seed summary. They show that seed 17 supplies no clear scientific-quality
advantage to either policy after separating schema compliance from substantive
correctness.

No additional model calls were made. This report contains no raw completion,
prompt, reasoning trace, or tool payload.

## Audit basis

The audit compared:

- immutable seed-17 manifest SHA-256
  `88aacc3868dc116f30ba6c9769834886a1ec26071967f7cf8ae5d7413a5b71aa`;
- manifest configuration SHA-256
  `aac9f721c1a42b8b84fbb3bda26ddda5ec88ce1bc009cdd5974dc73b0bebd635`;
- measurement source commit
  `ace866c91859c4234632c0806cf77700121dc40f`;
- frozen grader implementation hashes recorded inside `run.json`;
- `calls.A.jsonl` SHA-256
  `c20bdbfdd1037b5b1c94030caad1d971f39744e5fb739e44a8e27afb0137732a`;
- `calls.B.jsonl` SHA-256
  `163ef5cf615122424f247677cd00a9d5f1446ff9fad1b6f4c0e595d9dd7fa2d0`.

The call records agree with the completed cells in `run.json`. The xhigh theorem
timeout has no completed call record, while the two-turn tool task accounts for
the extra call-log row in each arm. Only the strict answer fields needed to
classify the disputed cells were examined.

The frozen grader is intentionally exact. `critic_classification` requires the
expected verdict and exact reason code. `evidence_attribution` requires the
exact answer code plus the exact citation set. This is valid for measuring
structured-output compliance, but its single pass bit currently conflates
schema fidelity with scientific or evidentiary correctness.

## Cell-level findings

### `critic_fatal_circular` / B — grade justified

The response recognized the circular-definition defect but paired that reason
with a proceed verdict. Those two fields conflict. A claim that defines “more
cooperative” solely by the outcome it claims to explain is circular and offers
no independent explanatory or testable variable. The frozen fatal verdict is
therefore substantively correct, and the returned proceed verdict is not.

This is neither a keyword false negative nor a harmless alias. Keep the cell as
a scientific and contract failure.

### `critic_proceed_theorem` / A — timeout justified

Arm A exceeded the fixed 180-second request deadline. There is no completion in
the call ledger to reinterpret. The pilot explicitly keeps timeouts in the
denominator, so this remains a failure-inclusive operational result. It cannot
be relabeled through grading review.

### `critic_proceed_theorem` / B — scientific pass, exact-code failure

The underlying game-theory claim is correct. Under grim trigger, cooperation
is sustainable when

```text
R / (1 - delta) >= T + delta * P / (1 - delta),
```

or equivalently `delta >= (T - R) / (T - P)`. With the frozen payoffs this
threshold is `0.5`; the supplied `delta=0.9` clears it.

Arm B returned the correct proceed verdict and a semantically equivalent
“consistent and testable” rationale, but omitted the frozen code's theorem
prefix. The exact equality grader therefore behaved as implemented. Its reason
text — “lacks the expected substantive reason” — overstates the defect: the
defect is vocabulary/schema fidelity, not theorem understanding.

Keep the official cell failed for this pilot because the response violated the
frozen exact-code contract. Record it separately as a substantive scientific
pass when diagnosing whether medium effort understood the task.

### `evidence_attrition` / A and B — likely grader false negatives

Both arms independently selected the manifest's explicit
“insufficient outcome data” alternative and cited both required evidence
documents exactly. That answer is supported by the packet:

- observed final-round means cover only retained groups;
- dropout occurs only in the punishment arm;
- dropout is associated with low interim contribution;
- the missing final outcomes are unknown.

The complete-case difference therefore does not identify the randomized
treatment's final-round causal effect without assumptions about those missing
outcomes. “Causal increase not identified” and “insufficient outcome data” are
both true descriptions of the same defect. The prompt presents them as separate
answer codes without defining a precedence rule or making them mutually
exclusive.

The strict grader rejected the latter only because its frozen expected code is
the former. Calling the returned answer “not supported by the supplied packet”
is inaccurate. This is a high-confidence fixture taxonomy ambiguity and a
likely false negative for evidentiary quality in both arms.

The symmetry matters: both profiles produced the same disputed answer and the
same complete citation set. The cell supplies no seed-17 evidence favoring one
effort policy over the other.

## Official and diagnostic counts

### Frozen pilot accounting

| Arm | Passed | Incorrect answer | Timeout | Attempted |
| --- | ---: | ---: | ---: | ---: |
| A — current/xhigh | 4 | 1 | 1 | 6 |
| B — medium | 3 | 3 | 0 | 6 |

Frozen paired categories are three both-pass, one A-only, zero B-only, and two
both-not-passed. One pair is incomplete because of the arm-A timeout. These are
the only counts the existing repeat summarizer may consume.

### Post-hoc semantic diagnostic

| Arm | Substantively correct completed answers | Operational timeout | Substantive failure |
| --- | ---: | ---: | ---: |
| A — current/xhigh | 5 | 1 | 0 |
| B — medium | 5 | 0 | 1 |

This second table is an audit aid. It is not a corrected run, an alternative
promotion statistic, or permission to override the preregistration.

## Implication for the locked pilot

Continue seeds 29 and 43 against the unchanged manifest and unchanged graders.
Changing the task or accepting aliases now would make the repetitions
non-comparable and would tune the evaluation after seeing outcomes.

When the exact three-seed run completes:

1. publish the frozen failure-inclusive result exactly as registered;
2. attach this audit as a limitation;
3. do not apply the post-hoc semantic counts to the locked promotion rule;
4. do not claim that seed-17's three B incorrect-answer rows are three
   scientific reasoning failures;
5. if the locked result is near a decision boundary, treat the ambiguity as a
   reason for a new preregistered panel, not a reason to flip this result.

The run's `incomplete_transport` status also prevents seed 17 by itself from
supporting a gain claim, regardless of grading interpretation.

## Future grader repair — separate version only

Do not change `fixtures.json`, `runner.py`, or the current manifests for this
pilot. A future v2 panel should make these repairs before any calls:

1. **Separate correctness dimensions.** Record strict JSON/schema compliance,
   canonical-label compliance, and substantive correctness independently. A
   single bit should not describe a correct theorem judgment with a code alias
   as scientifically wrong.
2. **Use explicit JSON-schema enums.** List complete allowed strings rather
   than encoding alternatives in one `_or_` placeholder. State that the value
   must match one enum member exactly.
3. **Make attrition labels mutually exclusive.** A cleaner answer contract is
   a direct identification verdict plus a reason code, for example
   `identified: false` and `reason_code: differential_attrition_missing_outcomes`.
   Reserve a distinct “no outcome data” code for packets containing no outcome
   observations at all.
4. **Improve failure reasons.** Report `noncanonical_reason_code` separately
   from `wrong_substantive_reason`, and `ambiguous_supported_answer` separately
   from `unsupported_answer`.
5. **Freeze new tasks and hashes before use.** Validate v2 on authored boundary
   cases, then run it only on fresh seeds/tasks. Never merge v2 results into the
   locked v1 three-seed estimate.

## Source locations

- Private run metadata inspected in place:
  `/home/decross1/projects/a_bgt_rsi_upgrade_runs/2026-W38/qwen-effort-seed-17/evaluation/`
- Frozen measurement source:
  `/home/decross1/projects/a_bgt_rsi_worktrees/weekly-upgrade-measurement-20260914`
- Grader implementation at source commit:
  [`bench/weekly_upgrade_eval/runner.py`](../../../bench/weekly_upgrade_eval/runner.py)
- Frozen fixture definitions:
  [`bench/weekly_upgrade_eval/fixtures.json`](../../../bench/weekly_upgrade_eval/fixtures.json)
- Pilot contract:
  [`experiments/PREREG_weekly_qwen_effort_pilot_2026-09-14.md`](../../../experiments/PREREG_weekly_qwen_effort_pilot_2026-09-14.md)

The relative links above point at the delivery branch for review convenience;
the audit itself used the recorded `ace866c` measurement worktree and the
artifact-embedded hashes.
