# Plan correction before the first benchmark request

Recorded 2026-09-15 at 17:08 UTC. The original `a` resident window failed to
acquire the research lease while Nara was executing iteration003. Its durable
state has no captured initial runtime, no watchdog and no attempted Nara stop;
it created no evaluator output and issued **zero benchmark model requests**.
The corresponding Flash window was never launched. Both remain in the archive.

Independent source review found that the unchanged role-effort adapter uses
the original `critic_current` identifier to mean xhigh. Renaming that identifier
had also incorrectly mapped the conditional evidence/execution retry to medium
or off. Correct the unissued plan to retain those semantic IDs and route all
resident role-effort arms through Qwen, including the medium-to-xhigh retry.
Regression fixtures execute the unchanged adapter and assert the second request's
resolved effort. Historical adapters, graders and scores remain unchanged.

The corrected **`b` pair** keeps126 tasks,145 planned calls, original primary
grades, the9,740-second worst per-arm call ceiling and the existing predeclared
decision thresholds. Each arm has a6,000-second harness budget; resident wall
is6,660seconds and Flash wall9,000seconds, each reserving600seconds for recovery.
Incomplete panels cannot qualify for a replacement recommendation.

| Active immutable plan | Raw SHA-256 |
| --- | --- |
| `primary-model-comparison-v2.plan.json` | `9616a6f5b982585570fb1bcd6de76aa754fcb722225f90ecded3d737838ec0b8` |
| `context-model-comparison-v3.plan.json` | `3c48d52f8430bcb9eb32b415c1fbdc4dcd93cb4c47310368e369a091d1a2e542` |
| `fresh-model-comparison-v2.plan.json` | `19b28a34a3e75442f74a809e61b3b82d4d42a6e960aaf0bef6cfda6dbebf6b30` |

Context and fresh task content/policies are unchanged; their revisions bind the
corrected shared source dependency. All superseded plan bytes and the original
policy source are retained under the local `lab-eight-hour/preexecution-revisions`
artifact directory. This correction used source inspection and tests, with no
observed benchmark outcomes from either arm.

The successor research campaign is active separately. Its17:00 scheduled cycle
recorded iteration002 with an undecidable critic verdict. A daemon research
iteration then acquired the same canonical lease. A temporary operator-created
dispatch pause lets that current iteration finish and prevents another dispatch
from racing model measurement. Only the exact recorded pause bytes may be
removed; a human-created or modified pause is preserved.
