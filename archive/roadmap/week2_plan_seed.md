# Week 2 plan seed — input to Day-38 planning

> **Seed only, not a plan.** Bullets below are observations from Week 1
> that should inform Week 2's planning task (Day 38). Week-2 planning
> *execution* is a separate task per the prompt's constraint — do not
> begin it after the Day 7 retrospective.

## What Week 1 produced (load-bearing for Week 2 choices)

1. **Apparatus v0 is online and reproducible.** All seven days landed
   with full audit chains in `run_state/week1.run.jsonl`; the orchestrator
   reconstructs end-to-end via `inspect_run`; experiment.lock captures
   the version-pin truth-table for re-runs.

2. **The cooperation lock-in finding (Day 7).** Gemma 4 in repeated PD
   exhibits invariant first-mover cooperation against any non-defecting
   opponent across `T ∈ {0.0, 0.2, 0.7}` and across a baseline vs.
   exploitation-prompted framing. The same model+prompt defects 88–98%
   vs `all_d`, so the model is responsive to incentives — it simply does
   not defect first. This is the publish-worthy headline once the
   `day7_publication_review_gate` clears.

## Week-2 priorities (in roughly the order the roadmap §5.1 already
## sequences; each gets a one-sentence success criterion)

3. **Day 38 — UI v1 ships (Track D)** _and_ dispatch plumbing
   (`agent/ownership.yaml`, `agent/collision_protocol.md`,
   `run_state/claims.jsonl`) gets exercised on its first real
   concurrent-track day. Success: 4-track parallel work merges cleanly;
   `week2.md` retrospective writes section 7 alignment-evidence.

4. **Day 39 — critic agent (`workers/critic.py`).** Specifically
   designed to second-guess "the result is just right" cases like Day
   7's 1.000 vs TFT — i.e. would the critic have caught the
   precompute-range violation independently? Success: critic flags ≥80%
   of injected-flaw hypotheses in the 20-known-flawed-hypotheses fixture.

5. **Day 40 — meta-review synthesis + first orchestrator-dispatched
   task.** First dispatch should be small / low-risk
   (docstring-drafting, schema-test scaffolding) to validate the
   protocol. Success: dispatched task lands clean + soft-gate sentinel
   recognized by Track A.

6. **Day 41 — auto-evaluator calibration.** First task that produces a
   numeric threshold (κ + Spearman). Will inform novelty scoring in
   later phases. Success: κ > 0.6 on the calibration set.

## Day-7-specific seeds (extensions of today's experiment)

7. **A second model for cross-model comparison.** Qwen 3.6 was deferred
   to Week 2-3 per `not_in_scope`. The Day-7 cooperation lock-in is a
   one-model finding — replication on a second model would tighten the
   "Gemma 4 specifically" qualifier and answer the harder question:
   does the cooperation prior generalize? Candidate: Qwen 3.6 served on
   the same DGX Spark, same prompt, same opponents.

8. **Higher-temperature ladder + alternative prompts on Gemma 4.**
   T=0.7 didn't break the lock-in; T=1.5 is the next natural step. And
   the `exploitation_hint` variant changed `all_d` behavior but not
   cooperation — the prompt search should also try (a) longer-horizon
   framing ("game ends after 100 rounds"), (b) different payoff
   matrices that break the 5/0/10/1 PD structure, (c) explicit
   role-play instructions.

9. **PD re-run with critic in the loop (Day 43).** Once the critic
   agent (#4) and meta-review (#5) are online, replay Day-7's
   experiment as the first end-to-end Phase-2-architecture exercise.
   Hard-gate the publication side; soft-gate the run.

10. **Orchestrator generalization beyond surgical extension.** Day 7
    needed a 30-line surgical edit to add `play_pd_match` to
    `KNOWN_TASK_TYPES`. The Week-2 dispatcher (Day 39's
    `agent_wrapper/dispatch_coding_agent.py`) should land a generic
    task-type → worker dispatch table so future workers don't need the
    same kind of edit. Also: standardize the per-opponent CSV format
    so `quicklook.py` doesn't need an adapter step.

---

_Bullets above are the *seed*, not the plan. Week-2 planning happens
on Day 38 with the human + Track A acting on these inputs, the
Day-7 retrospective answers, and the alignment-evidence section of
`human/retrospectives/week1.md`._
