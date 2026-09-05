"""Additional lab-specific exposure checks beyond the inherited audit tests."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from tools.audit_claim_binding import exposure_manifest, main
from tools.claim_binding_audit import ApparatusAuditInputError, audit_claim_bindings


def source_pair(tmp_path):
    loop = tmp_path / "loop.jsonl"
    calls = tmp_path / "calls.jsonl"
    stages = ["retrieve_literature", "novelty_classify", "critic_loop_v0"]
    iterations, records = [], []
    for ident, mode in [("i-bound", "bound"), ("i-mismatch", "mismatch"), ("i-unknown", "unknown")]:
        ids = [ident + str(n) for n in range(3)]
        iterations.append({"iteration_id": ident, "hypothesis": {"text": "H"}, "wrapper_call_ids": ids})
        for n, stage in enumerate(stages):
            completion = json.dumps([{"id": "tool-" + str(n), "type": "function",
                                     "function": {"name": stage, "arguments": json.dumps({"hypothesis_text": "old" if mode == "mismatch" else "H"})}}])
            if mode == "unknown" and n == 2:
                completion = "final prose without a terminal discriminator"
            records.append({"request_id": ids[n], "run_id": ident,
                            "caller_tag": "nara.run_iteration",
                            "parent_request_id": ident if n == 0 else ids[n - 1],
                            "completion": completion})
    loop.write_text("".join(json.dumps(r) + "\n" for r in iterations))
    calls.write_text("".join(json.dumps(r) + "\n" for r in records))
    return loop, calls


def test_exposure_preserves_all_members_and_never_changes_disposition(tmp_path):
    loop, calls = source_pair(tmp_path)
    before = (loop.read_bytes(), calls.read_bytes())
    report = audit_claim_bindings(loop, calls)
    result = exposure_manifest(report)
    manifest = result["manifest"]
    assert manifest["aggregate"]["iteration_status"] == {"bound": 1, "mismatch": 1, "unverifiable": 1}
    assert [r["evidence_quarantined"] for r in manifest["iterations"]] == [False, True, True]
    assert all(r["research_disposition"] == "unchanged" for r in manifest["iterations"])
    assert manifest["authority_effect"] == "none"
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert result["manifest_sha256"] == "sha256:" + sha256(encoded).hexdigest()
    assert (loop.read_bytes(), calls.read_bytes()) == before


def test_prefix_exposure_identity_survives_unrelated_later_appends(tmp_path):
    loop, calls = source_pair(tmp_path)
    b1, b2 = loop.read_bytes(), calls.read_bytes()
    kwargs = dict(loop_memory_bytes=len(b1), call_log_bytes=len(b2),
                  expected_loop_memory_sha256=sha256(b1).hexdigest(),
                  expected_call_log_sha256=sha256(b2).hexdigest())
    before = exposure_manifest(audit_claim_bindings(loop, calls, **kwargs))
    with calls.open("a") as f:
        f.write(json.dumps({"request_id": "unrelated"}) + "\n")
    after = exposure_manifest(audit_claim_bindings(loop, calls, **kwargs))
    assert after == before  # cursor identity, not mutable file mtime or path


@pytest.mark.parametrize("change", ["duplicate", "unknown_status", "wrong_count"])
def test_exposure_refuses_inconsistent_membership(tmp_path, change):
    loop, calls = source_pair(tmp_path)
    r = deepcopy(audit_claim_bindings(loop, calls))
    if change == "duplicate":
        r["iterations"].append(r["iterations"][0])
    elif change == "unknown_status":
        r["iterations"][0]["status"] = "accepted"
    else:
        r["aggregate"]["iterations"] += 1
    with pytest.raises(ApparatusAuditInputError):
        exposure_manifest(r)


def test_cli_exposure_findings_and_malformed_input_are_distinct(tmp_path, capsys):
    loop, calls = source_pair(tmp_path)
    args = ["--loop-memory", str(loop), "--call-log", str(calls), "--exposure"]
    assert main(args) == 1
    assert json.loads(capsys.readouterr().out)["manifest"]["aggregate"]["iterations"] == 3
    loop.write_text("malformed\n")
    assert main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "input invalid" in captured.err
