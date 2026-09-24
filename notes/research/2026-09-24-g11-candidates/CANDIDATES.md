# Thesis Candidates

## Candidate 1: Provenance-Induced Anchoring in Disclosure Games

**Title:** Provenance-Induced Anchoring in Disclosure Games

**Question:** Does timestamp-verifiable provenance in multi-agent disclosure games induce anchoring bias that deviates from Bayesian updating?

**Lens:** Lens 1 (Behavioral economics): Investigates anchoring and base-rate neglect in LLM agents under complete information.

**Prior work:** 2609.25701

**Theory:** Decision problem: Multi-agent disclosure game with verifiable timestamps. Benchmark: Nash equilibrium with perfect information. Preregistered rule: Agents anchor on first disclosed value if provenance is explicit, ignoring subsequent updates.

**Semi-synthetic:** Arms: Explicit provenance vs. implicit provenance. n=1000 simulations. Outcome: Deviation from Bayesian posterior. Missing rule: No penalty for anchoring error in current mechanisms.

**Applied:** Prediction market venue with historical price series data. Data: Historical crypto asset disclosure events.

**Falsifier:** If LLM agents update strictly according to Bayes' theorem regardless of provenance visibility, the hypothesis is falsified.

**Anomaly map:**
- Cause: Agents ignore later disclosures when initial value is anchored. Next test: Vary the magnitude of the initial anchor.
- Cause: Provenance labels increase confidence but not accuracy. Next test: Measure calibration error against ground truth.

**Cost:** 4 Flash hours for simulation setup and analysis.

**Conviction:** p_pass_T=0.8 (strong theoretical basis), p_pass_S=0.7 (clear experimental design), p_pass_A=0.6 (data availability uncertain), p_dead_end=0.1 (low risk of null result), interest_0_10=8 (high relevance to mechanism design).

**Builds on:** iter-2026-09-23-041 (extension)

## Candidate 2: Order Effects in Committee Elections

**Title:** Order Effects in Approval-Based Committee Elections

**Question:** Do order effects in question presentation alter agent strategies in approval-based committee elections beyond classical probability predictions?

**Lens:** Lens 2 (Quantum info and belief): Tests interference between sequential voting questions using a formal quantum-probability model plus a classical Bayesian baseline making different testable predictions via QQ-equality tests.

**Prior work:** 2609.16270

**Theory:** Decision problem: Sequential approval voting game. Benchmark: Equilibrium under simultaneous vs. sequential presentation. Preregistered rule: Violation of commutativity in preference aggregation indicates order effects.

**Semi-synthetic:** Arms: Simultaneous ballot vs. sequential pairwise comparisons. n=500 voter profiles. Outcome: Divergence in elected committees. Missing rule: No mechanism to correct for order-induced bias.

**Applied:** Prediction market venue with historical election data. Data: Historical committee election results from open datasets.

**Falsifier:** If QQ-equality holds and no significant difference emerges between simultaneous and sequential formats, the quantum cognition model is falsified.

**Anomaly map:**
- Cause: Sequential presentation induces framing effects. Next test: Randomize presentation order across trials.
- Cause: Interference patterns match quantum predictions but not classical ones. Next test: Compare fit quality of both models using AIC.

**Cost:** 6 Flash hours for model implementation and statistical testing.

**Conviction:** p_pass_T=0.7 (novel application of lens), p_pass_S=0.8 (robust experimental design), p_pass_A=0.5 (data scarcity risk), p_dead_end=0.2 (moderate risk of inconclusive results), interest_0_10=9 (high theoretical novelty).

**Builds on:** iter-2026-09-19-003 (new)

## Candidate 3: Exploitability of Generalist Strategies in Coordination Games

**Title:** Exploitability of Generalist Strategies in Frozen-Solo Coordination Games

**Question:** Are generalist LLM-agent strategies more exploitable than specialist strategies in coordination games with frozen solo-optimal baselines?

**Lens:** Lens 3 (Agents in strategic games): Analyzes counter-picking and metagame adaptation in solvable coordination games.

**Prior work:** 2609.26552

**Theory:** Decision problem: 3-agent coordination game with frozen solo-optimal strategy. Benchmark: Nash equilibrium in mixed strategies. Preregistered rule: Specialist strategies achieve higher payoff against fixed opponents than generalists.

**Semi-synthetic:** Arms: Generalist policy vs. specialist policy trained on specific opponent. n=2000 episodes. Outcome: Average reward differential. Missing rule: No dynamic adaptation to opponent specialization.

**Applied:** Prediction market venue with simulated trading agents. Data: Historical trading logs from decentralized exchanges.

**Falsifier:** If generalist strategies consistently outperform specialists across all opponent types, the exploitability hypothesis is falsified.

**Anomaly map:**
- Cause: Specialists overfit to training opponents. Next test: Evaluate against unseen opponent types.
- Cause: Generalists fail to exploit predictable patterns. Next test: Introduce adversarial perturbations to specialist strategies.

**Cost:** 5 Flash hours for reinforcement learning experiments.

**Conviction:** p_pass_T=0.85 (well-grounded in game theory), p_pass_S=0.9 (controlled environment), p_pass_A=0.7 (simulated data sufficient), p_dead_end=0.05 (low risk), interest_0_10=7 (practical implications for agent design).

**Builds on:** iter-2026-09-23-026 (extension)