# Veto elevation — turning falsifier text into knowledge and questions

*Owner ask (2026-08-19): "this is good information but how does it feedback
into the system… is there a way to store and summarize this, so it becomes
part of nara's knowledge base. Also looks like alot of vetos… how can we
elevate this to end up yielding actual research questions?"*

Before this seam the falsifier tiers were **verdict-only feedback**: the
frontier screen's `veto` blocked promotion and the redteam's `fatal_flaw`
killed an idea, while the *reasoning* — which names the exact controls the
claim is missing — was written to disk and never read again. This page is
the one-page flow and the gates.

## Flow

```
run_state/frontier_cluster_screen.jsonl        memory/loop_memory.jsonl
  screen.methods / screen.novelty                redteam.verdict == fatal_flaw
  {verdict, reasoning, role, vendor}             {verdict, critique, model}
  (+ cross_run: the second vendor)
                 \                                        /
                  \                                      /
                   ▼                                    ▼
        workers/constraint_distill.py  — DETERMINISTIC. No LLM, ever.
          · bracket-aware sentence/clause split → verbatim control fragments
          · each fragment must read as a RUNNABLE DESIGN OBJECT, not a
            complaint about the claim (rules below)
          · flaw_class by ORDERED KEYWORD RULES (+ flaw_class_all)
          · claim_head joined from surfaced_findings / loop_memory
                                   │
                                   ▼
                  memory/design_constraints.jsonl   (DERIVED; --rebuild-able)
                  {constraint_id, cluster_id, claim_head, flaw_class,
                   missing_controls[], source{kind, role, vendor_or_model,
                   verdict, verbatim_quote}, status: active}
                        │                                   │
        ── --propose ───┘                                   └── conditioning ──
             (flock-guarded)                                             ▼
                        ▼                                    workers/meta_review.py
   memory/frontier_agenda.jsonl  (APPEND-ONLY)      gate: NARA_CONSTRAINT_CONDITION
   {proposal_id: sha8("distilled\n<cluster_id>"),   (UNSET = OFF = today)
    proposed_by: "distilled:<kind>",                ≤3 bullets, each labelled
    topic: "<claim head> — re-scoped:               "[constraint from <kind>/<role>]"
            <the named missing control>",
    status: "proposed", cluster_id, ...}
                        │
                        ▼
   HUMAN accepts (`orchestrator/agenda_cli.py accept`) ──► idea ledger
```

**Wiring status (2026-08-19).** The distiller is **CLI-only**: nothing in the
loop calls it on a schedule, and no orchestrator file was touched to land it.
The conditioning gate is **dark**. So today the seam is: run it, read the
store, accept what deserves accepting. Automating the distil pass (a cron or
a coordinator pre-step) is a separate, deliberate decision.

## The two gates, and why they are where they are

**Gate 1 — `status: "proposed"` (always on).** A distilled follow-up is
**inert**. It sits on the agenda until a human accepts it; nothing reaches
`memory/idea_ledger.jsonl` on the strength of a frontier veto alone. This is
what keeps **D-061** intact: frontier models veto and annotate, they never
generate. The distiller only ever *re-points* a claim the loop already made
at a control the falsifier already named — and even that re-pointing is a
proposal, not an idea. The human is the generator-of-record.

**Gate 2 — `NARA_CONSTRAINT_CONDITION` (DARK; default OFF).** Feeding
constraint text back into `meta_review`'s conditioning bullets is the one
step that could *shape generation*. It therefore does not arm itself: unset
means OFF, and the gate state is logged on every run either way
(`[meta_review] design-constraint conditioning: OFF|ON`). The owner arms it
after a risk/reward ask. The known risk when armed: conditioning the
generator on its own critics' vocabulary can breed *control-checklist
mimicry* — claims written to satisfy the last veto rather than to be true.
That is an empirical question, and the OFF state is the honest default until
it is asked.

Two boundaries hold underneath both gates:

- **D-061** — no frontier text is paraphrased into the loop's voice. Every
  row carries `source.kind / role / vendor_or_model / verdict` and a
  `verbatim_quote` (≤600 chars). The distillation is code, so nothing is
  re-generated in transit.
- **D-014** — nothing here reads or writes the framework brain. The stores
  are repo-local JSONL; the runtime firewall is untouched.

## What gets distilled, and what does not

| Source | Distilled | Skipped |
| --- | --- | --- |
| frontier screen `methods` / `novelty` / `cross_run` | `veto`, `inconclusive` | `pass` |
| redteam critique | `fatal_flaw` | `proceed` |

`inconclusive` is kept because those reviews routinely *name the controls
they would need* ("Required controls include matched signal variance,
identical priors…"). Its verdict is recorded as `inconclusive` — never
relabelled a veto (inviolate rule 4) — and it **cannot** produce a proposal.

`flaw_class` ∈ `missing_control | no_evidence | category_error |
prior_exists | mechanism_underdetermined | unfalsifiable | other`, assigned
by ordered keyword rules, never by a model. The order is *what the finding
needs next*: `prior_exists` / `category_error` / `unfalsifiable` outrank the
control classes because no control can rescue a claim that is already
published, mis-stated, or unfalsifiable. Every rule that fired is kept in
`flaw_class_all`, so the single label never hides a second true reading.

When no control-like fragment parses, `missing_controls` is `[]` and the
verbatim quote still carries the knowledge. Extraction is deliberately
conservative — an invented control would be generation.

### What counts as a control (the extraction rules)

A kept fragment must be a **runnable design object — a thing you could go
do** — and must not be a **description of the claim's fault**. Same criterion
as the proposal filter below; the code enforces it in both places. Concretely
a fragment is dropped when it:

- carries a **fault predicate** (`mischaracterizes`, `conflates`, `too
  vague`, `ill-defined`, `underspecified`, `confounded`, `incoherent`,
  `hinges on`, `depends on`, `driven by`, `cannot`, `is not`, `do not`,
  `fails`, `neither`, `silently`, …), or opens on a **negation** (`not a
  comparison of composition bounds`);
- reads as a **relative clause** (`which …`) or a **bare** `such controls`;
- ends on a **dangling preposition/determiner** — the signature of a mangled
  shard;
- is shorter than 8 or longer than 140 characters.

Two constructions are *repaired* rather than dropped, because they are how a
reviewer names a control: a **requirement frame** keeps its tail (`The claim
requires at least an otherwise-identical randomized comparison …` → `an
otherwise-identical randomized comparison …`), and a **`no <X> is
provided/required/available`** keeps its subject (→ `<X>`). Both results are
still verbatim substrings.

Clause-splitting is **bracket-aware**: `(epsilon, delta)` is one token, never
two shards. An over-long clause is additionally expanded into its prefix and
its parenthetical, so a control named inside an aside is still found.

**Why these rules exist (2026-08-19).** The first live pass wrote 112 rows /
50 fragments with only a keyword filter, and the mere words
*comparator / comparison / control* let **16 complaints** in — among them
"The claim mischaracterizes its own comparator", "the claim silently depends
on missing controls", and the exact string this page holds up below as what
must be rejected: "The term 'non-equilibrium markets' is too vague to serve
as a controlled baseline". Two more rows held mangled shards of
`(epsilon, delta)`. All ten redteam rows that carried a "control" carried a
complaint — a fatal-flaw critique argues, it does not design. After the fix
the same stores yield **33 fragments across 11 rows** (was 50 across 22), and
five genuine controls that had been mangled or buried are now recovered
whole. `tests/test_constraint_distill.py` pins every one of those strings,
rejections and acceptances alike.

## Which vetoes become research questions

A cluster earns **one** proposal only when all of these hold:

1. a **blocking** verdict (`veto` or `fatal_flaw`) — not `inconclusive`;
2. `flaw_class` ∈ {`missing_control`, `mechanism_underdetermined`};
3. a fragment that reads as a **runnable design object** (baseline,
   ablation, matched/randomized comparison, control) and is not a complaint
   about the claim ("…is too vague to serve as a controlled baseline" names
   no experiment).

Otherwise there is no proposal. On the live stores (2026-08-19, after the
extraction fix) this turns 112 distilled constraints into **3** proposal
candidates — the filter is the point: a prior-work kill should stay dead, and
a vague critique should not be laundered into an agenda item.

Best-constraint-per-cluster ranking: frontier screen outranks local redteam,
more named controls outranks fewer, `constraint_id` breaks ties. Proposals
are capped per run (`PROPOSALS_CAP = 10`) with the withheld count reported,
never silently dropped.

### One proposal per cluster — across runs, not just within one

`proposal_id = sha8("distilled\n<cluster_id>")`. The key is the **cluster
alone**, and every candidate is checked against **the whole existing agenda
file** — on the id *and* on `cluster_id`, so rows minted by an earlier run
(under the old id function) and rows minted by the weekly cron both count. A
cluster that already has a proposal is **skipped, and the skip is counted and
printed**.

The key used to be `sha8("distilled\n<cluster_id>\n<topic>")`, and the topic
embeds both the claim head and the chosen control. Both drift routinely — a
re-screen names more controls (changing which one ranks best) and a
later-surfaced finding overrides the loop_memory hypothesis as the head — so
the guarantee held only *within a single run*. It double-minted twice live on
`cl-iter-2026-05-26-008` before it was caught (2026-08-19). Source kind is
deliberately **not** in the key: a frontier veto and a redteam kill of the
same cluster are the same cluster, and the ranking above already picks
between them.

### Concurrency

`cron/weekly-frontier-agenda.sh` is **installed** (`30 5 * * 0`) and appends
to the same `memory/frontier_agenda.jsonl`. `--propose` therefore does its
read-filter-append under **the same `flock`** the cron's gate 1 takes —
`run_state/.frontier-agenda-cron.lock` — and re-reads the agenda *inside* the
lock so a row the cron added while we waited is still seen. The wait is
capped (`AGENDA_LOCK_WAIT_S = 30`); on expiry the run **refuses and says so**
(exit 1), it never writes unlocked (inviolate rule 7).

## Running it

```bash
# distil only (idempotent; re-runs write nothing new)
.venv-chroma/bin/python -m workers.constraint_distill --once

# distil + append status=proposed follow-ups to the frontier agenda
.venv-chroma/bin/python -m workers.constraint_distill --once --propose

# see what would happen, write nothing
.venv-chroma/bin/python -m workers.constraint_distill --once --propose --dry-run

# regenerate design_constraints.jsonl from the current extractor
.venv-chroma/bin/python -m workers.constraint_distill --once --rebuild
```

Every store the run touches is overridable — `--screen`, `--loop-memory`,
`--surfaced`, `--constraints`, `--agenda` — and a fully overridden run reads
and writes **no** real store (pinned by a test; `--surfaced` was missing
until 2026-08-19, so an "isolated" run still read the real
`memory/surfaced_findings.jsonl`).

Idempotency: `constraint_id` hashes `cluster_id + kind + role + vendor +
the FULL reasoning`, so an unchanged store re-runs to zero new rows, while a
*re-screen* that produces new text records new knowledge instead of
overwriting the old. Hashing the already-truncated 600-char quote (the shape
before 2026-08-19) made two long reviews from the same
cluster/kind/role/vendor collide on a shared prefix, silently dropping the
second — truncation is a storage budget, never an identity.

### Which store may be rewritten, and which may not

`memory/design_constraints.jsonl` is a **derived artifact**: every field is a
deterministic, LLM-free function of `run_state/frontier_cluster_screen.jsonl`
and `memory/loop_memory.jsonl`, which are themselves the append-only ledgers
of what happened. The store records no event of its own, so `--rebuild`
regenerates it (atomically) and destroys no history — while leaving a fixed
extractor's known-wrong rows in place *would* leave bad text readable by the
conditioning seam. A row whose id moves in a rebuild carries
`legacy_constraint_id` so an older citation still resolves.

`memory/frontier_agenda.jsonl` is the opposite and stays strictly
**append-only**: it is the human-facing proposal queue and its rows carry a
lifecycle (`orchestrator/agenda_cli.py` rules on them). A distilled proposal
that a fixed extractor would no longer produce is **reported to the human**,
never deleted.

### Reconcile of the 2026-08-19 rebuild — one proposal is owed a ruling

The rebuild replaced all 112 rows (50 → 33 fragments, 22 → 11 rows carrying
controls); 14 ids moved under the full-text hash and each carries
`legacy_constraint_id`, so all four agenda citations still resolve. The
agenda file was **not modified** — byte-identical, and the three still-valid
clusters were skipped as already present.

One row needs the owner's eye. **`fa-43df1c54`** (`cl-iter-2026-05-27-004`)
was re-scoped to *"controls for which component drives the prediction"* —
which is not a control at all but a clause of the reviewer's complaint ("the
candidate neither specifies nor **controls for** which component drives the
prediction"). Its constraint now carries `missing_controls: []`, and the only
other row for that cluster is an `inconclusive`, which by the rules above
**cannot** produce a proposal. So this proposal exists solely because of the
extraction defect: **the fixed distiller does not produce it, and would not.**
It is left on the agenda, still `status: "proposed"` and still inert; the
ruling (`agenda_cli.py reject`, or accept it on its own merits) is the
human's, not the apparatus's.

The other three remain justified on genuine controls:
`fa-4453269d` → *no matched-history control*; `fa-93c91ab3` → *a well-mixed
or complete-graph baseline*; `fa-098ba109` → *comparison against random
perturbations or prior-only inference*.

Tests: `tests/test_constraint_distill.py` (extraction accept/reject pinned on
the live fragments, flaw-class rules, cross-run proposal idempotency, the
agenda flock, CLI hermeticity, rebuild — fixtures are verbatim live screen
texts) and the gate tests in `tests/test_meta_review.py`. Run with
`MOCK_LLM=1`; no model is involved either way.
