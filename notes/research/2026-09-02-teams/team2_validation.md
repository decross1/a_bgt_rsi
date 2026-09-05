# Team 2 validation — 2026-09-04

Base: `f0c7ea1ddd1859b0a671c72c6d71814941b9c25b`.
Integrated cleanup: `2ad38c5` (primary fast-forwarded main after verification).

## Recovery and review

The interrupted September 3 builder left a ten-file patch in
`/tmp/codex-team2-parent.AgSuQw/repo`. Its ledger remained `running`;
no final child report was available. The primary recovered the artifact and
closed that original execution as interrupted, without inventing a completion
sentinel or elapsed runtime.

Independent review `codex-team2-resume-review-20260904` found two blockers:
later architecture passages still described a single-model system, and the
edited startup sequences omitted the mandatory research-program read. It also
flagged present-tense wording around historical D-033. The primary fixed all
three in the isolated worktree. A separately contracted follow-up,
`codex-team2-review-fixes-20260904`, reviewed the complete final diff and
reported no blocking findings, nonblocking findings, or nits.

The primary applied the framework `code-review` skill to the actual local
range `f0c7ea1..2ad38c5`. Its diff is byte-identical to the final reviewed patch:
SHA-256 `0dba86f667f7e935da51dd9644c774e313a9888e0fc889713168687b3d586c7b`.
Production logic, metrics, schemas, version pins, and UI code are untouched.

## Independent checks

| Criterion | Observed | Verdict |
| --- | --- | --- |
| Exact base | Both reviews verified `f0c7ea1` | Pass |
| Allowlist | Exactly the ten files in the health report; no rename/deletion | Pass |
| Diff budget | 75 additions + 105 deletions = 180 lines | Pass |
| Patch formatting | `git diff --check` clean | Pass |
| Local links | 108 targets in the eight changed Markdown documents, zero missing | Pass |
| Test preservation | 38/38 test bodies identical; module ASTs identical after excluding the two removed xfail decorators | Pass |
| Targeted tests | Tool-plane, run-log attribution, and autoresearch: 43 passed | Pass |
| Current guidance | Model roles/startup sequence agree with contract; historical track/zone material explicitly labeled; runtime LOOP_V0 names retained | Pass |
| Independent review | No remaining findings after fixes | Pass |
| Mechanical premerge | `bash tools/premerge_check.sh f0c7ea1 180`: OK, ten files/180 lines | Pass |
| Full-suite comparison | Same seven failing node IDs, zero errors, same skipped module | Pass: no regression |
| Full-suite green | Seven failures remain | Fail; baseline comparison specifically authorized for this cleanup |
| Real serving smoke | `env -u MOCK_LLM` HTTP health + model-list probes: Gemma :8000 and Qwen :8001 both 200 with expected identities | Pass |
| Frontend/backend suites | No affected production/UI code; September 3 plan makes these conditional | Not applicable |

Targeted command, run from the isolated worktree:

```bash
MOCK_LLM=1 PYTHONDONTWRITEBYTECODE=1 \
  /home/decross1/projects/a_bgt_rsi/.venv-chroma/bin/python -m pytest \
  tests/test_tool_plane.py tests/test_runlog_agent.py tests/test_autoresearch.py \
  -q -p no:cacheprovider
```

Both full-suite runs used the main checkout, same interpreter/environment,
and required gitignored research stores, with this command:

```bash
MOCK_LLM=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv-chroma/bin/python -m pytest tests/ -q -p no:cacheprovider
```

- Before: **7 failed, 2,487 passed, 1 skipped, 2 xpassed**, 68 subtests,
  37.04 seconds.
- After: **7 failed, 2,489 passed, 1 skipped**, 68 subtests, 33.85 seconds.
- XML comparison verified identical failure/error/skip sets. The increase
  of two ordinary passes is exactly the removal of the two obsolete xfail
  wrappers; no test was removed or weakened.

The complete failing-node fingerprint is in
[team2_test_comparison.json](team2_test_comparison.json). Raw session outputs
are `/tmp/team2-resume-{base,candidate}-20260904.{log,xml}`. The real smoke
checks serving topology; it makes no inference-quality claim.

## Authority and limits

The owner-approved September 2 plan explicitly authorizes “python suite at
baseline,” retained by the September 3 continuation. That specific direction
governs this cleanup despite the generic full-green rule; seven failures are
still seven failures. See [the session handoff](../../../human/sessions/2026-09-04.md).

No production deletion was justified. Dependencies, experiment provenance,
protected-spine decomposition, and UI changes remain in their documented
owner-decision or future-session categories. The health report is at
[docs/project_health_2026-09.md](../../../docs/project_health_2026-09.md).
