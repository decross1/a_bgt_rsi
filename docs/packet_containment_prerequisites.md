# Packet candidate checks and outstanding execution prerequisites

Candidate work `LAB-DEVELOPMENT-20260905-002-S3`, based on
`56a0749c3e4f1094be3243036f8388b386f8afdc`. This document is an inert
development specification. `workers/packet_checks.py` is not wired into the
dispatcher, self-improver or daemon and does not authorize a worker.

The checks accept independently supplied expected identities. A model cannot
make its receipt trusted by supplying those expectations itself. Typed argv,
exact red assertion identity and a verified diff are useful admission and
candidate checks; none prevents an executable test from affecting the host.
The current generated acceptance/builder path remains unusable for this work.

Before live execution, the owning protected packet must demonstrate:

1. Generated tests, preconditions and worker code execute only in an OS-confined
   candidate with a read-only base/primary checkout, private home/temp,
   constrained writable output, process/capability limits and denied or mediated
   network. A local model requires a governed broker/endpoint capability; an
   unrestricted networked builder is not a no-network worker.
2. A trusted versioned runner, outside candidate write scope, supplies the
   actual collection/setup/call/teardown results, exception identity and reason
   fingerprint. Exit 1 alone is not valid red evidence. Test source and command
   bytes are bound to the admitted contract before execution and before base
   capture can be influenced. Candidate-authored tests are not sole promotion
   evidence.
3. A trusted Git adapter captures full base/before/after and diff hashes and
   feeds NUL-delimited `git diff --raw -z --no-abbrev -M` bytes into scope
   checking. Both rename endpoints, mode-only changes, additions and deletions
   count. This candidate conservatively refuses symlinks, gitlinks, copies,
   unmerged entries and non-UTF8 names; tabs/newlines in UTF-8 names are preserved.
   Detection of an out-of-scope diff is separate from prevention of external
   writes or secret reads. Untracked/generated-file and diff-line budgets need
   additional trusted Git/working-tree observations.
4. The builder must exit zero before it may submit a new clean commit.
   Verification and scope receipts bind the exact candidate and diff. Worker
   and verifier identities are independently admitted; differing names alone
   are not a statistical independence guarantee. A no-change task uses an
   explicit abstention/outcome path, not a fabricated new candidate.
5. One protected approved worker profile binds model/artifact/server/context/
   tool/qualification cursor and sandbox policy. Discovery and returned model
   IDs must agree exactly; their freshness and authenticity need independent
   evidence. A profile hash and matching names do not qualify coding competence.
   No registry, model pin, service or role is changed by this candidate.
6. Queue ownership uses a locked durable claim/lease/fence/acknowledgement
   adapter. Ordinary authorize-fix intake is not an executable packet: the
   current empty-scope/empty-test skeleton must not poison repeated first-row
   dispatch. Live replay must never redispatch terminal work.

Adversarial OS tests must prove an external sentinel is unchanged, a canary
credential cannot be read, a symlink cannot escape, an unapproved endpoint is
unreachable, and no surviving child can act after revocation. Python audit
hooks and post-hoc diff checks are not substitutes for those demonstrations.

Current source evidence: `orchestrator/self_improve.py:838-860`,
`orchestrator/packet_dispatcher.py:71-75,176-300,356-401`,
`orchestrator/nara_daemon.py:299-324`, `tools/qwen_builder.sh:37-64,217-264`,
and `tools/premerge_check.sh:53-89`. The mechanical gate protects only one
schema file even though `docs/packet_sdlc.md:121-130` protects all schemas;
the scanner also does not represent every model pin. Passing that scanner
cannot ratify a protected change.

The existing manual's statement that daemon dispatch is absent is stale: a
dark guarded seam exists. Neither that documentation inconsistency nor these
checks authorize `NARA_SELF_IMPROVE` or `NARA_PACKET_DISPATCH`. Schema,
run-state, model/policy and generic orchestrator integration still need exact
owning classification, review, full green validation and an applicable real
smoke. Keep old ledgers unchanged.
