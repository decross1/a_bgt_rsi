"""Tests for workers.claim_extract — canonical claim record extraction (A2).

Hermetic + deterministic: MOCK_LLM=1 is forced, so the deterministic path is
the whole behavior and NO wrapper call can occur (a sentinel raises if one is
attempted). The real-run refinement seam is exercised by monkeypatching
`_refine_fields` — success adopts the refined fields, failure falls back to
the deterministic draft AND logs it (rule 7, asserted on a captured run-log).

The leaked-JSON-blob repair is tested against BOTH hand-built fixtures that
replicate the two real defective rows' shapes (sf-iter-2026-06-13-001,
sf-iter-2026-08-04-001 — invalid LaTeX escapes and all) and, read-only,
against the actual rows in memory/surfaced_findings.jsonl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import claim_extract as ce

SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Force MOCK_LLM and make any wrapper-call attempt an immediate failure."""
    monkeypatch.setenv("MOCK_LLM", "1")

    def _boom(*a, **k):  # pragma: no cover - reached only on a discipline breach
        raise AssertionError("wrapper refinement must NOT run under MOCK_LLM")

    monkeypatch.setattr(ce, "_refine_fields", _boom)


def _row(text, topic="repeated public goods games", **extra):
    row = {
        "iteration_id": "iter-2026-01-01-001",
        "seed": {"topic": topic, "source": "human_cli"},
        "hypothesis": {"text": text},
        "journal_entry_path": "journal/iterations/001.md",
    }
    row.update(extra)
    return row


# ── Deterministic derivation ─────────────────────────────────────────────────

def test_deterministic_fields_with_mechanism_marker():
    text = ("Cooperation decays faster in large groups because free-riding "
            "is harder to attribute. A second sentence is ignored.")
    claim = ce.extract_claim(_row(text))
    assert claim["problem"] == "repeated public goods games"
    assert claim["predicted_effect"] == (
        "Cooperation decays faster in large groups because free-riding "
        "is harder to attribute.")
    assert claim["mechanism"] == ("because free-riding is harder to attribute")


def test_earliest_marker_wins():
    text = "Bids fall where exposure rises because loss aversion dominates."
    claim = ce.extract_claim(_row(text))
    assert claim["mechanism"].startswith("where exposure rises")


def test_no_marker_yields_empty_mechanism_never_invented():
    claim = ce.extract_claim(_row("Bidders shade bids below valuation."))
    assert claim["mechanism"] == ""


def test_problem_falls_back_to_first_sentence_without_topic():
    claim = ce.extract_claim(_row("Bidders shade bids. More text.", topic=""))
    assert claim["problem"] == "Bidders shade bids."


def test_evidence_ref_mapping():
    row = _row("Bidders shade bids.",
               experiment_outcome={"experiment_id": "exp003",
                                   "results_path": "experiments/exp003/results/summary.md"})
    ref = ce.extract_claim(row)["evidence_ref"]
    assert ref == {"iteration_id": "iter-2026-01-01-001",
                   "journal_entry_path": "journal/iterations/001.md",
                   "results_path": "experiments/exp003/results/summary.md"}


def test_evidence_ref_absent_fields_are_none():
    row = _row("Bidders shade bids.")
    del row["journal_entry_path"]
    ref = ce.extract_claim(row)["evidence_ref"]
    assert ref["journal_entry_path"] is None and ref["results_path"] is None


def test_empty_row_raises_never_fabricates():
    with pytest.raises(ValueError):
        ce.extract_claim({"iteration_id": "iter-x", "seed": {"topic": ""},
                          "hypothesis": {"text": "  "}})


def test_hypothesisless_legacy_row_uses_seed_topic():
    claim = ce.extract_claim({"iteration_id": "iter-legacy",
                              "seed": {"topic": "Folk theorem cooperation"}})
    assert claim["problem"] == "Folk theorem cooperation"
    assert claim["predicted_effect"] == "Folk theorem cooperation"


# ── Leaked-JSON-blob detection + repair ──────────────────────────────────────

# Shape of sf-iter-2026-06-13-001: raw LaTeX ($\lambda$) leaks INVALID JSON
# escapes into the blob, so strict json.loads fails.
BLOB_INVALID_ESCAPES = (
    '{\n  "candidates": [\n    "Do QRE better predict human play than Nash?",\n'
    '    "The decay of cooperation is better modeled by a QRE where the '
    'rationality parameter $\\lambda$ decreases over time."\n  ],\n'
    '  "chosen": "The decay of cooperation is better modeled by a QRE where '
    'the rationality parameter $\\lambda$ decreases over time."\n}'
)

# Shape of sf-iter-2026-08-04-001: chosen is double-escaped (valid), the
# candidates still carry invalid escapes.
BLOB_MIXED_ESCAPES = (
    '{\n  "candidates": [\n    "The frontier satisfies $b^*$ where '
    '$\\lambda$ scales the loss gradient."\n  ],\n'
    '  "chosen": "The frontier is a critical threshold $\\\\tau$ such that '
    'agents deviate from Nash only when the loss gradient is attenuated by '
    '$\\\\lambda$."\n}'
)


def test_blob_detection():
    assert ce._looks_like_blob(BLOB_INVALID_ESCAPES)
    assert ce._looks_like_blob(BLOB_MIXED_ESCAPES)
    assert not ce._looks_like_blob("A plain hypothesis about {sets} of bidders.")


def test_repair_strict_valid_blob_prefers_chosen():
    blob = json.dumps({"candidates": ["a claim", "b claim"], "chosen": "b claim"})
    assert ce._repair_blob(blob) == "b claim"


def test_repair_invalid_escape_blob():
    text = ce._repair_blob(BLOB_INVALID_ESCAPES)
    assert text.startswith("The decay of cooperation")
    assert "$\\lambda$" in text  # LaTeX survives repair (single backslash)


def test_repair_mixed_escape_blob():
    text = ce._repair_blob(BLOB_MIXED_ESCAPES)
    assert text.startswith("The frontier is a critical threshold")


def test_repair_candidates_only_takes_last():
    blob = json.dumps({"candidates": ["first", "second", "the pick"]})
    assert ce._repair_blob(blob) == "the pick"


def test_unrecoverable_blob_raises():
    with pytest.raises(ValueError):
        ce._repair_blob('{"candidates": [], "chosen": ""}')


def test_extract_claim_repairs_blob_hypothesis():
    claim = ce.extract_claim(_row(BLOB_INVALID_ESCAPES, topic="QRE vs Nash"))
    assert claim["problem"] == "QRE vs Nash"
    assert claim["predicted_effect"].startswith("The decay of cooperation")
    assert "candidates" not in claim["predicted_effect"]
    assert claim["mechanism"].startswith("where the rationality parameter")


# ── The two REAL defective rows (read-only) ──────────────────────────────────

def _real_claims():
    rows = {}
    for line in SURFACED.read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if obj.get("finding_id") in ("sf-iter-2026-06-13-001", "sf-iter-2026-08-04-001"):
            rows[obj["finding_id"]] = obj
    return rows


def test_real_leaked_rows_detected_and_repaired():
    rows = _real_claims()
    assert set(rows) == {"sf-iter-2026-06-13-001", "sf-iter-2026-08-04-001"}
    for fid, obj in rows.items():
        assert ce._looks_like_blob(obj["claim"]), fid
        repaired = ce._repair_blob(obj["claim"])
        assert repaired and not repaired.startswith("{"), fid
    assert "QRE" in ce._repair_blob(rows["sf-iter-2026-06-13-001"]["claim"])
    assert "Targeted-Loss Exposure Frontier" in ce._repair_blob(
        rows["sf-iter-2026-08-04-001"]["claim"])


def test_real_row_full_extract():
    obj = _real_claims()["sf-iter-2026-06-13-001"]
    claim = ce.extract_claim({
        "iteration_id": obj["source_iteration_id"],
        "seed": {"topic": obj["title"]},
        "hypothesis": {"text": obj["claim"]},
        "journal_entry_path": obj["evidence"]["journal_entry_path"],
    })
    assert claim["evidence_ref"]["iteration_id"] == "iter-2026-06-13-001"
    assert claim["evidence_ref"]["journal_entry_path"] == "journal/iterations/075.md"
    assert claim["predicted_effect"].startswith("In repeated public goods games")


# ── Refinement seam (real-run path, fully stubbed) ───────────────────────────

def test_refinement_adopted_on_success(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)
    refined = {"problem": "P", "mechanism": "M", "predicted_effect": "E"}
    monkeypatch.setattr(ce, "_refine_fields", lambda fields, text: dict(refined))
    claim = ce.extract_claim(_row("Bidders shade bids because of loss aversion."))
    assert {k: claim[k] for k in refined} == refined


def test_refinement_failure_is_logged_fallback(monkeypatch):
    monkeypatch.delenv("MOCK_LLM", raising=False)

    def _fail(fields, text):
        raise RuntimeError("backend down")

    logged = []
    from orchestrator import runtime
    monkeypatch.setattr(ce, "_refine_fields", _fail)
    monkeypatch.setattr(runtime, "append_run_log", lambda row: logged.append(row))

    claim = ce.extract_claim(_row("Bids fall because loss aversion dominates."))
    # Deterministic draft survives the failed refinement...
    assert claim["predicted_effect"].startswith("Bids fall")
    assert claim["mechanism"] == "because loss aversion dominates"
    # ...and the fallback is logged, never silent (rule 7).
    assert len(logged) == 1
    assert logged[0]["task_id"] == "claim_extract_refine"
    assert logged[0]["status"] == "fallback"
    assert "backend down" in logged[0]["observable_actual"]
