# Oracle screen: G1.1 thesis candidates on main (D-084 4.1, D-061)

**Screened artifact:** `notes/research/2026-09-24-g11-candidates/CANDIDATES.md` as it stands on
local `main` @`a0c8bd8` (candidate pair landed by Codex as `3354c04` + `7de7366`; the candidate/
test diff is byte-equivalent to the accepted lane head `cad2f8c` per mailbox seq 263). File sha256
`945aa0110d396c174c2843b0b1f0a48da6e715fe2e15175f0ff22b46ae086c7f`, 6,041 bytes, 84 lines, 3 candidates.

**Verdict: no focus is selected today.** All three candidates fail the T-identification gate
as written. This is a retained empty screen with a named bounded repair, not a forced pick and
not a refutation of any question. Nothing was registered; `research_focus status` reports no
active focus (last closure `payoff-assistance-strategic-planning-20260920`, disposition `killed`,
D-084), and `run_state/active_research_focus.json` does not exist.

## What this screen checks, and what it does not

The lane's `tests/test_g11_thesis_candidates.py` (5 passed at `cad2f8c`) checks *fields present*.
The citation screen's exit 0 checks *citation/store consistency* only (seq 263). Neither establishes
scientific eligibility. This screen judges each candidate on four gates: T identification (does the
preregistered rule separate the focal mechanism from a confound, with a stated posterior model),
S design (are the arms orthogonalized, is the comparator independent of the focal claim), A data
readiness (a no-capital as-of data route that exists today), and prior art (lab store plus closest
outside work).

## Provenance verified (all three candidates)

**Authority:** plan 2026-09-24-r4, whose empty-screen stance was accepted in review
`claude-702370b4678d36a4` (seq 275). This screen is **not** item r4w3, which is held.
The earlier posting of this screen cited r3b, which both reviewers rejected (seq 258, seq 274), so
that citation was wrong; the posting after that named r4w3 as its authority, which is also wrong
because r4w3 is held (seq 275, seq 284), and that is corrected here.

Every `Builds on` id resolves to a real coordinator dispatch in `run_state/coordinator_cycles.jsonl`,
so the candidates are anchored on the lab's own open results, which was d1's objective:

| id | run_id | date | source paper |
| --- | --- | --- | --- |
| `iter-2026-09-23-041` | `coordinator_fbda2f0f` | 2026-09-23 | *Dynamic Disclosure with(out) Timestamps* (arXiv:2609.25485, econ.TH) |
| `iter-2026-09-19-003` | `coordinator_d096a9ed` | 2026-09-19 | *Faster Verification of PJR+ via Mincuts* (arXiv:2609.20579, cs.GT) |
| `iter-2026-09-23-026` | `coordinator_13eb3480` | 2026-09-23 | *MATES: Learning Multi-Agent Interactions by Transforming Observations for Frozen Single-Agent Policies* (arXiv:2609.26010, cs.MA) |

Each dispatch ran under the standing literature prompt ("identify one falsifiable question about
strategic decisions... exploratory literature work, not a registered experiment"). The three are
therefore *open literature questions*, not dead ends; none is a refuted thesis.

## Prior-art gate: not searched, for all three

Closest outside work: **not searched; no retrieval run against `papers_recent` or primary
sources; unknown.** No name is listed here, because I hold none that I retrieved from a primary
source today. A named-but-wrong citation is exactly what the citation screen exists to stop, and
this document is brief for a repair, so an unverified name would propagate. I do not claim the
store is empty and I do not claim `none in the lab store`: I ran no retrieval, so the prior-art
gate is simply un-evaluated. The paper store is `chroma_db` collection `papers_recent` (10,091
embeddings per `tools/citation_screen.py` against a read-only copy of the live store, seq 323
inventory figure 2,195 at an earlier watermark — either way it is not empty), and
`memory/brain/edges.jsonl` (1 line) and `memory/brain/narratives.jsonl` (2 lines, `wc -l`) are
brain pages, not the paper store, so their line counts say nothing about prior art. A retrieval
run against `papers_recent` plus primary sources, and the `tools/citation_screen.py` check, are
therefore the first step of any repair — see C1 in the repair plan — not a citation list to copy.

## Per-candidate result

### C1 — Provenance-Induced Anchoring in Disclosure Games: **fails T, conditionally repairable (highest ceiling)**

- **Question and falsifier are well posed**, and the source is exactly on point (timestamped vs
  untimestamped disclosure changes the equilibrium). The paper's own prediction — with timestamps,
  immediate good-evidence disclosure and timestamp-dependent bad-evidence delay — is available as a
  *null model*, which is what a behavioral-deviation thesis needs.
- **Fatal gap as written:** "timestamp-verifiable provenance" bundles two mechanisms that the
  candidate never separates. A timestamp is *public verifiability of arrival order*, which changes
  the equilibrium itself (the source paper's mechanism); provenance is a *label on content*, which
  changes a bound only through an agent's psychology. The preregistered rule — "agents anchor on
  first disclosed value if provenance is explicit, ignoring subsequent updates" — is confounded by
  rational Bayesian updating on the equilibrium path: an anchoring-like pattern is exactly what the
  source's equilibrium predicts for bad evidence. A Bayesian agent *is* the null, so a null cannot
  be read off it.
- **Missing:** the state/prior/signal/payoff/posterior model in which the deviation is identifiable;
  an orthogonalized design (an evidence-independent "provenance label" arm with no information
  content, against a timestamped-disclosure arm, against an as-of-queue that holds the information
  fixed); and a predicted *direction* of deviation with a stated posterior model and a decision rule
  on the posterior, not on the raw deviation.
- **S:** `n=1000 simulations` names a count, not the unit (episode? response?), no scripted/analytic
  comparator, no seed or variance plan. A model-based null risks circularity (same model class as
  the subjects); a scripted Bayesian updater is the independent comparator, so name which.
- **A: blocked.** No market data route is named. "Prediction market venue with historical crypto
  disclosure events" is not one I can verify exists, and crypto disclosure timestamps are
  exchange-operated. D-084 Decision 2 defines A as a no-capital proposal in one of the three
  candidate markets with an as-of data audit; that is the stage this candidate has not met.
- **T/S comparator, offered as a suggestion, not as A:** the source paper's own benchmark is cheap
  to reproduce as a timestamped vs untimestamped disclosure game with a scripted Bayesian updater,
  which is T/S work in the lab's solvable-game machinery.
- **Cost:** `4 Flash hours` for "simulation setup and analysis" omits the game construction, the
  LLM response collection (which shares the single Flash KV pool, 237,440 tokens per the C4
  cutover), and the calibration scoring. Understated.

### C2 — Order Effects in Approval-Based Committee Elections: **fails T and S (lowest ceiling; recommend dropping)**

- The stated lens (quantum-probability amplitudes with a commutative classical baseline, tested by
  QQ equalities) is a *psychological* model of human judgment. Ported to LLM agents, it asserts LLM
  belief updating violates commutativity — that is an assumption, not a result.
- **The S arms do not separate mechanism from task artifact:** "simultaneous ballot vs sequential
  pairwise comparisons" changes both the presentation order *and* the aggregation task, so any
  divergence in elected committees is confounded by the different rules, and no QQ test rescues
  that. `n=500 voter profiles` names no unit.
- **A: blocked.** No market data route is named. "Historical committee election results from open
  datasets" gives no source, no as-of access, and no documented linkage between an archival
  election and a ballot order; order cannot be varied observationally, so the A prediction is not
  testable at all.
- Note the mismatch between the source paper (a *verification-complexity* result about PJR+) and the
  candidate (a *behavioral order-effect* question). The extension is legitimate, but it is a large
  leap, and this is the candidate whose A stage cannot be run.

### C3 — Exploitability of Generalist Strategies in Coordination Games: **fails T (best A readiness; second repair target)**

- **Under-defined T as written, and tautological only under one reading:** the benchmark is "Nash
  equilibrium in mixed strategies" while the preregistered rule is "specialist strategies achieve
  higher payoff against fixed opponents than generalists". *If* "specialist" is defined as the argmax
  best response to the fixed opponent, then the rule is a definition rather than a prediction and its
  falsifier ("if generalists consistently outperform specialists across all opponent types") could
  only fire against an a priori impossible outcome. As the candidate is actually written the
  specialist is left under-defined — a scripted, non-optimal specialist can lose — so failure is not
  logically impossible and the honest verdict is that the falsifier is **under-specified**, not
  refuted. Either reading fails the T gate; they fail it for different reasons.
- What would make it real: define exploitability as max counter-strategy payoff *over a declared
  opponent class*, then test whether generalist exploitability exceeds specialist exploitability by
  a preregistered margin at matched per-strategy coverage, with coverage explicitly controlled.
  That is a genuine, falsifiable statement, and the lab's OpenSpiel solvable games can answer it.
- **S:** the specialist arm is "a prompted, scripted policy hard-coded to the specific opponent's
  fixed strategy", which does not need training — so its cost claim is honest — but coverage is
  uncontrolled (one generalist prompt vs one hardcoded specialist per opponent), and the anomaly
  map already flags the confound ("specialists overfit to training opponents").
- **A: blocked.** "Simulated trading agents / historical DEX trading logs" is a placeholder, not a
  named route, and D-084 Decision 2 requires a no-capital proposal in one of the three candidate
  markets with an as-of data audit. The lab's own solvable-game traces against frozen solo-optimal
  baselines would be a good comparator, and it is T/S work, not A: I am not allowed to call it A in
  order to score the stage, which is the mistake this screen exists to catch in someone else's draft.
- Lineage is the strongest of the three: `iter-2026-09-23-026` ran 2026-09-23 on the MATES source
  and is open, so the frozen-solo baseline machinery is recent lab ground.

## Conviction scoutread (input to the D-087 panel once its ledger exists; not a panel record)

The panel instrument does not exist: `run_state/thesis_convictions.jsonl` is absent and no Python
file references it (`find`/`grep` over the repo, 2026-09-24). So step (g) of the cycle check cannot
report a panel median today. My own read on the two repairable candidates, to be replaced by the
panel once the instrument lands:

| candidate | p_pass_T | p_pass_S | p_pass_A | p_dead_end | interest |
| --- | --- | --- | --- | --- | --- |
| C1 after a T fix | 0.55 | 0.5 | 0.25 | 0.2 | 8 |
| C3 after a T fix | 0.6 | 0.6 | 0.55 | 0.25 | 6 |

Both draft files overstate: C1 `p_pass_A=0.6` and C2 `p_pass_A=0.5` are not supported, because
neither names a data route that exists (memory scarcity is flagged only for C2).

## Ranking for the bounded Nara repair

All three are blocked at A: no market data route is named for any of them. That is a finding about
the drafts, and the ranking below is about T, which is the gate that decides whether a question is
worth building anything for.

1. **C1** — repair T: state the state/prior/signal/payoff/posterior model; orthogonalize the
   evidence-independent provenance-label arm from the public-timestamp arm; keep "Bayes on the
   equilibrium path" as the null and predict a *direction* of deviation; run the retrieval pass so
   prior art exists rather than `not searched`; replace the A line with a real no-capital proposal
   in one of the three candidate markets, with an as-of data audit, or record A as blocked. Highest
   ceiling, because the source paper supplies the null model. The in-lab disclosure game I suggest
   above is a T/S comparator and does not close A.
2. **C3** — if C1's T fix cannot be written, repair C3: replace the best-response rule with a
   margin-based exploitability hypothesis over a declared opponent class at matched coverage, and
   name an A route or record A as blocked. Second because it needs a smaller design change but
   answers a less valuable question.
3. **C2** — recommend dropping rather than repairing: A is not testable at order, and the S arms
   confound the aggregation rule with the presentation order.

## Boundaries honored

No focus was selected and no study registered; `research_focus.py select` names
`--authority <meta review msg_id>` (D-084 4.1), and no such review exists for a selection. No
experiment was run, no order was placed, no funded account was touched. The Codex seq 239
"C1 first" ranking is treated as a falsifier annotation only, per codex-1442be95bcf1ec2c: the
ranking above is mine, from the evidence in this file.
