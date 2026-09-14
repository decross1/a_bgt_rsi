# Machine-topic starvation audit

**Observed:** 2026-09-14T05:14:48Z
**Window:** 2026-09-07T00:00:00Z through the source snapshots below
**Method:** Read-only local JSONL aggregation and read-only Chroma metadata
queries. No model call, service action, queue mutation, hypothesis triage, or
scientific-ledger write was performed. This report deliberately contains no
paper title, hypothesis text, abstract, or topic text.

This is a source-selection audit taken after the separate 59-row topicality
audit. The live window had advanced to 60 completed iterations, and this audit
adds coordinator-plan, suggestion-source, queue, agenda, and paper-category
provenance needed to identify the repeat mechanism.

## Snapshot identity

| Source | Bytes | SHA-256 |
|---|---:|---|
| `memory/finding_followups.jsonl` | 6,423 | `c63de67488e18c7aed92b60b0d3ed28d9ce03066b03cd352a629ba6db12c898d` |
| `memory/idea_ledger.jsonl` | 142,498 | `e4023ce56c625be6890e99fef4872fc6302613cef5c06525bb3d8c2ef840bf83` |
| `memory/loop_memory.jsonl` | 8,564,469 | `542427d9a73f16dd840b07b21a8eebfccbe41bfa3e11516a312166a43b84b2c6` |
| `run_state/coordinator_cycles.jsonl` | 1,859,377 | `4279661e77926ee08517b46197ce1e7742d80ef706f88733c2471a3028e9133c` |
| `logs/calls.jsonl` | 104,320,720 | `1c778a87d4b4bba83a3b5b184ba0ca7ccca13356cc48e9a2787f9fe1cca7febe` |

## Aggregate observations

### Queue and agenda

- The follow-up queue contains 4 rows, all with machine origin
  `coordinator_propose` and provenance `paper_gap`; it contains 0 human rows.
- Queue creation dates span 2026-08-15 through 2026-08-26. The file had not
  changed since 2026-08-26T18:06:45Z.
- The two tail queue records map to `cs.MA` source metadata and publication
  dates 2026-08-19 and 2026-08-25.
- The idea ledger contains 545 events across 223 reduced clusters. It has 4
  `agenda_item_added` and 4 `agenda_item_consumed` events, leaving 0 open
  projected agenda topics.
- Each paper-gap proposal was written to both the follow-up queue and the idea
  ledger. Agenda consumption closed one copy but did not alter the separate
  follow-up row.

### Coordinator selection

- 220 coordinator cycles occurred in the window; 60 planned a loop iteration.
- All 220 exposed the same source sequence:
  `coordinator_propose`, `coordinator_propose`, `arxiv_pick`.
- All 60 loop plans selected suggestion index 1. Every selection matched the
  final follow-up queue row; none matched the penultimate row.
- Those 60 plans therefore used 1 unique seed topic even though a current
  `arxiv_pick` option was present in every cycle.
- The cycle-log serializer recorded suggestion index 0's source before
  replacing the topic with the plan's actual topic. The observed source happened
  to have the same class, but the serializer could misattribute any future
  non-first selection whose source class differs.

### Downstream outcome

- The 60 completed loop records all carried coordinator seed provenance and 1
  unique seed topic, while producing 60 distinct hypothesis records.
- All 60 final relevance results were `off_domain` under rule `R0`.
- Novelty outcomes were 57 `unclear` and 3 `rediscovery`; critique outcomes were
  54 `undecidable` and 6 `restated`.
- The primary topicality path made 90 calls across the 60 run IDs: 30 runs had
  one check and 30 had two. All 90 responses parsed as literal `domain=off`;
  there were no malformed or unavailable judgments in this set.

### Paper-source context

- `papers_recent` held 1,883 records dated 2008-05-21 through 2026-09-10.
- Category counts were 934 `cs.MA`, 622 `cs.GT`, 298 `econ.TH`, and 29 across
  all other categories. Category metadata alone does not establish topical
  admissibility; it records why a broad multi-agent paper could enter the source
  pool.

## Diagnosis

The repeated selection was caused by a stale, non-consuming machine-follow-up
copy. `orchestrator/coordinator.py::_topic_suggestions` repeatedly read the last
two queue rows. `_consume_agenda_topic` only closed the idea-ledger copy after a
successful agenda dispatch, so the corresponding machine queue row survived and
the planner selected it again. The planner's prose-level instruction against
repetition was not programmatically enforced.

This was not the morning-topic fallback: a live `arxiv_pick` was present in all
220 cycles. It was also not evidence that downstream topicality had failed: the
judge consistently rejected the resulting hypotheses, but that check occurs
after generation and retrieval and therefore cannot stop seed selection.

## Bounded repair in this delivery

The repair does not alter the research-domain contract and does not create a new
state ledger.

1. A machine `coordinator_propose` row is suppressed only when existing durable
   evidence proves it handled: an unambiguous successful coordinator-dispatch
   receipt for the exact topic or a consumed paper-gap agenda receipt for that
   exact topic. A finalized loop-memory row alone is not consumption
   evidence because Nara may finalize a degraded, fallback-completed iteration.
   The coordinator receipt establishes successful dispatch under the recorded
   API; it does not claim that every scientific substep produced strong evidence.
2. Human finding follow-ups are never filtered by that evidence.
3. Failed or ambiguous coordinator outcomes and pending agenda items do not
   suppress a row, so a failed dispatch remains retryable.
4. Filtering occurs before the two-row queue cap, preventing stale handled rows
   from crowding out eligible work; the morning arXiv option remains appended.
5. Cycle-log attribution now matches the actual planned topic to its suggestion
   source. An unmatched topic, or duplicate exact-topic suggestions carrying
   conflicting sources, is reported with an unknown (`null`) source rather than
   inheriting suggestion index 0's source.

Paper-domain admission and broader repeat-policy changes remain outside this
repair. They depend on the owner's intended research scope and require separate
calibration.

## Read-only repair replay

Applying the repaired evidence projection to the frozen sources above produced
18 handled exact-topic keys. All 4 machine queue rows matched durable handled
evidence, leaving 0 eligible stale machine rows. This replay read the canonical
files without invoking the morning picker or writing state; hermetic tests cover
that a fresh arXiv option remains present after filtering.
