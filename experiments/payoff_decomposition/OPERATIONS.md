# Payoff representation follow-up operation

This source belongs in the canonical `a_bgt_rsi` checkout before any plan or
model call. Preserve the activated utility pilot, campaign and original raw
records. The worktree used to develop this package is not its execution root.
The root operator integrates the reviewed commit, checks the resident Gemma
qualification, and freezes both exact plans from canonical source:

```bash
cd /home/decross1/projects/a_bgt_rsi
.venv-chroma/bin/python -m experiments.payoff_decomposition.queue --prepare --job-id payoff-representation-a
.venv-chroma/bin/python -m experiments.payoff_decomposition.queue --prepare --job-id payoff-representation-b
.venv-chroma/bin/python -m experiments.payoff_decomposition.queue --status --job-id payoff-representation-a
```

Panel A is eligible 2026-09-15 19:00–2026-09-16 00:00 UTC. From the same
canonical checkout, the root operator invokes the finite supervised job with:

```bash
.venv-chroma/bin/python -m experiments.payoff_decomposition.queue --dispatch --job-id payoff-representation-a
```

On a completed and independently replayed job, the dispatcher seals
`job-admission.json` exactly once. If a completed window exists but that final
receipt was not sealed, `--validate` is a publication-only recovery; it does
not call a model. An incomplete or issued partial panel stays unadmitted.
Check `--status` and the raw `dispatch-reservation.json`, `dispatch-result.json`,
`supervision.json`, `result.json` and `admission.json` receipts before drawing
any diagnostic conclusion. Queue status replays the admission chain before
reporting `admitted_attempt_verified`; a file's existence alone yields
`admission_receipt_present_unverified`.

Panel B is separately fresh and cannot run before 2026-09-16 03:30 UTC, after
the scheduled morning ingestion window, or start unless the full 1860-second service envelope
for worker plus possible parent recovery fits before 08:00 UTC.
The provided user service/timer files are **not installed or enabled** by this
package. After exact source/plan review the root operator may copy the two
unit files into the user's systemd directory, reload the user manager and
enable `payoff-representation-b.timer`. It checks availability 16 times from
03:35 to 07:20 UTC. A busy lease/idleness preflight refuses before reservation;
the next scheduled tick remains eligible. One post-reservation retry window
`payoff-representation-b-r1` is created only after independent proof that the
first worker issued no model call, never created a sentinel or stopped Nara,
and had verified no-mutation restoration. Unknown, partial, or issued cases
cannot retry. The original refusal receipts and its source hashes remain
unchanged. The timer is not a guarantee that the job admits by morning.

These numerical focal/total counts test an arithmetic instrument only. They
do not validate novelty, repair the game strategy, establish a market effect,
or authorize a trade.
