"""Adversarial, offline evidence predicates. No builder or subprocess runs."""
from copy import deepcopy

import pytest

from workers.claim_binding import BindingError, canonical_bytes, digest
from workers.packet_checks import (
    pytest_argv, verify_candidate, verify_diff, verify_model_binding,
    verify_red, worker_environment,
)

G1, G2, G3 = "1" * 40, "2" * 40, "3" * 40
H1, H2 = "sha256:" + "1" * 64, "sha256:" + "2" * 64


def test_argv_has_fixed_non_shell_shape():
    nodes = ["tests/test_one.py::TestOne::test_case[a-1.0]", "tests/sub/test_two.py"]
    assert pytest_argv({"kind": "pytest-v1", "nodes": nodes}, approved_python="/env/bin/python") == (
        "/env/bin/python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes)


@pytest.mark.parametrize("node", [
    "tests/test_a.py;touch /tmp/x", "$(id)", "`id`", "tests/../test_a.py",
    "--override-ini=pythonpath=/bad", "/tmp/test_a.py", "tests/test_a.py\n-c x",
    "tests/test_a.py::test_a[param;id]", "tests/test_a.py && true", "tests//test_a.py",
])
def test_argv_rejects_shell_and_scope_escape(node):
    with pytest.raises(BindingError):
        pytest_argv({"kind": "pytest-v1", "nodes": [node]}, approved_python="/env/python")


@pytest.mark.parametrize("command", [
    {"kind": "bash", "nodes": ["tests/test_a.py"]},
    {"kind": "pytest-v1", "nodes": []},
    {"kind": "pytest-v1", "nodes": ["tests/test_a.py"] * 2},
    {"kind": "pytest-v1", "nodes": ["tests/test_a.py"], "shell": True},
])
def test_argv_rejects_ambiguous_contract(command):
    with pytest.raises(BindingError):
        pytest_argv(command, approved_python="/env/python")


def red_fixture():
    expected = dict(attempt_id="attempt-a", base_sha=G1, command_sha256=H1,
                    nodeid="tests/test_bug.py::test_bug", reason_sha256=H2)
    receipt = {k: expected[k] for k in ("attempt_id", "base_sha", "command_sha256")}
    receipt.update(kind="pytest-receipt-v1", exit_code=1, launched=True, timed_out=False,
                   collection_errors=0, setup_errors=0, teardown_errors=0, collected=2,
                   tests=[dict(nodeid=expected["nodeid"], phase="call", outcome="failed",
                               exception_type="AssertionError", reason_sha256=H2),
                          dict(nodeid="tests/test_ok.py::test_ok", phase="call", outcome="passed",
                               exception_type=None, reason_sha256=None)])
    return expected, receipt


def test_exact_expected_red_with_passing_control():
    expected, receipt = red_fixture()
    verify_red(receipt, expected)


@pytest.mark.parametrize("field,value", [
    ("exit_code", 0), ("exit_code", 2), ("exit_code", 127), ("exit_code", -9),
    ("exit_code", True), ("launched", False), ("timed_out", True),
    ("collection_errors", 1), ("setup_errors", 1), ("teardown_errors", 1),
    ("collected", 0), ("collected", 3), ("tests", []),
    ("attempt_id", "other"), ("base_sha", G2), ("command_sha256", H2),
])
def test_infrastructure_or_foreign_failure_is_not_red(field, value):
    expected, receipt = red_fixture()
    receipt[field] = value
    with pytest.raises(BindingError):
        verify_red(receipt, expected)


@pytest.mark.parametrize("field,value", [
    ("nodeid", "tests/test_other.py::test_other"), ("phase", "setup"),
    ("outcome", "skipped"), ("outcome", "passed"),
    ("exception_type", "ImportError"), ("reason_sha256", H1),
])
def test_only_named_assertion_failure_is_admitted(field, value):
    expected, receipt = red_fixture()
    receipt["tests"][0][field] = value
    with pytest.raises(BindingError):
        verify_red(receipt, expected)


def test_duplicate_failure_and_contradictory_pass_are_refused():
    expected, receipt = red_fixture()
    receipt["tests"][1] = deepcopy(receipt["tests"][0])
    with pytest.raises(BindingError):
        verify_red(receipt, expected)
    expected, receipt = red_fixture()
    receipt["tests"][1]["exception_type"] = "AssertionError"
    with pytest.raises(BindingError):
        verify_red(receipt, expected)


def raw_diff(status="M", paths=("workers/a.py",), oldmode="100644", newmode="100644",
             oldsha=G1, newsha=G2):
    return (f":{oldmode} {newmode} {oldsha} {newsha} {status}\0".encode()
            + b"\0".join(p.encode() if isinstance(p, str) else p for p in paths) + b"\0")


def test_nul_diff_preserves_unusual_paths_and_rename_endpoints():
    paths = ("workers/a\tb.py", "workers/new\nname.py")
    changes = verify_diff(raw_diff("R100", paths), ["workers/"])
    assert changes[0]["paths"] == list(paths)
    assert changes[0]["old_sha"] == G1 and changes[0]["new_sha"] == G2


@pytest.mark.parametrize("raw", [
    raw_diff("A", oldmode="000000", oldsha="0" * 40),
    raw_diff("D", newmode="000000", newsha="0" * 40),
    raw_diff(newmode="100755"),
])
def test_regular_add_delete_and_executable_mode_are_visible(raw):
    assert len(verify_diff(raw, ["workers/a.py"])) == 1


@pytest.mark.parametrize("raw,scope", [
    (raw_diff("R100", ("protected/a.py", "workers/a.py")), ["workers/"]),
    (raw_diff("R100", ("workers/a.py", "protected/a.py")), ["workers/"]),
    (raw_diff(paths=("workers_evil/a.py",)), ["workers/"]),
    (raw_diff(paths=("workers",)), ["workers/"]),
    (raw_diff(paths=("workers/a.py/child",)), ["workers/a.py"]),
    (raw_diff(paths=("workers/../protected/a.py",)), ["workers/"]),
    (raw_diff(paths=("/workers/a.py",)), ["workers/"]),
    (raw_diff(paths=("workers//a.py",)), ["workers/"]),
    (raw_diff(paths=("workers/a.py",)), ["workers/../workers/"]),
])
def test_scope_checks_both_rename_sides_and_path_boundaries(raw, scope):
    with pytest.raises(BindingError):
        verify_diff(raw, scope)


@pytest.mark.parametrize("raw", [
    raw_diff(newmode="120000"), raw_diff(oldmode="120000"),
    raw_diff(newmode="160000"), raw_diff("T"), raw_diff("U"), raw_diff("C100"),
    raw_diff("R101", ("workers/a.py", "workers/b.py")),
    raw_diff("R100", ("workers/a.py", "workers/a.py")),
    raw_diff("R100", ("workers/a.py",)), raw_diff()[:-1],
    raw_diff() + raw_diff(), raw_diff(paths=(b"workers/\xff.py",)),
    raw_diff("A"), raw_diff("D"), raw_diff(newsha="0" * 40), b"nonsense\0",
])
def test_ambiguous_or_unsafe_diff_is_refused(raw):
    with pytest.raises(BindingError):
        verify_diff(raw, ["workers/"])


def test_empty_diff_still_requires_explicit_scope():
    assert verify_diff(b"", ["workers/"]) == []
    with pytest.raises(BindingError):
        verify_diff(b"", [])


def candidate_fixture(raw=None):
    raw = raw_diff() if raw is None else raw
    diff_sha256 = digest(raw)
    observed = dict(attempt_id="attempt-a", contract_sha256=H1, base_sha=G1,
                    before_sha=G1, after_sha=G3, diff_sha256=diff_sha256, command_sha256=H1,
                    worker_id="builder", verifier_id="independent-runner")
    receipt = dict(observed, builder_exit_code=0, builder_launched=True,
                   builder_timed_out=False, clean_tree=True,
                   scope=dict(status="passed", candidate_sha=G3, diff_sha256=diff_sha256),
                   verification=dict(status="passed", candidate_sha=G3,
                                     command_sha256=H1, verifier_id="independent-runner"))
    return observed, receipt


def test_candidate_binds_exact_independent_observations():
    observed, receipt = candidate_fixture()
    verify_candidate(receipt, observed, raw_diff=raw_diff(), files_in_scope=["workers/"])


def test_distinct_empty_commit_is_not_a_change_candidate():
    observed, receipt = candidate_fixture()
    observed["diff_sha256"] = receipt["diff_sha256"] = digest(b"")
    receipt["scope"]["diff_sha256"] = digest(b"")
    assert observed["before_sha"] != observed["after_sha"]
    assert verify_diff(b"", ["workers/"]) == []
    with pytest.raises(BindingError, match="nonempty"):
        verify_candidate(receipt, observed, raw_diff=b"", files_in_scope=["workers/"])


@pytest.mark.parametrize("raw", [
    raw_diff("A", oldmode="000000", oldsha="0" * 40),
    raw_diff("D", newmode="000000", newsha="0" * 40),
    raw_diff(),
    raw_diff(newmode="100755", newsha=G1),
    raw_diff("R100", ("workers/a.py", "workers/b.py"), newsha=G1),
])
def test_candidate_requires_real_validated_changes_including_mode_only(raw):
    observed, receipt = candidate_fixture(raw)
    verify_candidate(receipt, observed, raw_diff=raw, files_in_scope=["workers/"])


@pytest.mark.parametrize("raw", [b"", raw_diff(paths=("workers/b.py",))])
def test_matching_receipts_cannot_substitute_different_raw_bytes(raw):
    observed, receipt = candidate_fixture()
    with pytest.raises(BindingError, match="observed digest"):
        verify_candidate(receipt, observed, raw_diff=raw, files_in_scope=["workers/"])


@pytest.mark.parametrize("raw,scope", [
    (raw_diff(paths=("protected/a.py",)), ["workers/"]),
    (raw_diff("R100", ("workers/a.py", "protected/a.py")), ["workers/"]),
    (raw_diff(), []),
    (raw_diff(), ["workers/../workers/"]),
    (raw_diff(newsha=G1), ["workers/"]),
    (b"malformed\0", ["workers/"]),
])
def test_green_receipts_cannot_hide_unvalidated_scope_or_noop_records(raw, scope):
    observed, receipt = candidate_fixture(raw)
    with pytest.raises(BindingError):
        verify_candidate(receipt, observed, raw_diff=raw, files_in_scope=scope)


@pytest.mark.parametrize("raw", [None, "not bytes", bytearray(raw_diff())])
def test_candidate_requires_observed_raw_bytes(raw):
    observed, receipt = candidate_fixture()
    with pytest.raises(BindingError, match="raw bytes"):
        verify_candidate(receipt, observed, raw_diff=raw, files_in_scope=["workers/"])


def test_consistent_receipts_cannot_admit_the_unchanged_head():
    observed, receipt = candidate_fixture()
    observed["after_sha"] = receipt["after_sha"] = G1
    receipt["scope"]["candidate_sha"] = receipt["verification"]["candidate_sha"] = G1
    with pytest.raises(BindingError, match="no new commit"):
        verify_candidate(receipt, observed, raw_diff=raw_diff(), files_in_scope=["workers/"])


@pytest.mark.parametrize("field,value", [
    ("builder_exit_code", 1), ("builder_exit_code", False), ("builder_launched", False),
    ("builder_timed_out", True), ("clean_tree", False), ("after_sha", G2),
    ("before_sha", G2), ("attempt_id", "late-attempt"), ("diff_sha256", H1),
    ("contract_sha256", H2), ("command_sha256", H2), ("verifier_id", "builder"),
])
def test_failed_builder_stale_commit_and_reused_receipts_refuse(field, value):
    observed, receipt = candidate_fixture()
    receipt[field] = value
    with pytest.raises(BindingError):
        verify_candidate(receipt, observed, raw_diff=raw_diff(), files_in_scope=["workers/"])


@pytest.mark.parametrize("which,field,value", [
    ("scope", "candidate_sha", G2), ("scope", "diff_sha256", H1),
    ("scope", "status", "unknown"), ("verification", "candidate_sha", G2),
    ("verification", "command_sha256", H2), ("verification", "verifier_id", "builder"),
])
def test_scope_and_test_receipts_cannot_be_from_another_candidate(which, field, value):
    observed, receipt = candidate_fixture()
    receipt[which][field] = value
    with pytest.raises(BindingError):
        verify_candidate(receipt, observed, raw_diff=raw_diff(), files_in_scope=["workers/"])


def test_no_change_and_self_verification_refuse_even_if_claimed_consistently():
    observed, receipt = candidate_fixture()
    observed["before_sha"] = receipt["before_sha"] = G3
    with pytest.raises(BindingError):
        verify_candidate(receipt, observed, raw_diff=raw_diff(), files_in_scope=["workers/"])


def test_matching_receipts_cannot_hide_a_builder_starting_from_another_base():
    observed, receipt = candidate_fixture()
    observed["before_sha"] = receipt["before_sha"] = G2
    with pytest.raises(BindingError, match="exact approved base"):
        verify_candidate(receipt, observed, raw_diff=raw_diff(), files_in_scope=["workers/"])
    observed, receipt = candidate_fixture()
    observed["verifier_id"] = receipt["verifier_id"] = "builder"
    receipt["verification"]["verifier_id"] = "builder"
    with pytest.raises(BindingError):
        verify_candidate(receipt, observed, raw_diff=raw_diff(), files_in_scope=["workers/"])


def test_environment_is_positive_and_has_no_ambient_dependencies(monkeypatch):
    monkeypatch.setenv("ARBITRARY_SECRET", "never-inherit")
    monkeypatch.setenv("PYTHONPATH", "/host/override")
    env = worker_environment(private_home="/private/home", private_tmp="/private/tmp",
                             approved_path="/env/bin:/usr/bin", attempt_id="a", contract_sha256=H1)
    assert env == dict(HOME="/private/home", TMPDIR="/private/tmp", PATH="/env/bin:/usr/bin",
                       LANG="C.UTF-8", PKT_ATTEMPT_ID="a", PKT_CONTRACT_SHA256=H1)


@pytest.mark.parametrize("path", ["relative", "/x/..", "/x/../y", "/x/./y", "/x//y", "/x\0y", "/"])
def test_private_paths_are_canonical(path):
    with pytest.raises(BindingError):
        worker_environment(private_home=path, private_tmp="/private/tmp",
                           approved_path="/usr/bin", attempt_id="a", contract_sha256=H1)
    with pytest.raises(BindingError):
        pytest_argv({"kind": "pytest-v1", "nodes": ["tests/test_a.py"]}, approved_python=path)


@pytest.mark.parametrize("path", ["/usr/bin:", ":/usr/bin", ".:/usr/bin", "/usr/bin::/bin"])
def test_search_path_cannot_include_ambient_current_directory(path):
    with pytest.raises(BindingError):
        worker_environment(private_home="/private/home", private_tmp="/private/tmp",
                           approved_path=path, attempt_id="a", contract_sha256=H1)


def model_fixture():
    profile = dict(profile_id="fixture-profile", model_id="fixture-model", artifact_sha256=H1,
                   server_image_sha256=H2, tool_contract_sha256=H1, qualification_cursor_sha256=H2,
                   sandbox_policy_sha256=H1, context_tokens=8192)
    return profile, {"data": [{"id": "fixture-model"}]}, {"model": "fixture-model"}


def test_model_identity_matches_pinned_profile_without_real_discovery():
    profile, discovery, completion = model_fixture()
    verify_model_binding(profile, discovery, completion, expected_profile_sha256=digest(canonical_bytes(profile)))


@pytest.mark.parametrize("kind", ["profile", "missing", "returned", "duplicate", "malformed", "context"])
def test_model_identity_drift_and_invalid_evidence_refuse(kind):
    profile, discovery, completion = model_fixture()
    expected = digest(canonical_bytes(profile))
    if kind == "profile":
        profile["artifact_sha256"] = H2
    elif kind == "missing":
        discovery["data"] = [{"id": "other-model"}]
    elif kind == "returned":
        completion["model"] = "other-model"
    elif kind == "duplicate":
        discovery["data"] *= 2
    elif kind == "malformed":
        discovery["data"] = [{}]
    else:
        profile["context_tokens"] = True
        expected = digest(canonical_bytes(profile))
    with pytest.raises(BindingError):
        verify_model_binding(profile, discovery, completion, expected_profile_sha256=expected)
