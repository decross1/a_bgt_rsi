# Implementation validation — 2026-09-14

This records implementation checks, not a model or runtime promotion decision.
The code was developed in an isolated worktree based on Claude's committed
handoff `654a055`. Delivery excludes unrelated local-main commits and dirty
maintenance/session files.

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
