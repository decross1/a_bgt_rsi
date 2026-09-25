# D-084–D-087 source-port reconciliation (2026-09-25)

**Status:** implementation-status note. It does not amend or rewrite the
historical decisions, owner quotations, or the two source documents. It records
which statements are historical, what a current operator may rely on, and what
remains unimplemented on this branch.

## Provenance and scope

This branch ported only the following committed Flash sources onto
`origin/main` commit `ba302f803407f21ffe9696fcadd107059ffd28c0`:

| Material | Committed source | Source blob |
|---|---|---|
| D-084 | `580b0376` | `DECISIONS.md` `1441bacb67fbb703f4d2485b0bd3892382bd615f` |
| D-085 | `d38cb83a` | `DECISIONS.md` `d0a25bb8f3906f2e96b9023ece40c85e2c94a517` |
| D-086 | `12ef9c63` | `DECISIONS.md` `8c80eafd8fa33fa691d9de182b3ed036206f7a2a` |
| D-087 and the final source documents | `a4ccb77e` | `DECISIONS.md` `adc0491ca083c14cb660a8ca20aee2b61924a967`; alignment `11e969cf4a8e7f28d557aa15499e2c8ba127830a`; brief `524ae8f8f89f5ad5e91dd616ca2caa5c96f86c99` |

The committed decision text is preserved verbatim in [DECISIONS.md](../../DECISIONS.md).
`ALIGNMENT_AND_GOALS.md` and `THESIS_BRIEF_2026-09-23.md` are source snapshots,
not a claim that every dated implementation/status sentence holds on current
`main`. Current runtime or implementation state must be established from the
current commit, receipts, and tests.

## Effective interpretation after the 2026-09-25 owner direction

The owner clarified that they do not want to participate in choosing the next
thesis: "it should be a decision of nara or oracle." This changes the operating
procedure implicit in the historical phrases "the owner picks one" and "selected
by the owner"; it does not alter the preserved quotations or the T/S/A ladder.

For a future, properly implemented selection path:

1. Nara generates the 3–5 candidates within D-086's information-and-beliefs
   direction and the thesis brief template.
2. Oracle screens and selects one after the required upstream evidence and
   review; the meta-oracle independently reviews the proposed selection.
3. No Derrick decision card is required for that non-live research choice.
4. A live-trading path still requires Derrick's explicit approval. The T/S/A
   ladder, preregistration, independent review, negative-result retention, and
   kill/reopening receipts remain required.

This is an operating clarification, not proof that the current implementation
can safely make the selection. A same-UID mailbox sender can currently imitate
roles, and the selection port under separate review is not approved for merge or
use. Until a default-deny, independently attributable reviewer/role mechanism is
verified and the selector's guard chain is tested, no code path may treat this
note as authorization to activate or select a focus.

## Host and scheduler boundary

D-084's historical phrase that "timers ... may proceed" does not authorize a
host-service, scheduler, security-policy, credential, or persistent-service
change. The repository `AGENTS.md` operating contract governs that boundary and
requires explicit human gating for host lifecycle changes. In particular, its
five-minute Oracle timer rule requires a reviewed commit-pinned verified runtime
snapshot before it can be active. The currently disabled Nara, Pi/Oracle, and
related loop timers remain disabled; this source-only documentation port changes
none of them.

## Implementation gaps carried forward

- **D-085 is historical policy, not an implementation claim on this branch.**
  Its source commit also changed coordinator, daemon, registry, and tests, but
  those code changes are intentionally not part of this port and are absent from
  `ba302f80`. Do not assume `COORDINATOR_DAILY_CAP` or `TOPIC_DAILY_CAP` defaults
  from D-085 are in force here.
- **D-087 is not implemented by this documentation port.** There is no approved,
  append-safe conviction ledger/tool, calibration scorer, or trusted identity
  mechanism on current `main`. Synthetic conformance work may proceed without
  real forecasts; promotion needs a separate reviewed implementation.
- **D-082 is a historical cross-reference only.** It is cited by D-084 but the
  D-082 entry is absent from this branch's `DECISIONS.md`; this port neither
  recreates it nor infers its exact text.
- **Point-in-time findings stay point-in-time.** Dates, state labels, merged
  SHAs, service descriptions, and "Done" markers in the ported source documents
  require present-tense verification before operational use.

## Next bounded work

The next safe artifact is a source-pinned, synthetic-only D-087 ledger
conformance test: distinct writer rows, no prefix truncation, corrupt-middle
rejection without byte changes, and recoverable torn tails. It must not write a
real forecast, select a focus, activate a service, or weaken attribution. Stop
if the work requires inventing trusted writer identity, panel aggregation,
quorum/scoring policy, or a live selection authority.
