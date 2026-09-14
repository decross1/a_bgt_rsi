# V2 research data model audit

**Campaign:** `v2-agentic-game-theory-20260914`
**Audit date:** 2026-09-14
**Scope:** active research identity, cohort isolation, and the minimum additive
contract needed to start a fresh game-theory and agent-behavior program without
rewriting the v0/v1 evidence record.

## Decision

V2 uses an immutable, hash-bound campaign declaration and copies one closed
campaign link onto each new iteration and surfaced finding. Membership is an
exact link comparison. Similar prose, a recent timestamp, or the current active
campaign never relabels an old record.

The runtime selection is a separate, reversible pointer:
`run_state/active_research_campaign.json`. With no pointer and no environment
assertion, existing behavior remains the legacy/global cohort. A valid pointer
activates one registered manifest for both hourly coordinator entry and the
Nara daemon. `NARA_RESEARCH_CAMPAIGN` may assert the same campaign ID; it cannot
activate a campaign by itself, and any mismatch fails before a model call.
A closure is another immutable receipt at
`run_state/research_campaign_closures/<campaign_id>.json`. Its campaign ID,
manifest hash, and chronology must match the active pointer; once present, the
campaign path fails closed. Neither lifecycle receipt edits the declaration or
changes links already stored in records.

The campaign declaration always remains `prepared`; lifecycle is separate.
This audit describes the implementation before root deployment. Subsequent
activation and service adoption are recorded in the canonical
`run_state/v2_preparation/deployment_receipt.json`, not inferred from this audit.
Neither activation nor CPU calibration registration is an LLM study result.

### Immutable extension policy

Do not append a future study to an activated campaign manifest: changing its
bytes would change the hash embedded in every existing campaign link. The
follow-on study path is an additive immutable registration receipt under
`run_state/research_campaign_studies/<campaign_id>/<study_id>.json`. That future
receipt must bind the stable campaign manifest hash plus exact study-manifest
and preregistration hashes, and its reader must reject duplicate study IDs or
redirected paths before any study runs. A larger change to the research
question instead requires a new campaign ID with an explicit predecessor link.
The receipt schema/reader is future qualification work; no model study is
registered by this patch.

## Active contracts

| Artifact | Producer | Main consumers | Schema/version | Identity and time | Missing/null meaning | Privacy class |
|---|---|---|---|---|---|---|
| Campaign manifest (`experiments/research_campaign_*.json`) | Owner-reviewed repository change | campaign loader, coordinator, progress projection | `research-campaign/v1` | `campaign_id`; `opened_at`; whole-file SHA-256; declaration `status=prepared` and `closed_at=null` are immutable | Unregistered/invalid means unavailable and execution refuses; lifecycle comes from receipts | Public research declaration; no prompts or hidden grading |
| Active campaign pointer (`run_state/active_research_campaign.json`) | Operator at adoption | coordinator, Nara, daemon | `research-campaign-activation/v1` | singleton pointer; `activated_at`; exact campaign manifest SHA-256 | Absent means legacy/global runtime; malformed or environment mismatch means fail closed | Public operational provenance; no credential material |
| Campaign closure (`run_state/research_campaign_closures/<campaign_id>.json`) | Operator at closure | activation resolver, progress projection | `research-campaign-closure/v1` | `campaign_id`; `closed_at`; exact campaign manifest SHA-256 | Absent means no recorded closure; malformed, mismatched, future, or pre-activation receipt fails closed | Public operational provenance; no credential material |
| Loop memory (`memory/loop_memory.jsonl`) | `orchestrator.nara` through `journal_stub.finalize_iteration_record` | coordinator, meta-review, promotion, progress | `iteration_record.schema.json`; optional `research-campaign-link/v1` | `iteration_id`; `started_at`/`ended_at` | Missing campaign link is `unlinked_legacy`, never an implicit match; optional stage blocks mean stage evidence unavailable | Internal research record; may contain model prose and paths, so UI must project bounded fields |
| Idea ledger (`memory/idea_ledger.jsonl`) | `workers.idea_ledger.append_event` and reducers | agenda, evidence ladder, refinement | `idea_ledger.schema.json`; heterogeneous event union | `cluster_id` plus event identity; `ts` | Legacy event schema has no campaign relation. It is shared negative memory only when a reader records an explicit matched member/evidence key | Internal research memory; bounded structured claims plus deterministic reason text |
| Surfaced findings (`memory/surfaced_findings.jsonl`) | `orchestrator.finding_promotion` | finding sessions, UI/progress | `surfaced_finding.schema.json`; optional `research-campaign-link/v1` | `finding_id`; `source_iteration_id`; `promoted_at` | Missing campaign link is legacy. V2 promotions copy the exact source-iteration link | Review-facing research result; contains claim and evidence prose; bounded UI projection only |
| Human feedback (`memory/loop_feedback.jsonl`) | `orchestrator.gate_cli` | meta-review, coordinator, promotion | frozen `loop_feedback.schema.json` | `iteration_id`; `gated_at` | No row means no human verdict. It has no campaign field and may join V2 only through one uniquely exact-matching iteration ID | Human-authored internal annotation; never model ground truth by itself |
| Promotion near misses (`memory/promotion_near_misses.jsonl`) | coordinator persistence of promotion results | UI/diagnostics | legacy heterogeneous rows; no unified V2 schema | `source_iteration_id`, stage/reason, timestamp | No campaign field. Join only through one uniquely exact-matching iteration ID | Internal diagnostic prose; never a scientific verdict |
| Coordinator cycles (`run_state/coordinator_cycles.jsonl`) | `coordinator_cycle_log` | daemon health, UI/progress | Python-validated historical shape; additive campaign link/context | `run_id`; `timestamp`; optional exact campaign link | Legacy rows remain unlinked. Current single-topic campaign cycles carry the exact topic link; campaign context records the planner cohort even on refusal | Operational/research metadata; outcomes are status summaries, not raw model text |
| Model calls (`logs/calls.jsonl`) | `agent_wrapper.wrapper` | audit, eval, telemetry | `calls.jsonl.schema.json` | UUID `request_id`; `timestamp`; `parent_request_id` | Null parent/seed has the schema meaning; absence is missing telemetry, never zero usage | Private/internal: full prompts and completions. Never expose raw rows in the progress API |
| Weekly trial journals (`run_state/weekly_upgrade/trials/*.json`) | weekly trial controller | receipt validators, benchmark projection | kind-specific strict receipt contracts; no single universal result schema | `trial_id`/`terminal_run_id`, ISO week, manifest and artifact hashes | Invalid/missing receipt is unavailable evidence. Terminal transport is distinct from complete/scored evaluation | Internal operational evidence; public UI receives only bounded metrics/status/hashes |
| Weekly evaluation summaries (`run_state/weekly_upgrade/evaluations/*.json`) | operator/evaluation recorder after receipt validation | progress projection, weekly review | family-specific observation schemas | trial/run IDs and bound artifact hashes; recorded timestamp | Operator annotation may be absent or partial. It never upgrades transport success into scientific truth | Mixed: bounded counts/verdict provenance may be public; raw model text and hidden graders remain private |

The weekly rows intentionally remain heterogeneous. A context-capability
summary, diversity-selection score, historical repair grade, and role-effort
trial do not become comparable merely because they share an ISO week. Their
existing family-specific receipt validators remain the authority.

## Campaign link and classification

Each iteration and finding link has exactly:

```json
{
  "schema_version": "research-campaign-link/v1",
  "campaign_id": "v2-agentic-game-theory-20260914",
  "campaign_manifest_sha256": "<64 lowercase hex>",
  "research_question_id": "rq-incentives-identified-history-001",
  "research_question_sha256": "<64 lowercase hex>",
  "topic_id": "topic-incentives-identified-history-001",
  "topic_sha256": "<64 lowercase hex>"
}
```

Readers classify a record as one of:

- `explicit_match`
- `unlinked_legacy`
- `malformed_campaign_link`
- `different_campaign`
- `campaign_link_mismatch`
- `malformed_record`

Only `explicit_match` enters V2 counts, conditioning, planner state, promotion,
or public campaign progress. Feedback and promotion-near-miss rows inherit no
membership of their own; they may be joined only after their iteration ID
resolves uniquely to an `explicit_match` iteration.

## Propagation and action isolation

The campaign-aware path is:

```text
active pointer + optional matching env assertion
  -> coordinator assessment filters iteration/finding cohorts
  -> exact preregistered topic suggestion carries the campaign link
  -> campaign action gate rejects global/deferred actions and rewritten topics
  -> Nara copies the link to active state, start/completion events, iteration
  -> meta-review conditions only on explicit-match prior iterations
  -> promotion examines only explicit-match iterations
  -> surfaced finding copies the source link byte-for-byte
```

The admitted campaign actions are `run_loop_iteration`, `promote_findings`,
`bubble_up`, and `noop`. Campaign planning currently defers global experiment,
forecast, paper-gap, idea-refinement, and system-improvement actions. A generic
bubble remains available; a finding-ID bubble may name only a currently
surfaced campaign finding.

Shared literature remains available with source provenance. The old idea and
design-constraint ledgers lack campaign relations, so their generated topic and
claim conditioning is excluded. A negative-memory lookup may still match an
old cluster by explicit evidence/member identity; that match remains visible in
the new iteration rather than silently importing the old claim as a V2 outcome.

## Legacy treatment

- Do not add campaign links to existing loop, finding, feedback, idea-ledger,
  cycle, or weekly-evaluation rows.
- Do not infer cohort membership from the campaign opening time.
- Do not infer membership from an equal or similar question string.
- Keep shared literature and archives readable; cohort isolation applies to
  outcomes and conditioning, not source erasure.
- Preserve all append-only histories. V2 adds fields and filters readers.

## Remaining qualification work

1. Independent review of the manifest, schemas, activation resolver,
   coordinator admission, Nara propagation, and promotion filter is complete;
   the final backend slice passed 270 selected tests and an independent
   80-test review. See [cross-review](CROSS_REVIEW.md).
2. Keep the activation pointer absent until the campaign is deliberately
   adopted. At adoption, write one pointer bound to the reviewed manifest hash;
   removing/restoring that small receipt is the rollback. Do not edit the
   manifest `status` or `closed_at`. A later closure uses the separate closure
   receipt and permanently blocks that exact active campaign lineage.
3. Foundation activation does not wait for an LLM-study registration. Before
   any model study itself executes, implement the additive study-registration
   receipt described above and bind its manifest/preregistration by exact
   hashes. Never edit the active campaign manifest. A study receipt means
   registered, not executed.
4. Run the CPU calibration and preserve its bound result receipt separately.
   `cpu_calibration_registered` and `cpu_calibration_verified` are different
   public states. These controls validate the payoff and measurement apparatus;
   they do not constitute evidence about LLM-agent behavior.
5. Run the first controlled model pilot only after its own preregistration and
   admission checks. The current campaign declaration contains no model-study
   reference, so its public `model_trial_status` is `not_registered`. Once a
   model study is registered, the absence of an exact hash-bound result means
   `registered_no_bound_result`, not a claim that no external run occurred.
6. Campaign-qualify experiment/refinement writers before admitting those
   actions. They remain deferred rather than silently writing global evidence.

## Evidence map

- Campaign validation, bounded reads, activation binding, and explicit-match
  classification: `orchestrator/research_campaign.py`.
- Exact campaign declaration:
  `experiments/research_campaign_v2_agentic_game_theory_20260914.json`.
- Additive record contracts: `schema/iteration_record.schema.json` and
  `schema/surfaced_finding.schema.json`.
- Iteration writer: `orchestrator/nara.py`; durable append:
  `orchestrator/journal_stub.py`.
- Campaign-filtered conditioning: `workers/meta_review.py`.
- Campaign-aware planner/action admission: `orchestrator/coordinator.py`.
- Cycle projection: `orchestrator/coordinator_cycle_log.py`.
- Campaign-filtered promotion: `orchestrator/finding_promotion.py`.
- Shared runtime selection for daemon and cron entry: coordinator entry plus
  `orchestrator/nara_daemon.py`.
- Isolation and backward-compatibility proofs:
  `tests/test_research_campaign.py`,
  `tests/test_research_campaign_propagation.py`,
  `tests/test_loop_v1_integration.py`, `tests/test_meta_review.py`, and
  `tests/test_finding_promotion.py`.
