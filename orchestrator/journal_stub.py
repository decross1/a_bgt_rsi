"""Journal-writer stub for LOOP_V0 Part 1 (hello-world).

The full journal_writer (Part 2) accepts a complete iteration_record
(hypothesis + retrieval + novelty + critique) and writes both the
JSONL row and a structured markdown entry. For Part 1, the stub
accepts just `summary` and `tool_calls_made` from Nara and writes a
minimal-but-schema-valid iteration_record.

The orchestrator (`nara.py`) passes through the iteration metadata
(iteration_id, started_at, etc.) via the Runtime closure pattern —
journal_writer_stub itself is called with only the LLM-supplied args
plus the Runtime's parent_request_id; the orchestrator fills the
metadata when it finalizes the row.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "iteration_record.schema.json"
LOOP_MEMORY_PATH = REPO_ROOT / "run_state" / "loop_memory.jsonl"
JOURNAL_DIR = REPO_ROOT / "journal" / "iterations"

_VALIDATOR = jsonschema.Draft7Validator(json.loads(SCHEMA_PATH.read_text()))


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_iteration_number() -> int:
    """Sequential NNN for journal/iterations/NNN.md based on existing entries."""
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(JOURNAL_DIR.glob("*.md"))
    if not existing:
        return 1
    # File names look like '001.md', '042.md'.
    try:
        last_n = max(int(p.stem) for p in existing if p.stem.isdigit())
    except ValueError:
        return len(existing) + 1
    return last_n + 1


def journal_writer_stub(
    summary: str,
    tool_calls_made: list[str],
    *,
    parent_request_id: str | None = None,
) -> dict:
    """LLM-callable tool. Returns the path of the journal entry written
    and the path of the loop_memory row.

    The orchestrator (`nara.py`) post-processes the returned dict and
    promotes it into a full iteration_record at end-of-iteration. This
    function just persists what the LLM gave us, in the right shape.

    For now this writes a minimal markdown stub and DOES NOT write to
    loop_memory.jsonl directly — the orchestrator handles that at
    end-of-iteration after collecting iteration_id, started_at, etc.
    """
    nnn = _next_iteration_number()
    md_path = JOURNAL_DIR / f"{nnn:03d}.md"
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    md = [
        f"# Iteration {nnn:03d}",
        "",
        f"*Written: {_utcnow_iso()}*",
        "",
        "## Nara's summary",
        "",
        summary,
        "",
        "## Tools called",
        "",
    ]
    for t in tool_calls_made:
        md.append(f"- `{t}`")
    md.append("")
    md_path.write_text("\n".join(md))

    return {
        "status": "passed",
        "result": {
            "journal_entry_path": f"journal/iterations/{nnn:03d}.md",
            "iteration_number": nnn,
            "summary": summary,
            "tool_calls_made": tool_calls_made,
        },
        "errors": [],
        "parent_request_id": parent_request_id,
    }


def finalize_iteration_record(record: dict) -> dict:
    """Validate a complete iteration_record against the schema and
    append one row to loop_memory.jsonl. Called by nara.py at
    end-of-iteration. Not exposed as an LLM tool.

    Raises jsonschema.ValidationError if the record is malformed.
    """
    errs = list(_VALIDATOR.iter_errors(record))
    if errs:
        raise jsonschema.ValidationError(
            f"iteration_record invalid: {errs[0].message} "
            f"(path: {list(errs[0].absolute_path)})"
        )
    LOOP_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOOP_MEMORY_PATH, "a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "status": "passed",
        "loop_memory_path": "run_state/loop_memory.jsonl",
        "iteration_id": record["iteration_id"],
    }
