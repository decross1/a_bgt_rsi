"""Freeze the re-adjudication manifest — the lock artifact of the D-076
follow-on battery.

Prereg: experiments/PREREG_readjudication_2026-08-19.md (v2, §3).

WHAT THIS WRITES
  bench/readjudication/manifest.jsonl
    line 1  : {"kind": "meta", ...} — counts, exclusions (by reason, with
              cluster ids), source shas, the contamination check, the
              inventory the prereg's Appendix B asserts.
    lines 2+: one row per judged claim, in the LOCKED run order.
  bench/readjudication/old_prompt.txt   (only with --freeze-old-prompt)
    the pre-swap redteam constant, recovered from git by AST extraction
    (prereg Appendix A) and sha-asserted.

READ-ONLY over the stores. It never writes memory/idea_ledger.jsonl,
memory/loop_memory.jsonl, or anything else outside bench/readjudication/.

DETERMINISM IS A REQUIREMENT, NOT A NICETY (this repo shipped a
hash-seed-dependent ordering bug on 2026-08-18):
  - the run order is ascending sha256(row_id.encode("utf-8")), tie-broken
    by row_id — never builtins.hash(), never set iteration order;
  - every collection that reaches the output is sorted explicitly;
  - input line order does not matter: clusters come from the reducer keyed
    by cluster_id, loop_memory is read into a dict keyed by iteration_id,
    fixtures are re-sorted by fixture id before ordering.
  Byte-identical output under PYTHONHASHSEED=0/1/random and under shuffled
  loop_memory / fixture input order is unit-tested
  (tests/test_readjudication.py).

Usage:
  .venv-chroma/bin/python -m bench.readjudication.build_manifest
  .venv-chroma/bin/python -m bench.readjudication.build_manifest --freeze-old-prompt
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent

DEFAULT_LEDGER = REPO_ROOT / "memory" / "idea_ledger.jsonl"
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_FIXTURES = REPO_ROOT / "bench" / "redteam_cal" / "fixtures.jsonl"
DEFAULT_OUT = HERE / "manifest.jsonl"
OLD_PROMPT_PATH = HERE / "old_prompt.txt"

PREREG = "experiments/PREREG_readjudication_2026-08-19.md"

# ── Prereg-pinned constants (§3.1). None of these resolve at run time. ──
KILL_CODE = "redteam_fatal_flaw"
REQUIRED_REOPENING_CONDITION = {
    "requires": "new_evidence",
    "evidence_kind": "redteam_proceed_on_revision",
}
REQUIRED_SUBAGENT_BACKEND = "vllm-gemma"
REQUIRED_SUBAGENT_MODEL = "gemma-4-26b-a4b"
# D-076 prompt swap instant. A target must have been judged strictly before
# it — "judged by the old instrument" is a CHECKED property of each row.
SWAP_INSTANT = datetime(2026, 8, 18, 6, 45, 0, tzinfo=timezone.utc)

# The pre-swap constant's provenance (prereg Appendix A). The commit is the
# D-076 swap; `^` is the revision immediately before it.
OLD_PROMPT_GIT_REV = "7780898^:workers/redteam_critic.py"
OLD_PROMPT_SYMBOL = "REDTEAM_AGENT_SYSTEM_PROMPT"
OLD_PROMPT_SHA256 = (
    "3433ac5d862d9e749f00455b0ed1d0b422b743c50202cb6fe45774c1445ae0bc"
)

# L9 lock-time assertion: a control row that is also (or nearly) a target
# row would make a known-bad LABEL and a reopen-eligibility CLAIM collide.
# Measured max cross-set token-Jaccard on 2026-08-19 was 0.29; 0.60 is the
# refusal threshold (the same threshold the intra-target near-duplicate
# scan reports at).
CONTAMINATION_JACCARD_MAX = 0.60

EXCLUSION_REASONS = (
    "reopen_kind_mismatch",
    "founding_evidence_mismatch",
    "historical_verdict_not_fatal",
    "historical_backend_mismatch",
    "judged_post_swap",
    "no_founding_hypothesis_text",
    "cluster_refined_since_kill",
)


# ---------------------------------------------------------------------------
# The claim-text join — REUSED, not invented (prereg §3.2)
# ---------------------------------------------------------------------------

def founding_iteration(cluster, cluster_id):
    """First iter-* member of the reduced cluster, else the id embedded in
    a 'cl-iter-…' cluster_id, else None.

    Verbatim rule from ui/backend/frontier_reviews.py::_founding_iteration —
    the battery does NOT invent a second join."""
    if isinstance(cluster, dict):
        for member in cluster.get("members") or []:
            if isinstance(member, str) and member.startswith("iter-"):
                return member
    if isinstance(cluster_id, str) and cluster_id.startswith("cl-iter-"):
        return cluster_id[3:]
    return None


def hypothesis_texts(path: Path) -> dict:
    """{iteration_id: FULL hypothesis text} from loop_memory.

    Same row lookup as ui/backend/frontier_reviews.py::_hypothesis_heads,
    with ONE deliberate departure stated in prereg §3.2: the UI truncates to
    a 140-char display head; a truncated claim is a DIFFERENT claim to the
    instrument, so this returns the full text, `.strip()`ed."""
    out: dict[str, str] = {}
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            iid = row.get("iteration_id")
            hyp = row.get("hypothesis")
            text = hyp.get("text") if isinstance(hyp, dict) else None
            if isinstance(iid, str) and isinstance(text, str) and text.strip():
                out[iid] = text.strip()
    return out


def loop_memory_rows(path: Path) -> dict:
    """{iteration_id: row} — last row wins (loop_memory is append-only and
    an iteration id appears once; the rule is stated so a duplicate cannot
    silently pick an arbitrary one)."""
    out: dict[str, dict] = {}
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            iid = row.get("iteration_id")
            if isinstance(iid, str):
                out[iid] = row
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def order_key(row_id: str) -> str:
    """The LOCKED run-order key: sha256 over the UTF-8 encoding of row_id.

    row_id is defined by the prereg (§4.2): the cluster_id for a target, the
    fixture id for a control, and `sidecar:<cluster_id>:<founding|refined>`
    for a sidecar row. Never builtins.hash() — that is per-process salted."""
    return hashlib.sha256(row_id.encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_ts(value):
    """Parse an ISO-8601 instant to an aware UTC datetime; None if absent
    or unparseable (the caller treats None as a failed check, never as a
    pass — inviolate rule 4)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _tokens(text: str) -> set:
    """Lowercased alphanumeric word tokens, for the Jaccard scans."""
    return {t for t in "".join(
        (c.lower() if c.isalnum() else " ") for c in text
    ).split() if t}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def parse_evidence_iteration(evidence_key):
    """'iteration:<iid>:redteam' -> '<iid>'; anything else -> None."""
    if not isinstance(evidence_key, str):
        return None
    parts = evidence_key.split(":")
    if len(parts) != 3 or parts[0] != "iteration" or parts[2] != "redteam":
        return None
    return parts[1] or None


# ---------------------------------------------------------------------------
# Target selection (prereg §3.1 + §3.3)
# ---------------------------------------------------------------------------

def select_targets(state: dict, lm_rows: dict) -> tuple[list, list]:
    """Apply §3.1's six criteria (+ §3.3's text criterion, + the L1
    `cluster_refined_since_kill` rule) to the reduced ledger state.

    Returns (target_rows, exclusions). Both are sorted by cluster_id here;
    the run order is applied later, once, over all row kinds.

    Every cluster whose kill code is `redteam_fatal_flaw` ends up in exactly
    one of the two lists — nothing is silently dropped (§3.3)."""
    targets: list[dict] = []
    exclusions: list[dict] = []

    def drop(cid, reason, detail=None):
        exclusions.append(
            {"cluster_id": cid, "reason": reason, "detail": detail}
        )

    for cid in sorted(state):
        cluster = state[cid]
        kill = cluster.get("kill_reason") or {}
        if kill.get("code") != KILL_CODE:  # criterion 1
            continue

        if (cluster.get("reopening_condition") or {}) != \
                REQUIRED_REOPENING_CONDITION:  # criterion 2
            drop(cid, "reopen_kind_mismatch",
                 json.dumps(cluster.get("reopening_condition"), sort_keys=True))
            continue

        founder = founding_iteration(cluster, cid)
        ev_iter = parse_evidence_iteration(kill.get("evidence_key"))
        if founder is None or ev_iter is None or ev_iter != founder:
            # criterion 3 — the ledger's own record of WHICH iteration's
            # verdict caused the kill must agree with the join we use to
            # fetch the text.
            drop(cid, "founding_evidence_mismatch",
                 f"evidence_key={kill.get('evidence_key')!r} founding={founder!r}")
            continue

        row = lm_rows.get(founder)
        redteam = (row or {}).get("redteam") or {}
        if redteam.get("verdict") != "fatal_flaw":  # criterion 4
            drop(cid, "historical_verdict_not_fatal",
                 f"verdict={redteam.get('verdict')!r}")
            continue

        if (redteam.get("subagent_backend") != REQUIRED_SUBAGENT_BACKEND
                or redteam.get("subagent_model") != REQUIRED_SUBAGENT_MODEL):
            drop(cid, "historical_backend_mismatch",  # criterion 5
                 f"{redteam.get('subagent_backend')!r}/"
                 f"{redteam.get('subagent_model')!r}")
            continue

        ended = _parse_ts(row.get("ended_at"))
        if ended is None or ended >= SWAP_INSTANT:  # criterion 6
            drop(cid, "judged_post_swap", f"ended_at={row.get('ended_at')!r}")
            continue

        hyp = (row.get("hypothesis") or {}).get("text")
        text = hyp.strip() if isinstance(hyp, str) else ""
        if not text:  # §3.3
            drop(cid, "no_founding_hypothesis_text", None)
            continue

        if cluster.get("refined_claim"):
            # L1: the reduced cluster's LIVE claim is the refined one
            # (ui/backend/frontier_reviews.py::_claim_head_of prefers it), so
            # a proceed on the superseded founding text would be recorded as
            # reopening evidence for a cluster whose current claim is a
            # different claim. Excluded from the target set; both texts still
            # ride as EXPLORATORY sidecar rows (see build()).
            drop(cid, "cluster_refined_since_kill",
                 f"refine_rounds={len(cluster.get('refine_history') or [])}")
            continue

        targets.append({
            "row_id": cid,
            "kind": "target",
            "claim_text": text,
            "claim_sha256": sha256_text(text),
            "cluster_id": cid,
            "founding_iteration": founder,
            "evidence_key": kill.get("evidence_key"),
            "cluster_member_count": len(cluster.get("members") or []),
            "evidence_level": cluster.get("evidence_level"),
            "historical_verdict": redteam.get("verdict"),
            "historical_confidence": redteam.get("confidence"),
            "historical_retries_used": redteam.get("retries_used"),
            "historical_subagent_status": redteam.get("subagent_status"),
            "historical_subagent_backend": redteam.get("subagent_backend"),
            "historical_subagent_model": redteam.get("subagent_model"),
            "historical_model_version": row.get("model_version"),
            "founding_ended_at": row.get("ended_at"),
            "era": ended.strftime("%Y-%m"),
        })

    exclusions.sort(key=lambda e: (e["reason"], e["cluster_id"]))
    return targets, exclusions


def build_sidecars(state: dict, lm_rows: dict, exclusions: list) -> list:
    """EXPLORATORY rows for every cluster excluded as
    `cluster_refined_since_kill`: its founding text AND its live refined
    claim, judged by both arms, reported in the artifact's `exploratory`
    block and entering NO bar, NO statistic, and NOT the reopen set R.

    Pre-stated in the prereg (§3.3 / L1) so the rule is fixed before the
    number is known — it is 1 cluster today."""
    out: list[dict] = []
    for exc in exclusions:
        if exc["reason"] != "cluster_refined_since_kill":
            continue
        cid = exc["cluster_id"]
        cluster = state[cid]
        founder = founding_iteration(cluster, cid)
        founding_text = ((lm_rows.get(founder) or {}).get("hypothesis")
                         or {}).get("text")
        refined_text = cluster.get("refined_claim")
        for variant, text in (("founding", founding_text),
                              ("refined", refined_text)):
            if not isinstance(text, str) or not text.strip():
                continue
            text = text.strip()
            out.append({
                "row_id": f"sidecar:{cid}:{variant}",
                "kind": "sidecar",
                "claim_text": text,
                "claim_sha256": sha256_text(text),
                "cluster_id": cid,
                "variant": variant,
                "founding_iteration": founder,
            })
    out.sort(key=lambda r: r["row_id"])
    return out


def load_controls(path: Path) -> list:
    """The COMPLETE 24-row R1a frozen manifest, spiked whole (§4.1)."""
    rows: list[dict] = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            fx = json.loads(line)
            text = (fx.get("hypothesis_text") or "").strip()
            rows.append({
                "row_id": fx["id"],
                "kind": "control",
                "claim_text": text,
                "claim_sha256": sha256_text(text),
                "fixture_id": fx["id"],
                "label": fx["label"],
                "provenance_class": (fx.get("provenance") or {}).get("class"),
            })
    rows.sort(key=lambda r: r["row_id"])
    return rows


# ---------------------------------------------------------------------------
# Contamination + near-duplicate scans
# ---------------------------------------------------------------------------

def contamination_scan(targets: list, controls: list) -> dict:
    """L9 lock-time assertion: no control row may also be a target row.

    Checks id collision, exact claim-text identity, and the maximum token
    Jaccard across the two sets. A collision would make a known-bad LABEL
    and a reopen-eligibility CLAIM refer to the same claim."""
    target_ids = {r["cluster_id"] for r in targets} | \
                 {r["founding_iteration"] for r in targets}
    id_collisions = sorted(
        c["row_id"] for c in controls if c["row_id"] in target_ids
    )
    by_sha = {}
    for t in targets:
        by_sha.setdefault(t["claim_sha256"], []).append(t["cluster_id"])
    exact = sorted(
        f"{c['row_id']}~{by_sha[c['claim_sha256']][0]}"
        for c in controls if c["claim_sha256"] in by_sha
    )
    t_tokens = [(t["cluster_id"], _tokens(t["claim_text"])) for t in targets]
    worst = {"jaccard": 0.0, "control": None, "target": None}
    for c in controls:
        ct = _tokens(c["claim_text"])
        for cid, tt in t_tokens:
            j = _jaccard(ct, tt)
            if j > worst["jaccard"]:
                worst = {"jaccard": round(j, 4), "control": c["row_id"],
                         "target": cid}
    return {
        "id_collisions": id_collisions,
        "exact_text_collisions": exact,
        "max_cross_set_jaccard": worst,
        "threshold": CONTAMINATION_JACCARD_MAX,
        "clean": bool(
            not id_collisions and not exact
            and worst["jaccard"] < CONTAMINATION_JACCARD_MAX
        ),
    }


def duplicate_scan(targets: list) -> dict:
    """Intra-target duplicate / near-duplicate report (Appendix B). Reported,
    not a refusal: a duplicate pair would let ONE judgment consume two
    slots, and the report must be able to say it did not happen."""
    by_sha: dict[str, list] = {}
    for t in targets:
        by_sha.setdefault(t["claim_sha256"], []).append(t["cluster_id"])
    exact = sorted(v for v in by_sha.values() if len(v) > 1)
    toks = [(t["cluster_id"], _tokens(t["claim_text"])) for t in targets]
    worst = {"jaccard": 0.0, "pair": None}
    near = 0
    for i in range(len(toks)):
        for k in range(i + 1, len(toks)):
            j = _jaccard(toks[i][1], toks[k][1])
            if j >= CONTAMINATION_JACCARD_MAX:
                near += 1
            if j > worst["jaccard"]:
                worst = {"jaccard": round(j, 4),
                         "pair": [toks[i][0], toks[k][0]]}
    return {
        "exact_duplicate_groups": exact,
        "near_duplicate_pairs_at_0.60": near,
        "max_pairwise_jaccard": worst,
    }


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def build(ledger_path: Path = DEFAULT_LEDGER,
          loop_memory_path: Path = DEFAULT_LOOP_MEMORY,
          fixtures_path: Path = DEFAULT_FIXTURES) -> tuple[dict, list]:
    """Return (meta, rows). Pure with respect to the filesystem outputs."""
    sys.path.insert(0, str(REPO_ROOT))
    from workers.idea_ledger import load_state  # lazy: repo import

    state = load_state(ledger_path)
    lm_rows = loop_memory_rows(loop_memory_path)

    targets, exclusions = select_targets(state, lm_rows)
    sidecars = build_sidecars(state, lm_rows, exclusions)
    controls = load_controls(fixtures_path)

    rows = targets + controls + sidecars
    # THE LOCKED RUN ORDER — one deterministic pass over every kind, so a
    # control is temporally indistinguishable from a target inside the arm's
    # own window (§4.2). sha256 of the UTF-8 row_id, tie-broken by row_id.
    for r in rows:
        r["order_key"] = order_key(r["row_id"])
    rows.sort(key=lambda r: (r["order_key"], r["row_id"]))

    kills = sum(
        1 for c in state.values()
        if (c.get("kill_reason") or {}).get("code") == KILL_CODE
    )
    n_killed = sum(1 for c in state.values() if c.get("kill_reason"))
    contamination = contamination_scan(targets, controls)
    n_good = sum(1 for c in controls if c["label"] == "known_good")
    n_bad = sum(1 for c in controls if c["label"] == "known_bad")

    era: dict[str, int] = {}
    sizes: dict[str, int] = {}
    for t in targets:
        era[t["era"]] = era.get(t["era"], 0) + 1
        sizes[str(t["cluster_member_count"])] = \
            sizes.get(str(t["cluster_member_count"]), 0) + 1

    meta = {
        "kind": "meta",
        "prereg": PREREG,
        # NO build timestamp, deliberately: the manifest is a PURE function
        # of its inputs, so a rebuild from the same stores is byte-identical
        # and the pinned sha256 is checkable by anyone. The lock commit's
        # timestamp is the build time of record.
        "ledger_path": str(ledger_path.relative_to(REPO_ROOT))
        if ledger_path.is_relative_to(REPO_ROOT) else str(ledger_path),
        "ledger_sha256": sha256_file(ledger_path),
        "loop_memory_sha256": sha256_file(loop_memory_path),
        "fixtures_path": str(fixtures_path.relative_to(REPO_ROOT))
        if fixtures_path.is_relative_to(REPO_ROOT) else str(fixtures_path),
        "fixtures_sha256": sha256_file(fixtures_path),
        "clusters_in_ledger": len(state),
        "clusters_killed": n_killed,
        "clusters_open": len(state) - n_killed,
        "kill_code": KILL_CODE,
        "qualifying_by_kill_code": kills,
        "n_targets": len(targets),
        "n_controls": len(controls),
        "n_controls_known_good": n_good,
        "n_controls_known_bad": n_bad,
        "n_sidecars": len(sidecars),
        "n_rows": len(rows),
        "n_excluded": len(exclusions),
        "exclusions_by_reason": {
            reason: sum(1 for e in exclusions if e["reason"] == reason)
            for reason in EXCLUSION_REASONS
        },
        "exclusions": exclusions,
        "target_era": dict(sorted(era.items())),
        "target_cluster_size": dict(sorted(sizes.items())),
        "contamination_scan": contamination,
        "duplicate_scan": duplicate_scan(targets),
        "swap_instant": SWAP_INSTANT.isoformat(),
        "order_rule": (
            "ascending sha256(row_id UTF-8), tie-broken by row_id; row_id is "
            "the cluster_id for a target, the fixture id for a control, and "
            "sidecar:<cluster_id>:<variant> for a sidecar"
        ),
    }
    return meta, rows


def write_manifest(meta: dict, rows: list, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        fh.write(json.dumps(meta, sort_keys=True) + "\n")
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def load_manifest(path: Path) -> tuple[dict, list]:
    """Read back a frozen manifest. Refuses a file whose first line is not
    the meta record (a manifest without its provenance is not a manifest)."""
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{path}: empty manifest")
    meta = json.loads(lines[0])
    if meta.get("kind") != "meta":
        raise ValueError(f"{path}: first line is not the meta record")
    rows = [json.loads(ln) for ln in lines[1:]]
    return meta, rows


# ---------------------------------------------------------------------------
# The pre-swap prompt (prereg Appendix A)
# ---------------------------------------------------------------------------

def extract_old_prompt(rev: str = OLD_PROMPT_GIT_REV) -> str:
    """Recover the pre-swap REDTEAM_AGENT_SYSTEM_PROMPT from git by AST
    extraction (prereg Appendix A step 2).

    AST + literal_eval, NOT regex: the constant is a parenthesised implicit
    concatenation of 31 quoted fragments, which a naive triple-quote pattern
    does not match at all — it would fail OPEN. NOT import/exec: that would
    pull in the pre-swap dependency graph."""
    src = subprocess.run(
        ["git", "show", rev], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == OLD_PROMPT_SYMBOL:
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(
                            f"{OLD_PROMPT_SYMBOL} at {rev} is not a non-empty str"
                        )
                    return value
    raise ValueError(f"{OLD_PROMPT_SYMBOL} not found at {rev}")


def freeze_old_prompt(out_path: Path = OLD_PROMPT_PATH) -> str:
    """Write the recovered constant to old_prompt.txt with ONE trailing
    newline (the loader strips it — the production constant carries none),
    asserting the pinned sha256 over the UTF-8 encoding FIRST."""
    text = extract_old_prompt()
    got = sha256_text(text)
    if got != OLD_PROMPT_SHA256:
        raise ValueError(
            f"old prompt sha256 {got} != pinned {OLD_PROMPT_SHA256} — the "
            "frozen instrument is not the instrument D-076 measured; REFUSING"
        )
    out_path.write_text(text + "\n")
    return got


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--loop-memory", default=str(DEFAULT_LOOP_MEMORY))
    ap.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--freeze-old-prompt", action="store_true",
                    help="also recover + sha-assert bench/readjudication/"
                         "old_prompt.txt from git (prereg Appendix A)")
    args = ap.parse_args(argv)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path

    meta, rows = build(
        Path(args.ledger), Path(args.loop_memory), Path(args.fixtures)
    )
    scan = meta["contamination_scan"]
    if not scan["clean"]:
        print(
            "REFUSING (exit 4): target/control contamination — "
            f"id_collisions={scan['id_collisions']} "
            f"exact={scan['exact_text_collisions']} "
            f"max_jaccard={scan['max_cross_set_jaccard']}",
            file=sys.stderr,
        )
        return 4

    write_manifest(meta, rows, out_path)
    print(f"manifest -> {out_path}")
    print(f"  sha256                {sha256_file(out_path)}")
    print(f"  ledger sha256         {meta['ledger_sha256']}")
    print(f"  qualifying by kill    {meta['qualifying_by_kill_code']}")
    print(f"  targets               {meta['n_targets']}")
    print(f"  controls              {meta['n_controls']} "
          f"({meta['n_controls_known_good']} good / "
          f"{meta['n_controls_known_bad']} bad)")
    print(f"  sidecars (EXPLORATORY){meta['n_sidecars']:>3}")
    print(f"  rows                  {meta['n_rows']}")
    print(f"  excluded              {meta['n_excluded']}")
    for reason, n in meta["exclusions_by_reason"].items():
        if n:
            ids = sorted(e["cluster_id"] for e in meta["exclusions"]
                         if e["reason"] == reason)
            print(f"    {reason}: {n} -> {', '.join(ids)}")
    print(f"  contamination clean   {scan['clean']} "
          f"(max cross-set jaccard {scan['max_cross_set_jaccard']['jaccard']})")
    print(f"  dup scan              {meta['duplicate_scan']}")

    if args.freeze_old_prompt:
        got = freeze_old_prompt()
        print(f"old_prompt.txt -> {OLD_PROMPT_PATH}\n  sha256 {got} (ASSERTED)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
