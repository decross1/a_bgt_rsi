# Stage 0 — Project inventory

> What I confirmed before proceeding, per the handoff prompt's guardrail
> "state explicitly rather than proceed on assumption."

## Files I can see in project knowledge

- `START_HERE.md` — orientation
- `PROJECT_CONTEXT.md` — full project background, including the program
  arc and open scoping items (one of which is the v4 / technical-plan-v1
  re-scope this review addresses)
- `ARCHITECTURE.md` — apparatus architecture walkthrough, including the
  eight-step intelligence loop in §6
- `DECISIONS.md` — decision log D-001 through D-022 plus open decisions
- `plan.yaml` — the frozen Week 1 machine-readable plan (Day 1–7),
  including Appendix A "Deviations from research program v2" and
  Appendix C
- `CLAUDE.md` — the operating contract (referenced; full content
  read-through limited but inviolate-rules confirmed via cross-references
  in `START_HERE.md`, `plan.yaml`, and `DECISIONS.md`)
- `README.md` — repo layout
- `HUMAN_PLAN.md` — the researcher's daily blocker list
- `AGENT_PLAN.md` (referenced; per-day track schedule)
- `current_day.md` (referenced; live tracker)
- `docs/diagrams/README.md` — diagram versioning convention
- `docs/diagrams/architecture_v4.svg` — fully visible
- `docs/diagrams/intelligence_loop_v4.svg` — fully visible
- `ui_plan.md` — Pi/OpenClaw observability dashboard plan (out of scope
  for this review but contextually useful)

## Files referenced but NOT present in project knowledge

Per `docs/sources/README.md`, these are the authoritative source documents
the canonical summaries are derived from, and they are **not yet
committed under `docs/sources/`**:

- `research_program_v2.pdf` — the intellectual research program
- `research_apparatus_technical_plan_v1.md` — the technical companion to
  the program
- `week1_days_31-37_plan.md` (a.k.a. `agent_plan_week1.md`) — the
  human-readable Week 1 plan

The handoff prompt names these as the authoritative sources to read in
Stage 0. I do not have them. The handoff prompt's instruction in this
case is explicit: "list exactly what is missing before proceeding — do
not invent their contents."

**Mitigation.** The canonical summaries (`PROJECT_CONTEXT.md`,
`ARCHITECTURE.md`, `DECISIONS.md`) and `plan.yaml` are derived from
these sources, and per `docs/sources/README.md` they are the operative
authority for execution until the originals are committed. I treat the
canonical docs as substitute. **Where this review is reasoning about
program intent specifically and not derived statements, I flag it.**

I do not have `CLAUDE.md` in full view, but the relevant inviolate rules
(human-only Block 1, version pins, Day 7 human gate, validations never
silently coerced, hard checkpoints abort the day) are cross-referenced
from the visible files and treated as guardrails.

## Source paper

I fetched the Google AI co-scientist blog post in full from
`research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/`
(canonical URL preserved in fetch metadata). I fetched the arXiv 2502.18864
landing page and abstract; I did not fetch the 81-page PDF body, so
finer-grain claims about appendix content are not in my scope. I did not
fetch the cf-PICI papers. Where a claim in the prior analysis needs the
paper body to verify, I say so plainly.

## Constraints I will honor

- Week 1 plan is frozen — nothing edits `plan.yaml`, `CLAUDE.md`'s
  inviolate rules, or version pins. Any Week 1 touch goes in
  "Frozen-plan change proposals" for explicit human approval.
- Diagrams version up — new files committed as `_v5.svg`; v4 stays in
  place per `docs/diagrams/README.md`.
- Scope holds — no Polymarket live design, no fine-tuning, no Week 1
  concurrency, no second model before Week 2–3.

Stage 1 follows.
