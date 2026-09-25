"""Receipt-bound thesis selection, deliberately separate from experiment authority.

Nara may only propose an immutable set of three to five full candidate cards.
Oracle supplies the evidence-bearing screen.  A meta-oracle acceptance is bound
to both digests, the deterministic top candidate, and the exact Git HEAD before
the focus pointer may change.  This module never writes loop memory, starts a
campaign, registers a study, or grants scientific credit.

Usage: Oracle first posts a plan declaring only the expected candidate-source
path, set identifier, and schema. Nara's real lane then commits the source on
its ``nara/<plan-msg-id>`` branch and emits the normal terminal receipt. The
candidate set binds that receipt's identity, row hash, branch, and head; the
selector resolves the declared path and blob at that immutable head. A plan
therefore never predicts an output digest it could not know yet. Only then can
Oracle ``screen`` and the receipt-bound ``meta-accept``/``select`` proceed.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import oracle_mailbox, research_focus


SCHEMA_SET = "thesis-candidate-set/v1"
SCHEMA_SCREEN = "thesis-oracle-screen/v1"
SCHEMA_ACCEPT = "thesis-meta-accept/v1"
DIRECTORY = "run_state/thesis_selection"
MAX_ARTIFACT_BYTES = 1_048_576
MAX_SOURCE_BLOB_BYTES = 1_048_576
MAX_EVIDENCE_ENTRIES = 12
MAX_SCAN_BYTES = 4 * MAX_ARTIFACT_BYTES
MAX_PRIMARY_SOURCE_BYTES = 512 * 1024
MAX_PRIMARY_SOURCE_TOTAL_BYTES = 4 * 1024 * 1024
MAX_FOCUS_RECEIPT_FILES = 64
MAX_GIT_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_MAILBOX_ROWS = 20_000
MAX_CHANGED_PATHS = 256
SHA = re.compile(r"[0-9a-f]{64}\Z")
IDENTITY = re.compile(r"[a-z0-9][a-z0-9-]{2,95}\Z")
VERDICTS = {"pass", "fail"}
PRIOR_STATUSES = {"verified", "unknown", "contradicted"}


class ThesisSelectionError(ValueError):
    """A selection artifact is malformed, stale, or has insufficient authority."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _object(raw: bytes) -> dict:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ThesisSelectionError("duplicate JSON key")
            out[key] = value
        return out

    def invalid(_value):
        raise ThesisSelectionError("non-finite JSON value")

    result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(result, dict):
        raise ThesisSelectionError("expected JSON object")
    return result


def _text(value: object, name: str, maximum: int = 1800) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ThesisSelectionError(f"invalid {name}")
    return value


def _time(value: object, name: str) -> str:
    value = _text(value, name, 80)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ThesisSelectionError(f"invalid {name}") from exc
    if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
        raise ThesisSelectionError(f"invalid {name}")
    return value


def _mailbox_time(value: object, name: str, *, allow_future: bool = False) -> datetime:
    """Strict, aware mailbox time in UTC; mailbox rows cannot claim the future."""
    value = _text(value, name, 80)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ThesisSelectionError(f"invalid {name}") from exc
    if parsed.tzinfo is None:
        raise ThesisSelectionError(f"invalid {name}")
    parsed = parsed.astimezone(timezone.utc)
    if not allow_future and parsed > datetime.now(timezone.utc):
        raise ThesisSelectionError(f"invalid {name}")
    return parsed


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ThesisSelectionError(f"invalid {name}")
    return value


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not IDENTITY.fullmatch(value):
        raise ThesisSelectionError(f"invalid {name}")
    return value


def _git(root: Path, *argv: str) -> str:
    try:
        # Keep untrusted Git output out of process memory until its bounded size
        # is known.  `show` callers additionally prove the blob's byte size with
        # cat-file before requesting content.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(["git", *argv], cwd=root, stdout=stdout, stderr=stderr)
            deadline = time.monotonic() + 10
            while process.poll() is None:
                stdout_size = os.fstat(stdout.fileno()).st_size
                stderr_size = os.fstat(stderr.fileno()).st_size
                if stdout_size > MAX_GIT_OUTPUT_BYTES or stderr_size > MAX_GIT_OUTPUT_BYTES:
                    # Output goes straight to files, not pipes, so terminating
                    # and waiting cannot deadlock on an undrained pipe.
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise ThesisSelectionError("required Git source object is unavailable")
                if time.monotonic() >= deadline:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise ThesisSelectionError("required Git source object is unavailable")
                time.sleep(0.005)
            stdout_size = os.fstat(stdout.fileno()).st_size
            stderr_size = os.fstat(stderr.fileno()).st_size
            if stdout_size > MAX_GIT_OUTPUT_BYTES or stderr_size > MAX_GIT_OUTPUT_BYTES or process.returncode:
                raise ThesisSelectionError("required Git source object is unavailable")
            stdout.seek(0)
            output = stdout.read().decode("utf-8")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ThesisSelectionError("required Git source object is unavailable") from exc
    except UnicodeDecodeError as exc:
        raise ThesisSelectionError("required Git source object is not UTF-8 text") from exc
    return output


def _git_regular_blob(root: Path, head: str, path: str) -> str:
    """Return the pinned blob OID while rejecting Git symlinks and trees."""
    tree = _git(root, "ls-tree", head, "--", path).strip().split(maxsplit=3)
    if (len(tree) != 4 or tree[0] not in {"100644", "100755"}
            or tree[1] != "blob" or tree[3] != path):
        raise ThesisSelectionError("pinned evidence is not a regular Git file")
    return tree[2]


def _safe_directory(root: Path, relative: str) -> Path:
    path = root / relative
    path.mkdir(parents=True, exist_ok=True)
    if path.resolve() != path or not path.is_dir():
        raise ThesisSelectionError("redirected thesis-selection directory")
    _fsync_directory_chain(root, path)
    return path


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_directory_chain(root: Path, directory: Path) -> None:
    try:
        parts = directory.relative_to(root).parts
    except ValueError as exc:
        raise ThesisSelectionError("thesis directory escapes repository") from exc
    parent = root
    for part in parts:
        child = parent / part
        _fsync_directory(parent)
        _fsync_directory(child)
        parent = child


def _write_all(fd: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(fd, raw[offset:])
        if not isinstance(written, int) or written <= 0:
            raise ThesisSelectionError("immutable thesis receipt write made no progress")
        offset += written


def _write_immutable(directory: Path, target: Path, raw: bytes) -> None:
    """Atomically make a content-addressed receipt visible after fsync."""
    temporary: Path | None = None
    for _attempt in range(3):
        candidate = directory / f".immutable-{os.getpid()}-{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        try:
            _write_all(fd, raw)
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            raise
        else:
            os.close(fd)
            temporary = candidate
            break
    if temporary is None:
        raise ThesisSelectionError("could not allocate immutable thesis receipt")
    try:
        os.link(temporary, target, follow_symlinks=False)
        _fsync_directory(directory)
    except FileExistsError:
        if _read_regular(target, MAX_ARTIFACT_BYTES) != raw:
            raise ThesisSelectionError("immutable thesis receipt collision")
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    _fsync_directory(directory)


def _write(root: Path, category: str, value: dict) -> str:
    directory = _safe_directory(root, f"{DIRECTORY}/{category}")
    raw = _canonical(value) + b"\n"
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ThesisSelectionError("thesis artifact exceeds read bound")
    digest = hashlib.sha256(raw).hexdigest()
    target = directory / f"{digest}.json"
    _write_immutable(directory, target, raw)
    return digest


def _load(root: Path, category: str, digest: str) -> dict:
    digest = _sha(digest, f"{category} sha256")
    path = root / DIRECTORY / category / f"{digest}.json"
    try:
        raw = _read_regular(path, MAX_ARTIFACT_BYTES)
    except OSError as exc:
        raise ThesisSelectionError("missing thesis receipt") from exc
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ThesisSelectionError("thesis receipt hash differs")
    return _object(raw)


def _read_regular(path: Path, limit: int) -> bytes:
    """Bounded stable read without following a leaf *or parent* symlink."""
    target = path if path.is_absolute() else Path.cwd() / path
    parts = target.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ThesisSelectionError("invalid untrusted evidence path")
    opened: list[int] = []
    try:
        directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(directory)
        for part in parts[1:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            opened.append(directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        opened.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ThesisSelectionError("untrusted evidence is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 1_048_576))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns, before.st_size)
        if len(raw) != before.st_size or len(raw) > limit or identity != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_size):
            raise ThesisSelectionError("untrusted evidence changed during read")
        return raw
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _validate_prior(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"status", "summary", "sources"}:
        raise ThesisSelectionError("invalid prior_work")
    if value["status"] not in PRIOR_STATUSES:
        raise ThesisSelectionError("invalid prior_work status")
    _text(value["summary"], "prior_work summary")
    sources = value["sources"]
    if not isinstance(sources, list) or len(sources) > 12:
        raise ThesisSelectionError("invalid prior_work sources")
    if value["status"] != "unknown" and not sources:
        raise ThesisSelectionError("non-unknown prior_work needs a source")
    for source in sources:
        if not isinstance(source, dict) or set(source) != {"locator", "claim", "source_path", "source_sha256"}:
            raise ThesisSelectionError("invalid prior_work source")
        _text(source["locator"], "prior_work locator", 800)
        _text(source["claim"], "prior_work claim", 1200)
        if (not isinstance(source["source_path"], str) or not source["source_path"]
                or len(source["source_path"]) > 240 or source["source_path"].startswith("/")
                or ".." in Path(source["source_path"]).parts):
            raise ThesisSelectionError("invalid prior_work source path")
        _sha(source["source_sha256"], "prior_work source sha256")


def _validate_card(card: object) -> None:
    if not isinstance(card, dict) or set(card) != {
        "candidate_id", "title", "lenses", "mechanism", "theory", "experiment", "applied", "prior_work", "anomaly_branches", "estimated_flash_hours", "conviction"
    }:
        raise ThesisSelectionError("candidate card must contain structured theory, experiment, applied, prior_work, and anomaly branches")
    candidate_id = _identity(card["candidate_id"], "candidate id")
    # The durable focus identifier adds the ``thesis-`` namespace.
    if len(candidate_id) > 89:
        raise ThesisSelectionError("candidate id is too long for a focus identity")
    _text(card["title"], "title")
    lenses = card["lenses"]
    allowed_lenses = {"behavioral_economics", "quantum_information", "strategic_games"}
    if (not isinstance(lenses, list) or not 1 <= len(lenses) <= len(allowed_lenses)
            or any(item not in allowed_lenses for item in lenses) or len(set(lenses)) != len(lenses)):
        raise ThesisSelectionError("candidate needs one or more thesis-brief lenses")
    _text(card["mechanism"], "mechanism", 1800)
    theory = card["theory"]
    theory_fields = {"game", "players", "actions", "information_structure", "solution_concept", "benchmark", "prediction", "falsifier", "predeclared_decision_rule"}
    if not isinstance(theory, dict) or set(theory) != theory_fields:
        raise ThesisSelectionError("theory needs game, information structure, solver, prediction, and falsifier")
    for key, item in theory.items():
        _text(item, f"theory {key}")
    experiment = card["experiment"]
    experiment_fields = {"benchmark", "arms", "sample_plan", "outcome", "falsifier"}
    if not isinstance(experiment, dict) or set(experiment) != experiment_fields:
        raise ThesisSelectionError("experiment needs benchmark, arms, sample plan, outcome, and falsifier")
    _text(experiment["benchmark"], "experiment benchmark")
    _text(experiment["outcome"], "experiment outcome")
    _text(experiment["falsifier"], "experiment falsifier")
    arms = experiment["arms"]
    if not isinstance(arms, list) or not 2 <= len(arms) <= 12:
        raise ThesisSelectionError("experiment needs two or more arms")
    arm_ids = []
    for arm in arms:
        if not isinstance(arm, dict) or set(arm) != {"arm_id", "treatment"}:
            raise ThesisSelectionError("invalid experiment arm")
        arm_ids.append(_identity(arm["arm_id"], "experiment arm id"))
        _text(arm["treatment"], "experiment arm treatment")
    if len(arm_ids) != len(set(arm_ids)):
        raise ThesisSelectionError("duplicate experiment arm")
    sample = experiment["sample_plan"]
    if not isinstance(sample, dict) or set(sample) != {"unit", "target_n", "missingness"}:
        raise ThesisSelectionError("experiment needs unit, target_n, and missingness")
    _text(sample["unit"], "sample unit")
    _text(sample["missingness"], "sample missingness")
    if isinstance(sample["target_n"], bool) or not isinstance(sample["target_n"], int) or sample["target_n"] < 1:
        raise ThesisSelectionError("invalid sample target_n")
    applied = card["applied"]
    applied_fields = {"venue", "data", "as_of", "measurement", "limitation"}
    if not isinstance(applied, dict) or set(applied) != applied_fields:
        raise ThesisSelectionError("applied route needs venue, data, as_of, measurement, and limitation")
    for key, item in applied.items():
        _text(item, f"applied {key}")
    _validate_prior(card["prior_work"])
    branches = card["anomaly_branches"]
    if not isinstance(branches, list) or not 2 <= len(branches) <= 8:
        raise ThesisSelectionError("candidate needs at least two anomaly branches")
    for branch in branches:
        if not isinstance(branch, dict) or set(branch) != {"outcome", "next_hypothesis"}:
            raise ThesisSelectionError("invalid anomaly branch")
        _text(branch["outcome"], "anomaly outcome")
        _text(branch["next_hypothesis"], "anomaly next_hypothesis")
    hours = card["estimated_flash_hours"]
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 < hours <= 24:
        raise ThesisSelectionError("invalid estimated_flash_hours")
    _validate_conviction(card["conviction"])


def _validate_conviction(value: object) -> dict:
    required = {"p_pass_t", "p_pass_s", "p_pass_a", "p_dead_end", "interest_0_10", "reasons"}
    if not isinstance(value, dict) or set(value) != required:
        raise ThesisSelectionError("invalid D-087 conviction")
    for key in ("p_pass_t", "p_pass_s", "p_pass_a", "p_dead_end"):
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not 0 <= item <= 1:
            raise ThesisSelectionError("invalid D-087 probability")
    interest = value["interest_0_10"]
    if isinstance(interest, bool) or not isinstance(interest, (int, float)) or not 0 <= interest <= 10:
        raise ThesisSelectionError("invalid D-087 interest")
    reasons = value["reasons"]
    if not isinstance(reasons, dict) or set(reasons) != required - {"reasons"}:
        raise ThesisSelectionError("D-087 reasons must cover every forecast")
    for reason in reasons.values():
        _text(reason, "D-087 reason", 1200)
    return value


def validate_candidate_set(value: dict) -> None:
    if set(value) != {"schema_version", "set_id", "proposed_at", "proposed_by", "source", "candidates", "execution_authorized", "scientific_credit"} or value.get("schema_version") != SCHEMA_SET:
        raise ThesisSelectionError("unsupported candidate set")
    _identity(value.get("set_id"), "set id")
    _time(value.get("proposed_at"), "proposed_at")
    if value.get("proposed_by") != "nara":
        raise ThesisSelectionError("candidate sets must be proposed by nara")
    source = value.get("source")
    if not isinstance(source, dict) or set(source) != {"receipt_msg_id", "receipt_row_sha256", "branch", "base_sha", "head_sha", "path", "blob_sha256", "git_blob_oid", "thesis_brief_path", "thesis_brief_sha256", "decision_path", "decision_sha256"}:
        raise ThesisSelectionError("candidate set needs a terminal Nara source receipt")
    _text(source["receipt_msg_id"], "candidate source receipt msg id", 160)
    _sha(source["receipt_row_sha256"], "candidate source receipt row sha256")
    if not isinstance(source["branch"], str) or not re.fullmatch(r"nara/[a-z0-9._/-]{1,120}", source["branch"]):
        raise ThesisSelectionError("candidate source must name a Nara branch")
    if not isinstance(source["head_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["head_sha"]):
        raise ThesisSelectionError("invalid candidate source head")
    if not isinstance(source["base_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["base_sha"]):
        raise ThesisSelectionError("invalid candidate source base")
    if not isinstance(source["path"], str) or not source["path"] or len(source["path"]) > 240 or source["path"].startswith("/") or ".." in Path(source["path"]).parts:
        raise ThesisSelectionError("invalid candidate source path")
    _sha(source["blob_sha256"], "candidate source blob sha256")
    if not isinstance(source["git_blob_oid"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["git_blob_oid"]):
        raise ThesisSelectionError("invalid candidate source Git blob")
    for path_key, sha_key, expected_path in (
        ("thesis_brief_path", "thesis_brief_sha256", "docs/v2/THESIS_BRIEF_2026-09-23.md"),
        ("decision_path", "decision_sha256", "DECISIONS.md"),
    ):
        if source[path_key] != expected_path:
            raise ThesisSelectionError("candidate source governance path differs")
        _sha(source[sha_key], "candidate source governance sha256")
    if value.get("execution_authorized") is not False or value.get("scientific_credit") != "none_proposal_only":
        raise ThesisSelectionError("candidate set cannot authorize or earn credit")
    cards = value.get("candidates")
    if not isinstance(cards, list) or not 3 <= len(cards) <= 5:
        raise ThesisSelectionError("candidate set must have three to five cards")
    ids = []
    for card in cards:
        _validate_card(card)
        ids.append(card["candidate_id"])
    if len(ids) != len(set(ids)):
        raise ThesisSelectionError("duplicate candidate id")


def create_candidate_set(repo_root: Path, value: dict) -> dict:
    """Persist Nara's complete proposal set; no selection happens here."""
    validate_candidate_set(value)
    digest = _write(Path(repo_root).resolve(), "candidate_sets", value)
    return {"candidate_set_sha256": digest, "candidate_count": len(value["candidates"]), "execution_authorized": False}


def _validate_evaluation(value: object, candidate_ids: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != {"candidate_id", "verdicts", "dimension_scores", "evidence", "reason"}:
        raise ThesisSelectionError("invalid candidate evaluation")
    if _identity(value["candidate_id"], "evaluation candidate id") not in candidate_ids:
        raise ThesisSelectionError("evaluation names unknown candidate")
    verdicts = value["verdicts"]
    required = {"theory", "experiment", "applied", "prior_work"}
    if not isinstance(verdicts, dict) or set(verdicts) != required or any(v not in VERDICTS for v in verdicts.values()):
        raise ThesisSelectionError("invalid screen verdict")
    scores = value["dimension_scores"]
    if not isinstance(scores, dict) or set(scores) != required or any(
        isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 3
        for score in scores.values()
    ):
        raise ThesisSelectionError("invalid evidence-scored dimensions")
    evidence = value["evidence"]
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ThesisSelectionError("screen evidence must cover every gate")
    for key, entries in evidence.items():
        if not isinstance(entries, list) or not entries or len(entries) > MAX_EVIDENCE_ENTRIES:
            raise ThesisSelectionError(f"screen evidence missing for {key}")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"locator", "note"}:
                raise ThesisSelectionError("invalid screen evidence")
            _text(entry["locator"], "screen evidence locator", 800)
            _text(entry["note"], "screen evidence note", 1600)
    _text(value["reason"], "screen reason")


def _source_declaration(value: object) -> dict:
    """The Oracle plan may name a source shape, never an unknown output hash."""
    if not isinstance(value, dict) or set(value) != {"schema_version", "set_id", "path", "base_sha"}:
        raise ThesisSelectionError("Oracle plan candidate source declaration is incomplete")
    if value.get("schema_version") != "nara-thesis-candidate-source/v1":
        raise ThesisSelectionError("Oracle plan candidate source schema differs")
    _identity(value.get("set_id"), "Oracle plan candidate source set id")
    path = value.get("path")
    if not isinstance(path, str) or not path or len(path) > 240 or path.startswith("/") or ".." in Path(path).parts:
        raise ThesisSelectionError("invalid Oracle plan candidate source path")
    if not isinstance(value.get("base_sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", value["base_sha"]):
        raise ThesisSelectionError("invalid Oracle plan candidate source base")
    return value


def _verify_candidate_provenance(root: Path, candidate_set: dict, candidate_set_sha256: str, *, admission: bool, rows: list[dict] | None = None) -> dict:
    """Bind cards to one terminal receipt and its exact Git output.

    Mailbox actor fields are unauthenticated routing/provenance labels.  They
    identify the lane contract being checked here; they do not authenticate a
    principal or turn selection into a security boundary.
    """
    source = candidate_set["source"]
    rows = _mailbox_rows(root / "run_state/oracle_nara_mailbox.jsonl") if rows is None else rows
    by_id = {row["msg_id"]: row for row in rows}
    receipt = by_id.get(source["receipt_msg_id"])
    if not isinstance(receipt, dict) or receipt.get("row_sha256") != source["receipt_row_sha256"]:
        raise ThesisSelectionError("candidate source terminal receipt identity differs")
    if receipt.get("actor") != "nara" or receipt.get("kind") != "receipt" or receipt.get("to") != "oracle":
        raise ThesisSelectionError("candidate source receipt is not a Nara receipt to Oracle")
    body = receipt.get("body")
    if not isinstance(body, dict) or body.get("state") != "validated":
        raise ThesisSelectionError("candidate source receipt is not a validated terminal receipt")
    if body.get("branch") != source["branch"] or body.get("head_sha") != source["head_sha"]:
        raise ThesisSelectionError("candidate source receipt branch or head differs")
    if body.get("base_sha") != source["base_sha"]:
        raise ThesisSelectionError("candidate source receipt base differs")
    plan = by_id.get(receipt.get("in_reply_to"))
    if not isinstance(plan, dict) or plan.get("actor") != "oracle" or plan.get("kind") != "plan_item" or plan.get("to") != "nara":
        raise ThesisSelectionError("candidate source receipt does not reply to an Oracle plan for Nara")
    declaration = _source_declaration(plan.get("body", {}).get("thesis_candidate_source"))
    if declaration != {"schema_version": "nara-thesis-candidate-source/v1", "set_id": candidate_set["set_id"], "path": source["path"], "base_sha": source["base_sha"]}:
        raise ThesisSelectionError("Oracle plan source declaration differs from candidate set")
    if source["branch"] != f"nara/{plan['msg_id']}":
        raise ThesisSelectionError("candidate source branch differs from real Nara lane branch")
    receipt_time = _mailbox_time(receipt.get("ts"), "Nara receipt ts", allow_future=False)
    plan_time = _mailbox_time(plan.get("ts"), "Oracle plan ts", allow_future=False)
    if plan_time > receipt_time:
        raise ThesisSelectionError("candidate source terminal receipt precedes its plan")
    expiry = plan.get("expires_at")
    if expiry is not None and receipt_time > _mailbox_time(expiry, "Oracle plan expires_at", allow_future=True):
        raise ThesisSelectionError("candidate source terminal receipt arrived after its plan expired")
    if admission:
        branch_head = _git(root, "rev-parse", source["branch"]).strip()
        if branch_head != source["head_sha"]:
            raise ThesisSelectionError("candidate source branch no longer names the receipted head")
    base_head = _git(root, "rev-parse", source["base_sha"]).strip()
    if base_head != source["base_sha"]:
        raise ThesisSelectionError("candidate source base commit is unavailable")
    try:
        ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", source["base_sha"], source["head_sha"]],
                                  cwd=root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ThesisSelectionError("candidate source ancestry is unavailable") from exc
    if ancestry.returncode != 0:
        raise ThesisSelectionError("candidate source head does not descend from the plan base")
    changed = _git(root, "diff", "--name-only", "--no-renames", f"{source['base_sha']}..{source['head_sha']}").splitlines()
    if len(changed) > MAX_CHANGED_PATHS:
        raise ThesisSelectionError("candidate source changed-file scan exceeds bound")
    allowed = set(plan.get("body", {}).get("allowed_write_paths", []))
    acceptance = plan.get("body", {}).get("acceptance", {})
    if isinstance(acceptance, dict) and isinstance(acceptance.get("test_path"), str):
        allowed.add(acceptance["test_path"])
    if (source["path"] not in changed or not changed or any(path not in allowed for path in changed)):
        raise ThesisSelectionError("candidate source changed files differ from the Nara plan allowance")
    size = _git(root, "cat-file", "-s", f"{source['head_sha']}:{source['path']}").strip()
    if not size.isascii() or not size.isdigit() or int(size) > MAX_SOURCE_BLOB_BYTES:
        raise ThesisSelectionError("candidate source blob exceeds read bound")
    if _git_regular_blob(root, source["head_sha"], source["path"]) != source["git_blob_oid"]:
        raise ThesisSelectionError("candidate source path/blob differs from pinned commit")
    raw = _git(root, "show", f"{source['head_sha']}:{source['path']}").encode()
    if hashlib.sha256(raw).hexdigest() != source["blob_sha256"]:
        raise ThesisSelectionError("candidate source blob hash differs")
    source_object = _object(raw)
    if set(source_object) != {"schema_version", "set_id", "candidates"} or source_object.get("schema_version") != "nara-thesis-candidate-source/v1" or source_object.get("set_id") != candidate_set["set_id"] or source_object.get("candidates") != candidate_set["candidates"]:
        raise ThesisSelectionError("tracked Nara source does not exactly contain this candidate set")
    for path_key, sha_key, label in (
        ("thesis_brief_path", "thesis_brief_sha256", "Thesis brief"),
        ("decision_path", "decision_sha256", "D-087 decision"),
    ):
        _git_regular_blob(root, source["head_sha"], source[path_key])
        evidence_size = _git(root, "cat-file", "-s", f"{source['head_sha']}:{source[path_key]}").strip()
        if not evidence_size.isascii() or not evidence_size.isdigit() or int(evidence_size) > MAX_PRIMARY_SOURCE_BYTES:
            raise ThesisSelectionError(f"{label} exceeds read bound")
        evidence_raw = _git(root, "show", f"{source['head_sha']}:{source[path_key]}").encode()
        if hashlib.sha256(evidence_raw).hexdigest() != source[sha_key]:
            raise ThesisSelectionError(f"{label} binding differs from candidate source")
    source_total = 0
    for card in candidate_set["candidates"]:
        for prior in card["prior_work"]["sources"]:
            path = prior["source_path"]
            if path == source["path"]:
                raise ThesisSelectionError("prior work cannot self-attest in the candidate source")
            # Nara may assemble and rank candidate cards, but it cannot mint the
            # prior work used to justify them in the same candidate commit.  The
            # exact evidence bytes must already exist at the plan-declared base
            # and survive unchanged at the receipted head.  This proves source
            # provenance only; Oracle's explicit prior_work screen below remains
            # the independent relevance judgment.
            try:
                base_blob = _git_regular_blob(root, source["base_sha"], path)
            except ThesisSelectionError as exc:
                raise ThesisSelectionError("prior work source is absent from the plan base") from exc
            head_blob = _git_regular_blob(root, source["head_sha"], path)
            if head_blob != base_blob:
                raise ThesisSelectionError("prior work source differs from the plan base")
            size = _git(root, "cat-file", "-s", f"{source['base_sha']}:{path}").strip()
            if not size.isascii() or not size.isdigit() or int(size) > MAX_PRIMARY_SOURCE_BYTES:
                raise ThesisSelectionError("primary source exceeds read bound")
            source_total += int(size)
            if source_total > MAX_PRIMARY_SOURCE_TOTAL_BYTES:
                raise ThesisSelectionError("primary source set exceeds read bound")
            primary_raw = _git(root, "show", f"{source['base_sha']}:{path}").encode()
            if (len(primary_raw) < 64 or hashlib.sha256(primary_raw).hexdigest() != prior["source_sha256"]
                    or prior["locator"].encode() not in primary_raw):
                raise ThesisSelectionError("prior work lacks substantive primary-source provenance")
    plan_index = rows.index(plan)
    receipt_index = rows.index(receipt)
    plan_receipts = [row for row in rows[plan_index + 1:] if row.get("actor") == "nara" and row.get("kind") == "receipt" and row.get("in_reply_to") == plan.get("msg_id")]
    if admission:
        reviews = [row for row in rows[plan_index + 1:receipt_index] if row.get("actor") in {"claude", "codex"} and row.get("kind") == "review" and row.get("in_reply_to") == plan.get("msg_id")]
        if not reviews or reviews[-1].get("body", {}).get("verdict") != "accept":
            raise ThesisSelectionError("latest plan review before Nara receipt does not accept")
        review_time = _mailbox_time(
            reviews[-1].get("ts"), "candidate source plan review ts", allow_future=False,
        )
        if not plan_time <= review_time <= receipt_time:
            raise ThesisSelectionError("candidate source plan review chronology is non-monotonic")
        if any(row.get("kind") == "withdraw" and row.get("in_reply_to") == plan.get("msg_id") for row in rows[plan_index + 1:receipt_index]):
            raise ThesisSelectionError("candidate source Oracle plan was withdrawn before receipt")
        if not plan_receipts or plan_receipts[-1].get("msg_id") != receipt.get("msg_id"):
            raise ThesisSelectionError("latest Nara plan receipt no longer supports this candidate source")
    return receipt


def _ranking(candidate_set: dict, evaluations: list[dict]) -> tuple[list[str], list[str]]:
    card_by_id = {card["candidate_id"]: card for card in candidate_set["candidates"]}
    evaluated = {row["candidate_id"]: row for row in evaluations}
    eligible = []
    for candidate_id, card in card_by_id.items():
        row = evaluated[candidate_id]
        passed = all(row["verdicts"][gate] == "pass" for gate in row["verdicts"])
        # Unknown related work is a truthful state, but cannot be silently treated
        # as a literature screen complete enough to select a research focus.
        if passed and card["prior_work"]["status"] == "verified":
            eligible.append(candidate_id)
    order = sorted(
        card_by_id,
        key=lambda ident: (
            ident not in eligible,
            -sum(evaluated[ident]["dimension_scores"].values()),
            ident,
        ),
    )
    return eligible, order


def _primary_source_refs(candidate_set: dict) -> set[str]:
    """Stable, content-bound references available for a reopened thesis."""
    return {
        f"{source['source_path']}@sha256:{source['source_sha256']}"
        for card in candidate_set["candidates"]
        for source in card["prior_work"]["sources"]
    }


def validate_screen(value: dict, candidate_set: dict) -> None:
    if set(value) != {"schema_version", "candidate_set_sha256", "screened_at", "screened_by", "evaluations", "eligible_ids", "ranking", "execution_authorized", "scientific_credit"} or value.get("schema_version") != SCHEMA_SCREEN:
        raise ThesisSelectionError("unsupported oracle screen")
    _sha(value.get("candidate_set_sha256"), "candidate set sha256")
    _time(value.get("screened_at"), "screened_at")
    if value.get("screened_by") != "oracle":
        raise ThesisSelectionError("screen must be made by oracle")
    if value.get("execution_authorized") is not False or value.get("scientific_credit") != "none_screen_only":
        raise ThesisSelectionError("screen cannot authorize or earn credit")
    candidate_ids = {card["candidate_id"] for card in candidate_set["candidates"]}
    evaluations = value.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != len(candidate_ids):
        raise ThesisSelectionError("screen must evaluate every candidate")
    for evaluation in evaluations:
        _validate_evaluation(evaluation, candidate_ids)
    if {row["candidate_id"] for row in evaluations} != candidate_ids:
        raise ThesisSelectionError("screen must evaluate each candidate once")
    eligible, ranking = _ranking(candidate_set, evaluations)
    if value.get("eligible_ids") != eligible or value.get("ranking") != ranking:
        raise ThesisSelectionError("screen eligibility or ranking is not deterministic")


def create_screen(repo_root: Path, candidate_set_sha256: str, value: dict) -> dict:
    root = Path(repo_root).resolve()
    candidate_set = _load(root, "candidate_sets", candidate_set_sha256)
    validate_candidate_set(candidate_set)
    if value.get("candidate_set_sha256") != candidate_set_sha256:
        raise ThesisSelectionError("screen candidate set digest differs")
    # The caller supplies findings; only rank outputs are derived by this code.
    evaluations = value.get("evaluations")
    if isinstance(evaluations, list):
        candidate_ids = {card["candidate_id"] for card in candidate_set["candidates"]}
        for evaluation in evaluations:
            _validate_evaluation(evaluation, candidate_ids)
        if {row.get("candidate_id") for row in evaluations} == candidate_ids:
            eligible, ranking = _ranking(candidate_set, evaluations)
            value = {**value, "eligible_ids": eligible, "ranking": ranking}
    validate_screen(value, candidate_set)
    digest = _write(root, "screens", value)
    return {"screen_sha256": digest, "eligible_ids": value["eligible_ids"], "ranking": value["ranking"], "execution_authorized": False}


def _head(root: Path) -> str:
    head = _git(root, "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ThesisSelectionError("repository HEAD is unavailable")
    return head


def _mailbox_rows(path: Path) -> list[dict]:
    """Return the canonical live rows from a lock-captured mailbox prefix.

    The final row hash is the decision cutoff: admission checks inspect every
    review through that tail. Rows appended after the shared lock is released
    belong to a later admission attempt (and are therefore seen by ``select``).
    Hash-valid evidence which fails the mailbox writer-derived identity or
    structural/relational predicates is retained in the file but quarantined
    from selection exactly as it is from every other live mailbox projection.
    """
    lock_path = path.parent / ".oracle_nara_mailbox.lock"
    try:
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            raw = _read_regular(path, 16 * 1024 * 1024)
            fcntl.flock(lock, fcntl.LOCK_UN)
    except OSError as exc:
        raise ThesisSelectionError("mailbox receipt is unavailable") from exc
    if len(raw) > 16 * 1024 * 1024 or (raw and not raw.endswith(b"\n")):
        raise ThesisSelectionError("mailbox exceeds bound or has incomplete tail")
    rows, previous = [], None
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        row = _object(line)
        claimed = row.get("row_sha256")
        check = dict(row)
        check.pop("row_sha256", None)
        if not isinstance(claimed, str) or not SHA.fullmatch(claimed) or row.get("prev_sha256") != previous or hashlib.sha256(_canonical(check)).hexdigest() != claimed:
            raise ThesisSelectionError(f"mailbox chain broken at line {number}")
        rows.append(row)
        if len(rows) > MAX_MAILBOX_ROWS:
            raise ThesisSelectionError("mailbox row scan exceeds bound")
        previous = claimed
    # Do not maintain a second, weaker mailbox schema here.  In particular,
    # oracle_mailbox.row_issue derives msg_id from the writer payload, which a
    # merely re-hashed forged row cannot satisfy.
    return oracle_mailbox.live_rows(rows)


def _selection_binding(value: object) -> dict:
    needed = {"candidate_set_sha256", "screen_sha256", "chosen_candidate_id", "reviewed_head", "focus_generation"}
    if not isinstance(value, dict) or set(value) != needed:
        raise ThesisSelectionError("mailbox thesis selection binding is incomplete")
    _sha(value["candidate_set_sha256"], "mailbox candidate set sha256")
    _sha(value["screen_sha256"], "mailbox screen sha256")
    _identity(value["chosen_candidate_id"], "mailbox chosen candidate")
    if not isinstance(value["reviewed_head"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["reviewed_head"]):
        raise ThesisSelectionError("mailbox reviewed head is invalid")
    try:
        research_focus._validate_generation(value["focus_generation"])
    except research_focus.FocusError as exc:
        raise ThesisSelectionError("mailbox focus generation is invalid") from exc
    return value


def _operational_focus(value: object, chosen: str) -> dict:
    """Canonical operational fields must be repeated by proposal and review."""
    required = {"focus_id", "title", "selection_reason", "next_action", "next_gate", "blockers", "stage", "intake_policy", "initial_convictions"}
    if not isinstance(value, dict) or set(value) != required:
        raise ThesisSelectionError("mailbox thesis operational focus is incomplete")
    if value["focus_id"] != f"thesis-{chosen}" or not IDENTITY.fullmatch(str(value["focus_id"])):
        raise ThesisSelectionError("operational focus id differs from chosen candidate")
    for key, maximum in (("title", 180), ("selection_reason", 1800), ("next_action", 900)):
        _text(value[key], f"operational {key}", maximum)
    if value["stage"] not in {"needs_clean_refinement", "blocked"} or value["intake_policy"] not in {"focus_before_new_topics", "observe_only"}:
        raise ThesisSelectionError("invalid operational focus stage or policy")
    if not isinstance(value["blockers"], list) or len(value["blockers"]) > 12:
        raise ThesisSelectionError("invalid operational focus blockers")
    for blocker in value["blockers"]:
        _text(blocker, "operational blocker", 600)
    gate = value["next_gate"]
    if not isinstance(gate, dict) or set(gate) != {"from", "to", "artifact", "status", "owner"} or gate.get("status") not in {"pending", "blocked"}:
        raise ThesisSelectionError("invalid operational next gate")
    for item in gate.values():
        _text(item, "operational next gate", 400)
    convictions = value["initial_convictions"]
    if not isinstance(convictions, dict) or set(convictions) != {"nara", "oracle", "claude"}:
        raise ThesisSelectionError("operational D-087 convictions are incomplete")
    for forecast in convictions.values():
        _validate_conviction(forecast)
    return value


def _verify_mailbox_accept(root: Path, value: dict, *, admission: bool, rows: list[dict] | None = None) -> tuple[dict, dict]:
    """Verify a hash-bound review record, without treating labels as identity."""
    rows = _mailbox_rows(root / "run_state/oracle_nara_mailbox.jsonl") if rows is None else rows
    by_id = {row.get("msg_id"): row for row in rows}
    review = by_id.get(value.get("review_msg_id"))
    proposal = by_id.get(value.get("proposal_msg_id"))
    if not isinstance(review, dict) or not isinstance(proposal, dict):
        raise ThesisSelectionError("meta review or oracle proposal is absent")
    if review.get("row_sha256") != value.get("review_row_sha256") or proposal.get("row_sha256") != value.get("proposal_row_sha256"):
        raise ThesisSelectionError("mailbox source hash differs")
    if review.get("actor") not in {"claude", "codex"} or review.get("kind") != "review" or review.get("in_reply_to") != proposal.get("msg_id"):
        raise ThesisSelectionError("meta acceptance requires a Claude or Codex review replying to Oracle")
    if not isinstance(review.get("body"), dict) or review["body"].get("verdict") != "accept":
        raise ThesisSelectionError("meta review did not accept")
    # Thesis selection deliberately avoids the owner-question/card channel.
    # A plain Oracle note binds the evidence proposal; a reviewer label remains
    # provenance metadata, not authenticated identity or owner authorization.
    if proposal.get("actor") != "oracle" or proposal.get("kind") != "note":
        raise ThesisSelectionError("selection must be proposed by an Oracle note in the mailbox")
    proposal_binding = _selection_binding(proposal.get("body", {}).get("thesis_selection"))
    review_binding = _selection_binding(review.get("body", {}).get("thesis_selection"))
    required = {
        "candidate_set_sha256": value["candidate_set_sha256"],
        "screen_sha256": value["screen_sha256"],
        "chosen_candidate_id": value["chosen_candidate_id"],
        "reviewed_head": value["reviewed_head"],
        "focus_generation": value["focus_generation"],
    }
    if proposal_binding != required or review_binding != required:
        raise ThesisSelectionError("mailbox review does not bind this exact selection")
    proposal_focus = _operational_focus(proposal.get("body", {}).get("thesis_focus"), required["chosen_candidate_id"])
    review_focus = _operational_focus(review.get("body", {}).get("thesis_focus"), required["chosen_candidate_id"])
    if proposal_focus != review_focus:
        raise ThesisSelectionError("meta review does not bind canonical operational focus fields")
    if admission:
        proposal_index = rows.index(proposal)
        review_index = rows.index(review)
        if review_index <= proposal_index:
            raise ThesisSelectionError("meta review precedes the selection proposal")
        verdicts = [row for row in rows[proposal_index + 1:] if row.get("actor") in {"claude", "codex"} and row.get("kind") == "review" and row.get("in_reply_to") == proposal.get("msg_id")]
        if not verdicts or verdicts[-1].get("msg_id") != review.get("msg_id") or verdicts[-1].get("body", {}).get("verdict") != "accept":
            raise ThesisSelectionError("latest meta verdict at admission does not accept this selection")
    return proposal, review


def _review_used(root: Path, review_msg_id: str) -> bool:
    directory = root / research_focus.DIRECTORY
    if not directory.exists() or directory.is_symlink():
        return False
    scanned = 0
    seen = 0
    for path in directory.iterdir():
        seen += 1
        if seen > MAX_FOCUS_RECEIPT_FILES:
            raise ThesisSelectionError("focus receipt scan exceeds file bound")
        if path.suffix != ".json" or path.name.startswith("."):
            continue
        remaining = MAX_SCAN_BYTES - scanned
        if remaining <= 0:
            raise ThesisSelectionError("focus receipt scan exceeds bound")
        try:
            size = path.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        if size > remaining:
            raise ThesisSelectionError("focus receipt scan exceeds bound")
        try:
            # The remaining aggregate budget is an individual read cap too;
            # an object cannot consume a fresh MiB when only one byte remains.
            raw = _read_regular(path, min(MAX_ARTIFACT_BYTES, remaining))
        except (OSError, ValueError):
            if remaining < MAX_ARTIFACT_BYTES:
                raise ThesisSelectionError("focus receipt scan exceeds bound")
            continue
        scanned += len(raw)
        if scanned > MAX_SCAN_BYTES:
            raise ThesisSelectionError("focus receipt scan exceeds bound")
        try:
            receipt = _object(raw)
        except ValueError:
            continue
        if receipt.get("schema_version") == research_focus.THESIS_SCHEMA and receipt.get("review_msg_id") == review_msg_id:
            return True
    return False


def validate_meta_accept(value: dict, screen: dict, *, root: Path | None = None,
                         current_head: str | None = None,
                         rows: list[dict] | None = None) -> None:
    if set(value) != {"schema_version", "candidate_set_sha256", "screen_sha256", "chosen_candidate_id", "reviewed_head", "focus_generation", "accepted_at", "review_msg_id", "review_row_sha256", "proposal_msg_id", "proposal_row_sha256", "execution_authorized", "scientific_credit"} or value.get("schema_version") != SCHEMA_ACCEPT:
        raise ThesisSelectionError("unsupported meta acceptance")
    _sha(value.get("candidate_set_sha256"), "candidate set sha256")
    if value.get("screen_sha256") != screen.get("_digest"):
        raise ThesisSelectionError("meta acceptance screen digest differs")
    if value.get("chosen_candidate_id") != (screen.get("ranking") or [None])[0] or value["chosen_candidate_id"] not in screen.get("eligible_ids", []):
        raise ThesisSelectionError("meta acceptance must choose deterministic eligible winner")
    head = value.get("reviewed_head")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ThesisSelectionError("invalid reviewed head")
    if current_head is not None and head != current_head:
        raise ThesisSelectionError("reviewed head is stale")
    try:
        research_focus._validate_generation(value.get("focus_generation"))
    except research_focus.FocusError as exc:
        raise ThesisSelectionError("meta acceptance focus generation is invalid") from exc
    if root is not None and current_head is not None and value["focus_generation"] != research_focus.selection_generation(root):
        raise ThesisSelectionError("reviewed focus generation is stale")
    _time(value.get("accepted_at"), "accepted_at")
    if value.get("execution_authorized") is not False or value.get("scientific_credit") != "none_accept_only":
        raise ThesisSelectionError("meta acceptance cannot authorize or earn credit")
    for key in ("review_msg_id", "proposal_msg_id"):
        _text(value.get(key), key, 160)
    for key in ("review_row_sha256", "proposal_row_sha256"):
        _sha(value.get(key), key)
    if root is not None:
        _verify_mailbox_accept(root, value, admission=current_head is not None, rows=rows)


def create_meta_accept(repo_root: Path, value: dict) -> dict:
    root = Path(repo_root).resolve()
    set_digest = _sha(value.get("candidate_set_sha256"), "candidate set sha256")
    screen_digest = _sha(value.get("screen_sha256"), "screen sha256")
    candidate_set = _load(root, "candidate_sets", set_digest)
    validate_candidate_set(candidate_set)
    rows = _mailbox_rows(root / "run_state/oracle_nara_mailbox.jsonl")
    source_receipt = _verify_candidate_provenance(root, candidate_set, set_digest, admission=True, rows=rows)
    screen = _load(root, "screens", screen_digest)
    screen["_digest"] = screen_digest
    if screen.get("candidate_set_sha256") != set_digest:
        raise ThesisSelectionError("screen candidate set digest differs")
    validate_screen({key: val for key, val in screen.items() if key != "_digest"}, candidate_set)
    if _mailbox_time(candidate_set["proposed_at"], "candidate proposed_at") < _mailbox_time(source_receipt["ts"], "Nara receipt ts"):
        raise ThesisSelectionError("candidate set predates its terminal Nara receipt")
    if _mailbox_time(screen["screened_at"], "screened_at") < _mailbox_time(candidate_set["proposed_at"], "candidate proposed_at"):
        raise ThesisSelectionError("screen predates candidate set")
    validate_meta_accept(value, screen, current_head=_head(root), root=root, rows=rows)
    proposal, review = _verify_mailbox_accept(root, value, admission=True, rows=rows)
    review_time = _mailbox_time(review["ts"], "meta review ts")
    if _mailbox_time(proposal["ts"], "selection proposal ts") < _mailbox_time(screen["screened_at"], "screened_at") or review_time < _mailbox_time(proposal["ts"], "selection proposal ts"):
        raise ThesisSelectionError("selection mailbox chronology is non-monotonic")
    if value["accepted_at"] != review["ts"]:
        raise ThesisSelectionError("accepted_at must equal the meta review timestamp")
    if rows.index(proposal) <= rows.index(source_receipt) or rows.index(review) <= rows.index(source_receipt):
        raise ThesisSelectionError("selection proposal and meta review must follow the Nara terminal receipt")
    digest = _write(root, "meta_accepts", value)
    return {"meta_accept_sha256": digest, "chosen_candidate_id": value["chosen_candidate_id"], "execution_authorized": False}


def select_thesis_focus(repo_root: Path, *, meta_accept_sha256: str, reason: str, expected_previous_sha256: str | None = None, _mailbox_locked: bool = False) -> dict:
    """Install one selection while its reviewed mailbox prefix remains frozen."""
    root = Path(repo_root).resolve()
    # Recovery precedes every live mailbox read.  Once preparation is fsynced,
    # its receipt, cutoff, generation, and exact D-087 payload are the only
    # transaction this invocation may finish; later reviewer rows cannot turn a
    # crash into orphaned conviction rows or a different selection decision.
    pending = research_focus.pending_prepared_thesis_focuses(root)
    if pending:
        prepared = pending[0]
        receipt = prepared["receipt"]
        if receipt["meta_accept_sha256"] != meta_accept_sha256:
            raise research_focus.FocusError("pending prepared thesis transaction must recover before a new selection")
        current = research_focus._prepared_focus_state(root)
        if current["status"] == "selected":
            # A caller cannot use a recovered receipt to mask a second CAS.
            if current.get("receipt_sha256") != prepared["receipt_sha256"]:
                raise research_focus.FocusError("refuse to overwrite an active focus; close it first")
            if expected_previous_sha256 != prepared["expected_previous_sha256"]:
                raise research_focus.FocusError("refuse to overwrite an active focus; close it first")
        if (reason != receipt["selection_reason"]
                or expected_previous_sha256 != prepared["expected_previous_sha256"]):
            raise ThesisSelectionError("prepared selection invocation differs from its frozen review")
        return research_focus.commit_prepared_thesis_focus(root, prepared)
    # A crash after the no-clobber link may report failure even though the
    # pointer is already durable.  The retained prepared receipt is the only
    # idempotency witness allowed to return that active selection.
    prepared = research_focus.find_prepared_thesis_focus(root, meta_accept_sha256=meta_accept_sha256)
    if prepared is not None:
        current = research_focus._prepared_focus_state(root)
        if current["status"] == "selected" and current["receipt_sha256"] == prepared["receipt_sha256"]:
            if expected_previous_sha256 != prepared["expected_previous_sha256"]:
                raise research_focus.FocusError("refuse to overwrite an active focus; close it first")
            if reason != prepared["receipt"]["selection_reason"]:
                raise ThesisSelectionError("prepared selection invocation differs from its frozen review")
            return research_focus.commit_prepared_thesis_focus(root, prepared)
    mailbox_path = root / "run_state/oracle_nara_mailbox.jsonl"
    if not _mailbox_locked:
        mailbox_path.parent.mkdir(parents=True, exist_ok=True)
        with (mailbox_path.parent / ".oracle_nara_mailbox.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            # The shared hold spans tail validation and pointer fsync below: a
            # reviewer either lands before this cutoff (and is considered), or
            # after a durable selected receipt has frozen the suffix.
            return select_thesis_focus(root, meta_accept_sha256=meta_accept_sha256, reason=reason,
                                       expected_previous_sha256=expected_previous_sha256, _mailbox_locked=True)
    rows = _mailbox_rows(mailbox_path)
    current = research_focus.project_focus(root)
    if current.get("status") == "selected":
        raise research_focus.FocusError("refuse to overwrite an active focus; close it first")
    if current.get("status") == "source_invalid":
        raise research_focus.FocusError("repair invalid focus explicitly before replacing it")
    accept = _load(root, "meta_accepts", meta_accept_sha256)
    set_digest = _sha(accept.get("candidate_set_sha256"), "candidate set sha256")
    screen_digest = _sha(accept.get("screen_sha256"), "screen sha256")
    candidate_set = _load(root, "candidate_sets", set_digest)
    validate_candidate_set(candidate_set)
    source_receipt = _verify_candidate_provenance(root, candidate_set, set_digest, admission=True, rows=rows)
    screen = _load(root, "screens", screen_digest)
    screen["_digest"] = screen_digest
    validate_screen({key: val for key, val in screen.items() if key != "_digest"}, candidate_set)
    validate_meta_accept(accept, screen, root=root, current_head=_head(root), rows=rows)
    proposal, _review = _verify_mailbox_accept(root, accept, admission=True, rows=rows)
    if rows.index(proposal) <= rows.index(source_receipt):
        raise ThesisSelectionError("selection proposal must follow the Nara terminal receipt")
    operational = _operational_focus(proposal["body"]["thesis_focus"], accept["chosen_candidate_id"])
    if reason != operational["selection_reason"]:
        raise ThesisSelectionError("selection reason must equal the reviewed canonical proposal")
    chosen = accept["chosen_candidate_id"]
    card = next(card for card in candidate_set["candidates"] if card["candidate_id"] == chosen)
    if operational["initial_convictions"]["nara"] != card["conviction"]:
        raise ThesisSelectionError("Nara initial conviction differs from the candidate source")
    receipt = {
        "schema_version": research_focus.THESIS_SCHEMA,
        "focus_id": operational["focus_id"],
        "title": operational["title"],
        "candidate_set_sha256": set_digest,
        "screen_sha256": screen_digest,
        "meta_accept_sha256": meta_accept_sha256,
        "review_msg_id": accept["review_msg_id"],
        "review_row_sha256": accept["review_row_sha256"],
        "proposal_msg_id": accept["proposal_msg_id"],
        "proposal_row_sha256": accept["proposal_row_sha256"],
        "chosen_candidate_id": chosen,
        "selection_head": accept["reviewed_head"],
        # Deterministic retry identity: the acceptance time is the immutable
        # selection time, so a crash between receipt fsync and pointer replace
        # can resume the exact same receipt under the focus lock.
        "selected_at": accept["accepted_at"],
        "selected_by": "oracle",
        "selection_reason": operational["selection_reason"],
        "stage": operational["stage"],
        "next_action": operational["next_action"],
        "next_gate": operational["next_gate"],
        "blockers": operational["blockers"],
        "intake_policy": operational["intake_policy"],
        "execution_authorized": False,
        "scientific_credit": "none_selection_only",
        "mailbox_cutoff_seq": rows[-1]["seq"],
        "mailbox_cutoff_sha256": rows[-1]["row_sha256"],
        "focus_generation": accept["focus_generation"],
        "initial_conviction_rows": [
            {"forecaster": forecaster, "row_sha256": digest}
            for forecaster, digest in _initial_conviction_refs(
                operational["focus_id"], accept["accepted_at"], operational["initial_convictions"]
            )
        ],
    }
    candidate_raw = research_focus.canonical(receipt) + b"\n"
    candidate_sha = hashlib.sha256(candidate_raw).hexdigest()
    existing = root / research_focus.DIRECTORY / f"{candidate_sha}.json"
    closures = research_focus._closures(root)
    if any(closure.get("focus_id") == operational["focus_id"] and closure.get("disposition") == "graduated" for closure in closures):
        raise ThesisSelectionError("a graduated thesis focus remains terminal")
    if any(closure.get("focus_receipt_sha256") == candidate_sha for closure in closures):
        raise ThesisSelectionError("meta review was already used by a closed focus")
    closure = research_focus._closure_tip(closures)
    if closure is not None and closure.get("focus_id") == operational["focus_id"] and closure.get("disposition") == "killed":
        reopening = _review.get("body", {}).get("reopening") if isinstance(_review.get("body"), dict) else None
        if (not isinstance(reopening, dict) or set(reopening) != {"closure_sha256", "condition", "evidence_refs"}
                or reopening.get("closure_sha256") != closure.get("closure_sha256")
                or not isinstance(reopening.get("evidence_refs"), list) or not reopening["evidence_refs"]):
            raise ThesisSelectionError("killed focus reopening must bind its closure and evidence")
        if (not isinstance(reopening.get("condition"), str)
                or reopening["condition"] not in closure.get("reopening_conditions", [])):
            raise ThesisSelectionError("killed focus reopening must record a closure condition")
        current_refs = _primary_source_refs(candidate_set)
        if (any(not isinstance(ref, str) for ref in reopening["evidence_refs"])
                or not set(reopening["evidence_refs"]).issubset(current_refs)):
            raise ThesisSelectionError("killed focus reopening evidence is not substantive source provenance")
        old_refs: set[str] = set()
        old_receipt = root / research_focus.DIRECTORY / f"{closure.get('focus_receipt_sha256')}.json"
        if old_receipt.is_file():
            old_focus = research_focus._object(research_focus._read(
                root, f"{research_focus.DIRECTORY}/{old_receipt.name}", 16384))
            if old_focus.get("schema_version") == research_focus.THESIS_SCHEMA:
                old_set = _load(root, "candidate_sets", old_focus["candidate_set_sha256"])
                validate_candidate_set(old_set)
                old_refs = _primary_source_refs(old_set)
        if not set(reopening["evidence_refs"]) - old_refs:
            raise ThesisSelectionError("killed focus reopening needs genuinely new primary evidence")
        closed_at = _mailbox_time(closure.get("closed_at"), "closure closed_at")
        if (_mailbox_time(source_receipt.get("ts"), "Nara receipt ts") <= closed_at
                and _mailbox_time(screen.get("screened_at"), "screened_at") <= closed_at):
            raise ThesisSelectionError("killed focus reopening reuses stale candidate and screen evidence")
    if _review_used(root, accept["review_msg_id"]) and not existing.is_file():
        raise ThesisSelectionError("meta review was already used by a focus")
    prepared = research_focus.prepare_thesis_focus(
        root, receipt, expected_previous_sha256=expected_previous_sha256,
        expected_generation=accept["focus_generation"], initial_convictions=operational["initial_convictions"],
    )
    return research_focus.commit_prepared_thesis_focus(root, prepared)


def _initial_conviction_refs(focus_id: str, selected_at: str, forecasts: dict) -> list[tuple[str, str]]:
    """Precompute final receipt references before any durable write occurs."""
    try:
        rows = research_focus._initial_conviction_rows(focus_id, selected_at, forecasts)
    except (KeyError, TypeError, research_focus.FocusError) as exc:
        raise ThesisSelectionError("initial D-087 forecasts are invalid") from exc
    return [(forecaster, rows[forecaster][2]) for forecaster in ("nara", "oracle", "claude")]


def verify_selection_sources(root: Path, receipt: dict) -> None:
    """Re-verify every source named by a v2 focus on each projection."""
    root = Path(root).resolve()
    rows = _mailbox_rows(root / "run_state/oracle_nara_mailbox.jsonl")
    cutoff_seq = receipt.get("mailbox_cutoff_seq")
    cutoff_sha = receipt.get("mailbox_cutoff_sha256")
    if (type(cutoff_seq) is not int or cutoff_seq < 1 or cutoff_seq > len(rows)
            or rows[cutoff_seq - 1].get("row_sha256") != cutoff_sha):
        raise ThesisSelectionError("focus mailbox cutoff is not present in the verified mailbox")
    candidate_set = _load(root, "candidate_sets", receipt["candidate_set_sha256"])
    validate_candidate_set(candidate_set)
    _verify_candidate_provenance(root, candidate_set, receipt["candidate_set_sha256"], admission=False, rows=rows)
    screen = _load(root, "screens", receipt["screen_sha256"])
    screen["_digest"] = receipt["screen_sha256"]
    if screen.get("candidate_set_sha256") != receipt["candidate_set_sha256"]:
        raise ThesisSelectionError("screen candidate set digest differs")
    validate_screen({key: value for key, value in screen.items() if key != "_digest"}, candidate_set)
    accept = _load(root, "meta_accepts", receipt["meta_accept_sha256"])
    if any(accept.get(key) != receipt.get(key) for key in (
        "candidate_set_sha256", "screen_sha256", "chosen_candidate_id",
        "review_msg_id", "review_row_sha256", "proposal_msg_id", "proposal_row_sha256", "focus_generation",
    )):
        raise ThesisSelectionError("focus source receipt differs")
    # A focus stays readable after unrelated repository progress.  HEAD and the
    # mutable Nara branch are admission-time guards, not a live-status lease.
    validate_meta_accept(accept, screen, root=root, current_head=None, rows=rows)
    if receipt["selection_head"] != accept["reviewed_head"]:
        raise ThesisSelectionError("focus selection head differs")
    proposal, _review = _verify_mailbox_accept(root, accept, admission=False, rows=rows)
    operational = _operational_focus(proposal["body"]["thesis_focus"], accept["chosen_candidate_id"])
    if any(receipt.get(key) != operational[key] for key in ("focus_id", "title", "selection_reason", "stage", "next_action", "next_gate", "blockers", "intake_policy")) or receipt.get("selected_at") != accept["accepted_at"] or receipt.get("selected_by") != "oracle":
        raise ThesisSelectionError("installed focus operational fields differ from reviewed canonical proposal")
    research_focus.verify_initial_convictions(
        root, receipt, expected_forecasts=operational["initial_convictions"]
    )


def _input(path: str) -> dict:
    return _object(_read_regular(Path(path), MAX_ARTIFACT_BYTES))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose")
    propose.add_argument("--input", required=True)
    screen = sub.add_parser("screen")
    screen.add_argument("--candidate-set", required=True)
    screen.add_argument("--input", required=True)
    accept = sub.add_parser("meta-accept")
    accept.add_argument("--input", required=True)
    select = sub.add_parser("select")
    select.add_argument("--meta-accept", required=True)
    select.add_argument("--reason", required=True)
    select.add_argument("--expected-previous-sha256")
    return parser


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = (repo_root or Path.cwd()).resolve()
    try:
        if args.command == "propose":
            result = create_candidate_set(root, _input(args.input))
        elif args.command == "screen":
            result = create_screen(root, args.candidate_set, _input(args.input))
        elif args.command == "meta-accept":
            result = create_meta_accept(root, _input(args.input))
        else:
            result = select_thesis_focus(root, meta_accept_sha256=args.meta_accept, reason=args.reason, expected_previous_sha256=args.expected_previous_sha256)
    except (OSError, ValueError, ThesisSelectionError, research_focus.FocusError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
