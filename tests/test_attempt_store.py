"""SQLite effects are confined to pytest's private temporary directory."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest

from workers.attempt_store import AttemptStore
from workers.claim_binding import BindingError, admit_claim


def prepared(tmp_path):
    store = AttemptStore(tmp_path / "attempts.sqlite")
    attempt = store.reserve("2026-09-05")
    claim = admit_claim({"text": "H1"})
    store.put_claim(attempt["attempt_id"], claim)
    return store, attempt["attempt_id"], claim


def receipt(store, attempt, claim, dispatch="d1", step="critique", **changes):
    args = dict(dispatch_id=dispatch, step=step, producer="fixture:critic",
                parent_request_id="wrapper-1", source_receipt_ids=[],
                output={"verdict": "survives"})
    args.update(changes)
    return store.put_receipt(attempt, claim.claim_sha256, **args)


def test_concurrent_incomplete_starts_reserve_distinct_durable_ids(tmp_path):
    path = tmp_path / "attempts.sqlite"
    store = AttemptStore(path)
    barrier = threading.Barrier(8)
    def reserve(_):
        barrier.wait(timeout=5)
        return store.reserve("2026-09-05", minimum_sequence=12)
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(reserve, range(8)))
    assert len({r["attempt_id"] for r in rows}) == 8
    assert len({r["iteration_id"] for r in rows}) == 8
    assert sorted(r["iteration_id"] for r in rows) == [f"iter-2026-09-05-{n:03d}" for n in range(13, 21)]
    # Abandoned reservations persist across reopen without any completed work.
    assert AttemptStore(path).reserve("2026-09-05")["iteration_id"].endswith("021")


def test_receipt_replay_is_idempotent_and_cannot_replace_failure(tmp_path):
    store, attempt, claim = prepared(tmp_path)
    first = receipt(store, attempt, claim, status="failed")
    assert receipt(store, attempt, claim, status="failed") == first
    original = store.read_receipt(first)
    with pytest.raises(BindingError, match="different receipt"):
        receipt(store, attempt, claim, status="passed")
    assert store.read_receipt(first) == original
    revised = receipt(store, attempt, claim, dispatch="d2", supersedes=first)
    assert revised != first and store.read_receipt(revised)["supersedes"] == first
    with pytest.raises(BindingError, match="unsuccessful"):
        store.verify_for_commit(attempt, claim, [first], required_steps=("critique",), required_sources={"critique": ()})
    store.verify_for_commit(attempt, claim, [revised], required_steps=("critique",), required_sources={"critique": ()})


def test_old_claim_evidence_cannot_promote_a_revision(tmp_path):
    store, attempt, c1 = prepared(tmp_path)
    r1 = receipt(store, attempt, c1)
    c2 = admit_claim({"text": "H2"}, supersedes=c1)
    store.put_claim(attempt, c2)
    with pytest.raises(BindingError, match="wrong identity"):
        store.verify_for_commit(attempt, c2, [r1], required_steps=("critique",), required_sources={"critique": ()})
    with pytest.raises(BindingError, match="another claim"):
        receipt(store, attempt, c2, dispatch="d2", source_receipt_ids=[r1])
    r2 = receipt(store, attempt, c2, dispatch="d2", supersedes=r1)
    store.verify_for_commit(attempt, c2, [r2], required_steps=("critique",), required_sources={"critique": ()})
    assert store.read_receipt(r1)["input_claim_sha256"] == c1.claim_sha256


def test_unknown_cross_attempt_or_missing_evidence_refused(tmp_path):
    store, a1, c = prepared(tmp_path)
    r1 = receipt(store, a1, c)
    a2 = store.reserve("2026-09-05")["attempt_id"]
    store.put_claim(a2, c)
    with pytest.raises(BindingError, match="wrong identity"):
        store.verify_for_commit(a2, c, [r1], required_steps=("critique",), required_sources={"critique": ()})
    with pytest.raises(BindingError, match="unknown"):
        receipt(store, a2, c, source_receipt_ids=[r1])
    with pytest.raises(BindingError, match="missing"):
        store.verify_for_commit(a1, c, [r1], required_steps=("critique", "retrieval"), required_sources={"critique": ("retrieval",), "retrieval": ()})
    with pytest.raises(BindingError, match="unknown"):
        store.read_receipt("sha256:" + "0" * 64)
    with pytest.raises(BindingError, match="duplicate"):
        store.verify_for_commit(a1, c, [r1, r1], required_steps=("critique",), required_sources={"critique": ()})


def test_write_failure_never_returns_a_successful_receipt(tmp_path):
    store, attempt, claim = prepared(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER deny_receipt BEFORE INSERT ON receipts BEGIN SELECT RAISE(ABORT, 'injected append failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="append failure"):
        receipt(store, attempt, claim)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0


def test_tampered_receipt_is_not_eligible(tmp_path):
    store, attempt, claim = prepared(tmp_path)
    rid = receipt(store, attempt, claim)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE receipts SET canonical=? WHERE receipt_sha256=?", (b'{}', rid))
    with pytest.raises(BindingError, match="corrupt"):
        store.verify_for_commit(attempt, claim, [rid], required_steps=("critique",), required_sources={"critique": ()})


def test_unknown_revision_and_wrong_step_supersession_refused(tmp_path):
    store, attempt, c1 = prepared(tmp_path)
    c2 = admit_claim({"text": "H2"}, supersedes=admit_claim({"text": "unregistered"}))
    with pytest.raises(BindingError, match="unknown superseded"):
        store.put_claim(attempt, c2)
    r1 = receipt(store, attempt, c1, step="retrieval")
    with pytest.raises(BindingError, match="same step"):
        receipt(store, attempt, c1, dispatch="d2", step="critique", supersedes=r1)


def test_store_has_no_live_default_and_rejects_symlink(tmp_path):
    with pytest.raises(TypeError):
        AttemptStore()
    target = tmp_path / "target.sqlite"
    target.write_bytes(b"sentinel")
    link = tmp_path / "link.sqlite"
    link.symlink_to(target)
    with pytest.raises(BindingError, match="symlink"):
        AttemptStore(link)
    assert target.read_bytes() == b"sentinel"


def test_late_old_claim_receipt_cannot_displace_current_evidence(tmp_path):
    store, attempt, c1 = prepared(tmp_path)
    r1 = receipt(store, attempt, c1)
    c2 = admit_claim({"text": "H2"}, supersedes=c1)
    store.put_claim(attempt, c2)
    r2 = receipt(store, attempt, c2, dispatch="d2", supersedes=r1)
    original = {rid: store.read_receipt(rid) for rid in (r1, r2)}
    with sqlite3.connect(store.path) as db:
        count_before = db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    try:
        late = receipt(store, attempt, c1, dispatch="late", supersedes=r2)
    except BindingError as error:
        assert "current claim" in str(error)
    else:
        # Demonstrate the original displacement before reporting the red failure.
        with pytest.raises(BindingError, match="superseded"):
            store.verify_for_commit(attempt, c2, [r2], required_steps=("critique",),
                                    required_sources={"critique": ()})
        pytest.fail(f"new stale-claim receipt {late} displaced current c2/r2 evidence")
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == count_before
    store.verify_for_commit(attempt, c2, [r2], required_steps=("critique",),
                            required_sources={"critique": ()})
    assert {rid: store.read_receipt(rid) for rid in (r1, r2)} == original
    assert receipt(store, attempt, c1) == r1


@pytest.mark.parametrize("status", ["passed", "failed", "skipped"])
@pytest.mark.parametrize("step", ["critique", "new-step"])
def test_every_new_stale_claim_receipt_is_refused(tmp_path, status, step):
    store, attempt, c1 = prepared(tmp_path)
    r1 = receipt(store, attempt, c1)
    c2 = admit_claim({"text": "H2"}, supersedes=c1)
    store.put_claim(attempt, c2)
    r2 = receipt(store, attempt, c2, dispatch="d2", supersedes=r1)
    with pytest.raises(BindingError, match="unique current claim"):
        receipt(store, attempt, c1, dispatch="late", status=status, step=step,
                supersedes=r2 if step == "critique" else None)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 2
    store.verify_for_commit(attempt, c2, [r2], required_steps=("critique",),
                            required_sources={"critique": ()})


@pytest.mark.parametrize("status", ["passed", "failed", "skipped"])
def test_superseded_receipt_replay_preserves_original_bytes(tmp_path, status):
    store, attempt, c1 = prepared(tmp_path)
    r1 = receipt(store, attempt, c1, status=status)
    original = store.read_receipt(r1)
    c2 = admit_claim({"text": "H2"}, supersedes=c1)
    store.put_claim(attempt, c2)
    r2 = receipt(store, attempt, c2, dispatch="d2", supersedes=r1, status=status)
    r3 = receipt(store, attempt, c2, dispatch="d3", supersedes=r2)
    assert receipt(store, attempt, c1, status=status) == r1
    assert receipt(store, attempt, c2, dispatch="d2", supersedes=r1, status=status) == r2
    with pytest.raises(BindingError, match="different receipt bytes"):
        receipt(store, attempt, c1, status=status, output={"changed": True})
    assert store.read_receipt(r1) == original
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 3
    store.verify_for_commit(attempt, c2, [r3], required_steps=("critique",),
                            required_sources={"critique": ()})


def test_ambiguous_claim_heads_refuse_new_receipts(tmp_path):
    store, attempt, c1 = prepared(tmp_path)
    other = admit_claim({"text": "unlinked external fault"})
    with sqlite3.connect(store.path) as db:
        # Inject an external-store fault that the ordinary claim API refuses.
        db.execute("INSERT INTO claims VALUES (?, ?, ?, ?)",
                   (attempt, other.claim_sha256, other.canonical, None))
    for claim in (c1, other):
        with pytest.raises(BindingError, match="unique current claim"):
            receipt(store, attempt, claim)
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


@pytest.mark.parametrize("fault", ["second-root", "sibling-revision"])
def test_ambiguous_claim_heads_in_private_store_refuse_commit_verification(tmp_path, fault):
    store, attempt, c1 = prepared(tmp_path)
    r1 = receipt(store, attempt, c1)
    selected, selected_receipt = c1, r1
    if fault == "sibling-revision":
        selected = admit_claim({"text": "H2"}, supersedes=c1)
        store.put_claim(attempt, selected)
        selected_receipt = receipt(store, attempt, selected, dispatch="d2", supersedes=r1)
    store.verify_for_commit(attempt, selected, [selected_receipt],
                            required_steps=("critique",), required_sources={"critique": ()})
    original = store.read_receipt(r1)
    other = admit_claim({"text": "external private-store fault"},
                        supersedes=c1 if fault == "sibling-revision" else None)
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO claims VALUES (?, ?, ?, ?)",
                   (attempt, other.claim_sha256, other.canonical, other.supersedes))
        count_before = db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    with pytest.raises(BindingError, match="unique current claim"):
        store.verify_for_commit(attempt, selected, [selected_receipt],
                                required_steps=("critique",), required_sources={"critique": ()})
    assert receipt(store, attempt, c1) == r1
    assert store.read_receipt(r1) == original
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == count_before


def test_ancestor_symlink_is_unsupported_caller_precondition(tmp_path):
    # This fixture documents an unchecked caller obligation, not confinement.
    requested = tmp_path / "requested"
    resolved = tmp_path / "resolved"
    requested.mkdir()
    resolved.mkdir()
    link = requested / "link"
    link.symlink_to(resolved, target_is_directory=True)
    store = AttemptStore(link / "attempts.sqlite")
    attempt = store.reserve("2026-09-05")
    assert (resolved / "attempts.sqlite").is_file()
    with sqlite3.connect(resolved / "attempts.sqlite") as db:
        assert db.execute("SELECT attempt_id FROM attempts").fetchall() == [(attempt["attempt_id"],)]


def test_failed_retry_invalidates_prior_success_and_forks_refuse(tmp_path):
    store, attempt, claim = prepared(tmp_path)
    r1 = receipt(store, attempt, claim)
    r2 = receipt(store, attempt, claim, dispatch="d2", supersedes=r1, status="failed")
    with pytest.raises(BindingError, match="superseded"):
        store.verify_for_commit(attempt, claim, [r1], required_steps=("critique",), required_sources={"critique": ()})
    with pytest.raises(BindingError, match="current step head"):
        receipt(store, attempt, claim, dispatch="fork", supersedes=r1)
    with pytest.raises(BindingError, match="current step head"):
        receipt(store, attempt, claim, dispatch="unlinked")
    with pytest.raises(BindingError, match="unsuccessful"):
        receipt(store, attempt, claim, dispatch="child", step="child", source_receipt_ids=[r2])


def test_claim_revision_invalidates_old_commit_and_branching_refuses(tmp_path):
    store, attempt, old = prepared(tmp_path)
    r = receipt(store, attempt, old)
    new = admit_claim({"text": "new"}, supersedes=old)
    store.put_claim(attempt, new)
    with pytest.raises(BindingError, match="superseded"):
        store.verify_for_commit(attempt, old, [r], required_steps=("critique",), required_sources={"critique": ()})
    for claim in (admit_claim({"text": "fork"}, supersedes=old), admit_claim({"text": "second root"})):
        with pytest.raises(BindingError, match="current head"):
            store.put_claim(attempt, claim)


def test_commit_requires_exact_current_dependency_graph(tmp_path):
    store, attempt, claim = prepared(tmp_path)
    upstream = receipt(store, attempt, claim, dispatch="up1", step="retrieval")
    downstream = receipt(store, attempt, claim, source_receipt_ids=[upstream])
    graph = {"retrieval": (), "critique": ("retrieval",)}
    steps = ("retrieval", "critique")
    store.verify_for_commit(attempt, claim, [upstream, downstream], required_steps=steps, required_sources=graph)
    with pytest.raises(BindingError, match="dependency graph"):
        store.verify_for_commit(attempt, claim, [downstream], required_steps=("critique",), required_sources={"critique": ()})
    new_upstream = receipt(store, attempt, claim, dispatch="up2", step="retrieval", supersedes=upstream)
    with pytest.raises(BindingError, match="dependency graph"):
        store.verify_for_commit(attempt, claim, [new_upstream, downstream], required_steps=steps, required_sources=graph)
    repaired = receipt(store, attempt, claim, dispatch="down2", supersedes=downstream, source_receipt_ids=[new_upstream])
    store.verify_for_commit(attempt, claim, [new_upstream, repaired], required_steps=steps, required_sources=graph)
    with pytest.raises(BindingError, match="dependency graph"):
        store.verify_for_commit(attempt, claim, [new_upstream, repaired], required_steps=steps, required_sources={"retrieval": (), "critique": ()})
