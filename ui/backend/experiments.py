"""Experiments endpoints — Page B (Interactive Experiment Digestion).

The experiments on disk are HETEROGENEOUS. exp001 ships a JSON summary +
a per_round.jsonl; exp003 ships a MARKDOWN summary + a trials.jsonl; exp002
has no ``results/`` directory at all. These endpoints DETECT what each
experiment carries and degrade honestly — they never assume a uniform
schema and never fabricate fields that are absent.

Two endpoints, wired by ``register`` into the existing FastAPI app:

- ``GET /api/experiments`` — scans ``<experiments_dir>/*/`` and probes each
  experiment's ``results/`` dir, returning a flag-set per experiment.
  ``available:false`` when ``experiments_dir`` is absent (never a 500).
- ``GET /api/experiments/{expId}`` — parses what EXISTS for one experiment:
  a parsed ``summary.json`` + a bounded per-opponent per-round aggregate of
  ``per_round.jsonl`` (the file can be large — we aggregate, never dump),
  OR the raw markdown of ``summary.md`` + a bounded head sample of
  ``trials.jsonl``. Flags say what was found/missing. ``404`` when the
  experiment dir does not exist; ``400`` on path-traversal expId.

All reads are read-only; the UI never writes to ``experiments/``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException


# Default to the worktree root's experiments/ dir (git-tracked, populated).
# ``parents[2]`` from ui/backend/experiments.py == the worktree root.
_REPO = Path(__file__).resolve().parents[2]
DEFAULT_EXPERIMENTS_DIR = _REPO / "experiments"

# Bounds so a large producer file can never blow up the endpoint.
MAX_TRIALS_SAMPLE = 50          # head rows of trials.jsonl returned verbatim
MAX_PER_ROUND_ROWS = 100_000    # hard cap on per_round.jsonl rows scanned
MAX_LOOP_MEMORY_ROWS = 100_000  # hard cap on loop_memory.jsonl rows scanned

# Payoff-gap threshold that classifies an opponent as having EXPLOITED the
# LLM (opponent mean payoff exceeds the LLM's by more than this). Single
# source of truth: the backend marks each per_opponent row's `exploited`
# flag and echoes the threshold so the frontend never re-derives it.
EXPLOIT_GAP_THRESHOLD = 0.5

# Dirs under experiments/ that are scaffolding, not experiments.
_SKIP_DIRS = {"fixtures", "__pycache__"}

# The PRIMARY checkout's loop_memory (mirrors loop_v0.py's read pattern). The
# UI worktree's memory/ is not the one Nara writes; the bridge lives in the
# primary checkout. Read-only.
_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")
DEFAULT_LOOP_MEMORY_PATH = _PRIMARY_REPO / "memory" / "loop_memory.jsonl"

# Sandbox-tier -> experiment map. KEEP IN SYNC with
# orchestrator/tier_registry.py (do NOT import orchestrator from ui/). Tier
# order is the sandbox spectrum: synthetic -> semi_synthetic -> applied.
_TIER_MAP: list[dict] = [
    {
        "tier": "synthetic",
        "label": "Synthetic",
        "description": (
            "Classical games with known equilibria — the loop rediscovers or "
            "characterizes what is already known, so success is cleanly "
            "measurable."
        ),
        "experiment_ids": [
            "exp001_repeated_pd",
            "exp003_vickrey_rediscovery",
            "exp004_combinatorial_auction",
            "exp005_mechanism_aware",
        ],
    },
    {
        "tier": "semi_synthetic",
        "label": "Semi-synthetic",
        "description": (
            "LLM-as-designer scenarios with structure but no single ground "
            "truth — scored against a benchmark (e.g. VCG)."
        ),
        "experiment_ids": [
            "exp006_mechanism_design",
        ],
    },
    {
        "tier": "applied",
        "label": "Applied",
        "description": (
            "Design-only paper forecasting — read-only market data scored "
            "offline. CFTC-gated; not run (no live trading)."
        ),
        "experiment_ids": [
            "exp007_polymarket",
        ],
    },
]


def _read_loop_memory_bridges(path: Path) -> dict[str, list[dict]]:
    """Build experiment_id -> [{iteration_id, metric, value, trials}] from the
    loop_memory.jsonl bridge. Each row may carry a top-level
    ``experiment_outcome`` block {experiment_id, metric, value, trials?, ...};
    we key its outcomes by experiment_id, one entry per bridging iteration.

    Read-only; tolerates an absent file (-> empty), skips malformed rows, and
    ignores rows without a usable experiment_outcome. We never fabricate a
    bridge — only what the producer authored is surfaced.
    """
    bridges: dict[str, list[dict]] = {}
    if not path.exists():
        return bridges
    scanned = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if scanned >= MAX_LOOP_MEMORY_ROWS:
                    # Bounded read: a runaway bridge file can never blow up the
                    # page. The cap is far above the real row count.
                    break
                line = line.strip()
                if not line:
                    continue
                scanned += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    # Producer's contract; skip malformed rows rather than 500.
                    continue
                if not isinstance(row, dict):
                    continue
                outcome = row.get("experiment_outcome")
                if not isinstance(outcome, dict):
                    continue
                exp_id = outcome.get("experiment_id")
                if not isinstance(exp_id, str) or not exp_id:
                    continue
                bridges.setdefault(exp_id, []).append({
                    "iteration_id": row.get("iteration_id"),
                    "metric": outcome.get("metric"),
                    "value": outcome.get("value"),
                    "trials": outcome.get("trials"),
                })
    except OSError:
        # Unreadable bridge degrades to no-bridges rather than 500ing the page.
        return {}
    return bridges


def _resolve_headline(results_dir: Path) -> dict | None:
    """Resolve the SINGLE authoritative {verdict, tone, ...} headline for a
    results dir. This is the ONE verdict resolver shared by the detail endpoint
    and the research page — they must never diverge.

    Precedence (identical to the detail endpoint's render order):
      1. summary.json -> _derive_headline (per_opponent / per_mechanism / flat).
      2. An authored summary.md ``**Verdict: ...**`` line OVERRIDES the json
         headline ONLY for the legacy per_opponent (exp001) shape and the
         markdown-only (exp003) case — i.e. whenever the json headline is NOT a
         STRUCTURED (per_mechanism/flat, carries a ``kind``) headline. A
         structured json headline is the producer's authored conclusion and the
         markdown does not clobber it.
    Returns None when nothing readable yields a verdict — never fabricated.
    """
    headline: dict | None = None
    summary_json = results_dir / "summary.json"
    if summary_json.is_file():
        try:
            summary = json.loads(summary_json.read_text(encoding="utf-8"))
            headline = _derive_headline(summary)
        except (OSError, json.JSONDecodeError):
            headline = None
    summary_md = results_dir / "summary.md"
    if summary_md.is_file():
        try:
            md = summary_md.read_text(encoding="utf-8")
            verdict = _md_verdict(md)
        except OSError:
            verdict = None
        if verdict is not None:
            structured = (
                isinstance(headline, dict)
                and headline.get("kind") in ("per_mechanism", "flat")
            )
            if not structured:
                headline = {"verdict": verdict, "tone": _md_verdict_tone(verdict)}
    return headline


def _experiment_verdict(results_dir: Path) -> dict | None:
    """Derive a lightweight {text, tone} verdict for the research page by
    REUSING the SAME resolver the detail endpoint uses (``_resolve_headline``),
    so the two surfaces can never diverge — including the per_opponent (exp001)
    case where an authored summary.md verdict overrides the json headline. We
    never fabricate a verdict — no readable headline returns None.
    """
    headline = _resolve_headline(results_dir)
    if headline is None:
        return None
    return {"text": headline.get("verdict"), "tone": headline.get("tone")}


def _safe_exp_id(exp_id: str) -> str:
    """Allow only flat experiment-dir names. Refuse path traversal so the
    detail endpoint can't be coaxed outside ``experiments_dir``."""
    if not exp_id or len(exp_id) > 128:
        raise HTTPException(status_code=400, detail="invalid expId")
    allowed = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    )
    if any(ch not in allowed for ch in exp_id):
        raise HTTPException(status_code=400, detail="invalid expId")
    if exp_id in (".", ".."):
        raise HTTPException(status_code=400, detail="invalid expId")
    return exp_id


def _title_from_id(exp_id: str) -> str:
    """Derive a human title from the dir name. We don't invent metadata the
    experiment doesn't carry — this is a pure presentational transform of the
    id (``exp001_repeated_pd`` -> ``exp001 repeated pd``)."""
    return exp_id.replace("_", " ")


def _probe(results_dir: Path) -> dict:
    """Detect which known artifacts a results/ dir carries. Every flag is a
    plain on-disk existence check — nothing is assumed."""
    has_summary_json = (results_dir / "summary.json").is_file()
    has_summary_md = (results_dir / "summary.md").is_file()
    has_per_round = (results_dir / "per_round.jsonl").is_file()
    has_trials = (results_dir / "trials.jsonl").is_file()
    n_results_files = 0
    if results_dir.is_dir():
        n_results_files = sum(1 for p in results_dir.iterdir() if p.is_file())
    return {
        "has_results_dir": results_dir.is_dir(),
        "has_summary_json": has_summary_json,
        "has_summary_md": has_summary_md,
        "has_per_round": has_per_round,
        "has_trials": has_trials,
        "n_results_files": n_results_files,
    }


def _aggregate_per_round(path: Path) -> dict:
    """Aggregate per_round.jsonl into bounded per-opponent per-round series.

    Per-round rows carry NO task_id, so round->inspector linkage is ABSENT
    for this shape — we surface that fact rather than fabricate a link.
    Returns per-opponent arrays of {round, llm, opp, llm_payoff, opp_payoff,
    cum_llm, cum_opp} (cumulative payoff is accumulated server-side so the
    chart can plot the running total without re-walking the rows), capped at
    MAX_PER_ROUND_ROWS scanned.
    """
    by_opponent: dict[str, list[dict]] = {}
    cum: dict[str, dict[str, float]] = {}
    total = 0
    truncated = False
    has_task_id = False
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                if total >= MAX_PER_ROUND_ROWS:
                    truncated = True
                    break
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    # Producer's contract; skip malformed rows rather than 500.
                    continue
                total += 1
                if "task_id" in row:
                    has_task_id = True
                opp = row.get("opponent", "unknown")
                series = by_opponent.setdefault(opp, [])
                running = cum.setdefault(opp, {"llm": 0.0, "opp": 0.0})
                lp = row.get("llm_payoff")
                op = row.get("opp_payoff")
                if isinstance(lp, (int, float)):
                    running["llm"] += lp
                if isinstance(op, (int, float)):
                    running["opp"] += op
                series.append(
                    {
                        "round": row.get("round"),
                        "llm": row.get("llm"),
                        "opp": row.get("opp"),
                        "llm_payoff": lp,
                        "opp_payoff": op,
                        "cum_llm": round(running["llm"], 4),
                        "cum_opp": round(running["opp"], 4),
                    }
                )
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"per_round unreadable: {exc}"
        ) from exc
    return {
        "by_opponent": by_opponent,
        "total_rows": total,
        "truncated": truncated,
        # Round->inspector linkage requires a task_id on each round row. The
        # exp001 producer does not emit one; say so honestly.
        "round_inspector_linkage": has_task_id,
    }


def _verdict_tone(verdict) -> str | None:
    """Tone a single per-row / flat YES|NO verdict token. Returns ``ok`` for a
    YES, ``bad`` for a NO, ``warn`` for anything else, and ``None`` when the
    field is absent (so a caller can tell "no verdict" from "ambiguous"). We
    never guess a green/red outcome — only a clean YES/NO token colors."""
    if not isinstance(verdict, str):
        return None
    v = verdict.strip().lower()
    if v == "yes":
        return "ok"
    if v == "no":
        return "bad"
    return "warn"


def _derive_per_mechanism_headline(summary: dict) -> dict | None:
    """Headline for the per_mechanism shape (exp004 efficiency/revenue,
    exp005 signed-residual). Tally each row's YES/NO ``verdict`` token and
    summarize: YES on all N (ok), NO on all N (bad), or a mixed split (warn).
    Pure tally of the verdicts the producer already authored — we never invent
    a per-row verdict, and rows with a missing/ambiguous verdict count as
    not-YES. Returns ``None`` when there are no per_mechanism rows."""
    rows = summary.get("per_mechanism")
    if not isinstance(rows, list) or not rows:
        return None
    n = len(rows)
    n_yes = sum(
        1 for r in rows
        if isinstance(r, dict) and _verdict_tone(r.get("verdict")) == "ok"
    )
    if n_yes == n:
        verdict = f"YES on all {n} mechanisms"
        tone = "ok"
    elif n_yes == 0:
        verdict = f"NO on all {n} mechanisms"
        tone = "bad"
    else:
        verdict = f"Mixed: YES on {n_yes}/{n} mechanisms"
        tone = "warn"
    return {
        "verdict": verdict,
        "tone": tone,
        "kind": "per_mechanism",
        "n_mechanisms": n,
        "n_yes": n_yes,
    }


def _derive_flat_headline(summary: dict) -> dict | None:
    """Headline for the flat top-level-verdict shape (exp006). The producer
    authors a single ``verdict`` token; we only tone it (YES->ok, NO->bad,
    else warn). Returns ``None`` when there is no top-level verdict — we never
    fabricate one. The flat scalar metrics render in the metrics card, not
    here."""
    tone = _verdict_tone(summary.get("verdict"))
    if tone is None:
        return None
    return {
        "verdict": str(summary.get("verdict")),
        "tone": tone,
        "kind": "flat",
    }


def _derive_headline(summary: dict) -> dict | None:
    """Dispatch to the right OUTCOME-verdict deriver by the summary's SHAPE.

    The experiments are heterogeneous: exp001 carries ``per_opponent`` rows,
    exp004/005 carry ``per_mechanism`` rows, exp006 carries a flat top-level
    ``verdict``. We probe in that order and return the first shape that
    matches; ``None`` when none does (e.g. a markdown-only experiment whose
    json is absent). Each deriver is a pure transform of producer fields —
    nothing measured anew, no verdict invented.
    """
    # Only dispatch into a structured deriver when the list is NON-EMPTY. An
    # empty per_opponent/per_mechanism array is still a list, but it carries no
    # rows to tally — so we must fall through to the flat deriver rather than
    # short-circuit to None and silently drop a present top-level verdict.
    if isinstance(summary.get("per_opponent"), list) and summary["per_opponent"]:
        return _derive_per_opponent_headline(summary)
    if isinstance(summary.get("per_mechanism"), list) and summary["per_mechanism"]:
        return _derive_per_mechanism_headline(summary)
    return _derive_flat_headline(summary)


def _derive_per_opponent_headline(summary: dict) -> dict | None:
    """Derive the OUTCOME verdict for an exp001-shaped summary.json.

    The key result of a repeated-PD sweep is whether the LLM was EXPLOITED:
    against a defector its mean payoff collapses while it keeps cooperating.
    We classify each opponent by whether the LLM out-/under-scored it and
    surface the worst case, plus a one-line verdict. Pure transform of the
    summary the producer already emits — no new measurement, nothing faked.
    Returns ``None`` when the summary lacks per-opponent rows.
    """
    rows = summary.get("per_opponent")
    if not isinstance(rows, list) or not rows:
        return None
    exploited = []  # opponent out-scored the LLM by a clear margin
    coop_rates = []
    n_payoff_comparisons = 0  # opponents with a usable (lp, op) pair
    for r in rows:
        if not isinstance(r, dict):
            continue
        cr = r.get("llm_coop_rate")
        if isinstance(cr, (int, float)):
            coop_rates.append(cr)
        lp = r.get("llm_mean_payoff")
        op = r.get("opp_mean_payoff")
        if isinstance(lp, (int, float)) and isinstance(op, (int, float)):
            n_payoff_comparisons += 1
            if op - lp > EXPLOIT_GAP_THRESHOLD:
                exploited.append(
                    {"opponent": r.get("opponent", "?"),
                     "llm_mean_payoff": lp, "opp_mean_payoff": op,
                     "gap": round(op - lp, 4)}
                )
    exploited.sort(key=lambda e: e["gap"], reverse=True)
    parse_failures = sum(
        r.get("llm_parse_failures", 0) or 0
        for r in rows if isinstance(r, dict)
    )
    if exploited:
        worst = exploited[0]
        verdict = (
            f"EXPLOITED by {worst['opponent']}: opponent mean payoff "
            f"{worst['opp_mean_payoff']:.2f} vs LLM {worst['llm_mean_payoff']:.2f}"
        )
        tone = "bad"
    elif n_payoff_comparisons == 0:
        # No opponent carried a numeric (lp, op) pair, so exploitation could
        # not be measured. Never claim the favorable "held its own" outcome
        # from absent data — say it is undetermined.
        verdict = "Payoff data absent — exploitation undetermined"
        tone = "warn"
    else:
        verdict = "Not exploited: LLM held its own against every opponent"
        tone = "ok"
    return {
        "verdict": verdict,
        "tone": tone,
        "n_exploited": len(exploited),
        "n_opponents": len(rows),
        "worst": exploited[0] if exploited else None,
        "exploited": exploited,
        "exploit_gap_threshold": EXPLOIT_GAP_THRESHOLD,
        "mean_llm_coop_rate": (
            round(sum(coop_rates) / len(coop_rates), 4) if coop_rates else None
        ),
        "total_parse_failures": parse_failures,
    }


def _md_verdict(md: str) -> str | None:
    """Pull the verdict line out of a markdown summary (exp003 writes a
    ``**Verdict: ...**`` line). Returns the first such line stripped of its
    bold markers, or ``None`` if absent — we never invent a verdict."""
    for raw in md.splitlines():
        line = raw.strip()
        if line.lower().startswith("**verdict"):
            return line.replace("**", "").strip()
    return None


def _md_verdict_tone(verdict: str) -> str:
    """Tone a markdown verdict line from its DECISION token, not a substring
    scan of the whole sentence.

    A naked ``'no' in verdict.lower()`` mis-tones lines containing words like
    'cannot'/'economic'/'enough'; ``'yes' in ...`` mis-tones 'eyes'. We anchor
    on the text immediately after the first ``Verdict:`` label and test a
    word-boundary YES/NO at its head. Anything else is ``warn`` — we never
    guess a green/red outcome from an ambiguous line.
    """
    low = verdict.lower()
    idx = low.find("verdict")
    if idx != -1:
        # Skip the label itself plus any ':'/'—'/whitespace separators.
        rest = verdict[idx + len("verdict"):]
        rest = rest.lstrip(" :\t—-")
    else:
        rest = verdict
    head = rest.lower()
    if re.match(r"yes\b", head):
        return "ok"
    if re.match(r"no\b", head):
        return "bad"
    return "warn"


def _sample_trials(path: Path, limit: int) -> dict:
    """Return a bounded head sample of trials.jsonl (generic — we do not
    assume a fixed trial schema). Reports the total count it could read."""
    rows: list[dict] = []
    total = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                total += 1
                if len(rows) >= limit:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"trials unreadable: {exc}"
        ) from exc
    return {"sample": rows, "total_rows": total, "truncated": total > len(rows)}


def register(
    app,
    *,
    experiments_dir: Path = DEFAULT_EXPERIMENTS_DIR,
    loop_memory_path: Path = DEFAULT_LOOP_MEMORY_PATH,
) -> APIRouter:
    """Attach the experiments router. ``experiments_dir`` defaults to the
    worktree's ``experiments/`` (git-tracked + populated); ``loop_memory_path``
    defaults to the PRIMARY checkout's ``memory/loop_memory.jsonl`` (mirrors
    loop_v0.py — the bridge lives in the primary checkout, not this worktree).
    Tests pin both to tmp."""
    experiments_dir = Path(experiments_dir)
    loop_memory_path = Path(loop_memory_path)
    router = APIRouter(prefix="/api/experiments", tags=["experiments"])
    research_router = APIRouter(prefix="/api/research", tags=["research"])

    @router.get("")
    def list_experiments():
        if not experiments_dir.is_dir():
            return {"available": False, "reason": "experiments dir absent",
                    "experiments": []}
        out = []
        for child in sorted(experiments_dir.iterdir()):
            if not child.is_dir() or child.name in _SKIP_DIRS:
                continue
            if child.name.startswith("."):
                continue
            probe = _probe(child / "results")
            out.append({
                "id": child.name,
                "title": _title_from_id(child.name),
                **probe,
            })
        return {"available": True, "experiments": out}

    @router.get("/{exp_id}")
    def experiment_detail(exp_id: str):
        exp_id = _safe_exp_id(exp_id)
        exp_dir = experiments_dir / exp_id
        if not exp_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"no experiment {exp_id}")
        results_dir = exp_dir / "results"
        probe = _probe(results_dir)

        payload: dict = {
            "id": exp_id,
            "title": _title_from_id(exp_id),
            **probe,
            "summary_json": None,
            "summary_md": None,
            "per_round": None,
            "trials": None,
            "headline": None,
        }

        if probe["has_summary_json"]:
            try:
                summary = json.loads(
                    (results_dir / "summary.json").read_text(encoding="utf-8")
                )
                payload["summary_json"] = summary
            except (OSError, json.JSONDecodeError) as exc:
                payload["summary_json_error"] = f"unreadable: {exc}"

        if probe["has_per_round"]:
            payload["per_round"] = _aggregate_per_round(
                results_dir / "per_round.jsonl"
            )

        if probe["has_summary_md"]:
            try:
                payload["summary_md"] = (
                    results_dir / "summary.md"
                ).read_text(encoding="utf-8")
            except OSError as exc:
                payload["summary_md_error"] = f"unreadable: {exc}"

        # The headline is resolved by the ONE shared resolver so this detail
        # surface and /api/research can never diverge (json shape + the
        # per_opponent/markdown-only override, structured json never clobbered).
        payload["headline"] = _resolve_headline(results_dir)

        if probe["has_trials"]:
            payload["trials"] = _sample_trials(
                results_dir / "trials.jsonl", MAX_TRIALS_SAMPLE
            )

        return payload

    def _research_experiment(exp_id: str, bridges: dict[str, list[dict]]) -> dict:
        """Build one research-page experiment entry: probe flags + verdict +
        bridge. The dir may be ABSENT (e.g. a design-only tier entry) — then
        has_results_dir is false and verdict is null. ``bridges`` is read ONCE
        per request by the caller and passed in (not re-parsed per experiment).
        Nothing is fabricated."""
        results_dir = experiments_dir / exp_id / "results"
        probe = _probe(results_dir)
        verdict = (
            _experiment_verdict(results_dir)
            if probe["has_results_dir"]
            else None
        )
        return {
            "id": exp_id,
            "title": _title_from_id(exp_id),
            **probe,
            "verdict": verdict,
            "bridge": bridges.get(exp_id, []),
        }

    @research_router.get("")
    def research():
        if not experiments_dir.is_dir():
            return {
                "available": False,
                "reason": "experiments dir absent",
                "tiers": [],
                "untiered": [],
            }
        # Parse the loop_memory bridge ONCE per request, not once per experiment.
        bridges = _read_loop_memory_bridges(loop_memory_path)
        tiered_ids: set[str] = set()
        tiers_out = []
        for tier in _TIER_MAP:
            experiments = []
            for exp_id in tier["experiment_ids"]:
                tiered_ids.add(exp_id)
                experiments.append(_research_experiment(exp_id, bridges))
            tiers_out.append({
                "tier": tier["tier"],
                "label": tier["label"],
                "description": tier["description"],
                "experiments": experiments,
            })
        # Any experiment DIR on disk not claimed by the tier map -> untiered.
        untiered = []
        for child in sorted(experiments_dir.iterdir()):
            if not child.is_dir() or child.name in _SKIP_DIRS:
                continue
            if child.name.startswith("."):
                continue
            if child.name in tiered_ids:
                continue
            untiered.append(_research_experiment(child.name, bridges))
        return {
            "available": True,
            "tiers": tiers_out,
            "untiered": untiered,
        }

    app.include_router(router)
    app.include_router(research_router)
    return router
