"""LOOP_V0 step 1.5 worker — meta-review synthesis.

An *active read* of loop memory: tail the last `n` iteration_records,
join the human gate verdicts from `loop_feedback.jsonl`, and ask Gemma
to distill 3–5 conditioning bullets — what kept winning, what kept
losing (especially patterns a human marked "invalid"), and what
surprised. The orchestrator runs this as a pre-step before the LLM
loop so the next iteration is conditioned on the loop's own history.

The LLM call goes through `agent_wrapper.wrapper.call_sync`, which
auto-logs to `logs/calls.jsonl` with full provenance. The JSON
extraction reuses the same balanced-brace scanner as hypothesize.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from agent_wrapper.wrapper import call_sync

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_FEEDBACK = REPO_ROOT / "memory" / "loop_feedback.jsonl"
DEFAULT_IDEA_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
DEFAULT_DESIGN_CONSTRAINTS = REPO_ROOT / "memory" / "design_constraints.jsonl"

# DARK gate for the design-constraint conditioning seam (below). Unset —
# the default — means OFF; the gate state is logged on EVERY run either way.
CONSTRAINT_GATE_ENV = "NARA_CONSTRAINT_CONDITION"
CONSTRAINT_BULLET_CAP = 3
BULLET_CAP_WITH_CONSTRAINTS = 11   # 5 model + 3 idea-ledger + 3 constraints

CALLS_LOG_PATH = os.environ.get("LOOP_V0_CALLS_LOG", "logs/calls.jsonl")


META_REVIEW_SYSTEM_PROMPT = (
    "You are the META-REVIEW worker in the a_bgt_rsi research apparatus.\n"
    "\n"
    "You are given a digest of the most recent loop iterations — each with\n"
    "its hypothesis, novelty class, automated critique verdict, optional\n"
    "experiment outcome, and (when present) a HUMAN gate verdict of\n"
    "'valid' / 'invalid' / 'needs_revision'. The human verdict outweighs\n"
    "the automated signals.\n"
    "\n"
    "Distill 3 to 5 short conditioning bullets that should steer the next\n"
    "iteration:\n"
    "  - what kept WINNING (patterns the loop should keep doing),\n"
    "  - what kept LOSING — especially anything a human marked 'invalid',\n"
    "  - what SURPRISED (a result that ran against expectation).\n"
    "\n"
    "Each bullet is one imperative or observational sentence. Be concrete;\n"
    "name the pattern, not a platitude.\n"
    "\n"
    "Output STRICT JSON, nothing else — no prose, no markdown fences, no\n"
    "channel markers. Schema:\n"
    "{\n"
    '  "conditioning_bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"]\n'
    "}\n"
    "\n"
    "`conditioning_bullets` has 3 to 5 items."
)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Find the first balanced JSON object in `text` and parse it.

    Gemma occasionally wraps JSON in prose or in `<channel|>` markup.
    We scan for the first `{` and find its matching `}` by counting
    braces, then try to parse that slice."""
    if not isinstance(text, str):
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _read_jsonl(path: str | os.PathLike) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of dicts. Missing file -> []. Skips
    blank and malformed lines (never crashes on a partial write)."""
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _sub(row: dict[str, Any], key: str) -> dict[str, Any]:
    """Return row[key] when it's a dict, else an empty dict. Loop-memory
    rows leave hypothesis/novelty/critique/experiment_outcome as None
    until those stages have run."""
    v = row.get(key)
    return v if isinstance(v, dict) else {}


def _digest_row(row: dict[str, Any], verdict: dict[str, Any]) -> str:
    """One compact line per iteration for the LLM prompt."""
    iid = row.get("iteration_id", "?")
    hyp = _sub(row, "hypothesis").get("text") or row.get("seed", {}).get("topic") or "(no hypothesis)"
    nov = _sub(row, "novelty").get("class") or "?"
    crit = _sub(row, "critique").get("verdict") or "?"
    exp = _sub(row, "experiment_outcome").get("summary")
    human = verdict.get("verdict")
    parts = [f"[{iid}] hypothesis: {str(hyp)[:300]}",
             f"novelty={nov}", f"critique={crit}"]
    if exp:
        parts.append(f"experiment={str(exp)[:200]}")
    if human:
        note = verdict.get("note")
        hv = f"HUMAN_VERDICT={human}"
        if note:
            hv += f" ({str(note)[:120]})"
        parts.append(hv)
    return " | ".join(parts)


def meta_review(
    *,
    n: int = 8,
    loop_memory_path: str | os.PathLike = DEFAULT_LOOP_MEMORY,
    feedback_path: str | os.PathLike = DEFAULT_FEEDBACK,
    parent_request_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Synthesize 3–5 conditioning bullets from the last `n` loop iterations.

    Returns worker-shaped:
    ```
    {
        "status": "passed" | "error",
        "result": {
            "conditioning_bullets": [str, ...],   # 3..5 (+ idea-ledger /
                                                  # design-constraint lines)
            "rows_considered": int,
            "constraint_conditioning": "on" | "off",   # DARK gate state
        } | None,
        "errors": [str, ...],
        "wrapper_request_id": str | None,
        "parent_request_id": str | None,
    }
    ```
    """
    rows = _read_jsonl(loop_memory_path)
    if not rows:
        return {
            "status": "error",
            "result": None,
            "errors": [f"no iteration_records found at {loop_memory_path}"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }
    rows = rows[-max(int(n), 1):]

    # Join human gate verdicts by iteration_id (feedback may not exist yet).
    feedback = {
        f["iteration_id"]: f
        for f in _read_jsonl(feedback_path)
        if isinstance(f.get("iteration_id"), str)
    }

    digest = "\n".join(
        _digest_row(r, feedback.get(r.get("iteration_id", ""), {})) for r in rows
    )
    messages = [
        {"role": "system", "content": META_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Here are the last {len(rows)} loop iterations:\n\n{digest}\n\n"
            "Distill 3–5 conditioning bullets."
        )},
    ]

    try:
        record = call_sync(
            messages,
            temperature=0.2,
            top_p=0.9,
            max_tokens=512,
            caller_tag="meta_review",
            parent_request_id=parent_request_id,
            log_path=CALLS_LOG_PATH,
            model=model,
        )
    except Exception as exc:
        return {
            "status": "error",
            "result": None,
            "errors": [f"wrapper.call_sync failed: {type(exc).__name__}: {exc}"],
            "wrapper_request_id": None,
            "parent_request_id": parent_request_id,
        }

    wrapper_rid = record.get("request_id")
    payload = _extract_json_object(record.get("completion") or "")
    bullets: list[str] = []
    if isinstance(payload, dict):
        raw = payload.get("conditioning_bullets")
        if isinstance(raw, list):
            bullets = [b.strip() for b in raw if isinstance(b, str) and b.strip()]
    bullets = bullets[:5]

    if len(bullets) < 3:
        return {
            "status": "error",
            "result": None,
            "errors": [
                "meta-review produced fewer than 3 conditioning bullets; "
                "model emitted unusable output"
            ],
            "wrapper_request_id": wrapper_rid,
            "parent_request_id": parent_request_id,
        }

    # LOOP_V1 P3 (D-060): append the idea-ledger projection's deterministic
    # conditioning lines (graveyard adjacency + agenda context) so generation
    # sees the negative memory. Additive, capped, and fail-open — a missing/
    # empty ledger (pre-consolidation) changes nothing.
    try:
        from workers.idea_ledger import load_state
        from workers.idea_projection import conditioning_lines
        state = load_state(DEFAULT_IDEA_LEDGER)
        if state:
            topic = str((rows[-1].get("seed") or {}).get("topic") or "")
            extra = [ln for ln in conditioning_lines(state, topic)
                     if isinstance(ln, str) and ln.strip()][:3]
            bullets = (bullets + extra)[:8]
    except Exception as exc:  # logged fail-open — never silent (rule 7)
        print(f"[meta_review] idea-ledger conditioning skipped: {exc}",
              file=sys.stderr)

    # DESIGN-CONSTRAINT CONDITIONING — DARK by default (NARA_CONSTRAINT_CONDITION).
    # The falsifier tiers (frontier screen + local redteam) name the controls a
    # claim is missing; workers.constraint_distill turns that text into
    # provenance-tagged constraints deterministically (no LLM, D-061: the
    # frontier annotates, it never generates). Feeding those back into the
    # generator's conditioning is the ONE step that could shape generation, so
    # it does not arm itself — the owner sets the env var after a risk/reward
    # ask. The gate state is logged on every run, armed or not.
    raw_gate = os.environ.get(CONSTRAINT_GATE_ENV, "")
    armed = raw_gate.strip().lower() not in ("", "0", "false", "no", "off")
    if not armed:
        print(f"[meta_review] design-constraint conditioning: OFF "
              f"({CONSTRAINT_GATE_ENV}={raw_gate!r})", file=sys.stderr)
    else:
        try:
            from workers.constraint_distill import conditioning_bullets
            topic = str((rows[-1].get("seed") or {}).get("topic") or "")
            extra = conditioning_bullets(topic, DEFAULT_DESIGN_CONSTRAINTS,
                                         cap=CONSTRAINT_BULLET_CAP)
            bullets = (bullets + extra)[:BULLET_CAP_WITH_CONSTRAINTS]
            print(f"[meta_review] design-constraint conditioning: ON "
                  f"({CONSTRAINT_GATE_ENV}={raw_gate!r}) — {len(extra)} "
                  f"bullet(s) matched topic {topic[:60]!r}", file=sys.stderr)
        except Exception as exc:  # logged fail-open — never silent (rule 7)
            print(f"[meta_review] design-constraint conditioning skipped: {exc}",
                  file=sys.stderr)

    return {
        "status": "passed",
        "result": {
            "conditioning_bullets": bullets,
            "rows_considered": len(rows),
            "constraint_conditioning": "on" if armed else "off",
        },
        "errors": [],
        "wrapper_request_id": wrapper_rid,
        "parent_request_id": parent_request_id,
    }


if __name__ == "__main__":
    # Smoke: `env -u MOCK_LLM ./.venv-chroma/bin/python -m workers.meta_review`
    print(json.dumps(meta_review(n=8, parent_request_id="smoke"), indent=2))
