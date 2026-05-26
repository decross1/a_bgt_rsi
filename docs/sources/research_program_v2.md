# Research Program v2

A 2–5 year meta-scientific project on AI-augmented independent research.

## The Research Program

**Central question.** Can a well-designed at-home research loop, run by an independent researcher with modest hardware, produce findings at the productive edge of a research field — not through recursive self-improvement of models, but through amplifying a single human's ability to explore, evaluate, and contribute?

**Why this is novel.** The dominant AI-for-science narrative focuses on frontier-lab automation: recursive self-improvement, automated theorem-proving, scaling agentic systems. This program tests a structurally different hypothesis — that the research apparatus itself can be built, operated, and evaluated by one person with a DGX Spark and open models, and that the output can be real. This positions the work against Sakana's AI Scientist, FunSearch, Boiko's Coscientist, and related efforts, but asks a question those projects sidestep: what does this look like outside frontier labs, in domains without objective ground truth, for a solo researcher?

**The apparatus is the contribution.** The loop's findings about agent behavior, game theory, or whatever it lands on populate the work with content. Whether the apparatus produces findings a competent domain researcher would endorse is the actual claim.

**Primary field of application.** Game theory, behavioral game theory, and learning in games — chosen because LLM agents in game-theoretic settings are underexplored, have clean experimental design traditions, and let the loop operate across synthetic-to-applied environments with increasing realism.

**Sandbox spectrum.** Three tiers, all in use:

- **Synthetic** — classical games with known equilibria (repeated PD, public goods, stag hunt, Cournot, auctions). Loop's job: rediscover or characterize what's known. Success is cleanly measurable.
- **Semi-synthetic** — multi-agent LLM societies in designed scenarios, no ground truth but clear structure.
- **Applied** — Polymarket primarily; possibly other prediction markets, open-source contribution environments, or Kaggle-like settings over time.

The loop's value is strongest when findings generalize across tiers, and its failure modes are most diagnostic when it succeeds in one tier and fails in another.

## Program Arc (2–5 Years)

| Phase | Duration | Milestone |
|---|---|---|
| 1 — Alignment | 90 days | Reading foundations laid, apparatus v0 running, first synthetic-tier experiments, public preprint establishing the research program |
| 2 — Loop v1 | Months 4–9 | Full autoresearch loop operational across synthetic + semi-synthetic tiers; first real findings logged; 1–2 workshop papers submitted |
| 3 — Applied deployment | Months 10–18 | Polymarket live; multi-tier findings accumulating; main research contribution crystallizing; conference submission (EC, AAMAS, or NeurIPS workshop) |
| 4 — Meta-scientific synthesis | Months 19–36 | The meta-claim about independent AI-augmented research firms up from accumulated evidence; main paper or thesis-equivalent artifact |
| 5 — Extension | Months 37–60 | Depending on where Phase 4 lands — either a second research program using the same apparatus, or deepening into whatever the loop surfaced as most promising |

The active build slice is governed by a separate, focused plan — see `LOOP_V0.md`. This arc is the long-term orientation, not a daily ladder.

## Foundational Literature

The novelty-evaluation capability depends on the loop having access to the same body of work the researcher reads. Canonical references are ingested into the knowledge base at build time so the hypothesis generator and novelty classifier can ground claims; the arXiv pipeline (`cs.MA`, `cs.GT`, `econ.TH`) keeps the loop current.

**Game theory & learning in games**

- Osborne & Rubinstein, *A Course in Game Theory*
- Fudenberg & Tirole, *Game Theory*
- Fudenberg & Levine, *The Theory of Learning in Games*
- Cesa-Bianchi & Lugosi, *Prediction, Learning, and Games*
- AGT (Nisan / Roughgarden / Tardos / Vazirani), Ch. 4 on regret and equilibria
- Hart & Mas-Colell on correlated equilibrium via regret matching

**Evolutionary game theory**

- Weibull, *Evolutionary Game Theory*
- Hofbauer & Sigmund, *Evolutionary Games and Population Dynamics*
- Smith & Price 1973 (the original ESS paper); Nowak 2006 (five rules for cooperation)

**Behavioral game theory (indispensable for novelty evaluation)**

Without this layer, the loop cannot distinguish LLM-novel behavior from recapitulated human deviations.

- Camerer, *Behavioral Game Theory*
- McKelvey & Palfrey 1995 on quantal response equilibrium
- Stahl & Wilson 1995, Crawford et al. on level-k
- Camerer, Ho & Chong 2004 on cognitive hierarchy

**LLMs as agents (active literature; arXiv-tracked)**

- Horton 2023, "Large Language Models as Simulated Economic Agents" ("homo silicus")
- Aher, Arriaga & Kalai 2023 on replicating economic experiments
- Park et al. 2023, "Generative Agents" (Smallville)
- Fish, Gonczarowski & Shorrer on LLMs in market behavior

**The autoresearch loop literature (optimistic + skeptical, equal weight)**

- King et al. 2009, "The Automation of Science" — robot scientist
- Lu et al. 2024, Sakana's "The AI Scientist"
- Romera-Paredes et al. 2023, FunSearch
- Boiko et al. 2023, Coscientist (chemistry)
- Critical responses to Sakana (Matt Welsh, Melanie Mitchell, "LLMs as reviewers" 2024–2025)
- Replication crisis: Open Science Collaboration 2015, Ioannidis 2005, Camerer et al. 2016/2018

**Methodology of discovery**

- Hacking, *Representing and Intervening*
- Chang, *Inventing Temperature*
- Selected Lakatos on research programmes

## Cross-Cutting Practices

**Academic rigor by default.**

- Every claim in a post or preprint backed by data, code, or citation
- All data, logs, prompts, seeds, model versions, hardware specs recorded
- All experiments reproducible by an outside reader from the public repo
- When the loop produces a finding, the first question is always: is this already known? The literature search is part of the finding, not after it.

**Public research journal as primary data.** The journal is not accountability scaffolding — it is the record of the apparatus's outputs, the researcher's evaluations, and the evolving criteria for novelty. Format for each non-trivial loop output:

- What the loop claimed
- The prior for whether it's novel
- Literature search against it
- Post-search assessment (genuinely novel / rediscovery / nonsense / unclear)
- What would change the assessment

**Literature pipeline into the loop.** arXiv `cs.MA` / `cs.GT` / `econ.TH` papers flow into the vector store on a regular cadence. The hypothesis generator and novelty classifier have access to them. This closes a gap that current auto-science systems have: they rediscover known results because they don't know the literature.

**Robustness as first-class concern.** LLM agent behavior is prompt-, seed-, and model-version-sensitive in ways classical experimental economics isn't. Every finding gets a robustness battery. This is either an obstacle or its own contribution — systematic study of finding-robustness across prompt / seed / model variation is itself publishable.

**Standing red-flag checks**

- Reading without doing? → build
- Doing without thinking? → read
- Can I reproduce what I claimed to understand last week? If no, slow down
- Am I the bottleneck on evaluating loop outputs? That's the point — is that skill improving?
- Is the loop surfacing things I genuinely didn't know? If no for 30+ days, something is wrong with the hypothesis generator or experiment design

**Publishing discipline.** Weekly journal, monthly technical post, quarterly preprint or workshop-level writeup.

## What This Plan Deliberately Cuts

- Real analysis, measure theory, heavy optimization — deferred until the loop demands them
- Full economics track — compressed to mechanism design vocabulary
- Coursework-style coverage for coverage's sake — every reading serves the research program
- The assumption that 90 days produces mastery — Phase 1 produces alignment; Phases 2–4 produce contribution
- The assumption that the researcher works alone — cold outreach and public writing are infrastructure

## What This Plan Deliberately Includes That's Non-Standard

- The apparatus is the research contribution, not the findings
- Novelty evaluation is its own sub-research-problem, named explicitly
- Three-tier sandbox spectrum (synthetic / semi-synthetic / applied) with findings expected to generalize
- Public research journal as primary data, not as accountability
- Skeptical auto-science literature given equal weight to optimistic
- Robustness battery built in from the start of apparatus operation
- 2–5 year arc with 90 days as phase one, honestly scoped

> Revise aggressively. A plan that survives Phase 1 unchanged wasn't honest about what you'd learn.
