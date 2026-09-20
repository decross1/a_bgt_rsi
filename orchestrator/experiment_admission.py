"""Source-bound admission for V2 empirical evidence.

An experiment outcome is model input.  It is not evidence merely because it
has ``trials`` and a plausible summary.  This module reruns an allowlisted,
study-specific verifier, binds its raw artifacts to the registered campaign,
topic, study and preregistration, and writes one content-addressed receipt.

The I/O boundary returns a sealed :class:`AdmissionContext`.  Evidence-ladder
derivation remains pure and can only consume that context; a row-carried
``verified`` flag or a copied receipt dictionary has no authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA = "experiment-admission/v1"
REFERENCE_SCHEMA = "experiment-admission-ref/v1"
RECEIPT_DIRECTORY = "run_state/experiment_admissions"
MAX_RECEIPT_BYTES = 32_768
MAX_ARTIFACT_BYTES = 2_000_000
MAX_REGISTERED_BYTES = 512_000

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9._/-]{2,127}\Z")
_CONTEXT_SEAL = object()


class AdmissionError(ValueError):
    """An empirical outcome is not bound to admitted registered evidence."""


@dataclass(frozen=True)
class AdmissionRequest:
    """A selector into a closed verifier/artifact-root registry."""

    verifier_id: str
    artifact_root_id: str
    artifact_subpath: str


@dataclass(frozen=True)
class VerifierSpec:
    """Trusted code-side declaration for one registered study verifier."""

    verifier_id: str
    campaign_id: str
    study_id: str
    metric: str
    verifier_source_path: str
    raw_result_path: str
    unit_name: str
    evidence_kind: str
    l2_capable: bool
    artifact_roots: Mapping[str, Path]
    validator_loader: Callable[[], Callable[[Path], dict[str, Any]]]
    outcome_builder: Callable[[dict[str, Any]], dict[str, Any]]
    unit_count_field: str = "recorded_episodes"
    raw_result_sha256_field: str = "run_sha256"


@dataclass(frozen=True)
class AdmissionContext:
    """Pure, row-bound result of replaying one immutable admission receipt."""

    receipt_sha256: str
    reference_sha256: str
    campaign_link_sha256: str
    outcome_sha256: str
    study_id: str
    independent_units: int
    unit_name: str
    evidence_kind: str
    l2_capable: bool
    _seal: object = field(repr=False, compare=False)

    def l2_failures(self, row: dict[str, Any], minimum_units: int) -> list[str]:
        """Return pure failures binding this verified context to ``row``."""
        if self._seal is not _CONTEXT_SEAL:
            return ["experiment admission context is not verifier-produced"]
        reference = row.get("experiment_admission_ref")
        try:
            reference_sha = _sha256(_canonical(reference))
        except AdmissionError:
            return ["experiment_admission_ref is absent or malformed"]
        if reference_sha != self.reference_sha256:
            return ["experiment admission context belongs to a different reference"]
        try:
            link_sha = _sha256(_canonical(row.get("campaign")))
            outcome_sha = outcome_sha256(row.get("experiment_outcome"))
        except AdmissionError:
            return ["experiment admission row binding is malformed"]
        failures: list[str] = []
        if link_sha != self.campaign_link_sha256:
            failures.append("experiment admission campaign/topic binding differs")
        if outcome_sha != self.outcome_sha256:
            failures.append("experiment admission outcome hash differs")
        if not self.l2_capable:
            failures.append(
                f"verified evidence kind {self.evidence_kind!r} cannot earn L2"
            )
        if self.independent_units < minimum_units:
            failures.append(
                f"verified {self.unit_name}={self.independent_units} "
                f"(need >= {minimum_units})"
            )
        return failures


@dataclass(frozen=True)
class AdmissionBundle:
    """Reference for the durable row plus its already-verified pure context."""

    reference: dict[str, Any]
    context: AdmissionContext


_RECEIPT_FIELDS = {
    "schema_version",
    "verifier_id",
    "verifier_source_path",
    "verifier_source_sha256",
    "campaign_id",
    "campaign_manifest_sha256",
    "campaign_link_sha256",
    "topic_id",
    "topic_sha256",
    "study_id",
    "study_manifest_path",
    "study_manifest_sha256",
    "preregistration_path",
    "preregistration_sha256",
    "artifact_root_id",
    "artifact_subpath",
    "raw_result_path",
    "raw_result_sha256",
    "outcome_sha256",
    "metric",
    "unit_name",
    "independent_units",
    "evidence_kind",
    "l2_capable",
    "admission_eligible",
}

_REFERENCE_FIELDS = {
    "schema_version",
    "receipt_path",
    "receipt_sha256",
    "verifier_id",
    "campaign_id",
    "campaign_manifest_sha256",
    "topic_id",
    "topic_sha256",
    "study_id",
    "outcome_sha256",
    "unit_name",
    "independent_units",
    "evidence_kind",
}


def _must(condition: bool, reason: str) -> None:
    if not condition:
        raise AdmissionError(reason)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AdmissionError("admission value is not finite canonical JSON") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def outcome_sha256(outcome: Any) -> str:
    _must(type(outcome) is dict and bool(outcome), "experiment outcome is absent")
    return _sha256(_canonical(outcome))


def _strict_object(raw: bytes, where: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            _must(key not in value, f"duplicate JSON field in {where}")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw,
            object_pairs_hook=unique,
            parse_constant=lambda item: (_ for _ in ()).throw(
                AdmissionError(f"non-finite JSON value in {where}: {item}")
            ),
        )
    except (ValueError, UnicodeError) as exc:
        raise AdmissionError(f"{where} is not strict JSON") from exc
    _must(isinstance(value, dict), f"{where} is not an object")
    return value


def _relative(value: str, where: str) -> tuple[str, ...]:
    _must(isinstance(value, str) and 0 < len(value) <= 240, f"invalid {where}")
    path = Path(value)
    parts = path.parts
    _must(
        not path.is_absolute()
        and bool(parts)
        and all(part not in {"", ".", ".."} for part in parts),
        f"invalid {where}",
    )
    return parts


def _read_open_regular(fd: int, limit: int) -> bytes:
    before = os.fstat(fd)
    _must(
        stat.S_ISREG(before.st_mode) and before.st_size <= limit,
        "admission artifact is nonregular or oversized",
    )
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
    _must(
        len(raw) == before.st_size
        and len(raw) <= limit
        and (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ),
        "admission artifact changed during read",
    )
    return raw


def _read_regular(root: Path, relative: str, limit: int) -> bytes:
    """Stable bounded read without following any path component."""
    parts = _relative(relative, "admission artifact path")
    opened: list[int] = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(directory)
        for part in parts[:-1]:
            directory = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            opened.append(directory)
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        opened.append(fd)
        return _read_open_regular(fd, limit)
    except AdmissionError:
        raise
    except OSError as exc:
        raise AdmissionError("admission artifact is unavailable or redirected") from exc
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _open_or_create_directory(parent_fd: int, name: str) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        fd = os.open(name, flags, dir_fd=parent_fd)
    _must(stat.S_ISDIR(os.fstat(fd).st_mode), "admission state path is not a directory")
    return fd


def _artifact_directory(
    spec: VerifierSpec, request: AdmissionRequest
) -> tuple[Path, tuple[int, int]]:
    _must(request.verifier_id == spec.verifier_id, "admission verifier differs")
    _must(
        _ID.fullmatch(request.artifact_root_id) is not None, "invalid artifact root id"
    )
    parts = _relative(request.artifact_subpath, "artifact subpath")
    base = spec.artifact_roots.get(request.artifact_root_id)
    _must(base is not None, "artifact root is not allowlisted for this verifier")
    base = Path(base)
    opened: list[int] = []
    try:
        directory = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(directory)
        for part in parts:
            directory = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory,
            )
            opened.append(directory)
        info = os.fstat(directory)
        _must(stat.S_ISDIR(info.st_mode), "artifact output is not a directory")
        identity = (info.st_dev, info.st_ino)
    except AdmissionError:
        raise
    except OSError as exc:
        raise AdmissionError("artifact output is unavailable or redirected") from exc
    finally:
        for fd in reversed(opened):
            os.close(fd)
    return base.joinpath(*parts), identity


def _known_opponent_validator() -> Callable[[Path], dict[str, Any]]:
    from experiments.known_opponent_utility.admission import validate_pilot

    return validate_pilot


def _known_opponent_outcome(gate: dict[str, Any]) -> dict[str, Any]:
    value = {
        "scheduled_action_calls": gate["scheduled_action_calls"],
        "valid_action_calls": gate["valid_action_calls"],
        "scheduled_episodes": gate["scheduled_episodes"],
        "complete_episodes": gate["complete_episodes"],
        "zero_regret_complete_episodes": gate["zero_regret_complete_episodes"],
        "comprehension_passed": gate["comprehension_passed"],
        "attempted_calls": gate["attempted_calls"],
        "run_sha256": gate["run_sha256"],
        "manifest_sha256": gate["manifest_sha256"],
    }
    return {
        "experiment_id": "known-opponent-utility-response-pilot-v1",
        "metric": "disclosed_utility_action_validity_and_full_horizon_regret",
        "value": value,
        "trials": gate["recorded_episodes"],
        "summary": (
            "Prospective one-episode-per-condition utility-response pilot: "
            f"{gate['valid_action_calls']}/{gate['scheduled_action_calls']} valid actions, "
            f"{gate['complete_episodes']}/{gate['scheduled_episodes']} complete episodes, "
            f"{gate['zero_regret_complete_episodes']} zero-regret complete episodes. "
            "Descriptive local model behavior; no theoretical novelty or trading claim."
        ),
    }


DEFAULT_VERIFIERS: Mapping[str, VerifierSpec] = {
    "known-opponent-utility-pilot/v1": VerifierSpec(
        verifier_id="known-opponent-utility-pilot/v1",
        campaign_id="v2-known-opponent-utility-20260915",
        study_id="known-opponent-utility-response-pilot-v1",
        metric="disclosed_utility_action_validity_and_full_horizon_regret",
        verifier_source_path="experiments/known_opponent_utility/admission.py",
        raw_result_path="run.json",
        unit_name="independent_episodes",
        evidence_kind="registered_synthetic_study",
        l2_capable=True,
        artifact_roots={
            "known-opponent-lab-20260915": Path(
                "/home/decross1/projects/a_bgt_rsi_v2_artifacts/2026-09-15/"
                "lab-eight-hour/known-opponent-utility"
            )
        },
        validator_loader=_known_opponent_validator,
        outcome_builder=_known_opponent_outcome,
    )
}


def _spec(verifier_id: str, specs: Mapping[str, VerifierSpec] | None) -> VerifierSpec:
    registry = specs if specs is not None else DEFAULT_VERIFIERS
    spec = registry.get(verifier_id)
    _must(spec is not None, "experiment verifier is not allowlisted")
    _must(
        spec.verifier_id == verifier_id
        and _ID.fullmatch(spec.verifier_id) is not None
        and spec.evidence_kind in {"registered_synthetic_study", "diagnostic"},
        "experiment verifier declaration is invalid",
    )
    _must(
        spec.evidence_kind != "diagnostic" or spec.l2_capable is False,
        "diagnostic verifier cannot be L2 capable",
    )
    return spec


def _campaign_evidence(
    repo_root: Path,
    campaign: dict[str, Any],
    campaign_link: dict[str, Any],
    spec: VerifierSpec,
) -> dict[str, Any]:
    _must(isinstance(campaign, dict), "campaign registry entry is absent")
    _must(isinstance(campaign_link, dict), "campaign/topic link is absent")
    _must(campaign.get("campaign_id") == spec.campaign_id, "verifier campaign differs")
    manifest_sha = campaign.get("_manifest_sha256")
    _must(
        isinstance(manifest_sha, str) and _SHA.fullmatch(manifest_sha),
        "campaign hash missing",
    )
    question = campaign.get("research_question")
    _must(isinstance(question, dict), "campaign research question is absent")
    # Use the campaign registry's validated union. Registered topics live in
    # loader-private ``_registered_topics`` and their receipt digest must come
    # from that trusted state, never from the row being admitted.
    from orchestrator.research_campaign import CampaignError, all_topics, bind_topic

    try:
        topics = all_topics(campaign)
    except CampaignError as exc:
        raise AdmissionError("campaign topic registry is invalid") from exc
    topic_id = campaign_link.get("topic_id")
    topic = next((item for item in topics if item.get("topic_id") == topic_id), None)
    _must(topic is not None, "admission topic is not registered in campaign")
    try:
        expected_link = bind_topic(campaign, topic["text"])
    except (CampaignError, KeyError, TypeError) as exc:
        raise AdmissionError("registered campaign topic cannot be bound") from exc
    _must(campaign_link == expected_link, "campaign/topic link differs from registry")

    studies = campaign.get("study_manifests")
    _must(isinstance(studies, list), "campaign studies are absent")
    study = next(
        (
            item
            for item in studies
            if isinstance(item, dict) and item.get("study_id") == spec.study_id
        ),
        None,
    )
    _must(study is not None, "verifier study is not registered in campaign")
    study_raw = _read_regular(repo_root, study["path"], MAX_REGISTERED_BYTES)
    prereg_raw = _read_regular(
        repo_root, study["preregistration_path"], MAX_REGISTERED_BYTES
    )
    verifier_raw = _read_regular(
        repo_root, spec.verifier_source_path, MAX_REGISTERED_BYTES
    )
    _must(_sha256(study_raw) == study["sha256"], "study manifest hash differs")
    _must(
        _sha256(prereg_raw) == study["preregistration_sha256"],
        "study preregistration hash differs",
    )
    study_manifest = _strict_object(study_raw, "study manifest")
    _must(
        study_manifest.get("campaign_id") == campaign["campaign_id"]
        and study_manifest.get("study_id") == spec.study_id,
        "study manifest identity differs",
    )
    modules = study_manifest.get("execution_modules")
    _must(
        isinstance(modules, dict)
        and modules.get("independent_admission_path") == spec.verifier_source_path
        and modules.get("independent_admission_sha256") == _sha256(verifier_raw),
        "registered independent verifier source differs",
    )
    return {
        "campaign_manifest_sha256": manifest_sha,
        "campaign_link_sha256": _sha256(_canonical(campaign_link)),
        "topic_id": topic["topic_id"],
        "topic_sha256": topic["text_sha256"],
        "study_manifest_path": study["path"],
        "study_manifest_sha256": study["sha256"],
        "preregistration_path": study["preregistration_path"],
        "preregistration_sha256": study["preregistration_sha256"],
        "verifier_source_sha256": _sha256(verifier_raw),
    }


def _evaluate(
    *,
    repo_root: Path,
    campaign: dict[str, Any],
    campaign_link: dict[str, Any],
    outcome: dict[str, Any],
    request: AdmissionRequest,
    specs: Mapping[str, VerifierSpec] | None,
) -> dict[str, Any]:
    spec = _spec(request.verifier_id, specs)
    evidence = _campaign_evidence(repo_root, campaign, campaign_link, spec)
    output, output_identity = _artifact_directory(spec, request)
    raw_result_before = _read_regular(output, spec.raw_result_path, MAX_ARTIFACT_BYTES)
    try:
        gate = spec.validator_loader()(output)
    except AdmissionError:
        raise
    except Exception as exc:
        raise AdmissionError(
            "registered experiment verifier rejected artifacts"
        ) from exc
    _must(type(gate) is dict, "registered verifier returned a non-object")
    _must(gate.get("admission_eligible") is True, "study artifacts are not admitted")
    _must(
        gate.get("campaign_id") == spec.campaign_id
        and gate.get("study_id") == spec.study_id,
        "verifier result identity differs",
    )
    units = gate.get(spec.unit_count_field)
    _must(
        type(units) is int and units >= 0,
        "verifier independent-unit count is invalid",
    )
    output_after, output_identity_after = _artifact_directory(spec, request)
    _must(
        output_after == output and output_identity_after == output_identity,
        "artifact output changed during verification",
    )
    raw_result = _read_regular(output, spec.raw_result_path, MAX_ARTIFACT_BYTES)
    _must(
        raw_result == raw_result_before,
        "raw experiment result changed during verification",
    )
    raw_result_sha = _sha256(raw_result)
    _must(
        gate.get(spec.raw_result_sha256_field) == raw_result_sha,
        "verifier raw-result hash differs",
    )
    try:
        expected_outcome = spec.outcome_builder(gate)
    except Exception as exc:
        raise AdmissionError("registered outcome projection failed") from exc
    _must(
        _canonical(outcome) == _canonical(expected_outcome),
        "experiment outcome differs from verified artifact projection",
    )
    _must(
        outcome.get("experiment_id") == spec.study_id
        and outcome.get("metric") == spec.metric
        and outcome.get("trials") == units,
        "experiment outcome study, metric, or independent units differ",
    )
    return {
        "schema_version": RECEIPT_SCHEMA,
        "verifier_id": spec.verifier_id,
        "verifier_source_path": spec.verifier_source_path,
        "verifier_source_sha256": evidence["verifier_source_sha256"],
        "campaign_id": spec.campaign_id,
        "campaign_manifest_sha256": evidence["campaign_manifest_sha256"],
        "campaign_link_sha256": evidence["campaign_link_sha256"],
        "topic_id": evidence["topic_id"],
        "topic_sha256": evidence["topic_sha256"],
        "study_id": spec.study_id,
        "study_manifest_path": evidence["study_manifest_path"],
        "study_manifest_sha256": evidence["study_manifest_sha256"],
        "preregistration_path": evidence["preregistration_path"],
        "preregistration_sha256": evidence["preregistration_sha256"],
        "artifact_root_id": request.artifact_root_id,
        "artifact_subpath": request.artifact_subpath,
        "raw_result_path": spec.raw_result_path,
        "raw_result_sha256": raw_result_sha,
        "outcome_sha256": outcome_sha256(outcome),
        "metric": spec.metric,
        "unit_name": spec.unit_name,
        "independent_units": units,
        "evidence_kind": spec.evidence_kind,
        "l2_capable": spec.l2_capable,
        "admission_eligible": True,
    }


def _validate_receipt(receipt: dict[str, Any]) -> None:
    _must(
        set(receipt) == _RECEIPT_FIELDS
        and receipt.get("schema_version") == RECEIPT_SCHEMA,
        "unsupported experiment admission receipt",
    )
    for key in (
        "verifier_source_sha256",
        "campaign_manifest_sha256",
        "campaign_link_sha256",
        "topic_sha256",
        "study_manifest_sha256",
        "preregistration_sha256",
        "raw_result_sha256",
        "outcome_sha256",
    ):
        _must(
            isinstance(receipt[key], str) and _SHA.fullmatch(receipt[key]),
            f"invalid {key}",
        )
    _must(receipt["admission_eligible"] is True, "receipt is not admitted")
    _must(type(receipt["l2_capable"]) is bool, "receipt L2 capability is invalid")
    _must(
        receipt["evidence_kind"] != "diagnostic" or receipt["l2_capable"] is False,
        "diagnostic receipt cannot be L2 capable",
    )
    _must(
        type(receipt["independent_units"]) is int and receipt["independent_units"] >= 0,
        "receipt independent units are invalid",
    )


def _reference(receipt: dict[str, Any], receipt_sha: str) -> dict[str, Any]:
    return {
        "schema_version": REFERENCE_SCHEMA,
        "receipt_path": f"{RECEIPT_DIRECTORY}/{receipt_sha}.json",
        "receipt_sha256": receipt_sha,
        "verifier_id": receipt["verifier_id"],
        "campaign_id": receipt["campaign_id"],
        "campaign_manifest_sha256": receipt["campaign_manifest_sha256"],
        "topic_id": receipt["topic_id"],
        "topic_sha256": receipt["topic_sha256"],
        "study_id": receipt["study_id"],
        "outcome_sha256": receipt["outcome_sha256"],
        "unit_name": receipt["unit_name"],
        "independent_units": receipt["independent_units"],
        "evidence_kind": receipt["evidence_kind"],
    }


def _validate_reference(reference: dict[str, Any]) -> None:
    _must(
        set(reference) == _REFERENCE_FIELDS
        and reference.get("schema_version") == REFERENCE_SCHEMA,
        "unsupported experiment admission reference",
    )
    sha = reference.get("receipt_sha256")
    _must(
        isinstance(sha, str) and _SHA.fullmatch(sha), "invalid admission receipt hash"
    )
    _must(
        reference.get("receipt_path") == f"{RECEIPT_DIRECTORY}/{sha}.json",
        "admission receipt path is not content addressed",
    )


def _context(reference: dict[str, Any], receipt: dict[str, Any]) -> AdmissionContext:
    return AdmissionContext(
        receipt_sha256=reference["receipt_sha256"],
        reference_sha256=_sha256(_canonical(reference)),
        campaign_link_sha256=receipt["campaign_link_sha256"],
        outcome_sha256=receipt["outcome_sha256"],
        study_id=receipt["study_id"],
        independent_units=receipt["independent_units"],
        unit_name=receipt["unit_name"],
        evidence_kind=receipt["evidence_kind"],
        l2_capable=receipt["l2_capable"],
        _seal=_CONTEXT_SEAL,
    )


def _write_receipt(repo_root: Path, receipt: dict[str, Any]) -> AdmissionBundle:
    _validate_receipt(receipt)
    raw = _canonical(receipt) + b"\n"
    sha = _sha256(raw)
    opened: list[int] = []
    try:
        root_fd = os.open(repo_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(root_fd)
        state_fd = _open_or_create_directory(root_fd, "run_state")
        opened.append(state_fd)
        directory_fd = _open_or_create_directory(state_fd, "experiment_admissions")
        opened.append(directory_fd)
        try:
            fd = os.open(
                f"{sha}.json",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            existing_fd = os.open(
                f"{sha}.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
            try:
                existing = _read_open_regular(existing_fd, MAX_RECEIPT_BYTES)
            finally:
                os.close(existing_fd)
            _must(existing == raw, "content-addressed admission receipt differs")
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory_fd)
    except AdmissionError:
        raise
    except OSError as exc:
        raise AdmissionError("admission receipt storage is unavailable") from exc
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)
    reference = _reference(receipt, sha)
    return AdmissionBundle(reference=reference, context=_context(reference, receipt))


def admit_for_dispatch(
    *,
    repo_root: Path,
    campaign: dict[str, Any],
    campaign_link: dict[str, Any],
    outcome: dict[str, Any],
    request: AdmissionRequest,
    specs: Mapping[str, VerifierSpec] | None = None,
) -> AdmissionBundle:
    """Rerun a registered verifier and persist a source-bound receipt."""
    _must(isinstance(request, AdmissionRequest), "typed admission request is required")
    root = Path(repo_root).resolve(strict=True)
    receipt = _evaluate(
        repo_root=root,
        campaign=campaign,
        campaign_link=campaign_link,
        outcome=outcome,
        request=request,
        specs=specs,
    )
    return _write_receipt(root, receipt)


def load_context(
    row: dict[str, Any],
    *,
    repo_root: Path,
    specs: Mapping[str, VerifierSpec] | None = None,
    campaign_loader: Callable[[str, Path], dict[str, Any]] | None = None,
) -> AdmissionContext | None:
    """Replay a row's receipt and raw evidence; return no context when absent."""
    reference = row.get("experiment_admission_ref")
    if reference is None:
        return None
    _must(type(reference) is dict, "experiment admission reference is not an object")
    _validate_reference(reference)
    root = Path(repo_root).resolve(strict=True)
    receipt_raw = _read_regular(root, reference["receipt_path"], MAX_RECEIPT_BYTES)
    _must(
        _sha256(receipt_raw) == reference["receipt_sha256"],
        "experiment admission receipt hash differs",
    )
    receipt = _strict_object(receipt_raw, "experiment admission receipt")
    _validate_receipt(receipt)
    if campaign_loader is None:
        from orchestrator.research_campaign import CampaignError, load_campaign

        try:
            campaign = load_campaign(reference["campaign_id"], repo_root=root)
        except CampaignError as exc:
            raise AdmissionError("registered campaign replay failed") from exc
    else:
        campaign = campaign_loader(reference["campaign_id"], root)
    request = AdmissionRequest(
        verifier_id=receipt["verifier_id"],
        artifact_root_id=receipt["artifact_root_id"],
        artifact_subpath=receipt["artifact_subpath"],
    )
    rebuilt = _evaluate(
        repo_root=root,
        campaign=campaign,
        campaign_link=row.get("campaign"),
        outcome=row.get("experiment_outcome"),
        request=request,
        specs=specs,
    )
    _must(receipt == rebuilt, "experiment admission receipt replay differs")
    expected_reference = _reference(receipt, reference["receipt_sha256"])
    _must(reference == expected_reference, "experiment admission reference differs")
    return _context(reference, receipt)


def derive_verified_level(
    row: dict[str, Any],
    feedback_row: dict[str, Any] | None,
    adversarial_block: dict[str, Any] | None,
    health_rows: list,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Replay empirical admission and derive one fail-closed evidence level.

    An absent reference follows the ordinary ladder path. A present but
    invalid reference cannot earn L2 and is surfaced as a projection
    diagnostic. Unexpected programming or infrastructure exceptions retain
    their traceback instead of being mislabeled as invalid science.
    """
    from workers.evidence_ladder import derive_level

    failure: str | None = None
    try:
        context = load_context(row, repo_root=repo_root)
    except AdmissionError as exc:
        context = None
        failure = " ".join(str(exc).split())[:240] or "unspecified admission failure"
    result = derive_level(
        row,
        feedback_row,
        adversarial_block,
        health_rows,
        admission_context=context,
    )
    if failure is not None:
        result = {
            **result,
            "provisional": [
                *result.get("provisional", []),
                "experiment_admission_invalid",
            ],
            "reasons": [
                *result.get("reasons", []),
                f"experiment admission replay failed: {failure}",
            ],
        }
    return result


__all__ = [
    "AdmissionBundle",
    "AdmissionContext",
    "AdmissionError",
    "AdmissionRequest",
    "VerifierSpec",
    "admit_for_dispatch",
    "derive_verified_level",
    "load_context",
    "outcome_sha256",
]
