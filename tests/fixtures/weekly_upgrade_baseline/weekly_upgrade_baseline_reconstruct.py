"""Build minimal lock-time inputs from already-public benchmark artifacts.

The generated files exist only in pytest temporary directories.  They retain
the fields needed to exercise selection, aggregation, ledger reduction, and
hash-seed determinism without publishing the much larger live ledgers or
iteration caches from which the 2026-08-19 studies were originally locked.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _started_at(iteration_id: str) -> str:
    candidate = iteration_id.removeprefix("iter-")[:10]
    if len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
        return candidate + "T00:00:00Z"
    return "2026-08-01T00:00:00Z"


def _minimal_cache_result(iteration_id: str, *, flagged: bool) -> dict:
    return {
        "neighbors": [{
            "doc_id": f"public-reconstruction:{iteration_id}",
            "chunk_text": "Minimal public reconstruction placeholder.",
        }],
        "relevance": {
            "category": "off_domain" if flagged else "ok",
            "low_confidence": flagged,
        },
    }


def _write_cache(cache_root: Path, iteration_id: str, result: dict) -> None:
    _write_json(
        cache_root / iteration_id / "retrieval.json",
        {"status": "passed", "result": result},
    )


def materialize_critic(repo_root: Path, out_root: Path) -> dict[str, Path | str]:
    """Reconstruct the locked critic manifest's resolver population.

    Selected rows and envelopes come verbatim from the committed manifest.
    Unselected rows retain only public IDs, selection class, and a one-line
    placeholder pack.  Eighteen non-pool usable rows preserve the original
    census arithmetic without disclosing their unrelated content.
    """
    manifest_path = repo_root / "bench" / "critic_cal" / "manifest.jsonl"
    meta_path = repo_root / "bench" / "critic_cal" / "manifest_meta.json"
    audit_path = (
        repo_root / "bench" / "critic_cal" / "runs"
        / "override_audit_2026-08-19.json"
    )
    manifest = [
        json.loads(line) for line in manifest_path.read_text().splitlines()
        if line.strip()
    ]
    meta = json.loads(meta_path.read_text())
    cache_root = out_root / "iteration_cache"
    rows: list[dict] = []

    for fixture in manifest:
        recorded = fixture["recorded"]
        critique = {
            "verdict": recorded["verdict_final"],
            "subagent_status": recorded["subagent_status"],
            "subagent_turns_used": recorded["subagent_turns_used"],
            "subagent_wall_seconds": recorded["subagent_wall_seconds"],
            "subagent_backend": recorded["subagent_backend"],
            "subagent_model": recorded["subagent_model"],
            "contradicting_paper_id": recorded["contradicting_paper_id"],
        }
        if recorded["verdict_raw"] != recorded["verdict_final"]:
            critique["verdict_overridden_from"] = recorded["verdict_raw"]
            critique["override_reason"] = recorded["override_reason"]
        retrieval_envelope = copy.deepcopy(fixture["retrieval_envelope"])
        row = {
            "iteration_id": fixture["iteration_id"],
            "started_at": fixture["started_at"],
            "hypothesis": {"text": fixture["hypothesis_text"]},
            "retrieval": copy.deepcopy(retrieval_envelope["result"]),
            "critique": critique,
            "novelty": {"class": recorded["novelty_class"]},
            "redteam": {"verdict": recorded["redteam_verdict"]},
        }
        rows.append(row)
        _write_json(
            cache_root / fixture["iteration_id"] / "retrieval.json",
            retrieval_envelope,
        )
        novelty = fixture.get("novelty_envelope")
        if isinstance(novelty, dict):
            _write_json(
                cache_root / fixture["iteration_id"] / "novelty.json",
                novelty,
            )

    for exclusion in meta["exclusions_by_reason"]:
        reason = exclusion["reason"]
        if reason.startswith("S2 "):
            verdict = reason.split()[1]
            flagged = False
        elif reason.startswith("S3 pool"):
            verdict = "undecidable"
            flagged = True
        else:
            continue
        for iteration_id in exclusion["iteration_ids"]:
            result = _minimal_cache_result(iteration_id, flagged=flagged)
            rows.append({
                "iteration_id": iteration_id,
                "started_at": _started_at(iteration_id),
                "hypothesis": {"text": f"Public selection reconstruction {iteration_id}."},
                "retrieval": copy.deepcopy(result),
                "critique": {"verdict": verdict, "subagent_status": "passed"},
                "novelty": {"class": "novel"},
                "redteam": {"verdict": "proceed"},
            })
            _write_cache(cache_root, iteration_id, result)

    # The lock had 18 valid rows outside S1/S2/S3: overridden undecidables on
    # adequate packs.  Their identities/content never affect selection.
    for index in range(18):
        iteration_id = f"public-reconstruction-other-{index:02d}"
        result = _minimal_cache_result(iteration_id, flagged=False)
        rows.append({
            "iteration_id": iteration_id,
            "started_at": "2026-08-01T00:00:00Z",
            "hypothesis": {"text": "Public non-pool reconstruction row."},
            "retrieval": copy.deepcopy(result),
            "critique": {
                "verdict": "undecidable",
                "verdict_overridden_from": "survives",
                "override_reason": "relevance category reconstruction",
                "subagent_status": "passed",
            },
        })
        _write_cache(cache_root, iteration_id, result)

    for exclusion in meta["exclusions_by_reason"]:
        reason = exclusion["reason"]
        if reason == "no critique block":
            for iteration_id in exclusion["iteration_ids"]:
                rows.append({
                    "iteration_id": iteration_id,
                    "started_at": _started_at(iteration_id),
                    "hypothesis": {"text": "Public excluded reconstruction row."},
                })
        elif reason.startswith("critic subagent_status="):
            status = None if "=None" in reason else "schema_mismatch"
            for iteration_id in exclusion["iteration_ids"]:
                rows.append({
                    "iteration_id": iteration_id,
                    "started_at": _started_at(iteration_id),
                    "hypothesis": {"text": "Public excluded reconstruction row."},
                    "critique": {"verdict": "survives", "subagent_status": status},
                })

    rows.sort(key=lambda row: row["iteration_id"])
    if len(rows) != 167:
        raise AssertionError(f"critic reconstruction has {len(rows)} rows")
    loop_memory = out_root / "loop_memory.jsonl"
    _write_jsonl(loop_memory, rows)
    return {
        "loop_memory": loop_memory,
        "cache_root": cache_root,
        "audit_report": audit_path,
        "loop_memory_sha256": file_sha256(loop_memory),
        "cache_tree_sha256": tree_sha256(cache_root),
    }


def _raw_audit_row(processed: dict) -> dict:
    """Invert one already-public audit row into its minimal worker record."""
    row = {
        "iteration_id": processed["iteration_id"],
        "started_at": processed["started_at"],
    }
    if processed["pack_state"] != "absent":
        category = processed["relevance_category"]
        low_confidence = processed["relevance_low_confidence"]
        row["retrieval"] = (
            {} if category is None and low_confidence is None else {
                "relevance": {
                    "category": category,
                    "low_confidence": low_confidence,
                }
            }
        )

    if processed["has_critique"]:
        critique = {
            "verdict": processed["verdict_final"],
            "subagent_status": processed["subagent_status"],
            "subagent_turns_used": processed["subagent_turns_used"],
            "subagent_wall_seconds": processed["subagent_wall_seconds"],
        }
        if processed["verdict_raw"] != processed["verdict_final"]:
            critique.update({
                "verdict_overridden_from": processed["verdict_raw"],
                "override_reason": processed["override_reason"],
            })
        debate_keys = (
            "debate_verdict", "debate_rounds", "debate_stop_reason"
        )
        if any(processed[key] is not None for key in debate_keys):
            critique["debate"] = {
                "verdict": processed["debate_verdict"],
                "rounds": processed["debate_rounds"],
                "stop_reason": processed["debate_stop_reason"],
            }
        for key in ("skeptic_verdict", "skeptic_backend", "skeptic_model"):
            if processed[key] is not None:
                critique[key] = processed[key]
        if processed["skeptic_infra_error_flag"]:
            critique["skeptic_infra_error"] = True

        # thesis_to_experiment.is_eligible is a conjunction over these three
        # public fields. Infer the otherwise-unreported low-confidence bit only
        # when it is the sole explanation of the published eligibility value.
        for verdict_key, eligible_key in (
            ("verdict_raw", "t2e_eligible_raw"),
            ("verdict_final", "t2e_eligible_final"),
        ):
            eligible_without_low_confidence = (
                processed["novelty_class"] in ("novel", "unclear")
                and processed[verdict_key] == "survives"
            )
            if (
                eligible_without_low_confidence
                and not processed[eligible_key]
            ):
                critique["low_confidence"] = True
        row["critique"] = critique

    if processed["novelty_class"] is not None:
        row["novelty"] = {"class": processed["novelty_class"]}
    if processed["redteam_verdict"] is not None:
        row["redteam"] = {"verdict": processed["redteam_verdict"]}
    if processed["gate_status"] is not None:
        row["gate_status"] = processed["gate_status"]

    if (
        processed["l1_level_raw"] == "L2"
        or processed["l1_level_final"] == "L2"
    ):
        row["experiment_outcome"] = {"trials": 30, "summary": "valid"}
    if (
        processed["novelty_class"] == "unclear"
        and not any(
            str(reason).startswith("novelty.class=")
            for reason in processed["l1_missing_final"]
        )
    ):
        # Preserve the public surprising-vs-theory branch without recovering
        # the original private experiment narrative.
        row["experiment_outcome"] = {
            "trials": 30,
            "summary": "Verdict=NO (minimal public reconstruction)",
        }
    return row


def materialize_critic_audit(
    repo_root: Path, out_root: Path
) -> dict[str, Path | str]:
    """Rebuild minimal audit inputs from the committed per-row audit table.

    This does not recreate the original source bytes. It reconstructs only
    fields consumed by the public aggregation functions. Cluster membership
    uses public row IDs chosen only to preserve each published member count,
    latest row, and no-ordering-ambiguity invariant; it does not claim to
    recover the original cluster membership.
    """
    report_path = (
        repo_root / "bench" / "critic_cal" / "runs"
        / "override_audit_2026-08-19.json"
    )
    report = json.loads(report_path.read_text())
    loop_memory = out_root / "audit_loop_memory.jsonl"
    idea_ledger = out_root / "audit_idea_ledger.jsonl"
    loop_feedback = out_root / "audit_loop_feedback.jsonl"
    _write_jsonl(
        loop_memory,
        [_raw_audit_row(row) for row in report["rows"]],
    )
    public_ids = [row["iteration_id"] for row in report["rows"]]
    loop_order = {
        iteration_id: index for index, iteration_id in enumerate(public_ids)
    }
    cluster_events: list[dict] = []
    for cluster in report["clusters"]["clusters"]:
        latest = cluster["latest_iteration"]
        member_count = cluster["n_members_in_loop_memory"]
        earlier = [
            iteration_id for iteration_id in public_ids
            if loop_order[iteration_id] < loop_order[latest]
            and iteration_id < latest
        ]
        if len(earlier) < member_count - 1:
            raise AssertionError(
                "cannot reconstruct unambiguous members for "
                f"{cluster['cluster_id']}"
            )
        members = earlier[:member_count - 1] + [latest]
        cluster_events.append(_created(cluster["cluster_id"], members[0]))
        for index, member in enumerate(members[1:], start=1):
            cluster_events.append({
                "event_type": "member_added",
                "ts": f"2026-08-19T00:00:{index:02d}Z",
                "cluster_id": cluster["cluster_id"],
                "member_id": member,
            })
    _write_jsonl(idea_ledger, cluster_events)

    verdicts = [
        entry["key"]
        for entry in report["gate_ledger"]["by_verdict"]
        for _ in range(entry["n"])
    ]
    iteration_ids = list(report["gate_ledger"]["iteration_ids"])
    if len(verdicts) != report["gate_ledger"]["n_rows"]:
        raise AssertionError("gate-ledger verdict census is inconsistent")
    feedback_rows = [
        {
            "iteration_id": iteration_ids[index % len(iteration_ids)],
            "verdict": verdict,
        }
        for index, verdict in enumerate(verdicts)
    ]
    _write_jsonl(loop_feedback, feedback_rows)
    return {
        "loop_memory": loop_memory,
        "idea_ledger": idea_ledger,
        "loop_feedback": loop_feedback,
        "audit_report": report_path,
        "loop_memory_sha256": file_sha256(loop_memory),
        "idea_ledger_sha256": file_sha256(idea_ledger),
        "loop_feedback_sha256": file_sha256(loop_feedback),
    }


def _created(cluster_id: str, member_id: str, level: str = "L0") -> dict:
    return {
        "event_type": "cluster_created",
        "ts": "2026-08-19T00:00:00Z",
        "cluster_id": cluster_id,
        "origin": "manual",
        "member_id": member_id,
        "iteration_id": member_id,
        "evidence_level": level,
    }


def _killed(cluster_id: str, code: str, evidence_key: str) -> dict:
    return {
        "event_type": "cluster_killed",
        "ts": "2026-08-19T00:00:01Z",
        "cluster_id": cluster_id,
        "kill_reason": {
            "code": code,
            "evidence_key": evidence_key,
            "detail": "Public benchmark reconstruction.",
        },
        "reopening_condition": {
            "requires": "new_evidence",
            "evidence_kind": (
                "redteam_proceed_on_revision"
                if code == "redteam_fatal_flaw" else "replication"
            ),
        },
    }


def materialize_readjudication(
    repo_root: Path, out_root: Path
) -> dict[str, Path | str]:
    """Build a minimal idea-ledger/loop-memory pair for the public manifest."""
    manifest_path = repo_root / "bench" / "readjudication" / "manifest.jsonl"
    lines = [
        json.loads(line) for line in manifest_path.read_text().splitlines()
        if line.strip()
    ]
    locked_meta, manifest_rows = lines[0], lines[1:]
    targets = [row for row in manifest_rows if row["kind"] == "target"]
    sidecars = [row for row in manifest_rows if row["kind"] == "sidecar"]
    events: list[dict] = []
    loop_rows: list[dict] = []

    for target in sorted(targets, key=lambda row: row["cluster_id"]):
        cid = target["cluster_id"]
        founder = target["founding_iteration"]
        events.append(_created(cid, founder, target["evidence_level"]))
        for index in range(1, target["cluster_member_count"]):
            events.append({
                "event_type": "member_added",
                "ts": f"2026-08-19T00:00:{index + 1:02d}Z",
                "cluster_id": cid,
                "member_id": f"member:{cid}:{index}",
            })
        events.append(_killed(cid, "redteam_fatal_flaw", target["evidence_key"]))
        loop_rows.append({
            "iteration_id": founder,
            "ended_at": target["founding_ended_at"],
            "model_version": target["historical_model_version"],
            "hypothesis": {"text": target["claim_text"]},
            "redteam": {
                "verdict": target["historical_verdict"],
                "confidence": target["historical_confidence"],
                "retries_used": target["historical_retries_used"],
                "subagent_status": target["historical_subagent_status"],
                "subagent_backend": target["historical_subagent_backend"],
                "subagent_model": target["historical_subagent_model"],
            },
        })

    refined = locked_meta["exclusions"][0]["cluster_id"]
    founding = next(
        row for row in sidecars
        if row["cluster_id"] == refined and row["variant"] == "founding"
    )
    revision = next(
        row for row in sidecars
        if row["cluster_id"] == refined and row["variant"] == "refined"
    )
    founder = founding["founding_iteration"]
    events.extend([
        _created(refined, founder),
        _killed(refined, "redteam_fatal_flaw", f"iteration:{founder}:redteam"),
        {
            "event_type": "cluster_refined", "ts": "2026-08-19T00:00:02Z",
            "cluster_id": refined, "round": 1,
            "refined_claim": revision["claim_text"],
        },
        {
            "event_type": "cluster_refined", "ts": "2026-08-19T00:00:03Z",
            "cluster_id": refined, "round": 2,
            "refined_claim": revision["claim_text"],
        },
    ])
    loop_rows.append({
        "iteration_id": founder,
        "ended_at": "2026-08-15T00:00:00Z",
        "model_version": "public-reconstruction",
        "hypothesis": {"text": founding["claim_text"]},
        "redteam": {
            "verdict": "fatal_flaw", "confidence": 0.0, "retries_used": 0,
            "subagent_status": "passed", "subagent_backend": "vllm-gemma",
            "subagent_model": "gemma-4-26b-a4b",
        },
    })

    # Preserve only the public aggregate inventory: 112 killed / 20 open.
    for index in range(23):
        cid = f"public-other-killed-{index:02d}"
        events.extend([
            _created(cid, f"member:{cid}"),
            _killed(cid, "non_research_artifact", f"public:{cid}"),
        ])
    for index in range(20):
        cid = f"public-open-{index:02d}"
        events.append(_created(cid, f"member:{cid}"))

    ledger = out_root / "idea_ledger.jsonl"
    loop_memory = out_root / "loop_memory.jsonl"
    _write_jsonl(ledger, events)
    _write_jsonl(
        loop_memory,
        sorted(loop_rows, key=lambda row: row["iteration_id"]),
    )
    return {
        "idea_ledger": ledger,
        "loop_memory": loop_memory,
        "idea_ledger_sha256": file_sha256(ledger),
        "loop_memory_sha256": file_sha256(loop_memory),
    }
