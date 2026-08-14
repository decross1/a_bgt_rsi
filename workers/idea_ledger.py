"""Worker: idea-ledger event log + deterministic reducer + MAP-Elites acceptance
(LOOP_V1 P3, agent A3, D-060).

The ledger (`memory/idea_ledger.jsonl`) is an APPEND-ONLY event log; every
cluster state is a deterministic reduction over it — nothing here rewrites a
line, and `load_state` re-derives the same state from the same file every time.
Events are jsonschema-validated against `schema/idea_ledger.schema.json` at
BOTH append and load (an invalid line is a loud failure, never a skipped row —
rule 4).

MAP-Elites acceptance (`accept_candidate`): dedup-ladder clusters are the
niches (no descriptor grid). The prefilter REUSES the load-bearing layers from
`workers/mine_paper_gap.py` via import — lexical Jaccard (`JACCARD_DUP`, the
gate) then high-cosine (`TAU_DUP`, near-identical only) — never a
reimplemented embed. The LLM equivalence-or-better judge is an INJECTED seam
(`judge_fn`, the `workers/idea_judge.judge_pair` signature): when None (the
shipped default until judge calibration passes — LOOP_V1 P3 bars), the
prefilter alone decides.

Kill reasons are PROGRAMMATIC — a closed `code` enum built only by the
`kill_reason_from_*` builders from structured signals (Honest Lying 0/121:
never LLM prose). A builder given a non-condemning signal RAISES (a survivor
is never coerced into a kill). Reopening is evidence-keyed: a `cluster_killed`
event carries `reopening_condition = {"requires": "new_evidence",
"evidence_kind": ...}` and a `cluster_reopened` event must present matching
`evidence.evidence_kind` — the reducer refuses a mismatched reopen.

Derived status rule (pure, documented): `killed` while a kill stands;
otherwise `surfaced` iff evidence_level is L4/L5 (the surfacing bar, D-059);
otherwise `open`. Paper niches (`niche_seeded`) reduce to PRE-CLOSED clusters
(status `killed`, code `paper_prior_exists`, reopening on `articulated_delta`,
origin `paper_seed`) — rediscovery must articulate a delta to get back in.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

import jsonschema

from workers import mine_paper_gap
from workers.retrieval_relevance import _tokenize

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
SCHEMA_PATH = REPO_ROOT / "schema" / "idea_ledger.schema.json"

# Closed kill-code enum — MUST mirror schema/idea_ledger.schema.json.
KILL_CODES = (
    "redteam_fatal_flaw",
    "adversarial_refuted",
    "experiment_invalid",
    "experiment_null_effect",
    "paper_prior_exists",
)

# Evidence-ladder rungs at/above the surfacing bar (D-059: only L4+ surfaces).
_SURFACED_LEVELS = frozenset({"L4", "L5"})

_EVENT_TYPES = frozenset({
    "cluster_created", "member_added", "evidence_level_changed",
    "cluster_killed", "cluster_reopened", "niche_seeded",
    "agenda_item_added", "agenda_item_consumed",
})

_schema_cache: dict[str, Any] | None = None


def _schema() -> dict[str, Any]:
    global _schema_cache
    if _schema_cache is None:
        _schema_cache = json.loads(SCHEMA_PATH.read_text())
    return _schema_cache


def validate_event(event: dict[str, Any]) -> None:
    """jsonschema-validate one event. Raises jsonschema.ValidationError."""
    jsonschema.validate(event, _schema())


# ── Event log I/O ────────────────────────────────────────────────────────────

def append_event(path: str | Path, event: dict) -> None:
    """Validate + append one event line. Append-only: never rewrites."""
    validate_event(event)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _read_events(path: str | Path) -> list[dict[str, Any]]:
    """Read + validate every line. A malformed or schema-invalid line RAISES
    (rule 4: a broken ledger is a loud failure, never a silently thinner
    state). Missing file -> [] (an empty ledger is a legitimate cold start)."""
    p = Path(path)
    if not p.exists():
        return []
    events: list[dict[str, Any]] = []
    for i, line in enumerate(p.read_text().splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"idea_ledger: malformed JSON at {p}:{i}: {e}") from e
        validate_event(obj)
        events.append(obj)
    return events


# ── Deterministic reducer ────────────────────────────────────────────────────

def _new_cluster(cluster_id: str, origin: str, ts: str) -> dict[str, Any]:
    return {
        "cluster_id": cluster_id,
        "status": "open",
        "evidence_level": "L0",
        "elite": None,
        "members": [],
        "kill_reason": None,
        "reopening_condition": None,
        "origin": origin,
        "last_event_ts": ts,
        "agenda": [],  # additive: [{"topic","source","status","ts"}]
    }


def _derived_status(c: dict[str, Any]) -> str:
    if c["kill_reason"] is not None:
        return "killed"
    return "surfaced" if c["evidence_level"] in _SURFACED_LEVELS else "open"


def reduce_events(events: list[dict]) -> dict[str, dict]:
    """Pure, order-stable fold of validated events into cluster states keyed
    by cluster_id. Same event list -> same state, byte-for-byte under
    json.dumps. Never mutates its input. Semantic violations (unknown
    cluster, duplicate create, mismatched reopen key, elite without a claim)
    RAISE — an inconsistent ledger is never coerced into a state (rule 4)."""
    state: dict[str, dict] = {}
    for i, ev in enumerate(events):
        et, cid, ts = ev["event_type"], ev["cluster_id"], ev["ts"]
        if et not in _EVENT_TYPES:  # schema already guards; belt-and-braces
            raise ValueError(f"idea_ledger: unknown event_type {et!r} at index {i}")
        if et == "cluster_created":
            if cid in state:
                raise ValueError(f"idea_ledger: duplicate cluster_created for {cid!r} at index {i}")
            c = _new_cluster(cid, ev["origin"], ts)
            c["members"] = [ev["member_id"]]
            c["evidence_level"] = ev.get("evidence_level", "L0")
            if ev.get("claim") is not None:
                c["elite"] = {
                    "claim": copy.deepcopy(ev["claim"]),
                    "iteration_id": ev.get("iteration_id") or ev["member_id"],
                }
            state[cid] = c
        elif et == "niche_seeded":
            if cid in state:
                raise ValueError(f"idea_ledger: duplicate niche_seeded for {cid!r} at index {i}")
            paper = ev["paper"]
            c = _new_cluster(cid, "paper_seed", ts)
            c["members"] = [f"paper:{paper['arxiv_id']}"]
            c["kill_reason"] = {
                "code": "paper_prior_exists",
                "evidence_key": f"papers_recent:{paper['arxiv_id']}",
                "detail": f"pre-closed paper niche: {paper['title']}",
            }
            c["reopening_condition"] = {
                "requires": "new_evidence", "evidence_kind": "articulated_delta",
            }
            state[cid] = c
        else:
            c = state.get(cid)
            if c is None:
                raise ValueError(
                    f"idea_ledger: {et} for unknown cluster {cid!r} at index {i} "
                    f"(no prior cluster_created/niche_seeded)"
                )
            if et == "member_added":
                if ev["member_id"] not in c["members"]:
                    c["members"].append(ev["member_id"])
                if ev.get("as_elite"):
                    if ev.get("claim") is None:
                        raise ValueError(
                            f"idea_ledger: member_added as_elite without a claim "
                            f"({cid!r} at index {i}) — an elite is a claim record"
                        )
                    c["elite"] = {
                        "claim": copy.deepcopy(ev["claim"]),
                        "iteration_id": ev.get("iteration_id") or ev["member_id"],
                    }
            elif et == "evidence_level_changed":
                c["evidence_level"] = ev["evidence_level"]
            elif et == "cluster_killed":
                c["kill_reason"] = copy.deepcopy(ev["kill_reason"])
                c["reopening_condition"] = copy.deepcopy(ev["reopening_condition"])
            elif et == "cluster_reopened":
                if c["kill_reason"] is None:
                    raise ValueError(
                        f"idea_ledger: cluster_reopened on a non-killed cluster "
                        f"({cid!r} at index {i})"
                    )
                want = (c["reopening_condition"] or {}).get("evidence_kind")
                got = ev["evidence"]["evidence_kind"]
                if got != want:
                    raise ValueError(
                        f"idea_ledger: reopen evidence_kind {got!r} does not match "
                        f"reopening_condition {want!r} for {cid!r} at index {i} — "
                        f"evidence-keyed reopening is never coerced (rule 4)"
                    )
                c["kill_reason"] = None
                c["reopening_condition"] = None
            elif et == "agenda_item_added":
                c["agenda"].append({
                    "topic": ev["topic"], "source": ev["source"],
                    "status": "pending", "ts": ts,
                })
            elif et == "agenda_item_consumed":
                hit = next((a for a in c["agenda"]
                            if a["topic"] == ev["topic"] and a["status"] == "pending"), None)
                if hit is None:
                    raise ValueError(
                        f"idea_ledger: agenda_item_consumed with no pending item "
                        f"{ev['topic']!r} on {cid!r} at index {i}"
                    )
                hit["status"] = "consumed"
            c["last_event_ts"] = ts
        state[cid]["status"] = _derived_status(state[cid])
    return state


def load_state(path: str | Path) -> dict[str, dict]:
    """Read + validate the ledger, reduce to cluster states keyed by
    cluster_id. Deterministic: same file -> same dict."""
    return reduce_events(_read_events(path))


# ── Programmatic kill_reason builders (enum codes, never free prose) ─────────

def kill_reason_from_redteam(row: dict) -> dict[str, str]:
    """Build the kill_reason for a redteam fatal_flaw. `row` is an iteration
    row (loop_memory shape). RAISES when the verdict is not fatal_flaw —
    a survivor is never coerced into a kill."""
    rt = row.get("redteam") if isinstance(row.get("redteam"), dict) else {}
    verdict = rt.get("verdict")
    if verdict != "fatal_flaw":
        raise ValueError(
            f"kill_reason_from_redteam: verdict {verdict!r} is not 'fatal_flaw' — refusing to build a kill"
        )
    iteration_id = row.get("iteration_id") or "unknown"
    return {
        "code": "redteam_fatal_flaw",
        "evidence_key": f"iteration:{iteration_id}:redteam",
        "detail": f"redteam verdict fatal_flaw on iteration {iteration_id}",
    }


def kill_reason_from_adversarial(block: dict) -> dict[str, str]:
    """Build the kill_reason for a refuted adversarial vote (survived=False).
    RAISES when the block says survived=True."""
    if block.get("survived") is not False:
        raise ValueError(
            f"kill_reason_from_adversarial: survived={block.get('survived')!r} — refusing to build a kill"
        )
    ref = block.get("iteration_id") or block.get("finding_id") or "unknown"
    votes = block.get("votes")
    tally = f" (votes {votes})" if isinstance(votes, (str, int)) else ""
    return {
        "code": "adversarial_refuted",
        "evidence_key": f"iteration:{ref}:adversarial",
        "detail": f"adversarial skeptic vote refuted iteration {ref}{tally}",
    }


def kill_reason_from_experiment(outcome: dict) -> dict[str, str]:
    """Build the kill_reason from an experiment_outcome: INVALID summary ->
    experiment_invalid; effect_confirmed=False -> experiment_null_effect.
    RAISES on a confirming/ambiguous outcome."""
    ref = outcome.get("iteration_id") or outcome.get("experiment_id") or "unknown"
    summary = outcome.get("summary")
    if isinstance(summary, str) and "INVALID" in summary.upper():
        return {
            "code": "experiment_invalid",
            "evidence_key": f"iteration:{ref}:experiment_outcome",
            "detail": f"experiment outcome INVALID on {ref}",
        }
    if outcome.get("effect_confirmed") is False:
        return {
            "code": "experiment_null_effect",
            "evidence_key": f"iteration:{ref}:experiment_outcome",
            "detail": f"predicted effect not observed on {ref} (trials={outcome.get('trials')})",
        }
    raise ValueError(
        "kill_reason_from_experiment: outcome neither INVALID nor "
        "effect_confirmed=False — refusing to build a kill"
    )


def reopening_condition(evidence_kind: str) -> dict[str, str]:
    """The evidence-keyed reopening condition attached at kill time."""
    if not (isinstance(evidence_kind, str) and evidence_kind):
        raise ValueError("reopening_condition: evidence_kind must be a non-empty str")
    return {"requires": "new_evidence", "evidence_kind": evidence_kind}


# ── MAP-Elites acceptance ────────────────────────────────────────────────────

def _claim_text(obj: Any) -> str:
    """Comparison surface for a candidate / elite. Claim records join their
    three canonical fields; a bare {"text": ...} or str passes through."""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        claim = obj.get("claim") if isinstance(obj.get("claim"), dict) else obj
        parts = [claim.get(k) for k in ("problem", "mechanism", "predicted_effect")]
        joined = " ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
        if joined:
            return joined
        if isinstance(obj.get("text"), str):
            return obj["text"].strip()
    return ""


def _prefilter_dup_layer(cand_text: str, elite_text: str) -> tuple[str | None, float]:
    """The mine_paper_gap prefilter, reused via import: lexical Jaccard first
    (the LOAD-BEARING gate, JACCARD_DUP), then high cosine (TAU_DUP,
    near-identical only). Returns (kill_layer|None, score)."""
    lex = mine_paper_gap._lexical_overlap(_tokenize(cand_text), elite_text)
    if lex >= mine_paper_gap.JACCARD_DUP:
        return "lexical_jaccard", round(lex, 4)
    vecs = mine_paper_gap._embed_texts([cand_text, elite_text])
    cos = mine_paper_gap._cosine(vecs[0], vecs[1])
    if cos >= mine_paper_gap.TAU_DUP:
        return "cosine_tau_dup", round(cos, 4)
    return None, round(max(lex, cos), 4)


def accept_candidate(
    candidate: dict,
    cluster_state: dict,
    judge_fn: Callable[[str, str], dict] | None = None,
) -> dict[str, Any]:
    """MAP-Elites elite rule for one niche. Returns {"accepted": bool,
    "reason": str}.

    Ladder: (1) an empty niche accepts; (2) the imported mine_paper_gap
    prefilter (lexical Jaccard, then cosine) flags restatements of the
    incumbent elite; (3) when `judge_fn` is injected (idea_judge.judge_pair
    signature) its verdict is the top layer — "equivalent" rejects,
    "better_with_delta"/"distinct" accept; when None (default until
    calibration passes) the prefilter alone decides. A killed cluster admits
    a candidate ONLY via an articulated delta ("better_with_delta")."""
    cand_text = _claim_text(candidate)
    if not cand_text:
        raise ValueError("accept_candidate: candidate has no claim/text surface")

    killed = cluster_state.get("status") == "killed"
    elite = cluster_state.get("elite")

    if killed:
        if judge_fn is None:
            kr = cluster_state.get("kill_reason") or {}
            return {"accepted": False, "reason": (
                f"killed niche (code={kr.get('code')}): re-entry requires an "
                f"articulated delta and no judge is active (prefilter-only)"
            )}
        elite_text = _claim_text(elite) if elite else _claim_text(
            (cluster_state.get("kill_reason") or {}).get("detail", ""))
        verdict = _judged(judge_fn, cand_text, elite_text)
        if verdict == "better_with_delta":
            return {"accepted": True,
                    "reason": "killed niche re-entry: judge verdict better_with_delta (articulated delta)"}
        return {"accepted": False,
                "reason": f"killed niche re-entry refused: judge verdict {verdict} (no articulated delta)"}

    if elite is None:
        return {"accepted": True, "reason": "empty niche: no incumbent elite"}

    elite_text = _claim_text(elite)
    dup_layer, score = _prefilter_dup_layer(cand_text, elite_text)

    if judge_fn is None:
        if dup_layer is not None:
            return {"accepted": False,
                    "reason": f"prefilter duplicate of elite via {dup_layer} ({score})"}
        return {"accepted": True,
                "reason": f"prefilter distinct from elite (max signal {score})"}

    verdict = _judged(judge_fn, cand_text, elite_text)
    if verdict == "equivalent":
        return {"accepted": False,
                "reason": f"judge verdict equivalent to elite (prefilter layer: {dup_layer})"}
    if verdict == "better_with_delta":
        return {"accepted": True,
                "reason": f"judge verdict better_with_delta over elite (prefilter layer: {dup_layer})"}
    return {"accepted": True,
            "reason": f"judge verdict distinct from elite (prefilter layer: {dup_layer})"}


def _judged(judge_fn: Callable[[str, str], dict], a: str, b: str) -> str:
    """Call the injected judge; refuse an out-of-enum verdict (rule 4)."""
    out = judge_fn(a, b)
    verdict = out.get("verdict") if isinstance(out, dict) else None
    if verdict not in ("equivalent", "better_with_delta", "distinct"):
        raise ValueError(f"accept_candidate: judge returned invalid verdict {verdict!r}")
    return verdict
