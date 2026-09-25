# C3 identity-adapter payoff screen — 2026-09-25

Status: **evidence-only G1.1 feasibility screen; stop / no preregistration.**
This note is not a preregistration, a novelty claim, or evidence against the
underlying thesis. It independently checks one conditional completion of the
proposed C3 T0 instrument. It authorizes no `research_focus`, study, experiment,
runner, Nara lane item, Flash or network use, service/runtime change, or capital.

## Accepted source boundary

- **Observed:** `PREREG_DESIGN_CONSTRAINTS.md` at
  `e6d3dbd2256568e7239dbbf920a40f79db1758d2`
  (Git blob `c9f7c323867de8d01b1b03f78769b6a3ee509457`), especially
  lines 47-69 (common-class no-go), 79-100 (options 1 and 2), 118-134
  (admission rule), 136-171 (undefined equations), and 173-195 (stop
  boundary).
- **Observed:** `T_GATE_CHOICE.md` at
  `e023d74eb7b15ad25582816129f28e9168517dd6`
  (Git blob `7c25a4d15ee677f37ddf9b28f091caa84d1061f7`), especially
  lines 54-75 (model and predicate), 151-171 (stop conditions), 182-189
  (no authorization), and 201-216 (enumeration factors and missing payoff
  unit). The same blob is present in `e6d3dbd`.
- **Observed:** the declared model has `pi0(x)=x`, `H=4`,
  `lambda in {.25,.5,.75}`, five partner types, and 64 binary deterministic
  maps over six `(x, prior-partner-action)` states. The pass condition is the
  lower optimizer-tie envelope of generalist-minus-median-specialist excess
  selector regret `>= .10` at **every** declared `lambda`.
- **Observed limitation:** the accepted constraints leave the stage-payoff
  unit, adapter output, within-round order, copy-previous transition and
  bootstrap, comparator, score/floor, specialist aggregation, and pure-versus-
  mixed tie domain undefined. Options 1 and 2 are therefore design sketches,
  not evaluable instruments.

## Conditional identity-adapter screen

**Assumptions for this screen, not new C3 definitions.** Adopt only the payoff
candidate already recorded at constraints lines 141-145,

```text
V_lambda,H = (1/H) sum_t [
    (1-lambda) 1{y_t = x_t} + lambda 1{y_t = z_t}
].
```

Treat each enumerated `x` history as fixed while comparing policies. For
`copy focal previous`, use the literal local transition `z_t = y_(t-1)` for
`t >= 2`; its `t=1` bootstrap is either common/fixed across compared policies
or local in `y_1`. Recompute the induced `z` trajectory for each policy, as the
ex-ante comparator at constraints lines 153-155 requires. No conclusion below
is asserted for a nonlocal or policy-global bootstrap, another payoff, or
another counterfactual rule.

**Inferred (identity is feasible under either named output interpretation):**
the six-state binary map `a_I(x, p) = x` is one of the 64 maps. If the adapter
outputs an action, it directly gives `y_t=x_t`. If it outputs an observation,
the frozen identity policy gives `y_t=pi0(x_t)=x_t`.

**Inferred (non-copy types at `lambda=1/4`):** for `always0`, `always1`,
`follow x`, and `invert x`, the partner action is not changed by the candidate
focal action. Every deviation `y_t != x_t` loses `3/4` in the own-match term
and can gain at most `1/4` in the partner-match term. Identity is therefore
strictly optimal on every fixed history.

**Inferred (copy-previous dynamic bound at `lambda=1/4`):** for a candidate
trajectory `y`, let

```text
D = {t : y_t != x_t},       k = |D|.
```

Relative to identity, the own-match part loses exactly `(3/4)k`. Under
`z_t=y_(t-1)`, partner matches are equality edges on the action path. Changing
`k` action vertices can improve only their incident edges, at most `2k` edges;
overlap only lowers that bound. Their total possible improvement is therefore
at most `(1/4)(2k)=k/2`. A fixed bootstrap contributes one boundary edge; a
current-action bootstrap makes that first match constant. Both obey the same
degree bound. Hence, before or after division by `H`,

```text
V_1/4,H(a_I, q_copy, x) - V_1/4,H(a, q_copy, x)
    >= [(3/4)k - (1/2)k] / H
     = k / (4H).
```

This is positive whenever the realized action trajectory differs from
identity. It explicitly accounts for the fact that `y_t` changes future
`z_(t+1)`; it is not a pointwise proof that incorrectly holds `z` fixed. It
applies to `H=1`, `H=2`, and the declared `H=4` (and the same local path model
at other finite horizons), without needing independence among `x_t`, because
the comparison is historywise.

**Inferred conditional consequence:** under these assumptions, `a_I` is a
simultaneous best response for all five `q` at `lambda=1/4`. Thus any regret

```text
R(a,q) = max_b E_h[V(b,q,h)] - E_h[V(a,q,h)]
```

has `R(a_I,q)=0` for every `q`. If option 1 uses uniform average regret for
selection and worst-case regret for evaluation, both scores and the worst-case
floor are zero at `a_I`. Per-`q` specialists may also choose `a_I`, with zero
own-score or common-score excess. The optimizer cross-product consequently
contains a difference of zero, so its **lower** tie envelope is at most zero at
`lambda=1/4`, not at least `+0.10`. One failed declared lambda is enough to
fail the all-three-lambda predicate.

This is a conditional instrument screen, not a universal negative theorem.
The accepted text has not adopted the payoff and transition assumptions used
above; declining them leaves feasibility **unknown**, not positive.

## Options 1 and 2, and the surviving no-go

- **Observed / inferred, option 1:** the accepted text names selection score
  `M` and evaluation score `S` but does not define either equation, the floor,
  or the specialist excess. Different selection and evaluation scores can
  evade the original argmin identity in the abstract. The conditional screen
  shows that the recorded payoff candidate does not supply the required
  witness at `lambda=1/4` under the natural mean-regret / worst-regret
  completion.
- **Observed / inferred, option 2:** per-`q` specialist scoring and joint
  generalist scoring are explicitly on different scales. If each excess is
  taken relative to the minimum of the score that selected it, both selected
  excesses are zero by definition. If raw unlike scores are subtracted instead,
  the threshold has no common unit. A matched-coverage equation and a justified
  common normalization are prerequisites, not details to choose after seeing
  results.
- **Observed:** the common-class minimax no-go remains exact. If
  `S(a)=max_q R(a,q)`, `v=min_a S(a)`, `g in argmin_a S(a)`, and all compared
  policies use that score and class, then `E(g)=S(g)-v=0` while every specialist
  excess is nonnegative. Therefore
  `E(g)-median_q E(s_q) <= 0`. Neither underdefined option rebuts this result.

## Exact admission and stop boundary

Before preregistration, a proposed replacement must define the dynamics,
payoff and units, comparator, policy and information classes, selection scores,
floors, specialist score, and pure or mixed optimizer domains. With

```text
G_lambda       = argmin_g M_lambda(g),
P_q,lambda     = argmin_s C_q,lambda(s),
L_lambda       = min over g in G_lambda and
                  (s_q)_q in product_q P_q,lambda of
                  [E_g,lambda(g) - median_q E_s,q,lambda(s_q)],
```

the required exact witness is

```text
L_1/4 >= 1/10,    L_1/2 >= 1/10,    L_3/4 >= 1/10,
```

under one declared normalization and over every declared optimizer tie. A
positive value at only one lambda, a favorable tie selection, or a post-screen
change of threshold does not satisfy the predicate.

**Proposed G1.1 disposition:** Oracle/Nara should record stop / no-preregistration
and close the current C3 T0 instrument without enumeration. Any later G1.1
continuation must arrive separately as one genuinely new, equation-complete
instrument for review. It must predeclare a changed payoff,
transition/information structure, selection versus evaluation score, comparator
class, or normalized baseline and then satisfy the same all-three-lambda witness
obligation before enumeration. It is a revised claim, not a numerical repair of
this one, and this note does not authorize it.
