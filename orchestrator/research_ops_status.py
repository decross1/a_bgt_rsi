"""Content-free, read-only status of registered research and daily ingestion.

Campaign topic exhaustion is asserted only after an exact manifest and complete
loop-memory source replay. It is a queue observation, not a global no-work gate:
the coordinator may still have promotion or escalation work. Broken or bounded
sources remain unknown, never an empty queue or a successful ingestion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestrator import coordinator
from orchestrator.research_campaign import (
    KNOWN_OPPONENT_CAMPAIGN_ID,
    CampaignError,
    available_topics,
    load_active_campaign,
    load_campaign,
    unique_matching_records,
)
from pipeline import daily_arxiv_job as ingestion

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA = "research-ops-status/v1"
MAX_LOOP_BYTES = 16 * 1024 * 1024
MAX_CYCLE_BYTES = 8 * 1024 * 1024
MAX_BUDGET_BYTES = 2 * 1024 * 1024
MAX_ROWS = 50_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
INGESTION_CODES = frozenset({
    "arxiv_http_429_retry_exhausted", "arxiv_http_503_retry_exhausted",
    "fetch_timeout", "embed_timeout", "fetch_error", "embed_error",
    "IngestionError", "OSError", "ValueError",
})
LEGACY_LOG = Path("/home/decross1/cron-daily-arxiv.log")
MAX_LEGACY_LOG_BYTES = 1_000_000
LEGACY_START_RE = re.compile(r"^\[daily-arxiv\] ([0-9T:-]+Z) start$", re.MULTILINE)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        return None
    return parsed.astimezone(timezone.utc)


def _json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON field")
            out[key] = value
        return out

    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
    if not isinstance(value, dict):
        raise TypeError("JSONL row is not an object")
    return value


def _read_source(root: Path, relative: str, limit: int) -> tuple[list[tuple[dict, str]], dict]:
    """Read a complete bounded repository JSONL through nofollow descriptors."""
    parts = Path(relative).parts
    proof = {"available": False, "sha256": None, "rows": None, "bytes": None}
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return [], proof
    opened: list[int] = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(directory)
        for part in parts[:-1]:
            directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory)
            opened.append(directory)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        opened.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            return [], proof
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
        if (len(raw) != before.st_size or len(raw) > limit
                or (before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_ino, after.st_size, after.st_mtime_ns)):
            return [], proof
        lines = raw.splitlines()
        if len(lines) > MAX_ROWS or any(not line for line in lines):
            return [], proof
        rows = [(_json(line), _sha(line)) for line in lines]
        proof = {"available": True, "sha256": _sha(raw),
                 "rows": len(rows), "bytes": len(raw)}
        return rows, proof
    except (OSError, ValueError, TypeError, UnicodeError):
        return [], proof
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _ingestion(root: Path, observed: datetime) -> dict:
    """Replay the newest durable attempt and last-success cache pointer."""
    out = {
        "latest_attempt_status": "none", "latest_attempt_at": None,
        "latest_attempt_run_id": None, "latest_attempt_receipt_sha256": None,
        "latest_failure_code": None, "last_success_at": None,
        "last_success_input_sha256": None, "last_success_paper_count": None,
        "last_success_age_hours": None, "last_success_pointer_sha256": None,
        "source_status": "available",
    }
    if root.is_symlink() or not root.is_dir():
        out["source_status"] = "unknown"
        out["latest_attempt_status"] = "unknown"
        return out
    try:
        prior = ingestion._last_success(root)
        if prior is not None:
            finished = _time(prior.get("finished_at"))
            if finished is None or finished > observed:
                raise ValueError("last-success time is invalid")
            out.update(
                last_success_at=_stamp(finished),
                last_success_input_sha256=prior["input_sha256"],
                last_success_paper_count=prior["paper_count"],
                last_success_age_hours=round((observed - finished).total_seconds() / 3600, 2),
                last_success_pointer_sha256=_sha(ingestion._read_regular(
                    root / "last-success.json", 4096)),
            )
        runs = root / "runs"
        if runs.is_symlink() or not runs.is_dir():
            raise ValueError("ingestion run directory unavailable")
        children = list(runs.iterdir())
        if len(children) > ingestion.MAX_RUNS_SCAN:
            raise ValueError("ingestion run scan exceeds cap")
        candidates: list[tuple[datetime, str, Path, bytes]] = []
        for child in children:
            if child.is_symlink() or not child.is_dir() or not ingestion.RUN_RE.fullmatch(child.name):
                raise ValueError("ingestion run path is malformed")
            started_raw = ingestion._read_regular(child / "started.json", 8192)
            started = _json(started_raw)
            stamp = _time(started.get("started_at"))
            if (started.get("schema") != ingestion.SCHEMA
                    or started.get("run_id") != child.name or stamp is None
                    or stamp > observed):
                raise ValueError("ingestion started receipt is malformed")
            candidates.append((stamp, child.name, child, started_raw))
        if candidates:
            latest_time = max(item[0] for item in candidates)
            latest = [item for item in candidates if item[0] == latest_time]
            if len(latest) != 1:
                raise ValueError("ingestion latest-attempt chronology is ambiguous")
            _started, run_id, child, started_raw = latest[0]
            out["latest_attempt_run_id"] = run_id
            out["latest_attempt_at"] = _stamp(_started)
            terminal = child / "terminal.json"
            if not os.path.lexists(terminal):
                out["latest_attempt_status"] = "interrupted_unknown"
            else:
                terminal_raw = ingestion._read_regular(terminal, 8192)
                row = _json(terminal_raw)
                finished = _time(row.get("finished_at"))
                if (row.get("schema") != ingestion.SCHEMA or row.get("run_id") != run_id
                        or row.get("started_sha256") != _sha(started_raw)
                        or row.get("status") not in {"succeeded", "fetch_failed", "embed_failed"}
                        or finished is None or finished < _started or finished > observed):
                    raise ValueError("ingestion terminal receipt is malformed")
                failure = row.get("failure_code")
                if row["status"] == "succeeded" and failure is not None:
                    raise ValueError("successful ingestion has failure code")
                if row["status"] != "succeeded" and not isinstance(failure, str):
                    raise ValueError("failed ingestion has no failure code")
                out["latest_attempt_status"] = row["status"]
                out["latest_attempt_at"] = _stamp(finished)
                out["latest_attempt_receipt_sha256"] = _sha(terminal_raw)
                out["latest_failure_code"] = (
                    failure if failure in INGESTION_CODES else "other_failure")
    except (OSError, ValueError, ingestion.IngestionError, UnicodeError):
        out["source_status"] = "unknown"
        out["latest_attempt_status"] = "unknown"
    return out


def _legacy_ingestion_log(path: Path, observed: datetime) -> dict:
    """Date/hash-bind the older cron log; never present it as a job receipt."""
    out = {"status": "source_unknown", "started_at": None,
           "log_sha256": None, "http_codes_observed": [],
           "retry_count_observed": None, "receipt_bound": False}
    try:
        raw = ingestion._read_regular(path, MAX_LEGACY_LOG_BYTES)
        text = raw.decode("utf-8")
        matches = list(LEGACY_START_RE.finditer(text))
        if not matches:
            return out
        last = matches[-1]
        started = _time(last.group(1))
        if started is None or started > observed:
            return out
        section = text[last.end():]
        codes = sorted(set(re.findall(r"HTTP (429|503)\b", section)))
        retries = [int(item) for item in re.findall(r"before retry ([1-6])\b", section)]
        out.update(started_at=_stamp(started), log_sha256=_sha(raw),
                   http_codes_observed=codes,
                   retry_count_observed=max(retries, default=0))
        if re.search(r"^\[daily-arxiv\] [0-9T:-]+Z done$", section, re.MULTILINE):
            out["status"] = "succeeded_log_observed"
        elif "ArxivScraperError" in section and codes:
            out["status"] = "fetch_failed_log_observed"
        else:
            out["status"] = "interrupted_unknown"
    except (OSError, ValueError, UnicodeError, ingestion.IngestionError):
        pass
    return out


def project_research_ops_status(
    *, repo_root: Path = PROJECT_ROOT, ingestion_root: Path | None = None,
    legacy_ingestion_log: Path = LEGACY_LOG, observed_at: datetime | None = None,
) -> dict:
    """Return one bounded public status without dispatching work."""
    observed = observed_at or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset().total_seconds() != 0:
        raise ValueError("observed_at must be UTC")
    out: dict[str, Any] = {
        "schema": SCHEMA, "observed_at": _stamp(observed),
        "active_campaign": None,
        "campaign_queue": {"status": "unknown", "eligible_count": None,
                           "consumed_count": None, "eligible_topic_ids": [],
                           "loop_source_sha256": None},
        "next_registered_campaign": None,
        "next_work": {"code": "source_unknown", "campaign_id": None,
                      "topic_id": None, "study_id": None,
                      "manifest_sha256": None, "preregistration_sha256": None,
                      "activation_required": False},
        "last_productive": None,
        "last_cycle": None,
        "budget": {"source_status": "unknown", "spent_today": None,
                   "daily_cap": coordinator.DAILY_BUDGET_CAP,
                   "paced_allowance": coordinator._budget_allowance(observed),
                   "ledger_sha256": None},
        "dispatch_gate": {"operator_pause": os.path.lexists(
            repo_root / "run_state" / "pause_coordinator"),
                          "other_actionable_work": "not_assessed"},
        "ingestion": _ingestion(ingestion_root or repo_root / "run_state" / "arxiv_ingestion",
                                observed),
        "ingestion_legacy_log": _legacy_ingestion_log(legacy_ingestion_log, observed),
    }
    try:
        campaign = load_active_campaign(repo_root=repo_root, env_campaign_id="",
                                        now=observed)
        if campaign is not None:
            out["active_campaign"] = {
                "campaign_id": campaign["campaign_id"],
                "manifest_sha256": campaign["_manifest_sha256"],
            }
    except (CampaignError, OSError, ValueError):
        campaign = None
        out["campaign_queue"]["status"] = "source_unknown"
    if campaign is not None:
        rows, proof = _read_source(repo_root, "memory/loop_memory.jsonl", MAX_LOOP_BYTES)
        if proof["available"]:
            available = available_topics(campaign, [row for row, _sha_row in rows])
            eligible_ids = [row["topic_id"] for row in available]
            out["campaign_queue"] = {
                "status": "eligible" if eligible_ids else "all_registered_topics_consumed",
                "eligible_count": len(eligible_ids),
                "consumed_count": len(campaign["topic_policy"]["topics"]) - len(eligible_ids),
                "eligible_topic_ids": eligible_ids[:24],
                "loop_source_sha256": proof["sha256"],
            }
            consumed_count = len(campaign["topic_policy"]["topics"]) - len(eligible_ids)
            if campaign["campaign_id"] == KNOWN_OPPONENT_CAMPAIGN_ID and consumed_count >= 1:
                study = campaign["study_manifests"][0]
                out["next_work"] = {
                    "code": "freeze_and_run_registered_empirical_study",
                    "campaign_id": campaign["campaign_id"],
                    "topic_id": None, "study_id": study["study_id"],
                    "manifest_sha256": campaign["_manifest_sha256"],
                    "preregistration_sha256": study["preregistration_sha256"],
                    "activation_required": False,
                }
            elif eligible_ids:
                out["next_work"] = {
                    "code": "run_preregistered_campaign_topic",
                    "campaign_id": campaign["campaign_id"],
                    "topic_id": eligible_ids[0], "study_id": None,
                    "manifest_sha256": campaign["_manifest_sha256"],
                    "preregistration_sha256": None,
                    "activation_required": False,
                }
            members = unique_matching_records(
                [row for row, _sha_row in rows], campaign, identity_field="iteration_id")
            if members:
                last = max(members, key=lambda item: _time(item.get("ended_at"))
                           or datetime.min.replace(tzinfo=timezone.utc))
                ended = _time(last.get("ended_at"))
                if ended is not None and ended <= observed and ID_RE.fullmatch(
                    str(last.get("iteration_id"))):
                    out["last_productive"] = {
                        "kind": "campaign_iteration_recorded",
                        "iteration_id": last["iteration_id"],
                        "at": _stamp(ended),
                        "topic_id": last["campaign"]["topic_id"],
                        "gate_status": last.get("gate_status") if last.get("gate_status") in {
                            "pending", "blocked", "passed", "failed"} else "unknown",
                        "loop_source_sha256": proof["sha256"],
                    }
        if campaign["campaign_id"] != KNOWN_OPPONENT_CAMPAIGN_ID:
            try:
                next_campaign = load_campaign(KNOWN_OPPONENT_CAMPAIGN_ID, repo_root=repo_root)
                out["next_registered_campaign"] = {
                    "campaign_id": next_campaign["campaign_id"],
                    "manifest_sha256": next_campaign["_manifest_sha256"],
                    "registered_topic_count": len(next_campaign["topic_policy"]["topics"]),
                    "activation_required": True,
                }
                if out["campaign_queue"]["status"] == "all_registered_topics_consumed":
                    out["next_work"] = {
                        "code": "activate_registered_successor",
                        "campaign_id": next_campaign["campaign_id"],
                        "topic_id": None, "study_id": None,
                        "manifest_sha256": next_campaign["_manifest_sha256"],
                        "preregistration_sha256": None,
                        "activation_required": True,
                    }
            except (CampaignError, OSError, ValueError):
                pass
    cycles, cycle_proof = _read_source(repo_root, "run_state/coordinator_cycles.jsonl",
                                        MAX_CYCLE_BYTES)
    if cycle_proof["available"] and cycles:
        row, row_sha = cycles[-1]
        when = _time(row.get("timestamp"))
        plan, outcomes = row.get("plan"), row.get("outcomes")
        if (when is not None and when <= observed and row.get("status") == "executed"
                and ID_RE.fullmatch(str(row.get("run_id")))
                and isinstance(plan, list) and isinstance(outcomes, list)
                and len(plan) <= 6 and len(outcomes) <= 6):
            planned = [x.get("action") for x in plan if isinstance(x, dict)
                       and x.get("action") != "noop"]
            dispatched = [x.get("action") for x in outcomes if isinstance(x, dict)
                          and x.get("status") == "passed" and x.get("action") != "noop"]
            noop = len(plan) == 1 and isinstance(plan[0], dict) and plan[0].get("action") == "noop"
            out["last_cycle"] = {
                "run_id": row["run_id"], "at": _stamp(when),
                "action_code": "noop" if noop else "actions_planned",
                "planned_count": len(planned), "dispatched_count": len(dispatched),
                "outcome_count": len(outcomes),
                "raw_row_sha256": row_sha,
                "cycles_source_sha256": cycle_proof["sha256"],
            }
    budget_rows, budget_proof = _read_source(repo_root, "run_state/coordinator_budget.jsonl",
                                              MAX_BUDGET_BYTES)
    if budget_proof["available"]:
        today = observed.strftime("%Y-%m-%d")
        spent = 0
        valid = True
        for row, _sha_row in budget_rows:
            if row.get("date") != today:
                continue
            value = row.get("spent")
            if type(value) is not int or value < 0:
                valid = False
                break
            spent += value
        if valid:
            out["budget"].update(source_status="available", spent_today=spent,
                                 ledger_sha256=budget_proof["sha256"])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", required=True)
    args = parser.parse_args(argv)
    if args.plan:
        view = project_research_ops_status()
        print(json.dumps({
            "schema": view["schema"], "observed_at": view["observed_at"],
            "active_campaign": view["active_campaign"],
            "campaign_queue": view["campaign_queue"],
            "next_work": view["next_work"],
            "dispatch_gate": view["dispatch_gate"],
        }, sort_keys=True, separators=(",", ":")))
    return 0


__all__ = ["SCHEMA", "project_research_ops_status"]


if __name__ == "__main__":
    raise SystemExit(main())
