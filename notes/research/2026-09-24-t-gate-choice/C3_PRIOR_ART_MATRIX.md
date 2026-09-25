# C3 prior-art and algebraic-collision matrix

Date: 2026-09-24 UTC

Evidence snapshot: C3 choice note landed on `main` at
`e023d74eb7b15ad25582816129f28e9168517dd6` (patch-equivalent to
`oracle/2026-09-24-d3-r11` at `346d10c100159a74e95ae721eb25b50a69c33341`;
mailbox seq 418, as clarified in that note); this matrix is authored from C4 base
`9fc48c9b66ac5ebc1da03635272f4cecebc64545`.

Epistemic labels below are literal: **observed** means stated or derived
directly from the cited artifact; **inferred** means a comparison made in
this review; **unknown** means the current C3 definitions do not settle it.

Division of labor: the full design analysis is maintained separately at
`notes/research/2026-09-24-c3-t0-prereg/PREREG_DESIGN_CONSTRAINTS.md`
(`e6d3dbd`). This file is the primary-source collision record. It retains only
the algebra and definition checks needed to evaluate the literature claim.

## Bottom line

- **observed:** None of the primary sources in the bounded review below
  reports the complete C3 object: a frozen `pi0(x)=x`, the 64 deterministic
  observation adapters induced by a `2 x 3` state space, the five fixed
  partner rules, `H=4`, all 16 exogenous histories, three `lambda` values,
  and the same optimizer-tie envelope of generalist-minus-median-specialist
  *excess selector regret* under exhaustive enumeration.
- **inferred:** This is a failure to find a direct collision, not evidence of
  global novelty. The broad architecture and motivation are already crowded.
  TBS directly contrasts a static population generalist with an adaptively
  selected ensemble of specialist best responses; TALENTS uses fixed-share
  tracking regret to infer a partner type and condition behavior; MATES
  supplies the frozen-solo observation-adapter substrate.
- **inferred:** No reviewed theorem makes every well-defined finite C3 gap
  impossible. The published impossibility results address asymptotic regret
  against adaptive opponents under assumptions that do not automatically
  cover a fixed, exactly enumerable four-step game.
- **inferred, conditional and decisive:** One natural reading of the current
  phrase "excess selector regret" makes a positive gap impossible by
  definition; the short proof is below. If that reading is intended, the
  proposed `>= .10` pass band is empty and enumeration cannot rescue it.
- **unknown:** A defensible narrow novelty judgment, and even the sign test's
  non-vacuity, remain undecidable until the payoff, regret, comparator,
  generalist, specialist, selector, and tie-envelope definitions are frozen.

For this audit, a **direct collision** means either (a) a paper evaluates the
same substantive finite construction and statistic, or (b) a theorem's
stated assumptions entail the sign of C3's statistic. Sharing only the
adapter substrate, the generalist/specialist story, partner inference, or a
different regret notion is adjacent prior art, not a direct collision.

## Primary-source evidence matrix

| Primary source and status | What is established (**observed**) | Relation to C3 (**inferred**, unless marked otherwise) | Collision class |
|---|---|---|---|
| Abboud & Gal, [*MATES: Learning Multi-Agent Interactions by Transforming Observations for Frozen Single-Agent Policies*](https://arxiv.org/html/2609.26010v1), arXiv v1 submitted 2026-09-22 | Sections III-B and IV, eqs. (1)-(2), freeze a solo policy and train an observation-side adapter. Section V evaluates POGEMA, Navigation, and Discovery with learned neural policies; figures use 30 held-out episodes. Section V-F reports that no baseline dominates every setting and that an adapter over a randomly initialized frozen backbone is insufficient. It does not define a partner-type selector, C3 regret, or exact enumeration. | Closest substrate collision, plus a useful negative ablation. It does not test whether a finite frozen-solo adapter generalist has more excess selector regret than finite specialists. | Adjacent substrate; **not direct** |
| Ni et al., [*Theory of Mind Guided Strategy Adaptation for Zero-Shot Coordination*](https://arxiv.org/html/2602.12458), AAMAS 2026 paper; arXiv v1 submitted 2026-02-12 | Sections 3.1-3.2 explicitly compare a single static population best response (the generalist) with an ensemble of cluster-specialist best responses selected online from inferred partner intent. Evaluation is learned and empirical: a 16-round signaling toy and seven Overcooked layouts. Section 5 states that theoretical analysis is absent. Small partner pools can make TBS and the common BR comparable. | This is the closest collision with the *generic* generalist-versus-selected-specialists claim and architecture. It has no frozen-solo adapter class, C3 five-rule `Q`, exact trace enumeration, exploitability statistic, or optimizer-tie envelope. | Generic claim/architecture already occupied; **not narrow/direct** |
| Li et al., [*Modeling Latent Partner Strategies for Adaptive Zero-Shot Human-Agent Collaboration*](https://arxiv.org/html/2507.05244), arXiv v1 submitted 2025-07-07; paper metadata reports an RSS 2025 workshop best-paper award | Section III-C treats latent partner clusters as experts and uses fixed-share to minimize tracking regret while selecting/conditioning behavior. Section IV-A evaluates learned policies in four Overcooked layouts. The population best-response baseline beats TALENTS in Forced Coordination (Table I), while TALENTS leads most other layouts; the study also includes 119 retained human participants. | Strong selector-regret neighbor and a concrete negative result against universal selector superiority. Its expert loss is partner-action prediction and its outcome is empirical team reward, not C3 excess selector regret or exact finite enumeration. | Adjacent selector/regret; **not direct** |
| Lanctot et al., [*A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning*](https://arxiv.org/html/1711.00832), camera-ready NIPS 2017 paper; arXiv v2 2017-11-07 | Sections 3-4 introduce PSRO: approximate best responses to policy mixtures plus meta-strategies for policy selection. Section 4.1 measures joint-policy correlation/partner overfitting; experiments use learned gridworld and poker policies. | Establishes policy-population selection and partner-overfit context. Approximate learned responses and empirical payoff tables are materially different from C3's fixed adapter class, partner rules, statistic, and exhaustive enumeration. | Adjacent population/overfit; **not direct** |
| DiGiovanni & Tewari, [*Balancing adaptability and non-exploitability in repeated games*](https://proceedings.mlr.press/v180/digiovanni22a/digiovanni22a.pdf), UAI 2022, PMLR 180 | Section 2.3 makes regret benchmarks opponent-class dependent. Theorem 1 gives LAFF regret and non-exploitability guarantees for specified adversarial, follower, and bounded-memory classes when an enforceable egalitarian bargaining solution exists; it explicitly withholds the corresponding guarantee when none exists and calls the adversarial class restrictive. Section 5 reports linear LAFF regret in three games against an unconditional follower and a non-exploitative bounded-memory player. | Shows that adaptability/non-exploitability compatibility is conditional, not a universal ordering between generalists and specialists. It neither entails nor falsifies C3's finite gap. | Adjacent theorem and negative evidence; **not direct** |
| Wang et al., [*Balancing Safety and Exploitability in Opponent Modeling*](https://ojs.aaai.org/index.php/AAAI/article/view/7981), AAAI 2011, published 2011-08-04 | The paper constructs confidence-set opponent models that retain a high-probability minimax floor while exploiting inferred preferences, and extends the treatment to finite-stage stochastic games; demonstrations include repeated rock-paper-scissors and robot table tennis. | A counterweight to any sweeping claim that safe/general behavior and exploitation are universally incompatible. Its stationarity/model-confidence setting does not order the C3 policy classes. | Adjacent positive result; **not direct** |
| Arora, Dekel & Tewari, [*Online Bandit Learning against an Adaptive Adversary: from Regret to Policy Regret*](https://arxiv.org/abs/1206.6400), ICML 2012; Arora et al., [*Policy Regret in Repeated Games*](https://arxiv.org/abs/1811.04127), NeurIPS 2018; Nguyen-Tang & Arora, [*Learning in Markov Games with Adaptive Adversaries*](https://arxiv.org/abs/2411.00707), NeurIPS 2024 | The 2012 paper proves no sublinear policy regret against an unbounded-memory adaptive adversary and gives positive reductions for bounded memory. The 2018 paper gives an external/policy-regret incompatibility construction but also compatibility for stable play in its game-theoretic regime. The 2024 paper gives sample-efficiency barriers for unbounded-memory/nonstationary Markov-game opponents and positive results under memory, stationarity, and consistency restrictions. | These are real negative theorems, but their object is worst-case/asymptotic learnability, not the sign of one fixed `H=4` exact statistic. They do not make C3's proposed contrast impossible. | General lower bounds; **not applicable as a direct no-go** |
| Liu et al., [*Regret Minimization with Adaptive Opponents in Repeated Games*](https://arxiv.org/html/2606.06486), COLT 2026 ([PMLR 336 record](https://proceedings.mlr.press/v336/liu26c.html)); arXiv v1 2026-06-04 | Section 3.1 defines repeated policy regret so counterfactual opponents may respond to changed history. Section 3.2 and Appendix D give necessary conditions: without variation and imperfect-recall restrictions, sublinear RP-regret is impossible in general. The paper also supplies positive algorithms under additional conditions. | Most relevant warning about regret semantics: replaying the observed partner-action sequence is not the same as recomputing an adaptive partner's counterfactual response. Its lower bounds still do not determine C3's finite sign. | Adjacent definition/lower bound; **not direct** |

### Bounded failure-to-find

**observed:** The review inspected the primary full text/section structure of
the eight rows above and targeted arXiv/web searches through 2026-09-24 for
combinations of `frozen single-agent policy`, `observation adapter`,
`generalist specialist`, `best-response selection`, `partner policy`,
`selector regret`, `exploitability`, `finite horizon`, and `exact
enumeration`. No checked source contains the full direct-collision tuple or a
theorem that subsumes it.

**inferred:** This search bounds only these sources and queries. It does not
exhaust subscription indexes, dissertations, unpublished manuscripts,
code-only results, every citation edge, or work posted after the cutoff.
Accordingly the warranted statement is "no direct collision found in the
bounded review," not "first," "novel," or "unprecedented."

## Conditional algebraic no-go

This is an **inferred mathematical check**, not a result attributed to any
paper above.

Fix `lambda`. Let `A` be the same feasible policy class used for both labels,
and let `R_lambda(a,q)` be a lower-is-better regret score for policy `a`
against partner rule `q`. Under the natural robust reading, define

```text
S_lambda(a) = max over q in Q of R_lambda(a,q)
v_lambda    = min over a in A of S_lambda(a)
E_lambda(a) = S_lambda(a) - v_lambda
G_lambda    = argmin over a in A of S_lambda(a).
```

If a "generalist" is any `g in G_lambda`, every optimizer-tied generalist has
`E_lambda(g)=0`. If every specialist `s_q` is also an element of `A` and is
evaluated with that same score and floor, then `E_lambda(s_q)>=0`. Therefore

```text
Delta_lambda(g, s) = E_lambda(g)
                     - median over q in Q of E_lambda(s_q)
                   <= 0.
```

The inequality holds for every choice of optimizer ties, so even the upper
tie envelope is `<=0`. It also holds for mixed policies if all parties share
the same mixed feasible class and score. Under these conditions C3's positive
`>=.10` band is impossible and its proposed falsifier fires at every
`lambda`, before enumeration.

The proof **does not apply** if any of the following is intended:

- the generalist optimizes a Bayes/mean objective but `S_lambda` is a
  different worst-case or selector score;
- specialist excess uses a `q`-specific floor,
  `R_lambda(a,q)-min_a R_lambda(a,q)`, rather than the common `v_lambda`;
- the specialist or selector side has information or policies unavailable to
  the generalist (reverse inclusion); a larger class for the common-score
  generalist does not escape the no-go and makes the gap more negative;
- the generalist, specialist, and selector scores use different information,
  priors, counterfactual partner responses, normalizations, or signs; or
- "exploitability" is the partner's unilateral gain rather than the focal
  policy's regret.

Those exceptions can make a positive contrast coherent, but each defines a
different estimand. The preregistration must select one explicitly; it cannot
leave the exception implicit and interpret the resulting number afterward.

## Minimum pre-registration check for interpreting this matrix

The separate constraints note owns the full design. For novelty and collision
classification, six items must still be frozen before another search can be
definitive:

1. **Game:** both utilities, `lambda`, sum-versus-mean normalization and `.10`
   units; the within-round information/action order; the initial sentinel and
   `copy focal previous` bootstrap.
2. **Classes:** exact pure/mixed feasible sets and equations defining the
   generalist, every per-`q` specialist, and the selector's information,
   switching rule, and time of choice. A revealed `q` belongs only in its
   named control.
3. **Estimand:** whose exploitability is measured; external versus
   counterfactual policy/RP-regret; all max/min/expectation orderings; common
   versus `q`-specific floors; loss sign; and whether adaptive `q` is rerun on
   comparator histories.
4. **Ties:** optimizer sets, pure versus mixed faces, five-value median, and
   lower/upper-envelope domains. Apply the no-go above immediately if class,
   score, and floor coincide.
5. **Finite support receipt:** assert the six adapter inputs are exactly
   `{0,1} x {sentinel,0,1}`, the 64 maps are complete, the 16 histories are
   `{0,1}^4`, and `64 x 5 x 16 x 3 = 15,360` cells have no omissions or
   duplicates. Predeclare treatment of behaviorally equivalent `Q` rules.
6. **Nondegeneracy:** hand-check `H=1` and `H=2`; pin singleton-`Q` and
   revealed-type zero nulls plus symmetries; require an attainable range of at
   least `.10`, behaviorally distinct specialist optima, and selector evidence
   before an irreversible choice. Otherwise record a structural degeneracy,
   not a substantive negative result.

## Recommendation and authority boundary

**proposed:** Freeze the equations above and perform the algebraic trap check
before preregistration. If C3 intentionally uses different objectives or
floors that escape the no-go, name them and narrow any eventual claim to the
exact finite microgame and statistic. Do not claim novelty for frozen-solo
adapters, generalist-versus-specialist selection, partner inference, or
selector regret separately; the cited papers already occupy those pieces.
Only after the definitions are fixed should a new targeted collision search
judge the resulting exact claim.

This evidence note authorizes no thesis choice, preregistration, study,
enumeration, integration, model allocation, service change, network action,
or capital action.
