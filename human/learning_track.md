# Learning track — Phase 1 reading & problem sets

> A parallel rail for the researcher's intellectual progression
> through Phase 1. Sequenced by week with target completion windows
> but **no hard deadlines**. Block 1 work happens here.
>
> **Block 1 is NOT a `plan.yaml` precondition for Block 2.** The agent
> proceeds on apparatus build whether or not you've finished today's
> reading. This file tracks *your* progress; the agent does not query
> it. See [`../agent/autonomy.md`](../agent/autonomy.md) §7 for why.
>
> Where the human's understanding is the **content** of a task (schema
> authoring, contract authoring, expected-range pre-specification,
> publication review, architectural decisions), the relevant
> `plan.yaml` task carries `requires_human_understanding: true` and
> stays hard-gate regardless of phase boundary. Those exceptions are
> listed in §4 below.

---

## 1. The reading sequence (chapters)

Grouped by topic, sequenced by when you'll need it. Status is `not
started` / `in progress` / `done` — update in your weekly retrospective.

### Week 1 (Days 31–37)

| Chapter | Source | Target | Status |
|---|---|---|---|
| O&R Ch. 6 §6.1–6.3 | Osborne & Rubinstein, *A Course in Game Theory* | Day 31 | done |
| O&R Ch. 6 §6.4–6.5 + Ch. 7 start | O&R | Day 32 | done |
| Weibull Ch. 1 §1.1–1.4 | Weibull, *Evolutionary Game Theory* | Day 33 | done |
| Weibull Ch. 1 §1.5–end + Ch. 2 §2.1 | Weibull | Day 34 | done |
| C-B & L Ch. 1 §1.1–1.4 | Cesa-Bianchi & Lugosi, *Prediction, Learning, and Games* | Day 35 | done |
| **C-B & L Ch. 1 §1.5–end + Ch. 2 §2.1–2.3** | C-B & L | Day 36 (KEYSTONE) | in progress |
| Camerer Ch. 4 §4.3 + Fudenberg & Levine Ch. 1 §1.1–1.2 | Camerer; F&L | Day 37 | not started |

### Week 2 (Days 38–44) — critic + meta-review

| Chapter | Source | Target | Status |
|---|---|---|---|
| C-B & L Ch. 2 §2.4–2.8 (regret of MW + variants) | C-B & L | Day 38–39 | not started |
| Camerer Ch. 5 (level-k + cognitive hierarchy) | Camerer | Day 40–41 | not started |
| Horton 2023 + Aher et al. 2023 (re-read with critic in mind) | papers | Day 42 | not started |
| Bowles & Polanía-Reyes, *Economic incentives and social preferences*, intro chapter | B&P-R | Day 43 | not started |

### Week 3 (Days 45–51) — calibration + novelty

| Chapter | Source | Target | Status |
|---|---|---|---|
| C-B & L Ch. 3 (Internal regret + correlated equilibrium) | C-B & L | Day 45–47 | not started |
| McKelvey & Palfrey 1995 (QRE) | paper | Day 48 (for W2-08 holdout) | not started |
| Bandit literature primer (Lattimore & Szepesvári ch. 1–3 OR equivalent) | L&S | Day 49–51 | not started |

### Week 4 (Days 52–58) — first applied rung

| Chapter | Source | Target | Status |
|---|---|---|---|
| Myerson Ch. 3 (single-item auctions, equilibria) | Myerson, *Game Theory: Analysis of Conflict* | Day 52–54 | not started |
| Hartline notes (mechanism design intro) | Hartline | Day 55 | not started |
| Selected Polymarket / prediction-market literature | survey | Day 56–58 | not started |

### Weeks 5–13 (Days 59–90) — Phase 1 back half

To be sequenced as you reach them; placeholder for Camerer back half,
Roth & Sotomayor (matching), and a handful of papers per Day 90's
preprint scope.

---

## 2. Problem sets — the keystone problems

Phase 1 has a small number of **keystone problems** the program lists
as load-bearing. These are the problems where doing them yourself is
the difference between understanding the apparatus you're building and
just running it.

| Problem | Source | Target window | Status |
|---|---|---|---|
| Subgame-perfect equilibrium worked examples (O&R 6.1–6.3, 6.7, 6.10, 7.1) | O&R | Days 31–32 | done |
| ESS characterization (Weibull 1.1–1.3) | Weibull | Day 33 | done |
| **Replicator dynamics for hawk-dove (by hand)** | Weibull Ch. 2 | Day 34 | done |
| Hannan consistency proof structure (C-B & L 1.1, 1.2) | C-B & L | Day 35 | done |
| **Multiplicative Weights from scratch — algorithm + regret bound (by hand)** | C-B & L Ch. 2 | **Day 36 — KEYSTONE** | in progress |
| Level-k worked examples (Camerer 4.1, 4.2) | Camerer | Day 37 | not started |
| Internal-regret → correlated-equilibrium derivation (C-B & L Ch. 3) | C-B & L | Week 3 | not started |
| QRE point estimation on a toy game | derived from McKelvey & Palfrey | Week 3 | not started |
| Bandit regret bound for ε-greedy and UCB (by hand) | L&S | Week 3 | not started |
| Second-price auction equilibrium (by hand) | Myerson | Week 4 | not started |

The **MW derivation** (Day 36) is the single most important problem
in Week 1 — it's the foundation everything in the C-B & L track
builds on, and it's the first thing you'll really need for the Phase 2
critic + meta-review architecture.

---

## 3. Progress reporting cadence

- **Daily:** no reporting. The agent does not check Block 1 status.
- **Weekly:** in the retrospective at `retrospectives/weekN.md`,
  update the status column above and note: which keystone problems
  landed, which chapters slipped to next week, what surprised you.
- **Phase boundary:** at each tier-unlock attestation, the
  retrospective records that you have read enough to evaluate the
  outputs of whatever tier is being unlocked. E.g., the Phase-2 entry
  attestation requires you to attest "I have read enough to evaluate
  the next hypothesis the loop generates" (see
  [`../agent/autonomy.md`](../agent/autonomy.md) §6.5).

---

## 4. Where reading IS a hard-gate (the exception list)

The following `plan.yaml` tasks have `requires_human_understanding:
true` and stay hard-gate regardless of phase boundary. For each, the
relevant reading must be done before the task runs:

| Task | Required understanding | Relevant reading |
|---|---|---|
| `day2_block2_jsonl_schema` | Wrapper's call surface + logging granularity | Day-2 reading (`agent_wrapper/wrapper.py` docstring is its own primer) |
| `day6_block2_worker_contract` | Worker I/O contract shape | Day-6 keystone (MW derivation gives you the no-regret intuition for worker independence) |
| `day7_block2_precompute_expected_range` | Expected cooperation rate band | Horton 2023 + Aher et al. 2023 (Day 5 + Day 7 reading) |
| `day7_publication_review_gate` | What's publishable vs preliminary | Sakana + Mitchell critique (Day 1 + Day 2 reading) |
| Phase 2 hypothesis-generation onboarding | Theoretical grounding for a hypothesis | Topic-specific |
| Architectural decision points (new `D-NNN`) | Trade-off analysis | Context-dependent |
| System-failure escalations | Triage + recovery direction | Context-dependent |

For these tasks, the agent halts and the human is *the* required
input. Block 1 progress for that day's reading is implicitly assumed
but not checked.

---

## 5. What's NOT here

- **The daily plan** lives in [`daily_plan.md`](daily_plan.md). This
  file is a sequenced syllabus; the daily plan is your prescribed
  cadence.
- **The reading PDFs** live in `books/` (gitignored). This file is the
  table of contents.
- **The agent's running tasks** live in `plan.yaml` and `current_day.md`.
  This file does not track them.
