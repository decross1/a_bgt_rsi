"""Frontier-reviews SUBSTANCE endpoint tests (backend/frontier_reviews.py).

The owner rejected the invocation-only panel (2026-08-18): "i can't even
see what their debating issue was". These pins hold the replacement to the
substance:

1. the feed MERGES screen + agenda + refine events newest-first;
2. screen events carry each role's FULL reasoning text plus the D-061
   cross-run summary line when the vetoing role re-ran on the other vendor;
3. the claim_head is JOINED from the idea-ledger reduction (the real
   reducer, ladder.py's lazy-import path), truncated ~140 chars — and
   OMITTED (not fabricated, not null-stuffed) when the cluster carries no
   claim;
4. exit codes DECODE: the real 2026-08-18T06:00:43Z outage (claude exit 1
   + codex exit 127) reads as legible per-vendor lines, -1/124 as a
   timeout;
5. tail reads are BOUNDED and say so (windows.*.truncated);
6. absent files / an unreadable idea ledger degrade honestly — reported,
   never a 500, never silently coerced (rule 4);
7. the TTL cache is real (clock-injected) and `limit` never busts it.

Each test builds its own FastAPI app with register(app, <tmp paths>);
repo_root stays the REAL repo so the refine/claim join runs the REAL
workers.idea_ledger reducer over fixture events (test_ladder.py idiom).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.frontier_reviews import decode_exit, register

# ui/backend/tests/... -> parents[3] == the repo root (carries workers/).
REPO_ROOT = Path(__file__).resolve().parents[3]


# ─── fixtures ─────────────────────────────────────────────────────────

def _iso(minutes_ago: float = 0.0) -> str:
    instant = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return instant.isoformat().replace("+00:00", "Z")


METHODS_REASONING = (
    "The record contains no experiment at all, yet the claim asserts a "
    "specific causal mechanism; discriminating the two mechanisms requires "
    "an ablation varying history length while holding context size fixed."
)
NOVELTY_REASONING = (
    "Fontana, Pierri, and Aiello directly varied the gameplay-history "
    "window in an LLM iterated Prisoner's Dilemma; the candidate's precise "
    "mechanism is not established against an instruction-following control."
)


def _screen_row(ts: str, cluster_id: str = "cl-x", *, cross_run: bool = False,
                verdict: str = "veto") -> dict:
    methods = {"verdict": "veto", "reasoning": METHODS_REASONING,
               "closest_prior_work": "Axelrod 1984", "role": "methods_reviewer",
               "vendor": "claude", "parse_ok": True}
    if cross_run:
        methods["cross_run"] = {
            "verdict": "inconclusive", "reasoning": "cross-run reasoning",
            "closest_prior_work": "Axelrod 1984", "role": "methods_reviewer",
            "vendor": "codex", "parse_ok": True}
    return {"ts": ts, "cluster_id": cluster_id, "evidence_level": "L0",
            "screen": {"verdict": verdict, "escalated": False,
                       "methods": methods,
                       "novelty": {"verdict": "pass",
                                   "reasoning": NOVELTY_REASONING,
                                   "closest_prior_work": "Fontana et al.",
                                   "role": "novelty_reviewer",
                                   "vendor": "codex", "parse_ok": True}},
            "seconds": 49.7}


def _agenda_row(ts: str, n: int = 1) -> dict:
    return {"proposal_id": f"fa-{n:08d}", "proposed_by": "frontier:claude",
            "topic": f"topic {n}", "rationale": f"rationale {n}",
            "status": "proposed", "ts": ts}


def _calls_row(ts: str, *, vendor: str = "claude", exit_code: int = 0,
               role: str = "methods_reviewer") -> dict:
    return {"timestamp": ts, "vendor": vendor, "cli_version": "x",
            "role": role, "verdict": None, "duration_ms": 5,
            "exit_code": exit_code, "prompt_sha256": "ab" * 32}


LONG_PROBLEM = ("does longer payoff memory rather than improved instruction "
                "following drive cooperation gains in iterated games with "
                "large context windows and matched prompt composition, "
                "controlling for distractor padding")  # > 140 chars


def _ledger_events(cluster_id: str = "cl-x") -> list[dict]:
    """Schema-valid idea-ledger events: one cluster WITH a claim + one
    refine round, one cluster WITHOUT any claim text."""
    return [
        {"event_type": "cluster_created", "ts": "2026-08-01T00:00:00Z",
         "cluster_id": cluster_id, "member_id": "iter-001",
         "origin": "consolidation", "iteration_id": "iter-001",
         "claim": {"problem": LONG_PROBLEM, "mechanism": "m",
                   "predicted_effect": "p"}},
        {"event_type": "cluster_created", "ts": "2026-08-01T01:00:00Z",
         "cluster_id": "cl-bare", "member_id": "iter-002",
         "origin": "consolidation"},
    ]


def _refine_event(ts: str, cluster_id: str = "cl-x", round_: int = 1) -> dict:
    return {"event_type": "cluster_refined", "ts": ts,
            "cluster_id": cluster_id, "round": round_,
            "refined_claim": "refined: " + LONG_PROBLEM,
            "feedback_digest": "methods[veto]: confounded || novelty[pass]"}


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")


class _StubRunner:
    """Injected in place of ``subprocess.run`` (test_todo_cockpit.py's stub,
    verbatim idiom): records every blessed-exec argv and returns a canned
    result. NEVER spawns a process — no real CLI, no real ledger write."""

    def __init__(self, stdout: str = '{"ok": true}', returncode: int = 0,
                 stderr: str = ""):
        self.calls: list[dict] = []
        self._stdout = stdout
        self._returncode = returncode
        self._stderr = stderr

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": kwargs})

        class _Proc:
            returncode = self._returncode
            stdout = self._stdout
            stderr = self._stderr
        return _Proc()

    @property
    def last_argv(self) -> list[str]:
        assert self.calls, "no blessed exec was attempted"
        return self.calls[-1]["argv"]


def _client(tmp_path, *, screen=None, agenda=None, calls=None, ledger=None,
            status=None, **kwargs) -> TestClient:
    """App with every source pinned under tmp_path; sources given as row
    lists are written, None leaves the file ABSENT."""
    paths = {}
    for name, rows in (("screen", screen), ("agenda", agenda),
                       ("calls", calls), ("ledger", ledger),
                       ("status", status)):
        paths[name] = tmp_path / f"{name}.jsonl"
        if rows is not None:
            _write(paths[name], rows)
    app = FastAPI()
    # loop_memory pinned under tmp (ABSENT unless a test writes it) so the
    # founding-hypothesis fallback can never leak into the real checkout.
    kwargs.setdefault("loop_memory_path", tmp_path / "loop_memory.jsonl")
    kwargs.setdefault("repo_root", REPO_ROOT)
    register(app, screen_path=paths["screen"], agenda_path=paths["agenda"],
             agenda_status_path=paths["status"], calls_path=paths["calls"],
             idea_ledger_path=paths["ledger"], **kwargs)
    return TestClient(app)


# ─── merge order across the three sources ─────────────────────────────

def test_feed_merges_all_three_sources_newest_first(tmp_path):
    client = _client(
        tmp_path,
        screen=[_screen_row(_iso(40), "cl-x"), _screen_row(_iso(5), "cl-bare")],
        agenda=[_agenda_row(_iso(30))],
        ledger=_ledger_events() + [_refine_event(_iso(10))],
        calls=[],
    )
    body = client.get("/api/frontier_reviews").json()
    assert [e["type"] for e in body["events"]] == [
        "screen", "refine", "agenda", "screen"]
    assert body["events_in_window"] == 4
    assert body["available"] == {"screen": True, "agenda": True, "calls": True}


# ─── screen substance: full reasoning + cross-run summary ─────────────

def test_screen_event_carries_full_reasoning_and_cross_run(tmp_path):
    client = _client(tmp_path, screen=[_screen_row(_iso(1), cross_run=True)],
                     agenda=None, calls=None, ledger=None)
    body = client.get("/api/frontier_reviews").json()
    [event] = body["events"]
    assert event["type"] == "screen"
    assert event["cluster_id"] == "cl-x"
    assert event["verdict"] == "veto"
    assert event["evidence_level"] == "L0"
    # FULL reasoning text, both roles — the substance, verbatim.
    assert event["roles"]["methods"]["reasoning"] == METHODS_REASONING
    assert event["roles"]["novelty"]["reasoning"] == NOVELTY_REASONING
    assert event["roles"]["methods"]["verdict"] == "veto"
    assert event["roles"]["novelty"]["verdict"] == "pass"
    # D-061 cross-run: the vetoing role re-ran on the other vendor.
    assert event["cross_run_summary"] == (
        "the vetoing methods reviewer re-ran on codex: inconclusive")
    assert event["roles"]["methods"]["cross_run"]["verdict"] == "inconclusive"


def test_no_cross_run_means_no_summary_key(tmp_path):
    client = _client(tmp_path, screen=[_screen_row(_iso(1), cross_run=False)],
                     agenda=None, calls=None, ledger=None)
    [event] = client.get("/api/frontier_reviews").json()["events"]
    assert "cross_run_summary" not in event
    assert "cross_run" not in event["roles"]["methods"]


# ─── the claim-head join (present, truncated) and the omission ────────

def test_claim_head_joined_from_ledger_and_truncated(tmp_path):
    client = _client(tmp_path, screen=[_screen_row(_iso(1), "cl-x")],
                     agenda=None, calls=None, ledger=_ledger_events())
    [event] = client.get("/api/frontier_reviews").json()["events"]
    head = event["claim_head"]
    assert head.startswith("does longer payoff memory")
    assert len(head) <= 141  # 140 + the truncation mark
    assert head.endswith("…")
    assert client.get("/api/frontier_reviews").json()["ledger_join"]["ok"]


def test_claim_head_omitted_when_cluster_has_no_claim(tmp_path):
    # cl-bare exists in the ledger but carries NO claim text; cl-ghost is
    # not in the ledger at all. Both omit the key — never null, never a
    # fabricated head.
    client = _client(
        tmp_path,
        screen=[_screen_row(_iso(2), "cl-bare"), _screen_row(_iso(1), "cl-ghost")],
        agenda=None, calls=None, ledger=_ledger_events())
    events = client.get("/api/frontier_reviews").json()["events"]
    assert all("claim_head" not in e for e in events)


def test_claim_head_falls_back_to_founding_hypothesis(tmp_path):
    # cl-bare carries no claim text; its founding iter-* member's
    # hypothesis text is the honest "what was judged" fallback,
    # source-labelled so ledger-sourced heads stay distinguishable.
    lm = tmp_path / "loop_memory.jsonl"
    _write(lm, [{"iteration_id": "iter-002",
                 "hypothesis": {"text": "founding hypothesis text about "
                                        "payoff memory and collusion"}}])
    client = _client(
        tmp_path,
        screen=[_screen_row(_iso(2), "cl-bare")],
        agenda=None, calls=None, ledger=_ledger_events(),
        loop_memory_path=lm)
    [event] = client.get("/api/frontier_reviews").json()["events"]
    assert event["claim_head"].startswith("founding hypothesis text")
    assert event["claim_head_source"] == "founding_hypothesis"


def test_claim_head_fallback_absent_memory_still_omits(tmp_path):
    # No loop_memory file at all -> keys stay absent (never fabricated).
    client = _client(
        tmp_path,
        screen=[_screen_row(_iso(2), "cl-bare"), _screen_row(_iso(1), "cl-ghost")],
        agenda=None, calls=None, ledger=_ledger_events())
    events = client.get("/api/frontier_reviews").json()["events"]
    assert all("claim_head" not in e for e in events)


# ─── refine + agenda event fields ─────────────────────────────────────

def test_refine_event_fields(tmp_path):
    client = _client(tmp_path, screen=None, agenda=None, calls=None,
                     ledger=_ledger_events() + [_refine_event(_iso(3), round_=2)])
    [event] = client.get("/api/frontier_reviews").json()["events"]
    assert event["type"] == "refine"
    assert event["cluster_id"] == "cl-x"
    assert event["round"] == 2
    assert event["refined_claim_head"].startswith("refined: does longer")
    assert len(event["refined_claim_head"]) <= 141
    assert event["feedback_digest"].startswith("methods[veto]")


def test_agenda_event_fields(tmp_path):
    client = _client(tmp_path, screen=None, agenda=[_agenda_row(_iso(1), 7)],
                     calls=None, ledger=None)
    [event] = client.get("/api/frontier_reviews").json()["events"]
    # An UNRULED proposal: effective_status falls back to the row's own
    # status and NO ruling block is fabricated.
    assert event == {"type": "agenda", "ts": event["ts"],
                     "proposal_id": "fa-00000007",
                     "proposed_by": "frontier:claude", "topic": "topic 7",
                     "rationale": "rationale 7", "status": "proposed",
                     "effective_status": "proposed"}


# ─── the acceptance step: status join + accept/dismiss exec ───────────

def _status_row(n: int, status: str, note: str = "why", **extra) -> dict:
    return {"proposal_id": f"fa-{n:08d}", "status": status, "ts": _iso(0),
            "note": note, "agent_id": "human:ui", **extra}


def test_effective_status_joins_the_audit_file_last_row_wins(tmp_path):
    client = _client(
        tmp_path, screen=None, calls=None, ledger=None,
        agenda=[_agenda_row(_iso(3), 1), _agenda_row(_iso(2), 2),
                _agenda_row(_iso(1), 3)],
        status=[_status_row(1, "dismissed", "graveyard analysis"),
                _status_row(1, "accepted", "changed my mind",
                            cluster_id="cl-fa-00000001"),
                _status_row(2, "dismissed", "not research")])
    events = {e["proposal_id"]: e
              for e in client.get("/api/frontier_reviews").json()["events"]}
    # last row wins for fa-1; fa-2 dismissed; fa-3 never ruled on.
    assert events["fa-00000001"]["effective_status"] == "accepted"
    assert events["fa-00000001"]["ruling"]["note"] == "changed my mind"
    assert events["fa-00000001"]["ruling"]["cluster_id"] == "cl-fa-00000001"
    assert events["fa-00000002"]["effective_status"] == "dismissed"
    assert events["fa-00000002"]["ruling"]["note"] == "not research"
    assert events["fa-00000003"]["effective_status"] == "proposed"
    assert "ruling" not in events["fa-00000003"]
    # The proposals file itself is untouched — its own status still reads
    # "proposed" alongside the joined effective status (never rewritten).
    assert events["fa-00000001"]["status"] == "proposed"


def test_out_of_enum_audit_status_is_not_believed(tmp_path):
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)],
                     status=[_status_row(1, "accepted"),
                             _status_row(1, "sortof")])
    [event] = client.get("/api/frontier_reviews").json()["events"]
    assert event["effective_status"] == "accepted"


def test_absent_status_file_leaves_every_proposal_proposed(tmp_path):
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], status=None)
    [event] = client.get("/api/frontier_reviews").json()["events"]
    assert event["effective_status"] == "proposed"
    assert "ruling" not in event


def test_agenda_write_capability_reports_the_real_writer(tmp_path):
    # repo_root is the REAL checkout: agenda_cli.py + the interpreter exist.
    body = _client(tmp_path).get("/api/frontier_reviews").json()
    assert body["agenda_write"] == {
        "available": True, "verbs": ["accept", "dismiss"],
        "writer": "orchestrator.agenda_cli"}
    # A checkout WITHOUT the writer reports available:false — never a button
    # that would 502 (the handshake execs nothing to find out).
    bare = _client(tmp_path, repo_root=tmp_path / "bare")
    assert bare.get("/api/frontier_reviews").json()[
        "agenda_write"]["available"] is False


def test_accept_execs_the_blessed_cli_as_an_argv_array(tmp_path):
    runner = _StubRunner('{"proposal_id": "fa-00000001", "status": "accepted"}')
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner)
    resp = client.post("/api/frontier_agenda/accept",
                       json={"proposal_id": "fa-00000001",
                             "note": "the only live experiments",
                             "topic_override": "narrower topic"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    argv = runner.last_argv
    assert isinstance(argv, list)                      # ARRAY, never a string
    assert argv[1] == "-m" and argv[2] == "orchestrator.agenda_cli"
    assert argv[3:] == ["accept", "--proposal-id", "fa-00000001",
                        "--note", "the only live experiments",
                        "--by", "human:ui",
                        "--topic-override", "narrower topic"]
    assert runner.calls[-1]["kwargs"].get("shell") in (None, False)


def test_dismiss_execs_the_dismiss_verb_and_omits_topic_override(tmp_path):
    runner = _StubRunner('{"proposal_id": "fa-00000001", "status": "dismissed"}')
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner)
    resp = client.post("/api/frontier_agenda/dismiss",
                       json={"proposal_id": "fa-00000001", "note": "no",
                             "topic_override": "ignored"})
    assert resp.status_code == 200
    assert runner.last_argv[3:] == ["dismiss", "--proposal-id", "fa-00000001",
                                    "--note", "no", "--by", "human:ui"]


@pytest.mark.parametrize("proposal_id", [
    "fa-00000001; rm -rf /",      # shell metacharacters
    "fa 00000001",                # a space
    "--proposal-id",              # argv-flag confusion
    "fa/../../etc/passwd",        # traversal
    "", None, 17,
])
def test_hostile_proposal_id_422s_with_no_exec(tmp_path, proposal_id):
    runner = _StubRunner()
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner)
    resp = client.post("/api/frontier_agenda/accept",
                       json={"proposal_id": proposal_id, "note": "n"})
    assert resp.status_code == 422
    assert runner.calls == []                          # nothing ever spawned


@pytest.mark.parametrize("verb", ["accept", "dismiss"])
def test_blank_note_422s_with_no_exec(tmp_path, verb):
    runner = _StubRunner()
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner)
    resp = client.post(f"/api/frontier_agenda/{verb}",
                       json={"proposal_id": "fa-00000001", "note": "  "})
    assert resp.status_code == 422
    assert runner.calls == []


def test_blank_topic_override_422s_with_no_exec(tmp_path):
    runner = _StubRunner()
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner)
    resp = client.post("/api/frontier_agenda/accept",
                       json={"proposal_id": "fa-00000001", "note": "n",
                             "topic_override": "   "})
    assert resp.status_code == 422
    assert runner.calls == []


def test_nonzero_cli_exit_surfaces_stderr_verbatim(tmp_path):
    runner = _StubRunner("", returncode=1,
                         stderr="rejected: proposal fa-1 is already accepted")
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner)
    resp = client.post("/api/frontier_agenda/accept",
                       json={"proposal_id": "fa-00000001", "note": "n"})
    assert resp.status_code == 502
    assert resp.json() == {"rc": 1,
                           "stderr": "rejected: proposal fa-1 is already accepted"}


def test_successful_ruling_drops_the_ttl_cache(tmp_path):
    """A ruling must show up on the NEXT poll, not after the TTL — the owner
    clicking accept and seeing a stale `proposed` card is the bug."""
    fake = {"now": 100.0}
    runner = _StubRunner('{"status": "dismissed"}')
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner,
                     ttl_s=600.0, clock=lambda: fake["now"])
    first = client.get("/api/frontier_reviews").json()["events"][0]
    assert first["effective_status"] == "proposed"
    _write(tmp_path / "status.jsonl", [_status_row(1, "dismissed")])
    client.post("/api/frontier_agenda/dismiss",
                json={"proposal_id": "fa-00000001", "note": "no"})
    again = client.get("/api/frontier_reviews").json()["events"][0]
    assert again["effective_status"] == "dismissed"


def test_failed_ruling_keeps_the_cache(tmp_path):
    fake = {"now": 100.0}
    runner = _StubRunner("", returncode=1, stderr="rejected: nope")
    client = _client(tmp_path, screen=None, calls=None, ledger=None,
                     agenda=[_agenda_row(_iso(1), 1)], runner=runner,
                     ttl_s=600.0, clock=lambda: fake["now"])
    first = client.get("/api/frontier_reviews").json()
    client.post("/api/frontier_agenda/accept",
                json={"proposal_id": "fa-00000001", "note": "n"})
    assert client.get("/api/frontier_reviews").json()["generated_at"] == (
        first["generated_at"])


# ─── health: the decoded outage (the REAL 2026-08-18T06:00:43Z rows) ──

def test_real_outage_rows_decode_per_vendor(tmp_path):
    # The two real failure rows: claude exit 1, codex exit 127 — plus each
    # vendor's earlier clean call, so last_ok is provable.
    client = _client(tmp_path, screen=None, agenda=None, ledger=None, calls=[
        _calls_row(_iso(120), vendor="claude", exit_code=0),
        _calls_row(_iso(119), vendor="codex", exit_code=0),
        _calls_row(_iso(10), vendor="claude", exit_code=1),
        _calls_row(_iso(10), vendor="codex", exit_code=127,
                   role="novelty_reviewer"),
    ])
    health = client.get("/api/frontier_reviews").json()["health"]
    assert health["claude"]["consecutive_failures"] == 1
    assert health["claude"]["last_error"]["exit_code"] == 1
    assert health["claude"]["last_error"]["decoded"] == "CLI error (exit 1)"
    assert health["codex"]["consecutive_failures"] == 1
    assert health["codex"]["last_error"]["decoded"] == (
        "binary not found (PATH)")
    # last_ok is the earlier clean call, ~2h old.
    assert health["claude"]["last_ok_age_s"] > 7000
    assert health["codex"]["calls_24h"] == 2


def test_exit_decode_table():
    assert decode_exit(-1) == "timed out"
    assert decode_exit(124) == "timed out"
    assert decode_exit(127).startswith("binary not found (PATH)")
    assert decode_exit(2) == "CLI error (exit 2)"


def test_vendor_with_no_ok_call_has_null_last_ok(tmp_path):
    client = _client(tmp_path, screen=None, agenda=None, ledger=None, calls=[
        _calls_row(_iso(9), vendor="codex", exit_code=-1),
        _calls_row(_iso(8), vendor="codex", exit_code=-1),
    ])
    health = client.get("/api/frontier_reviews").json()["health"]
    assert health["codex"]["last_ok_ts"] is None
    assert health["codex"]["last_ok_age_s"] is None
    assert health["codex"]["consecutive_failures"] == 2
    assert health["codex"]["last_error"]["decoded"] == "timed out"


# ─── the bounded tail is real ─────────────────────────────────────────

def test_screen_tail_bound_drops_old_rows_and_says_so(tmp_path):
    old = _screen_row(_iso(60), "cl-old")
    new = _screen_row(_iso(1), "cl-new")
    # Window sized to hold roughly one row: the older row falls outside.
    bound = len(json.dumps(new)) + 10
    client = _client(tmp_path, screen=[old, new], agenda=None, calls=None,
                     ledger=None, screen_tail_bytes=bound)
    body = client.get("/api/frontier_reviews").json()
    ids = [e["cluster_id"] for e in body["events"]]
    assert ids == ["cl-new"]
    assert body["windows"]["screen"]["truncated"] is True
    assert body["windows"]["screen"]["bytes"] == bound


# ─── limit + TTL cache ────────────────────────────────────────────────

def test_limit_defaults_to_20_and_events_in_window_counts_all(tmp_path):
    rows = [_agenda_row(_iso(i), i) for i in range(25)]
    client = _client(tmp_path, screen=None, agenda=rows, calls=None,
                     ledger=None)
    body = client.get("/api/frontier_reviews").json()
    assert len(body["events"]) == 20
    assert body["events_in_window"] == 25
    assert len(client.get("/api/frontier_reviews?limit=25").json()["events"]) == 25


def test_ttl_cache_serves_within_ttl_and_recomposes_after(tmp_path):
    fake = {"now": 100.0}
    client = _client(tmp_path, screen=None, agenda=[_agenda_row(_iso(5), 1)],
                     calls=None, ledger=None,
                     ttl_s=5.0, clock=lambda: fake["now"])
    assert client.get("/api/frontier_reviews").json()["events_in_window"] == 1
    # New row lands; within TTL the cached compose still answers.
    _write(tmp_path / "agenda.jsonl",
           [_agenda_row(_iso(5), 1), _agenda_row(_iso(1), 2)])
    fake["now"] = 103.0
    assert client.get("/api/frontier_reviews").json()["events_in_window"] == 1
    # Past TTL the compose re-runs and sees it.
    fake["now"] = 106.0
    assert client.get("/api/frontier_reviews").json()["events_in_window"] == 2


def test_limit_never_busts_the_cache(tmp_path):
    fake = {"now": 100.0}
    client = _client(tmp_path, screen=None,
                     agenda=[_agenda_row(_iso(i), i) for i in range(5)],
                     calls=None, ledger=None,
                     ttl_s=60.0, clock=lambda: fake["now"])
    first = client.get("/api/frontier_reviews?limit=2").json()
    second = client.get("/api/frontier_reviews?limit=4").json()
    assert len(first["events"]) == 2
    assert len(second["events"]) == 4
    # Same compose (cache hit): identical generated_at.
    assert first["generated_at"] == second["generated_at"]


# ─── honest degradation ───────────────────────────────────────────────

def test_all_sources_absent_degrades_honestly(tmp_path):
    client = _client(tmp_path)  # nothing written
    resp = client.get("/api/frontier_reviews")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] == {"screen": False, "agenda": False,
                                 "calls": False}
    assert body["events"] == []
    assert body["health"] == {}
    assert body["ledger_join"]["ok"] is True  # absent ledger = cold checkout


def test_unreadable_idea_ledger_is_reported_not_coerced(tmp_path):
    (tmp_path / "ledger.jsonl").write_text("{not json\n", encoding="utf-8")
    client = _client(tmp_path, screen=[_screen_row(_iso(1), "cl-x")],
                     agenda=None, calls=None, ledger=None)
    body = client.get("/api/frontier_reviews").json()
    # The screen feed still serves; the join failure is NAMED on the wire.
    assert body["ledger_join"]["ok"] is False
    assert "idea_ledger" in body["ledger_join"]["error"]
    [event] = body["events"]
    assert event["type"] == "screen"
    assert "claim_head" not in event
