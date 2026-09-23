# Thesis candidates for G1.1

## Candidate 1: Anchoring in cheap talk

### Title
Anchored priors survive cheap talk in LLM sender-receiver games.

### Question and mechanism
An initial numeric anchor given to a receiver shifts its posterior even when the
sender's message is verifiably uninformative; the mechanism is insufficient
adjustment from an explicitly given starting value.

### Lens
1 (behavioral economics, Kahneman): anchoring applied to belief updating.

### Prior work
Anchoring in human judgment (Tversky and Kahneman, 2002); LLM anchoring studies
(ars-2310-09558); this is an extension to a game setting. New for uninformative
senders.

### T · theory
A Bayesian sender-receiver game with a binary state and uninformative messages,
solved exactly in OpenSpiel; the benchmark is the Bayes-plausible posterior; the
preregistered decision rule is a posterior shift of at least 0.05 with a paired
sign test at p<0.05.

### S · semi-synthetic
Flash agents in the same game with an anchor arm and a no-anchor arm; n=200
paired trials; outcome is posterior deviation; a non-numeric answer is scored
missing and excluded with the count reported.

### A · applied
Prediction-market quotes, tested on paper only; needs historical quote snapshots
and question text.

### Falsifier
No posterior shift at T under the exact Bayesian benchmark.

### Anomaly map
- A shift larger than the human effect would suggest the anchor is being read as
  content rather than as a starting value.
- No shift at T but a shift at S would suggest a prompt-surface mechanism.

### Cost
About 12 Flash hours for T and S plus one day of build.

### Conviction (D-087)
- p_pass_T: 0.6 because the benchmark is exact
- p_pass_S: 0.5 because local models are noisy
- p_pass_A: 0.3 because quote data is coarse
- p_dead_end: 0.2 because anchoring may be a prompt artifact
- interest_0_10: 7 because it is cheap and falsifiable

## Candidate 2 Order effects and the QQ test

**Title:**
Question order changes LLM belief reports beyond classical conditioning.

**Question and mechanism:**
Asking q before r changes the answer to r by more than classical conditioning
allows; the mechanism is interference between questions.

**Lens:**
2 (quantum-probability models of cognition, Deutsch): a formal order-effect model
against a classical Bayesian baseline that predicts order invariance, separated
by the published QQ-equality test.

**Prior work:**
QQ equality in judgment order effects (ars-1905-05216); this is a replication on
LLM agents, and new for local open weights.

**T · theory:**
A two-question decision problem over a fixed belief state with an exact
classical posterior benchmark and a QQ test; the decision rule is a violation
in at least 10 percent of states.

**S · semi-synthetic:**
Flash agents answering both question orders; arms are order AB and BA; n=400
responses; outcome is the order-effect magnitude; refusals are counted missing
and reported.

**A · applied:**
Options-implied probability elicitation as a no-capital venue; needs option
chain history.

**Falsifier:**
No QQ violation at T against the exact classical benchmark.

**Anomaly map:**
- Violations that vanish with longer prompts suggest an attention boundary
  condition, so the follow-up tests prompt length.
- Violations only for numeric questions suggest formatting, so the follow-up
  tests a format control.

**Cost:**
About 20 Flash hours and two days of build.

**Conviction (D-087):**
- p_pass_T: 0.55 because the test is exact
- p_pass_S: 0.45 because order effects are small
- p_pass_A: 0.25 because the market mapping is indirect
- p_dead_end: 0.3 because a formal model may not fit
- interest_0_10: 8 because the discriminator is published

## Candidate 3

| Field | Content |
|---|---|
| Title | A prepared specialist beats a generalist in a solved small game. |
| Question and mechanism | A narrow strategy tuned against a generalist's equilibrium play wins where unprepared opponents lose; the mechanism is exploitation of a fixed policy. |
| Lens | 3 (agents in strategic games): counter-picking and cheese strategies, abstracted into a solvable game rather than Civilization VI. |
| Prior work | Exploitable-strategy literature (ars-2502-00578); an extension to LLM policy families, and new for a solved 2x3 domain. |
| T · theory | A solved 2-player matrix game in OpenSpiel with an exact equilibrium benchmark; the decision rule is a payoff gap of at least 0.1 over 100 playouts. |
| S · semi-synthetic | Flash agents as specialist and generalist arms; n=300 matches; outcome is payoff differential; dropped matches are counted missing. |
| A · applied | Crypto funding-rate paper trading as a proposal; needs public funding-rate history. |
| Falsifier | The generalist's equilibrium is unexploitable in the exact computation. |
| Anomaly map | - No exploitable gap would suggest the generalist is already near-equilibrium, pointing at a convergence study. - A gap that reverses with a second specialist would suggest a metagame cycle and a follow-up on cycle length. |
| Cost | About 9 Flash hours for T and S plus half a day of build. |
| Conviction (D-087) | - p_pass_T: 0.7 because the game is small and solved - p_pass_S: 0.5 because LLM play is noisy - p_pass_A: 0.2 because funding rates are thin - p_dead_end: 0.15 because the domain may be too small - interest_0_10: 6 because it is a warm-up for a bigger game. |
