# Preregistration — game/science public development portfolio v0

**Prepared:** 2026-09-14, before any model call for this suite
**Suite:** `weekly-upgrade-game-science-public-dev-v0-2026-09-14`
**Evidence class:** public synthetic development regression
**Production authority:** none

## Question and claim boundary

This paired run asks whether reducing Qwen3.8-27B's critic reasoning effort
from the observed `xhigh` control to `medium`, while holding every other
declared inference setting fixed, changes objective completion on a small
game-theory and D-075 development panel.

The eight prompts, grader inputs, code cases and expected behaviors are visible
in the repository. The run can find obvious regressions, exercise the durable
artifact path and motivate a separately preregistered confirmation. It cannot
establish hidden-set generalization, a noninferiority margin, scientific
capability superiority or a production-policy upgrade. The tasks are synthetic
and are not described as historical bugs, private prompts, empirical findings
or external benchmark items.

## Frozen inputs

- Manifest: `experiments/weekly_upgrade_game_science_dev_v0_2026-09-14.json`
- Literal-file SHA-256:
  `a268fbf8eb2535066d97f6e7e15327300f35f0d1df727fdd039059b772bb10cf`
- Canonical configuration SHA-256:
  `1b4dd9097774d14bf0986aaff7727088a59574c636e3059a2a17863a5077a252`
- Portfolio plan SHA-256:
  `59c642437e6f12fbe35be9f9d0b3fe959fb340dc32146e164b1c0be330a30830`
- Manifest loader SHA-256:
  `a86b6e95b15708a6e67aff1c35dbaa599c8317c8b9760ed893d7bbed08d0431e`
- Objective graders SHA-256:
  `c98e08267768afccedf23602ca0cb3571f80af6ccda0d5e6a644076b81004e0b`
- Code sandbox SHA-256:
  `db611859025f05344af0b6c1ce741d94bb3165355624a09995147189c6210983`
- Runner SHA-256:
  `a2f045ed4849bcc18e4b3ccd2333ab7cc82ccd932fccbc1f74d5f9b76c5a78f8`
- Delegation starter SHA-256:
  `7d97e2c8e6da83622ec9a27039c6b78b85fea93ec721b8f1d0e11d01bb1063f1`
- Regret starter SHA-256:
  `89225665945de04d5491da75872b097a0590db311e394e6a82f414e6baf6e267`

The manifest independently freezes every arm and task object. The execution
controller must also bind the committed Git tree and the four execution-source
hashes above before admitting a live call.

## Arms and pairing

Both arms use backend `vllm-qwen`, model
`qwen3.8-27b-nvfp4-mtp`, temperature `0.2`, top-p `0.95`, seed `0`, and
the task-specific output/deadline cap.

- **A / control:** profile `critic_current`, reasoning effort `xhigh`.
- **B / candidate:** profile `critic_medium`, reasoning effort `medium`.

The 16 calls are serial. Task order is frozen in the manifest. Within each
successive task the arm order alternates `AB`, `BA`, so the complete order is
`AB BA AB BA AB BA AB BA`. No failed, missing, malformed, timed-out,
runtime-drifted or inconclusive-grader cell may be removed from the denominator.

## Tasks and objective grading

The panel has four scientific/formal tasks, two evidence tasks and two coding
tasks. Structured outputs use exact schemas and independently recomputed
numeric, categorical and citation oracles. Completion JSON rejects duplicate
keys and non-finite constants.

Generated source must pass the restrictive AST gate. Each declared behavioral
case runs in a fresh, non-networked bubblewrap process. The child receives the
function source and case arguments, never the expected result. The trusted
parent compares the bounded observation with the manifest oracle and records
content hashes. There is no host-execution fallback.

The required sandbox identity is frozen in the manifest:

- bubblewrap 0.9.0 at `/usr/bin/bwrap`, SHA-256
  `ae27935781511400c65ebcc0b4669775d602f46251b8707c947a1ac1b160c1c8`;
- Python 3.12.3 at `/usr/bin/python3.12`, SHA-256
  `6242e0e8650d7dbdebbc25e08bf4c9359ddaf65f54fcae0e57fa99395fa5357a`.

A missing or different isolation runtime makes code grading inconclusive and
prevents a complete trusted receipt.

## Resource and safety limits

- 16 planned local-model calls, strictly serial.
- Task request ceilings: 120 seconds structured; 180 seconds code.
- Output cap: 6,144 tokens for every task, including reasoning tokens where
  the backend accounts for them in the generation cap.
- Evaluator payload ceiling: 2,280 seconds.
- Dispatcher reservation: 2,310 charged Spark GPU-seconds.
- Aggregate isolated-grading ceiling: 120 seconds.
- Raw completion ceiling: 131,072 bytes per attempt.
- No coordinator action dispatch, production-ledger mutation, service change,
  scheduler activation or frontier API call.

The canonical weekly budget controller must reserve the full 2,310 seconds
before a live run and charge the trusted postflight receipt under the shared
7,200-second weekly Spark cap. The panel defers whole if it cannot fit; it does
not drop difficult tasks or one arm.

## Outcomes and interpretation

Report exact pass counts and paired A/B differences separately for scientific,
evidence and coding families, plus every failure code, failure-inclusive elapsed
time and Correct Task Throughput. Preserve per-case code receipts. Do not merge
families into a promotion score.

With eight visible tasks and one seed, every A/B difference is descriptive.
No result from this run alone authorizes promotion. A candidate advantage is a
trigger for a separately frozen repeat or held-out panel. Any runtime identity
drift, missing durable call, source-hash drift, sandbox mismatch, unbounded
artifact, or irreproducible objective grade invalidates the relevant receipt.

## Offline commands

Read-only plan:

```bash
python3 -m bench.weekly_upgrade_portfolio.runner \
  --plan \
  --manifest experiments/weekly_upgrade_game_science_dev_v0_2026-09-14.json
```

The live form requires an admitted dispatcher reservation and a fresh external
output directory; this preregistration does not itself authorize invoking it.
