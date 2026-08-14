"""Tests for orchestrator.frontier_agenda + cron/weekly-frontier-agenda.sh.

Hermetic by construction: the frontier seam is an INJECTED invoke_fn
(signature = agent_wrapper.frontier_cli.invoke_frontier), the agenda path is
injectable (tmp_path), and the cron script is exercised from a COPY inside a
fake tmp_path repo (it resolves REPO_ROOT from its own location) — no
subprocess ever reaches a real CLI, no repo file is touched.

Pinned behaviors:
  - proposal append shape: fa-<sha8> id, proposed_by frontier:<vendor>,
    status proposed, ts present; appended to the agenda file;
  - empty-ledger refusal: honest doc + NO vendor call + [];
  - per-vendor fail-open: one vendor unparseable/erroring -> [] for that
    vendor only, the other's proposals land;
  - accept_proposal flips status via APPEND of a superseding row
    (append-only, last-row-wins; unknown id raises);
  - dry-run writes nothing;
  - cron script refuses (exit 0 + REFUSE message) without the
    run_state/frontier_tos_ratified sentinel, and on the pause file.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import frontier_agenda as fa


STATE = {
    "cl-001": {
        "cluster_id": "cl-001",
        "status": "open",
        "evidence_level": "L1",
        "topic": "noise-robust cooperation in iterated games",
        "last_event_ts": "2026-08-01T00:00:00Z",
    },
}


def _proposals_json(n=2, prefix="topic"):
    return json.dumps([
        {"topic": f"{prefix} {i}", "rationale": f"grounded rationale {i}"}
        for i in range(n)
    ])


def make_invoke(responses, calls=None):
    """Canned invoke_fn: `responses` maps vendor -> record | Exception."""
    def invoke(vendor, prompt, *, timeout_s, role, ledger_path=None):
        if calls is not None:
            calls.append((vendor, role, prompt))
        resp = responses[vendor]
        if isinstance(resp, Exception):
            raise resp
        return resp
    return invoke


def _record(text, error=None):
    return {"text": text, "vendor": "x", "cli_version": "test-1.0",
            "duration_ms": 5, "exit_code": 0, "error": error}


def _read_rows(path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


# --- synthesize: append shape ------------------------------------------------

def test_synthesize_appends_proposals_with_pinned_shape(tmp_path):
    agenda = tmp_path / "frontier_agenda.jsonl"
    calls = []
    invoke = make_invoke(
        {"claude": _record(_proposals_json(2, "c")),
         "codex": _record(_proposals_json(1, "x"))},
        calls,
    )
    out = fa.synthesize(STATE, invoke, agenda_path=agenda)
    assert len(out) == 3
    rows = _read_rows(agenda)
    assert rows == out
    for row in rows:
        assert row["proposal_id"].startswith("fa-")
        assert len(row["proposal_id"]) == len("fa-") + 8
        assert row["proposed_by"] in ("frontier:claude", "frontier:codex")
        assert row["status"] == "proposed"
        assert row["topic"] and row["rationale"] and row["ts"]
    assert {r["proposed_by"] for r in rows} == {"frontier:claude",
                                                "frontier:codex"}
    # both vendors were called with the projection in the prompt
    assert [c[0] for c in calls] == ["claude", "codex"]
    assert all("## Live work" in c[2] and c[1] == fa.ROLE for c in calls)


def test_synthesize_idempotent_across_identical_runs(tmp_path):
    """2026-08-14 review: proposal_id is ts-free by design, so an unchanged
    projection re-run must SKIP already-agenda'd ids (append-only still — no
    rewrite; just zero new rows), not accumulate duplicate `proposed` rows."""
    agenda = tmp_path / "frontier_agenda.jsonl"
    invoke = make_invoke({"claude": _record(_proposals_json(1)),
                          "codex": _record("not json")})
    first = fa.synthesize(STATE, invoke, agenda_path=agenda)
    assert len(first) == 1
    second = fa.synthesize(STATE, invoke, agenda_path=agenda)
    assert second == []
    assert len(_read_rows(agenda)) == 1


# --- empty-ledger refusal ----------------------------------------------------

def test_empty_ledger_honest_doc_and_no_vendor_call(tmp_path):
    doc = fa.build_projection({})
    assert "no ledger state" in doc
    agenda = tmp_path / "frontier_agenda.jsonl"
    calls = []
    invoke = make_invoke({}, calls)  # any call would KeyError anyway
    out = fa.synthesize({}, invoke, agenda_path=agenda)
    assert out == []
    assert calls == []              # vendors never called
    assert not agenda.exists()      # nothing written


def test_nonempty_projection_delegates_to_render_ideas_md():
    doc = fa.build_projection(STATE)
    assert doc.startswith("# Ideas")
    assert "noise-robust cooperation" in doc


# --- per-vendor fail-open ----------------------------------------------------

def test_unparseable_vendor_yields_zero_for_that_vendor_only(tmp_path):
    agenda = tmp_path / "frontier_agenda.jsonl"
    invoke = make_invoke({"claude": _record("sorry, no JSON here"),
                          "codex": _record(_proposals_json(2))})
    out = fa.synthesize(STATE, invoke, agenda_path=agenda)
    assert len(out) == 2
    assert all(r["proposed_by"] == "frontier:codex" for r in out)


def test_invoke_error_and_exception_fail_open(tmp_path):
    agenda = tmp_path / "frontier_agenda.jsonl"
    invoke = make_invoke({"claude": _record("", error="timeout after 180s"),
                          "codex": RuntimeError("boom")})
    out = fa.synthesize(STATE, invoke, agenda_path=agenda)
    assert out == []
    assert not agenda.exists()


def test_malformed_items_dropped_not_coerced(tmp_path):
    agenda = tmp_path / "frontier_agenda.jsonl"
    text = json.dumps([
        {"topic": "good", "rationale": "grounded"},
        {"topic": "", "rationale": "missing topic"},
        {"rationale": "no topic key"},
        "not a dict",
    ])
    invoke = make_invoke({"claude": _record(text), "codex": _record("[]")})
    out = fa.synthesize(STATE, invoke, agenda_path=agenda)
    assert len(out) == 1
    assert out[0]["topic"] == "good"


# --- accept_proposal ---------------------------------------------------------

def test_accept_flips_status_via_append(tmp_path):
    agenda = tmp_path / "frontier_agenda.jsonl"
    invoke = make_invoke({"claude": _record(_proposals_json(1)),
                          "codex": _record("[]")})
    (proposal,) = fa.synthesize(STATE, invoke, agenda_path=agenda)
    superseding = fa.accept_proposal(proposal["proposal_id"], agenda)
    assert superseding["status"] == "accepted"
    rows = _read_rows(agenda)
    assert len(rows) == 2                       # append, never rewrite
    assert rows[0]["status"] == "proposed"      # original row intact
    assert rows[1]["status"] == "accepted"
    latest = fa.load_agenda(agenda)[proposal["proposal_id"]]
    assert latest["status"] == "accepted"       # last-row-wins


def test_accept_unknown_id_raises(tmp_path):
    agenda = tmp_path / "frontier_agenda.jsonl"
    with pytest.raises(ValueError, match="fa-deadbeef"):
        fa.accept_proposal("fa-deadbeef", agenda)


# --- dry-run -----------------------------------------------------------------

def test_dry_run_writes_nothing(tmp_path):
    agenda = tmp_path / "frontier_agenda.jsonl"
    invoke = make_invoke({"claude": _record(_proposals_json(2)),
                          "codex": _record(_proposals_json(1))})
    out = fa.synthesize(STATE, invoke, agenda_path=agenda, dry_run=True)
    assert len(out) == 3            # proposals still computed and returned
    assert not agenda.exists()      # but nothing written


# --- cron script gates (subprocess on a copy in a fake tmp repo) -------------

def _fake_repo(tmp_path):
    """Copy the script into a fake repo so its self-resolved REPO_ROOT is
    tmp_path — the real repo's run_state/ and logs/ are never touched."""
    for d in ("cron", "run_state", "logs"):
        (tmp_path / d).mkdir()
    script = tmp_path / "cron" / "weekly-frontier-agenda.sh"
    shutil.copy(REPO_ROOT / "cron" / "weekly-frontier-agenda.sh", script)
    script.chmod(0o755)
    return script


def test_cron_refuses_without_tos_sentinel(tmp_path):
    script = _fake_repo(tmp_path)
    proc = subprocess.run(["bash", str(script)], capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0     # designed dark state, not an error
    log_text = (tmp_path / "logs" / "frontier-cron.log").read_text()
    assert "REFUSE" in log_text
    assert "frontier_tos_ratified" in log_text


def test_cron_refuses_on_pause_file(tmp_path):
    script = _fake_repo(tmp_path)
    (tmp_path / "run_state" / "frontier_tos_ratified").touch()
    (tmp_path / "run_state" / "pause_frontier").touch()
    proc = subprocess.run(["bash", str(script)], capture_output=True,
                          text=True, timeout=30)
    assert proc.returncode == 0
    log_text = (tmp_path / "logs" / "frontier-cron.log").read_text()
    assert "REFUSE" in log_text
    assert "pause_frontier" in log_text
