"""Model I/O viewer + dispatch-trace read seams (owner request 2026-08-18).

The dashboard showed *that* the models were alive (KV usage, MTP, health
stats) but nothing of what actually passes THROUGH them. These endpoints are
the read seams for the "Model I/O" page: what Nara and the workers are
sending to gemma/qwen and what comes back, plus the orchestrator dispatch
chain and the spawn ledger's agent contracts.

- ``GET /api/model_io`` — newest-first call summaries out of the MAIN call
  log ``logs/calls.jsonl`` (prompt/completion previews, tokens, latency,
  empty-completion flag), filterable by model / caller_tag / run_id /
  since_ts. NOTE: experiments and bench redirect their calls to their own
  ``runs/*.calls.jsonl`` via ``LOOP_V0_CALLS_LOG`` — this slice reads the
  main log only (the frontend states that as a footnote; a log picker is
  future work).
- ``GET /api/model_io/{request_id}`` — the FULL row (all prompt_messages +
  completion) for one call, 404 when the id is not inside the bounded scan
  window (see below).
- ``GET /api/dispatch_trace`` — recent orchestrator.jsonl
  dispatch → worker_invocation → receipt triples joined by task_id, plus the
  last entries of the spawn ledger ``run_state/spawn.jsonl``.
- ``GET /api/runtime_activity`` — the RUNTIME plane only (owner feedback
  2026-08-18: the old top cards conflated dev-side Claude-Code build agents
  with the apparatus's own runtime agents): Nara's latest chain tasks out of
  orchestrator.jsonl + recent SUBAGENT WORK grouped from calls.jsonl by
  caller_tag family. The dev spawn ledger deliberately stays on
  ``/api/dispatch_trace`` — the plane separation is on the wire, not just
  in the view.

BOUNDED TAIL READS, ALWAYS: calls.jsonl is tens of MB and grows hourly, so
every request seeks from EOF and walks BACKWARD in blocks, stopping at the
first of (limit filled | file start | ``max_scan_bytes`` scanned). The whole
file is never parsed per request. The bound is honest on the wire:
``window_truncated`` is True when the byte bound stopped the scan while the
limit was still unfilled — i.e. older matching rows may exist unexamined —
and the detail 404 names the bound. Malformed lines are skipped, never a 500.

Read-only: nothing here writes to logs/ or run_state/.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

# _REPO == the checkout this file lives in (ui/backend/model_io.py).
_REPO = Path(__file__).resolve().parents[2]
DEFAULT_LOGS_DIR = _REPO / "logs"

# The spawn ledger lives under run_state/ in the PRIMARY checkout (the run
# drivers and the primary session write it there, not in a UI worktree) —
# the same idiom as activity.py's DEFAULT_ACTIVE_RUNS_DIR. Env-overridable
# below (UI_SPAWN_LEDGER) because app.py's register call passes no path for
# it; tests pin a tmp path via the kwarg.
_PRIMARY = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_SPAWN_LEDGER = _PRIMARY / "run_state" / "spawn.jsonl"

CALLS_FILE = "calls.jsonl"
ORCHESTRATOR_FILE = "orchestrator.jsonl"

# The backward-scan byte bound: how far back from EOF a single request will
# ever look. 16 MiB ≈ several days of main-log traffic at current rates;
# rows older than the window are out of scope for a LIVE I/O viewer (the
# /chain inspector + the raw log remain the deep-history tools). The list
# endpoint normally stops long before this (as soon as `limit` rows match).
DEFAULT_MAX_SCAN_BYTES = 16 * 1024 * 1024
_BLOCK_BYTES = 256 * 1024

# Previews are for the table row; the detail endpoint carries the full text.
PREVIEW_CHARS = 200

# orchestrator.jsonl rows are tiny (~350 B); 512 KiB of tail is >1000 rows,
# far more than the 100-task cap below ever needs. spawn.jsonl rows are
# bigger (a full contract block) but the endpoint surfaces only the last 10.
TRACE_TAIL_BYTES = 512 * 1024
SPAWN_TAIL_BYTES = 256 * 1024
SPAWN_ENTRIES = 10
SPAWN_STATEMENT_CHARS = 140

# /api/runtime_activity bounds: the strip wants LIVE/recent work, so its
# calls.jsonl grouping scan is bounded tighter than the list endpoint's
# (min() with the register-time max_scan_bytes so tests can shrink it).
CHAIN_ENTRIES = 8
SUBAGENT_GROUP_LIMIT = 8
SUBAGENT_SCAN_BYTES = 4 * 1024 * 1024


def _env_path(var: str, default: Path) -> Path:
    """app.py's env-override idiom (UI_* var wins, else the baked default)."""
    value = os.environ.get(var)
    return Path(value) if value else default


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(ts) -> datetime:
    """ISO timestamp -> aware datetime for ORDERING/COMPARISON (never display).

    Unparseable/absent sorts to the bottom (datetime.min, UTC) so a malformed
    row can never win a max or satisfy a since_ts filter. (activity.py idiom.)
    """
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _passthrough_str(value) -> str | None:
    """Record's own string value or None — NEVER derived (activity.py idiom).

    In particular `backend` stays None on pre-2026-06-10 rows; it is never
    guessed from the model name."""
    return value if isinstance(value, str) and value else None


def _scan_backward(path: Path, max_scan_bytes: int,
                   block_bytes: int = _BLOCK_BYTES):
    """Yield parsed JSON objects NEWEST-FIRST from the end of a JSONL file.

    Seeks to EOF and walks backward in `block_bytes` chunks, splitting on
    newlines; a line straddling a block boundary is carried into the earlier
    block, so every complete line parses exactly once. Stops after
    `max_scan_bytes` — the generator's `.truncated` attribute is not a thing
    in Python, so completeness is reported via the returned state dict:

        gen, state = _scan_backward(...)
        ... consume gen ...
        state["hit_bound"]   True iff the byte bound stopped the scan with
                             file content still unread (older rows exist
                             that were never examined).

    Malformed / non-object lines are skipped (never a crash); a trailing
    partial line (writer mid-append) simply fails to parse and is skipped.
    """
    state = {"hit_bound": False, "scanned_bytes": 0}

    def gen():
        if not path.exists():
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        pos = size
        carry = b""
        scanned = 0
        try:
            with open(path, "rb") as fh:
                while pos > 0:
                    if scanned >= max_scan_bytes:
                        state["hit_bound"] = True
                        break
                    read_size = min(block_bytes, pos, max_scan_bytes - scanned)
                    pos -= read_size
                    fh.seek(pos)
                    data = fh.read(read_size) + carry
                    scanned += read_size
                    state["scanned_bytes"] = scanned
                    lines = data.split(b"\n")
                    if pos > 0:
                        # First fragment belongs to the earlier block.
                        carry = lines[0]
                        lines = lines[1:]
                    else:
                        carry = b""
                    for raw in reversed(lines):
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            rec = json.loads(raw.decode("utf-8",
                                                        errors="replace"))
                        except json.JSONDecodeError:
                            continue
                        if isinstance(rec, dict):
                            yield rec
                else:
                    return
                # Loop exited via the bound-break; if a carry remains it is a
                # line whose start lies beyond the bound — unexamined content.
                if carry.strip():
                    state["hit_bound"] = True
        except OSError:
            return

    return gen(), state


def _tail_records(path: Path, window_bytes: int) -> list[dict]:
    """Parse JSON objects from the last `window_bytes` of a JSONL file, in
    FILE ORDER (oldest-first within the window). Bounded-tail discipline:
    drops the (likely partial) first line of a windowed read and skips
    malformed lines. (activity.py idiom.)"""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        window = min(size, window_bytes)
        with open(path, "rb") as fh:
            fh.seek(size - window)
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if window < size and lines:
        lines = lines[1:]
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _subagent_family(tag: str) -> tuple[str, str] | None:
    """Map a caller_tag to its SUBAGENT-WORK family ``(family_id, label)``,
    or None when the tag is NOT subagent work (Nara chain / station calls —
    nara.run_iteration, hypothesize, idea_judge, … — live on the other
    plane and are excluded).

    Families are EVIDENCE, never invented — derived from the caller_tag
    vocabulary actually observed in logs/calls.jsonl (checked 2026-08-18):

    - ``subagent.finding_skeptic_{1,2,3}`` + ``finding_promotion.synthesize``
      → one promotion-panel run; a run's rows share
      ``run_id "promote_findings_<hash>"`` (parent_request_id is null).
    - ``finding_session`` / ``finding_session_{attacker,defender,tutor}``
      → one two-voice session; rows share
      ``run_id "finding_session_fs-<hash>"``.
    - ``subagent.debate_{challenger,defender}`` → bounded-debate turns:
      workers/debate.py names its run_subagent calls ``debate_<role>`` and
      run_subagent tags every call ``subagent.<name>``
      (orchestrator/subagent.py), passing the iteration id as
      parent_request_id.
    - any other ``subagent.<name>`` → a generic run_subagent child,
      labelled honestly by its own name.
    """
    if tag.startswith("subagent.finding_skeptic_") \
            or tag.startswith("finding_promotion."):
        return "promotion_panel", "promotion panel"
    if tag.startswith("subagent.debate_"):
        return "debate", "bounded debate"
    if tag.startswith("subagent."):
        rest = tag[len("subagent."):]
        return f"subagent:{rest}", rest
    if tag == "finding_session" or tag.startswith("finding_session_"):
        return "two_voice_session", "two-voice session"
    return None


def _join_orch_tasks(orch_path: Path, cap: int) -> list[dict]:
    """orchestrator.jsonl triples joined by task_id, newest-first, capped.
    The latest row (>= so equal-timestamp triples resolve to the LAST
    file-order row — the receipt) owns status/stage/ts."""
    groups: dict[str, dict] = {}
    for rec in _tail_records(orch_path, TRACE_TAIL_BYTES):
        task_id = rec.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        ts = rec.get("timestamp")
        instant = _parse_ts(ts)
        grp = groups.setdefault(task_id, {
            "task_id": task_id, "task_type": None, "status": None,
            "stage": None, "duration_ms": None, "ts": None,
            "run_id": None, "_instant": instant,
        })
        if grp["task_type"] is None:
            grp["task_type"] = _passthrough_str(rec.get("task_type"))
        if grp["run_id"] is None:
            grp["run_id"] = _passthrough_str(rec.get("run_id"))
        if isinstance(rec.get("duration_ms"), (int, float)):
            grp["duration_ms"] = rec["duration_ms"]
        if instant >= grp["_instant"]:
            grp["_instant"] = instant
            grp["status"] = _passthrough_str(rec.get("status"))
            grp["stage"] = _passthrough_str(rec.get("stage"))
            grp["ts"] = _passthrough_str(ts)
    tasks = sorted(groups.values(), key=lambda g: g["_instant"],
                   reverse=True)[:cap]
    for grp in tasks:
        del grp["_instant"]
    return tasks


def _prompt_preview(rec: dict) -> str | None:
    """First PREVIEW_CHARS of the LAST USER message — the actual ask, not the
    (usually giant, usually repetitive) system prompt. Falls back to the last
    message of any role when no user message exists; None when the row has no
    legible prompt_messages at all."""
    messages = rec.get("prompt_messages")
    if not isinstance(messages, list) or not messages:
        return None
    chosen = None
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user" \
                and isinstance(msg.get("content"), str):
            chosen = msg["content"]
            break
    if chosen is None:
        last = messages[-1]
        if isinstance(last, dict) and isinstance(last.get("content"), str):
            chosen = last["content"]
    return chosen[:PREVIEW_CHARS] if chosen is not None else None


def _summary(rec: dict) -> dict:
    """One table row: previews + the scalar metadata, all pure passthrough
    (a missing field is null, never derived). `empty` flags a completion that
    is absent or whitespace-only — the "model returned nothing" signal the
    health panels can't show."""
    usage = rec.get("usage") if isinstance(rec.get("usage"), dict) else {}
    completion = rec.get("completion")
    completion_str = completion if isinstance(completion, str) else ""
    return {
        "ts": _passthrough_str(rec.get("timestamp")),
        "request_id": _passthrough_str(rec.get("request_id")),
        "parent_request_id": _passthrough_str(rec.get("parent_request_id")),
        "model": _passthrough_str(rec.get("model")),
        "backend": _passthrough_str(rec.get("backend")),
        "caller_tag": _passthrough_str(rec.get("caller_tag")),
        "run_id": _passthrough_str(rec.get("run_id")),
        "latency_ms": rec.get("latency_ms")
        if isinstance(rec.get("latency_ms"), (int, float)) else None,
        "input_tokens": usage.get("input_tokens")
        if isinstance(usage.get("input_tokens"), int) else None,
        "output_tokens": usage.get("output_tokens")
        if isinstance(usage.get("output_tokens"), int) else None,
        "prompt_preview": _prompt_preview(rec),
        "completion_preview": completion_str[:PREVIEW_CHARS],
        "empty": completion_str.strip() == "",
    }


def _matches(rec: dict, *, model: str | None, caller_tag: str | None,
             run_id: str | None, since: datetime | None) -> bool:
    """Filter one raw record. model / caller_tag are CASE-INSENSITIVE
    SUBSTRING matches (view filters — "gemma" should match the full served
    name; this is a search box, not attribution, which stays exact-match in
    roles.ts). run_id is exact. since_ts keeps rows whose timestamp parses to
    an instant >= since — an unparseable timestamp cannot claim to be after
    it, so it is excluded when the filter is active."""
    if model is not None:
        value = rec.get("model")
        if not isinstance(value, str) or model.lower() not in value.lower():
            return False
    if caller_tag is not None:
        value = rec.get("caller_tag")
        if not isinstance(value, str) \
                or caller_tag.lower() not in value.lower():
            return False
    if run_id is not None:
        if rec.get("run_id") != run_id:
            return False
    if since is not None:
        if _parse_ts(rec.get("timestamp")) < since:
            return False
    return True


def register(app, *, logs_dir: Path = DEFAULT_LOGS_DIR,
             spawn_path: Path | None = None,
             max_scan_bytes: int = DEFAULT_MAX_SCAN_BYTES) -> APIRouter:
    """Attach the Model I/O router (register-fn idiom, as activity/ladder).

    ``logs_dir`` carries both calls.jsonl and orchestrator.jsonl (the same
    dir app.py already passes to register_activity). ``spawn_path`` resolves
    None → ``UI_SPAWN_LEDGER`` env override → the primary checkout's
    ``run_state/spawn.jsonl``; tests pin tmp paths via the kwargs.
    ``max_scan_bytes`` is the backward-scan bound — tests shrink it to prove
    the bound is real."""
    logs_dir = Path(logs_dir)
    if spawn_path is None:
        spawn_path = _env_path("UI_SPAWN_LEDGER", DEFAULT_SPAWN_LEDGER)
    spawn_path = Path(spawn_path)
    calls_path = logs_dir / CALLS_FILE
    orch_path = logs_dir / ORCHESTRATOR_FILE
    router = APIRouter(prefix="/api", tags=["model_io"])

    @router.get("/model_io")
    def model_io(limit: int = 50, model: str | None = None,
                 caller_tag: str | None = None, run_id: str | None = None,
                 since_ts: str | None = None):
        """Newest-first call summaries from the tail of the MAIN call log."""
        capped = min(max(limit, 1), 200)
        since = None
        if since_ts:
            since = _parse_ts(since_ts)
            if since == datetime.min.replace(tzinfo=timezone.utc):
                # An unparseable filter must fail loudly, not silently match
                # nothing/everything (inviolate rule 4).
                raise HTTPException(status_code=400,
                                    detail=f"since_ts {since_ts!r} is not an "
                                           "ISO 8601 timestamp")
        records, state = _scan_backward(calls_path, max_scan_bytes)
        calls: list[dict] = []
        for rec in records:
            if not _matches(rec, model=model or None,
                            caller_tag=caller_tag or None,
                            run_id=run_id or None, since=since):
                continue
            calls.append(_summary(rec))
            if len(calls) >= capped:
                break
        return {
            "calls": calls,
            "source": "logs/calls.jsonl",
            # True iff the byte bound stopped the scan while the limit was
            # still unfilled — older matching rows may exist unexamined.
            "window_truncated": state["hit_bound"] and len(calls) < capped,
            "scanned_bytes": state["scanned_bytes"],
            "max_scan_bytes": max_scan_bytes,
            "generated_at": _utcnow_iso(),
        }

    @router.get("/model_io/{request_id}")
    def model_io_detail(request_id: str):
        """The FULL row (all prompt_messages + the whole completion) for one
        request_id, RAW passthrough. Scan is bounded like the list: a row
        older than `max_scan_bytes` from EOF is out of the window → 404."""
        records, _state = _scan_backward(calls_path, max_scan_bytes)
        for rec in records:
            if rec.get("request_id") == request_id:
                return {"found": True, "call": rec}
        raise HTTPException(
            status_code=404,
            detail=f"no call record for request_id {request_id!r} in the "
                   f"last {max_scan_bytes} bytes of {CALLS_FILE} (older rows "
                   "are outside the bounded scan window)")

    @router.get("/dispatch_trace")
    def dispatch_trace(limit: int = 30):
        """Recent orchestrator triples (joined by task_id, newest-first) +
        the spawn ledger's last entries. Degrades per-source: an absent file
        is announced, never a 500 and never fabricated rows."""
        capped = min(max(limit, 1), 100)
        tasks = _join_orch_tasks(orch_path, capped)

        # Spawn ledger: last SPAWN_ENTRIES raw entries, newest-first. The two
        # timestamp spellings on disk ("ts" and "timestamp") both pass
        # through; a closing (completed/escalated) line carries no contract,
        # so its task_statement is backfilled from the SPAWNED line of the
        # same spawn_id when that line is inside the scanned tail — a join,
        # not a guess (null when the opener is out of the window).
        spawn_rows = _tail_records(spawn_path, SPAWN_TAIL_BYTES)
        statements: dict[str, str] = {}
        for rec in spawn_rows:
            spawn_id = rec.get("spawn_id")
            contract = rec.get("contract")
            if isinstance(spawn_id, str) and isinstance(contract, dict) \
                    and isinstance(contract.get("task_statement"), str):
                statements[spawn_id] = contract["task_statement"]
        spawns = []
        for rec in reversed(spawn_rows[-SPAWN_ENTRIES:]):
            spawn_id = rec.get("spawn_id")
            statement = statements.get(spawn_id) \
                if isinstance(spawn_id, str) else None
            spawns.append({
                "spawn_id": _passthrough_str(spawn_id),
                "status": _passthrough_str(rec.get("status")),
                "ts": _passthrough_str(rec.get("ts"))
                or _passthrough_str(rec.get("timestamp")),
                "task_statement": statement[:SPAWN_STATEMENT_CHARS]
                if statement else None,
            })

        return {
            "orchestrator_available": orch_path.exists(),
            "spawn_available": spawn_path.exists(),
            "tasks": tasks,
            "spawns": spawns,
            "generated_at": _utcnow_iso(),
        }

    @router.get("/runtime_activity")
    def runtime_activity():
        """The RUNTIME plane for the /model-io strip: Nara's latest chain
        tasks + recent subagent work grouped by caller_tag family. The
        dev-side spawn ledger stays on /api/dispatch_trace on purpose.

        Grouping keys are EVIDENCE, never invented: rows group by
        (family, parent_request_id-else-run_id). The observed subagent rows
        carry a null parent_request_id and a per-run run_id
        (promote_findings_<hash> / finding_session_fs-<hash>), so run_id is
        usually the instance key; parent_request_id wins when present
        (debate turns carry the iteration id there). orchestrator.jsonl
        rows carry NO run_id field at all (checked 2026-08-18: zero
        occurrences), so the chain is the task_id join — "latest task per
        run_id" would fabricate a key the rows do not have.
        """
        scan_bound = min(max_scan_bytes, SUBAGENT_SCAN_BYTES)
        records, state = _scan_backward(calls_path, scan_bound)
        groups: dict[tuple, dict] = {}
        for rec in records:
            tag = rec.get("caller_tag")
            if not isinstance(tag, str) or not tag:
                continue
            fam = _subagent_family(tag)
            if fam is None:
                continue
            family_id, label = fam
            key = _passthrough_str(rec.get("parent_request_id"))
            key_source = "parent_request_id" if key else None
            if key is None:
                key = _passthrough_str(rec.get("run_id"))
                key_source = "run_id" if key else None
            instant = _parse_ts(rec.get("timestamp"))
            ts = _passthrough_str(rec.get("timestamp"))
            grp = groups.get((family_id, key))
            if grp is None:
                grp = groups[(family_id, key)] = {
                    "family": family_id, "label": label,
                    "group_key": key, "key_source": key_source,
                    "calls": 0, "models": set(), "caller_tags": set(),
                    "first_ts": None, "last_ts": None,
                    "_first": instant, "_last": instant,
                }
            grp["calls"] += 1
            model = _passthrough_str(rec.get("model"))
            if model:
                grp["models"].add(model)
            grp["caller_tags"].add(tag)
            if grp["last_ts"] is None or instant >= grp["_last"]:
                grp["_last"] = instant
                grp["last_ts"] = ts
            if grp["first_ts"] is None or instant <= grp["_first"]:
                grp["_first"] = instant
                grp["first_ts"] = ts

        newest = sorted(groups.values(), key=lambda g: g["_last"],
                        reverse=True)[:SUBAGENT_GROUP_LIMIT]
        subagent_groups = []
        for grp in newest:
            tags = sorted(grp["caller_tags"])
            label = grp["label"]
            if grp["family"] == "promotion_panel":
                # Skeptic count DERIVED from the distinct tags actually in
                # the group, never hardcoded.
                n = sum(1 for t in tags
                        if t.startswith("subagent.finding_skeptic_"))
                if n:
                    label = (f"promotion panel ({n} skeptic"
                             f"{'s' if n != 1 else ''})")
            subagent_groups.append({
                "family": grp["family"], "label": label,
                "group_key": grp["group_key"],
                "key_source": grp["key_source"],
                "calls": grp["calls"],
                "models": sorted(grp["models"]),
                "caller_tags": tags,
                "first_ts": grp["first_ts"], "last_ts": grp["last_ts"],
            })

        return {
            "orchestrator_available": orch_path.exists(),
            "calls_available": calls_path.exists(),
            "chain": _join_orch_tasks(orch_path, CHAIN_ENTRIES),
            "subagent_groups": subagent_groups,
            # True iff the byte bound stopped the grouping scan — older
            # subagent work may exist unexamined.
            "window_truncated": state["hit_bound"],
            "scanned_bytes": state["scanned_bytes"],
            "generated_at": _utcnow_iso(),
        }

    app.include_router(router)
    return router
