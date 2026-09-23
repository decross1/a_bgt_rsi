# Thesis brief: information and beliefs (owner direction, 2026-09-23)

Status: **the brief for goal G1.1.** Nara generates 3–5 candidate theses from
it on local weights. Oracle screens them, the meta-oracle reviews the screen,
and the owner picks one; it becomes the focus through the G0.2 selection CLI.
Nothing here is a hypothesis: under D-061 the meta-oracle frames the brief
and does not write theses. See D-086 for the owner's words.

## Direction

**Area:** how agents form, share and update beliefs, i.e. information and
beliefs, studied with LLM agents in game-theoretic settings (the program's
field, `docs/sources/research_program_v2.md`).

**Lenses the owner is interested in.** A candidate should draw on at least one
and say which:

1. **Behavioral economics (Kahneman).** Heuristics and biases in judgment
   under uncertainty: anchoring, base-rate neglect, framing, loss aversion,
   overconfidence, fast versus deliberate reasoning. Question: which human
   biases do LLM agents share, lack, or invert, and why?
2. **Quantum information and belief (Deutsch; quantum-probability models of
   cognition).** Information as physical and constrained in how it can be
   copied and spread; quantum-probability models of judgment, such as order
   effects and interference between questions. **Rigor requirement:** any
   quantum framing needs a formal model and a classical Bayesian baseline that
   makes a different, testable prediction (for order effects, the published
   QQ-equality test is the known discriminator). Metaphor alone is rejected.
3. **Agents in strategic games.** Counter-picking and counter-swapping,
   one-trick specialization against generalists, cheese strategies (cheap
   exploits a prepared opponent beats), and how a metagame adapts to them,
   with games like Civilization VI as inspiration. For T and S these must be
   abstracted into games that can be specified and solved; Civ6 itself is
   not an environment.

A candidate that joins two lenses (for example, a bias that shapes how agents
spread information in a game) is welcome but must stay testable at T.

## Candidate template (every field required)

| Field | Content |
|---|---|
| Title | One sentence |
| Question and mechanism | What happens, and through what mechanism |
| Lens | 1, 2 or 3 above, and how it is used |
| Prior work | The closest existing results (retrieve from the lab's paper store and the literature; cite them) and whether this is a replication, an extension or new |
| **T · theory** | A game or decision problem solvable with OpenSpiel or an exact computation; the benchmark (equilibrium, Bayesian posterior); the preregistered decision rule |
| **S · semi-synthetic** | LLM agents on local Flash in a designed version of that game; arms, sample, outcome and missing-data rule |
| **A · applied** | The market this would be tested in (options, prediction markets, crypto, or another no-capital venue) and what data it needs; for now a proposal only |
| Falsifier | The result that kills it at T |
| **Anomaly map** | For each plausible *unexpected* outcome at T or S: what it would suggest (a different mechanism, a related effect in the literature, a boundary condition) and the follow-up hypothesis it would lead to |
| Cost | Rough Flash hours and build effort for T and S |

## How candidates are judged

- **Testable at every stage**, with an exact benchmark at T.
- **Informative when it fails.** Prefer candidates whose anomaly map has
  several rich branches over ones where a null result ends the line. This is
  the owner's main concern.
- **Novel or a declared replication**, checked against the paper store.
- **Honest applied route**, with the data the market needs named.
- **Fits the apparatus.** It is buildable on Flash with the lab's runners, and
  its results would say something about the apparatus itself (the program's
  central question).

## Learning from anomalies (the refinement protocol)

The owner does not want refutation to be the end of the story. When a result
fails or surprises, the lab asks what it relates to, whether it can be built
on, and whether it gives a new insight that refines the campaign. The
safeguards:

1. **Record first.** The original result and its preregistered verdict are
   kept exactly as they came out. It is never relabelled as a success.
2. **Explain second.** Nara writes an anomaly note: what was unexpected, the
   candidate explanations (starting from the anomaly map), and the related
   work each points to.
3. **Branch, don't bend.** Every follow-up is a **new hypothesis with its own
   preregistration and data**, linked to its parent as a branch. The data that
   suggested it cannot also confirm it.
4. **Decide.** The thesis continues, branches, or is killed. A killed parent
   with a promising branch is normal: the branch becomes a successor thesis.
5. **Credit the insight.** Anomaly notes that lead to a confirmed branch count
   as findings of the apparatus, the thing the program is trying to show.

The meta-oracle reviews every anomaly note and branch for HARKing
(hypothesising after the results are known) and for reuse of confirmatory
data.

## Literature scouting (always on)

Owner direction: scouting never stops, and the paper store keeps growing.
Every ingested paper is embedded (already done by the 03:00 arXiv job into
`chroma_db`). What changes: while a thesis is active, each new paper is
scored for relevance to it. A related paper is linked to the thesis as related
work, prior art or new evidence, and can prompt an anomaly note or a
refinement. An unrelated paper is stored for future theses. Unrelated
single-paper hypotheses are no longer the default cycle output. This is goal
G1.2.
