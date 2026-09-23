"""Plan 2026-09-24 d3 (G7.1): stop fixture drift at the lane, and measure the
loop's failing meta_review step instead of falling back silently.

Why this exists (run_state/meta_oracle_reviews.jsonl, retro claude-fd99b8f6159965c4,
cause missing_context, three material postings on 2026-09-23): every nara_dev plan
item's test fixtures were derived by hand from live files, and three days running
they invented keys and enum values the live files do not hold. The cost was three
postings of one item, two withdrawals and six lane holds. The retro's highest-value
fix is to make the gate refuse that, rather than to ask me to be careful.

Eight cases, all red on main:

  1  a fixture whose keys are not a subset of the live file's keys is refused, naming the key
  2  a fixture whose declared enum field holds a value the live file never contains is refused,
     naming the value
  3  a fixture whose live path does not exist is refused
  4  a JSONL live file is accepted row-by-row (keys over the union of same-kind rows); a
     non-object row or an unparseable line is refused, naming the file
  5  a fixture whose live path escapes the repo root is refused
  6  a green precheck receipt that git tracks does not admit the item, and receipts are read
     from the main lab root only
  7  validate_plan_item accepts fixture_sources / fixture_enums of string->string and rejects
     every other shape
  8  loop_health.meta_review_fallbacks counts the fallback events whose note names meta_review
     over a window, with last_seen, from injected rows (red on main: the function does not exist)

Case 4's shape is dictated by what the lab actually stores (review
claude-5dea097dd434208a amendment 4): `run_state/oracle_nara_mailbox.jsonl` and
`run_state/week1.run.jsonl` are JSONL, and the lane-status CLI prints JSON to
stdout, so it is not declarable as a fixture_source at all.

Hermetic: the unit cases call lane.admission() and mailbox.validate_plan_item()
directly and point lane ROOT at a tmp_path scratch repo (the same redirect
tests/test_nara_lane_precheck.py uses). Case 6's tracking check uses a real
scratch git repo; no case needs bubblewrap or Flash.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import sys

import pytest

from orchestrator import coordinator_cycle_log
from orchestrator import loop_health
from orchestrator import nara_lane as lane
from orchestrator import oracle_mailbox as mailbox


def _repo(tmp_path, monkeypatch):
    """A scratch git repo standing in for the lab, with run_state/ gitignored.

    The git identity is set locally, not per-command: `git commit` refuses when
    neither user.email nor a system identity is available, and the sandbox the lane
    runs its tests in has no HOME. tests/test_nara_lane_precheck.py's scratch repo
    never commits past its init, so it does not hit this."""
    root = tmp_path / "repo"
    (root / "run_state").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
                    "-m", "init"], cwd=root, check=True)
    (root / ".gitignore").write_text("run_state/\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "ignore run_state"],
                   cwd=root, check=True)
    monkeypatch.setattr(lane, "ROOT", root)
    monkeypatch.setattr(lane, "RUN_LOG", tmp_path / "run.jsonl")
    monkeypatch.setattr(lane, "log", lambda *a, **k: None)
    return root


def _live(root, rel, rows_or_obj):
    """Write a live file under the scratch repo; a list is written as JSONL."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows_or_obj, list):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows_or_obj))
    else:
        path.write_text(json.dumps(rows_or_obj))
    return path


def admit_only(item):
    """Reasons from admission() with the precheck-receipt rule dropped, so each case
    below is about the rule it names and not about the receipt the scratch repo has
    no way to have. `admission_without_receipt` is the lane's own helper for exactly
    this (the precheck entry point's test has no receipt by definition)."""
    return [r for r in lane.admission(item) if "precheck receipt" not in r]


def item(sources=None, enums=None, *, test_path="tests/test_fixture_hygiene_fixture.py",
         content="def test_v():\n    assert True\n"):
    body = {"title": "fixture hygiene item", "objective": "x", "task_class": "tooling",
            "allowed_write_paths": ["tools/fixture_hygiene_fixture.py"],
            "acceptance": {"test_path": test_path, "test_content": content,
                           "test_argv": ["python", "-m", "pytest", "-q", test_path]}}
    if sources is not None:
        body["fixture_sources"] = sources
    if enums is not None:
        body["fixture_enums"] = enums
    return {"actor": "oracle", "msg_id": "oracle-fixture-hygiene", "seq": 1, "kind": "plan_item", "body": body}


MB_ROWS = [{"schema": "oracle-nara-mailbox/v1", "seq": 1, "actor": "oracle", "kind": "plan_item",
            "body": {"title": "t"}, "in_reply_to": None},
           {"schema": "oracle-nara-mailbox/v1", "seq": 2, "actor": "nara", "kind": "receipt",
            "body": {"state": "held"}, "in_reply_to": "m1"}]


# ── cases 1-5: the fixture_sources check in admission() ───────────────────────

def test_invented_fixture_key_is_refused_naming_the_key(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _live(root, "run_state/research_focus/abc.json", {"schema_version": "research-focus/v1",
                                                     "focus_id": "f", "stage": "active"})
    reasons = admit_only(_with_fixture({"focus_id": "f", "stage": "active", "lane_state": "held"},
                                           {"fixture_focus": "run_state/research_focus/abc.json"}))
    assert reasons, "an invented fixture key must not admit the item"
    assert any("lane_state" in r for r in reasons), reasons


def test_invented_enum_value_is_refused_naming_the_value(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _live(root, "run_state/research_focus/abc.json", {"schema_version": "research-focus/v1",
                                                     "stage": "needs_clean_refinement"})
    reasons = admit_only(_with_fixture({"stage": "active"},
                                           {"fixture_focus": "run_state/research_focus/abc.json"},
                                           {"fixture_focus": ["stage"]}))
    assert reasons, "an enum value the live file never holds must not admit the item"
    assert any("active" in r for r in reasons), reasons


def test_missing_live_path_is_refused(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    reasons = admit_only(_with_fixture({"focus_id": "f"},
                                           {"fixture_focus": "run_state/research_focus/absent.json"}))
    assert any("run_state/research_focus/absent.json" in r for r in reasons), reasons


def test_jsonl_live_file_is_accepted_and_bad_rows_refused(tmp_path, monkeypatch):
    """Amendment 4: JSONL is the shape of most live lab state, so it is checked
    row-wise (keys over the union of same-kind rows, enum values over all rows),
    and only a non-object row or an unparseable line is refused - naming the file."""
    root = _repo(tmp_path, monkeypatch)
    _live(root, "run_state/oracle_nara_mailbox.jsonl", MB_ROWS)
    ok = _with_fixture({"schema": "oracle-nara-mailbox/v1", "seq": 2, "actor": "nara", "kind": "receipt",
                        "body": {"state": "held"}, "in_reply_to": "m1"},
                       {"fixture_mailbox": "run_state/oracle_nara_mailbox.jsonl"},
                       {"fixture_mailbox": ["kind"]})
    assert admit_only(ok) == [], admit_only(ok)
    # a key present in one row but not the other is still allowed: the union
    assert admit_only(_with_fixture({"schema": "oracle-nara-mailbox/v1", "seq": 1, "actor": "oracle",
                                      "kind": "plan_item", "body": {"title": "t"}},
                                     {"fixture_mailbox": "run_state/oracle_nara_mailbox.jsonl"})) == []
    # an invented key in a JSONL fixture is still refused
    bad = _with_fixture({"schema": "oracle-nara-mailbox/v1", "seq": 1, "actor": "oracle", "kind": "plan_item",
                         "body": {"title": "t"}, "owner_decision": True},
                        {"fixture_mailbox": "run_state/oracle_nara_mailbox.jsonl"})
    assert any("owner_decision" in r for r in admit_only(bad))
    # a non-object row names the file
    (root / "run_state/oracle_nara_mailbox.jsonl").write_text(json.dumps(MB_ROWS[0]) + "\n[1, 2]\n")
    reasons = admit_only(_with_fixture({"schema": "oracle-nara-mailbox/v1", "seq": 1, "actor": "oracle",
                                         "kind": "plan_item", "body": {"title": "t"}},
                                        {"fixture_mailbox": "run_state/oracle_nara_mailbox.jsonl"}))
    assert reasons and any("run_state/oracle_nara_mailbox.jsonl" in r for r in reasons), reasons
    # an unparseable line names the file
    (root / "run_state/oracle_nara_mailbox.jsonl").write_text("{not json\n")
    reasons = admit_only(_with_fixture({"schema": "oracle-nara-mailbox/v1"},
                                           {"fixture_mailbox": "run_state/oracle_nara_mailbox.jsonl"}))
    assert reasons and any("run_state/oracle_nara_mailbox.jsonl" in r for r in reasons), reasons


def test_live_path_outside_the_repo_root_is_refused(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    outside = tmp_path / "elsewhere.json"
    outside.write_text(json.dumps({"schema": "external/v1"}))
    reasons = admit_only(_with_fixture({"schema": "external/v1"}, {"fixture_x": str(outside)}))
    assert reasons and any("outside" in r.lower() for r in reasons), reasons


def _with_fixture(fixture: dict, sources: dict, enums: dict | None = None):
    """One fixture object is enough to exercise the check. It is registered under the
    source-map key itself, since that is the key `check_fixtures` looks the fixture up
    by - a fixture named in no source map is deliberately left unchecked."""
    it = item(sources=sources, enums=enums)
    it["body"]["fixtures"] = {next(iter(sources)): fixture}
    return it


# ── case 6: a tracked receipt is not a precheck ───────────────────────────────

def test_tracked_precheck_receipt_does_not_admit_and_receipts_read_from_main_root(tmp_path, monkeypatch):
    """run_state/precheck_receipts/ was not gitignored, so a receipt was committed onto
    the gate branch at bef22e3; and the lane reads receipts from its own ROOT, which a
    worktree checkout shares. A receipt that git tracks proves nothing, and receipts
    never resolve inside a worktree."""
    root = _repo(tmp_path, monkeypatch)
    content = "def test_v():\n    assert True\n"
    sha = hashlib.sha256(content.encode()).hexdigest()
    it = item(content=content)

    # a green receipt, but tracked by git: the item is still held
    # One tracked sibling is enough to prove the refusal is about tracking: the same
    # `_prechecked()` lookup, the same repo, the same one commit, and only the file
    # under the test's own sha differs in trackedness. Two receipts of the same sha in
    # one directory is not a thing the filesystem allows, so the shas differ instead.
    tracked = root / "run_state/precheck_receipts" / f"{sha}ee.json"
    tracked.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"schema": "nara-lane-precheck/v1", "test_path": "tests/test_fixture_hygiene_fixture.py",
               "state": "green"}
    tracked.write_text(json.dumps({**receipt, "test_sha256": tracked.stem}))
    untracked = root / "run_state/precheck_receipts" / f"{sha}.json"
    untracked.write_text(json.dumps({**receipt, "test_sha256": sha}))
    subprocess.run(["git", "add", "-f", "--", str(tracked.relative_to(root))], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "receipt"],
                   cwd=root, check=True)
    assert lane._prechecked(it) is True, "an untracked receipt in a repo that tracks another must admit"
    it_tracked = item(content=content + "# tracked\n")  # same shape, sha = the tracked file's stem
    assert lane._prechecked(it_tracked) is False, "a receipt tracked by git must not count as prechecked"

    # and receipts resolve against the main lab checkout, never a worktree of it. The
    # lane's own ROOT is redirected to the scratch repo, so the rule is exercised the
    # way the lane hits it: from inside a worktree of that repo.
    worktree = root.parent / "wt"
    subprocess.run(["git", "worktree", "add", "--detach", str(worktree), "HEAD"], cwd=root, check=True)
    monkeypatch.setattr(lane, "ROOT", worktree)
    inside = lane._receipt_dir()
    assert not str(inside).startswith(str(worktree)), f"receipts resolved inside a worktree: {inside}"
    assert str(inside).startswith(str(root)), f"receipts resolved outside the main lab root: {inside}"


# ── case 7: the mailbox validates the new keys ────────────────────────────────

def test_validate_plan_item_accepts_the_new_maps_and_rejects_other_shapes():
    good = {"title": "t", "objective": "o", "task_class": "tooling",
            "allowed_write_paths": ["tools/x.py"],
            "acceptance": {"test_path": "tests/test_x.py", "test_content": "x",
                           "test_argv": ["python", "-m", "pytest", "-q", "tests/test_x.py"]},
            "fixture_sources": {"fixture_focus": "run_state/research_focus/abc.json"},
            "fixture_enums": {"fixture_focus": ["stage"]}}
    mailbox.validate_plan_item(good)
    for bad in (["not", "a", "map"], {"f": 1}, {"f": ["run_state/x.json", "run_state/y.json"]}, 17, None):
        body = dict(good, fixture_sources=bad)
        with pytest.raises(mailbox.MailboxError):
            mailbox.validate_plan_item(body)
    for bad in ({"f": "stage"}, {"f": [1]}, {"f": []}, "stage"):
        body = dict(good, fixture_enums=bad)
        with pytest.raises(mailbox.MailboxError):
            mailbox.validate_plan_item(body)


# ── case 8: measure the failing meta_review step ──────────────────────────────

def _fallback(ts, note="meta_review did not produce conditioning bullets (status=error); proceeding un-conditioned."):
    return {"timestamp": ts, "agent": "coordinator", "event_type": "loop_v0_fallback",
            "skill_used": "fallback", "iteration_id": "iter-x", "note": note}


def test_meta_review_fallbacks_counts_only_meta_review_over_the_window():
    """loop_v0_fallback is the coordinator's own record that a step degraded and the
    cycle proceeded anyway. 2026-09-23: 15 such rows named meta_review and nothing
    in the loop reported it, so the conditioning step was a silent no-op. Rows are
    injected; the detector never reads the disk and never calls a model."""
    rows = [_fallback("2026-09-23T07:37:57+00:00"), _fallback("2026-09-23T08:05:59+00:00"),
            {"timestamp": "2026-09-23T08:00:00+00:00", "agent": "coordinator",
             "event_type": "loop_v0_fallback", "note": "frontier vendor down; used local weights."},
            {"timestamp": "2026-09-23T09:00:00+00:00", "agent": "coordinator",
             "event_type": "cycle", "note": "meta_review failed here too"},
            _fallback("2026-09-20T01:00:00+00:00")]
    got = loop_health.meta_review_fallbacks(rows, window_hours=24,
                                            now="2026-09-23T09:30:00+00:00")
    assert got == {"meta_review_fallbacks": 2, "last_seen": "2026-09-23T08:05:59+00:00"}, got
    outside = loop_health.meta_review_fallbacks(rows, window_hours=24, now="2026-09-23T23:30:00+00:00")
    assert outside["meta_review_fallbacks"] == 2
    only_old = loop_health.meta_review_fallbacks([rows[-1]], window_hours=24, now="2026-09-23T09:30:00+00:00")
    assert only_old == {"meta_review_fallbacks": 0, "last_seen": None}, only_old
    assert loop_health.meta_review_fallbacks([], window_hours=24, now="2026-09-23T09:30:00+00:00") == \
        {"meta_review_fallbacks": 0, "last_seen": None}
    # rows the loop wrote without a note, or with an unreadable timestamp, are skipped, not fatal
    messy = [_fallback("not-a-timestamp"), {"timestamp": "2026-09-23T08:00:00+00:00",
                                           "event_type": "loop_v0_fallback"}]
    assert loop_health.meta_review_fallbacks(messy, window_hours=24, now="2026-09-23T09:30:00+00:00") == \
        {"meta_review_fallbacks": 0, "last_seen": None}


# ── the parser and the d1/d4 acceptance tests are tested where they live ──────

# One candidate per markdown shape, in the exact file form the precheck stub commits:
# candidate 1 as `### Field` sections, candidate 2 as `**Field:**` labelled lines,
# candidate 3 as `| Field | cell |` table rows. The shipped G1.1 acceptance test is a
# document check that has to stay red until Nara fills the document, so it cannot carry
# a document of its own; the fixture is this text and the tests below drive the shipped
# parser over it and over mutants of it.
CANDIDATE_FIXTURE = pathlib.Path(__file__).with_name("fixtures") / "g11_candidates_three_shapes.md"


def _g11_module(document, tmp_path):
    """The shipped G1.1 acceptance test, loaded with its module-level DOC pointed at a
    temporary document. It is a document check, so the only way to test the parser is to
    hand it documents; see CANDIDATE_FIXTURE for why the fixtures live here."""
    import importlib.util

    source = pathlib.Path(__file__).with_name("test_g11_thesis_candidates.py")
    assert source.is_file(), f"{source.name} must ship beside this test to be driven here"
    # Drive the shipped file under its own basename, the name pytest gives it, and drop
    # any cached copy so the drive cannot leak into or out of pytest's own import of it:
    # a stale sys.modules entry made pytest skip the import and run the test functions
    # with their module-level constants unbound (seen as 5 doc-check failures in a
    # combined run, both files green alone).
    sys.modules.pop(source.stem, None)
    root = pathlib.Path(tmp_path)
    target = root / "notes/research/2026-09-24-g11-candidates/CANDIDATES.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document)
    spec = importlib.util.spec_from_file_location(source.stem, source)
    module = importlib.util.module_from_spec(spec)
    # exec_module registers the name in sys.modules; leaving it there makes pytest skip
    # its own import of the same-named test file later and run its test functions with
    # the module-level constants unbound. Save and restore around the drive.
    sys.modules.pop("test_g11_thesis_candidates", None)  # this file is not the shipped one
    spec.loader.exec_module(module)
    module.ROOT, module.DOC = root, target
    return module


def test_the_shipped_candidate_test_passes_against_the_three_shape_fixture(tmp_path):
    """One candidate per markdown shape: `### Field` sections, `**Field:**` labelled
    lines, `| Field | cell |` rows. A failure here is a parser bug in MY test, not a
    thin document, which is the distinction the acceptance test cannot make for itself.

    A labelled line is written `**Lens:** text` rather than `Lens: text` because a colon
    at line end is a hard break in some markdown renderers. Measured, not assumed.
    """
    module = _g11_module(CANDIDATE_FIXTURE.read_text(), tmp_path)
    assert len(module.ranges()) == 3
    for key in module.REQUIRED:
        for rng in module.ranges():
            assert module.filled(module.field(rng, key)), f"{key} not read in one of the three shapes"
    for check in (module.test_three_to_five_candidates_and_no_title_block,
                  module.test_every_field_is_filled_and_the_line_is_honest,
                  module.test_lens_is_one_two_or_three_and_two_carries_the_rigor_rule,
                  module.test_each_stage_names_what_the_brief_asks_for,
                  module.test_anomaly_map_holds_two_outcomes_and_conviction_is_five_numbered_fields):
        check()


def test_the_candidate_test_is_shipped_exactly_as_the_lane_receipted_it():
    """The lane's precheck receipt is named for sha256(test_content), so any edit to the
    shipped acceptance test voids the red/green proof that admitted the item. Pinning the
    bytes here is what makes that visible in CI rather than at the lane.

    The receipt itself is deliberately NOT asserted present: run_state/ is ignored, so it
    exists only in the operator's live checkout and would skip in a clean one. What is
    asserted instead is the rule that keeps a receipt honest - that
    run_state/precheck_receipts stays ignored. At bef22e3 one was committed onto a gate
    branch, and a receipt that travels with a checkout pre-admits the test it names, which
    is the claim the receipt exists to prove. Case 6 shows admission() refusing a tracked
    receipt in a scratch repo; this is the same rule against the lab's real .gitignore.
    """
    import hashlib

    shipped = pathlib.Path(__file__).with_name("test_g11_thesis_candidates.py").read_text()
    sha = hashlib.sha256(shipped.encode()).hexdigest()
    assert sha == "8546e592a1638669347cdc51b3cdd8d0a0b4fcf1f951169b76ef57bfa3822b5c", (
        f"shipped G1.1 test changed ({sha[:16]}); re-run `nara_lane precheck` and repost")
    assert len(shipped.encode()) <= lane.MAX_TEST_BYTES, "an acceptance test over 8 KiB is refused by admission()"
    receipts = "run_state/precheck_receipts"
    gitignore = (lane.ROOT / ".gitignore").read_text()
    active = [ln.strip() for ln in gitignore.splitlines()
              if not ln.lstrip().startswith("#") and ln.strip().rstrip("/") == receipts]
    assert active, f"{receipts}/ is not ignored by the lab's .gitignore, so a committed " \
                   "receipt would travel with a branch and pre-admit its own test"


def test_the_candidate_test_rejects_documents_that_break_its_rules(tmp_path):
    """Negative controls for the shipped G1.1 test - the mutants its red-first claim
    rests on, run rather than asserted (canary (a), owner-approved 2026-09-24)."""
    base = CANDIDATE_FIXTURE.read_text()
    mutants = {
        "only two candidates": lambda t: t[: t.rindex("## Candidate 3")],
        "probability outside [0,1]": lambda t: t.replace("p_pass_T: 0.6", "p_pass_T: 6"),
        "interest outside [0,10]": lambda t: t.replace("interest_0_10: 8", "interest_0_10: 88"),
        "title left as a placeholder": lambda t: t.replace(
            "### Title\nAnchored priors survive cheap talk in LLM sender-receiver games.", "### Title\nTODO"),
        "no benchmark named at T": lambda t: t.replace("the benchmark is the Bayes-plausible posterior",
                                                       "the target is the posterior"),
        "one anomaly row only": lambda t: re.sub(r"(?m)^- No shift at T but a shift at S.*$", "", t),
        "conviction numbers with no reasons": lambda t: re.sub(r"because [^\n|]*", "", t),
    }
    for name, mutate in mutants.items():
        mutated = mutate(base)
        assert mutated != base, f"{name}: the mutant did not change the fixture"
        module = _g11_module(mutated, tmp_path / name.replace(" ", "_").replace("[", "").replace("]", ""))
        failures = []
        for check in (getattr(module, n) for n in dir(module) if n.startswith("test_")):
            try:
                check()
            except AssertionError:
                failures.append(check.__name__)
        assert failures, f"{name}: the shipped test accepted a document that breaks its rules"


# ── case 9: a test suite that reads the live frontier log cannot be hermetic ──

def test_no_test_reads_the_live_frontier_call_log(tmp_path):
    """`emit_health_signals()` takes frontier_calls_path as an argument but falls back
    to the module default, which resolves to `<repo root>/run_state/frontier_calls.jsonl`
    - a real, growing, append-only file. tests/conftest.py's autouse `_no_live_artifacts`
    redirects the cycle and health paths but not that one, so a test that leaves the
    argument out reads whatever the coordinator happened to write last.

    Measured on 2026-09-24: `pytest tests/test_coordinator_cycle_log.py` passes in the
    main checkout (193 lines in the live log) and fails 4 of 36 from an equal-based
    worktree of the same commit (3 lines). The live log is not gitignored either, so the
    suite's result depends on an operator-local file.

    Hermetic here is a claim the lab already makes in conftest's own words: "a full
    pytest run adds ZERO rows to run_state/". This check is that claim, inverted to the
    read side: no test may depend on live frontier rows, which the pytest cache cannot
    see and CI on a clean checkout would hit.
    """
    leaked = subprocess.run(
        ["git", "check-ignore", "-q", "--stdin"], cwd=lane.ROOT,
        input=b"run_state/frontier_calls.jsonl\n", capture_output=True).returncode == 0
    default = str(coordinator_cycle_log.DEFAULT_FRONTIER_CALLS)
    assert default.endswith("run_state/frontier_calls.jsonl")
    assert "tmp" in default or leaked, (
        "run_state/frontier_calls.jsonl is read by the health-signal tests through a "
        "module default that conftest does not redirect, so their result depends on "
        "live coordinator rows: add a `_no_live_artifacts` redirect for "
        "coordinator_cycle_log.DEFAULT_FRONTIER_CALLS (and loop_health's, if it reads "
        "the same file) or ignore the file. Evidence: 4 failures in a fresh worktree of "
        "the passing main commit.")
