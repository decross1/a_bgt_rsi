# G1.1 Nara candidate-source plan template

Status: **proposed source template only**. This is not a mailbox plan item,
selection, focus, experiment authorization, or scientific-credit claim. Oracle
may author and release a plan only after the reviewed
d132f319fc88f549c24929afe44476982a7d7c2f runtime is
installed and the ordinary meta-review gate accepts the exact posted item.

## Exact proposed body

~~~json
{
  "title": "G1.1: produce a source-bound information-and-belief candidate set",
  "objective": "Produce only the raw three-to-five-card candidate source at notes/nara_candidates.json. Do not choose, rank, or name a winner; do not create a focus, authorize execution, or claim scientific credit or novelty. Treat pinned source identity as distinct from scientific merit. Preserve these current evidence limits: C1 is stopped at insufficient_full_text_binding; the C3 identity-adapter screen's stop/no-preregistration disposition supersedes the older choice; the applied audit and research plan are proposals; exp007 is mock and retrodictive.",
  "task_class": "documentation",
  "allowed_write_paths": [
    "notes/nara_candidates.json"
  ],
  "input_paths": [
    "docs/v2/THESIS_BRIEF_2026-09-23.md",
    "notes/research/2026-09-25-c1-source-disposition/DISPOSITION.md",
    "notes/research/2026-09-25-c1-neighbor-prior-art/C1_EXACT_CLAIM_MATRIX.md",
    "notes/research/2026-09-24-t-gate-choice/T_GATE_CHOICE.md",
    "notes/research/2026-09-24-t-gate-choice/C3_PRIOR_ART_MATRIX.md",
    "notes/research/2026-09-25-c3-payoff-screen/C3_IDENTITY_ADAPTER_SCREEN.md",
    "notes/research/2026-09-15-flash-and-applied-research/PIPELINE_AUDIT.md",
    "notes/research/2026-09-15-flash-and-applied-research/TRADING_RESEARCH_PLAN.md",
    "experiments/exp007_polymarket/notes.md"
  ],
  "acceptance": {
    "test_path": "tests/test_nara_candidate_source.py",
    "test_content": "<insert the exact 7,741 UTF-8 bytes whose SHA-256 is 061eb1daebcefe7195f9be6d89b486cff147389ad01f9d5cc95530a42e08cb49>",
    "test_argv": [
      "python",
      "-m",
      "pytest",
      "-q",
      "tests/test_nara_candidate_source.py"
    ]
  },
  "budget": {
    "attempts": 2,
    "wall_clock_minutes": 45
  },
  "thesis_candidate_source": {
    "schema_version": "nara-thesis-candidate-source/v1",
    "set_id": "g11-information-beliefs-r2-20260925",
    "path": "notes/nara_candidates.json",
    "base_sha": "c820c22b30a1188498642199208e2c058142bb91"
  }
}
~~~

The publisher must replace test_content with the file's exact contents, not
the placeholder, and must not add another writable path. The known-good
precheck stub at tests/fixtures/nara_candidate_source_g11_good.json maps exactly
notes/nara_candidates.json to the 18,323-byte payload. It is directly
consumable by the lane's --stub option, is evidence only, and is never copied
into Nara's implementation worktree.

## Offline discrimination receipt

The reviewed lane precheck was run against commit
c820c22b30a1188498642199208e2c058142bb91, tree
0370bcf481adbb8ba7d13b1b1be25a28ecf4afc5. The absent-output run failed and
the fixture-backed run passed one collected acceptance test. The resulting
descriptor receipt is
c997be65f369a4650f5d999474c7e570be3cce6bd4dbe0b996eda95a19e2fea4
(nara-lane-precheck/v2). It is isolated author-side evidence, not live
admission state; regenerate or deliberately install the exact receipt only
after the reviewed runtime cutover.
