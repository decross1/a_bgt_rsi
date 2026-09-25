# D-084–D-087 source-port reconciliation (2026-09-25)

**Status:** implementation-status note. It does not amend or rewrite the
historical decisions or owner quotations. It records which statements are
historical, what a current operator may rely on, and what remains unimplemented
on this branch. The imported working documents carry added reconciliation
banners; their original committed blob IDs below preserve the unmodified source.

## Provenance and scope

This branch ported only the following committed Flash sources onto
`origin/main` commit `ba302f803407f21ffe9696fcadd107059ffd28c0`:

| Material | Committed source | Source blob |
|---|---|---|
| D-084 | `580b0376` | `DECISIONS.md` `1441bacb67fbb703f4d2485b0bd3892382bd615f` |
| D-085 | `d38cb83a` | `DECISIONS.md` `d0a25bb8f3906f2e96b9023ece40c85e2c94a517` |
| D-086 | `12ef9c63` | `DECISIONS.md` `8c80eafd8fa33fa691d9de182b3ed036206f7a2a` |
| D-087 and the final source documents | `a4ccb77e` | `DECISIONS.md` `adc0491ca083c14cb660a8ca20aee2b61924a967`; alignment `11e969cf4a8e7f28d557aa15499e2c8ba127830a`; brief `524ae8f8f89f5ad5e91dd616ca2caa5c96f86c99` |

The D-084–D-087 decision bodies are preserved verbatim in
[DECISIONS.md](../../DECISIONS.md). The working copies of
`ALIGNMENT_AND_GOALS.md` and `THESIS_BRIEF_2026-09-23.md` add only prominent
reconciliation banners; their body text remains the recorded source snapshot.
Neither document claims that every dated implementation/status sentence holds on
current `main`. Current runtime or implementation state must be established from
the current commit, receipts, and tests.

## Current-session operating instruction (unverified attribution)

This steward recorded the current conversation instruction: "it should be a
decision of nara or oracle." It is model-asserted conversation attribution with
no authenticated repository transcript, ratification record, or activation
receipt. It is therefore a reported operating instruction, not evidence that an
implementation is ratified, active, or safe to use. It changes the procedure
implicit in the historical phrases "the owner picks one" and "selected by the
owner"; it does not alter the preserved quotations or the T/S/A ladder.

For a future, properly implemented selection path:

1. Nara generates the 3–5 candidates within D-086's information-and-beliefs
   direction and the thesis brief template.
2. Oracle screens and selects one after the required upstream evidence and
   review; the meta-oracle independently reviews the proposed selection.
3. The reported procedure has no Derrick decision card for that non-live
   research choice.
4. A live-trading path still requires Derrick's explicit approval. The T/S/A
   ladder, preregistration, independent review, negative-result retention, and
   kill/reopening receipts remain required.

This reported procedure is not proof that the current implementation can safely
make the selection. A same-UID mailbox sender can currently imitate roles, and
the selection port under separate review is not approved for merge or use. Until
a default-deny, independently attributable reviewer/role mechanism is verified
and the selector's guard chain is tested, no code path may treat this note as
authorization to activate or select a focus.

## Host and scheduler boundary

D-084's historical phrase that "timers ... may proceed" does not authorize a
host-service, scheduler, security-policy, credential, or persistent-service
change. The applicable `a_bgt_rsi` `AGENTS.md` runtime boundary governs its own
model/runtime-cutover and service changes; it must be reverified at the time of
any action. Separately, the committed `oracle_system` contract at
`9619b881c3ce4b8a8250cd2cfff6a70e20b3104a`, `AGENTS.md` §21 (lines 64–68),
requires its five-minute timer to stay inactive until a reviewed-commit,
private verified runtime snapshot has the specified read/write boundaries. That
is an Oracle-specific rule, not an `a_bgt_rsi` rule. Reverify both current
contracts and any contemporaneous service state at action time. This source-only
documentation port performed no service action and makes no present-tense claim
about which units are enabled or disabled.

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
