# V0/v1 research archive

A verified local archive preserves the pre-v2 research, benchmark evidence, documentation, and human records. Original files remain available. The archive contains **20,310 files / 959,334,485 bytes** and was verified against every recorded SHA-256 checksum.

The manifest identity is `ef57b8e8027d04bc3c93c171d736438b852f5b23a5e51989d9883cbdbc33025f`. The machine-local location is recorded in `run_state/v2_preparation/archive_receipt.json`; raw research and private maintenance notes are not published with this documentation.

## Contents

| Source group | Files |
| --- | ---: |
| external-1/2026-W38 | 194 |
| external-2/2026-W38 | 27 |
| external-3/chroma_db-20260913T043001Z.tar.gz | 1 |
| external-3/receipt.json | 1 |
| repository/AGENTS.md | 1 |
| repository/ARCHITECTURE.md | 1 |
| repository/CLAUDE.md | 1 |
| repository/DECISIONS.md | 1 |
| repository/LOOP_V0.md | 1 |
| repository/LOOP_V1.md | 1 |
| repository/PROJECT_CONTEXT.md | 1 |
| repository/README.md | 1 |
| repository/START_HERE.md | 1 |
| repository/archive | 55 |
| repository/bench | 108 |
| repository/books | 1 |
| repository/chroma_db | 1 |
| repository/docs | 82 |
| repository/experiments | 266 |
| repository/human | 39 |
| repository/journal | 401 |
| repository/logs | 26 |
| repository/memory | 30 |
| repository/notes | 17453 |
| repository/run_state | 1610 |
| repository/tasks | 6 |

## Preservation and retrieval

The archive has `files/` copies plus `manifest.json` and `manifest.sha256`. Each manifest entry binds its source group, relative path, exact byte length, checksum and capture metadata. Original research scores are not revised by the archive. Human notes and journals are copied verbatim and are not interpreted as machine-authored lessons.

Snapshots have per-file cutoffs, not a global transaction across running services. Growing append-only logs retain a verified captured prefix. Symlinks are not followed; named credential-path patterns and environment/cache directories are excluded and recorded as exclusions. Private contents are not secret-scanned or content-classified. The shared literature/vector store stays in place; its source manifest is included. The existing 2026-09-13 04:30 UTC literature backup is also preserved as an external source with verified compressed bytes; it predates the current live database and has not had a restore rehearsal. The live store is retained. Model weights and installed environments are outside the archive.

Verify or retrieve locally:

```bash
python3 tools/research_archive.py verify --archive /path/from/archive_receipt
```

Use `manifest.json` to locate an original relative path under `files/repository/`. Historical external benchmark and review runs live under `files/external-1/` and `files/external-2/`; the private manifest records their exact source roots. The literature backup and its receipt are under `files/external-3/`. Archive verification checks every retained file and refuses missing, changed, redirected or unlisted files.

## V2 boundary

V2 starts a fresh campaign within game theory and agent behavior. Prior findings remain historical evidence, not automatic new-campaign successes. Shared literature and prior failure knowledge remain available with explicit provenance. Active operational ledgers are not truncated or silently repurposed.

Earlier narrower snapshots are retained. The final capture ran from 22:29:52 to 22:31:24 UTC on 2026-09-14 and includes the three initial followthrough trials, operational model-call logs, books copied verbatim, and existing source archives. `archive_receipts.jsonl` preserves prior receipts; `archive_receipt.json` points to this most comprehensive verified capture. Later v2 activity is new evidence and is not retroactively inserted into this immutable archive.
