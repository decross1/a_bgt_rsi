"""Pointed gate-verdict copy tests (owner ask 2026-08-18 #2: the owe card's
three sections were GENERIC — WHAT YOU'RE DOING must name the hypothesis +
experiment + cluster, WHAT APPROVAL MEANS must state the real consequences,
VET FIRST must be pointed probes with values inline).

Fixture-driven through the live endpoint (test_owe_triage idiom: every path
at tmp_path). The pins:

- WHAT YOU'RE DOING joins hypothesis.text (truncated), experiment facts, and
  the idea-ledger cluster placement.
- WHAT APPROVAL MEANS branches: killed cluster -> settles-the-record + does
  NOT reopen (+ the null-kill close-out); open/no cluster -> the grep-proven
  live consequences (L5 rung, promotion, consolidation, meta-review). The
  mechanical loop_feedback line is a one-line footnote, not the headline.
- VET FIRST probes: old-redteam caveat only on fatal_flaw rows PREDATING the
  2026-08-18 R1a battery; debate > skeptic > pre-debate-era; low_confidence
  retrieval with the reason inline; discrimination check with the locked-rule
  path; ledger siblings named. Ordered by decisiveness, capped at 5.
- ABSENT facts produce NO fabricated text — ever.
- A schema-invalid ledger falls back to the tolerant raw scan (never 500s,
  kill facts still honest).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app

_ITEM_KEYS = {"kind", "id", "title", "since", "detail", "resolve_command"}

# Verbatim anchors of the caveat + branch texts (human_todo.py constants).
_CAVEAT_ANCHOR = "OLD redteam prompt"
_PRE_DEBATE_ANCHOR = "pre-debate-era row: no independent skeptic ever saw this"
_FOOTNOTE_ANCHOR = "(Mechanically: gate_cli appends one row to memory/loop_feedback.jsonl"


def _client(tmp_path) -> TestClient:
    """TestClient with every path at tmp_path (test_owe_triage idiom)."""
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"current_day": "owe_pointed"}), encoding="utf-8")
    telemetry = tmp_path / "telemetry.jsonl"
    telemetry.write_text("", encoding="utf-8")
    bench = tmp_path / "day1.csv"
    bench.write_text(
        "prompt_idx,completion_tokens,elapsed_s,decode_tok_per_s\n0,256,8.0,32.0\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    loop_run_state = tmp_path / "loop_run_state"
    loop_run_state.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)
    return TestClient(create_app(
        logs_dir=tmp_path / "logs",
        telemetry_file=telemetry,
        state_file=state,
        bench_csv=bench,
        mtp_csv=tmp_path / "mtp.csv",
        loop_v0_repo=repo,
        loop_v0_run_state=loop_run_state,
        loop_v0_journal=journal_dir,
        loop_v0_memory=tmp_path / "loop_memory.jsonl",
        coordinator_run_state=tmp_path / "coord_run_state",
        coordinator_memory=tmp_path / "coord_memory",
    ))


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r) if not isinstance(r, str) else r for r in rows)
        + "\n",
        encoding="utf-8",
    )


def _mem_row(iteration_id: str, **overrides) -> dict:
    """A pending experiment-stage loop_memory row; overrides are merged
    shallowly (None removes the key)."""
    row = {
        "iteration_id": iteration_id,
        "gate_status": "pending",
        "ended_at": "2026-06-05T20:31:13Z",
        "seed": {"topic": f"topic of {iteration_id}"},
        "hypothesis": {"text": "Cognitive load forces truthful VCG bidding."},
        "experiment_outcome": {
            "experiment_id": "exp004", "metric": "vcg_truthful_fraction",
            "value": 0.965, "trials": 150,
            "results_path": "experiments/exp004/results/summary.json",
        },
    }
    for key, value in overrides.items():
        if value is None:
            row.pop(key, None)
        else:
            row[key] = value
    return row


# Schema-valid ledger fixtures (workers/idea_ledger.py reducer accepts them).
def _ledger_created(cid: str, member: str, ts="2026-08-15T01:00:00Z") -> dict:
    return {"event_type": "cluster_created", "ts": ts, "cluster_id": cid,
            "origin": "consolidation", "member_id": member,
            "iteration_id": member}


def _ledger_added(cid: str, member: str, ts="2026-08-15T01:00:00Z") -> dict:
    return {"event_type": "member_added", "ts": ts, "cluster_id": cid,
            "member_id": member, "accept_reason": "lexical_jaccard:0.690"}


def _ledger_killed(cid: str, code: str, evidence_key: str,
                   ts="2026-08-15T01:14:25Z",
                   reopen_kind="redteam_proceed_on_revision") -> dict:
    return {"event_type": "cluster_killed", "ts": ts, "cluster_id": cid,
            "kill_reason": {"code": code, "evidence_key": evidence_key,
                            "detail": f"{code} via {evidence_key}"},
            "reopening_condition": {"requires": "new_evidence",
                                    "evidence_kind": reopen_kind}}


def _get_item(client: TestClient, item_id: str) -> dict:
    body = client.get("/api/human_todo").json()
    by_id = {i["id"]: i for i in body["items"]}
    assert item_id in by_id, f"{item_id} missing from {sorted(by_id)}"
    return by_id[item_id]


# --- WHAT YOU'RE DOING + WHAT APPROVAL MEANS: killed-cluster branch ---------

def test_killed_cluster_doing_and_consequence(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-A")])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-A", "iter-A"),
        _ledger_killed("cl-iter-A", "redteam_fatal_flaw",
                       "iteration:iter-A:redteam"),
    ])
    item = _get_item(client, "iter-A")
    # Frozen keys intact (additive contract).
    assert _ITEM_KEYS <= set(item)
    # DOING: hypothesis + experiment facts + the ledger placement, verbatim
    # from the record.
    doing = item["doing"]
    assert "judging whether this finished iteration's record is sound" in doing
    assert 'hypothesis: "Cognitive load forces truthful VCG bidding."' in doing
    assert ("Its experiment exp004 measured vcg_truthful_fraction=0.965 "
            "over 150 trials." in doing)
    assert "cluster cl-iter-A, KILLED 2026-08-15 (redteam_fatal_flaw)" in doing
    # MEANS: kill code + date, does NOT reopen (with the ledger's reopening
    # condition), settles-the-record — and the mechanical line is a trailing
    # one-line footnote, not the headline.
    means = item["approval_means"]
    assert means.startswith("Cluster cl-iter-A is already KILLED "
                            "(redteam_fatal_flaw, 2026-08-15)")
    assert "does NOT reopen" in means
    assert "new evidence (redteam_proceed_on_revision)" in means
    assert "settles the historical record" in means
    assert "nothing downstream re-runs" in means
    assert means.endswith("readers are last-row-wins.)")
    assert _FOOTNOTE_ANCHOR in means
    # Softened calibration claim (2026-08-18): no automated scorer joins
    # loop_feedback to calibration entries — the copy says the join is
    # manual, and the old overclaim is gone.
    assert "your calibration stats" not in means
    assert "that join is manual today" in means


def test_null_kill_is_a_record_keeping_closeout(tmp_path):
    """Kill code experiment_null_effect citing this row's OWN experiment ->
    the verdict is named a record-keeping close-out."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-N", experiment_outcome={
                     "experiment_id": "exp010_audit", "metric": "delta",
                     "value": 0.0, "trials": 30})])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-N", "iter-N"),
        _ledger_killed("cl-iter-N", "experiment_null_effect",
                       "iteration:exp010_audit:experiment_outcome",
                       reopen_kind="experiment_rerun"),
    ])
    means = _get_item(client, "iter-N")["approval_means"]
    assert "experiment_null_effect" in means
    assert "record-keeping close-out" in means
    assert "does NOT reopen" in means


def test_open_cluster_consequence_names_what_a_verdict_gates(tmp_path):
    """No kill -> the grep-proven live consequences: L5 rung ('valid' only),
    promotion + consolidation derivation, coordinator open-threads,
    meta-review conditioning. NOT the killed-branch text."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-O")])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl",
                 [_ledger_created("cl-iter-O", "iter-O")])
    item = _get_item(client, "iter-O")
    means = item["approval_means"]
    assert "lifts this iteration to L5" in means
    assert "workers/evidence_ladder.py" in means
    assert "passes only on verdict 'valid'" in means
    assert "orchestrator/finding_promotion.py" in means
    assert "workers/meta_review.py" in means
    assert "meta-review digest" in means
    assert "settles the historical record" not in means
    # The garbled "— the level promotion eligibility … derive from;"
    # sentence is gone (2026-08-18 rewrite as plain English).
    assert "derive from;" not in means
    assert _FOOTNOTE_ANCHOR in means
    # DOING names the open cluster.
    assert "cluster cl-iter-O" in item["doing"]
    assert "KILLED" not in item["doing"]


# --- VET FIRST probes --------------------------------------------------------

def test_old_redteam_caveat_only_on_rows_predating_the_battery(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        _mem_row("iter-old", ended_at="2026-06-05T20:00:00Z",
                 redteam={"verdict": "fatal_flaw", "critique": "circular"}),
        _mem_row("iter-new", ended_at="2026-08-18T09:00:00Z",
                 redteam={"verdict": "fatal_flaw",
                          "critique": "conflates baseline with cause"}),
    ])
    old = _get_item(client, "iter-old")
    assert any(_CAVEAT_ANCHOR in b for b in old["vet"])
    assert any("6/7 parsed known-good fixtures" in b for b in old["vet"])
    # The caveat leads — it is the most decisive probe on such a row.
    assert _CAVEAT_ANCHOR in old["vet"][0]
    new = _get_item(client, "iter-new")
    assert not any(_CAVEAT_ANCHOR in b for b in new["vet"])
    assert any("redteam: fatal_flaw — conflates baseline with cause" in b
               for b in new["vet"])


def test_pre_debate_era_row_flags_the_missing_skeptic(tmp_path):
    """The iter-2026-06-05-004 shape: no critique.debate, no skeptic_verdict
    -> the human's read is the only adversarial pass, and the card says so."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-P", critique={"verdict": "survives"})])
    vet = _get_item(client, "iter-P")["vet"]
    assert any(_PRE_DEBATE_ANCHOR in b for b in vet)
    assert any("your read is the ONLY adversarial pass" in b for b in vet)


def test_debate_probe_names_rounds_and_verdict(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-D", critique={
                     "verdict": "survives",
                     "debate": {"verdict": "refuted", "rounds": 2,
                                "stop_reason": "defender_conceded"}})])
    vet = _get_item(client, "iter-D")["vet"]
    assert any("challenger's strongest round 2 attack" in b for b in vet)
    assert any("(verdict: refuted)" in b for b in vet)
    assert not any(_PRE_DEBATE_ANCHOR in b for b in vet)


def test_skeptic_verdict_named_when_no_debate(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-S", critique={
                     "verdict": "survives",
                     "skeptic_verdict": "survives_attack"})])
    vet = _get_item(client, "iter-S")["vet"]
    assert any("independent skeptic verdict: survives_attack" in b for b in vet)
    assert not any(_PRE_DEBATE_ANCHOR in b for b in vet)


def test_low_confidence_retrieval_probe_carries_the_reason(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-R", retrieval={
                     "relevance": {"low_confidence": True,
                                   "reason": "off-domain hypothesis"},
                     "neighbors": [{"doc_id": "camerer_bgt-chunk-39",
                                    "score": 0.5335,
                                    "title": "(OCR full document)"}]})])
    vet = _get_item(client, "iter-R")["vet"]
    assert any("retrieval was thin/off-topic (reason: off-domain hypothesis)"
               in b for b in vet)
    assert any("top retrieval neighbor camerer_bgt-chunk-39" in b
               and "0.5335" in b for b in vet)
    assert any("not a restatement" in b for b in vet)


def test_experiment_probe_points_at_the_locked_rule(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-E")])
    vet = _get_item(client, "iter-E")["vet"]
    assert any("does vcg_truthful_fraction=0.965 actually discriminate" in b
               for b in vet)
    assert any("experiments/exp004/results/summary.json" in b for b in vet)


def test_ledger_sibling_is_named(tmp_path):
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-A")])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-A", "iter-A"),
        _ledger_added("cl-iter-A", "iter-B"),
    ])
    vet = _get_item(client, "iter-A")["vet"]
    assert any("cluster cl-iter-A also holds iter-B" in b for b in vet)


def test_probes_capped_at_five(tmp_path):
    """A row with every fact present still renders at most 5 probes."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        _mem_row("iter-F",
                 redteam={"verdict": "fatal_flaw", "critique": "c"},
                 novelty={"class": "unclear", "rationale": "r"},
                 critique={"verdict": "survives"},
                 retrieval={
                     "relevance": {"low_confidence": True, "reason": "thin"},
                     "neighbors": [{"doc_id": "doc-1", "score": 0.5}]}),
    ])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-F", "iter-F"),
        _ledger_added("cl-iter-F", "iter-G"),
    ])
    vet = _get_item(client, "iter-F")["vet"]
    assert len(vet) == 5


# --- absent facts fabricate NOTHING ----------------------------------------

def test_absent_facts_produce_no_fabricated_text(tmp_path):
    """A minimal pending row (bare experiment_outcome, no hypothesis, no
    redteam/critique/retrieval/novelty, no ledger) gets ONLY the sentences
    its record supports — nothing invented."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [{
        "iteration_id": "iter-bare",
        "gate_status": "pending",
        "ended_at": "2026-08-01T00:00:00Z",
        "experiment_outcome": {"experiment_id": "exp-x"},  # no metric/value
    }])
    item = _get_item(client, "iter-bare")
    doing = item["doing"]
    assert doing == ("You are judging whether this finished iteration's "
                     "record is sound.")
    assert "hypothesis" not in doing
    assert "measured" not in doing
    assert "cluster" not in doing
    # No kill claims without a ledger; the open-branch consequences stand.
    means = item["approval_means"]
    assert "KILLED" not in means
    assert "reopen" not in means
    # The only honest probe left: nothing adversarial ever saw this row.
    assert item["vet"] == [
        "pre-debate-era row: no independent skeptic ever saw this — "
        "your read is the ONLY adversarial pass"
    ]
    joined = " ".join(item["vet"])
    for fabricated in ("redteam", "retrieval", "novelty", "discriminate",
                       "neighbor", "cluster"):
        assert fabricated not in joined


def test_undated_fatal_flaw_row_still_gets_the_old_redteam_caveat(tmp_path):
    """2026-08-18 fix: a legacy row with NO usable date (no ended_at, no
    started_at) used to lose the old-redteam caveat entirely. The date basis
    now falls back to the ledger kill stamp, and a row with no date anywhere
    FAILS TOWARD SHOWING THE WARNING."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        # (a) undated, no ledger trace at all -> caveat by fail-toward-warning.
        _mem_row("iter-undated", ended_at="",
                 redteam={"verdict": "fatal_flaw", "critique": "c"}),
        # (b) undated, but the cluster kill stamp PREDATES the battery.
        _mem_row("iter-killdate", ended_at="",
                 redteam={"verdict": "fatal_flaw", "critique": "c"}),
        # (c) undated, cluster kill stamp ON/AFTER the battery date -> the
        # new-prompt probe, not the caveat.
        _mem_row("iter-postkill", ended_at="",
                 redteam={"verdict": "fatal_flaw",
                          "critique": "post-battery critique"}),
    ])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-killdate", "iter-killdate"),
        _ledger_killed("cl-iter-killdate", "redteam_fatal_flaw",
                       "iteration:iter-killdate:redteam",
                       ts="2026-08-15T01:14:25Z"),
        _ledger_created("cl-iter-postkill", "iter-postkill"),
        _ledger_killed("cl-iter-postkill", "redteam_fatal_flaw",
                       "iteration:iter-postkill:redteam",
                       ts="2026-08-18T09:00:00Z"),
    ])
    undated = _get_item(client, "iter-undated")["vet"]
    assert any(_CAVEAT_ANCHOR in b for b in undated)
    killdated = _get_item(client, "iter-killdate")["vet"]
    assert any(_CAVEAT_ANCHOR in b for b in killdated)
    post = _get_item(client, "iter-postkill")["vet"]
    assert not any(_CAVEAT_ANCHOR in b for b in post)
    assert any("redteam: fatal_flaw — post-battery critique" in b for b in post)


def test_self_citation_is_segment_exact_never_substring(tmp_path):
    """2026-08-18 fix: the close-out sentence keyed on `iid in evidence_key`
    (substring), so a superseded_duplicate kill with evidence_key
    'cluster:cl-<iid>' false-positively read as self-cited. The match is now
    an exact ':'-segment test — a duplicate-supersession kill is NOT this
    iteration's own consumed result."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl", [
        _mem_row("iter-DUP", experiment_outcome={
            "experiment_id": "exp-dup", "metric": "m", "value": 0.0,
            "trials": 3, "summary": "x"}),
    ])
    # experiment_null_effect kill whose evidence_key embeds the iteration id
    # only as a SUBSTRING of another segment (cluster:cl-iter-DUP).
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-DUP", "iter-DUP"),
        _ledger_killed("cl-iter-DUP", "experiment_null_effect",
                       "cluster:cl-iter-DUP"),
    ])
    means = _get_item(client, "iter-DUP")["approval_means"]
    assert "record-keeping close-out" not in means
    # An exact segment still triggers the close-out (control).
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-DUP", "iter-DUP"),
        _ledger_killed("cl-iter-DUP", "experiment_null_effect",
                       "iteration:iter-DUP:experiment_outcome"),
    ])
    means = _get_item(client, "iter-DUP")["approval_means"]
    assert "record-keeping close-out" in means


def test_raw_fallback_honors_cluster_reopened(tmp_path):
    """A schema-invalid ledger (reducer refuses -> tolerant raw scan) whose
    cluster was killed THEN reopened must read as live: the raw scan clears
    the kill on cluster_reopened exactly like the reducer (2026-08-18 fix —
    the docstring claim that no reopen event exists was false)."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-RO")])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-RO", "member_id": "iter-RO"},  # no origin
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:14:25Z",
         "cluster_id": "cl-iter-RO",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-RO:redteam",
                         "detail": "fatal"}},
        {"event_type": "cluster_reopened", "ts": "2026-08-16T00:00:00Z",
         "cluster_id": "cl-iter-RO",
         "evidence": {"evidence_kind": "redteam_proceed_on_revision"}},
    ])
    item = _get_item(client, "iter-RO")
    assert item["triage"] == "valid"  # owe_triage scan honors the reopen
    means = item["approval_means"]
    assert "already KILLED" not in means
    assert "lifts this iteration to L5" in means
    assert "KILLED" not in item["doing"]


def test_ledger_reduction_memoized_on_mtime_and_size(tmp_path):
    """B1 perf pin (2026-08-18): _ledger_clusters re-derives the reduction
    ONLY when the ledger file changes on disk — a warm call returns the
    cached tuple object; an appended event invalidates the memo."""
    from backend import human_todo

    memory = tmp_path / "coord_memory"
    _write_jsonl(memory / "idea_ledger.jsonl",
                 [_ledger_created("cl-iter-M", "iter-M")])
    first = human_todo._ledger_clusters(memory)
    warm = human_todo._ledger_clusters(memory)
    assert warm is first  # memo hit: no re-read, no re-reduce
    assert first[0]["iter-M"] == "cl-iter-M"
    # The file changes (append a kill): the memo must miss and re-derive.
    _write_jsonl(memory / "idea_ledger.jsonl", [
        _ledger_created("cl-iter-M", "iter-M"),
        _ledger_killed("cl-iter-M", "redteam_fatal_flaw",
                       "iteration:iter-M:redteam"),
    ])
    fresh = human_todo._ledger_clusters(memory)
    assert fresh is not first
    assert fresh[1]["cl-iter-M"]["killed"] is True


def test_schema_invalid_ledger_falls_back_to_raw_scan(tmp_path):
    """A ledger the strict reducer rejects (cluster_created missing origin)
    still yields honest kill facts via the tolerant raw scan — and never
    500s the endpoint."""
    client = _client(tmp_path)
    _write_jsonl(tmp_path / "coord_memory" / "loop_memory.jsonl",
                 [_mem_row("iter-K")])
    _write_jsonl(tmp_path / "coord_memory" / "idea_ledger.jsonl", [
        {"event_type": "cluster_created", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-K", "member_id": "iter-K"},  # no origin
        {"event_type": "cluster_killed", "ts": "2026-08-15T01:00:00Z",
         "cluster_id": "cl-iter-K",
         "kill_reason": {"code": "redteam_fatal_flaw",
                         "evidence_key": "iteration:iter-K:redteam",
                         "detail": "fatal"}},  # no reopening_condition
    ])
    resp = client.get("/api/human_todo")
    assert resp.status_code == 200
    item = {i["id"]: i for i in resp.json()["items"]}["iter-K"]
    means = item["approval_means"]
    assert "already KILLED (redteam_fatal_flaw, 2026-08-15)" in means
    # The reopening kind is unknown to the raw scan here — stated generically,
    # never invented.
    assert "reopening needs new evidence per the ledger's reopening_condition" in means
