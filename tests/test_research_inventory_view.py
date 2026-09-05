import copy
import hashlib
import json

import pytest

from tools.research_inventory_view import render, validate, verify_sources


def example():
    raw = b'{"id":"x"}\n'
    digest = hashlib.sha256(raw).hexdigest()
    row = dict(item_id="x", status="blocked", evidence_level="L2",
               binding_status="unverifiable", next_evidence="Bind an exact claim",
               source_refs=[dict(path="source.jsonl", line=1, raw_row_sha256=digest)],
               claim="</script><img src=x onerror=alert(1)>", reason="No bound claim",
               confidence="High confidence in observed bytes; science unknown", last_evidence_at=None)
    return dict(schema="research-inventory-view-v1", source_as_of="2026-09-05T05:37:41Z",
                cursor_sha256="a" * 64, sources={"source.jsonl": dict(sha256=digest, bytes=len(raw), records=1)},
                coverage=dict(items=["x"], iterations=["x"]), items=[row], iterations=[copy.deepcopy(row)],
                limits="Frozen observation; no promotion")


def test_html_treats_claim_as_text_and_keeps_unknown_status():
    html = render(example())
    assert '<img src=x' not in html and '&lt;img src=x' in html
    assert html.count('<script>') == 1
    assert 'No live execution status is inferred' in html
    assert 'Current L1/L2 labels only' in html and 'Binding: unverifiable' in html
    assert 'Latest member observation and next requirement' in html


@pytest.mark.parametrize("fault", ["duplicate", "missing", "missing-ref", "wrong-row", "bad-status", "bad-time", "traversal"])
def test_incomplete_or_ambiguous_input_fails(fault):
    report = example()
    if fault == "duplicate": report["items"].append(copy.deepcopy(report["items"][0]))
    if fault == "missing": report["items"] = []
    if fault == "missing-ref": report["items"][0]["source_refs"] = []
    if fault == "wrong-row": report["items"][0]["source_refs"][0]["line"] = 2
    if fault == "bad-status": report["items"][0]["status"] = "success"
    if fault == "bad-time": report["source_as_of"] = "2026-09-05T05:00:00"
    if fault == "traversal": report["sources"]["../outside"] = report["sources"].pop("source.jsonl")
    with pytest.raises(ValueError): validate(report)


def test_exact_bytes_then_stale_source_and_wrong_row_hash(tmp_path):
    report = example()
    path = tmp_path / "source.jsonl"
    path.write_bytes(b'{"id":"x"}\n')
    verify_sources(report, tmp_path)
    report["items"][0]["source_refs"][0]["raw_row_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="raw row"): verify_sources(report, tmp_path)
    path.write_bytes(b'{"id":"changed"}\n')
    with pytest.raises(ValueError, match="source changed"): verify_sources(example(), tmp_path)


@pytest.mark.parametrize("declared,line", [(1, 1), (3, 3)])
def test_correctly_hashed_two_rows_reject_false_record_count(tmp_path, declared, line):
    report = example()
    raw = b'{"id":"x"}\n{"id":"y"}\n'
    (tmp_path / "source.jsonl").write_bytes(raw)
    report["sources"]["source.jsonl"] = dict(
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), records=declared)
    report["items"][0]["source_refs"][0]["line"] = line
    with pytest.raises(ValueError, match="source record count"):
        verify_sources(report, tmp_path)


@pytest.mark.parametrize("records", [True, -1, 1.0, "1", None])
def test_record_count_is_a_nonnegative_integer(records):
    report = example()
    report["sources"]["source.jsonl"]["records"] = records
    with pytest.raises(ValueError, match="source record count"):
        validate(report)


def test_whole_file_only_evidence_retains_byte_checks(tmp_path):
    report = example()
    (tmp_path / "source.jsonl").write_bytes(b'{"id":"x"}\n')
    raw = b"Frozen non-row evidence\n"
    whole = tmp_path / "notes.md"
    whole.write_bytes(raw)
    report["sources"]["notes.md"] = dict(
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), records=None)
    verify_sources(report, tmp_path)
    whole.write_bytes(raw + b"changed\n")
    with pytest.raises(ValueError, match="source changed"):
        verify_sources(report, tmp_path)


def test_frozen_two_row_cli_render_preserves_inputs_and_refuses_overwrite(tmp_path, monkeypatch):
    from tools.research_inventory_view import main
    report = example()
    # Last raw row has no newline: splitlines still counts it and preserves bytes.
    raw = b'{"id":"x"}\n{"id":"y"}'
    (tmp_path / "source.jsonl").write_bytes(raw)
    report["sources"]["source.jsonl"] = dict(
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), records=2)
    ref = report["items"][0]["source_refs"][0]
    ref["line"] = 2
    ref["raw_row_sha256"] = hashlib.sha256(raw.splitlines(keepends=True)[1]).hexdigest()
    inventory = tmp_path / "inventory.json"
    frozen = json.dumps(report).encode()
    inventory.write_bytes(frozen)
    output = tmp_path / "view.html"
    monkeypatch.setattr("sys.argv", ["research_inventory_view", str(inventory),
        "--sha256", hashlib.sha256(frozen).hexdigest(), "--snapshot", str(tmp_path),
        "--output", str(output)])
    main()
    html = output.read_bytes()
    assert html == render(report).encode()
    assert b"&lt;img src=x" in html and b"No live execution status is inferred" in html
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == html
    assert inventory.read_bytes() == frozen
    assert (tmp_path / "source.jsonl").read_bytes() == raw
