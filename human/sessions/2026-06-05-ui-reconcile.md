# UI reconcile guide — main (bb7b813) ↔ worktree-ui-session

**For the concurrent UI session.** The primary session's 2026-06-05 dynamic-workflow
run wrote `ui/` changes to main (commits `ef02a7e` + merge `bb7b813`) while your session
was live — a process miss (a UI session was already the `ui/` owner). This guide makes the
merge clean. **Decision (human, 2026-06-05): you merge main and resolve, keeping both.**

## Do this in your worktree
```bash
git -C .claude/worktrees/ui-session add -A && git -C .claude/worktrees/ui-session commit -m "wip: activity + experiments UI before main reconcile"
git -C .claude/worktrees/ui-session fetch origin
git -C .claude/worktrees/ui-session merge origin/main      # base 6a44467 → bb7b813
```
Then resolve per the map below.

## What main added from the primary session (all `ui/`-only)
- **Loop-v1 iteration surfacing (KEEP — this is the only part of mine you don't already have):**
  `meta_review.conditioning_bullets`, `redteam.{verdict,retries_used}`, and `gate_status`
  rendered in `ActiveIterationPanel.tsx` + `ResolvedIterationsList.tsx`; the supporting
  optional types in `types/schemas.ts`; fixtures in `fixtures/loop_v0/index.ts`.
- **exp004 surfacing (DROP — your generic experiments feature subsumes it):**
  `ui/backend/experiments.py::compute_exp004_summary`, the `/api/experiments/exp004` route in
  `app.py`, `getExp004Summary` in `api/http.ts`, `Exp004Panel.tsx`, `Exp004Summary` type, and
  the Dashboard wiring + `test_exp004_panel.tsx` / `test_experiments.py`.

## File-by-file resolution

| Conflict | Resolution |
|---|---|
| `ui/backend/experiments.py` (add/add) | **Take yours.** Yours is the generic, artifact-detecting lister/detail; mine is exp004-only. Confirm your experiment scan includes `exp004_combinatorial_auction` (it has `results/summary.json`, which your `_probe` already detects) so exp004 shows up via your `/api/experiments/{exp_id}`. Discard `compute_exp004_summary`. |
| `ui/backend/tests/test_experiments.py` (add/add) | **Take yours.** Drop mine. |
| `ui/backend/app.py` | **Take yours** for the experiments routes; **drop** my `/api/experiments/exp004` literal route + the `compute_exp004_summary` import + `exp004_summary`/`DEFAULT_EXP004_SUMMARY`/`UI_EXP004_SUMMARY` wiring (yours covers exp004 generically). Keep both sides' other route additions. |
| `ui/frontend/src/api/http.ts` | Keep both additions; **drop** my `getExp004Summary` (use your `getExperimentDetail("exp004_combinatorial_auction")`). |
| `ui/frontend/src/components/ResolvedIterationsList.tsx` | **Take yours as the base** (your pagination + filters + selection is the bigger design); **port in** my Loop-v1 block rendering — the `gate_status` badge, `redteam` verdict/retries chip, and `meta_review` bullets per row. This is the one real manual merge. |
| `ui/frontend/tests/test_resolved_iterations_list.tsx` | Merge: keep your pagination/filter tests + add assertions for the ported Loop-v1 badges. |
| `ui/frontend/src/types/schemas.ts` | **Additive — keep both.** Keep my `meta_review`/`redteam`/`gate_status` optional fields on the iteration type; drop my `Exp004Summary` type (use your experiments types). |
| `ui/frontend/src/components/ActiveIterationPanel.tsx` (+ its test) | Mine only on main; **keep mine** (the Loop-v1 block rendering). If yours also touched it, merge the block-rendering in. |
| `Dashboard.tsx`, `fixtures/loop_v0/index.ts`, `Exp004Panel.tsx`, `test_exp004_panel.tsx` | Drop `Exp004Panel` + its test + its Dashboard wiring (subsumed by your Experiments routes). Keep the `fixtures/loop_v0` additions (they back the Loop-v1 surfacing). |

## Net intent
You own `ui/`. From the primary's run, **only the Loop-v1 iteration surfacing
(meta_review/redteam/gate_status) survives** — folded into your components. The exp004 panel
is redundant with your generic experiments surface and is dropped. When resolved + green,
print `UI READY TO MERGE` and primary merges `--no-ff`.

## Process correction (so this doesn't recur)
When a UI session is live, the primary session's workflows must **not** write `ui/` — they
should hand a UI spec to the session instead. Worth a DECISIONS.md note amending the
"Dynamic Workflow discipline" (build agents already forbidden from `ui/`; the gap was a
*worktree-isolated* UI agent racing a real UI session).
