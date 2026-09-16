# Flash-Next qualification closed — retain the resident pair

**Decision, 2026-09-16:** retain Gemma at 32K and Qwen at 16K. Keep the tested
Mia Flash-Next configuration as a candidate for a future reviewed qualification,
not the production lab model. The next regular review is Sunday 05:30 UTC.

Flash showed useful strengths in the earlier admitted development panels. It
also regressed on a portfolio gate, did not resolve the strict repair contract,
and has now hit the fixed startup pageout guard on both final cap attempts.
The last attempt generated **no benchmark responses**. Its failure cannot be
counted as incorrect science or used to revise the earlier admitted scores.

## Measured tradeoffs

These are separate historical panels, not one newly pooled benchmark. The
126-cell development panel contains 53 underlying task lineages; its repeated
cells are not 126 independent problems. The resident comparator is the declared
role bundle in that study, not a claim about every current production call.

| Evidence | Resident configuration | Mia Flash-Next | Interpretation |
| --- | ---: | ---: | --- |
| Objective development cells | 14/24 | 17/24 | Flash led on this panel |
| Topic-generation cells | 39/48 | 48/48 | Flash led under the declared policies |
| Portfolio contract cells | 16/16 | 14/16 | Flash's 12.5-point drop exceeded the declared 10-point regression allowance |
| Diversity protocol cells | 2/10 | 3/10 | Neither established reliable diversity plus selection |
| Role/effort cells | 12/18 | 15/18 | A stack/policy result; not an isolated weights effect |
| Historical strict repair cells | 0/6 | 0/6 | No accepted strict-contract repair win |
| Primary context checks | 4/4 | 4/4 | Small checks within the 126-cell panel; separate from the capacity sweep below |
| Separate fresh science tasks | 6/6 | 5/6 | Resident won one additional task; small development set |
| Separate fresh strict repair tasks | 0/6 | 0/6 | Both remain zero under the original contract |
| Predeclared repair-framing diagnostic | 6/6 | 6/6 | Diagnostic transformation passed sandboxes; it does not replace either strict score |
| Primary evaluator time | 1,870.5 s | 1,500.1 s | Recorded evaluator wall time, including its failures; excludes lifecycle overhead |
| Final cap diagnostic | Not applicable | 0/40 calls issued | Startup guard stopped execution; quality is unmeasured |

The context panel tested four evidence tasks in three placements at each
capacity tier. Each row below contains 12 calls. A tier reserves 2,048 output
tokens: measured input maxima were about 6K, 14K and 30K, not 8K, 16K and 32K
of prompt text alone.

| Total capacity tier | Gemma | Qwen | Mia Flash-Next |
| --- | --- | --- | --- |
| 8K | 12/12; 19.0 s for the panel | 12/12 | 12/12; 55.4 s |
| 16K | 12/12; 37.0 s | 12/12 | 12/12; 104.1 s |
| 32K | 12/12; 117.1 s | Unmeasured | 12/12; 200.6 s |
| 64K | Unmeasured | Unmeasured | Unmeasured |

Qwen's 24 cells were run under a separate plan; their later matched-cell audit
is a cross-plan diagnostic, not a same-plan randomized comparison. All timing
above is end-to-end recorded wall time, not raw decode tokens per second.

The evidence supports keeping the tested capacities available. It does not
prove those limits are globally optimal, that every request should fill them,
or that Qwen cannot support a larger lane. No 64K capability is established.

## Final startup outcome

The [closed supervisor receipt](flash-cap-closure-result.public.json) binds the
registered window and all terminal evidence. The attempt ran from 04:25:07 to
04:38:24 UTC. Host pageout reached 562,221,056 bytes over five seconds against a
536,870,912-byte ceiling. Host available memory was 36.55 GiB at the breach and
never fell below 30.17 GiB. Candidate cgroup swap, OOM, OOM-kill and restart
counters stayed zero. This was a host pageout guard, not an out-of-memory kill.

Restoration took 404.3 seconds and verified the exact resident containers,
restart baselines, endpoints and Nara state. No readiness, probe, admission or
evaluation artifacts existed. The prior aborted attempt remains immutable.
The UI now displays both attempts within the same diagnostic history.

## What would reopen the candidate

The Sunday review may propose a new bounded qualification only with a material,
documented change or an evidence-based explanation of the startup pageout:
for example a reviewed loader/runtime change, a different deployable artifact,
or a prospective host-state intervention. A renamed study alone is not a new
hypothesis. Do not relax the frozen guard after seeing this result.

First establish readiness and repeatable recovery under the newly declared
conditions. Then compare against the strongest declared incumbent stack on the
frozen benchmark release, followed by its larger triggered repair/science
panels. Keep runtime qualification, output-cap diagnostics and model-quality
results separate. The new core records Flash as unissued until those runtime
conditions are met.

## Evidence provenance

The historical values were reread on 2026-09-16 through the existing bounded
admission projections:

- `lab_model_eval_progress.project_progress()`: admitted pair
  `qfn-ab-lab-primary-20260915-b`; plan SHA-256
  `9616a6f5b982585570fb1bcd6de76aa754fcb722225f90ecded3d737838ec0b8`.
- `lab_model_supplement_progress.project_progress()`: fresh pair index
  `c1ab218a5f0014f67943cd328e77e82e320954e773c35fb21ff2654492a983ee`
  and context pair index
  `0717b42861d057db9d0c9e62b7a8e062f5c9d946f86cd4b30e5f6af59ac2ecc0`.
- `lab_model_context_crossplan_progress.project_progress()`: Qwen/Mia
  cross-plan index
  `60610c79c710a40ba7b42f257ebf5bb21b5a49ec0462d9f53b64616f4e572c10`.
- Final cap public receipt SHA-256
  `0b1f8fc0df2a9435650e6e871ecae5795fdabe563f5d6e59af2c57f1d809ad86`.

No historical result was rerun, rescored or rebased into the new release.
