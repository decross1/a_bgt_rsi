# Retired autonomy-v1 sweepers

This directory preserves fourteen files removed from active code discovery on
2026-09-14. They implemented, tested, or proposed contracts for the Track
A/B/C/D ownership, claim, dispatch, and soft/hard-gate framework that the
repository retired on 2026-05-26 in commit `08fc327`.

The copies have a `.txt` suffix and mode `0644`. They are source evidence, not
Python modules, pytest inputs, or cron entrypoints.

## Why these files are retired

- `agent/README.md` says the ownership registry, claim/lock protocol, and
  autonomy-tier machinery are archived references rather than active rules.
- The tools depend on retired or absent inputs including
  `agent/ownership.yaml`, `agent/autonomy.md`,
  `run_state/claims.jsonl`, and `run_state/attestations.jsonl`.
- A tracked-source reference scan found no active importer or caller outside
  the two cron wrappers and their two dedicated test files. Remaining mentions
  are historical documentation or comments.
- Both cron wrappers describe themselves as not installed. The user crontab
  inspected on 2026-09-14 contained neither wrapper, and no user or system
  timer matched `claim` or `sla`.
- Before archival, the dedicated test pair still passed (`41 passed`). That
  establishes that the preserved implementation was internally coherent; it
  does not make its retired operating contract live.

The old coding dispatcher and draft-schema cluster met the same removal bar:

- `agent_wrapper/dispatch_coding_agent.py` requires the absent
  `agent/ownership.yaml` and `agent/prompts/dispatched_task.md`. Its dedicated
  test is module-level skipped with the retirement reason.
- The active dispatcher is `orchestrator/packet_dispatcher.py`, which consumes
  `schema/task_packet.schema.json` and explicitly does not import the old
  dispatcher.
- The four files under `schema/proposed/` were dated Day-8/Day-9 drafts. A
  tracked-source reference scan found no producer, loader, registry, launcher,
  or installed scheduler using them outside their dedicated tests and
  historical prose.
- Before archival, the proposal/dispatcher test slice reported `67 passed, 1
  skipped, 35 subtests passed`. The active task-packet, packet-dispatch,
  self-improvement, and lab-channel slice separately reported `133 passed, 19
  subtests passed`.

Active concurrency and weekly-upgrade coordination use the current repository
and runtime contracts. These archived tools must not be restored piecemeal.
Revival would require a new decision, restored data contracts, current security
review, and explicit scheduler installation.

## Preserved files

| Original path | Preserved path | SHA-256 of original bytes |
| --- | --- | --- |
| `tools/claims_check.py` | `tools/claims_check.py.txt` | `495c62adebdd3f7cfb857a0981cdcda9a55ee772c33020d1f6a2b32b624b87a3` |
| `tools/gate_sla_check.py` | `tools/gate_sla_check.py.txt` | `e28ed37b9ce112bc477f7d5d757aede6e29db6e30a9791d0fb474fa64a1a2dbe` |
| `cron/claims-weekly.sh` | `cron/claims-weekly.sh.txt` | `8ef78b875453dafafe344c98620c0d5b977fa7a69287b31875301e00aa3aa5b3` |
| `cron/sla-sweep.sh` | `cron/sla-sweep.sh.txt` | `716aa0a473cf417e6093dbf3e7654554b79ab18363054be7bbc13747447fdca3` |
| `tests/test_claims_check.py` | `tests/test_claims_check.py.txt` | `e6833740bb9386c2c257119973115cd05e44adc4acd6626d9a6e89faebfa0f73` |
| `tests/test_gate_sla_check.py` | `tests/test_gate_sla_check.py.txt` | `fafca2cb3bdb22186f4150c35ca7a74efb1c0fca790c379672644926362de38a` |
| `agent_wrapper/dispatch_coding_agent.py` | `agent_wrapper/dispatch_coding_agent.py.txt` | `f391f7593a134fdfa739ad5fb72e22c50244bcf64fa6235fc3f64d3b0662749e` |
| `schema/proposed/calls.jsonl.schema.json` | `schema/proposed/calls.jsonl.schema.json.txt` | `4669cb9220f79a9df221f28238b762c5bd8ef467624f160f19cab20ee7e226dc` |
| `schema/proposed/dispatched_task.schema.json` | `schema/proposed/dispatched_task.schema.json.txt` | `70ad4f8980478781d18b6b375bd2eef4df03aed1bbb220cc806d86c6f3829165` |
| `schema/proposed/events.jsonl.schema.json` | `schema/proposed/events.jsonl.schema.json.txt` | `4553887fb7e52a60a858193a890430cb267b304542d827e88ccd9bed3f1ea006` |
| `schema/proposed/events_v2_separate_gate_clear.jsonl.schema.json` | `schema/proposed/events_v2_separate_gate_clear.jsonl.schema.json.txt` | `5d77af45a0997bc30377d8278672d674748484175c8635ef892fd289ef820228` |
| `tests/test_calls_schema_proposed.py` | `tests/test_calls_schema_proposed.py.txt` | `d16dd8be36159d1ebe7344691423a3655f75d5bf0a0e40f159f86899ba0ba681` |
| `tests/test_dispatch_coding_agent.py` | `tests/test_dispatch_coding_agent.py.txt` | `e11a1f22d24765eb08aa825e5038fc1dacde7b4b59c0e510964386e0da42e144` |
| `tests/test_events_schema_proposed.py` | `tests/test_events_schema_proposed.py.txt` | `0080288ccc31784bcdb7b561bb3588dc00ec0712c59350797bc6508783d492d2` |

The hashes cover the file bodies before renaming; the archived `.txt` copies
have the same hashes.
