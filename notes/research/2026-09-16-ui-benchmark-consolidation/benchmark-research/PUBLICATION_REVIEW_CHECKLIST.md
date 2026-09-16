# Stable Benchmark v1 Publication Review Checklist

This checklist is bounded to release `1.0.0`. Every prepublication review item must be recorded before creating a publication witness. A failed review item keeps the definition in `draft`; it does not authorize an ad hoc edit during a live window. Checked items record the completed publication review, while the remaining unchecked items are prospective execution steps that require terminal receipts.

## Definition and construct review

- [x] `definition.draft.json` loads with `load_definition()`, passes `definition.schema.json`, and its raw SHA-256 matches the review receipt.
- [x] Exactly 21 ordered units exist: science/evidence 4, functional repair 4, deterministic tools 4, strategic 6, actor–tool–critic micro-workflows 3.
- [x] Strategic rows are public goods 2, Vickrey 2, Cournot 1, and ex ante Brier reporting 1; each prompt says to maximize own payoff.
- [x] Trusted code derives own utility and regret. Brier uses private belief 0.65 before an outcome and labels joint utility descriptive only.
- [x] Public family counts are descriptive. No cross-domain credited total or omnibus score is projected; regret is aggregated within mechanism only.
- [x] SYSTEM claim scope says actor–tool–critic micro-workflows and makes no whole-orchestrator or production-funnel claim.
- [x] Every exact output enum and field name required by evidence and SYSTEM graders is disclosed in the public prompt; evidence asks for the minimal sufficient citation set.
- [x] Quantitative prompts disclose the grader's `1e-9` absolute tolerance and require enough decimal precision for repeating values.

## Resource and route review

- [x] Task ceilings recompute to 29 calls/arm, 58 paired, 25,088 output tokens/arm, 1,575 summed episode seconds/arm, and a 7,200-second supervised ceiling.
- [x] Resident role map names exact production routes: capability/actor Gemma and critic Qwen; profiles and every resolved policy lever are explicit.
- [x] Every route is used, labels and model/profile names are bounded, temperature is in `[0,2]`, top-p in `(0,1]`, and sampling extras use only supported bounded fields.
- [x] Harness source hashes include the stable runner/graders/manifest, code sandbox, wrapper, generation policy, worker activity, local backends, lease, and calls schema.
- [x] A candidate transport cannot silently route Flash through the resident Qwen wrapper. Endpoint binding remains a supervisor gate.

## Integrity and privacy review

- [x] Definition, manifest, run, replay, admission, and projection loaders reject symlinks, oversized input, duplicate JSON keys, non-finite numbers, and excessive JSON shape where applicable.
- [x] Run receipts account for all ordered tasks and every attempted call; unknown transport attempts are conservatively charged and cannot be admitted as exact.
- [x] Wrapped actor/critic endpoint timeouts remain `timeout`, while other transport failures remain `transport_error`.
- [x] Replay reruns objective graders and code sandboxes from private raw evidence and checks execution source hashes.
- [x] Admission independently binds definition, run manifest, arm, comparison cohort, run, replay, execution gate, controller source bundle, monitor end, guard result, and restoration.
- [x] A checked-in comparison registration orders `reference` then `candidate`, freezes both manifests and historical source maps, and binds the lifecycle plan, worker argv, controller sources, and receipt directories before execution.
- [x] Public projection exposes no prompt, grader input, hidden case, raw completion, arbitrary receipt object, or private path.
- [x] `invalid`, `skipped_budget`, and `unissued` cells never receive an admitted score. Warranted abstention stays visible.

## Historical and statistical review

- [x] `baseline_status` remains `not_started`; no 87/126, 101/126, context, fresh, cap, payoff, or calibration result is converted into a v1 baseline.
- [x] The canary is described as a fixed public regression instrument, not broad scientific intelligence or a sufficient model-selection proof.
- [x] Repeated public-goods and Vickrey rows share mechanism clusters. Intervals are omitted below four clusters and remain descriptive otherwise.
- [x] No small-N result authorizes automatic promotion.
- [x] External rotations remain outside v1 and require exact version, license review, selected IDs, oracle replay, and ARM/resource pilot.

## Publication and initial run

- [x] Create a public Git or preregistration witness for the reviewed draft bytes; record its actual UTC timestamp and SHA-256.
- [x] Generate `definition.published.json` from those reviewed bytes with `publish_definition()`; do not invent or predate publication.
- [x] Confirm `published_at < 2026-10-14T00:00:00Z`; reaching that review boundary requires an explicit extension or new release.
- [x] Commit the published definition, ordered comparison registration, frozen release copies, schemas, source bundle, and review receipt before inference. The fixed `definition.published.json` path selects the release; `registered_at` orders its comparison cohorts.
- [ ] Execute the resident arm only after its external runtime gate; replay and admit it after restoration.
- [ ] Write the Flash arm as `unissued`, 21/21 accounted and zero calls, with the final startup-pageout gate reason. Do not create a pairwise loss or imputed score.
- [ ] Run focused stable package, supervisor-window, backend projection/history, JSON-schema, compile, and repository-required tests from the frozen commit.

## Recorded review values

- Current reviewed draft SHA-256: `f682b506defab469f0d69d4d3b59d8d60744900f8d8980e5e0ddcfa6a4379187` (supersedes the pre-contract-audit draft).
- Review boundary: `2026-10-14T00:00:00Z`.
- Current candidate disposition: runtime-gate startup abort, zero stable-suite calls; stable arm `unissued`.
- Causal source/draft witness: [`e95073dc5ae6ec266b196ec9c5bba6cab91aba46`](https://github.com/decross1/a_bgt_rsi/commit/e95073dc5ae6ec266b196ec9c5bba6cab91aba46), committed `2026-09-16T05:20:16Z`.
- Published definition and registration witness: [`1fa863cef3dbd288d8408838e3138e00ece20aba`](https://github.com/decross1/a_bgt_rsi/commit/1fa863cef3dbd288d8408838e3138e00ece20aba), committed `2026-09-16T05:28:35Z`.
- Recorded `published_at`: `2026-09-16T05:22:36.754311Z`.
- Published definition SHA-256: `75de9dc0dc324a4559332f88ae6e5ae861ba0d6f683334d85395d082bbaf04df`.
- Comparison registration SHA-256: `87f048a9062bdb09aa79cd913b3f146d89b1f710afdbe8b020c11ba0d81a9c04`.
- Resident window-plan SHA-256: `f8899e16356c063637707cbf487ee55ddcb17009ce8f1c7bed363a2b81feab80`.
- Baseline at publication: `not_started`; no inference had been issued.
