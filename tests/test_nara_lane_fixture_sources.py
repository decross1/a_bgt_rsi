"""Plan 2026-09-24 d3 slice 1 (G7.1): refuse a plan item whose fixture data does not
match the live files it claims to come from.

Why this exists (run_state/meta_oracle_reviews.jsonl, retro claude-fd99b8f6159965c4,
cause missing_context, three material postings on 2026-09-23; and nine postings of
plan 2026-09-24 d1 today): every nara_dev plan item's test fixtures were derived by
hand from live files, and they invented keys and enum values the live files do not
hold. The lane found each one only after a sandbox run, so every mistake cost a
posting, a review round and a hold. The retro's highest-value fix is to make the gate
refuse that before the sandbox, rather than to ask the author to be careful.

This is the first of three slices. The rejected d3 (oracle/2026-09-24-d3 @4b09dd2,
review claude-0404f2c56845b56f, seq 216) carried all of it in one 1,860-line rewrite
of the lane, cut from a stale base, and in doing so deleted main's concurrency, claim
and input-visibility work (tests/test_nara_lane_parallel.py's 26 tests, lane_concurrency(),
_claim_if_meta_accepts()) and added a .venv-chroma symlink to the tree. These three
slices are each cut from main and touch one thing:

  1 (this file) a declared fixture must match its live file, and a declaration with no
    fixture data behind it is refused - so fixture_sources can never be decorative.
  2 (oracle/2026-09-24-d3-fixture-binding, later) an item whose acceptance test is not
    bound to the fixture it ships is refused, and the lane materializes the fixture
    where the test can read it.
  3 (later still) a tracked precheck receipt must not admit an item.

Cases 1-6 here:

  1 a fixture key the live file does not hold is refused, naming the key
  2 a declared enum field holding a value the live file never holds is refused, naming
    the value; a field the fixture omits is skipped
  3 a fixture whose declared live path does not exist is refused
  4 a JSONL live file is judged row-by-row over rows of the fixture's own `kind`; a
    non-object row or an unparseable line is refused naming the file, and a `kind` the
    file never holds is refused naming the live kinds
  5 a live path that escapes the repo root is refused, by .., by absolute path, and by
    a symlink out of the tree
  6 fixture_sources / fixture_enums / fixtures are shape-checked at posting time, and a
    declaration for a fixture the item does not ship is refused there, so the two halves
    of the mistake (a source with nothing behind it, a fixture with nothing behind it)
    get one rule at one door
  7 ROOT itself is provenance, not an assumption: the same declaration is refused under
    an empty root, admitted under a root holding the file, refused when the file is not
    tracked by git, and admitted again pointed at THIS checkout. The rejected d3 read
    lane ROOT and asserted the shape it found there, so its checks were true only in the
    tree that wrote them.
  8 the rule is checked against the lab's own real files - the closure record
    tests/fixtures/payoff_closure_a1a65b36d71c1401.json is admitted against the live
    research-focus file it was copied from, and the same fixture with an invented key or
    an invented enum value is refused. This is the case that turns the gate on for real
    data rather than only for the scratch files cases 1-6 build.

What is deliberately NOT here: the fixture-to-test binding and materialization (slice
2), the precheck-receipt tracking rule (slice 3), the cycle-duration measurement (its
own branch, oracle/2026-09-24-cycle-timeout), and meta_review_fallbacks (its own item) -
none of them is a fixture-vs-live-file rule.

Hermetic: every case calls lane.admission() or mailbox.validate_plan_item() directly on
an in-memory item and points lane ROOT at a tmp_path scratch repo, the same redirect
tests/test_nara_lane_precheck.py uses. Nothing here calls the sandbox or the model
server; the whole file runs in well under a second.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

from orchestrator import nara_lane as lane
from orchestrator import oracle_mailbox as mailbox


# ── fixtures for the test itself ──────────────────────────────────────────────

FIXTURE_LIVE = {"schema_version": "research-focus/v1", "focus_id": "payoff-assistance",
                "status": "none", "execution_authorized": False}


def _repo(tmp_path, monkeypatch):
    """A scratch git repo that lane ROOT points at, so `root` in the path checks is
    tmp_path and not the real lab checkout. Returns the root."""
    root = tmp_path / "lab"
    root.mkdir()
    for arg in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(root), *arg], check=True, capture_output=True)
    (root / "run_state").mkdir()
    # A scratch repo has nothing tracked, so live files are tracked by fiat here;
    # test_a_source_resolves_under_whatever_checkout_runs_admission is where the
    # tracked/untracked line is actually tested, against a real `git ls-files`.
    monkeypatch.setattr(lane, "_fixture_is_tracked", lambda path, repo: True)
    monkeypatch.setattr(lane, "ROOT", root)
    monkeypatch.setattr(lane, "RUN_LOG", tmp_path / "run.jsonl")
    monkeypatch.setattr(lane, "log", lambda *a, **k: None)
    return root


def _live(root, rel, rows_or_obj):
    """Write a live file under the scratch root: a list becomes JSONL lines, a dict
    becomes one JSON document."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows_or_obj, list):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows_or_obj))
    else:
        path.write_text(json.dumps(rows_or_obj))
    return path


def item(sources=None, enums=None, fixtures=None, *,
         test_path="tests/test_fixture_sources_case.py",
         content="def test_v():\n    assert True\n"):
    """A plan item shaped exactly as the mailbox and the lane read it."""
    body = {"title": "fixture sources item", "objective": "x", "task_class": "tooling",
            "allowed_write_paths": ["tools/fixture_sources_case.py"],
            "acceptance": {"test_path": test_path, "test_content": content,
                           "test_argv": ["python", "-m", "pytest", "-q", test_path]}}
    if sources is not None:
        body["fixture_sources"] = sources
    if enums is not None:
        body["fixture_enums"] = enums
    if fixtures is not None:
        body["fixtures"] = fixtures
    return {"actor": "oracle", "msg_id": "oracle-fixture-sources", "seq": 1,
            "kind": "plan_item", "body": body}


def admit_only(item_row):
    """Refusal reasons from admission() with the precheck-receipt rule dropped, so each
    case below is about fixtures and not about the receipt every new test lacks."""
    return [r for r in lane.admission(item_row) if "precheck receipt" not in r]


# ── case 1: an invented key ───────────────────────────────────────────────────

def test_invented_fixture_key_is_refused_naming_the_key(tmp_path, monkeypatch):
    """The 2026-09-23 defect, exactly: a fixture copied by hand from a live file and
    given a key the file does not have. Refused at admission, and the reason names the
    key and the live keys, so the author does not have to guess what to fix."""
    root = _repo(tmp_path, monkeypatch)
    _live(root, "run_state/research_focus/abc.json", FIXTURE_LIVE)
    bad = dict(FIXTURE_LIVE, stage="T")          # `stage` is not in the live file
    reasons = admit_only(item(sources={"focus": "run_state/research_focus/abc.json"},
                              fixtures={"focus": bad}))
    assert len(reasons) == 1, reasons
    assert "stage" in reasons[0] and "live keys" in reasons[0], reasons[0]

    # mutation arm: the same item with the invented key removed is admitted clean, so
    # the refusal above is about the key and not about the declaration existing.
    assert admit_only(item(sources={"focus": "run_state/research_focus/abc.json"},
                           fixtures={"focus": dict(FIXTURE_LIVE)})) == []


# ── case 2: an enum value the live file never holds ───────────────────────────

def test_invented_enum_value_is_refused_naming_the_value(tmp_path, monkeypatch):
    """A str-valued field is not assumed to be an enum (that would refuse half of
    history); the item DECLARES which fields are enums, and a declared field holding a
    value no live row holds is refused, naming the value and the live values."""
    root = _repo(tmp_path, monkeypatch)
    # JSONL, because that is the shape of the lab's live state this gate reads
    # (run_state/oracle_nara_mailbox.jsonl, week1.run.jsonl). The JSON-file arm is case 1.
    _live(root, "run_state/research_focus/abc.jsonl",
          [dict(FIXTURE_LIVE, status=s) for s in ("none", "active")])
    src = {"focus": "run_state/research_focus/abc.jsonl"}

    refused = admit_only(item(sources=src, enums={"focus": ["status"]},
                              fixtures={"focus": dict(FIXTURE_LIVE, status="active")}))
    assert refused == [], refused                 # a value the file holds is fine

    bad = admit_only(item(sources=src, enums={"focus": ["status"]},
                          fixtures={"focus": dict(FIXTURE_LIVE, status="converged")}))
    assert len(bad) == 1 and "converged" in bad[0] and "live values" in bad[0], bad

    # a declared field the fixture omits is skipped, not refused: declaring an enum
    # field is a claim about the rows, not an obligation on every fixture.
    omit = dict(FIXTURE_LIVE)
    omit.pop("status")
    assert admit_only(item(sources=src, enums={"focus": ["status"]},
                           fixtures={"focus": omit})) == []

    # and an undeclared str field is never judged: focus_id is invented-able here and
    # nothing refuses it, because nothing declared it an enum.
    assert admit_only(item(sources=src, enums={"focus": ["status"]},
                           fixtures={"focus": dict(FIXTURE_LIVE, focus_id="whatever")})) == []


# ── case 3: a live path that does not exist ───────────────────────────────────

def test_missing_live_path_is_refused(tmp_path, monkeypatch):
    """d1 today was posted telling the builder to copy titles from a file that exists
    nowhere (review claude-e347ce59ca643116, seq 165). A declared source that is not on
    disk is refused at admission, so a path in a plan item means a file."""
    root = _repo(tmp_path, monkeypatch)
    _live(root, "run_state/research_focus/abc.json", FIXTURE_LIVE)
    reasons = admit_only(item(
        sources={"focus": "run_state/research_focus/abc.json",
                 "ghost": "run_state/never_written.json"},
        fixtures={"focus": dict(FIXTURE_LIVE), "ghost": {"whatever": 1}}))
    assert len(reasons) == 1 and "run_state/never_written.json" in reasons[0], reasons


# ── case 4: JSONL, judged row-by-row ─────────────────────────────────────────

def test_jsonl_live_file_is_accepted_and_bad_rows_refused(tmp_path, monkeypatch):
    """Most live lab state is JSONL (run_state/oracle_nara_mailbox.jsonl,
    run_state/week1.run.jsonl), where rows legitimately differ in shape by `kind`. Keys
    are therefore the union over rows of the fixture's own kind; a row that is not a
    JSON object and a line that does not parse are refused naming the file, because a
    row this check cannot judge must not be silently skipped."""
    root = _repo(tmp_path, monkeypatch)
    rows = [{"seq": 1, "actor": "oracle", "kind": "note", "body": {"title": "t"}},
            {"seq": 2, "actor": "nara", "kind": "receipt", "body": {"state": "validated"}}]
    _live(root, "run_state/oracle_nara_mailbox.jsonl", rows)
    src = {"mailbox_row": "run_state/oracle_nara_mailbox.jsonl"}

    # a row of each kind is admitted against the union of its own kind's keys
    assert admit_only(item(sources=src, fixtures={"mailbox_row": rows[0]})) == []
    assert admit_only(item(sources=src, fixtures={"mailbox_row": rows[1]})) == []

    # a key no row of that kind holds is refused
    invented = dict(rows[0], payload="x")
    bad = admit_only(item(sources=src, fixtures={"mailbox_row": invented}))
    assert len(bad) == 1 and "payload" in bad[0], bad

    # a `kind` the file never holds is refused naming the live kinds - it has no kind
    # cohort to borrow keys from, which is exactly when a hand-written fixture drifts.
    alien = {"seq": 9, "actor": "oracle", "kind": "forecast", "body": {"p": 0.5},
             "invented": 1}
    alien_reasons = admit_only(item(sources=src, fixtures={"mailbox_row": alien}))
    assert any("forecast" in r and "note" in r and "receipt" in r for r in alien_reasons), \
        alien_reasons

    # an unparseable line names the file, and is a refusal rather than a skip
    path = root / "run_state/oracle_nara_mailbox.jsonl"
    path.write_text(json.dumps(rows[0]) + "\nnot json at all\n")
    unparseable = admit_only(item(sources=src, fixtures={"mailbox_row": rows[0]}))
    assert len(unparseable) == 1 and "oracle_nara_mailbox.jsonl" in unparseable[0], unparseable

    # a non-object row does too
    path.write_text(json.dumps(rows[0]) + "\n[1, 2, 3]\n")
    non_object = admit_only(item(sources=src, fixtures={"mailbox_row": rows[0]}))
    assert len(non_object) == 1 and "object" in non_object[0], non_object


# ── case 5: the path stays inside the repo root ───────────────────────────────

def test_live_path_outside_the_repo_root_is_refused(tmp_path, monkeypatch):
    """Three ways out, all refused, none of them reaching the filesystem outside the
    scratch root: .., an absolute path, and a symlink that leaves the tree."""
    root = _repo(tmp_path, monkeypatch)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(FIXTURE_LIVE))

    for rel, why in (("../outside.json", "dotdot"), ("/" + str(outside), "absolute"),
                     ("run_state/link.json", "symlink")):
        if rel == "run_state/link.json":
            os.symlink(outside, root / "run_state/link.json")
        reasons = admit_only(item(sources={"focus": rel}, fixtures={"focus": dict(FIXTURE_LIVE)}))
        assert len(reasons) == 1 and "outside the repo" in reasons[0], (why, reasons)

    # mutation arm: the same fixture declared against a file that IS in the tree is
    # admitted, so the three refusals above are about the escape and not the fixture.
    _live(root, "run_state/research_focus/abc.json", FIXTURE_LIVE)
    assert admit_only(item(sources={"focus": "run_state/research_focus/abc.json"},
                           fixtures={"focus": dict(FIXTURE_LIVE)})) == []


# ── case 6: posting-time shapes, and a declaration with nothing behind it ─────

GOOD_BODY = {"title": "t", "objective": "o", "task_class": "tooling",
             "allowed_write_paths": ["tools/x.py"],
             "acceptance": {"test_path": "tests/test_x.py", "test_content": "x",
                            "test_argv": ["python", "-m", "pytest", "-q", "tests/test_x.py"]},
             "fixture_sources": {"focus": "run_state/research_focus/abc.json"},
             "fixture_enums": {"focus": ["stage"]},
             "fixtures": {"focus": {"stage": "T"}}}


def test_validate_plan_item_accepts_the_new_maps_and_rejects_other_shapes():
    """validate_plan_item is why fixture_sources was decorative on the rejected branch
    (review claude-56275cf790bac03c, finding 1): unknown keys pass it silently, so an
    author could declare the field and the lane would never see a shape it had to
    honor. Shapes are refused at posting, so admission() can trust them."""
    mailbox.validate_plan_item(GOOD_BODY)
    for bad in (["not", "a", "map"], {"f": 1}, {"f": ["run_state/x.json", "run_state/y.json"]},
                17, None):
        with pytest.raises(mailbox.MailboxError):
            mailbox.validate_plan_item(dict(GOOD_BODY, fixture_sources=bad))
    for bad in ({"f": "stage"}, {"f": [1]}, {"f": []}, "stage"):
        with pytest.raises(mailbox.MailboxError):
            mailbox.validate_plan_item(dict(GOOD_BODY, fixture_enums=bad))
    for bad in ({"../escape": {}}, {"f": "not an object"}, {"f": ["a"]}, ["list"], "x",
                {"": {"stage": "t"}}):
        with pytest.raises(mailbox.MailboxError):
            mailbox.validate_plan_item(dict(GOOD_BODY, fixtures=bad))
    # an enum declared for a fixture with no source is a field nothing can check
    with pytest.raises(mailbox.MailboxError):
        mailbox.validate_plan_item(dict(GOOD_BODY, fixture_sources={}))


def test_mailbox_rejects_an_unpaired_fixture_declaration_before_it_is_queued(tmp_path):
    path = tmp_path / "mailbox.jsonl"
    incomplete = dict(GOOD_BODY)
    incomplete.pop("fixtures")

    with pytest.raises(mailbox.MailboxError, match="fixtures"):
        mailbox.post("oracle", "plan_item", incomplete, to="nara", path=path)

    assert not path.exists()


def test_a_declaration_with_no_fixture_behind_it_is_refused(tmp_path, monkeypatch):
    """The same gap one layer down, at admission: `fixtures` was an unknown key to the
    old validate_plan_item, so a bare fixture_sources declaration passed every check
    while comparing nothing. A declaration must name a fixture the item actually ships,
    and an enum map must name a source that exists."""
    root = _repo(tmp_path, monkeypatch)
    _live(root, "run_state/research_focus/abc.json", FIXTURE_LIVE)

    # declared a source, shipped no fixture data at all
    reasons = admit_only(item(sources={"focus": "run_state/research_focus/abc.json"}))
    assert len(reasons) == 1 and "no fixtures.focus" in reasons[0], reasons

    # shipped a fixture under a different name than the one declared: both halves of the
    # mistake are named, because they are two different mistakes - a source with nothing
    # behind it, and a fixture with nothing behind it.
    reasons = admit_only(item(sources={"focus": "run_state/research_focus/abc.json"},
                              fixtures={"other": dict(FIXTURE_LIVE)}))
    assert len(reasons) == 1 and "no fixtures.focus" in reasons[0], reasons
    # the other half, at the posting gate: a shipped fixture no declaration names, so the
    # lane has no live file for it and no worktree path to write it to.
    with pytest.raises(mailbox.MailboxError):
        mailbox.validate_plan_item(dict(GOOD_BODY,
                                       fixtures={"focus": {"stage": "T"}, "other": {"k": 1}}))
    with pytest.raises(mailbox.MailboxError):        # and a fixture shipped with no source
        mailbox.validate_plan_item({"title": "t", "objective": "o", "task_class": "tooling",
                                    "allowed_write_paths": ["tools/x.py"],
                                    "acceptance": GOOD_BODY["acceptance"],
                                    "fixtures": {"synthetic": {"k": 1}}})

    # declared an enum for a fixture that is not shipped
    reasons = admit_only(item(sources={"focus": "run_state/research_focus/abc.json"},
                              enums={"focus": ["stage"]},
                              fixtures={"focus": dict(FIXTURE_LIVE)},
                              ))
    assert reasons == [], reasons          # focus IS shipped, so the enum has a subject
    with pytest.raises(mailbox.MailboxError):        # refused at posting, not at admission
        mailbox.validate_plan_item(dict(GOOD_BODY, fixture_enums={"ghost": ["stage"]},
                                       fixtures={"focus": {"stage": "T"}}))
    reasons = admit_only(item(sources={"focus": "run_state/research_focus/abc.json"},
                              enums={"ghost": ["stage"]},
                              fixtures={"focus": dict(FIXTURE_LIVE)}))
    assert len(reasons) == 1 and "fixture_enums.ghost" in reasons[0], reasons

    # mutation arm: source + enum + shipped fixture, all naming the same thing
    assert admit_only(item(sources={"focus": "run_state/research_focus/abc.json"},
                           enums={"focus": ["status"]},
                           fixtures={"focus": dict(FIXTURE_LIVE, status="none")})) == []


# ── case 7: the gate runs against the lab's own real files ────────────────────
#
# Cases 1-6 build their live files in a scratch repo, which is the same fixture-drift
# class this gate exists to end: a scratch file whose shape was decided by the person
# writing the test. This case points the gate at a real tracked file in this repo.
#
# The live file is run_state/frontier_calls.jsonl - the D-061 frontier-review ledger, one
# JSON object per call, 1,145 lines as of sha256
# 169a01b8b621fad0a1d7182b49be7881d71a90ae38399ed6d435d8e35a63d136, and every line holds
# the same eight keys. tests/fixtures/frontier_calls_tail_169a01b8_tracked.jsonl carries its last
# line, copied by a command (git show main:run_state/frontier_calls.jsonl | tail -1)
# rather than by hand, which is the whole point of the gate.
#
# The test reads these two paths out of its own directory rather than out of lane ROOT:
# the root that admission() resolves a fixture_sources path against is the checkout
# running admission(), and a test that read it from ROOT would pass in one checkout and
# fail in another, which is how the rejected d3 branch's own tests were written.

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"
FRONTIER_SNAPSHOT = FIXTURE_DIR / "frontier_calls_tail_169a01b8_tracked.jsonl"
FRONTIER_LIVE_REL = "run_state/frontier_calls.jsonl"


def _point_root_at_this_checkout(tmp_path, monkeypatch):
    """ROOT = this repo, so a fixture_sources path resolves to the real tracked file.
    The scratch-repo redirect in _repo() is for the path-fence cases; a live-file check
    has to run against the real one."""
    root = pathlib.Path(__file__).resolve().parents[1]
    monkeypatch.setattr(lane, "ROOT", root)
    monkeypatch.setattr(lane, "RUN_LOG", tmp_path / "run.jsonl")
    monkeypatch.setattr(lane, "log", lambda *a, **k: None)
    return root


def test_the_gate_reads_the_lab_own_real_ledger(tmp_path, monkeypatch):
    """The snapshot row is admitted against the real ledger it was copied from, and the
    same row with an invented key or an invented enum value is refused. Red on main for
    both halves at once: with no check there is nothing to refuse the invented row, and
    nothing to admit the real one - an empty reasons list for the bad fixture is exactly
    the silent pass this gate replaces."""
    root = _point_root_at_this_checkout(tmp_path, monkeypatch)
    live = root / FRONTIER_LIVE_REL
    assert live.is_file(), f"missing live file: {live}"
    snapshot = json.loads(FRONTIER_SNAPSHOT.read_text().splitlines()[0])

    src = {"frontier_row": FRONTIER_LIVE_REL}
    enums = {"frontier_row": ["vendor", "role"]}

    # the real row, copied by command out of the real file, is admitted
    assert admit_only(item(sources=src, enums=enums, fixtures={"frontier_row": snapshot})) == []

    # an invented key on that same row is refused, and the reason lists the live keys, so
    # the author sees the file's real shape instead of guessing at it
    invented = dict(snapshot, model="gpt-5")
    bad_key = admit_only(item(sources=src, enums=enums, fixtures={"frontier_row": invented}))
    assert len(bad_key) == 1 and "model" in bad_key[0] and "prompt_sha256" in bad_key[0], bad_key

    # an invented enum value on a declared field is refused naming the live values -
    # `verdict` is null on all 1,145 real lines, so a fixture claiming a verdict string
    # is describing a file the lab does not write
    invented_enum = dict(snapshot, vendor="torvalds")
    bad_enum = admit_only(item(sources=src, enums=enums, fixtures={"frontier_row": invented_enum}))
    assert len(bad_enum) == 1 and "torvalds" in bad_enum[0] and "claude" in bad_enum[0], bad_enum

    # and the snapshot really is a row of the live file, so the case above is testing the
    # gate rather than a snapshot that drifted from its source
    assert snapshot in [json.loads(line) for line in
                        live.read_text().splitlines() if line.strip()]


def test_a_source_resolves_under_whatever_checkout_runs_admission(tmp_path, monkeypatch):
    """The rejected d3 resolved a fixture path against lane ROOT and asserted the shape
    of the file it found, so its checks were true in the tree that wrote them. Here ROOT
    is redirected twice - to a scratch repo, then to this checkout - and the same
    declaration resolves to the file each root names. Provenance, not an assumption
    about which checkout happens to be running.

    The second half is the tracked/untracked line: a file that is not in git cannot be
    the live source a fixture is said to come from, because nothing would tell anyone
    when it changed. That distinction is what let the rejected branch's own
    precheck-receipt test pass while proving nothing (review claude-0404f2c56845b56f,
    seq 216), and it is asserted here rather than documented.
    """
    root = _repo(tmp_path, monkeypatch)
    rel = "run_state/research_focus/abc.json"
    src, fixtures = {"focus": rel}, {"focus": dict(FIXTURE_LIVE)}
    monkeypatch.setattr(lane, "_fixture_is_tracked", lambda path, repo: False)

    # an empty tree: the same declaration is refused, naming the file
    reasons = admit_only(item(sources=src, fixtures=fixtures))
    assert len(reasons) == 1 and rel in reasons[0], reasons

    # the same root, now holding the file and tracked: admitted, so the refusal above was
    # the missing file and not the declaration
    _live(root, rel, FIXTURE_LIVE)
    monkeypatch.setattr(lane, "_fixture_is_tracked", lambda path, repo: True)
    assert admit_only(item(sources=src, fixtures=fixtures)) == []

    # the file exists but git does not track it: refused, naming the reason
    monkeypatch.setattr(lane, "_fixture_is_tracked", lambda path, repo: False)
    untracked = admit_only(item(sources=src, fixtures=fixtures))
    assert len(untracked) == 1 and "not tracked by git" in untracked[0], untracked

    # and pointed at THIS checkout, the same declaration reads the real ledger
    here = pathlib.Path(__file__).resolve().parents[1]
    monkeypatch.setattr(lane, "ROOT", here)
    monkeypatch.setattr(lane, "_fixture_is_tracked", lambda path, repo: True)
    assert admit_only(item(sources={"frontier_row": FRONTIER_LIVE_REL},
                           fixtures={"frontier_row": json.loads(
                               FRONTIER_SNAPSHOT.read_text().splitlines()[0])})) == []
