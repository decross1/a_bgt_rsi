# Public-safe game-theory benchmark portfolio plan

**Prepared:** 2026-09-14
**Status:** implemented public development suite; no model calls or promotion authority
**Budget target:** at most 2,310 charged seconds for one paired development run

## What exists and what is missing

The current public objective canary has twelve single-turn tasks: three formal
game-theory calculations, four critic classifications, three evidence
attribution cases and two deterministic tool calls. Its graders check exact
numeric, categorical, citation and tool semantics. This is a useful vertical
slice, but it does not yet cover:

- the D-075 delegation, liquid-democracy, social-choice and sortition scope;
- fresh execution of generated code;
- transitive delegation, cycles, ties and comparator-definition edge cases;
- evidence whose surface aggregate conflicts with the correct stratified
  conclusion; or
- the boundary between evidence about acyclic delegation and a claim about
  allowing cycles.

The existing canary remains frozen. Adding grader kinds to its current module
would change an execution dependency of already registered experiments.
Implement the additional tasks as a separate development package and
manifest.

## Publication and claim boundary

Call this suite **public synthetic development data**. “Private-safe” here
means it contains no private user prompts, historical raw model output,
unpublished research findings, machine-memory rows, credentials, proprietary
paper text or reconstructed private bug reports. It does **not** mean the
answers are hidden from an optimizer with repository access.

Every task must declare `origin: synthetic_authored_for_eval`, its derivation,
the D-075 or formal-game concept it tests, and the hashes of every prompt,
starter file and grader input. Do not label any task “historical bug-derived”
without a separately reviewable source and permission to publish it. Raw run
artifacts remain outside Git.

This panel can catch regressions and justify a larger held-out evaluation. It
cannot establish a small noninferiority margin or promote a production policy.

## Proposed eight-task slice

The first slice adds four scientific/formal tasks, two evidence tasks and two
bounded coding tasks. Each structured grader derives the oracle from the
manifest inputs rather than accepting a self-declared expected answer.

### Scientific and formal reasoning

**SCI-D075-LD-POWER-001 — delegation concentration.** Provide baseline voting
weights `[2,2,2,2]` and post-delegation weights `[4,2,1,1]`. Require baseline
HHI `0.25`, post-delegation HHI `0.34375`, delta `0.09375` and direction
`increased`. The grader normalizes the supplied weights and recomputes all
values. Mutation tests reject using raw-weight squares, omitting normalization,
or reversing the sign.

**SCI-D075-SORTITION-001 — strategic participation representation.** A
population contains 60 voters in group A and 40 in group B. Thirty from each
group enter the eligible pool, from which 12 seats are sampled uniformly.
Require expected seats `(6,6)`, expected A share `0.5`, population A share
`0.6`, and representation bias `-0.1`. The grader recomputes expectations from
counts. Mutation tests reject treating population shares as eligible-pool
shares and reporting observed integer draws as an expectation.

**SCI-D075-SOCIAL-CHOICE-001 — Condorcet versus plurality.** Freeze seven
ballots: three `A>B>C`, two `B>C>A`, and two `C>B>A`. Require plurality winner
`A`, Condorcet winner `B`, B-over-A margin `1`, and B-over-C margin `3`.
Recompute first-choice and pairwise counts. Mutation tests reject conflating
plurality and Condorcet winners, reversing a margin, and silently breaking a
tie outside the declared rule.

**SCI-GT-COORDINATION-001 — complete bounded equilibrium report.** Supply the
symmetric two-action game with row payoffs `[[4,0],[3,3]]` and column payoffs
`[[4,3],[0,3]]`. Require the two pure equilibria and the symmetric mixed
adoption probability `0.75`. Grade probability-simplex validity and unilateral
deviation residuals against the supplied matrices, not string labels alone.
Mutation tests reject pure-only answers, the risk-dominance threshold reported
as a mixing probability, and swapped player payoffs.

### Evidence and scientific inference

**EVID-D075-CYCLE-BOUNDARY-001 — scope of evidence.** Use two short synthetic
documents with stable IDs. One reports an acyclic-delegation experiment that
prohibited cycles; the other allows cycles but reports no voting-power or
concentration outcome. Ask whether the packet identifies the causal effect of
allowing cycles on concentration. The valid reason code is
`no_allowed_vs_forbidden_concentration_comparison`, citing both IDs. Mutation
tests reject treating
an acyclic result as evidence about cycles, citing only the topically similar
document, or inventing a source ID.

**EVID-GT-SIMPSON-001 — aggregate versus stratified cooperation.** Use a
synthetic two-stratum table based on explicit counts: treatment successes are
`81/87` and `192/263`; control successes are `234/270` and `55/80`.
Treatment is higher within both strata while control is higher in aggregate.
Require codes for both directions, an `aggregation_confounded` conclusion and
the exact IDs for the aggregate and stratum tables. Mutation tests reject the
aggregate-only causal conclusion, arithmetic reversal and unsupported
citations.

### Executable coding

**CODE-D075-DELEGATION-001 — resolve delegation graphs.** Give a small
synthetic module with a documented `resolve(ballots)` function. Each listed
voter has unit weight and either casts `A`/`B` or delegates to another voter.
Transitive paths terminating at a ballot accrue weight; paths entering a
cycle, self-loop, missing target or invalid value are exhausted. The function
must return vote totals and sorted exhausted voter IDs without mutating input.
Repository-visible grader cases, withheld from the sandboxed child invocation,
cover shared tails, a cycle with an inbound delegation, self-delegation,
missing targets, arbitrary voter IDs and input immutability.

**CODE-GT-REGRET-001 — implement external regret.** Give a synthetic module
whose `external_regret(payoffs, chosen)` incorrectly uses the best action on
each round. Require earned payoff, best fixed-action payoff, total external
regret and average external regret. Public grader cases cover the known
`[(1,0),(0,1),(1,0),(0,1)]` trap, ties, floats, an adaptive sequence that beats
every fixed action, malformed rows and invalid chosen indices. The task spec
states whether negative regret is retained; the grader must implement exactly
that convention.

## Safe coding grader

The model returns one strict JSON object containing replacement source for one
declared file. The host parser writes only that field to an ephemeral task
copy; it never evaluates model-provided shell text. A restrictive AST gate
rejects imports, unapproved attributes/calls, helpers and top-level effects.
The trusted child executes the function with a reduced builtins dictionary.
Run each case in a fresh bubblewrap process that receives its input but no
expected answer; the trusted parent compares the bounded JSON result with its
oracle. The implemented sandbox uses:

- new user, IPC, PID, network, UTS and cgroup namespaces via `--unshare-all`;
- only read-only `/usr`, `/lib` and the ephemeral task bind, plus isolated
  `/proc`, `/dev`, and tmpfs `/tmp`;
- uid/gid 65534 with all capabilities dropped;
- CPU, address-space, file-descriptor, file-size and wall-clock limits;
- stdout/stderr redirected to bounded regular files so a pipe cannot grow
  without limit, with process-group kill and wait on timeout; and
- no host sockets, secrets, repository or live-state mounts.

The manifest pins `/usr/bin/bwrap` and `/usr/bin/python3.12` by SHA-256 and
version; the run artifact records expected and observed identities. The AST
gate prevents process creation, while the PID namespace limits visibility;
there is no separately claimed numerical PID cgroup cap.

If the exact binary identities or isolation controls are unavailable, record
`INCONCLUSIVE_GRADER` and keep the task in the denominator. Never fall back to
executing generated code on the host. Sandbox setup is CPU-only and does not
receive the Spark GPU lease.

## Proposed artifact paths

Implementation should be isolated at these new paths:

```text
bench/weekly_upgrade_portfolio/__init__.py
bench/weekly_upgrade_portfolio/manifest.py
bench/weekly_upgrade_portfolio/graders.py
bench/weekly_upgrade_portfolio/runner.py
bench/weekly_upgrade_portfolio/code_sandbox.py
bench/weekly_upgrade_portfolio/tasks/code_delegation/starter.py
bench/weekly_upgrade_portfolio/tasks/code_regret/starter.py
experiments/weekly_upgrade_game_science_dev_v0_2026-09-14.json
experiments/PREREG_weekly_upgrade_game_science_dev_v0_2026-09-14.md
tests/test_weekly_upgrade_portfolio_manifest.py
tests/test_weekly_upgrade_portfolio_graders.py
tests/test_weekly_upgrade_portfolio_runner.py
tests/test_weekly_upgrade_portfolio_sandbox.py
```

Do not modify the frozen `bench/weekly_upgrade_eval/fixtures.json` or its
registered manifests. Dispatcher registration is a later, separate patch after
the new runner's offline plan, artifact receipt and sandbox tests pass.

## Manifest and grader contracts

The content manifest should freeze:

- publication class and claim limits;
- task IDs, families and role (`scientific`, `evidence`, `coding`);
- literal prompt or hashed task-file paths;
- strict output schema;
- per-task request timeout and output cap;
- objective grader version and all numeric/tie/convention parameters;
- provenance and content hashes;
- the pinned bubblewrap and system-Python identities for coding tasks; and
- the paired AB/BA order.

The manifest should not permanently bake in “strongest” model aliases. A
preregistered execution card supplies two fully resolved arms and records the
returned runtime/model identity. Every raw completion is durable before
parsing. Missing, invalid, timed-out and inconclusive-grader attempts remain in
the declared denominator.

Required property/mutation tests include:

- duplicate keys, unknown fields, NaN/infinity and hash drift fail closed;
- action/player relabeling and positive payoff scaling transform the oracle;
- plausible wrong numeric answers fail each structured grader;
- citation order may vary but duplicates, omissions and unknown IDs fail;
- code cannot escape the declared target file or sandbox;
- timeout and container failure cannot become a pass;
- raw output is written before parser/grader failure; and
- `--plan` neither imports the wrapper nor writes output/ledger files.

## Weekly budget fit

One paired slice declares 16 model calls. Every call has a 6,144-token output
cap so an `xhigh` reasoning arm is not structurally forced into truncation:

- six structured tasks × two arms × 120 seconds = 1,440 seconds;
- two coding tasks × two arms × 180 seconds = 720 seconds;
- at most 120 seconds for isolated grading.

Set the evaluator payload to at most 2,280 seconds and the dispatcher
reservation to 2,310 seconds. Record actual charged time when the terminal
receipt is trusted. Do not run this slice in a week where the three-repeat
Qwen pilot has reserved 6,750 seconds unless the canonical ledger proves the
combined reservations fit the 7,200-second cap. The panel defers rather than
dropping difficult tasks or shortening one arm.

One run gives development evidence, not reliable-success statistics. Repeat
the same frozen panel across later weeks or use a separately preregistered
confirmation run before attributing stochastic-policy gains. Report per-family
success, failure-inclusive wall time and Correct Task Throughput; do not merge
them into a score where a science gain hides a coding/evidence regression.

## Completion evidence for this tranche

The implementation tranche is complete when:

1. all eight task inputs and provenance records validate;
2. every grader passes its oracle and rejects its named plausible errors;
3. code-grader escape, timeout and unavailable-container tests fail closed;
4. an injected fake transport produces a complete 16-cell artifact and a
   receipt reconstructible from raw records;
5. offline planning proves no wrapper import, calls or writes;
6. private-safe scanning finds no secrets, raw production rows or unlicensed
   text; and
7. the preregistration states the development-only claim and 2,310-second cap.

No live model run, dispatcher registration, scheduler activation or production
policy change is part of this design document.
