"""LOOP_V1 — distill falsifier verdicts into DESIGN CONSTRAINTS (feedback seam).

The falsifier tiers already say precise, useful things and then throw them
away: `run_state/frontier_cluster_screen.jsonl` carries per-role reasonings
that NAME the controls a claim is missing ("missing: a well-mixed baseline,
an ablation removing neighbor observability, a fixed-horizon comparison,
sample size"), and `memory/loop_memory.jsonl` carries the local redteam's
fatal-flaw critiques. Today the VERDICT gates promotion and the CONTENT
conditions nothing. This module turns that content into durable, queryable
knowledge.

WHAT THIS IS NOT: no LLM call happens here, ever. Distillation is
deterministic CODE — sentence-splitting, keyword rules, verbatim quoting.
The frontier's words are carried as provenance-tagged ANNOTATION with the
role/vendor attached, never paraphrased into the loop's own voice and never
used to generate anything on their own (D-061: frontier models veto and
annotate; they are never generators, and they never write loop_memory or
the brain). The runtime never reads the framework brain either (D-014) —
nothing here touches it.

Three seams, all opt-in (full flow + gates: ``docs/veto_elevation.md``):

  1. ``--once``   — append new rows to ``memory/design_constraints.jsonl``
                    (shape below). Idempotent on ``constraint_id``.
                    ``--rebuild`` REWRITES that store from the current
                    extractor (it is a derived artifact — see ``distill``).
  2. ``--propose``— ONE follow-up per vetoed cluster that named a runnable
                    control, appended to ``memory/frontier_agenda.jsonl`` at
                    ``status: "proposed"`` — INERT until a human accepts it,
                    so the human stays the generator-of-record. "One per
                    cluster" holds ACROSS RUNS: the proposal id hashes the
                    cluster alone and every candidate is checked against the
                    whole existing agenda file (rows from earlier runs and
                    from the weekly cron included).
  3. ``conditioning_bullets()`` — read by workers.meta_review behind the
                    DARK env gate ``NARA_CONSTRAINT_CONDITION`` (default OFF;
                    conditioning generation is the one step that could shape
                    it, so it does not arm itself).

Row shape (``memory/design_constraints.jsonl``):

    {"constraint_id": "dc-<sha8>", "ts": ..., "cluster_id": ...,
     "claim_head": "<what was being judged>",
     "flaw_class": <one of FLAW_CLASSES, by ORDERED KEYWORD RULES>,
     "flaw_class_all": [...],   # every rule that fired — a single label
                                # never hides a second true reading (rule 4)
     "missing_controls": ["<verbatim fragment>", ...],   # [] when none parse
     "source": {"kind": "frontier_screen"|"redteam", "role": ...,
                "vendor_or_model": ..., "verdict": ...,
                "verbatim_quote": "<=600 chars"},
     "status": "active",
     "legacy_constraint_id": "dc-<sha8>"}   # --rebuild only, when the id moved

CLI: ``python -m workers.constraint_distill --once [--rebuild] [--propose]
      [--dry-run]``
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("constraint_distill")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCREEN = REPO_ROOT / "run_state" / "frontier_cluster_screen.jsonl"
DEFAULT_LOOP_MEMORY = REPO_ROOT / "memory" / "loop_memory.jsonl"
DEFAULT_SURFACED = REPO_ROOT / "memory" / "surfaced_findings.jsonl"
DEFAULT_CONSTRAINTS = REPO_ROOT / "memory" / "design_constraints.jsonl"
DEFAULT_AGENDA = REPO_ROOT / "memory" / "frontier_agenda.jsonl"

# The agenda has a LIVE concurrent writer: cron/weekly-frontier-agenda.sh is
# installed (30 5 * * 0) and appends via orchestrator.frontier_agenda. That
# script's gate 1 is `flock -n 9` on this exact file, so taking the SAME lock
# here is what makes a `--propose` run and the weekly cron mutually exclusive.
AGENDA_LOCK = REPO_ROOT / "run_state" / ".frontier-agenda-cron.lock"
AGENDA_LOCK_WAIT_S = 30.0   # bounded wait, then an explicit logged refusal

QUOTE_MAX = 600          # source.verbatim_quote budget
HEAD_MAX = 200           # claim_head budget
CONTROLS_CAP = 6         # named controls kept per constraint
FRAGMENT_MIN = 8         # chars; below this a "fragment" names nothing
FRAGMENT_MAX = 140       # chars; above this it is a sentence, not an object
CONDITION_CAP = 3        # bullets handed to meta_review when ARMED
PROPOSALS_CAP = 10       # per --propose run; the remainder is reported

# Verdicts that carry an articulated defect worth distilling. "pass" says
# nothing about design; "inconclusive" often names the controls it would
# need, so it is kept — with its own verdict recorded, never relabelled.
DEFECT_VERDICTS = ("veto", "inconclusive", "fatal_flaw")
BLOCKING_VERDICTS = ("veto", "fatal_flaw")   # a proposal needs a real kill

# What marks a fragment as control-like (the extraction filter). Word-
# bounded on purpose: an unbounded "matched" also fires inside
# "mismatched hypothesis", which is a category complaint, not a control.
_CONTROL_RE = re.compile(
    r"\b(?:baselines?|ablations?|controls?|randomi[sz]\w*|sample sizes?|"
    r"comparisons?|comparators?|matched|holdouts?|replications?|seeds?|"
    r"effect sizes?|pre-registered|sweep|manipulation checks?|placebo|"
    r"counterfactuals?|held constant|holding \w+ (?:fixed|constant)|"
    r"condition order)\b", re.IGNORECASE)

# A fragment that names only "such controls" carries no design information.
_VAGUE_FRAGMENT = re.compile(
    r"^(?:such|these|those|the|any|other|additional|its|their)\s+"
    r"(?:controls?|baselines?|comparisons?|ablations?)$", re.IGNORECASE)

# Ordered flaw-class rules: FIRST match wins for `flaw_class`, and every
# match is recorded in `flaw_class_all`. Order is by what the finding needs
# next: a prior-exists / category-error / unfalsifiable kill cannot be
# rescued by running a control, so those outrank the control classes.
_FLAW_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prior_exists", (
        "already introduced", "already reports", "already establish",
        "restatement", "prior result", "existing empirical result",
        "existing result", "subsume", "special case", "trivial corollary",
        "is already", "already done", "minor restatement",
    )),
    ("category_error", (
        "category error", "mischaracteriz", "conflat", "tautolog",
        "circular", "mismatched hypothesis", "logically circular",
        "assess an entirely different mechanism",
    )),
    ("unfalsifiable", (
        "unfalsifiable", "cannot be falsified", "not a testable hypothesis",
        "untestable", "not falsifiable", "no predictive relationship",
    )),
    ("missing_control", (
        "missing control", "missing:", "required control", "requires at minimum",
        "requires at least", "at minimum an", "baseline", "ablation",
        "randomiz", "sample size", "matched", "no control", "lacks essential controls",
        "control", "comparison",
    )),
    ("mechanism_underdetermined", (
        "underdetermined", "unidentified", "insufficient to produce",
        "cannot separate", "does not isolate", "silently assumes",
        "additional, unstated", "unstated asymmetry", "no logical bridge",
        "confound",
    )),
    ("no_evidence", (
        "experiment_outcome is null", "no experiment", "no experimental",
        "absence of contradiction", "no evidence", "contains only the claim",
        "is a reported observation", "no data", "not provided",
        "categorically incapable", "incapable of supporting",
    )),
)
FLAW_CLASSES = tuple(name for name, _ in _FLAW_RULES) + ("other",)

# Sentence boundary = terminator followed by something that STARTS a
# sentence; "fixed-horizon vs. unknown-horizon comparison" is one phrase.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
_CLAUSE_TOKEN = re.compile(r"[;,:]|\s+(?:and|nor|as well as)\s+", re.IGNORECASE)
_LEADING_NOISE = re.compile(
    r"^(?:and|or|nor|but|also|then|plus|while|yet|so|thus|therefore|"
    r"however|moreover|whereas)\b\s*"
    r"|^(?:missing|required|the required)\s+controls?\s*(?:include|are)?\s*"
    r"|^missing\s*:\s*"
    r"|^at\s+(?:minimum|least)\s*"
    r"|^no\s+", re.IGNORECASE)
_RELATIVE_START = re.compile(r"^(?:which|that|who|whose|where|it|this|they)\b",
                             re.IGNORECASE)

# --- the RUNNABLE-DESIGN-OBJECT test ---------------------------------------
# docs/veto_elevation.md §"Which vetoes become research questions" states the
# criterion: a kept fragment must read as a runnable design object — a thing
# you could go do — and NOT as a description of the claim's fault. Until
# 2026-08-19 only `_CONTROL_RE` guarded the store, so the mere WORDS
# comparator/comparison/control admitted complaints: "The claim
# mischaracterizes its own comparator", "the claim silently depends on
# missing controls", and — the exact string the doc holds up as what must be
# REJECTED — "The term 'non-equilibrium markets' is too vague to serve as a
# controlled baseline". These three rules make the code satisfy the doc.

# (1) A fault predicate is the verb of a COMPLAINT, never of a design object.
#     Note what is deliberately ABSENT: requires/lacks/needs and the
#     "…is provided/available/required" copulas. Those are how a reviewer
#     NAMES a missing control, so they are stripped (below), not rejected.
_FAULT_RE = re.compile(
    r"\b(?:mischaracteriz\w*|conflat\w*|tautolog\w*|circular|"
    r"too vague|vague|ill-?defined|underspecified|unfalsifiable|untestable|"
    r"incoherent|confound\w*|"
    r"silently|hinges?|depends? on|driven by|drives?|determined by|"
    r"cannot|could not|does not|do not|did not|is not|are not|was not|"
    r"were not|fails?|failure|neither|"
    r"assumes?|mistakes?|misreads?|misstates?)\b", re.IGNORECASE)

# (2) A negated opening states what the record ISN'T ("not a comparison of
#     composition bounds") — a finding, not an experiment.
_NEGATED_START = re.compile(r"^(?:not|never|nothing|none)\b", re.IGNORECASE)

# (3) A requirement frame introduces the control; the control is the TAIL.
#     "The claim requires at least an otherwise-identical randomized
#     comparison…" -> "an otherwise-identical randomized comparison…".
#     Bounded to the first 80 chars so it strips a frame, not a sentence.
_REQUIREMENT_FRAME = re.compile(
    r"^.{0,80}?\b(?:requires?|require|needs?|needed|lacks?|lacking|"
    r"is missing|are missing|must\s+(?:have|include)|"
    r"depends?\s+on\s+missing)\s+(?:at\s+(?:minimum|least)\s+)?",
    re.IGNORECASE)

# (4) "No <control> is provided" — the same naming construction from the
#     other end. The leading "no " is already stripped; drop the copular
#     tail so the design object survives (still a verbatim prefix).
_MISSING_TAIL = re.compile(
    r"\s+(?:is|are|was|were)\s+(?:provided|available|present|given|reported|"
    r"shown|performed|conducted|required|specified|described|documented)\b.*$",
    re.IGNORECASE)

# (5) A fragment ending on a preposition/determiner is a mangled shard
#     ("numerical or analytical comparison of"), not a design object.
_DANGLING_TAIL = re.compile(
    r"\b(?:of|in|on|to|for|with|and|or|by|from|at|as|than|between|across|"
    r"over|under|that|which|the|a|an|is|are|was|were)$", re.IGNORECASE)


def _split_clauses(sentence: str) -> list[str]:
    """Clause split that never cuts inside a bracketed group.

    A plain ``re.split`` on ``[;,:]`` mangles "(epsilon, delta) curves" into
    two shards — both of which then reached the live store (2026-08-19).
    Depth-tracked so a parenthetical is one token."""
    parts: list[str] = []
    depth = start = i = 0
    while i < len(sentence):
        ch = sentence[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(depth - 1, 0)
        elif depth == 0:
            m = _CLAUSE_TOKEN.match(sentence, i)
            if m:
                parts.append(sentence[start:i])
                i = start = m.end()
                continue
        i += 1
    parts.append(sentence[start:])
    return parts


def _matching_bracket(text: str, start: int) -> int:
    """Index of the bracket closing the one at `start`, else -1."""
    depth = 0
    for k in range(start, len(text)):
        if text[k] in "([":
            depth += 1
        elif text[k] in ")]":
            depth -= 1
            if depth == 0:
                return k
    return -1


def _clause_candidates(sentence: str) -> list[str]:
    """Depth-0 clauses, plus — for any clause too long to be a fragment —
    its prefix and its parenthetical contents, re-split.

    Keeping parentheticals whole is what stops "(epsilon, delta)" being
    mangled, but a reviewer also names controls INSIDE an aside ("…are
    identifiable (… so an information-theoretic identifiability argument or
    empirical reconstruction rate with baselines is required and absent)").
    Expanding only the over-long clauses recovers those without re-opening
    the mangling. Each expansion is strictly shorter, so this terminates."""
    out: list[str] = []
    work = _split_clauses(sentence)
    while work:
        clause = work.pop(0)
        out.append(clause)
        if len(clause) <= FRAGMENT_MAX:
            continue
        i = clause.find("(")
        if i < 0:
            continue
        j = _matching_bracket(clause, i)
        pieces = [clause[:i],
                  clause[i + 1:j] if j > 0 else clause[i + 1:],
                  clause[j + 1:] if j > 0 else ""]
        expanded: list[str] = []
        for piece in pieces:
            piece = piece.strip(" ,;:")
            if piece:
                expanded.extend(_split_clauses(piece))
        work[:0] = expanded
    return out


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """JSONL -> list of dicts. Missing file -> []. Malformed/blank lines are
    skipped (never crash on a partial write)."""
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _append_rows(path: str | Path, rows: list[dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _rewrite_rows(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Atomic full rewrite (tmp + os.replace) — a --rebuild must never leave
    a half-written derived store behind."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".rebuild.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def _agenda_lock_path(agenda_path: str | Path) -> Path:
    """The real agenda file is guarded by the cron's own lock; any other
    path (tests, a scratch agenda) gets a sibling lock so a test can never
    contend with the installed weekly cron."""
    p = Path(agenda_path)
    try:
        if p.resolve() == DEFAULT_AGENDA.resolve():
            return AGENDA_LOCK
    except OSError:
        pass
    return Path(str(p) + ".lock")


@contextlib.contextmanager
def _agenda_lock(path: str | Path, wait_s: float) -> Iterator[bool]:
    """Exclusive flock, bounded wait, explicit result.

    cron/weekly-frontier-agenda.sh (installed: 30 5 * * 0) holds this exact
    lock across its whole `orchestrator.frontier_agenda --once` pass, which
    ends in an append to the same agenda file. Taking it here is what stops a
    `--propose` run interleaving a partial line with the cron's. Yields False
    rather than writing unlocked if the cap expires — a fallback that is
    stated, time-capped and logged (inviolate rule 7), never a silent
    degraded path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = p.open("w")
    acquired = False
    deadline = time.monotonic() + wait_s
    try:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.25)
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def _flat(text: Any, limit: int) -> str:
    """Whitespace-collapsed text truncated to `limit` chars INCLUDING the
    ellipsis — a quote budget that is not actually a budget is a lie."""
    if not isinstance(text, str):
        return ""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: max(limit - 1, 0)].rstrip() + "…"


def classify_flaw(text: str) -> tuple[str, list[str]]:
    """(flaw_class, every_class_that_matched) by ordered keyword rules.

    Deterministic and LLM-free. No match -> ("other", []); the verbatim
    quote still carries the knowledge in that case."""
    low = (text or "").lower()
    matched = [name for name, pats in _FLAW_RULES if any(p in low for p in pats)]
    return (matched[0] if matched else "other"), matched


def _balanced(frag: str) -> str:
    """Drop an unclosed parenthetical tail — clause-splitting inside "(...)"
    otherwise leaves fragments like "an ablation removing observability
    (which would eliminate imitation". Prefix-only: still verbatim."""
    while frag.count("(") > frag.count(")"):
        frag = frag[: frag.rfind("(")].rstrip(" ,;")
    return frag


def extract_missing_controls(reasoning: str) -> list[str]:
    """Verbatim RUNNABLE-DESIGN-OBJECT fragments named in a reviewer's
    reasoning — the controls a reader could go run, not the reviewer's
    complaints about the claim.

    Conservative: split into sentences, split those on clause boundaries
    (bracket-aware, so "(epsilon, delta)" stays whole), strip a leading
    marker ("Missing controls include", "no "), REJECT anything carrying a
    fault predicate or a negated opening, strip a requirement frame ("The
    claim requires at least …") and a "…is provided" tail so the named
    object survives, then keep only fragments that (a) name a control-ish
    thing, (b) read as a noun phrase rather than a trailing relative clause
    or a mangled shard. Nothing is invented — every returned string is a
    substring of the reasoning modulo whitespace and the stripped frame."""
    if not isinstance(reasoning, str) or not reasoning.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for sentence in _SENTENCE_SPLIT.split(" ".join(reasoning.split())):
        for raw in _clause_candidates(sentence):
            frag = _LEADING_NOISE.sub("", raw.strip()).strip()
            # The fault test runs on the WHOLE clause, before any frame is
            # stripped — otherwise stripping "…that lacks" would launder
            # "an underspecified metric that lacks a formal criterion" into
            # an acceptance.
            if _FAULT_RE.search(frag) or _NEGATED_START.match(frag):
                continue
            frag = _REQUIREMENT_FRAME.sub("", frag, count=1)
            frag = _MISSING_TAIL.sub("", frag)
            frag = _balanced(frag).strip(" .;,'\"")
            if not (FRAGMENT_MIN <= len(frag) <= FRAGMENT_MAX) \
                    or len(frag.split()) < 2:
                continue
            if _RELATIVE_START.match(frag) or _VAGUE_FRAGMENT.match(frag):
                continue
            if _DANGLING_TAIL.search(frag) or not _CONTROL_RE.search(frag):
                continue
            low = frag.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(frag)
            if len(out) >= CONTROLS_CAP:
                return out
    return out


# A fragment only becomes an EXPERIMENT if it names a design object...
_STRONG_DESIGN = re.compile(
    r"\b(?:baselines?|ablations?|comparisons?|randomi[sz]\w*|matched|"
    r"controls?|holdouts?|counterfactuals?|held constant|sweep|"
    r"replications?)\b", re.IGNORECASE)
# ...and is not merely a COMPLAINT about the claim, or a restatement of the
# mechanism ("'non-equilibrium markets' is too vague to serve as a
# controlled baseline" names no runnable control).
_COMPLAINT = re.compile(
    r"\b(?:conflat\w*|too vague|ill-defined|confounded|lacks?|fails?|"
    r"cannot|mischaracteriz\w*|silently|hinges|driven by|determined by)\b",
    re.IGNORECASE)


def best_control(fragments: list[str]) -> str | None:
    """The fragment that best reads as AN EXPERIMENT TO RUN, or None when
    none does: it must name a design object and must not be a complaint
    about the claim. A bare "sample size" is a parameter, not an
    experiment. None here means NO proposal for that cluster — inventing
    the experiment would be generation, and this module never generates."""
    best: tuple[int, int, str] | None = None
    for i, frag in enumerate(fragments):
        if not _STRONG_DESIGN.search(frag) or _COMPLAINT.search(frag):
            continue
        if frag.strip().lower() in ("sample size", "sample sizes", "effect size"):
            continue
        score = 1 if 4 <= len(frag.split()) <= 20 else 0
        if best is None or (score, -i) > (best[0], -best[1]):
            best = (score, i, frag)
    if best is None:
        return None
    return re.sub(r"^no\s+", "", best[2], flags=re.IGNORECASE)


def _recovered_hypothesis(text: str) -> str:
    """Some early loop_memory rows (iter-2026-06-05-005) stored the whole
    candidate-selection JSON blob in hypothesis.text, with LaTeX that makes
    it invalid strict JSON. Same deterministic recovery as
    bench/redteam_cal/build_fixtures.py: escape lone backslashes, parse,
    take "chosen" (else the first candidate). Anything unparseable is
    returned unchanged — no guessing."""
    if not text.startswith("{"):
        return text
    try:
        blob = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text))
    except json.JSONDecodeError:
        return text
    chosen = blob.get("chosen") if isinstance(blob, dict) else None
    if isinstance(chosen, str) and chosen.strip():
        return chosen
    cands = blob.get("candidates") if isinstance(blob, dict) else None
    if isinstance(cands, list) and cands and isinstance(cands[0], str):
        return cands[0]
    return text


def claim_heads(loop_memory_path: str | Path = DEFAULT_LOOP_MEMORY,
                surfaced_path: str | Path = DEFAULT_SURFACED) -> dict[str, str]:
    """{iteration_id -> short claim head}. The surfaced finding's `claim` is
    the best head; the iteration's hypothesis text is the fallback (the
    surfaced `title` is NOT trusted — some rows carry a retrieved paper's
    title there). Absent -> key simply missing, never fabricated."""
    heads: dict[str, str] = {}
    for row in _read_jsonl(loop_memory_path):
        iid = row.get("iteration_id")
        hyp = row.get("hypothesis") if isinstance(row.get("hypothesis"), dict) else {}
        text = hyp.get("text")
        if isinstance(iid, str) and isinstance(text, str) and text.strip():
            heads[iid] = _flat(_recovered_hypothesis(text.strip()), HEAD_MAX)
    for row in _read_jsonl(surfaced_path):
        iid = row.get("source_iteration_id")
        claim = row.get("claim")
        if isinstance(iid, str) and isinstance(claim, str) and claim.strip():
            heads[iid] = _flat(claim.strip(), HEAD_MAX)
    return heads


def _constraint(cluster_id: str, head: str, kind: str, role: str,
                vendor: str, verdict: str, reasoning: str,
                ts: str) -> dict[str, Any]:
    controls = extract_missing_controls(reasoning)
    quote = _flat(reasoning, QUOTE_MAX)
    flaw, all_flaws = classify_flaw(reasoning)
    # Hash the FULL reasoning, not the 600-char stored quote: two reasonings
    # from the same cluster/kind/role/vendor that share a 600-char prefix
    # would otherwise collide and the second would be silently dropped as
    # "already distilled". Truncation is a STORAGE budget, never an identity.
    digest = hashlib.sha256(
        f"{cluster_id}\n{kind}\n{role}\n{vendor}\n"
        f"{' '.join(reasoning.split())}".encode("utf-8")
    ).hexdigest()[:8]
    return {
        "constraint_id": f"dc-{digest}",
        "ts": ts,
        "cluster_id": cluster_id,
        "claim_head": head,
        "flaw_class": flaw,
        "flaw_class_all": all_flaws,
        "missing_controls": controls,
        "source": {
            "kind": kind,
            "role": role,
            "vendor_or_model": vendor,
            "verdict": verdict,
            "verbatim_quote": quote,
            # Integrator 2026-08-19: 11 of 33 live fragments sat PAST the
            # 600-char quote budget — every one verified present in the full
            # source reasoning (zero fabrications), but a reader auditing
            # such a row could not confirm the fragment from the row itself.
            # The budget stays a real budget (breaking it to hide this would
            # be the lie _flat's docstring warns about); instead the gap is
            # LEGIBLE: false means "verify against the source ledger, not
            # this excerpt".
            "quote_covers_controls": all(c in quote for c in controls),
        },
        "status": "active",
    }


def constraints_from_screen(rows: list[dict], heads: dict[str, str]
                            ) -> list[dict[str, Any]]:
    """One constraint per defect-bearing reviewer entry — methods, novelty,
    and each role's cross_run re-review (a cross-run veto is a SECOND
    vendor's independent statement, so it earns its own row)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        cid = row.get("cluster_id")
        screen = row.get("screen") if isinstance(row.get("screen"), dict) else {}
        if not isinstance(cid, str) or not screen:
            continue
        head = heads.get(cid.removeprefix("cl-"), cid)
        ts = row.get("ts") if isinstance(row.get("ts"), str) else _now_utc_iso()
        for role_key in ("methods", "novelty"):
            entry = screen.get(role_key)
            if not isinstance(entry, dict):
                continue
            for review in (entry, entry.get("cross_run")):
                if not isinstance(review, dict):
                    continue
                verdict = review.get("verdict")
                reasoning = review.get("reasoning")
                if verdict not in DEFECT_VERDICTS or not isinstance(reasoning, str):
                    continue
                out.append(_constraint(
                    cid, head, "frontier_screen",
                    str(review.get("role") or f"{role_key}_reviewer"),
                    str(review.get("vendor") or "unknown"),
                    str(verdict), reasoning, ts))
    return out


def constraints_from_redteam(rows: list[dict], heads: dict[str, str]
                             ) -> list[dict[str, Any]]:
    """One constraint per redteam FATAL_FLAW critique (proceed rows carry no
    defect). Cluster id follows the ledger convention: "cl-<iteration_id>"."""
    out: list[dict[str, Any]] = []
    for row in rows:
        rt = row.get("redteam") if isinstance(row.get("redteam"), dict) else {}
        iid = row.get("iteration_id")
        critique = rt.get("critique")
        if rt.get("verdict") != "fatal_flaw" or not isinstance(iid, str):
            continue
        if not isinstance(critique, str) or not critique.strip():
            continue
        ts = row.get("ended_at") if isinstance(row.get("ended_at"), str) else _now_utc_iso()
        out.append(_constraint(
            f"cl-{iid}", heads.get(iid, iid), "redteam", "redteam_critic",
            str(rt.get("subagent_model") or rt.get("subagent_backend") or "unknown"),
            "fatal_flaw", critique, ts))
    return out


def _row_key(row: dict) -> tuple[str, str, str, str, str]:
    """Identity of a constraint INDEPENDENT of the id function — used only to
    carry an old id forward across a --rebuild."""
    src = row.get("source") if isinstance(row.get("source"), dict) else {}
    return (str(row.get("cluster_id")), str(src.get("kind")),
            str(src.get("role")), str(src.get("vendor_or_model")),
            str(src.get("verbatim_quote")))


def distill(*, screen_path: str | Path = DEFAULT_SCREEN,
            loop_memory_path: str | Path = DEFAULT_LOOP_MEMORY,
            surfaced_path: str | Path = DEFAULT_SURFACED,
            constraints_path: str | Path = DEFAULT_CONSTRAINTS,
            dry_run: bool = False,
            rebuild: bool = False) -> dict[str, Any]:
    """One distillation pass. Returns {"written", "skipped", "by_flaw_class",
    "rebuilt", "replaced"}; `written` rows are appended unless dry_run.
    Idempotent — constraint_ids already on file are skipped (the id hashes
    source+cluster+FULL reasoning, so an unchanged store re-runs to zero new
    rows and a RE-screen with new text records new knowledge instead of
    overwriting the old).

    `rebuild=True` REWRITES the store from the current extractor instead of
    appending. That is legitimate because
    ``memory/design_constraints.jsonl`` is a DERIVED artifact: every field is
    a deterministic, LLM-free function of ``frontier_cluster_screen.jsonl``
    plus ``loop_memory.jsonl``, which are themselves the append-only ledgers
    of what actually happened. The store records no event of its own, so
    regenerating it destroys no history — whereas leaving a fixed extractor's
    old output in place would leave known-wrong rows readable by the
    conditioning seam. (``memory/frontier_agenda.jsonl`` is the opposite: it
    records human-facing proposals and their lifecycle, so it stays strictly
    append-only.) Any row whose id moved carries `legacy_constraint_id` so
    an agenda row citing the old id is still resolvable."""
    heads = claim_heads(loop_memory_path, surfaced_path)
    fresh = (constraints_from_screen(_read_jsonl(screen_path), heads)
             + constraints_from_redteam(_read_jsonl(loop_memory_path), heads))
    prior_rows = _read_jsonl(constraints_path)
    existing = set() if rebuild else {r.get("constraint_id") for r in prior_rows}
    prior_ids = {_row_key(r): r.get("constraint_id") for r in prior_rows}
    seen: set[str] = set()
    written: list[dict[str, Any]] = []
    for row in fresh:
        cid = row["constraint_id"]
        if cid in existing or cid in seen:
            continue
        seen.add(cid)
        if rebuild:
            old = prior_ids.get(_row_key(row))
            if isinstance(old, str) and old and old != cid:
                row["legacy_constraint_id"] = old
        written.append(row)
    by_class: dict[str, int] = {}
    for row in written:
        by_class[row["flaw_class"]] = by_class.get(row["flaw_class"], 0) + 1
    if not dry_run:
        if rebuild:
            _rewrite_rows(constraints_path, written)
        elif written:
            _append_rows(constraints_path, written)
    log.info("constraint_distill: %d %s constraint(s), %d skipped as already "
             "distilled%s", len(written), "rebuilt" if rebuild else "new",
             len(fresh) - len(written),
             " (dry-run, nothing written)" if dry_run else "")
    return {"written": written, "skipped": len(fresh) - len(written),
            "by_flaw_class": by_class, "rebuilt": rebuild,
            "replaced": len(prior_rows) if rebuild else 0}


def load_active(path: str | Path = DEFAULT_CONSTRAINTS) -> list[dict[str, Any]]:
    """Active constraints, newest ts first (deterministic tie-break on id)."""
    rows = [r for r in _read_jsonl(path)
            if r.get("status") == "active" and isinstance(r.get("cluster_id"), str)]
    rows.sort(key=lambda r: (str(r.get("ts") or ""), str(r.get("constraint_id"))),
              reverse=True)
    return rows


def conditioning_bullets(topic: str,
                         path: str | Path = DEFAULT_CONSTRAINTS,
                         cap: int = CONDITION_CAP) -> list[str]:
    """Up to `cap` labelled design-constraint bullets matched to `topic` by
    cheap token overlap (the idea_projection convention). An off-topic store
    contributes ZERO bullets — never padded. Read by meta_review only when
    NARA_CONSTRAINT_CONDITION is set; this function itself is inert."""
    from workers.retrieval_relevance import _tokenize
    ttoks = _tokenize(topic)
    if not ttoks:
        return []
    scored: list[tuple[float, str, dict]] = []
    for row in load_active(path):
        ctoks = _tokenize(f"{row.get('claim_head', '')} "
                          f"{' '.join(row.get('missing_controls') or [])}")
        if not ctoks:
            continue
        overlap = len(ttoks & ctoks) / len(ttoks)
        if overlap > 0.0:
            scored.append((overlap, str(row.get("constraint_id")), row))
    scored.sort(key=lambda x: (-x[0], x[1]))
    bullets: list[str] = []
    seen_clusters: set[str] = set()
    for _, _, row in scored:
        cluster = str(row.get("cluster_id"))
        if cluster in seen_clusters:   # one bullet per claim, not per reviewer
            continue
        seen_clusters.add(cluster)
        src = row.get("source") if isinstance(row.get("source"), dict) else {}
        label = f"[constraint from {src.get('kind')}/{src.get('role')}]"
        controls = row.get("missing_controls") or []
        body = ("missing controls named: " + "; ".join(controls[:3])) if controls \
            else f"{row.get('flaw_class')}: {_flat(src.get('verbatim_quote'), 220)}"
        bullets.append(f"{label} {_flat(row.get('claim_head'), 110)} — {body}")
        if len(bullets) >= cap:
            break
    return bullets


def proposal_id_for(cluster_id: str) -> str:
    """The proposal id for a cluster — hashed from the CLUSTER ALONE.

    Until 2026-08-19 the id hashed the rendered topic, and the topic embeds
    both the claim_head and the chosen control. Both drift routinely: a
    re-screen names more controls (changing which one ranks best), and a
    later-surfaced finding overrides the loop_memory hypothesis as the head.
    So the documented "ONE follow-up proposal per vetoed cluster" guarantee
    held only WITHIN a single run — proven live twice on
    cl-iter-2026-05-26-008. The dedupe key must be the stable thing the
    guarantee is stated over: the cluster. Source kind is deliberately NOT
    in the key — a frontier veto and a redteam kill of the same cluster are
    the same cluster, and `_proposal_rank` already picks between them."""
    return "fa-" + hashlib.sha256(
        f"distilled\n{cluster_id}".encode("utf-8")).hexdigest()[:8]


def proposals_from_constraints(constraints: list[dict], ts: str
                               ) -> list[dict[str, Any]]:
    """ONE follow-up proposal per vetoed cluster that NAMED a missing
    control — the named control becomes the experiment. Clusters killed on
    prior-exists / category-error / unfalsifiable grounds get no proposal
    (a control cannot rescue them), nor do clusters where nothing parsed:
    inventing an experiment there would be generation, which this module
    does not do."""
    best: dict[str, dict] = {}
    for row in constraints:
        src = row.get("source") if isinstance(row.get("source"), dict) else {}
        if src.get("verdict") not in BLOCKING_VERDICTS:
            continue
        if row.get("flaw_class") not in ("missing_control", "mechanism_underdetermined"):
            continue
        if best_control(row.get("missing_controls") or []) is None:
            continue
        cid = str(row.get("cluster_id"))
        prior = best.get(cid)
        if prior is None or _proposal_rank(row) > _proposal_rank(prior):
            best[cid] = row
    out: list[dict[str, Any]] = []
    for cid in sorted(best):
        row = best[cid]
        src = row["source"]
        control = best_control(row["missing_controls"])
        topic = f"{row.get('claim_head')} — re-scoped: {control}"
        rationale = (
            f"Distilled (deterministically, no LLM) from a "
            f"{src.get('kind')} {src.get('verdict')} on {cid} by "
            f"{src.get('role')}/{src.get('vendor_or_model')}. Verbatim: "
            f"\"{src.get('verbatim_quote')}\" Named missing controls: "
            + "; ".join(row["missing_controls"])
            + ". status=proposed — a human accepts before this reaches the "
            "idea ledger (D-061: the falsifier annotates, the human is the "
            "generator-of-record)."
        )
        out.append({
            "proposal_id": proposal_id_for(cid),
            "proposed_by": f"distilled:{src.get('kind')}",
            "topic": topic,
            "rationale": rationale,
            "status": "proposed",
            "ts": ts,
            "cluster_id": cid,
            "constraint_id": row.get("constraint_id"),
        })
    return out


def _proposal_rank(row: dict) -> tuple[int, int, str]:
    """Pick-the-best-constraint key for a cluster: a frontier screen
    statement outranks the local redteam, more named controls outranks
    fewer, id breaks ties (determinism)."""
    src = row.get("source") if isinstance(row.get("source"), dict) else {}
    return (1 if src.get("kind") == "frontier_screen" else 0,
            len(row.get("missing_controls") or []),
            str(row.get("constraint_id")))


def _select_proposals(candidates: list[dict], agenda_rows: list[dict],
                      cap: int) -> dict[str, Any]:
    """Filter candidates against the WHOLE existing agenda file — every row,
    including rows minted by earlier runs and by the weekly cron — on both
    the stable proposal_id and the cluster_id. The cluster check is what
    makes the guarantee hold for the four legacy rows whose ids were minted
    under the old topic-hash: a cluster that already has a proposal on the
    agenda is skipped, and the skip is COUNTED, never silent."""
    claimed_ids = {r.get("proposal_id") for r in agenda_rows}
    claimed_clusters = {r["cluster_id"] for r in agenda_rows
                        if isinstance(r.get("cluster_id"), str) and r["cluster_id"]}
    fresh, skipped_clusters = [], []
    for p in candidates:
        if p["proposal_id"] in claimed_ids or p["cluster_id"] in claimed_clusters:
            skipped_clusters.append(p["cluster_id"])
            continue
        fresh.append(p)
    withheld = max(len(fresh) - cap, 0)
    return {"proposals": fresh[:cap], "withheld": withheld,
            "already_present": len(skipped_clusters),
            "skipped_clusters": skipped_clusters}


def propose(constraints: list[dict], *,
            agenda_path: str | Path = DEFAULT_AGENDA,
            cap: int = PROPOSALS_CAP,
            dry_run: bool = False,
            lock_path: str | Path | None = None,
            lock_wait_s: float = AGENDA_LOCK_WAIT_S) -> dict[str, Any]:
    """Append `status: proposed` follow-ups to the frontier agenda (unless
    dry_run). Idempotent per CLUSTER across runs; capped per run with the
    withheld count REPORTED, never silently dropped.

    The read-filter-append is done under the same flock the installed weekly
    cron takes (`run_state/.frontier-agenda-cron.lock`), and the agenda is
    re-read INSIDE the lock so a proposal the cron appended while we waited
    is still seen."""
    candidates = proposals_from_constraints(constraints, _now_utc_iso())
    if dry_run:
        res = _select_proposals(candidates, _read_jsonl(agenda_path), cap)
        res["lock_timeout"] = False
        log.info("constraint_distill: %d proposal(s) would be appended, %d "
                 "already on the agenda, %d withheld by the per-run cap "
                 "(dry-run, nothing written)", len(res["proposals"]),
                 res["already_present"], res["withheld"])
        return res
    lock = Path(lock_path) if lock_path else _agenda_lock_path(agenda_path)
    with _agenda_lock(lock, lock_wait_s) as acquired:
        if not acquired:
            log.error("constraint_distill: agenda lock %s still held after "
                      "%.0fs (the weekly frontier-agenda cron is running) — "
                      "REFUSING to append unlocked. %d proposal(s) not "
                      "written; re-run when the cron finishes.",
                      lock, lock_wait_s, len(candidates))
            return {"proposals": [], "withheld": 0, "already_present": 0,
                    "skipped_clusters": [], "lock_timeout": True}
        res = _select_proposals(candidates, _read_jsonl(agenda_path), cap)
        res["lock_timeout"] = False
        if res["proposals"]:
            _append_rows(agenda_path, res["proposals"])
    log.info("constraint_distill: %d proposal(s) appended, %d already on the "
             "agenda, %d withheld by the per-run cap", len(res["proposals"]),
             res["already_present"], res["withheld"])
    return res


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(name)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(
        description="Distill frontier-screen and redteam verdicts into "
                    "memory/design_constraints.jsonl (deterministic, no LLM).")
    p.add_argument("--once", action="store_true",
                   help="Run one distillation pass over the real stores.")
    p.add_argument("--propose", action="store_true",
                   help="Also append status=proposed follow-ups (one per "
                        "vetoed cluster that named a missing control) to "
                        "memory/frontier_agenda.jsonl.")
    p.add_argument("--rebuild", action="store_true",
                   help="REWRITE memory/design_constraints.jsonl from the "
                        "current extractor instead of appending. The store "
                        "is a derived artifact (see distill.__doc__); the "
                        "frontier agenda is NOT and is never rewritten.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be written; write nothing.")
    p.add_argument("--screen", default=str(DEFAULT_SCREEN))
    p.add_argument("--loop-memory", default=str(DEFAULT_LOOP_MEMORY))
    p.add_argument("--surfaced", default=str(DEFAULT_SURFACED))
    p.add_argument("--constraints", default=str(DEFAULT_CONSTRAINTS))
    p.add_argument("--agenda", default=str(DEFAULT_AGENDA))
    args = p.parse_args(argv)
    if not args.once:
        p.print_help(sys.stderr)
        return 2

    # Every store the pass touches comes from an argument — a fully
    # overridden run reads and writes NO real store (it used to fall through
    # to memory/surfaced_findings.jsonl regardless of --screen/--agenda).
    out = distill(screen_path=args.screen, loop_memory_path=args.loop_memory,
                  surfaced_path=args.surfaced,
                  constraints_path=args.constraints, dry_run=args.dry_run,
                  rebuild=args.rebuild)
    print(f"constraints: {len(out['written'])} "
          f"{'rebuilt (replaced ' + str(out['replaced']) + ')' if out['rebuilt'] else 'new'}, "
          f"{out['skipped']} skipped; "
          f"by flaw_class: {json.dumps(out['by_flaw_class'], sort_keys=True)}")
    if args.propose:
        # Propose over the FULL active store, not just this run's new rows:
        # a cluster distilled yesterday still deserves its follow-up.
        active = out["written"] if args.dry_run else load_active(args.constraints)
        res = propose(active, agenda_path=args.agenda, dry_run=args.dry_run)
        for row in res["proposals"]:
            print(json.dumps(row, ensure_ascii=False))
        if res.get("lock_timeout"):
            print("proposals: REFUSED — the agenda lock is held by the weekly "
                  "frontier-agenda cron; nothing was written.", file=sys.stderr)
            return 1
        print(f"proposals: {len(res['proposals'])} appended, "
              f"{res['already_present']} skipped (cluster already on the "
              f"agenda), {res['withheld']} withheld by the per-run cap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
