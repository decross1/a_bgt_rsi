# exp002 — LOOP_V0 robustness battery on the three Phase-2 topics

_Each topic re-run 5× with the chain's default sampling (no seed plumbing)._
_Total rows in `results.jsonl`: 15._

Per-topic tables follow. The headline interpretation is in `notes.md` (human-written, per CLAUDE.md inviolate rule #9).

---

## topic_1_open_bayesian_pgg

- **Diagnostic role**: `open`
- **Human priors**: novelty=`unclear` / verdict=`restated`
- **n runs**: 5 (errors: 0, ok: 5)
- **Wall-clock**: mean 29.5 s, sd 3.6 s
- **Distinct chosen hypotheses**: 1/5

**Novelty class distribution**

| class | count |
|---|---|
| `novel` | 5 |

**Critic verdict distribution**

| verdict | count |
|---|---|
| `survives` | 5 |

**Critic sub-agent status distribution**

| status | count |
|---|---|
| `passed` | 5 |

**Top-neighbor (novelty) distribution**

| doc_id | count |
|---|---|
| `2605.23513` | 4 |
| `(null)` | 1 |

**Chosen hypotheses (verbatim)**

  1.   In repeated public goods games with noisy contribution observation, conditional cooperators using a Bayesian belief over others' types will exhibit faster contribution decay than under perfect observation, even when expected observation error is mean-zero.
  2. ↺ In repeated public goods games with noisy contribution observation, conditional cooperators using a Bayesian belief over others' types will exhibit faster contribution decay than under perfect observation, even when expected observation error is mean-zero.
  3. ↺ In repeated public goods games with noisy contribution observation, conditional cooperators using a Bayesian belief over others' types will exhibit faster contribution decay than under perfect observation, even when expected observation error is mean-zero.
  4. ↺ In repeated public goods games with noisy contribution observation, conditional cooperators using a Bayesian belief over others' types will exhibit faster contribution decay than under perfect observation, even when expected observation error is mean-zero.
  5. ↺ In repeated public goods games with noisy contribution observation, conditional cooperators using a Bayesian belief over others' types will exhibit faster contribution decay than under perfect observation, even when expected observation error is mean-zero.

---

## topic_2_rediscovery_probe

- **Diagnostic role**: `should-be-rediscovery`
- **Human priors**: novelty=`rediscovery` / verdict=`restated`
- **n runs**: 5 (errors: 0, ok: 5)
- **Wall-clock**: mean 26.2 s, sd 1.1 s
- **Distinct chosen hypotheses**: 1/5

**Novelty class distribution**

| class | count |
|---|---|
| `rediscovery` | 5 |

**Critic verdict distribution**

| verdict | count |
|---|---|
| `survives` | 5 |

**Critic sub-agent status distribution**

| status | count |
|---|---|
| `passed` | 5 |

**Top-neighbor (novelty) distribution**

| doc_id | count |
|---|---|
| `blume_1995-chunk-92` | 5 |

**Chosen hypotheses (verbatim)**

  1.   In symmetric 2x2 coordination games played on a fixed network, fictitious play with uniform priors converges to the risk-dominant equilibrium more often than to the payoff-dominant one as the population grows.
  2. ↺ In symmetric 2x2 coordination games played on a fixed network, fictitious play with uniform priors converges to the risk-dominant equilibrium more often than to the payoff-dominant one as the population grows.
  3. ↺ In symmetric 2x2 coordination games played on a fixed network, fictitious play with uniform priors converges to the risk-dominant equilibrium more often than to the payoff-dominant one as the population grows.
  4. ↺ In symmetric 2x2 coordination games played on a fixed network, fictitious play with uniform priors converges to the risk-dominant equilibrium more often than to the payoff-dominant one as the population grows.
  5. ↺ In symmetric 2x2 coordination games played on a fixed network, fictitious play with uniform priors converges to the risk-dominant equilibrium more often than to the payoff-dominant one as the population grows.

---

## topic_3_deliberately_wrong

- **Diagnostic role**: `should-be-falsified-deliberately-wrong-claim`
- **Human priors**: novelty=`nonsense` / verdict=`falsified`
- **n runs**: 5 (errors: 0, ok: 5)
- **Wall-clock**: mean 28.1 s, sd 6.8 s
- **Distinct chosen hypotheses**: 3/5

**Novelty class distribution**

| class | count |
|---|---|
| `nonsense` | 5 |

**Critic verdict distribution**

| verdict | count |
|---|---|
| `falsified` | 5 |

**Critic sub-agent status distribution**

| status | count |
|---|---|
| `passed` | 5 |

**Top-neighbor (novelty) distribution**

| doc_id | count |
|---|---|
| `(null)` | 5 |

**Contradicting-paper (critic) distribution**

| doc_id | count |
|---|---|
| `osborne_rubinstein-chunk-852` | 5 |

**Chosen hypotheses (verbatim)**

  1.   {
  "candidates": [
    "In finitely repeated prisoner's dilemmas with common knowledge of rationality, subgame perfect equilibrium predicts cooperation in the penultimate round when the stage-game cooperation payoff exceeds twice the defection payoff.",
    "In finitely repeated…
  2.   In finitely repeated prisoner's dilemmas with common knowledge of rationality, subgame perfect equilibrium predicts cooperation in the penultimate round when the stage-game cooperation payoff exceeds twice the defection payoff.
  3. ↺ In finitely repeated prisoner's dilemmas with common knowledge of rationality, subgame perfect equilibrium predicts cooperation in the penultimate round when the stage-game cooperation payoff exceeds twice the defection payoff.
  4. ↺ In finitely repeated prisoner's dilemmas with common knowledge of rationality, subgame perfect equilibrium predicts cooperation in the penultimate round when the stage-game cooperation payoff exceeds twice the defection payoff.
  5.   {
  "candidates": [
    "In finitely repeated prisoner's dilemmas with common knowledge of rationality, subgame perfect equilibrium predicts cooperation in the penultimate round when the stage-game cooperation payoff exceeds twice the defection payoff.",
    "In finitely repeated…

---
