"""Deterministic fixture-manifest builder — D1 critic calibration battery.

Prereg: experiments/PREREG_critic_cal_2026-08-19.md (v2), sections 4-6.

ZERO model calls, ZERO retrieval calls, ZERO embedding calls. Every
fixture is a REAL historical (claim, pack) pair drawn from
memory/loop_memory.jsonl and run_state/iteration_cache/, replayed
verbatim. That is a v2 rescoping, not a convenience: a builder that
constructs fresh packs must run live BGE-M3 + Chroma against a corpus
the arxiv cron mutates continuously, so its manifest can never be
rebuilt byte-identically. History-only makes the manifest genuinely
reproducible AND makes every pack one production actually assembled for
that exact claim — which the "hand-planted neighbor" and "query
substitution" objections both rule out for constructed fixtures.

THREE STRATA (26 fixtures, 26 calls per arm):

  S1  H1-POPULATION — CENSUS, n=10, not a sample.
      Every row in the whole record whose critic verdict is NATIVE
      undecidable on an ADEQUATE pack. This is the entire population
      hypothesis H1 is about. The other 49 undecidables are either the
      critic obeying the RETRIEVAL RELEVANCE WARNING printed in its own
      prompt (19) or an override applied after the critic already said
      'survives' (30) — neither is a calibration question.

  S2  DECISIVE-ADEQUATE CONTROL — n=8, blind within class.
      Rows where the critic reached a DECISIVE native verdict on an
      adequate pack. Quota 4 survives / 2 restated / 2 falsified so the
      two rare classes are represented; within each class the pick is
      sha256(iteration_id) ascending, which is blind to content.

  S3  FLAGGED-PACK CONTROL — n=8, blind.
      Rows whose recorded relevance is category 'off_domain' with
      low_confidence true, so the replay carries the RETRIEVAL RELEVANCE
      WARNING exactly as production did. Historically the sub-agent's
      RAW verdict on these packs is undecidable only 19/36 of the time,
      so this is not a bar the instrument clears by construction.

RELEVANCE, and why it is REPLAYED rather than recomputed
--------------------------------------------------------
workers.retrieval_relevance.relevance() is a pure function (no embed, no
LLM), so recomputing it costs nothing. This builder therefore does BOTH
and records both. It replays the RECORDED block because that is the
block that shaped the production prompt, and it records the fresh
recomputation as a diagnostic — because they DISAGREE, materially:

  * recomputing with topicality=None (the only option without an LLM
    call) reclassifies 35 of the 36 recorded off_domain rows to 'ok',
    since 35 of them fired rule R0, the LLM topicality judge;
  * recomputing with the RECORDED topicality/anchor arguments still
    diverges on 20 of 119 relevance-bearing rows, because D-075 R2
    (2026-08-18) demoted R0 for hypotheses matching a curated
    DOMAIN_ANCHOR_PHRASES entry, and most of the record predates it.

So "compute the relevance block per fixture" would have silently
deleted the entire flagged-pack stratum. The divergence is reported per
fixture (`relevance_recompute_agrees`) and in the build meta.

Determinism: rebuilding from the source stores yields a byte-identical
manifest.jsonl (sorted keys, ascii-escaped, fixed row order). Any
mismatch between a fresh resolution and an existing manifest REFUSES
loudly (ResolutionError / exit 1) — inviolate rule 4, never coerced.
An ERA BOUND pins the resolution against a growing ledger.

Exclusions are NEVER silent: every candidate rejected from every pool is
recorded with its reason and id, and the counts by reason ride in the
manifest's build meta.

Usage:
    python -m bench.critic_cal.build_manifest             # write
    python -m bench.critic_cal.build_manifest --check     # verify only
    python -m bench.critic_cal.build_manifest --force     # overwrite
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOOP_MEMORY_PATH = REPO_ROOT / "memory" / "loop_memory.jsonl"
CACHE_ROOT = REPO_ROOT / "run_state" / "iteration_cache"
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.jsonl"
META_PATH = Path(__file__).resolve().parent / "manifest_meta.json"

PREREG = "experiments/PREREG_critic_cal_2026-08-19.md"

# ERA BOUND — the manifest is a FROZEN artifact resolved against the
# record as it stood at lock. The loop is always-on (D-063 hourly cron),
# so an unbounded rule re-resolves to a growing set and the builder would
# refuse forever. Bounding restores reproducibility WITHOUT touching the
# manifest; the era end is stated, not implied.
ERA_END = "2026-08-19T06:00:00Z"

DECISIVE_VERDICTS = ("survives", "restated", "falsified", "refuted")

# Locked stratum sizes and quotas.
S1_EXPECTED_N = 10           # CENSUS — a different count is drift, not a sample
S2_QUOTA = (("survives", 4), ("restated", 2), ("falsified", 2))
S3_N = 8
TOTAL_N = S1_EXPECTED_N + sum(n for _, n in S2_QUOTA) + S3_N  # 26

# The synthetic iteration_id namespace the driver seeds into the shared
# iteration cache. Deliberately NOT prefixed "iter-" so it cannot be
# picked up by experiments/lit_falsification_battery/calibrate_anchor.py,
# which globs CACHE_ROOT for "iter-*", nor joined by
# ui/backend/iteration_journey.py, which keys on real iteration_ids.
CACHE_NAMESPACE = "critcal-"

# The critic truncates every neighbor's chunk_text to 600 chars in the
# prompt (workers/critic_loop_v0.py:199-201). Historical replay inherits
# that verbatim, so it is a recorded fidelity FACT, not a hazard here.
CHUNK_PROMPT_WINDOW = 600


class ResolutionError(RuntimeError):
    """A resolution rule did not yield what the prereg pinned. Refuse."""


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _canon_sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def order_key(fixture_id: str) -> str:
    return hashlib.sha256(fixture_id.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Row predicates (pure)
# ---------------------------------------------------------------------------

def _critique(row: dict) -> dict:
    c = row.get("critique")
    return c if isinstance(c, dict) else {}


def _recorded_relevance(row: dict) -> dict | None:
    ret = row.get("retrieval")
    if not isinstance(ret, dict):
        return None
    rel = ret.get("relevance")
    return rel if isinstance(rel, dict) else None


def is_native(row: dict) -> bool:
    return "verdict_overridden_from" not in _critique(row)


def pack_is_adequate(row: dict) -> bool:
    """No RETRIEVAL RELEVANCE WARNING was in the prompt for this call."""
    rel = _recorded_relevance(row)
    if rel is None:
        return isinstance(row.get("retrieval"), dict)
    if rel.get("low_confidence"):
        return False
    cat = rel.get("category")
    return cat is None or cat == "ok"


def pack_is_flagged(row: dict) -> bool:
    rel = _recorded_relevance(row)
    return bool(rel) and rel.get("category") == "off_domain" and bool(
        rel.get("low_confidence")
    )


# ---------------------------------------------------------------------------
# Usability gate — every exclusion happens HERE, at build time, before any
# call is made. A status != "passed" return at RUN time is a driver defect
# tripping run-validity bar V1, never a finding.
# ---------------------------------------------------------------------------

def usability(row: dict) -> str | None:
    """None when usable; otherwise the exclusion reason string."""
    iid = row.get("iteration_id")
    if not isinstance(iid, str) or not iid:
        return "no iteration_id"
    if (row.get("started_at") or "") >= ERA_END:
        return f"outside era bound (started_at >= {ERA_END})"
    if not _critique(row):
        return "no critique block"
    if _critique(row).get("subagent_status") != "passed":
        return (
            f"critic subagent_status={_critique(row).get('subagent_status')!r} "
            "(not 'passed')"
        )
    hyp = (row.get("hypothesis") or {}).get("text")
    if not isinstance(hyp, str) or not hyp.strip():
        return "empty hypothesis.text"
    cache_file = CACHE_ROOT / iid / "retrieval.json"
    if not cache_file.exists():
        return "no run_state/iteration_cache/<id>/retrieval.json"
    try:
        env = json.loads(cache_file.read_text())
    except Exception as exc:
        return f"cache retrieval.json unreadable: {type(exc).__name__}"
    if not isinstance(env, dict) or "result" not in env:
        return "cache retrieval.json is not a worker envelope (no 'result')"
    neighbors = (env.get("result") or {}).get("neighbors")
    if not isinstance(neighbors, list) or not neighbors:
        return "cache retrieval.result.neighbors empty or not a list"
    # The critic reads retrieval['result']['neighbors'] from the CACHE; the
    # loop_memory copy is FLATTENED (no 'result' wrapper). Assert the two
    # agree before emitting, so a fixture can never be replayed against a
    # pack different from the one the recorded verdict was formed on.
    mem_ret = row.get("retrieval") or {}
    if _canon_sha(neighbors) != _canon_sha(mem_ret.get("neighbors")):
        return "cache/loop_memory neighbors sha256 mismatch"
    if _canon_sha((env.get("result") or {}).get("relevance")) != _canon_sha(
        mem_ret.get("relevance")
    ):
        return "cache/loop_memory relevance sha256 mismatch"
    return None


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------

def _read_envelope(iid: str, key: str) -> dict | None:
    path = CACHE_ROOT / iid / f"{key}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _recompute_relevance(neighbors: list[dict], hyp: str, rel: dict | None) -> dict:
    """The pure-function recomputation, as a DIAGNOSTIC. The arguments the
    caller can supply without a model call are stated explicitly: the
    recorded anchor_cosine and the recorded topicality verdict. Both are
    None on legacy rows, which reduces relevance() exactly to its legacy
    ladder (R1..R5) with R0/R0b unable to fire."""
    from workers.retrieval_relevance import relevance

    anchor = (rel or {}).get("anchor_cosine")
    topicality = (rel or {}).get("topicality")
    fresh = relevance(
        neighbors, hyp, anchor_cosine=anchor, topicality=topicality
    )
    return {
        "args": {"anchor_cosine": anchor, "topicality": topicality},
        "result": fresh,
    }


def make_fixture(row: dict, stratum: str, label_rationale: str) -> dict:
    iid = row["iteration_id"]
    crit = _critique(row)
    env = _read_envelope(iid, "retrieval")
    nov_env = _read_envelope(iid, "novelty")
    neighbors = env["result"]["neighbors"]
    rel = (env.get("result") or {}).get("relevance")
    hyp = row["hypothesis"]["text"]
    fixture_id = f"{stratum}-{iid}"
    recomputed = _recompute_relevance(neighbors, hyp, rel)
    nov_class = ((nov_env or {}).get("result") or {}).get("class")
    return {
        "fixture_id": fixture_id,
        "iteration_id": iid,
        "stratum": stratum,
        "order_key": order_key(fixture_id),
        "cache_iteration_id": CACHE_NAMESPACE + fixture_id,
        "era": (row.get("started_at") or "")[:7],
        "started_at": row.get("started_at"),
        "hypothesis_text": hyp,
        "hypothesis_word_count": len(hyp.split()),
        # What the record says happened — the replay comparator, NOT a label.
        "recorded": {
            "verdict_final": crit.get("verdict"),
            "verdict_raw": crit.get("verdict_overridden_from") or crit.get("verdict"),
            "override_reason": crit.get("override_reason"),
            "subagent_status": crit.get("subagent_status"),
            "subagent_turns_used": crit.get("subagent_turns_used"),
            "subagent_wall_seconds": crit.get("subagent_wall_seconds"),
            "subagent_backend": crit.get("subagent_backend"),
            "subagent_model": crit.get("subagent_model"),
            "contradicting_paper_id": crit.get("contradicting_paper_id"),
            "novelty_class": (row.get("novelty") or {}).get("class"),
            "redteam_verdict": (row.get("redteam") or {}).get("verdict"),
        },
        # Replayed VERBATIM — the complete worker envelope the critic reads.
        "retrieval_envelope": env,
        "novelty_envelope": nov_env,
        "pack": {
            "n_neighbors": len(neighbors),
            "neighbor_doc_ids": [n.get("doc_id") for n in neighbors],
            "pack_sha256": _canon_sha(neighbors),
            "envelope_sha256": _canon_sha(env),
            "n_chunks_over_prompt_window": sum(
                1 for n in neighbors
                if len((n.get("chunk_text") or "")) > CHUNK_PROMPT_WINDOW
            ),
            "prompt_window_chars": CHUNK_PROMPT_WINDOW,
        },
        "relevance_recorded": rel,
        "relevance_recomputed": recomputed,
        "relevance_recompute_agrees": bool(
            rel is not None
            and recomputed["result"].get("category") == rel.get("category")
            and bool(recomputed["result"].get("low_confidence"))
            == bool(rel.get("low_confidence"))
        ),
        # Exactly which prompt blocks this replay will carry — derived from
        # the REPLAYED envelope, so it is checkable without running anything.
        "prompt_shape": {
            "relevance_warning_fires": bool((rel or {}).get("low_confidence")),
            "novelty_context_fires": nov_class == "rediscovery",
            "novelty_class_in_cache": nov_class,
            "coverage_override_would_fire_on_survives": bool(
                (rel or {}).get("low_confidence")
                or ((rel or {}).get("category") not in (None, "ok"))
            ),
        },
        "label_rationale": label_rationale,
    }


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

S1_RATIONALE = (
    "H1 POPULATION CENSUS. The primary critic NATIVELY returned "
    "'undecidable' here, on a pack the apparatus did NOT flag, so no "
    "RETRIEVAL RELEVANCE WARNING was in its prompt and no override "
    "touched the verdict. This is the entire population H1 is about. "
    "The fixture carries NO label: the battery measures whether the "
    "recorded verdict REPRODUCES, not whether it was correct — no "
    "non-circular correctness label exists for this row."
)
S2_RATIONALE = (
    "DECISIVE-ADEQUATE CONTROL. The critic reached a decisive native "
    "verdict ({verdict!r}) on an unflagged pack. Replaying it detects a "
    "condemner: an instrument that turns a previously decided claim into "
    "'undecidable'. The recorded verdict is a SELF-CONSISTENCY "
    "comparator, not ground truth — it is the same instrument's earlier "
    "output."
)
S3_RATIONALE = (
    "FLAGGED-PACK CONTROL. Recorded relevance is category 'off_domain' "
    "with low_confidence true, so the replay carries the RETRIEVAL "
    "RELEVANCE WARNING verbatim, exactly as production did. Scored on "
    "verdict_raw, because the coverage override fires unconditionally "
    "after the sub-agent speaks. NOT pre-ordained: across all 36 such "
    "rows the sub-agent's RAW verdict is 'undecidable' on only 19."
)


def _pick(pool: list[dict], n: int) -> list[dict]:
    """Blind deterministic pick: sha256(iteration_id) ascending."""
    ranked = sorted(pool, key=lambda r: (hashlib.sha256(
        r["iteration_id"].encode()).hexdigest(), r["iteration_id"]))
    return ranked[:n]


def resolve(loop_memory: list[dict]) -> tuple[list[dict], dict]:
    """Returns (fixtures, build_meta). Refuses loudly on any drift."""
    exclusions: list[dict] = []
    usable: list[dict] = []
    for row in loop_memory:
        reason = usability(row)
        if reason is None:
            usable.append(row)
        else:
            exclusions.append({
                "iteration_id": row.get("iteration_id"),
                "reason": reason,
            })

    s1_pool = [
        r for r in usable
        if _critique(r).get("verdict") == "undecidable"
        and is_native(r) and pack_is_adequate(r)
    ]
    s2_pool = [
        r for r in usable
        if _critique(r).get("verdict") in DECISIVE_VERDICTS
        and is_native(r) and pack_is_adequate(r)
    ]
    s3_pool = [r for r in usable if pack_is_flagged(r)]

    if len(s1_pool) != S1_EXPECTED_N:
        raise ResolutionError(
            f"S1 is a CENSUS pinned at {S1_EXPECTED_N} rows and resolved to "
            f"{len(s1_pool)} ({sorted(r['iteration_id'] for r in s1_pool)}). "
            "Either the era bound is stale or the population moved — inspect "
            "and re-lock; never silently re-sample."
        )

    fixtures = [make_fixture(r, "S1", S1_RATIONALE) for r in s1_pool]

    s2_selected: list[dict] = []
    s2_quota_report = []
    for verdict, quota in S2_QUOTA:
        cand = [r for r in s2_pool if _critique(r).get("verdict") == verdict]
        if len(cand) < quota:
            raise ResolutionError(
                f"S2 quota for {verdict!r} is {quota} but only {len(cand)} "
                "adequate-pack native rows exist"
            )
        chosen = _pick(cand, quota)
        s2_quota_report.append({
            "verdict": verdict, "quota": quota, "pool_n": len(cand),
            "chosen": sorted(r["iteration_id"] for r in chosen),
        })
        for r in chosen:
            s2_selected.append(r)
            fixtures.append(make_fixture(
                r, "S2", S2_RATIONALE.format(verdict=verdict)
            ))
        for r in cand:
            if r not in chosen:
                exclusions.append({
                    "iteration_id": r["iteration_id"],
                    "reason": f"S2 {verdict} pool: not in the first {quota} by "
                              "sha256(iteration_id)",
                })

    if len(s3_pool) < S3_N:
        raise ResolutionError(
            f"S3 needs {S3_N} flagged-pack rows, pool has {len(s3_pool)}"
        )
    s3_selected = _pick(s3_pool, S3_N)
    for r in s3_pool:
        if r not in s3_selected:
            exclusions.append({
                "iteration_id": r["iteration_id"],
                "reason": f"S3 pool: not in the first {S3_N} by "
                          "sha256(iteration_id)",
            })
    for r in s3_selected:
        fixtures.append(make_fixture(r, "S3", S3_RATIONALE))

    fixtures.sort(key=lambda f: (f["stratum"], f["order_key"], f["fixture_id"]))
    _self_check(fixtures)

    by_reason: dict[str, list[str]] = {}
    for e in exclusions:
        by_reason.setdefault(e["reason"], []).append(str(e["iteration_id"]))
    meta = {
        "prereg": PREREG,
        "era_end": ERA_END,
        "model_calls_made": 0,
        "retrieval_calls_made": 0,
        "loop_memory_sha256": hashlib.sha256(
            LOOP_MEMORY_PATH.read_bytes()).hexdigest(),
        "loop_memory_rows": len(loop_memory),
        "n_usable": len(usable),
        "cache_namespace": CACHE_NAMESPACE,
        "strata": {
            "S1": {"n": S1_EXPECTED_N, "pool_n": len(s1_pool), "rule": "CENSUS"},
            "S2": {"n": sum(n for _, n in S2_QUOTA), "pool_n": len(s2_pool),
                   "rule": "quota by recorded verdict, sha256 blind within class",
                   "quotas": s2_quota_report},
            "S3": {"n": S3_N, "pool_n": len(s3_pool),
                   "rule": "sha256(iteration_id) ascending, blind"},
        },
        "exclusions_by_reason": [
            {"reason": k, "n": len(v), "iteration_ids": sorted(v)}
            for k, v in sorted(by_reason.items())
        ],
        "n_exclusions_total": len(exclusions),
        "relevance_recompute_divergence": {
            "n_fixtures_diverging": sum(
                1 for f in fixtures if not f["relevance_recompute_agrees"]
            ),
            "diverging_fixture_ids": sorted(
                f["fixture_id"] for f in fixtures
                if not f["relevance_recompute_agrees"]
            ),
            "note": (
                "relevance() is pure and free to recompute, but it is NOT "
                "stable across the record: D-075 R2 (2026-08-18) demoted the "
                "R0 topicality gate for curated-phrase hypotheses, and R0 "
                "itself needs an LLM verdict that only the recorded block "
                "carries. The RECORDED block is replayed; the recomputation "
                "rides as a diagnostic."
            ),
        },
        # Frozen per-bar denominators. Stated as explicit id sets so a
        # denominator can never be re-read as 8-or-6 after the numbers land.
        "bar_denominators": {
            "V1": sorted(f["fixture_id"] for f in fixtures),
            "C1": sorted(f["fixture_id"] for f in fixtures if f["stratum"] == "S3"),
            "C2": sorted(f["fixture_id"] for f in fixtures if f["stratum"] == "S2"),
            "E1": sorted(f["fixture_id"] for f in fixtures if f["stratum"] == "S1"),
            "E2": sorted(f["fixture_id"] for f in fixtures if f["stratum"] == "S2"),
        },
    }
    return fixtures, meta


def _self_check(fixtures: list[dict]) -> None:
    """Build-time integrity gates. Each stands alone (inviolate rule 4);
    a violation refuses the build rather than emitting a bad manifest."""
    if len(fixtures) != TOTAL_N:
        raise ResolutionError(f"manifest has {len(fixtures)} rows, expected {TOTAL_N}")
    ids = [f["fixture_id"] for f in fixtures]
    if len(set(ids)) != len(ids):
        raise ResolutionError("duplicate fixture_id in manifest")
    iids = [f["iteration_id"] for f in fixtures]
    if len(set(iids)) != len(iids):
        raise ResolutionError(
            "an iteration_id appears in two strata — one judgment cannot "
            "consume two fixture slots"
        )
    counts = {s: sum(1 for f in fixtures if f["stratum"] == s) for s in ("S1", "S2", "S3")}
    expected = {"S1": S1_EXPECTED_N, "S2": sum(n for _, n in S2_QUOTA), "S3": S3_N}
    if counts != expected:
        raise ResolutionError(f"stratum split {counts}, expected {expected}")
    for f in fixtures:
        if not f["retrieval_envelope"].get("result", {}).get("neighbors"):
            raise ResolutionError(f"{f['fixture_id']}: empty replayed neighbors")
        if not str(f["label_rationale"]).strip():
            raise ResolutionError(f"{f['fixture_id']}: empty label_rationale")
        if f["stratum"] == "S3" and not f["prompt_shape"]["relevance_warning_fires"]:
            raise ResolutionError(
                f"{f['fixture_id']}: S3 fixture whose replay does NOT carry the "
                "relevance warning — the stratum's whole premise"
            )
        if f["stratum"] in ("S1", "S2") and f["prompt_shape"]["relevance_warning_fires"]:
            raise ResolutionError(
                f"{f['fixture_id']}: adequate-pack fixture whose replay DOES "
                "carry the relevance warning"
            )


# ---------------------------------------------------------------------------
# Serialize / verify / CLI
# ---------------------------------------------------------------------------

def serialize(fixtures: list[dict]) -> str:
    return "".join(
        json.dumps(f, sort_keys=True, ensure_ascii=True) + "\n" for f in fixtures
    )


def build(loop_memory_path: Path = LOOP_MEMORY_PATH) -> tuple[list[dict], dict]:
    return resolve(_read_jsonl(loop_memory_path))


def load_manifest(path: Path = MANIFEST_PATH) -> list[dict]:
    return _read_jsonl(path)


def verify_manifest(rows: list[dict]) -> None:
    """Compare a manifest against a fresh resolution. Any difference is a
    resolution mismatch -> refuse loudly."""
    fresh, _ = build()
    if rows == fresh:
        return
    fresh_by_id = {f["fixture_id"]: f for f in fresh}
    for r in rows:
        f = fresh_by_id.get(r["fixture_id"])
        if f is None:
            raise ResolutionError(
                f"manifest row {r['fixture_id']} has no fresh-resolution match"
            )
        if r != f:
            diff = sorted(k for k in set(f) | set(r) if r.get(k) != f.get(k))
            raise ResolutionError(
                f"manifest row {r['fixture_id']} diverges from its source store "
                f"on {diff}; REFUSING (fixtures are frozen at lock and must "
                "re-verify byte-for-byte)"
            )
    raise ResolutionError(
        "manifest diverges from fresh resolution (row set/order mismatch)"
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in args
    force = "--force" in args

    try:
        fixtures, meta = build()
    except ResolutionError as exc:
        print(f"RESOLUTION MISMATCH — refusing: {exc}", file=sys.stderr)
        return 1

    payload = serialize(fixtures)
    meta["manifest_sha256"] = hashlib.sha256(payload.encode()).hexdigest()

    print(f"resolved {len(fixtures)} fixtures  "
          f"(S1={S1_EXPECTED_N} census / S2={sum(n for _, n in S2_QUOTA)} / S3={S3_N})")
    print(f"usable rows {meta['n_usable']} of {meta['loop_memory_rows']}")
    print("exclusions by reason:")
    for e in meta["exclusions_by_reason"]:
        print(f"  {e['n']:>3d}  {e['reason']}")
    print(f"  ---  {meta['n_exclusions_total']} total")
    div = meta["relevance_recompute_divergence"]
    print(f"relevance recompute diverges on {div['n_fixtures_diverging']} "
          f"of {len(fixtures)} fixtures")

    if MANIFEST_PATH.exists():
        existing = MANIFEST_PATH.read_text()
        if existing == payload:
            print(f"manifest verified: byte-identical to fresh resolution "
                  f"(sha256 {meta['manifest_sha256'][:16]})")
            META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
            return 0
        if check_only or not force:
            print(
                "REFUSING: bench/critic_cal/manifest.jsonl exists and DIFFERS "
                "from a fresh resolution. The manifest is frozen at lock; "
                "inspect the divergence (--check) or overwrite explicitly "
                "with --force.",
                file=sys.stderr,
            )
            return 1
    elif check_only:
        print("REFUSING --check: manifest.jsonl does not exist", file=sys.stderr)
        return 1

    MANIFEST_PATH.write_text(payload)
    META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print(f"wrote {MANIFEST_PATH} ({len(fixtures)} rows, "
          f"sha256 {meta['manifest_sha256'][:16]})")
    print(f"wrote {META_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
