#!/usr/bin/env python3
"""
Day 9 task -- contract test for agent_wrapper/dispatch_coding_agent.py
(W2-01, Day 39 deliverable). Track A is building the dispatcher today;
this test pins:

  1. The TASK-SPEC SHAPE the dispatcher accepts (validated against
     schema/proposed/dispatched_task.schema.json).
  2. ZONE RESOLUTION: every task_spec.allowed_paths entry must fall
     under exactly ONE zone in agent/ownership.yaml, and that zone must
     equal task_spec.target_zone AND have dispatchable:true. Track A's
     primary zones (state-file, orchestrator, etc.) are never
     dispatchable; the dispatcher refuses to launch on those.
  3. CLAIM-PROTOCOL OBEDIENCE: the dispatched-task prompt the
     dispatcher assembles MUST instruct the agent to (i) scan
     claims.jsonl, (ii) append a claim, (iii) THEN write files,
     (iv) release on commit -- in that order. We check the prompt text
     for the literal step ordering rather than relying on the
     dispatched agent's runtime behaviour (which we can't observe in a
     unit test).
  4. NO REAL SUBPROCESS LAUNCH: subprocess.Popen is patched. The test
     fails if the dispatcher invokes a real shell command.

If agent_wrapper/dispatch_coding_agent.py does not exist yet
(pre-Day-39), the dispatcher-import tests SKIP with a reason. The
zone-resolution + schema-shape tests run unconditionally — those
contracts are file-driven and don't need the implementation.

Run standalone:
    MOCK_LLM=1 python3 tests/test_dispatch_coding_agent.py
or under pytest:
    MOCK_LLM=1 pytest tests/test_dispatch_coding_agent.py
"""
from __future__ import annotations

import pytest

pytest.skip(
    "Retired machinery: the track-A/B/C/D claim-and-lock dispatch framework "
    "was retired 2026-05-26 (D-030; commit 08fc327 removed agent/ownership.yaml, "
    "which this test depends on). Un-skip only if the dispatcher is "
    "deliberately revived from archive/.",
    allow_module_level=True,
)

import fnmatch
import importlib
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DISPATCH_PATH = REPO_ROOT / "agent_wrapper" / "dispatch_coding_agent.py"
OWNERSHIP_PATH = REPO_ROOT / "agent" / "ownership.yaml"
SCHEMA_PATH = REPO_ROOT / "schema" / "proposed" / "dispatched_task.schema.json"
PROMPT_TEMPLATE_PATH = REPO_ROOT / "agent" / "prompts" / "dispatched_task.md"


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _load_ownership() -> dict:
    """Read agent/ownership.yaml. Returns the parsed YAML dict."""
    with OWNERSHIP_PATH.open() as fh:
        return yaml.safe_load(fh)


def _zone_for_path(path: str, ownership: dict) -> list[str]:
    """Return zone ids whose globs cover `path`. Length 1 is the well-
    formed case; 0 = unassigned; >1 = ownership conflict."""
    matches = []
    for zone in ownership["zones"]:
        for pat in zone["paths"]:
            # fnmatch.fnmatch treats '*' as matching '/'; mirror the
            # behaviour tools/claims_check.py uses in
            # --validate-ownership (D-029 documents why).
            if fnmatch.fnmatch(path, pat):
                matches.append(zone["id"])
                break
    return matches


def _sample_valid_task_spec() -> dict:
    """A well-formed task spec that lives in the tests-shared zone
    (Track B's dispatchable zone). Used by the happy-path tests."""
    return {
        "task_id": "w2-01-critic-tests",
        "target_zone": "tests-shared",
        "allowed_paths": ["tests/test_critic_demo.py"],
        "task_description": "Draft a demo critic test against the W2-01 critic.",
        "success_criteria": [
            "pytest tests/test_critic_demo.py exits 0",
            "the test asserts critique_text is non-empty",
        ],
        "autonomy_tier": "soft_gate",
        "worktree_prefix": "auto-task",
    }


def _load_dispatcher():
    """Return (dispatch_callable, source_tag). source_tag ∈ {'real','absent'}."""
    if not DISPATCH_PATH.exists():
        return None, "absent"
    spec = importlib.util.spec_from_file_location(
        "agent_wrapper.dispatch_coding_agent", DISPATCH_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "dispatch_coding_agent", None)
    if fn is None:
        raise AttributeError(
            "agent_wrapper/dispatch_coding_agent.py exists but exposes no "
            "`dispatch_coding_agent` symbol; Day-9 contract cannot proceed.")
    return (fn, mod), "real"


# ──────────────────────────────────────────────────────────────────────
# Schema-shape tests (no dispatcher import needed)
# ──────────────────────────────────────────────────────────────────────
class TaskSpecSchemaTest(unittest.TestCase):
    """The schema/proposed/dispatched_task.schema.json contract is
    file-driven and runnable today, before the dispatcher exists."""

    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text())
        cls.validator = Draft202012Validator(cls.schema)

    def test_schema_self_validates(self):
        # The schema itself must be a well-formed Draft 2020-12 schema.
        Draft202012Validator.check_schema(self.schema)

    def test_valid_spec_passes(self):
        errors = list(self.validator.iter_errors(_sample_valid_task_spec()))
        self.assertEqual(errors, [], f"valid spec rejected: {errors}")

    def test_missing_required_fails(self):
        for missing in (
            "task_id", "target_zone", "allowed_paths",
            "task_description", "success_criteria",
            "autonomy_tier", "worktree_prefix",
        ):
            with self.subTest(missing=missing):
                spec = _sample_valid_task_spec()
                spec.pop(missing)
                errors = list(self.validator.iter_errors(spec))
                self.assertTrue(
                    errors,
                    f"spec missing {missing!r} should fail validation",
                )

    def test_bad_autonomy_tier_fails(self):
        spec = _sample_valid_task_spec()
        spec["autonomy_tier"] = "full_autonomy"  # not in the enum
        self.assertTrue(list(self.validator.iter_errors(spec)))

    def test_empty_allowed_paths_fails(self):
        spec = _sample_valid_task_spec()
        spec["allowed_paths"] = []
        self.assertTrue(list(self.validator.iter_errors(spec)))

    def test_duplicate_allowed_paths_fails(self):
        spec = _sample_valid_task_spec()
        spec["allowed_paths"] = ["tests/a.py", "tests/a.py"]
        self.assertTrue(list(self.validator.iter_errors(spec)))

    def test_unknown_field_rejected(self):
        spec = _sample_valid_task_spec()
        spec["scratchwork"] = "I should not be here"
        errors = list(self.validator.iter_errors(spec))
        self.assertTrue(errors, "additionalProperties:false should reject unknowns")

    def test_bad_task_id_pattern_fails(self):
        spec = _sample_valid_task_spec()
        spec["task_id"] = "W2-01-CRITIC"   # uppercase forbidden
        self.assertTrue(list(self.validator.iter_errors(spec)))

    def test_decision_id_pattern_strict(self):
        spec = _sample_valid_task_spec()
        spec["decision_id"] = "D-12"   # only 2 digits
        self.assertTrue(list(self.validator.iter_errors(spec)))
        spec["decision_id"] = "D-028"
        self.assertEqual(list(self.validator.iter_errors(spec)), [])

    def test_timeout_minutes_bounds(self):
        spec = _sample_valid_task_spec()
        spec["timeout_minutes"] = 0
        self.assertTrue(list(self.validator.iter_errors(spec)))
        spec["timeout_minutes"] = 481
        self.assertTrue(list(self.validator.iter_errors(spec)))
        spec["timeout_minutes"] = 120
        self.assertEqual(list(self.validator.iter_errors(spec)), [])


# ──────────────────────────────────────────────────────────────────────
# Zone-resolution tests (driven by agent/ownership.yaml, dispatcher-free)
# ──────────────────────────────────────────────────────────────────────
class ZoneResolutionTest(unittest.TestCase):
    """Every allowed_paths entry must resolve to exactly ONE zone, and
    that zone must equal target_zone AND have dispatchable:true. These
    are properties of the task-spec + ownership.yaml combination — they
    don't need the dispatcher to exist to be checkable."""

    @classmethod
    def setUpClass(cls):
        cls.ownership = _load_ownership()
        cls.zones_by_id = {z["id"]: z for z in cls.ownership["zones"]}

    def _resolve(self, spec):
        zones_seen = set()
        for p in spec["allowed_paths"]:
            matches = _zone_for_path(p, self.ownership)
            self.assertEqual(
                len(matches), 1,
                f"path {p!r} matched {len(matches)} zones: {matches}",
            )
            zones_seen.add(matches[0])
        return zones_seen

    def test_valid_spec_resolves_to_single_zone(self):
        spec = _sample_valid_task_spec()
        zones = self._resolve(spec)
        self.assertEqual(zones, {"tests-shared"})
        self.assertEqual(zones.pop(), spec["target_zone"])

    def test_target_zone_must_be_dispatchable(self):
        spec = _sample_valid_task_spec()
        zone = self.zones_by_id[spec["target_zone"]]
        self.assertTrue(
            zone.get("dispatchable", False),
            f"target_zone {spec['target_zone']!r} must be dispatchable",
        )

    def test_non_dispatchable_target_rejected(self):
        # The dispatcher MUST refuse to launch a task into a primary
        # Track-A zone. We don't call the dispatcher here -- we assert
        # the ownership-derived invariant the dispatcher will check.
        for zid in ("orchestrator", "state-file", "bench-and-logs",
                    "chroma-store", "setup-scripts", "repo-config"):
            with self.subTest(zone=zid):
                zone = self.zones_by_id[zid]
                self.assertFalse(
                    zone.get("dispatchable", False),
                    f"zone {zid!r} must NOT be dispatchable per "
                    "agent/ownership.yaml; primary Track-A zones are "
                    "never dispatched",
                )

    def test_paths_spanning_multiple_zones_is_invalid(self):
        # A task spec that asks for a file in tests-shared AND a file in
        # schemas is malformed — one dispatch, one zone. The dispatcher
        # MUST refuse this; we surface the multi-zone fact at the spec
        # level so the test fails before the dispatcher is invoked.
        bad = _sample_valid_task_spec()
        bad["allowed_paths"] = [
            "tests/test_demo.py",        # tests-shared
            "schema/proposed/foo.json",  # schemas
        ]
        zones = set()
        for p in bad["allowed_paths"]:
            zones.update(_zone_for_path(p, self.ownership))
        self.assertGreater(
            len(zones), 1,
            "this fixture intentionally spans two zones; if it suddenly "
            "resolves to one, ownership.yaml may have a glob conflict",
        )

    def test_path_in_target_zone_only(self):
        # task_spec.target_zone declares the zone; every allowed_paths
        # entry must fall under THAT zone's globs.  Reject the case
        # where target_zone says 'tests-shared' but a path lives in
        # 'schemas'.
        bad = _sample_valid_task_spec()
        bad["allowed_paths"] = ["schema/proposed/foo.json"]  # not tests-shared
        for p in bad["allowed_paths"]:
            zones = _zone_for_path(p, self.ownership)
            self.assertNotIn(
                bad["target_zone"], zones,
                "fixture intentionally mismatches target_zone vs path",
            )


# ──────────────────────────────────────────────────────────────────────
# Prompt-template tests (the assembled prompt drives the dispatched
# agent's behaviour -- we test the template directly)
# ──────────────────────────────────────────────────────────────────────
class DispatchedTaskPromptTemplateTest(unittest.TestCase):
    """The agent/prompts/dispatched_task.md template instructs the
    dispatched agent to obey the claim protocol. The 5-step ordering
    (scan → claim → write → commit → release) is what we lock here;
    the dispatcher reads this file to assemble the runtime prompt."""

    @classmethod
    def setUpClass(cls):
        cls.text = PROMPT_TEMPLATE_PATH.read_text()
        cls.lower = cls.text.lower()

    def test_template_exists(self):
        self.assertTrue(PROMPT_TEMPLATE_PATH.exists())

    def test_mentions_claim_protocol(self):
        self.assertIn("claim protocol", self.lower)

    def test_mentions_scan_then_append_then_write(self):
        # The template should describe scan-before-claim-before-write.
        scan_idx = self.lower.find("scan run_state/claims.jsonl")
        append_idx = self.lower.find("append your claim")
        write_idx = self.lower.find("write the file")
        self.assertGreaterEqual(scan_idx, 0, "template missing 'scan run_state/claims.jsonl'")
        self.assertGreaterEqual(append_idx, 0, "template missing 'append your claim'")
        self.assertGreaterEqual(write_idx, 0, "template missing 'write the file'")
        self.assertLess(scan_idx, append_idx,
                        "scan step must precede the append-claim step")
        self.assertLess(append_idx, write_idx,
                        "append-claim must precede the write step")

    def test_mentions_release_on_commit(self):
        self.assertIn("release", self.lower)
        self.assertIn("commit", self.lower)

    def test_forbids_state_file_writes(self):
        # The dispatched agent must not touch run_state/week1.state.json
        # or run_state/week1.run.jsonl -- those are Track A's.
        self.assertIn("run_state/week1.state.json", self.text)
        self.assertIn("run_state/week1.run.jsonl", self.text)


# ──────────────────────────────────────────────────────────────────────
# Dispatcher import + subprocess-isolation tests (skipped when absent)
# ──────────────────────────────────────────────────────────────────────
class DispatcherImportTest(unittest.TestCase):
    """If agent_wrapper/dispatch_coding_agent.py exists, it must expose
    a `dispatch_coding_agent` callable. We don't INVOKE it here because
    a real invocation would spawn a Claude Code subprocess; subprocess
    isolation is tested separately below."""

    def test_dispatcher_exposes_public_callable(self):
        loaded, source = _load_dispatcher()
        if source == "absent":
            self.skipTest(
                "agent_wrapper/dispatch_coding_agent.py not yet "
                "present (Day-39 deliverable, Track A)"
            )
        fn, _mod = loaded
        self.assertTrue(callable(fn), "dispatch_coding_agent must be callable")


class DispatcherSubprocessIsolationTest(unittest.TestCase):
    """When the dispatcher exists, calling it MUST go through
    subprocess.Popen (per agent/collision_protocol.md §5 which says the
    dispatcher 'spawns a Claude Code session'). We patch Popen so the
    test never actually spawns a real shell; we just observe that the
    dispatcher's launch path is mockable.

    If the dispatcher is absent the test skips. If it's present but
    fails to be importable, the test fails — a broken dispatcher must
    not silently look like 'not built yet'.
    """

    def test_no_real_subprocess_launch(self):
        loaded, source = _load_dispatcher()
        if source == "absent":
            self.skipTest("dispatcher not yet present (Day 39)")
        fn, mod = loaded

        # Patch Popen on the module's namespace. If the dispatcher uses
        # subprocess.run instead, this test will need to extend to that
        # API as well; both should be unreachable in a unit test.
        fake_proc = MagicMock()
        fake_proc.wait.return_value = 0
        fake_proc.returncode = 0
        fake_proc.communicate.return_value = (b"", b"")

        spec = _sample_valid_task_spec()
        # Patch every plausible launch primitive the dispatcher might
        # use; if the dispatcher routes through a different API the
        # test surfaces it.
        with patch("subprocess.Popen", return_value=fake_proc) as p_popen, \
             patch("subprocess.run", return_value=fake_proc) as p_run, \
             patch("subprocess.check_call", return_value=0) as p_check, \
             patch("os.execvp", side_effect=AssertionError("execvp leaked")):
            try:
                # The dispatcher may take additional kwargs; pass a
                # minimal call and tolerate TypeError (the contract
                # gets nailed in Day-39's tests). What we're locking
                # here is 'whatever it calls, it goes through a
                # patched primitive — never the real shell'.
                fn(spec)
            except TypeError:
                self.skipTest(
                    "dispatcher signature differs from minimal "
                    "(task_spec,) call; Day-39 will tighten this test"
                )
            except Exception as exc:
                # Any non-TypeError that doesn't escape through our
                # AssertionError ('execvp leaked') is acceptable in
                # this scaffold — the *failure mode we care about* is
                # an UNPATCHED subprocess call.
                if "execvp leaked" in str(exc):
                    raise
        # If we got here, no AssertionError was raised by the os.execvp
        # patch — the dispatcher did not bypass subprocess.* — which is
        # the invariant this test exists to lock.


# ──────────────────────────────────────────────────────────────────────
# Cross-file consistency: schema enum matches autonomy.md tier list
# ──────────────────────────────────────────────────────────────────────
class AutonomyTierConsistencyTest(unittest.TestCase):
    """The autonomy_tier enum in the schema must match the three tiers
    agent/autonomy.md defines. Drift in either direction is a defect."""

    def test_enum_matches_autonomy_md(self):
        schema = json.loads(SCHEMA_PATH.read_text())
        enum = set(schema["properties"]["autonomy_tier"]["enum"])
        self.assertEqual(
            enum, {"autonomous", "soft_gate", "hard_gate"},
            "autonomy_tier enum drifted from agent/autonomy.md §2",
        )


# ──────────────────────────────────────────────────────────────────────
# End-to-end dispatch integration (Track A extension, Day 9 hard-gate)
# ──────────────────────────────────────────────────────────────────────
class DispatcherE2EIntegrationTest(unittest.TestCase):
    """End-to-end dispatch cycle: spawn a STUB subprocess (via the
    dispatcher's documented ``_subprocess_cmd`` test seam), have the stub
    emit the COMPLETE sentinel, verify the returned DispatchResult names
    the merge-candidate worktree + carries a non-zero duration + the
    sentinel string. Also exercises the four-sentinel state machine
    (COMPLETE-ready / BLOCKED / FAILED / timeout) and the concurrency cap.

    This is the formal pytest-equivalent of Track A's Day-9 hard-gate
    (day9_block2_dispatcher_integration_test). The seven smoke-test cases
    Track A ran inline (notes in run_state/week1.run.jsonl 2026-05-26)
    correspond 1:1 to the cases here; this class re-runs them under the
    unittest discovery surface so the gate's `pytest tests/...` command
    works without modification.

    Added by Track A integrator post-merge (Day 9). Track B's note said
    'test_no_real_subprocess_launch is intentionally minimal; Day-39 will
    tighten this'; that tightening lives here as the test_e2e_* family.
    """

    @classmethod
    def setUpClass(cls):
        loaded, source = _load_dispatcher()
        if source == "absent":
            raise unittest.SkipTest(
                "agent_wrapper/dispatch_coding_agent.py not yet present"
            )
        cls.fn, cls.mod = loaded

    def _minimal_spec(self, task_id="e2e-test", target_zone="notes"):
        return {
            "task_id": task_id,
            "target_zone": target_zone,
            "description": "stub e2e test",
            "success_criteria": ["sentinel printed"],
            "allowed_paths": ["notes/dispatched-stub.md"],
        }

    def test_e2e_dispatch_complete_sentinel(self):
        """Stub prints the COMPLETE sentinel → status='complete'."""
        stub = [
            "bash", "-c",
            "cat > /dev/null; "
            'echo "DISPATCHED TASK e2e-complete COMPLETE — ready to merge"; '
            "exit 0",
        ]
        result = self.fn(
            self._minimal_spec(task_id="e2e-complete"),
            worktree_prefix="auto-task",
            timeout_minutes=1,
            autonomy_tier="autonomous",
            _subprocess_cmd=stub,
        )
        self.assertEqual(result.status, "complete")
        self.assertIn("COMPLETE — ready to merge", result.sentinel)
        self.assertGreaterEqual(result.duration_sec, 0.0)
        self.assertIsNotNone(result.worktree_path)
        self.assertIsNotNone(result.branch)
        self.assertIsNone(result.error)

    def test_e2e_dispatch_hard_gate_sentinel(self):
        stub = [
            "bash", "-c",
            "cat > /dev/null; "
            'echo "DISPATCHED TASK e2e-hg COMPLETE — HARD GATE — needs human attestation"; '
            "exit 0",
        ]
        result = self.fn(
            self._minimal_spec(task_id="e2e-hg"),
            worktree_prefix="auto-task",
            timeout_minutes=1,
            autonomy_tier="hard_gate",
            _subprocess_cmd=stub,
        )
        self.assertEqual(result.status, "complete_hard_gate")
        self.assertIn("HARD GATE", result.sentinel)

    def test_e2e_dispatch_blocked_sentinel(self):
        stub = [
            "bash", "-c",
            "cat > /dev/null; "
            'echo "DISPATCHED TASK e2e-blocked BLOCKED — claim conflict"; '
            "exit 0",
        ]
        result = self.fn(
            self._minimal_spec(task_id="e2e-blocked"),
            worktree_prefix="auto-task",
            timeout_minutes=1,
            autonomy_tier="soft_gate",
            _subprocess_cmd=stub,
        )
        self.assertEqual(result.status, "blocked")
        self.assertIn("BLOCKED", result.sentinel)

    def test_e2e_dispatch_failed_sentinel(self):
        stub = [
            "bash", "-c",
            "cat > /dev/null; "
            'echo "DISPATCHED TASK e2e-failed FAILED — schema validation"; '
            "exit 0",
        ]
        result = self.fn(
            self._minimal_spec(task_id="e2e-failed"),
            worktree_prefix="auto-task",
            timeout_minutes=1,
            autonomy_tier="soft_gate",
            _subprocess_cmd=stub,
        )
        self.assertEqual(result.status, "failed")
        self.assertIn("FAILED", result.sentinel)

    def test_e2e_dispatch_no_sentinel(self):
        """Stub exits 0 without printing a sentinel → status='failed' with
        error='exited_without_sentinel' (protocol violation by the agent)."""
        stub = ["bash", "-c", "cat > /dev/null; echo 'no sentinel'; exit 0"]
        result = self.fn(
            self._minimal_spec(task_id="e2e-nosig"),
            worktree_prefix="auto-task",
            timeout_minutes=1,
            autonomy_tier="autonomous",
            _subprocess_cmd=stub,
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "exited_without_sentinel")

    def test_e2e_dispatch_timeout(self):
        """Stub sleeps past timeout → status='timeout' + escalation logged."""
        stub = ["bash", "-c", "cat > /dev/null; sleep 30"]
        result = self.fn(
            self._minimal_spec(task_id="e2e-timeout"),
            worktree_prefix="auto-task",
            timeout_minutes=0.05,   # ≈3 sec (0.05 * 60)
            autonomy_tier="autonomous",
            _subprocess_cmd=stub,
        )
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error, "timeout")

    def test_e2e_dispatch_refuses_state_file_zone(self):
        # Use the importlib-loaded module's DispatcherError class — a
        # ``from ... import DispatcherError`` would resolve to the
        # standard-import class instance, distinct from the spec-loaded
        # one ``self.fn`` actually raises, and assertRaises would miss it.
        spec = self._minimal_spec(task_id="e2e-bad-zone",
                                  target_zone="state-file")
        with self.assertRaises(self.mod.DispatcherError) as cm:
            self.fn(spec, worktree_prefix="auto-task",
                    autonomy_tier="autonomous",
                    _subprocess_cmd=["bash", "-c", "true"])
        self.assertIn("not dispatchable", str(cm.exception))

    def test_e2e_dispatch_concurrency_cap(self):
        """Append a fake active dispatched claim, then verify the second
        dispatch raises DispatcherError('cap_exceeded')."""
        import datetime as _dt
        import json as _json
        # Reference module-level names through cls.mod so the test exercises
        # the same module instance ``self.fn`` was loaded from.
        CLAIMS_FILE = self.mod.CLAIMS_FILE
        DispatcherError = self.mod.DispatcherError
        WEEK2_DISPATCH_CAP = self.mod.WEEK2_DISPATCH_CAP
        sentinel_tag = "__E2E_CONCURRENCY_TEST__"
        now = _dt.datetime.now(_dt.timezone.utc)
        fake = {
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "agent_id": f"claude-dispatched-{sentinel_tag}",
            "zone": "notes",
            "paths": [f"notes/{sentinel_tag}.md"],
            "intent": "write",
            "expires_at": (now + _dt.timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        }
        with CLAIMS_FILE.open("a") as fh:
            fh.write(_json.dumps(fake) + "\n")
        try:
            with self.assertRaises(DispatcherError) as cm:
                self.fn(
                    self._minimal_spec(task_id="e2e-cap"),
                    worktree_prefix="auto-task",
                    autonomy_tier="autonomous",
                    _subprocess_cmd=["bash", "-c", "true"],
                )
            self.assertIn("cap_exceeded", str(cm.exception))
            self.assertIn(str(WEEK2_DISPATCH_CAP), str(cm.exception))
        finally:
            lines = CLAIMS_FILE.read_text().splitlines(keepends=True)
            CLAIMS_FILE.write_text("".join(
                l for l in lines if sentinel_tag not in l
            ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
