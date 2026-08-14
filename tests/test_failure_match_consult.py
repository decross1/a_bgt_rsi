"""LOOP_V1 P3 (D-060): the nara-side negative-memory consult.

Pins the spine seam the 2026-08-14 review flagged as untested:
`orchestrator.nara._failure_match_consult` — the mandatory adopt-or-reject
against killed clusters / paper niches after hypothesize lands.

Hermetic: nara.DEFAULT_IDEA_LEDGER is conftest-patched to tmp_path; the
runtime is a fake carrying only dispatch_tool + log_event; iteration_cache
is redirected by the repo-wide fixture. MOCK_LLM=1.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator import nara
from workers.idea_ledger import append_event


class _FakeRuntime:
    def __init__(self, retry_result=None):
        self.events = []
        self.dispatched = []
        self._retry_result = retry_result

    def log_event(self, ev):
        self.events.append(ev)

    def dispatch_tool(self, name, args, parent_request_id=None):
        self.dispatched.append((name, args))
        if self._retry_result is None:
            return {"status": "error", "result": None, "errors": ["down"]}
        return self._retry_result


def _seed_killed_cluster(topic_text: str):
    """A killed cluster whose member text matches the hypothesis lexically."""
    lp = nara.DEFAULT_IDEA_LEDGER
    ts = "2026-08-14T00:00:00Z"
    append_event(lp, {"event_type": "cluster_created", "ts": ts,
                      "cluster_id": "cl-k1", "member_id": "iter-old-001",
                      "origin": "consolidation",
                      "claim": {"problem": topic_text, "mechanism": topic_text,
                                "predicted_effect": topic_text}})
    append_event(lp, {"event_type": "cluster_killed", "ts": ts,
                      "cluster_id": "cl-k1",
                      "kill_reason": {"code": "redteam_fatal_flaw",
                                      "evidence_key": "iteration:iter-old-001:redteam",
                                      "detail": "circular derivation"},
                      "reopening_condition": {"requires": "new_evidence",
                                              "evidence_kind": "articulated_delta"}})


HYP = ("Conditional cooperators using Bayesian belief updating exhibit faster "
       "contribution decay under noisy observation in repeated public goods games.")


def test_no_ledger_is_none():
    rt = _FakeRuntime()
    captured = {"hypothesis": {"text": HYP}}
    assert nara._failure_match_consult(rt, captured, "iter-t-001", "topic", None) is None
    assert rt.dispatched == []


def test_match_with_successful_retry_adopts():
    _seed_killed_cluster(HYP)
    revised = {"status": "passed",
               "result": {"text": "A materially different mechanism: reputation "
                                  "spillover under partner choice.",
                          "candidates_considered": 1}}
    rt = _FakeRuntime(retry_result=revised)
    captured = {"hypothesis": {"text": HYP}}
    block = nara._failure_match_consult(rt, captured, "iter-t-002", "topic", None)
    assert block is not None
    assert block["resolution"] == "adopt"
    assert block["matched_cluster_id"] == "cl-k1"
    assert block["kill_reason"] == "redteam_fatal_flaw"
    # The hypothesis was revised away from the dead ground.
    assert captured["hypothesis"]["text"].startswith("A materially different")
    # The consult is a logged, auditable event (never silent).
    assert any(e.get("event_type") == "loop_v0_failure_match" for e in rt.events)
    assert rt.dispatched and rt.dispatched[0][0] == "hypothesize"


def test_match_with_failed_retry_rejects_and_keeps_hypothesis():
    _seed_killed_cluster(HYP)
    rt = _FakeRuntime(retry_result=None)  # re-hypothesize worker down
    captured = {"hypothesis": {"text": HYP}}
    block = nara._failure_match_consult(rt, captured, "iter-t-003", "topic", None)
    assert block is not None
    assert block["resolution"] == "reject"
    assert captured["hypothesis"]["text"] == HYP  # kept; the chain proceeds
