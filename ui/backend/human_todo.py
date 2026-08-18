"""Human TODO composition endpoint — the B3 read-only slice of
ui/notes/observability_reconciliation_plan.md.

The human's queue is invisible today: 11+ iterations sit at
``gate_status="pending"`` with no ``loop_feedback`` verdict and no surface
says so. This module composes everything awaiting a human into ONE list,
each item carrying the exact CLI command that resolves it (the sanctioned
write-back channels already exist; the UI backend stays read-only).

One endpoint, wired by ``register`` into the existing FastAPI app:

- ``GET /api/human_todo`` — ``{"items": [...], "counts": {...}}``,
  items oldest-first by ``since``, each
  ``{kind, id, title, since, detail, resolve_command}``. Kinds:

  - ``gate_verdict``     — ``loop_memory.jsonl`` rows with
    ``gate_status="pending"``, NO row in ``loop_feedback.jsonl``, AND a
    usable (non-empty dict) ``experiment_outcome``. The cockpit gates
    only experiment/applied-stage iterations awaiting owner sign-off;
    literature-stage pending rows (no ``experiment_outcome``) AUTO-ADVANCE
    — they stay observable via ``/api/loop_v0/iterations`` but never
    block the inbox (orchestrator/gate_cli.py is the resolve channel).
  - ``finding_review``   — ``surfaced_findings.jsonl`` rows whose EFFECTIVE
    status (base row overridden by the LAST
    ``surfaced_findings.status.jsonl`` row per finding_id) is ``surfaced``
    or ``in_review`` (orchestrator/finding_session.py REPL resolves).
  - ``bubble_ack``       — ``coordinator_bubbles.jsonl`` rows with no ack in
    ``memory/coordinator_acks.jsonl`` (absent file = nothing acked; the ack
    channel itself is pending main-session blessing — plan A5).
  - ``stale_active_run`` — ``run_state/active_run.json`` exists and its
    freshest of ``step_started_at``/``started_at`` is >30 min old (the
    known lock-leak failure). Malformed/missing timestamps = NOT stale.
  - ``state_gate``       — ``run_state/week1.state.json``
    ``human_gates_pending`` entries (inviolate rule 3: blocking).

Mirrors the ``coordinator.py`` register-fn idiom (same ``_read_jsonl``
tolerance of absent files and malformed lines). Read-only: the UI never
writes ``run_state/`` or ``memory/``. The endpoint never 500s on absent
or garbled data files.

Dev-session deferrals (D-046, additive): ``memory/dev_session_queue.jsonl``
is read alongside the sources above — rows fold by ``ref_id``, LAST status
wins (``defer`` appends ``status:"open"``, ``close`` appends
``status:"closed"``; mirrors ``orchestrator/todo_cli.py list_deferred``).
An item whose ``ref_id`` has an open deferral gets ``deferred: true`` plus
a ``deferral: {note, by, at}`` block — it is STILL listed and STILL counted
(the contract: a deferral assigns the work; it does not resolve the item).
No existing keys change.

Evidence ladder (2026-08-14, additive): a ``finding_review`` item carries
``evidence_level`` verbatim when its surfaced_findings row has one (new rows
do, per finding_promotion.py / D-059). Legacy rows stay key-absent — the
cockpit reads absence as below-bar.

Pointed gate-verdict copy (2026-08-18 #2): after ``owe_triage.enrich_items``
runs, ``_point_gate_verdicts`` overrides the three display keys (``doing`` /
``approval_means`` / ``vet``) on gate_verdict items with item-specific copy
joined from the loop_memory row and the idea-ledger reduction
(workers/idea_ledger.load_state, the /api/ladder import idiom). Every fact is
derived from a real record or omitted — never fabricated; a failed join
leaves the generic enrichment standing.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .owe_triage import enrich_items, membership_from_rows

KINDS = (
    "gate_verdict",
    "finding_review",
    "bubble_ack",
    "stale_active_run",
    "state_gate",
)

# active_run.json older than this (freshest timestamp) is a lock-leak suspect.
STALE_ACTIVE_RUN_AFTER = timedelta(minutes=30)

# Verdict enum mirrors schema/loop_feedback.schema.json (frozen shape).
_GATE_RESOLVE_TEMPLATE = (
    ".venv-chroma/bin/python -m orchestrator.gate_cli "
    "--iteration-id {iteration_id} --verdict <valid|invalid|needs_revision> "
    "--note '<why>'"
)
# finding_session is a REPL: launch it, then `start <finding_id>` and close
# with /validate, /reject, /spawn or /refine (orchestrator/finding_session.py).
_FINDING_RESOLVE_TEMPLATE = (
    ".venv-chroma/bin/python -m orchestrator.finding_session"
    "  # then: start {finding_id} ; /validate|/reject|/spawn|/refine <note>"
)
_BUBBLE_RESOLVE = (
    "(ack channel pending main-session blessing — see "
    "ui/notes/observability_reconciliation_plan.md A5)"
)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    # Producer's contract; skipping malformed rows keeps the
                    # endpoint useful while a primary-session bug is fixed.
                    continue
                # Bare scalars/arrays are valid JSON but not row records;
                # drop them like malformed lines (mirrors coordinator.py).
                if not isinstance(parsed, dict):
                    continue
                rows.append(parsed)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"unreadable: {exc}") from exc
    return rows


def _as_text(value, default: str = "") -> str:
    """Defensive coercion — producer-owned JSONL fields may be any shape."""
    if isinstance(value, str):
        return value
    if value is None:
        return default
    try:
        return str(value)
    except Exception:  # noqa: BLE001 — never let a weird repr 500 the endpoint
        return default


def _parse_ts(value) -> datetime | None:
    """Parse an ISO timestamp; None on anything unparseable. Naive values
    are taken as UTC (the producers stamp Z-suffixed UTC)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _item(kind: str, id_: str, title: str, since: str, detail: str,
          resolve_command: str) -> dict:
    return {
        "kind": kind,
        "id": id_,
        "title": title,
        "since": since,
        "detail": detail,
        "resolve_command": resolve_command,
    }


def _gate_verdict_items(memory_dir: Path) -> list[dict]:
    feedback_ids = {
        r.get("iteration_id")
        for r in _read_jsonl(memory_dir / "loop_feedback.jsonl")
    }
    items = []
    for row in _read_jsonl(memory_dir / "loop_memory.jsonl"):
        if row.get("gate_status") != "pending":
            continue
        iteration_id = _as_text(row.get("iteration_id"))
        if not iteration_id or iteration_id in feedback_ids:
            continue
        # Only experiment/applied-stage iterations are gated. The in-data
        # signal is a usable experiment_outcome dict; literature-stage rows
        # (absent/non-dict/empty experiment_outcome) auto-advance and are
        # dropped from the blocking inbox (still observable elsewhere).
        eo = row.get("experiment_outcome")
        if not isinstance(eo, dict) or not eo:
            continue
        seed = row.get("seed") if isinstance(row.get("seed"), dict) else {}
        item = _item(
            "gate_verdict",
            iteration_id,
            _as_text(seed.get("topic")) or iteration_id,
            _as_text(row.get("ended_at")),
            f"iteration {iteration_id} finished and awaits a human gate "
            "verdict (Step-8; no loop_feedback row yet)",
            _GATE_RESOLVE_TEMPLATE.format(iteration_id=iteration_id),
        )
        # Owe-card facts (2026-08-18, additive): the scalars the triage
        # enrichment turns into vet-first bullets. Only simple, present
        # values attach — absent facts stay key-absent, never fabricated.
        redteam = row.get("redteam")
        if isinstance(redteam, dict) and isinstance(redteam.get("verdict"), str):
            item["redteam_verdict"] = redteam["verdict"]
        if isinstance(eo.get("experiment_id"), str):
            item["experiment_id"] = eo["experiment_id"]
        for src_key, dst_key in (
            ("metric", "metric"), ("value", "metric_value"), ("trials", "trials"),
        ):
            value = eo.get(src_key)
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                item[dst_key] = value
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Pointed gate-verdict copy (owner ask 2026-08-18 #2: the three owe-card
# sections were GENERIC — "make it a little more pointed in what exactly the
# point of releasing this would be"). Runs AFTER owe_triage.enrich_items and
# overrides ONLY the three display keys (doing / approval_means / vet) on
# gate_verdict items whose loop_memory row is found. Every fact is derived
# from a real record or omitted — NEVER fabricated; when a join fails the
# generic enrichment stands. Frozen item keys are never touched.
# ---------------------------------------------------------------------------

# ui/backend/human_todo.py -> the checkout root (carries workers/), the same
# root app.py's DEFAULT_LOOP_V0_REPO resolves to when serving the primary.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The R1a redteam calibration battery date (bench/redteam_cal/runs/,
# PREREG_redteam_cal_2026-08-18.md): it measured the pre-battery redteam
# configuration condemning 6/7 parsed known-good fixtures. fatal_flaw rows
# that PREDATE the battery carry this caveat verbatim.
_REDTEAM_CAL_DATE = "2026-08-18"
_OLD_REDTEAM_CAVEAT = (
    "killed by the OLD redteam prompt — the R1a calibration battery "
    "(bench/redteam_cal/runs/, 2026-08-18) measured that configuration "
    "condemning 6/7 parsed known-good fixtures; treat the fatal_flaw as "
    "weak evidence, judge the hypothesis on its merits"
)

# One-line mechanical footnote — the state change itself is the headline.
_FEEDBACK_FOOTNOTE = (
    " (Mechanically: gate_cli appends one row to memory/loop_feedback.jsonl; "
    "readers are last-row-wins.)"
)


def _read_jsonl_quiet(path: Path) -> list[dict]:
    """_read_jsonl without the HTTPException: the pointing pass is display
    derivation and must never take the endpoint down over a side-store."""
    try:
        return _read_jsonl(path)
    except HTTPException:
        return []


def _head(value, limit: int) -> str:
    """Truncated single-line head of a producer-owned text field."""
    text = " ".join(_as_text(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _sub(row: dict, key: str) -> dict:
    value = row.get(key)
    return value if isinstance(value, dict) else {}


def _num(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None


# B1 perf memo (2026-08-18): the ledger reduction behind the pointed copy is
# re-derived ONLY when memory/idea_ledger.jsonl changes on disk. Key: the
# ledger path; value: (mtime_ns, size, (member_of, clusters)). The cached
# tuple is returned as-is — every consumer is READ-ONLY on it (the pointing
# pass only formats strings off the facts). The endpoint polls every 30 s;
# before the memo + the workers/idea_ledger.py precompiled validator, each
# warm request paid ~3 s of per-event jsonschema recompilation.
_LEDGER_MEMO: dict[str, tuple[int, int, tuple[dict, dict]]] = {}


def _ledger_clusters(memory_dir: Path) -> tuple[dict[str, str], dict[str, dict]]:
    """(member_id -> cluster_id, cluster_id -> facts) off the idea ledger.

    member_id -> cluster_id is ``owe_triage.membership_from_rows`` — the ONE
    deterministic join (last membership event in ledger file order wins)
    shared with the triage enrichment, so the card's cluster block and the
    pointed copy CANNOT disagree (B2 fix 2026-08-18: the old set-union walk
    here mapped dup-relinked members PYTHONHASHSEED-dependently).

    Primary path for cluster facts: ``workers.idea_ledger.load_state`` — the
    SAME reducer the /api/ladder seam uses, imported the same way (repo root
    on sys.path, lazy). The raw ``cluster_killed`` events are scanned
    tolerantly alongside for the kill timestamp (the reduction keeps
    last_event_ts, not per-event stamps); a ``cluster_reopened`` event
    clears the raw-scan kill exactly as the reducer does. Fallback on ANY
    reducer failure (workers unimportable, schema-invalid ledger): the
    tolerant raw scan alone — the endpoint never 500s, and facts only the
    reducer knows are omitted, never fabricated.

    Warm calls are memoized on the ledger file's (mtime_ns, size) — the
    reduction re-runs only when the file changes (B1; consumers are
    read-only on the result)."""
    path = Path(memory_dir) / "idea_ledger.jsonl"
    memo_key: str | None = None
    memo_id: tuple[int, int] | None = None
    try:
        stat = path.stat()
        memo_key = str(path)
        memo_id = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        pass  # absent/unstatable ledger: compute (cheaply) without the memo
    if memo_key is not None:
        hit = _LEDGER_MEMO.get(memo_key)
        if hit is not None and (hit[0], hit[1]) == memo_id:
            return hit[2]

    rows = _read_jsonl_quiet(path)
    member_of = membership_from_rows(rows)
    kills: dict[str, dict] = {}
    raw_members: dict[str, list[str]] = {}
    for row in rows:
        cid = row.get("cluster_id")
        if not isinstance(cid, str) or not cid:
            continue
        event = row.get("event_type")
        if event in ("cluster_created", "member_added"):
            for key in ("member_id", "iteration_id"):
                member = row.get(key)
                if isinstance(member, str) and member:
                    bucket = raw_members.setdefault(cid, [])
                    if member not in bucket:
                        bucket.append(member)
        elif event == "cluster_killed":
            kills[cid] = row
        elif event == "cluster_reopened":
            # The raw fallback honors reopen like the reducer: kill cleared
            # (2026-08-18 fix — a reopened cluster is live, not killed).
            kills.pop(cid, None)

    state: dict[str, dict] = {}
    if path.exists():
        try:
            root = str(_REPO_ROOT)
            if root not in sys.path:
                sys.path.insert(0, root)
            from workers.idea_ledger import load_state  # ladder.py idiom
            loaded = load_state(path)
            if isinstance(loaded, dict):
                state = loaded
        except Exception:  # noqa: BLE001 — reducer trouble = raw scan only
            state = {}

    clusters: dict[str, dict] = {}
    for cid in set(raw_members) | set(kills) | set(state):
        c = state.get(cid) if isinstance(state.get(cid), dict) else {}
        members = c.get("members") if isinstance(c.get("members"), list) else None
        if members is None:
            members = raw_members.get(cid, [])
        members = [m for m in members if isinstance(m, str) and m]
        # Reducer status wins when known; both paths honor cluster_reopened
        # (the reducer via kill_reason=None, the raw scan via kills.pop).
        killed = (c.get("status") == "killed") if c else (cid in kills)
        kill_event = kills.get(cid, {})
        reason = c.get("kill_reason")
        if not isinstance(reason, dict):
            reason = kill_event.get("kill_reason")
            reason = reason if isinstance(reason, dict) else {}
        reopen = c.get("reopening_condition")
        if not isinstance(reopen, dict):
            reopen = kill_event.get("reopening_condition")
            reopen = reopen if isinstance(reopen, dict) else {}
        clusters[cid] = {
            "cluster_id": cid,
            "killed": killed,
            "members": members,
            "status": _as_text(c.get("status")) or ("killed" if killed else ""),
            "evidence_level": _as_text(c.get("evidence_level")),
            "kill_code": _as_text(reason.get("code")) if killed else "",
            "kill_evidence_key": _as_text(reason.get("evidence_key")) if killed else "",
            "kill_ts": (_as_text(kill_event.get("ts"))
                        or _as_text(c.get("last_event_ts"))) if killed else "",
            "reopen_kind": _as_text(reopen.get("evidence_kind")) if killed else "",
        }
    result = (member_of, clusters)
    if memo_key is not None and memo_id is not None:
        _LEDGER_MEMO[memo_key] = (memo_id[0], memo_id[1], result)
    return result


def _pointed_doing(row: dict, cluster: dict | None) -> str:
    """WHAT YOU'RE DOING, item-specific: the hypothesis being judged, the
    experiment facts, and where the idea ledger already placed this idea."""
    lead = "You are judging whether this finished iteration's record is sound"
    hyp = _head(_sub(row, "hypothesis").get("text"), 200)
    if hyp:
        lead += f' — hypothesis: "{hyp}"'
    parts = [lead + "."]
    eo = _sub(row, "experiment_outcome")
    exp_id = _as_text(eo.get("experiment_id"))
    metric = _as_text(eo.get("metric"))
    value = _num(eo.get("value"))
    if exp_id and metric and value is not None:
        sentence = f"Its experiment {exp_id} measured {metric}={value}"
        trials = _num(eo.get("trials"))
        if trials is not None:
            sentence += f" over {trials} trials"
        parts.append(sentence + ".")
    if cluster:
        if cluster["killed"]:
            parts.append(
                f"The idea ledger folded it into cluster "
                f"{cluster['cluster_id']}, KILLED "
                f"{cluster['kill_ts'][:10] or 'undated'} "
                f"({cluster['kill_code'] or 'unknown code'})."
            )
        else:
            level = (f", evidence {cluster['evidence_level']}"
                     if cluster["evidence_level"] else "")
            parts.append(
                f"The idea ledger tracks it in cluster "
                f"{cluster['cluster_id']} ({cluster['status'] or 'open'}"
                f"{level})."
            )
    return " ".join(parts)


def _pointed_means(row: dict, cluster: dict | None) -> str:
    """WHAT APPROVAL MEANS, consequence-specific. Only REAL consequences —
    each named consumer verified by grep: orchestrator/coordinator.py joins
    the verdict as human_verdict + drops the row from open threads (killed-
    cluster members are already excluded, D-059); workers/evidence_ladder.py
    L5 rung passes only on verdict 'valid'; orchestrator/finding_promotion.py
    and workers/consolidate_memory.py derive levels from that same feedback
    join; workers/meta_review.py folds the verdict into the digest Gemma
    reads. Killed clusters: schema/idea_ledger reopening_condition — a
    verdict is not the 'new_evidence' a reopen requires."""
    if cluster and cluster["killed"]:
        code = cluster["kill_code"] or "unknown code"
        date = cluster["kill_ts"][:10] or "an unrecorded date"
        # Calibration claim softened (2026-08-18): no automated scorer joins
        # loop_feedback to calibration entries today — the cockpit's
        # calibration page exists, but that comparison is a manual read.
        text = (
            f"Cluster {cluster['cluster_id']} is already KILLED ({code}, "
            f"{date}) — this verdict settles the historical record, nothing "
            "downstream re-runs (it can feed your calibration review, but "
            "that join is manual today — the cockpit calibration page has "
            "no automated loop_feedback scorer). It does NOT "
            "reopen the cluster: reopening needs new evidence"
        )
        if cluster["reopen_kind"]:
            text += f" ({cluster['reopen_kind']})"
        text += " per the ledger's reopening_condition."
        if code in ("experiment_null_effect", "experiment_invalid"):
            iid = _as_text(row.get("iteration_id"))
            exp_id = _as_text(_sub(row, "experiment_outcome").get("experiment_id"))
            # Exact ':'-segment match, never substring (2026-08-18 fix: an
            # iteration id substring-matched "cluster:cl-<same-id>" keys).
            segments = cluster["kill_evidence_key"].split(":")
            if (iid and iid in segments) or (exp_id and exp_id in segments):
                text += (
                    " The kill already consumed this iteration's null "
                    "result — your verdict is a record-keeping close-out."
                )
        text += (
            " The coordinator already excludes killed-cluster members from "
            "its open threads (orchestrator/coordinator.py, D-059)."
        )
        return text + _FEEDBACK_FOOTNOTE
    return (
        "A 'valid' verdict lifts this iteration to L5 on the evidence "
        "ladder: the L5 rung (workers/evidence_ladder.py) passes only on "
        "verdict 'valid', while 'invalid' or 'needs_revision' holds it "
        "below L5. That ladder level is what promotion eligibility reads "
        "(orchestrator/finding_promotion.py), and workers/meta_review.py "
        "folds your verdict into the meta-review digest Gemma reads. Any "
        "verdict also removes the iteration from the coordinator's open "
        "threads (orchestrator/coordinator.py)."
    ) + _FEEDBACK_FOOTNOTE


def _pointed_probes(row: dict, cluster: dict | None) -> list[str]:
    """VET FIRST: pointed probes with values inline, each derived from the
    row (or the ledger), ordered by decisiveness, capped at 5. Absent facts
    contribute NOTHING."""
    probes: list[tuple[int, str]] = []
    iid = _as_text(row.get("iteration_id"))

    # Redteam — a fatal_flaw hard-caps the ladder at L0, so it leads. Rows
    # predating the 2026-08-18 R1a battery get the measured-miscalibration
    # caveat; later rows get the verdict + critique head.
    red = _sub(row, "redteam")
    red_verdict = _as_text(red.get("verdict"))
    row_date = (_as_text(row.get("ended_at"))
                or _as_text(row.get("started_at")))[:10]
    if red_verdict == "fatal_flaw":
        # Date basis for the caveat: the row's own stamps, else the ledger
        # kill stamp — and a row with NO usable date at all FAILS TOWARD THE
        # WARNING (2026-08-18 fix: an undated legacy row used to lose the
        # old-redteam caveat; every legacy row predates the battery anyway).
        date = row_date if len(row_date) == 10 else ""
        if not date and cluster:
            kill_date = _as_text(cluster.get("kill_ts"))[:10]
            if len(kill_date) == 10:
                date = kill_date
        if not date or date < _REDTEAM_CAL_DATE:
            probes.append((0, _OLD_REDTEAM_CAVEAT))
        else:
            crit = _head(red.get("critique"), 140)
            probes.append((0, (
                f"redteam: fatal_flaw — {crit}" if crit else
                "redteam: fatal_flaw — read the full critique in the dossier"
            )))
    elif red_verdict:
        probes.append((8, (
            f"redteam: {red_verdict} — no fatal flaw claimed; the headline "
            "still needs your own read"
        )))

    # Retrieval confidence — a thin/off-topic retrieval undermines novelty
    # AND survival at once.
    rel = _sub(_sub(row, "retrieval"), "relevance")
    if rel.get("low_confidence"):
        reason = _head(rel.get("reason"), 120)
        probes.append((1, (
            f"retrieval was thin/off-topic (reason: {reason or 'unstated'}) "
            "— check whether the cited neighbors actually support the claim"
        )))

    # Adversarial pass — debate transcript > lone skeptic verdict > the
    # honest pre-D-065 gap (no independent skeptic ever saw the row).
    crit_block = _sub(row, "critique")
    debate = crit_block.get("debate")
    debate = debate if isinstance(debate, dict) else None
    skeptic = _as_text(crit_block.get("skeptic_verdict"))
    if debate:
        rounds = debate.get("rounds")
        rounds = rounds if isinstance(rounds, int) and not isinstance(rounds, bool) else "?"
        probes.append((2, (
            f"read the challenger's strongest round {rounds} attack in the "
            "dossier debate transcript (verdict: "
            f"{_as_text(debate.get('verdict')) or 'unstated'})"
        )))
    elif skeptic:
        probes.append((2, (
            f"independent skeptic verdict: {skeptic} — weigh it against the "
            f"critic's own '{_as_text(crit_block.get('verdict')) or '?'}'"
        )))
    else:
        probes.append((2, (
            "pre-debate-era row: no independent skeptic ever saw this — "
            "your read is the ONLY adversarial pass"
        )))

    # Experiment — does the number discriminate, per the locked rule?
    eo = _sub(row, "experiment_outcome")
    metric = _as_text(eo.get("metric"))
    value = _num(eo.get("value"))
    if metric and value is not None:
        where = _as_text(eo.get("results_path")) or "the prereg/results path"
        probes.append((3, (
            f"does {metric}={value} actually discriminate the hypothesis "
            f"from the null? check the locked decision rule in {where}"
        )))

    # Novelty — rediscovery/unclear are the classes worth leading with.
    nov = _sub(row, "novelty")
    nov_class = _as_text(nov.get("class"))
    if nov_class:
        rationale = _head(nov.get("rationale"), 140)
        priority = 4 if nov_class in ("rediscovery", "unclear") else 7
        probes.append((priority, (
            f"novelty: {nov_class}" + (f" — {rationale}" if rationale else "")
        )))

    # Duplicates — the ledger folded siblings in as the same idea.
    if cluster:
        siblings = [m for m in cluster["members"] if m and m != iid][:2]
        if siblings:
            probes.append((5, (
                f"cluster {cluster['cluster_id']} also holds "
                f"{', '.join(siblings)} — the ledger folded these as ONE "
                "idea; check the sibling record before judging this one in "
                "isolation"
            )))

    # Top retrieval neighbor — is the hypothesis just a restatement?
    neighbors = _sub(row, "retrieval").get("neighbors")
    top = (neighbors[0] if isinstance(neighbors, list) and neighbors
           and isinstance(neighbors[0], dict) else None)
    if top:
        name = _as_text(top.get("doc_id")) or _as_text(top.get("title"))
        score = _num(top.get("score"))
        if name and score is not None:
            title = _as_text(top.get("title"))
            shown = (f"{name} ('{_head(title, 60)}')"
                     if title and title != name else name)
            probes.append((6, (
                f"top retrieval neighbor {shown} at score {score} — verify "
                "the hypothesis is not a restatement of it"
            )))

    probes.sort(key=lambda pair: pair[0])
    return [text for _priority, text in probes[:5]]


def _point_gate_verdicts(items: list[dict], memory_dir: Path) -> None:
    """Override doing / approval_means / vet on gate_verdict items with the
    pointed, record-joined copy. In place, after owe_triage.enrich_items;
    any per-item failure leaves that item's generic enrichment standing."""
    gate_items = [i for i in items if i.get("kind") == "gate_verdict"]
    if not gate_items:
        return
    try:
        rows_by_id: dict[str, dict] = {}
        for row in _read_jsonl_quiet(Path(memory_dir) / "loop_memory.jsonl"):
            row_id = row.get("iteration_id")
            if isinstance(row_id, str) and row_id:
                rows_by_id[row_id] = row
        member_of, clusters = _ledger_clusters(Path(memory_dir))
    except Exception:  # noqa: BLE001 — pointing must never cost the queue
        return
    for item in gate_items:
        try:
            item_id = _as_text(item.get("id"))
            row = rows_by_id.get(item_id)
            if row is None:
                continue
            cid = member_of.get(item_id)
            if cid is None and f"cl-{item_id}" in clusters:
                cid = f"cl-{item_id}"  # the consolidator's self-named convention
            cluster = clusters.get(cid) if cid else None
            doing = _pointed_doing(row, cluster)
            means = _pointed_means(row, cluster)
            probes = _pointed_probes(row, cluster)
            if doing:
                item["doing"] = doing
            if means:
                item["approval_means"] = means
            if probes:
                item["vet"] = probes
        except Exception:  # noqa: BLE001 — one bad row must not strip the rest
            continue


def _finding_review_items(memory_dir: Path) -> list[dict]:
    findings = _read_jsonl(memory_dir / "surfaced_findings.jsonl")
    # Effective status = LAST audit row per finding_id overriding the base
    # row (surfaced_findings.jsonl is never edited in place).
    overrides: dict[str, str] = {}
    for status_row in _read_jsonl(memory_dir / "surfaced_findings.status.jsonl"):
        fid = status_row.get("finding_id")
        if isinstance(fid, str) and fid:
            overrides[fid] = _as_text(status_row.get("status"))
    items = []
    for finding in findings:
        fid = _as_text(finding.get("finding_id"))
        if not fid:
            continue
        status = overrides.get(fid, _as_text(finding.get("status")))
        if status not in ("surfaced", "in_review"):
            continue
        item = _item(
            "finding_review",
            fid,
            _as_text(finding.get("title")) or fid,
            _as_text(finding.get("promoted_at")),
            f"promoted finding awaits human interrogation (status: {status})",
            _FINDING_RESOLVE_TEMPLATE.format(finding_id=fid),
        )
        # Evidence-ladder pass-through (2026-08-14 work order B): new
        # surfaced rows carry `evidence_level` (finding_promotion.py, D-059);
        # the cockpit inbox filters on it (L4/L5 = above the bar). ADDITIVE
        # and only when present as a string — legacy rows stay key-absent,
        # which the frontend reads as below-bar/demoted.
        level = finding.get("evidence_level")
        if isinstance(level, str) and level:
            item["evidence_level"] = level
        items.append(item)
    return items


def _bubble_ack_items(memory_dir: Path) -> list[dict]:
    acked = {
        a.get("bubble_run_id")
        for a in _read_jsonl(memory_dir / "coordinator_acks.jsonl")
    }
    items = []
    for bubble in _read_jsonl(memory_dir / "coordinator_bubbles.jsonl"):
        run_id = _as_text(bubble.get("run_id"))
        if run_id and run_id in acked:
            continue
        items.append(_item(
            "bubble_ack",
            run_id or _as_text(bubble.get("timestamp")),
            _as_text(bubble.get("note")) or "(bubble with no note)",
            _as_text(bubble.get("timestamp")),
            "the loop raised this to the human; no acknowledgement recorded",
            _BUBBLE_RESOLVE,
        ))
    return items


def _stale_active_run_items(run_state_dir: Path) -> list[dict]:
    path = run_state_dir / "active_run.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Unreadable/garbled mirror is a producer problem, not a TODO we can
        # date — and "malformed = NOT stale" by contract.
        return []
    if not isinstance(data, dict):
        return []
    stamps = [
        ts for ts in (
            _parse_ts(data.get("step_started_at")),
            _parse_ts(data.get("started_at")),
        ) if ts is not None
    ]
    if not stamps:
        return []  # missing/malformed timestamps = NOT stale
    freshest = max(stamps)
    if datetime.now(timezone.utc) - freshest <= STALE_ACTIVE_RUN_AFTER:
        return []
    return [_item(
        "stale_active_run",
        _as_text(data.get("run_id")) or "active_run",
        "investigate/clear stale active_run — possible lock-leak",
        freshest.isoformat().replace("+00:00", "Z"),
        f"run_state/active_run.json claims a live run (kind="
        f"{_as_text(data.get('kind')) or '?'}) but its freshest timestamp "
        f"is over {int(STALE_ACTIVE_RUN_AFTER.total_seconds() // 60)} min old",
        "inspect run_state/active_run.json; if no apparatus process is "
        "live, remove the file (lock-leak cleanup)",
    )]


def _state_gate_items(run_state_dir: Path) -> list[dict]:
    path = run_state_dir / "week1.state.json"
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(state, dict):
        return []
    gates = state.get("human_gates_pending")
    if not isinstance(gates, list):
        return []
    items = []
    for index, gate in enumerate(gates):
        if isinstance(gate, dict):
            gate_id = (_as_text(gate.get("id")) or _as_text(gate.get("gate_id"))
                       or _as_text(gate.get("task_id")) or f"state-gate-{index}")
            title = (_as_text(gate.get("title")) or _as_text(gate.get("description"))
                     or _as_text(gate.get("note")) or gate_id)
            since = (_as_text(gate.get("since")) or _as_text(gate.get("created_at"))
                     or _as_text(gate.get("timestamp")))
        else:
            gate_id = f"state-gate-{index}"
            title = _as_text(gate) or gate_id
            since = ""
        items.append(_item(
            "state_gate",
            gate_id,
            title,
            since,
            "human_gates_pending entry in run_state/week1.state.json — "
            "blocking until the human explicitly clears it (inviolate rule 3)",
            "the human clears the gate explicitly in the primary session; "
            "the entry is then removed from run_state/week1.state.json",
        ))
    return items


def _open_deferrals(memory_dir: Path) -> dict[str, dict]:
    """Fold ``memory/dev_session_queue.jsonl`` by ``ref_id`` — LAST status
    wins (``defer`` appends ``status:"open"``, ``close`` appends
    ``status:"closed"``; the ledger is append-only, never edited in place).
    Returns ref_id -> the winning OPEN row. Same fold as
    ``orchestrator/todo_cli.py list_deferred``: the ledger's identity key is
    ``ref_id`` alone. Absent file == no deferrals (D-046; the ledger is new
    and gitignored)."""
    folded: dict[str, dict] = {}
    for row in _read_jsonl(memory_dir / "dev_session_queue.jsonl"):
        ref = row.get("ref_id")
        if not isinstance(ref, str) or not ref:
            continue
        status = row.get("status")
        if status == "open":
            folded[ref] = row  # last open row wins (freshest note)
        elif status == "closed":
            folded.pop(ref, None)
        # Unknown statuses: skipped, like malformed lines — a future writer's
        # contract is not ours to interpret.
    return folded


def _tag_deferred(items: list[dict], memory_dir: Path) -> None:
    """ADDITIVE in place: an item whose id has an open deferral gains
    ``deferred: true`` + ``deferral: {note, by, at}``. The item stays listed
    and stays counted — a deferral assigns the work; it does not resolve the
    item. Untagged items are untouched (no existing keys change)."""
    deferrals = _open_deferrals(memory_dir)
    if not deferrals:
        return
    for item in items:
        row = deferrals.get(item["id"])
        if row is None:
            continue
        item["deferred"] = True
        item["deferral"] = {
            "note": _as_text(row.get("note")),
            "by": _as_text(row.get("attested_by")),
            "at": _as_text(row.get("deferred_at")),
        }


def register(
    app,
    *,
    run_state_dir: Path,
    memory_dir: Path,
) -> APIRouter:
    """Attach the human-TODO router. Reads loop_memory / loop_feedback /
    surfaced_findings(+status) / bubbles / acks from ``memory_dir`` and
    active_run.json / week1.state.json from ``run_state_dir`` (the same
    split ``coordinator.register`` uses)."""
    router = APIRouter(prefix="/api/human_todo", tags=["human_todo"])

    @router.get("")
    def human_todo():
        """Everything awaiting the human, oldest-first by ``since``, each
        with the exact CLI command that resolves it. Never 500s on absent
        or garbled data files."""
        run_state = Path(run_state_dir)
        memory = Path(memory_dir)
        items: list[dict] = []
        items.extend(_gate_verdict_items(memory))
        items.extend(_finding_review_items(memory))
        items.extend(_bubble_ack_items(memory))
        items.extend(_stale_active_run_items(run_state))
        items.extend(_state_gate_items(run_state))
        # D-046 additive fold: tag (never remove) items with open deferrals.
        _tag_deferred(items, memory)
        # Owe-card triage (2026-08-18, additive): action phrase, what the
        # approval means, vet-first bullets, and the documented
        # likely-superseded / observable heuristics off idea_ledger.jsonl.
        # Tags never dismiss — every item stays listed and counted.
        enrich_items(items, memory)
        # Pointed gate-verdict copy (owner ask 2026-08-18 #2): join each
        # item's loop_memory row + the idea-ledger reduction so the card
        # says exactly WHAT is being judged, what the verdict CHANGES, and
        # what to PROBE — overriding the generic doing/approval_means/vet.
        _point_gate_verdicts(items, memory)
        # Oldest-first: the longest-waiting item tops the queue. Items with
        # no parseable `since` sort first (unknown age is surfaced, not hidden).
        items.sort(key=lambda item: item.get("since") or "")
        counts = {kind: 0 for kind in KINDS}
        for item in items:
            counts[item["kind"]] += 1
        return {"items": items, "counts": counts}

    app.include_router(router)
    return router
