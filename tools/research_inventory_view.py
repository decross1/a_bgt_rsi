"""Render an explicitly classified, frozen research inventory without runtime imports.

This checks caller-selected evidence consistency, not scientific truth or source
authenticity. It does not derive a rung, promote a claim, or import model code.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path
import re


STATUSES = {"learned", "running", "owed", "invalid", "blocked"}
BINDINGS = {"bound", "mismatch", "unverifiable", "missing"}


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("expected SHA256 hex digest")


def validate(report):
    if report.get("schema") != "research-inventory-view-v1":
        raise ValueError("unsupported inventory schema")
    stamp = datetime.fromisoformat(report["source_as_of"].replace("Z", "+00:00"))
    if stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError("source cursor must be UTC")
    _digest(report["cursor_sha256"])
    for name, meta in report["sources"].items():
        if not name or name.startswith("/") or "\\" in name or any(
                part in {"", ".", ".."} for part in name.split("/")):
            raise ValueError("source path must be canonical and relative")
        _digest(meta["sha256"])
        # None denotes existing whole-file-only evidence, never row-addressable.
        if meta["records"] is not None and (type(meta["records"]) is not int or meta["records"] < 0):
            raise ValueError("source record count must be a nonnegative integer")
    for collection in ("items", "iterations"):
        rows = report[collection]
        ids = [row["item_id"] for row in rows]
        expected = report["coverage"][collection]
        if len(ids) != len(set(ids)) or len(expected) != len(set(expected)) \
                or sorted(ids) != sorted(expected):
            raise ValueError("missing, duplicate or unexpected inventory item")
        for row in rows:
            if row["status"] not in STATUSES or row["binding_status"] not in BINDINGS \
                    or row["evidence_level"] not in {"L" + str(i) for i in range(6)}:
                raise ValueError("invalid explicit disposition")
            if not row["next_evidence"] or not row["source_refs"]:
                raise ValueError("next evidence and source references required")
            for ref in row["source_refs"]:
                if ref["path"] in report["sources"] and report["sources"][ref["path"]]["records"] is None:
                    raise ValueError("source record count required for a row locator")
                if ref["path"] not in report["sources"] or type(ref["line"]) is not int \
                        or not 1 <= ref["line"] <= report["sources"][ref["path"]]["records"]:
                    raise ValueError("source locator outside declared cursor")
                _digest(ref["raw_row_sha256"])
    return report


def verify_sources(report, snapshot):
    """Check full source bytes and referenced raw rows against the pinned cursor.

    Caller owns snapshot ancestry/lifecycle. No check-open or OS confinement
    guarantee is made; model execution is not part of this tool.
    """
    validate(report)
    lines = {}
    for name, meta in report["sources"].items():
        raw = (snapshot / name).read_bytes()
        if len(raw) != meta["bytes"] or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise ValueError("source changed relative to frozen cursor: " + name)
        lines[name] = raw.splitlines(keepends=True)
        if meta["records"] is not None and len(lines[name]) != meta["records"]:
            raise ValueError("source record count differs from frozen cursor: " + name)
    for row in report["items"] + report["iterations"]:
        for ref in row["source_refs"]:
            raw = lines[ref["path"]][ref["line"] - 1]
            if hashlib.sha256(raw).hexdigest() != ref["raw_row_sha256"]:
                raise ValueError("raw row differs from evidence locator")


def render(report):
    validate(report)
    e = lambda value: escape(str(value), quote=True)
    content = []
    for row in report["items"]:
        refs = "\n".join(f'{r["path"]}:{r["line"]} SHA256 {r["raw_row_sha256"]}'
                         for r in row["source_refs"])
        content.append(
            f'<tr data-status="{e(row["status"])}" data-level="{e(row["evidence_level"])}">'
            f'<td><strong>{e(row["item_id"])}</strong><p>{e(row["claim"])}</p></td>'
            f'<td>{e(row["status"])}<p>{e(row["reason"])}</p></td>'
            f'<td>{e(row["evidence_level"])}<p>Binding: {e(row["binding_status"])}</p></td>'
            f'<td>{e(row["last_evidence_at"] or "unknown")}<p>{e(row["next_evidence"])}</p></td>'
            f'<td><details><summary>Evidence and limits</summary>'
            f'<p>{e(row["confidence"])}</p><pre>{e(refs)}</pre></details></td></tr>')
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research evidence inventory</title>
<style>body{font:16px system-ui;margin:2rem;color:#19232c;background:#f6f8fa}
main{max-width:1500px;margin:auto}table{border-collapse:collapse;width:100%;background:white}
th,td{padding:1rem;text-align:left;vertical-align:top;border-bottom:1px solid #ccd5dd}
th{background:#e5edf4}td:first-child{width:30%}p{line-height:1.45}pre{white-space:pre-wrap;
overflow-wrap:anywhere;font-size:12px}label{display:inline-block;margin:0 1rem 1rem 0}
input,select{font:inherit;padding:.4rem}tr[hidden]{display:none}.note{background:#fff3cd;padding:1rem}
</style><main><h1>Research evidence inventory</h1>''' + (
        f'<p>Source as of <strong>{e(report["source_as_of"])}</strong>. '
        f'Cursor SHA256 <code>{e(report["cursor_sha256"])}</code>.</p>'
        f'<p class="note">{e(report["limits"])}</p>'
        '<p>L0–L5 labels are evidence-ladder projections. Experiment tiers and governance tiers '
        'are separate. “Invalid” here includes inactive or killed items; it does not mean that '
        'an unbound hypothesis has been disproved. No live execution status is inferred.</p>'
        '<label>Search <input id="query" type="search"></label>'
        '<label>Disposition <select id="status"><option value="">All</option>'
        + ''.join(f'<option>{s}</option>' for s in sorted(STATUSES)) + '</select></label>'
        '<label><input id="focus" type="checkbox"> Current L1/L2 labels only</label>'
        '<p id="count" aria-live="polite"></p><table><thead><tr><th>Item and claim</th>'
        '<th>Disposition</th><th>Recorded level</th><th>Latest member observation and next requirement</th>'
        '<th>Sources</th></tr></thead><tbody>' + ''.join(content) + '</tbody></table>'
        f'<p>Coverage: {len(report["items"])} current clusters and '
        f'{len(report["iterations"])} historical iterations in the companion JSON.</p>'
    ) + '''</main><script>
const rows=[...document.querySelectorAll('tbody tr')];
const query=document.getElementById('query'),status=document.getElementById('status');
const focus=document.getElementById('focus');
function filter(){let shown=0;for(const row of rows){
row.hidden=!(row.textContent.toLowerCase().includes(query.value.toLowerCase())&&
(!status.value||row.dataset.status===status.value)&&
(!focus.checked||['L1','L2'].includes(row.dataset.level)));if(!row.hidden)shown++;}
document.getElementById('count').textContent=shown+' of '+rows.length+' clusters shown';}
for(const input of [query,status,focus])input.addEventListener('input',filter);filter();
</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.inventory.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        raise ValueError("inventory differs from selected digest")
    report = json.loads(raw)
    verify_sources(report, args.snapshot)
    with args.output.open("x") as handle:
        handle.write(render(report))


if __name__ == "__main__":
    main()
