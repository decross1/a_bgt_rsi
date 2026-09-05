"""Pure candidate packet checks: consistency/diff detection, not OS isolation.

No process, filesystem, environment, network, model or ledger operations.
Expected identities must come from the trusted admission/controller side,
and observations from independent Git/runner adapters. These predicates do
not authenticate a receipt author or qualify a model. Runtime is not wired.
"""
from __future__ import annotations

import re

from workers.claim_binding import (
    BindingError, canonical_bytes, digest, require_digest, require_id,
)


def _object(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        raise BindingError("missing or unknown fields")


def _git_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise BindingError("expected full SHA-1 Git object identity")
    return value


def _path(value, *, directory=False):
    if not isinstance(value, str) or not value or "\0" in value or "\\" in value:
        raise BindingError("invalid repository path")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise BindingError("invalid UTF-8 path") from exc
    path = value[:-1] if directory and value.endswith("/") else value
    if path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
        raise BindingError("path must be canonical and repository-relative")
    return path


def _absolute_path(value):
    if not isinstance(value, str) or not value.startswith("/"):
        raise BindingError("expected an absolute canonical path")
    _path(value[1:])
    return value


def pytest_argv(command: dict, *, approved_python: str) -> tuple[str, ...]:
    """Fixed grammar only. Test Python is still executable and needs confinement."""
    _object(command, ("kind", "nodes"))
    if command["kind"] != "pytest-v1" or type(command["nodes"]) is not list or not command["nodes"]:
        raise BindingError("unsupported test runner or empty nodes")
    _absolute_path(approved_python)
    for node in command["nodes"]:
        if not isinstance(node, str) or not re.fullmatch(
                r"tests/(?:[A-Za-z0-9_-]+/)*test_[A-Za-z0-9_]+\.py"
                r"(?:::[A-Za-z0-9_]+){0,2}(?:\[[A-Za-z0-9_.-]+\])?", node):
            raise BindingError("test node outside admitted argv grammar")
    if len(set(command["nodes"])) != len(command["nodes"]):
        raise BindingError("duplicate test node")
    return (approved_python, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            *command["nodes"])


def verify_red(receipt: dict, expected: dict) -> None:
    """Require one exact assertion failure from an independently trusted runner."""
    identities = ("attempt_id", "base_sha", "command_sha256")
    _object(expected, (*identities, "nodeid", "reason_sha256"))
    _object(receipt, (*identities, "kind", "exit_code", "launched", "timed_out",
                      "collection_errors", "setup_errors", "teardown_errors", "collected", "tests"))
    require_id(expected["attempt_id"])
    _git_sha(expected["base_sha"])
    require_digest(expected["command_sha256"])
    require_id(expected["nodeid"])
    require_digest(expected["reason_sha256"])
    if any(receipt[k] != expected[k] for k in identities):
        raise BindingError("red receipt identity mismatch")
    if receipt["kind"] != "pytest-receipt-v1" or type(receipt["exit_code"]) is not int \
            or receipt["exit_code"] != 1 or receipt["launched"] is not True \
            or receipt["timed_out"] is not False:
        raise BindingError("red receipt is not an executed failing test")
    if any(type(receipt[k]) is not int or receipt[k] != 0 for k in
           ("collection_errors", "setup_errors", "teardown_errors")):
        raise BindingError("infrastructure failures cannot be expected red evidence")
    tests = receipt["tests"]
    if type(tests) is not list or not tests or type(receipt["collected"]) is not int \
            or receipt["collected"] != len(tests):
        raise BindingError("missing or incomplete collected-test evidence")
    nodes, failures = [], []
    for test in tests:
        _object(test, ("nodeid", "phase", "outcome", "exception_type", "reason_sha256"))
        nodes.append(require_id(test["nodeid"]))
        if test["phase"] != "call" or test["outcome"] not in ("passed", "failed"):
            raise BindingError("only completed call-phase tests are admissible")
        if test["outcome"] == "failed":
            failures.append(test)
        elif test["exception_type"] is not None or test["reason_sha256"] is not None:
            raise BindingError("passing test carries contradictory failure evidence")
    if len(nodes) != len(set(nodes)) or len(failures) != 1:
        raise BindingError("expected exactly one unique failing node")
    failure = failures[0]
    if failure["nodeid"] != expected["nodeid"] or failure["exception_type"] != "AssertionError" \
            or failure["reason_sha256"] != expected["reason_sha256"]:
        raise BindingError("failure is not the exact expected assertion")


def verify_diff(raw: bytes, files_in_scope: list[str]) -> list[dict]:
    """Parse `git diff --raw -z --no-abbrev -M`; reject unsafe/ambiguous shapes.

    Both rename paths are checked. File/directory scopes differ by trailing /.
    Symlinks, gitlinks, copies, unmerged paths and non-UTF8 names fail closed.
    This cannot prevent a write that already occurred outside the Git diff.
    """
    if type(raw) is not bytes or type(files_in_scope) is not list or not files_in_scope:
        raise BindingError("raw bytes and explicit nonempty scope required")
    scopes = [(_path(p, directory=True), p.endswith("/")) for p in files_in_scope]
    if len(scopes) != len(set(scopes)):
        raise BindingError("duplicate scope")
    if not raw:
        return []
    if not raw.endswith(b"\0"):
        raise BindingError("raw diff lacks terminal NUL")
    pieces = raw[:-1].split(b"\0")
    i, seen, changes = 0, set(), []
    while i < len(pieces):
        try:
            header = pieces[i].decode("ascii")
            match = re.fullmatch(r":(\d{6}) (\d{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) (A|D|M|R\d{1,3})", header)
            if match is None:
                raise BindingError("unsupported raw diff header/status")
            oldmode, newmode, oldsha, newsha, status = match.groups()
            oldpath = pieces[i + 1].decode("utf-8")
            paths = [oldpath]
            i += 2
            if status.startswith("R"):
                if int(status[1:]) > 100:
                    raise BindingError("invalid rename similarity")
                paths.append(pieces[i].decode("utf-8"))
                i += 1
                if paths[0] == paths[1]:
                    raise BindingError("rename must change path")
        except (IndexError, UnicodeError) as exc:
            raise BindingError("truncated or undecodable raw diff") from exc
        regular = {"100644", "100755"}
        if status == "A":
            valid = oldmode == "000000" and oldsha == "0" * 40 and newmode in regular and newsha != "0" * 40
        elif status == "D":
            valid = newmode == "000000" and newsha == "0" * 40 and oldmode in regular and oldsha != "0" * 40
        else:
            valid = oldmode in regular and newmode in regular and oldsha != "0" * 40 and newsha != "0" * 40
            if status == "M":
                valid = valid and (oldmode != newmode or oldsha != newsha)
        if not valid:
            raise BindingError("unsafe file type or inconsistent diff modes/objects")
        for path in paths:
            _path(path)
            if path in seen:
                raise BindingError("duplicate/ambiguous changed path")
            seen.add(path)
            if not any((not directory and path == p) or
                       (directory and path.startswith(p + "/")) for p, directory in scopes):
                raise BindingError("changed path outside exact packet scope: " + path)
        changes.append(dict(status=status, paths=paths, old_mode=oldmode, new_mode=newmode,
                            old_sha=oldsha, new_sha=newsha))
    return changes


def verify_candidate(receipt: dict, observed: dict, *, raw_diff: bytes,
                     files_in_scope: list[str]) -> None:
    """Require a scoped change bound to independent candidate observations.

    The trusted adapter supplies actual base-to-candidate raw Git diff bytes;
    trusted admission supplies the contract's scope. This checks consistency,
    not those callers' authenticity, and performs no Git or filesystem reads.
    Empty parsed diffs belong to the separate abstention path.
    """
    ids = ("attempt_id", "contract_sha256", "base_sha", "before_sha", "after_sha",
           "diff_sha256", "command_sha256", "worker_id", "verifier_id")
    _object(observed, ids)
    _object(receipt, (*ids, "builder_exit_code", "builder_launched", "builder_timed_out",
                      "clean_tree", "scope", "verification"))
    for k in ("base_sha", "before_sha", "after_sha"):
        _git_sha(observed[k])
    for k in ("contract_sha256", "diff_sha256", "command_sha256"):
        require_digest(observed[k])
    for k in ("attempt_id", "worker_id", "verifier_id"):
        require_id(observed[k])
    if any(receipt[k] != observed[k] for k in ids):
        raise BindingError("candidate receipt differs from independently observed identity")
    if observed["before_sha"] != observed["base_sha"]:
        raise BindingError("builder did not start from the exact approved base")
    if observed["worker_id"] == observed["verifier_id"]:
        raise BindingError("worker cannot be its own verifier")
    if type(receipt["builder_exit_code"]) is not int or receipt["builder_exit_code"] != 0 \
            or receipt["builder_launched"] is not True or receipt["builder_timed_out"] is not False:
        raise BindingError("failed/unlaunched/timed-out builder cannot submit a candidate")
    if receipt["clean_tree"] is not True or observed["before_sha"] == observed["after_sha"]:
        raise BindingError("candidate is dirty or has no new commit")
    changes = verify_diff(raw_diff, files_in_scope)
    if digest(raw_diff) != observed["diff_sha256"]:
        raise BindingError("raw diff differs from independently observed digest")
    if not changes:
        raise BindingError("candidate requires nonempty validated changes")
    scope, verification = receipt["scope"], receipt["verification"]
    _object(scope, ("status", "candidate_sha", "diff_sha256"))
    _object(verification, ("status", "candidate_sha", "command_sha256", "verifier_id"))
    if scope != dict(status="passed", candidate_sha=observed["after_sha"], diff_sha256=observed["diff_sha256"]):
        raise BindingError("scope receipt does not bind the exact candidate diff")
    if verification != dict(status="passed", candidate_sha=observed["after_sha"],
                            command_sha256=observed["command_sha256"], verifier_id=observed["verifier_id"]):
        raise BindingError("trusted verification does not bind the exact candidate")


def worker_environment(*, private_home: str, private_tmp: str, approved_path: str,
                       attempt_id: str, contract_sha256: str) -> dict[str, str]:
    """Construct a positive environment from trusted values; read no ambient env."""
    for path in (private_home, private_tmp):
        _absolute_path(path)
    require_id(approved_path)
    for path in approved_path.split(":"):
        _absolute_path(path)
    return {"HOME": private_home, "TMPDIR": private_tmp, "PATH": approved_path,
            "LANG": "C.UTF-8", "PKT_ATTEMPT_ID": require_id(attempt_id),
            "PKT_CONTRACT_SHA256": require_digest(contract_sha256)}


def verify_model_binding(profile: dict, discovery: dict, completion: dict, *,
                         expected_profile_sha256: str) -> None:
    """Identity consistency only; qualification/freshness/authentication external."""
    fields = ("profile_id", "model_id", "artifact_sha256", "server_image_sha256",
              "tool_contract_sha256", "qualification_cursor_sha256", "sandbox_policy_sha256", "context_tokens")
    _object(profile, fields)
    if digest(canonical_bytes(profile)) != require_digest(expected_profile_sha256):
        raise BindingError("worker profile is not the independently approved bytes")
    require_id(profile["profile_id"])
    require_id(profile["model_id"])
    for k in fields[2:-1]:
        require_digest(profile[k])
    if type(profile["context_tokens"]) is not int or profile["context_tokens"] <= 0:
        raise BindingError("invalid context contract")
    if type(discovery) is not dict or type(discovery.get("data")) is not list:
        raise BindingError("missing model discovery evidence")
    ids = []
    for item in discovery["data"]:
        if type(item) is not dict:
            raise BindingError("malformed discovered model")
        ids.append(require_id(item.get("id")))
    if len(ids) != len(set(ids)) or profile["model_id"] not in ids \
            or type(completion) is not dict or completion.get("model") != profile["model_id"]:
        raise BindingError("configured/discovered/returned model identity mismatch")
