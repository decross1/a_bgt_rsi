#!/usr/bin/env python3
"""inspect_run.py -- reconstruct the causal chain of an orchestrated run.

Day 5 / Track C draft (plan.yaml task ``track_c_day5_draft_inspect_run``),
consumed by ``day6_block2_inspect_run_cli``. This is the "reproducibility"
promise made operational: given a task, show exactly what happened.

WHAT IT DOES
    Given a ``--task-id`` (or ``--request-id``), reads the orchestrator /
    wrapper JSONL logs and reconstructs the full causal chain by following
    ``parent_request_id`` -> ``request_id`` links::

        orchestrator dispatch
          -> worker invocation
            -> wrapper request
              -> wrapper response (vLLM call)

    Each level is printed indented, with its timestamp and duration.

USAGE
    python3 tools/inspect_run.py --task-id <id>
    python3 tools/inspect_run.py --task-id <id> --log logs/orchestrator.jsonl \\
                                                --log logs/day6.jsonl
    python3 tools/inspect_run.py --request-id <uuid>      # root by request_id

    With no ``--log``, reads ``logs/orchestrator.jsonl`` and, unless
    ``--no-discover`` is given, also any sibling ``*.jsonl`` in that
    directory -- so the wrapper/vLLM level (logged to ``logs/dayN.jsonl``)
    is picked up without naming it explicitly.

LOG SCHEMA (field-name tolerant)
    ``logs/orchestrator.jsonl`` does not exist until Day 6 and its exact
    field names are not yet frozen, so every accessor below tries a list
    of candidate keys. A record is expected to carry, under at least one
    name in each group:

        unique id   : request_id | id | event_id
        parent link : parent_request_id | parent_id | parent   (null = root)
        task id     : task_id            (orchestrator-side records only)
        timestamp   : timestamp | ts | time
        duration    : duration_ms | latency_ms | elapsed_ms
        level/stage : level | stage | event | event_type | record_type | kind

    When no level key is present the level is inferred from record shape
    (a ``calls.jsonl`` wrapper record has ``prompt_messages`` +
    ``completion``; a worker_input has ``task_type`` + ``payload``; etc).

This tool only ever READS logs. It never calls an LLM and never writes.
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_LOG = "logs/orchestrator.jsonl"

# Candidate key names, tried in order, for each logical field.
ID_KEYS = ("request_id", "id", "event_id")
PARENT_KEYS = ("parent_request_id", "parent_id", "parent")
TASK_KEYS = ("task_id",)
TIME_KEYS = ("timestamp", "ts", "time")
DURATION_KEYS = ("duration_ms", "latency_ms", "elapsed_ms")
LEVEL_KEYS = ("level", "stage", "event", "event_type", "record_type", "kind")


def _first(record, keys):
    """Return the first non-None value among ``keys`` in ``record``."""
    for k in keys:
        if record.get(k) is not None:
            return record[k]
    return None


def rec_id(r):
    return _first(r, ID_KEYS)


def rec_parent(r):
    return _first(r, PARENT_KEYS)


def rec_task(r):
    return _first(r, TASK_KEYS)


def rec_time(r):
    return _first(r, TIME_KEYS)


def rec_duration(r):
    return _first(r, DURATION_KEYS)


def rec_level(r):
    """The pipeline stage of a record: explicit level key, else inferred."""
    explicit = _first(r, LEVEL_KEYS)
    if explicit is not None:
        return str(explicit)
    if "prompt_messages" in r and "completion" in r:
        return "wrapper_call"          # logs/dayN.jsonl, calls schema
    if "task_type" in r and "payload" in r:
        return "worker_input"          # worker_contract input half
    if "status" in r and "jsonl_log_path" in r:
        return "worker_output"         # worker_contract output half
    return "record"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load_records(paths):
    """Read JSONL ``paths`` into a list of dicts. Returns (records, warnings).

    Malformed lines, non-object records and missing files are skipped with
    a warning -- never fatal -- so a single bad line cannot hide a chain.
    Each record gets a ``__source__`` key recording ``path:lineno``.
    """
    records, warnings, seen = [], [], set()
    for p in paths:
        path = Path(p)
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            warnings.append(f"log file not found, skipped: {p}")
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                warnings.append(f"{p}:{lineno}: skipped malformed JSON ({e})")
                continue
            if not isinstance(obj, dict):
                warnings.append(f"{p}:{lineno}: skipped non-object record")
                continue
            obj["__source__"] = f"{p}:{lineno}"
            records.append(obj)
    return records, warnings


def discover_siblings(paths):
    """Return sibling ``*.jsonl`` files in the directories of ``paths``.

    Lets a plain ``--task-id`` query pick up the wrapper log
    (logs/dayN.jsonl) alongside logs/orchestrator.jsonl without naming it.
    """
    extra = []
    for d in {Path(p).resolve().parent for p in paths}:
        if d.is_dir():
            extra.extend(sorted(str(f) for f in d.glob("*.jsonl")))
    return extra


# --------------------------------------------------------------------------
# Indexing & chain reconstruction
# --------------------------------------------------------------------------
def build_index(records):
    """Index records. Returns (by_id, children, kept, warnings).

    ``by_id``    maps request_id -> record (first wins on collision).
    ``children`` maps parent_request_id -> [child records].
    ``kept``     is records minus dropped duplicate-id records.
    """
    by_id, kept, warnings = {}, [], []
    for r in records:
        rid = rec_id(r)
        if rid is not None and rid in by_id:
            warnings.append(
                f"duplicate request_id {rid} "
                f"({r.get('__source__')} vs {by_id[rid].get('__source__')}); "
                "keeping the first"
            )
            continue
        if rid is None:
            warnings.append(
                f"{r.get('__source__', '?')}: record has no request_id; "
                "it can be a chain leaf but not a parent"
            )
        else:
            by_id[rid] = r
        kept.append(r)
    children = {}
    for r in kept:
        pid = rec_parent(r)
        if pid is not None:
            children.setdefault(pid, []).append(r)
            if pid not in by_id:
                # A dangling parent reference: this record can never
                # attach to any chain. Report it -- a wrapper-call
                # record orphaned this way would otherwise just be
                # absent from the printed chain with no warning.
                warnings.append(
                    f"chain break: {rec_level(r)} record {rec_id(r)} "
                    f"references missing parent {pid}"
                )
    return by_id, children, kept, warnings


def select_roots(kept, by_id, task_id, request_id, warnings):
    """Pick the root record(s) of the requested chain.

    Returns (roots, error). ``error`` is a string when nothing matched.
    A well-formed task has exactly one root; more than one means the
    chain is fragmented and that is reported, not hidden.
    """
    if request_id is not None:
        root = by_id.get(request_id)
        if root is None:
            return [], f"no record with request_id={request_id!r}"
        return [root], None

    matches = [r for r in kept if rec_task(r) == task_id]
    if not matches:
        return [], f"no record with task_id={task_id!r}"

    # A dangling parent (pid not in by_id) is reported by build_index;
    # here we only need to find where each task chain starts.
    match_ids = {rec_id(r) for r in matches if rec_id(r) is not None}
    roots = []
    for r in matches:
        pid = rec_parent(r)
        if pid is None or pid not in match_ids:
            roots.append(r)
    if not roots:
        # Every match has a parent inside the set -> a cycle. Don't loop.
        roots = [min(matches, key=lambda r: rec_time(r) or "")]
        warnings.append(
            f"task_id={task_id}: no parentless record (possible cycle); "
            "using the earliest record as root"
        )
    roots.sort(key=lambda r: rec_time(r) or "")
    if len(roots) > 1:
        warnings.append(
            f"task_id={task_id}: chain is fragmented -- {len(roots)} root "
            "records (a complete chain has exactly 1)"
        )
    return roots, None


def build_tree(record, children, depth, visited, warnings):
    """Recursively assemble the chain subtree rooted at ``record``.

    ``visited`` carries the request_ids on the path from the root so a
    parent<->child cycle is detected and pruned instead of looping.
    """
    rid = rec_id(record)
    node = {"record": record, "depth": depth, "children": [], "cycle": False}
    if rid is None:
        return node
    if rid in visited:
        warnings.append(f"cycle detected at request_id {rid}; subtree pruned")
        node["cycle"] = True
        return node
    visited = visited | {rid}
    kids = sorted(children.get(rid, []), key=lambda r: (rec_time(r) or ""))
    for kid in kids:
        node["children"].append(
            build_tree(kid, children, depth + 1, visited, warnings)
        )
    return node


def count_nodes(node):
    return 1 + sum(count_nodes(c) for c in node["children"])


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def fmt_duration(ms):
    if ms is None:
        return "dur=?"
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return "dur=?"
    return f"dur={ms / 1000:.2f}s" if ms >= 1000 else f"dur={ms:.1f}ms"


def summarize(r):
    """A short, level-appropriate one-liner of the interesting fields."""
    bits = []
    if r.get("model"):
        bits.append(f"model={r['model']}")
    usage = r.get("usage")
    if isinstance(usage, dict) and usage:
        bits.append(
            f"tokens={usage.get('input_tokens', '?')}/"
            f"{usage.get('output_tokens', '?')}"
        )
    if r.get("task_type"):
        bits.append(f"task_type={r['task_type']}")
    if r.get("status"):
        bits.append(f"status={r['status']}")
    if r.get("caller_tag"):
        bits.append(f"caller={r['caller_tag']}")
    errs = r.get("errors")
    if isinstance(errs, list) and errs:
        bits.append(f"errors={len(errs)}")
    comp = r.get("completion")
    if isinstance(comp, str) and comp.strip():
        preview = " ".join(comp.split())
        if len(preview) > 64:
            preview = preview[:61] + "..."
        bits.append(f'completion="{preview}"')
    return "  ".join(bits)


def render_tree(node, lines):
    """Append the indented text rendering of ``node`` (and subtree)."""
    r = node["record"]
    depth = node["depth"]
    indent = "  " * depth
    connector = "" if depth == 0 else "└─ "
    detail = "  " * depth + "    "

    level = rec_level(r)
    ts = rec_time(r) or "<no-timestamp>"
    dur = fmt_duration(rec_duration(r))
    pid = rec_parent(r)

    lines.append(f"{indent}{connector}[{level}]  {ts}  {dur}")
    lines.append(f"{detail}request_id={rec_id(r)}  parent={pid if pid else '-'}")
    summ = summarize(r)
    if summ:
        lines.append(f"{detail}{summ}")
    if node["cycle"]:
        lines.append(f"{detail}(cycle -- subtree pruned here)")
    for child in node["children"]:
        render_tree(child, lines)


def _emit_warnings(warnings):
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if warnings:
        print(f"({len(warnings)} warning(s) -- chain may be incomplete)",
              file=sys.stderr)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def run(argv=None):
    """Entry point. Returns a process exit code (0 ok, 1 not found/no data)."""
    parser = argparse.ArgumentParser(
        prog="inspect_run.py",
        description="Reconstruct the causal chain of an orchestrated run "
                    "from JSONL logs.",
    )
    sel = parser.add_mutually_exclusive_group(required=True)
    sel.add_argument("--task-id", help="root the chain at this task_id")
    sel.add_argument("--request-id",
                     help="root the chain at this request_id (for logs "
                          "without a task_id, e.g. wrapper-call logs)")
    parser.add_argument("--log", action="append", dest="logs", metavar="PATH",
                        help=f"JSONL log to read (repeatable). "
                             f"Default: {DEFAULT_LOG}")
    parser.add_argument("--no-discover", action="store_true",
                        help="do not auto-load sibling *.jsonl files")
    args = parser.parse_args(argv)

    requested = list(args.logs) if args.logs else [DEFAULT_LOG]
    paths = list(requested)
    if not args.no_discover:
        paths += discover_siblings(requested)

    records, warnings = load_records(paths)
    by_id, children, kept, idx_warnings = build_index(records)
    warnings += idx_warnings

    if not kept:
        print("error: no usable log records found in: "
              + ", ".join(requested), file=sys.stderr)
        _emit_warnings(warnings)
        return 1

    roots, error = select_roots(kept, by_id, args.task_id,
                                args.request_id, warnings)
    if error:
        print(f"error: {error}", file=sys.stderr)
        _emit_warnings(warnings)
        return 1

    selector = (f"task-id {args.task_id}" if args.task_id
                else f"request-id {args.request_id}")
    print(f"Causal chain for {selector}")
    print("logs: " + ", ".join(requested)
          + ("" if args.no_discover else "  (+ discovered sibling *.jsonl)"))
    print("=" * 78)

    total = 0
    for i, root in enumerate(roots):
        if len(roots) > 1:
            print(f"-- chain fragment {i + 1} of {len(roots)} "
                  "(chain is broken; see warnings) --")
        tree = build_tree(root, children, 0, frozenset(), warnings)
        total += count_nodes(tree)
        lines = []
        render_tree(tree, lines)
        print("\n".join(lines))

    print("=" * 78)
    print(f"{total} record(s) across {len(roots)} root(s).")
    _emit_warnings(warnings)
    return 0


if __name__ == "__main__":
    sys.exit(run())
