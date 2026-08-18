"""Tests for workers.consolidate_memory — the one-shot idempotent migration
CLI (LOOP_V1 P1, agent A7).

Hermetic + deterministic: no real model, no Chroma, no live files. The three
parallel-built contract modules (evidence_ladder / claim_extract / idea_ledger)
are supplied as contract-shaped stubs through the `*_fn` seams; the embedder is
monkeypatched marker->vector (markers like `[[k1]]` never tokenize, so the
lexical layer sees only real words).

Pinned behaviors (LOOP_V1 verification list):
  * dry-run (the DEFAULT) writes NOTHING;
  * second --execute run appends ZERO events (idempotency);
  * source corpora are never rewritten;
  * redteam fatal_flaw -> programmatic cluster_killed; rediscovery ->
    niche_seeded; leaked-JSON-blob claims repaired via claim_extract;
  * an out-of-enum rung from derive_level raises (never coerced).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import consolidate_memory as cm

VEC = {
    "k1": [1.0, 0.0, 0.0, 0.0, 0.0],
    "k2": [0.0, 1.0, 0.0, 0.0, 0.0],
    "k3": [0.0, 0.0, 1.0, 0.0, 0.0],
    "k4": [0.0, 0.0, 0.0, 1.0, 0.0],
    "k6": [0.0, 0.0, 0.0, 0.0, 1.0],
}


def _stub_embed(texts):
    out = []
    for i, t in enumerate(texts):
        vec = next((list(v) for key, v in VEC.items() if f"[[{key}]]" in t), None)
        if vec is None:  # unique one-hot per position -> all cosines 0
            vec = [0.0] * (len(texts) + 5)
            vec[i] = 1.0
        out.append(vec)
    return out


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "1")
    monkeypatch.setattr(cm, "_embed_texts", _stub_embed)


# ── Contract-shaped stubs for the parallel-built modules. ────────────────────
def _stub_derive(row, feedback_row, adversarial_block, health_rows):
    return {"level": row.get("_lvl", "L0"), "provisional": [],
            "missing_for_next": [], "reasons": []}


def _make_extract(calls):
    def _extract(iteration_row):
        calls.append(iteration_row.get("iteration_id"))
        return {"problem": "Bidder shading emerges under valuation uncertainty",
                "mechanism": "risk weighting compresses marginal bids",
                "predicted_effect": "systematic underbidding versus theory",
                "evidence_ref": {"iteration_id": iteration_row.get("iteration_id"),
                                 "journal_entry_path": None, "results_path": None}}
    return _extract


def _stub_append_event(path, event):
    # Seam pin: every planned event must satisfy the REAL ledger schema —
    # the production write path (idea_ledger.append_event) validates, so a
    # shape drift here is a migration that dies on --execute.
    from workers.idea_ledger import validate_event
    validate_event(event)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


# ── Fixture corpus. ──────────────────────────────────────────────────────────
def _loop_rows():
    return [
        {"iteration_id": "iter-001", "seed": {"topic": ""}, "_lvl": "L2",
         "hypothesis": {"text": "Cooperation rises steadily alongside memory "
                                "depth within repeated dilemma simulations [[k1]]"},
         "novelty": {"class": "novel"}, "critique": {"verdict": "survives"},
         "redteam": {"verdict": "proceed"}},
        # reworded near-dup of iter-001: tokens are a subset -> lexical >= 0.6,
        # but its vector is ORTHOGONAL, so only the lexical layer can catch it.
        {"iteration_id": "iter-002", "seed": {"topic": ""}, "_lvl": "L0",
         "hypothesis": {"text": "Cooperation rises alongside memory depth [[k2]]"},
         "novelty": {"class": "novel"}},
        {"iteration_id": "iter-003", "seed": {"topic": ""}, "_lvl": "L0",
         "hypothesis": {"text": "Auction overbidding stems from loss aversion "
                                "under ascending price formats [[k3]]"},
         "redteam": {"verdict": "fatal_flaw", "critique": "logically circular"}},
        {"iteration_id": "iter-004", "seed": {"topic": ""}, "_lvl": "L1",
         "hypothesis": {"text": "Zero determinant strategies enforce "
                                "extortionate payoff relations [[k4]]"},
         "novelty": {"class": "rediscovery", "rationale": "Press-Dyson 2012"}},
        # leaked JSON blob -> repaired via claim_extract
        {"iteration_id": "iter-005", "seed": {"topic": ""}, "_lvl": "L0",
         "hypothesis": {"text": '{\n  "candidates": ["leaked scratchpad"]\n}'},
         "novelty": {"class": "novel"}},
    ]


def _surfaced_rows():
    return [
        {"finding_id": "sf-001", "source_iteration_id": "iter-001",
         "claim": "Longer memory windows sustain cooperative equilibria in "
                  "iterated play [[k6]]",
         "adversarial": {"survived": False, "n_refuted": 3}},
        # leaked blob claim -> repaired from its SOURCE iteration row
        {"finding_id": "sf-002", "source_iteration_id": "iter-003",
         "claim": '{"claim": "leaked blob"}'},
    ]


def _write_corpus(tmp_path):
    lm = tmp_path / "loop_memory.jsonl"
    sf = tmp_path / "surfaced_findings.jsonl"
    lm.write_text("".join(json.dumps(r) + "\n" for r in _loop_rows()))
    sf.write_text("".join(json.dumps(r) + "\n" for r in _surfaced_rows()))
    return lm, sf


def _run(tmp_path, execute, derive=_stub_derive, calls=None):
    lm, sf = (tmp_path / "loop_memory.jsonl", tmp_path / "surfaced_findings.jsonl")
    if not lm.exists():
        lm, sf = _write_corpus(tmp_path)
    return cm.consolidate(
        loop_memory_path=lm, surfaced_path=sf,
        feedback_path=tmp_path / "loop_feedback.jsonl",
        ledger_path=tmp_path / "idea_ledger.jsonl",
        archive_path=tmp_path / "idea_archive.jsonl",
        execute=execute, derive_level_fn=derive,
        extract_claim_fn=_make_extract(calls if calls is not None else []),
        append_event_fn=_stub_append_event)


def _events(tmp_path):
    p = tmp_path / "idea_ledger.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


# ── Tests. ───────────────────────────────────────────────────────────────────
def test_dry_run_is_default_and_writes_nothing(tmp_path):
    lm, sf = _write_corpus(tmp_path)
    before = (lm.read_bytes(), sf.read_bytes())
    report = _run(tmp_path, execute=False)
    assert report["dry_run"] is True
    assert report["events_planned"] > 0 and report["events_appended"] == 0
    assert not (tmp_path / "idea_ledger.jsonl").exists()
    assert not (tmp_path / "idea_archive.jsonl").exists()
    assert (lm.read_bytes(), sf.read_bytes()) == before


def test_execute_clusters_via_lexical_layer_and_source_attach(tmp_path):
    report = _run(tmp_path, execute=True)
    # cl-iter-001 {r1, r2, sf-001} / cl-iter-003 {r3, sf-002} / r4 / r5
    assert report["clusters"] == 4
    ev = _events(tmp_path)
    created = {e["member_id"] for e in ev if e["event_type"] == "cluster_created"}
    assert created == {"iter-001", "iter-003", "iter-004", "iter-005"}
    added = {e["member_id"]: e for e in ev if e["event_type"] == "member_added"}
    # reworded near-dup collapsed by the LOAD-BEARING lexical layer (its
    # vector is orthogonal — the cosine layers could not have caught it)
    assert added["iter-002"]["cluster_id"] == "cl-iter-001"
    assert added["iter-002"]["accept_reason"].startswith("lexical_jaccard")
    # surfaced findings attach to their source iteration's cluster directly
    assert added["sf-001"]["cluster_id"] == "cl-iter-001"
    assert added["sf-001"]["accept_reason"].startswith("source_iteration")
    assert added["sf-002"]["cluster_id"] == "cl-iter-003"


def test_evidence_level_from_elite_member(tmp_path):
    report = _run(tmp_path, execute=True)
    lvl = [e for e in _events(tmp_path) if e["event_type"] == "evidence_level_changed"]
    by_cluster = {e["cluster_id"]: e for e in lvl}
    assert by_cluster["cl-iter-001"]["evidence_level"] == "L2"
    assert by_cluster["cl-iter-001"]["basis"] == "evidence_ladder:iter-001"
    assert by_cluster["cl-iter-004"]["evidence_level"] == "L1"
    assert report["rungs"] == {"L2": 1, "L0": 2, "L1": 1}


def test_fatal_flaw_kills_cluster_programmatically(tmp_path):
    report = _run(tmp_path, execute=True)
    assert report["killed"] == 1
    killed = [e for e in _events(tmp_path) if e["event_type"] == "cluster_killed"
              and e["kill_reason"]["code"] == "redteam_fatal_flaw"]
    assert len(killed) == 1
    assert killed[0]["cluster_id"] == "cl-iter-003"
    assert "iter-003" in killed[0]["kill_reason"]["evidence_key"]
    assert killed[0]["reopening_condition"]["requires"] == "new_evidence"


def test_rediscovery_seeds_paper_niche(tmp_path):
    report = _run(tmp_path, execute=True)
    assert report["paper_niches"] == 1
    niche = [e for e in _events(tmp_path) if e["event_type"] == "cluster_killed"
             and e["kill_reason"]["code"] == "paper_prior_exists"]
    assert len(niche) == 1
    assert niche[0]["cluster_id"] == "cl-iter-004"
    assert niche[0]["kill_reason"]["evidence_key"] == "iteration:iter-004:novelty"
    assert "Press-Dyson" in niche[0]["kill_reason"]["detail"]
    assert niche[0]["reopening_condition"]["evidence_kind"] == "articulated_delta"


def test_leaked_blobs_repaired_via_claim_extract(tmp_path):
    calls: list = []
    report = _run(tmp_path, execute=False, calls=calls)
    assert report["claims_repaired"] == 2
    assert set(report["repaired_ids"]) == {"iter-005", "sf-002"}
    # the surfaced blob is repaired from its SOURCE iteration row
    assert calls == ["iter-005", "iter-003"]


def test_archive_holds_near_dup_non_elite_only(tmp_path):
    report = _run(tmp_path, execute=True)
    rows = [json.loads(l) for l in
            (tmp_path / "idea_archive.jsonl").read_text().splitlines()]
    assert report["archived"] == 1 and len(rows) == 1
    assert rows[0]["member_id"] == "iter-002"
    assert rows[0]["reason"] == "near_dup_non_elite"
    # source-attached surfaced member is the same evidence, NOT a near-dup
    assert all(r["member_id"] != "sf-001" for r in rows)


def test_execute_never_rewrites_source_corpora(tmp_path):
    lm, sf = _write_corpus(tmp_path)
    before = (lm.read_bytes(), sf.read_bytes())
    _run(tmp_path, execute=True)
    assert (lm.read_bytes(), sf.read_bytes()) == before


def test_second_execute_appends_zero_events(tmp_path):
    first = _run(tmp_path, execute=True)
    assert first["events_appended"] > 0
    ledger_before = (tmp_path / "idea_ledger.jsonl").read_bytes()
    archive_before = (tmp_path / "idea_archive.jsonl").read_bytes()
    second = _run(tmp_path, execute=True)
    assert second["events_appended"] == 0
    assert second["skipped_already_processed"] == 7
    assert (tmp_path / "idea_ledger.jsonl").read_bytes() == ledger_before
    assert (tmp_path / "idea_archive.jsonl").read_bytes() == archive_before


def test_missing_corpus_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        cm.consolidate(
            loop_memory_path=tmp_path / "absent.jsonl",
            surfaced_path=tmp_path / "also_absent.jsonl",
            ledger_path=tmp_path / "idea_ledger.jsonl",
            archive_path=tmp_path / "idea_archive.jsonl",
            derive_level_fn=_stub_derive,
            extract_claim_fn=_make_extract([]),
            append_event_fn=_stub_append_event)


def test_out_of_enum_rung_raises_never_coerced(tmp_path):
    def bad_derive(row, fb, adv, health):
        return {"level": "L9", "provisional": [], "missing_for_next": [],
                "reasons": []}
    with pytest.raises(ValueError, match="L9"):
        _run(tmp_path, execute=False, derive=bad_derive)


# ── D-075 R4: refills match EXISTING open clusters before minting. ──────────
# The 2026-08-18 case: a corpus refill re-ran consolidation and rows that
# near-dup'd ALREADY-MINTED open clusters founded byte-similar duplicate
# clusters (3 of them; one then got killed while its identical original
# stayed open). Ratified fix: fresh items go through the SAME prefilter
# layers against existing not-killed ledger clusters FIRST; a match appends
# member_added to the EXISTING cluster instead of cluster_created.

def _refill(tmp_path, row):
    with open(tmp_path / "loop_memory.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_refill_near_dup_member_adds_to_existing_cluster(tmp_path):
    first = _run(tmp_path, execute=True)
    assert first["clusters"] == 4 and first["merged_into_existing"] == 0
    n_before = len(_events(tmp_path))
    # Refill row: reworded near-dup of open cluster cl-iter-001's members.
    # No [[k*]] marker -> its stub vector is orthogonal to every other text,
    # so ONLY the load-bearing lexical layer can catch it against the
    # existing cluster (exactly the intra-batch pin, now cross-run).
    _refill(tmp_path, {
        "iteration_id": "iter-101", "seed": {"topic": ""}, "_lvl": "L0",
        "hypothesis": {"text": "Cooperation rises alongside memory depth"},
        "novelty": {"class": "novel"}})
    # Dry-run plans the merge and writes nothing.
    dry = _run(tmp_path, execute=False)
    assert dry["merged_into_existing"] == 1 and dry["clusters"] == 0
    assert dry["events_planned"] == 1 and dry["events_appended"] == 0
    assert len(_events(tmp_path)) == n_before
    # Execute: ONE member_added to the EXISTING cluster; NO cluster_created.
    second = _run(tmp_path, execute=True)
    assert second["clusters"] == 0
    assert second["merged_into_existing"] == 1
    assert second["events_appended"] == 1
    new_ev = _events(tmp_path)[n_before:]
    assert len(new_ev) == 1
    assert new_ev[0]["event_type"] == "member_added"
    assert new_ev[0]["cluster_id"] == "cl-iter-001"
    assert new_ev[0]["member_id"] == "iter-101"
    assert new_ev[0]["accept_reason"].startswith("lexical_jaccard")
    assert second["existing_merges"] == [
        {"cluster_id": "cl-iter-001", "member_id": "iter-101",
         "layer": "lexical_jaccard", "score": 1.0}]
    # The near-dup joiner's text is preserved in the archive.
    rows = [json.loads(l) for l in
            (tmp_path / "idea_archive.jsonl").read_text().splitlines()]
    a101 = [r for r in rows if r["member_id"] == "iter-101"]
    assert len(a101) == 1
    assert a101[0]["cluster_id"] == "cl-iter-001"
    assert a101[0]["reason"] == "near_dup_non_elite"
    # Idempotency survives the merge: a third run appends ZERO events.
    third = _run(tmp_path, execute=True)
    assert third["events_appended"] == 0
    assert third["merged_into_existing"] == 0
    assert third["skipped_already_processed"] == 8


def test_refill_batch_chains_onto_existing_not_each_other(tmp_path):
    # Two refill near-dups of the same existing cluster: BOTH member_add to
    # cl-iter-001 — the existing cluster outranks minting a fresh intra-batch
    # duplicate (the exact 3-duplicate shape of the 08-18 incident).
    _run(tmp_path, execute=True)
    _refill(tmp_path, {
        "iteration_id": "iter-103", "seed": {"topic": ""}, "_lvl": "L0",
        "hypothesis": {"text": "Cooperation rises alongside memory depth"},
        "novelty": {"class": "novel"}})
    _refill(tmp_path, {
        "iteration_id": "iter-104", "seed": {"topic": ""}, "_lvl": "L0",
        "hypothesis": {"text": "Cooperation rises steadily alongside memory "
                               "depth within repeated dilemma simulations"},
        "novelty": {"class": "novel"}})
    second = _run(tmp_path, execute=True)
    assert second["merged_into_existing"] == 2 and second["clusters"] == 0
    added = {e["member_id"]: e for e in _events(tmp_path)
             if e["event_type"] == "member_added"}
    assert added["iter-103"]["cluster_id"] == "cl-iter-001"
    assert added["iter-104"]["cluster_id"] == "cl-iter-001"


def test_refill_dup_of_killed_cluster_founds_its_own(tmp_path):
    # cl-iter-003 was killed by redteam fatal_flaw in run 1. A refill near-dup
    # of it must NOT silently member_add into the dead niche (re-entry stays
    # accept_candidate's evidence-keyed job) — it founds its own cluster.
    _run(tmp_path, execute=True)
    _refill(tmp_path, {
        "iteration_id": "iter-102", "seed": {"topic": ""}, "_lvl": "L0",
        "hypothesis": {"text": "Auction overbidding stems from loss aversion"},
        "novelty": {"class": "novel"}})
    second = _run(tmp_path, execute=True)
    assert second["merged_into_existing"] == 0
    assert second["clusters"] == 1
    created = [e for e in _events(tmp_path) if e["event_type"] == "cluster_created"
               and e["member_id"] == "iter-102"]
    assert len(created) == 1 and created[0]["cluster_id"] == "cl-iter-102"
    killed_adds = [e for e in _events(tmp_path)
                   if e["event_type"] == "member_added"
                   and e["cluster_id"] == "cl-iter-003"
                   and e["member_id"] == "iter-102"]
    assert killed_adds == []
