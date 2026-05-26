# Reading list — Phase 1 quick reference

> Quick-reference index of every Phase 1 reading, grouped by source.
> Use when you finish a chapter ahead of schedule and want to know
> what's next.
>
> For the **sequenced** reading rail (week-by-week), see
> [`learning_track.md`](learning_track.md).

---

## Textbooks (pre-staged in `books/`)

### Osborne & Rubinstein, *A Course in Game Theory*

Foundations of strategic-form and extensive-form games. Week 1.

- Ch. 6 §6.1–6.3 — extensive games with perfect information; Nash, SPNE intro
- Ch. 6 §6.4–6.5 — SPNE refinements
- Ch. 7 §1 — one-deviation principle, repeated games intro

### Weibull, *Evolutionary Game Theory*

Population dynamics, ESS, replicator dynamics. Days 33–34.

- Ch. 1 §1.1–1.4 — population states; ESS characterization
- Ch. 1 §1.5–end — extended ESS material
- Ch. 2 §2.1 — replicator dynamics intro
- Ch. 2 §2.2 onward — Phase 2 candidate

### Cesa-Bianchi & Lugosi, *Prediction, Learning, and Games*

No-regret learning, multiplicative weights. **Keystone for Phase 2
architecture.**

- Ch. 1 §1.1–1.4 — Hannan consistency, regret framework — Day 35
- Ch. 1 §1.5–end — Ch. 2 §2.1–2.3 — **Multiplicative Weights derivation — Day 36 (KEYSTONE)**
- Ch. 2 §2.4–2.8 — MW variants, regret bounds — Week 2
- Ch. 3 — internal regret, correlated equilibrium — Week 3
- Ch. 4+ — Phase 2 candidate

### Camerer, *Behavioral Game Theory*

Learning-in-games, cognitive hierarchy, level-k. Days 34–37.

- Ch. 4 §4.1–4.2 — learning models, EWA intro — Day 34
- Ch. 4 §4.3 — cognitive hierarchy, level-k — Day 37
- Ch. 5 — level-k applications — Week 2
- Ch. 4 §4.4 onward — Phase 2 candidate

### Fudenberg & Levine, *The Theory of Learning in Games*

Learning-in-games formalism. Day 37+.

- Ch. 1 §1.1–1.2 — learning-in-games framing — Day 37
- Ch. 2 onward — Phase 2

### Myerson, *Game Theory: Analysis of Conflict*

Mechanism design foundations. Week 4.

- Ch. 3 — single-item auctions — Week 4
- Ch. 4 onward — Phase 2

### Bowles & Polanía-Reyes, *Economic incentives and social preferences*

Crowding-out, social motivations. Week 2+.

- Intro chapter — Week 2

### Hartline, *Mechanism Design and Approximation* (notes)

Mechanism design intro for the applied-tier rung ladder. Week 4.

### Lattimore & Szepesvári, *Bandit Algorithms*

Bandit selection for multi-candidate generation (W2-12). Week 3.

- Ch. 1–3 — bandit primer — Week 3
- Ch. 4 onward — Phase 2

---

## Papers (pre-staged in `papers/`)

### Apparatus / loop literature

- Lu et al. 2024 — *The AI Scientist* (Sakana) — Day 1
- Melanie Mitchell critique of Sakana — Day 2
- Matt Welsh thread — Day 2
- Hart & Mas-Colell 2000 — *A Simple Adaptive Procedure Leading to
  Correlated Equilibrium* — Day 3
- Horton 2023 — *Large Language Models as Simulated Economic Agents*
  (homo silicus) — Day 6
- Aher, Arriaga & Kalai 2023 — *Using LLMs to Replicate Human Subject
  Studies* — Day 5

### Game theory / mechanism design

- McKelvey & Palfrey 1995 — *Quantal Response Equilibria for Normal
  Form Games* — Week 3 (used as W2-08 holdout target)
- Selected Polymarket / prediction-market literature — Week 4

### Phase 2+ candidates

- Sutton & Barto, *Reinforcement Learning* — Phase 2
- ~~A second model-comparison primer (Qwen 3.6 vs Gemma 4) — Week 2-3~~
  Dropped 2026-05-26 (D-033): single-model apparatus on Gemma 4.

---

## Ambient listening (one episode/day)

This is the 14:30–15:30 slot. No notes; just listening on a walk. Not
sequenced; pick what sounds good that day. Past picks worth revisiting:

- Dwarkesh Patel — agent infrastructure
- EconTalk with Al Roth — market design
- ML Street Talk — RAG / agents
- Complexity Podcast — evolution of cooperation
- Rationally Speaking — epistemics
- A keynote from Simons / NeurIPS workshop / AAMAS on game theory + LLMs

---

## Reading-list discipline

- **Don't try to read ahead of the cadence.** The chapters are
  sequenced for what the apparatus needs that day. Reading Camerer
  Ch. 6 before you've done Ch. 4 will not help you on Day 37.
- **Don't skip the keystone problems.** Reading without working a
  problem is a form of intellectual fast-fashion. The MW derivation
  (Day 36) and replicator dynamics for hawk-dove (Day 34) are the
  ones you'll actually use.
- **If you fall behind, fall behind on chapters, not on keystone
  problems.** A missed chapter is recoverable; a missed keystone
  problem leaves you running an apparatus you don't understand.
- **Phase 2+ candidates are not your problem until they are.** Don't
  read Sutton & Barto in Week 2 because it looks important; it is
  scheduled later, when the loop architecture actually needs it.
