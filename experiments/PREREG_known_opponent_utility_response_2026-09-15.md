# Known-opponent utility response: registered pilot

This is a prospective engineering study under campaign
`v2-known-opponent-utility-20260915`. It tests model-agent behavior in a
disclosed eight-round public-goods game; it does not claim a new repeated-game
theorem, human behavior, market profit, or a scientific L1–L5 finding. The
reputation and repeated-game literature is a known prior. [Huynh et al.'s
original public-goods agent study](https://arxiv.org/abs/2512.07462v2) and
[Horton et al.'s original simulated-economic-agent study](https://arxiv.org/abs/2301.07543v2)
motivate fixed payoffs, complete histories, counterbalanced labels and model
identity; they are not evidence that this local model passes the test.

The measurable question is whether a local agent selects actions consistent
with its **declared** objective against three publicly scripted opponent
regimes: all-retain, all-contribute and grim-trigger. The focal player either
maximizes own material payoff or group material payoff. The exact finite-horizon
optimal response, including ties, is computed by the existing
`bench/agentic_game_theory/optimal_control.py`. Regret is evaluated within each
declared utility and opponent regime; an own-payoff regret is not pooled with a
joint-payoff regret as if they were the same welfare measure.

The first panel has three opponent scripts × two declared utility objectives ×
two focal seat positions = **12 scheduled episodes**. Each episode schedules
one matched payoff-comprehension item and eight serial action requests, for
108 scheduled calls. One episode per condition is a transport/behavior pilot,
not an independent replication or a treatment-effect estimate. The scripts,
payoff formula, round number, full history and horizon are disclosed to the
agent; the oracle's optimal actions and regret are never disclosed. Neutral A/B
utility labels and action labels alternate across the two seat/order blocks.
Prompts, resolved policy, checkpoint, endpoint, seeds, exact tasks and cutoff
must be frozen in a separate run manifest before a model call. Existing
September 14 CPU controls and preregistration may supply **source mechanics**;
their outcomes and any frozen holdout are not new campaign observations.

The primary pilot outputs are valid action calls / all 96 scheduled action
calls, complete episodes / 12, payoff-comprehension pass / 12, exact regret
for complete episodes within each utility, and zero-regret complete episodes /
12. Report focal and group cooperation rates descriptively. A malformed or
missing action stops that episode; its valid prefix remains visible, subsequent
unissued actions remain unknown, and incomplete episodes have **no** full-horizon
regret. Every return, timeout, transport error and cutoff stays in the
denominator. Raw response streams and the oracle sequence remain private and
SHA-bound; the public result carries codes, counts and hashes only.

The study is falsified as a utility-consistency **pilot** if the agent cannot
complete episodes with valid actions or if complete episodes show positive
regret despite disclosed incentives. No post-result prompt repair, parser
relaxation, changed script or enlarged budget rescales this frozen run. A
replicated comparison needs a new preregistered seed panel and sufficient
independent episodes. The scientific novelty critic, idea-ledger
`paper_prior_exists` rejection, L1–L5 ladder and human-valid gate remain
unchanged; an applied behavioral result may be descriptive or negative while
the theoretical claim is a rediscovery.

The executable producer is
[`known_opponent_utility/pilot.py`](known_opponent_utility/pilot.py). Its
`freeze_manifest` binds a currently passed qualification receipt, the exact
allowlisted endpoint, policy, seed, all twelve tasks and source bytes before
the first call. The operator must run it inside an existing finite, monitored
model window with `admission_gate()` returning the exact registered receipt
and `safety_check()` backed by the live controller. No cron job runs this
study by itself. The independent
[`admission.py`](known_opponent_utility/admission.py) replays each private SSE,
resolved request, public action, scripted history and complete-episode DP
oracle. A shortened schedule is recorded as partial and cannot become a
full-schedule empirical bridge. Only its admitted content-free result may be
passed by [`loop_bridge.py`](known_opponent_utility/loop_bridge.py) into a
second **still eligible** preregistered campaign topic via the existing
`nara.run_iteration(experiment_outcome=...)` novelty and criticism path. This
does not make the prior theory novel; it gives the critic an observed local
behavioral outcome to assess. The third campaign topic remains queued for a
later, separately frozen iteration.

The separately timed `h1-btcusdt-rest-20260915-lab8h` BTCUSDT H1 REST
displayed-quote study is an **external
known-prior market application**. Its prospective source and later outcome can
inform an application question, but a REST reference score cannot be imported
as this model-agent study's result, executable paper fill, scientific novelty
or live-trade authorization. Its own frozen plan and source gate adjudicate it.
