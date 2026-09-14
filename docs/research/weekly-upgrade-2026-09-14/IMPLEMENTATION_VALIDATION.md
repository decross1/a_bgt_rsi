# Implementation validation — 2026-09-14

This records implementation checks, not a model or runtime promotion decision.
The code was developed in an isolated worktree based on Claude's committed
handoff `654a055`. Delivery excludes unrelated local-main commits and dirty
maintenance/session files.

## Unblock tranche: current validation

The later unblock tranche resolves all seven historical failures with minimal
reconstruction inputs derived from already-committed study artifacts. Exact
scientific rows, aggregate results and numerical expectations are retained;
real subprocess hash-seed checks still reconstruct the studies. Unrelated
population/membership records are explicitly synthetic. Derived hashes are
distinguished from the original ignored-store pins in
[fixture provenance](../../../tests/fixtures/weekly_upgrade_baseline/provenance.json).
The full raw ledger/cache bundles were removed before any commit. Historical
counts below describe the earlier delivery, before this repair.

This work also fixed two explicit-input defects: critic manifest metadata
hashed a global source instead of the supplied path, and the audit's cluster
reconstruction reread global loop memory. Both now use the explicit caller
input; dedicated regressions point the global path at a missing file.

The full integrated suite now reports **2,692 passed, zero failed, 1 skipped,
2 xpassed**, plus 68 passing subtests. See
[validation receipt](unblock_validation.json). The two xpasses are inherited
expected-failure markers whose tests pass. Public reconstruction and explicit
source-path checks passed 137 tests; independent cache/promotion review passed
39 tests; coordinator/frontier integration checks passed 97 tests.
Shell syntax and scoped diff checks passed.

A fresh `env -u MOCK_LLM` compatibility smoke against the existing Qwen3.8
endpoint returned exactly `{"sum":2}` using the thinking-off profile. See
[isolated call record](unblock_qwen_compatibility_smoke.jsonl). Both queues were
empty at preflight, with approximately 41.5 GiB MemAvailable. This verifies
request compatibility; the preregistered effort pilot has not run.

Independent review found and fixed cache expiry, provider/transport identity,
role-routing, and state-directory issues. The cache stays off by default and
requires declared provider epochs; these are operator attestations, not
verified immutable server revisions. See
[operation and rollback](frontier_cache_operation.md). No new live frontier
calls or cache activation occurred in this tranche.

The [read-only readiness replay](skeptic_readiness_report.json) reproduced
the upstream R0 blockade: 59 recent completed iterations, zero clean-survives
candidates eligible for the skeptic. Counterfactual gate demotion does not
establish scientific validity. Follow the
[completion tracker](UNBLOCKING_PLAN.md) for the remaining experiments,
automatic trial dispatch and eventual activation work.

The subsequent [topic-starvation audit](topic_starvation_audit.md) located the
upstream cause: 60 coordinator research dispatches repeatedly chose one stale
machine-mined follow-up whose agenda copy had already been consumed. The code
now omits exact handled machine topics using existing consumed-agenda or
unambiguous successful-dispatch receipts. Human follow-ups and failed or
ambiguous dispatches remain eligible. Finalized loop memory alone is not
treated as proof of success. Topic-source logging follows the selected topic.

The root's [frozen queue replay](topic_queue_repair_replay.json) independently
removed all four handled machine entries while preserving the recorded arXiv
suggestion. No model, picker, or canonical-state mutation occurred in that
replay. This verifies selection behavior, not a completed post-deployment
scientific iteration or a model-performance gain.

## Test baseline

The original `654a055` checkout, with frozen copies of the same existing local
memory/cache/health inputs, produced **2,518 passed, 7 failed, 1 skipped** plus
68 passing subtests. The seven failures predate this implementation:

- `test_critic_cal`: unusable-row census, pinned reference rates, native
  undecidable census, and cluster ordering reconstruction (four tests).
- `test_readjudication`: manifest independence across hash seeds 0, 1 and 12345
  (three tests).

Live files were copied into both test worktrees; tests never shared writable
production ledgers. The original checkout lacked ignored memory/cache files,
which initially produced additional environment errors. Those are distinguished
from regressions by the matched-input baseline above.

Final integrated candidate: **2,644 passed, 7 failed, 1 skipped**, with 68 passing subtests. The failure IDs exactly match baseline; there are **zero new failures**. See [machine-readable comparison](test_comparison.json). The full-suite command was `MOCK_LLM=1 .venv-chroma/bin/python -m pytest -q tests`.

Focused delivery branch, built directly from remote main plus the handoff and
implementation commits: **2,649 passed, 7 failed, 1 skipped, 2 xpassed**, plus
68 passing subtests. Its seven failures also exactly match the baseline. The
two expected-failure markers belong to older tests on remote main; both tests
pass. The final focused implementation set passed **133 tests**. Committed
changes exclude live ledgers and copied maintenance authority/configuration.

## Live checks

- **Qwen profile:** the existing `:8001` endpoint accepted
  `qwen_card_instruct`, including `enable_thinking=false`, and returned exactly
  `{"sum":2}` with `finish_reason=stop` in about 776 ms. See
  [call record](qwen_instruct_smoke.jsonl). This verifies request compatibility,
  not scientific quality.
- **Gemma paired harness:** two arms across two templates completed in about
  4.62 seconds. All four task outcomes failed their objective grader. There
  were no transport/provenance failures. See [run](gemma_smoke_run.json) and
  [frozen smoke manifest](gemma_smoke_manifest.json). One tool question's wording
  was subsequently clarified to specify mixed-strategy security value; the
  preserved smoke uses the old wording and is not a clean quality comparison.
  The equilibrium responses were also mathematically incorrect. No upgrade
  claim or promotion follows from this smoke.
- **Subscription transports:** actual Claude and Codex returned completed smoke
  replies. Claude used `/usr/bin/claude` 2.1.143 and reported Opus 4.7 plus a
  Haiku helper in usage metadata; Codex CLI 0.154.0 requested `gpt-5.6-sol` and
  did not expose a resolved model ID. See [receipts](transport_smoke_receipts.jsonl).
- **Source fetch:** all four configured primary-source URLs were retrieved,
  totaling 82,853 bytes. The collector recorded URL, timestamp, digest and
  limits. All fetched material remained `FETCHED_UNVERIFIED`; HTTP success did
  not validate its claims. See [receipts](source_fetch_receipts.json).
- **Long Claude code review:** a separate substantive review attempt exceeded
  its explicit 180-second deadline. The process group was stopped and the
  result recorded as TIMEOUT, not a successful review. See
  [receipt](claude_code_review_timeout.jsonl). The earlier handoff's two actual
  Claude review rounds remain separately documented in [review record](REVIEW_RECORD.md).

Before GPU smoke, both model endpoints reported zero running/waiting requests
and the system reported about 41.6 GiB MemAvailable. Tests used synthetic
inputs and isolated artifacts; no serving restart, model replacement, context
change, cron activation, scientific-ledger write or production cutover occurred.

## Live weekly review

The first full two-provider run completed Codex analysis in 108 seconds and
Claude adversarial review in 69 seconds. Codex proposed comparing Qwen critic
efforts; Claude objected that the proposal named the profile implementation
file as the change surface even though both profiles already existed. The
controller returned INVALID_REPORT because one substantive violated-rule
explanation exceeded the initial 240-character field limit. That outcome is
preserved in [report](weekly_review_smoke_v1.json) and
[receipts](weekly_review_smoke_v1_receipts.jsonl). It is not a completed validated
review or a passed trial. The limit was subsequently aligned with the bounded
objection fields, and raw unvalidated responses are retained for diagnosis.

The second full run also completed both provider calls, but rejected descriptive
locators that did not occur literally in the frozen excerpts. See the preserved
[report](weekly_review_smoke_v2.json), [receipts](weekly_review_smoke_v2_receipts.jsonl),
and [explicitly unvalidated adversary output](weekly_review_smoke_v2_unvalidated_adversary.json).
The proposer had received the literal-citation instruction; the adversary had
not. That missing instruction is now supplied to both roles. Original invalid
reports stay invalid and never authorize an experiment.

Substantive dispositions: accept the need for adequate output caps, paired timing
controls, and more independent tasks before any quality claim. Keep malformed
and missing decisions in the primary failure-inclusive metric; a parseable-only
view is secondary. Do not disable MTP during an inference-policy comparison,
since that adds a runtime confounder. Three seeds alone do not establish power.

The corrected adversary prompt was then tested in a separate, explicitly
budgeted protocol replay against the same frozen proposal and snapshot. It
**passed validation** and returned **revise**, with five objections. See
[validated response](adversary_protocol_v3_validated.json) and
[receipt](adversary_protocol_v3_receipt.jsonl). This was a separate one-call
integration check; it did not rewrite either original report or exceed their
two-call budgets. No experiment or production change was authorized by these
review outcomes. The citation-prompt correction passed all 34 controller tests.

## Independent implementation review

Three delegated implementation/review streams covered policy compatibility,
evaluation validity, and the weekly controller. Root also followed the repo's
code-review checklist. Material findings corrected during integration:

- Empty backend registry in fresh-process evaluation preflight.
- Evaluation activity sink/run-ID not restored after calls.
- Partial Codex output accepted without a completed-turn event.
- Incorrect legacy subagent sampling telemetry and missing persistent defaults.
- Qwen reasoning history lost on direct-loop repair/reprompt paths.
- Source collection needing a hard deadline around DNS and trickling reads.
- Weekly telemetry using the current calendar week instead of the last seven days.
- Missing exact snapshot digest in tool-free analyst prompts.
- Invented baseline measurements and misleading proposal/candidate hash naming.
- Revision and evidence-reference semantics in the review artifacts.

## Limits carried forward

The bundled panel is a public development canary, with deliberately small Qwen
caps for liveness diagnosis. It does not establish science/coding improvements,
end-to-end agent success, OOD validity or a runtime speedup. No defaults were
promoted. Independent hidden tasks, adequately budgeted quality sweeps, runtime
artifact attestation, a serial resource lease and deployed scheduling remain
follow-on qualification. Direct Nara/subagent wall budgets still check between
turns; the weekly evaluator uses the bounded wrapper path.
