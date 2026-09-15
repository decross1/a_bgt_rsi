# Primary model comparison — 2026-09-15

**Current decision: retain the incumbent for whole-lab production; continue Flash confirmation.**

The optimized Mia MTP3 Flash configuration completed the same frozen 126 development cells as the resident Gemma/Qwen role bundle. Both windows closed with exact service restoration, and independent raw-response and original-grade replay passed for all 126 cells in each arm. These compare deployable bundles; differences cannot be attributed to model weights alone.

| Family | Resident passed | Flash passed | Resident task seconds | Flash task seconds |
|---|---:|---:|---:|---:|
| objective | 14/24 | 17/24 | 621.2 | 298.6 |
| topic | 39/48 | 48/48 | 116.0 | 321.8 |
| context | 4/4 | 4/4 | 14.1 | 30.3 |
| portfolio | 16/16 | 14/16 | 367.2 | 219.0 |
| diversity | 2/10 | 3/10 | 21.3 | 228.3 |
| role_effort | 12/18 | 15/18 | 572.1 | 236.4 |
| historical | 0/6 | 0/6 | 158.5 | 165.6 |

| Whole panel | Resident | Flash |
|---|---:|---:|
| Correct cells | 87 | 101 |
| Timeouts | 1 | 0 |
| Evaluation minutes, including failures | 31.18 | 25.00 |
| Correct cells per evaluation hour | 167.4 | 242.4 |

The Flash portfolio loss is **12.5 percentage points**, exceeding the preregistered ten-point family regression allowance. The overall score does not override this failure. Fresh coding/science and dedicated context evaluations are still pending, and no production replacement is authorized by this publication.

The exact paired outcomes are 82 both-pass, 19 Flash-only, 5 resident-only, and 20 neither. Repeated policies and placements share underlying tasks; these are descriptive development results, not 126 independent scientific observations or evidence of general benchmark superiority.

## Timing and memory

Flash evaluation took 1,500.14 seconds; its entire supervised window took about 2,908.83 seconds. Prelaunch verification took about 4m09s, container start to readiness about 11m12s, and exact restoration about 6m48s. Probe, quiescing and other overhead are separate. The resident comparison started with warm servers, so this is not a matched cold-start experiment. These measurements do not establish TTFT or raw decode tokens/second.

Minimum available physical memory was 30.30 GiB for the Flash window and 37.41 GiB for the resident window. Both cleared the preferred 20 GiB margin. Flash used the qualified reduced-47K-vocabulary, MTP3, V2-optimized 32K Mia configuration. The canaries passed; lossless speculation remains unestablished without the repeated MTP0 parity control.

## Coding and policy limitations

The two portfolio losses are the same delegation-coding task under two registered conditions. Flash returned valid JSON but called `list.sort()`, which the explicit source API contract excludes (`sorted()` is permitted). The grader rejected both before behavioral execution; these are source-contract failures, and algorithmic correctness was not tested. They are not two independent algorithm failures. Resident passed the behavioral cases in both cells.

Original historical repair scores remain 0/6 for both arms. Under the separately preregistered fence/terminal-newline diagnostic, Flash repairs one historical case; resident repairs none. The diagnostic never replaces the original score. The normalization aggregate also includes already-passing portfolio coding: Flash two and resident four. It must not be described as three or four newly rescued historical repairs.

The experimental resident bundle is not an unqualified best incumbent. Relative to the prior C0 bundle it improved objective and portfolio tasks, but regressed on topic planning and some role tasks. A hybrid assembled from the best observed roles has not been tested. Retain those known alternatives when designing the next prospective comparison.

## Context limitations

Configured server capacities were Gemma 32,768, Qwen 16,384, and Flash 32,768. Maximum measured primary-panel input tokens were respectively 18,874, 290, and 17,386. The four primary context cells therefore do not validate Qwen at 16K or either model near full 32K input. Separate registered context panels reserve output headroom and test 8K/16K/32K capacity bands where supported.

## Provenance

- Pair: `qfn-ab-lab-primary-20260915-b`.
- Corrected plan raw SHA-256: `9616a6f5b982585570fb1bcd6de76aa754fcb722225f90ecded3d737838ec0b8`.
- Published report raw SHA-256: `efcbb9e1fdcc878e01af92eb3951535916fdc55e8db95b0970d0e5aa74278a3b`.
- Flash run raw SHA-256: `68193bdb172405ea07022b5e8f25de19a4a384825717dc6dc597f0d06eb28667`.
- Resident run raw SHA-256: `e3d0d6f0d6612ce7617aa06999dfb7813b9e29c394f5358084db3f4b81a641a8`.
- Local immutable publication: `lab-eight-hour/evaluation-pairs/qfn-ab-lab-primary-20260915-b/index.json` under the dated v2 artifact root.
- Selection thresholds: [PREREGISTRATION.md](PREREGISTRATION.md); the unissued first plan was corrected before model calls as recorded in [PRE_EXECUTION_CORRECTION.md](PRE_EXECUTION_CORRECTION.md).
