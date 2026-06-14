# archive/plans/ — imported plan-mode scratch artifacts (reference-only)

The files in this directory are **plan-mode scratch artifacts** that were
authored in Claude Code plan-mode sessions and stranded outside the repo under
`~/.claude/plans/` (per-machine, un-versioned, invisible to the repo and to a
UI session). They were imported here on 2026-06-14 because they are
**load-bearing or justify durable decisions** and would otherwise vanish on a
reimage. Each carries a provenance header naming its scratch original.

These are **kept for the record, reference-only.** They are *not* an active
plan or a source of truth — their executed outcomes already live in
`LOOP_V0.md`, `docs/`, the dated `human/sessions/` notes, and `DECISIONS.md`.
Read them as historical context for *why* the apparatus is shaped the way it is,
not as instructions to follow.

## Imported plans

| File | One-line description |
| --- | --- |
| [`idempotent-spinning-sonnet.md`](idempotent-spinning-sonnet.md) | LOOP_V0 "Part 1" substrate plan: install the framework, Runtime abstraction, Nara hello-world, and the UI. **Load-bearing** — cited by `ui_plan.md:16`. |
| [`i-want-to-start-concurrent-flurry.md`](i-want-to-start-concurrent-flurry.md) | `/activity` "active-now hero" rework and the batch→fan-out→gate workflow rhythm for building UI pages. **Load-bearing** — cited by `ui_plan.md:126`. |
| [`snoopy-hopping-milner.md`](snoopy-hopping-milner.md) | Documentation restructure + autonomy framework + 30-day roadmap (end of Phase 1 Week 1). Roadmap rationale. |
| [`peaceful-brewing-seal.md`](peaceful-brewing-seal.md) | Phase 2 / Loop v1 trajectory + Slice 1 (Vickrey rediscovery); apparatus state snapshot at 2026-05-27 EOD. Roadmap rationale. |
| [`peaceful-brewing-seal-agent-a6d822d6b420662cd.md`](peaceful-brewing-seal-agent-a6d822d6b420662cd.md) | Cohabitation research: vLLM (Gemma 4 26B-A4B-NVFP4) + Ollama (Qwen3.6-27B) on DGX Spark GB10. Justifies the version pins. |
| [`peaceful-brewing-seal-agent-a3d80dfd274cb8534.md`](peaceful-brewing-seal-agent-a3d80dfd274cb8534.md) | Qwen3.6-27B critic/coder-tier quantization plan (NVFP4 + MTP under vLLM). Justifies the version pins. |

## Plans policy

Plan-mode files under `~/.claude/plans/` are **scratch** (per-machine,
un-versioned, invisible to the repo and to a UI session). **Any plan that will
be executed is committed into the repo** before/at execution — active
cross-workstream work into `LOOP_V0.md` or a `docs/` detail-doc, a UI work order
into the day's `human/sessions/YYYY-MM-DD.md` note, a decision into `DECISIONS.md`
(append-only). A plan worth keeping for the record (but not active) lands **here**
in `archive/plans/` with a provenance header. `~/.claude/plans/` is never a
source of truth and is never cited from a live in-repo doc.

The other ~12 plans still in `~/.claude/plans/` were deliberately **not** imported:
their outcomes already live in the session notes, `docs/`, and `DECISIONS.md`, so
keeping them here would duplicate a source of truth.
