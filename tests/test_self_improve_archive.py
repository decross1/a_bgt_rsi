"""Synthetic fault histories only; never live dispatch or release."""
from copy import deepcopy

import pytest

from bench.self_improve_archive.simulator import (
    Quarantined, Simulator, rollback_requirement, synthetic_score,
)
from workers.claim_binding import BindingError, canonical_bytes, digest, load_json

BASE = "sha256:" + "1" * 64
CMD = "sha256:" + "2" * 64


def packet(task_id="p", base=BASE, rollback="code"):
    return dict(task_id=task_id, source_id="intake-row-1", base_sha256=base,
                base_release_generation=0, test_command_sha256=CMD,
                budget_units=10, rollback_class=rollback)


def restore(lines):
    return Simulator.from_lines(lines, expected_history_sha256=Simulator.history_sha256(lines))


def send(sim, kind, at=0, **kwargs):
    return sim.submit(dict(kind=kind, at=at, **kwargs), expected_sequence=sim.sequence)


def claimed(rollback="code"):
    sim = Simulator(BASE)
    send(sim, "admit", packet=packet(rollback=rollback))
    send(sim, "claim", task_id="p", owner="worker-a", lease_units=10)
    return sim


def result(sim, task_id="p", outcome="candidate", patch="synthetic patch"):
    task = sim.view()["tasks"][task_id]
    return dict(outcome=outcome, attempt_id=task["attempt_id"],
                contract_sha256=task["contract_sha256"], cost_units=11 if outcome == "over_budget" else 3,
                patch=patch if outcome == "candidate" else None,
                score=synthetic_score(patch) if outcome == "candidate" else None,
                verifier_id="verifier" if outcome == "candidate" else None,
                reason_sha256=None if outcome == "candidate" else CMD)


def finish(sim, task_id="p", outcome="candidate", at=1, patch="synthetic patch"):
    t = sim.view()["tasks"][task_id]
    return send(sim, "finish", at=at, task_id=task_id, owner=t["owner"], generation=t["generation"],
                result=result(sim, task_id, outcome, patch))


def test_admission_binds_bytes_source_and_is_idempotent():
    sim = Simulator(BASE)
    p = packet()
    token = send(sim, "admit", packet=p)
    history = sim.export()
    assert send(sim, "admit", packet=deepcopy(p)) == token
    assert sim.export() == history
    p["source_id"] = "different-source"
    with pytest.raises(BindingError, match="changed contract"):
        send(sim, "admit", packet=p)
    assert sim.view()["tasks"]["p"]["packet"]["source_id"] == "intake-row-1"


@pytest.mark.parametrize("payload", [{}, {"task_id": "p"}, {"status": "enqueued"}])
def test_incomplete_intake_never_becomes_dispatchable(payload):
    sim = Simulator(BASE)
    with pytest.raises(BindingError):
        send(sim, "admit", packet=payload)
    assert sim.sequence == 0 and not sim.view()["tasks"]


def test_two_same_sequence_claims_have_only_one_winner_in_serialized_model():
    sim = Simulator(BASE)
    send(sim, "admit", packet=packet())
    seq = sim.sequence
    first = dict(kind="claim", at=0, task_id="p", owner="a", lease_units=5)
    second = dict(first, owner="b")
    sim.submit(first, expected_sequence=seq)
    with pytest.raises(BindingError, match="compare-and-swap"):
        sim.submit(second, expected_sequence=seq)
    with pytest.raises(BindingError, match="already leased"):
        sim.submit(second, expected_sequence=sim.sequence)
    assert sim.view()["tasks"]["p"]["owner"] == "a"


def test_worker_crash_expiry_reclaim_fences_old_attempt_and_late_receipt():
    sim = claimed()
    old_result = result(sim)
    send(sim, "claim", at=10, task_id="p", owner="worker-b", lease_units=5)
    task = sim.view()["tasks"]["p"]
    assert task["generation"] == 2 and task["attempt_id"] != old_result["attempt_id"]
    with pytest.raises(BindingError, match="stale or foreign"):
        send(sim, "finish", at=11, task_id="p", owner="worker-a", generation=1, result=old_result)
    with pytest.raises(BindingError, match="exact attempt"):
        send(sim, "finish", at=11, task_id="p", owner="worker-b", generation=2, result=old_result)
    assert sim.view()["champion"] == BASE
    finish(sim, at=11)


def test_disconnected_controller_replays_and_expired_heartbeat_cannot_resurrect():
    sim = restore(claimed().export())
    with pytest.raises(BindingError, match="unexpired"):
        send(sim, "heartbeat", at=10, task_id="p", owner="worker-a", generation=1, lease_units=5)
    send(sim, "claim", at=10, task_id="p", owner="new-worker", lease_units=5)
    assert sim.view()["tasks"]["p"]["generation"] == 2


def test_valid_heartbeat_extends_but_wrong_owner_and_nonextension_refuse():
    sim = claimed()
    for owner, at, lease in [("other", 1, 20), ("worker-a", 1, 1)]:
        with pytest.raises(BindingError):
            send(sim, "heartbeat", at=at, task_id="p", owner=owner, generation=1, lease_units=lease)
    send(sim, "heartbeat", at=1, task_id="p", owner="worker-a", generation=1, lease_units=20)
    assert sim.view()["tasks"]["p"]["expires_at"] == 21


def test_duplicate_terminal_ack_has_one_archive_entry_and_cannot_redispatch():
    sim = claimed()
    r = result(sim)
    archive_id = send(sim, "finish", at=1, task_id="p", owner="worker-a", generation=1, result=r)
    seq = sim.sequence
    assert send(sim, "finish", at=20, task_id="p", owner="worker-a", generation=1, result=r) == archive_id
    assert sim.sequence == seq and len(sim.view()["archive"]) == 1
    with pytest.raises(BindingError, match="terminal"):
        send(sim, "claim", at=21, task_id="p", owner="b", lease_units=5)
    r["score"] += 1
    with pytest.raises(BindingError, match="conflicting terminal"):
        send(sim, "finish", at=21, task_id="p", owner="worker-a", generation=1, result=r)


@pytest.mark.parametrize("outcome", ["candidate", "failed", "evaluator_outage", "over_budget"])
def test_terminal_archive_is_inert_and_preserves_negative_evidence(outcome):
    sim = claimed()
    archive_id = finish(sim, outcome=outcome)
    state = sim.view()
    entry = state["archive"][archive_id]
    assert digest(canonical_bytes(entry)) == archive_id
    assert entry["inert"] is True and entry["authority"] == "none"
    assert entry["result"]["outcome"] == outcome
    assert state["champion"] == BASE and state["release_generation"] == 0
    if outcome != "candidate":
        with pytest.raises(BindingError):
            send(sim, "simulate_release", at=2, archive_id=archive_id, expected_release_generation=0)


@pytest.mark.parametrize("field,value", [
    ("score", -1), ("patch", "changed patch"), ("attempt_id", BASE),
    ("contract_sha256", BASE), ("verifier_id", "worker-a"), ("cost_units", 11),
    ("cost_units", True), ("reason_sha256", CMD), ("outcome", "executed"),
])
def test_malformed_or_unbound_success_never_enters_archive(field, value):
    sim = claimed()
    r = result(sim)
    r[field] = value
    with pytest.raises(BindingError):
        send(sim, "finish", at=1, task_id="p", owner="worker-a", generation=1, result=r)
    assert not sim.view()["archive"] and sim.view()["champion"] == BASE


def test_deterministic_replay_and_corrupt_derived_view_rebuild_without_history_edit():
    sim = claimed()
    finish(sim)
    history = sim.export()
    restored = restore(history)
    stale = restored.view()
    stale["tasks"].clear()
    stale["release_generation"] = 99
    assert not restored.legitimate_projection(stale)
    assert restored.legitimate_projection(restored.rebuild_projection())
    assert restored.view() == sim.view() and restored.export() == history
    assert restore(history).export() == history


@pytest.mark.parametrize("fault", ["truncated", "bad_json", "changed", "reordered", "duplicate", "nan", "keys"])
def test_authoritative_corruption_quarantines_instead_of_skipping_or_converging(fault):
    sim = claimed()
    finish(sim)
    history = list(sim.export())
    if fault == "truncated":
        history[-1] = history[-1][:-1]
    elif fault == "bad_json":
        history.insert(2, b"garbage")
    elif fault == "changed":
        event = load_json(history[-1]); event["command"]["result"]["score"] += 1
        history[-1] = canonical_bytes(event)
    elif fault == "reordered":
        history[1], history[2] = history[2], history[1]
    elif fault == "duplicate":
        history.append(history[-1])
    elif fault == "nan":
        history[-1] = b'{"score":NaN}'
    else:
        history[-1] = b'{"sequence":1,"sequence":2}'
    with pytest.raises(Quarantined):
        restore(tuple(history))
    assert sim.sequence == 3  # no mutation of the valid source


def test_release_and_rollback_advance_generation_without_rewinding_history():
    sim = claimed()
    archive_id = finish(sim)
    before = sim.export()
    send(sim, "simulate_release", at=2, archive_id=archive_id, expected_release_generation=0)
    assert sim.view()["release_generation"] == 1
    assert sim.view()["champion"] == digest(b"synthetic patch")
    with pytest.raises(BindingError):
        send(sim, "simulate_code_rollback", at=3, target_sha256=BASE, expected_release_generation=0)
    send(sim, "simulate_code_rollback", at=3, target_sha256=BASE, expected_release_generation=1)
    assert sim.view()["champion"] == BASE and sim.view()["release_generation"] == 2
    assert sim.export()[:len(before)] == before
    assert restore(sim.export()).view() == sim.view()
    with pytest.raises(BindingError, match="stale parent"):
        send(sim, "simulate_release", at=4, archive_id=archive_id, expected_release_generation=2)


def test_complete_row_truncation_is_detected_by_external_snapshot_cursor():
    sim = claimed()
    history = sim.export()
    cursor = Simulator.history_sha256(history)
    with pytest.raises(Quarantined, match="pinned snapshot"):
        Simulator.from_lines(history[:-1], expected_history_sha256=cursor)


@pytest.mark.parametrize("part,change", [
    ("header", "whitespace"), ("header", "key_order"),
    ("empty_header", "whitespace"), ("empty_header", "key_order"),
    ("event", "whitespace"), ("event", "key_order"),
    ("header", "format"), ("header", "root"),
])
def test_authoritative_raw_rows_are_never_silently_canonicalized(part, change):
    import json
    original = Simulator(BASE) if part == "empty_header" else claimed()
    history = list(original.export())
    index = 1 if part == "event" else 0
    value = load_json(history[index])
    if change == "whitespace":
        changed = json.dumps(value, indent=2).encode()
    elif change == "key_order":
        changed = json.dumps(dict(reversed(list(value.items()))), separators=(",", ":")).encode()
    else:
        value["format" if change == "format" else "initial_champion"] = "unsupported-v2" if change == "format" else CMD
        changed = canonical_bytes(value)
    assert changed != history[index]
    history[index] = changed
    # Even a cursor pinned to these altered raw bytes cannot authorize a
    # replay that exports a different history or accepts an invalid chain.
    with pytest.raises(Quarantined):
        restore(tuple(history))
    assert restore(original.export()).export() == original.export()


def test_reusing_archived_descendant_cannot_inherit_stale_evaluation_authority():
    sim = claimed()
    old = finish(sim)
    send(sim, "admit", at=1, packet=packet("second"))
    send(sim, "claim", at=1, task_id="second", owner="b", lease_units=5)
    new = finish(sim, task_id="second", at=2, patch="second synthetic patch")
    send(sim, "simulate_release", at=3, archive_id=new, expected_release_generation=0)
    with pytest.raises(BindingError, match="stale parent"):
        send(sim, "simulate_release", at=4, archive_id=old, expected_release_generation=1)


@pytest.mark.parametrize("kind,requirement", [
    ("state", "durable-state migration"), ("protocol", "mixed-version compatibility"),
    ("effects", "irreversible-effect compensation"),
])
def test_noncode_rollback_never_masquerades_as_code_restore(kind, requirement):
    sim = claimed(rollback=kind)
    archive_id = finish(sim)
    assert requirement in rollback_requirement(kind)
    with pytest.raises(BindingError, match=requirement):
        send(sim, "simulate_release", at=2, archive_id=archive_id, expected_release_generation=0)
    assert sim.view()["champion"] == BASE


def test_revision_requires_new_task_identity_and_new_attempt():
    sim = claimed()
    p = packet(); p["test_command_sha256"] = BASE
    with pytest.raises(BindingError):
        send(sim, "admit", packet=p)
    p["task_id"] = "revision"
    send(sim, "admit", packet=p)
    send(sim, "claim", task_id="revision", owner="a", lease_units=5)
    tasks = sim.view()["tasks"]
    assert tasks["p"]["attempt_id"] != tasks["revision"]["attempt_id"]


def test_lease_boundary_and_backwards_clock_fail_closed():
    sim = claimed()
    with pytest.raises(BindingError, match="unexpired"):
        finish(sim, at=10)
    finish(sim, at=9)
    with pytest.raises(BindingError, match="backwards"):
        send(sim, "admit", at=8, packet=packet("new"))
