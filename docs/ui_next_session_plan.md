# UI session plan — next session (authored by the primary session, 2026-06-09 evening)

> **To the UI session.** Your evening merge (`73b431b`) was adversarially reviewed by the
> primary session (framework `code-review`, two reviewers, executed against tonight's live
> data). **The render layer passed**: the dashboard correctly renders all three of tonight's
> live iterations — `iter-2026-06-09-006` (rediscovery/restated + `novelty_axes` chip),
> `-007` (the first live `undecidable` + amber low-evidence badge with `category/rule` in
> the tooltip), `-008` (violet `nemoclaw_agent` provenance — the β headline row). No closed
> schemas, behavioral forward-compat tests, clean boundary. The findings below are
> test-side and small. Boundary unchanged: write only `ui/` + `ui_plan.md`.

## Task 1 — fix the review findings (suite is red in the MAIN checkout today)

1. **(blocking)** `ui/frontend/tests/test_revalidate_live_rows.tsx:51-56` (and the same
   idiom in `test_validate_iterations.tsx:41`, `test_validate_lowevidence.tsx:42`):
   `REPO_ROOT` hardcodes the ui-session worktree depth (`../../../../../..`), so the live
   tests die at import (`ENOENT /home/memory/loop_memory.jsonl`) when run from the merged
   main checkout. Walk up until `memory/loop_memory.jsonl` exists (mirror the backend's
   `_PRIMARY_REPO` approach). This also voids the report's "auto-validates every future
   live row" claim outside the worktree — the fix restores it.
2. **(blocking)** `test_revalidate_live_rows.tsx:331-355`: `KNOWN_RELEVANCE_KEYS` omits
   **`topicality`** — the drift census is red on live rows 006/007. Add it (and to the
   additive-key comment block in `ui/frontend/src/types/schemas.ts:259-264`). Full additive
   set is now: `anchor_cosine, curated_overlap, neighbor_spread, topicality, category,
   rule_fired`.
3. **(blocking)** `test_revalidate_live_rows.tsx:382-391`: the novelty-axes census loop
   double-renders (`ResolvedIterationsList` + standalone `NoveltyAxesChip`) before
   `cleanup()` → `Found multiple elements`. It was vacuously green at merge time (no live
   axes rows existed); tonight's rows execute it. Insert `cleanup()` between renders or
   scope the query.
4. `test_validate_lowevidence.tsx:153`: pre-existing pin of the off-domain tile at literal
   `"0%"` — live row 007 makes it 1-of-55. Re-pin as a cohort invariant, not a literal.
5. (non-blocking) `ui/backend/tests/test_live_8700.py` never probes `/api/human_todo` —
   the one endpoint your merge added (the live 404 it was built to catch existed until the
   primary restarted the server tonight). Add the GET. Also: the `_git_sha()` request-time
   version is an unsound stale-binary signal (it reports working-tree HEAD, not the loaded
   code) — either snapshot the sha at import or drop the claim from the report.
6. (nit) `Dashboard.tsx` ~L268: `<Link>` inside `<summary>` both navigates and toggles.
   (nit) Delete the stray 7-byte `fixture` file at the worktree root (untracked debris).

## Task 2 — re-validate against tonight's live data (no code expected beyond Task 1)

The primary restarted **both** servers on merged/final code (`:8700` UI backend — human_todo
now 200; `:8077` tool plane with `NARA_SKEPTIC=1`). Live data now present:
- 55 loop_memory rows; newest three exercise every new render path (axes chip, undecidable
  chip, low-evidence tooltip with `category: off_domain; rule: R0`, nemoclaw badge).
- 140+ coordinator cycles incl. `coordinator_6d8a2c4e` (status `executed`,
  promote_findings passed, **no promotions** — findings/bubbles/health files remain ABSENT;
  the empty states stay the honest render; do NOT expect populated panels).
- Two mid-flight `active_run.json` snapshots are quoted in `docs/ui_validation_handoff.md`
  §gap-3 (note: no `current_step`/`narration` at this granularity — render what exists).

## Task 3 (small, additive) — surface the new verdict semantics for the human auditor

Tonight's apparatus changes (commits `fedf53c`/`d5bd020`) made `undecidable` the COMMON
fail-closed verdict and added override provenance. Two small additive renders, if cheap:
- Where a critique block carries `verdict_overridden_from` / `override_reason` /
  `skeptic_verdict`, show a small "overridden from X" hint (tooltip is fine) — the human
  needs to see *why* a verdict was demoted (skeptic vs coverage vs low-confidence).
- The transfer bucket: axes `{known, *, matches|silent}` ⇒ consider a quiet
  "transfer/replication" label next to the rediscovery chip (matches
  `docs/novelty_two_axis_rubric.md`).

## Context for next session's primary work (so your renders anticipate the data)
- PD narrative-vs-list (`exp001`) + Cournot (`exp009`) REAL runs are queued — expect
  `experiment_outcome` blocks with `Verdict=YES|NO` summaries appearing on iterations.
- The MCP run tool may become submit+poll (15s client timeout vs ~90s tool); if so, the
  active-run panel becomes the agent's progress view — keep it robust to `kind:"ad_hoc"`
  and `kind:"experiment"` writers (your staleness handling already tolerates them).

Print `UI READY TO MERGE` when Task 1 lands and the suite is green from BOTH the worktree
and the main checkout.
