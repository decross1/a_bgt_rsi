"""Tests for workers.constraint_distill.

Every fixture reasoning below is VERBATIM from the live stores — the
frontier screen (`run_state/frontier_cluster_screen.jsonl`, 2026-08-15
window) and a redteam fatal-flaw critique from `memory/loop_memory.jsonl`.
Extraction tuned on paraphrases would be extraction tuned on nothing.

All paths are explicit tmp paths: this suite adds zero rows to the live
memory/ or run_state/ stores (D-048). No LLM is involved at any point —
the module is deterministic by construction.
"""
import fcntl
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from workers import constraint_distill as cd


# --- verbatim fixtures ------------------------------------------------------

# cl-iter-2026-06-05-002, methods_reviewer / claude, verdict "veto".
REAL_METHODS_VETO = (
    "The record contains no experimental evidence at all (experiment_outcome "
    "is null); the only cited support is a novelty check and a "
    "non-contradiction literature scan, neither of which can support a causal "
    "mechanism claim. The claim asserts a specific driver — imitation-based "
    "signal propagation outpacing horizon-induced decay — but no controls "
    "exist to separate this from the cheaper confound that LLM agents "
    "converge on the payoff-dominant action because 'stag'-style cooperation "
    "is salient in the model's pretraining prior, independent of network "
    "structure. Missing controls include a well-mixed or complete-graph "
    "baseline, an ablation removing neighbor observability (which would "
    "eliminate imitation while leaving the prior intact), a fixed-horizon vs. "
    "unknown-horizon comparison to establish that backward-induction pressure "
    "was ever operative, and any sample size or randomization over seeds/ring "
    "positions."
)

# cl-iter-2026-05-27-002, novelty_reviewer / codex, verdict "veto".
REAL_NOVELTY_VETO = (
    "In a symmetric 2x2 coordination game, the risk-dominant action is "
    "precisely the strict best response to a uniform belief over the "
    "opponent's two actions. The claimed increasing-frequency pattern is "
    "therefore a weaker simulation-level restatement of the standard "
    "risk-dominance/basin-of-attraction result, not a distinct network result."
)

# iter-2026-06-05-006, redteam fatal_flaw (local Gemma).
REAL_REDTEAM_CRITIQUE = (
    "The statement is a reported observation (a data point), not a testable "
    "hypothesis. It lacks a predictive relationship between variables and "
    "cannot be falsified because it describes a past result rather than a "
    "proposed mechanism or effect."
)


def _screen_row(cluster_id="cl-iter-2026-06-05-002"):
    return {
        "ts": "2026-08-15T06:39:39.990011+00:00",
        "cluster_id": cluster_id,
        "evidence_level": "L0",
        "screen": {
            "verdict": "veto",
            "methods": {
                "verdict": "veto", "reasoning": REAL_METHODS_VETO,
                "role": "methods_reviewer", "vendor": "claude",
                "parse_ok": True,
            },
            "novelty": {
                "verdict": "veto", "reasoning": REAL_NOVELTY_VETO,
                "role": "novelty_reviewer", "vendor": "codex",
                "parse_ok": True,
            },
        },
    }


def _memory_row(iteration_id="iter-2026-06-05-002",
                text="The convergence of LLM agents to the payoff-dominant "
                     "equilibrium in a ring-network stag-hunt is driven by "
                     "local imitation-based learning."):
    return {"iteration_id": iteration_id, "hypothesis": {"text": text},
            "ended_at": "2026-06-05T04:00:00Z", "redteam": None}


def _redteam_row(iteration_id="iter-2026-06-05-006"):
    return {
        "iteration_id": iteration_id,
        "hypothesis": {"text": "Experiment exp006_mechanism_design reports "
                               "designer_mean_efficiency = 0.71."},
        "ended_at": "2026-06-05T05:00:00Z",
        "redteam": {"verdict": "fatal_flaw", "critique": REAL_REDTEAM_CRITIQUE,
                    "subagent_backend": "vllm-gemma",
                    "subagent_model": "gemma-4-26b-a4b"},
    }


def _write(path: Path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def stores(tmp_path):
    """Screen + loop-memory + empty output stores, all under tmp_path."""
    screen = tmp_path / "frontier_cluster_screen.jsonl"
    memory = tmp_path / "loop_memory.jsonl"
    surfaced = tmp_path / "surfaced_findings.jsonl"
    _write(screen, [_screen_row()])
    _write(memory, [_memory_row(), _redteam_row()])
    _write(surfaced, [])
    return {
        "screen_path": screen, "loop_memory_path": memory,
        "surfaced_path": surfaced,
        "constraints_path": tmp_path / "design_constraints.jsonl",
    }


# --- extraction -------------------------------------------------------------

def test_extraction_names_the_controls_the_reviewer_named():
    controls = cd.extract_missing_controls(REAL_METHODS_VETO)
    joined = " | ".join(controls).lower()
    assert "well-mixed or complete-graph baseline" in joined
    assert "ablation removing neighbor observability" in joined
    assert "unknown-horizon comparison" in joined
    assert "sample size or randomization" in joined
    # Fragments are verbatim-derived, never invented prose.
    for frag in controls:
        assert frag.strip(" .") in " ".join(REAL_METHODS_VETO.split())


def test_extraction_is_conservative_when_no_control_is_named():
    # A prior-work veto names no control — the quote still carries the
    # knowledge, but nothing is manufactured.
    assert cd.extract_missing_controls(REAL_NOVELTY_VETO) == []
    assert cd.extract_missing_controls(REAL_REDTEAM_CRITIQUE) == []
    assert cd.extract_missing_controls("") == []
    assert cd.extract_missing_controls(None) == []


def test_extraction_drops_vague_and_relative_fragments():
    text = ("No such controls, measurements, or even a defined collusion "
            "metric are present, which is the minimal control the claim "
            "silently depends on.")
    for frag in cd.extract_missing_controls(text):
        assert not frag.lower().startswith("which")
        assert frag.lower() != "such controls"


# --- flaw_class rules -------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    (REAL_METHODS_VETO, "missing_control"),
    (REAL_NOVELTY_VETO, "prior_exists"),
    (REAL_REDTEAM_CRITIQUE, "unfalsifiable"),
    ("The hypothesis conflates the baseline (bounded rationality) with the "
     "proposed cause (cognitive load), making it logically circular.",
     "category_error"),
    ("The stated mechanism is insufficient to produce the claimed effect, "
     "leaving the effect's sign underdetermined.", "mechanism_underdetermined"),
    ("experiment_outcome is null and the record cites nothing else.",
     "no_evidence"),
    ("The wording of the third sentence is awkward.", "other"),
])
def test_flaw_class_keyword_rules(text, expected):
    flaw, _all = cd.classify_flaw(text)
    assert flaw == expected
    assert flaw in cd.FLAW_CLASSES


def test_flaw_class_all_keeps_every_reading():
    flaw, all_flaws = cd.classify_flaw(REAL_METHODS_VETO)
    assert flaw == all_flaws[0] == "missing_control"
    # The same text is ALSO a no-evidence complaint; the single label does
    # not hide that (inviolate rule 4).
    assert "no_evidence" in all_flaws


# --- row shape + idempotency ------------------------------------------------

def test_distill_writes_provenance_tagged_rows(stores):
    out = cd.distill(**stores)
    rows = [json.loads(l) for l in stores["constraints_path"].read_text().splitlines()]
    assert len(rows) == len(out["written"]) == 3   # 2 screen roles + 1 redteam
    kinds = {r["source"]["kind"] for r in rows}
    assert kinds == {"frontier_screen", "redteam"}
    methods = next(r for r in rows if r["source"]["role"] == "methods_reviewer")
    assert methods["constraint_id"].startswith("dc-")
    assert methods["cluster_id"] == "cl-iter-2026-06-05-002"
    assert methods["status"] == "active"
    assert methods["flaw_class"] == "missing_control"
    assert methods["source"]["vendor_or_model"] == "claude"
    assert methods["source"]["verdict"] == "veto"
    quote = methods["source"]["verbatim_quote"]
    assert len(quote) <= cd.QUOTE_MAX
    # Verbatim modulo the budget truncation; extraction still ran on the FULL
    # reasoning, so controls named past char 600 survive in missing_controls.
    assert " ".join(REAL_METHODS_VETO.split()).startswith(quote.rstrip("…"))
    assert any("complete-graph baseline" in c for c in methods["missing_controls"])
    assert methods["claim_head"].startswith("The convergence of LLM agents")
    redteam = next(r for r in rows if r["source"]["kind"] == "redteam")
    assert redteam["source"]["vendor_or_model"] == "gemma-4-26b-a4b"
    assert redteam["source"]["verdict"] == "fatal_flaw"
    assert redteam["missing_controls"] == []


def test_distill_is_idempotent(stores):
    first = cd.distill(**stores)
    second = cd.distill(**stores)
    assert len(first["written"]) == 3
    assert second["written"] == []
    assert second["skipped"] == 3
    rows = stores["constraints_path"].read_text().strip().splitlines()
    assert len(rows) == 3


def test_dry_run_writes_nothing(stores):
    out = cd.distill(dry_run=True, **stores)
    assert len(out["written"]) == 3
    assert not stores["constraints_path"].exists()


def test_redteam_proceed_rows_are_not_distilled(tmp_path, stores):
    proceed = _memory_row("iter-2026-06-07-001")
    proceed["redteam"] = {"verdict": "proceed", "critique": "Looks fine.",
                          "subagent_model": "gemma-4-26b-a4b"}
    _write(stores["loop_memory_path"], [_memory_row(), _redteam_row(), proceed])
    out = cd.distill(**stores)
    assert all(r["cluster_id"] != "cl-iter-2026-06-07-001" for r in out["written"])


def test_pass_verdicts_are_not_distilled(stores):
    row = _screen_row()
    row["screen"]["novelty"]["verdict"] = "pass"
    _write(stores["screen_path"], [row])
    out = cd.distill(**stores)
    roles = {r["source"]["role"] for r in out["written"]}
    assert "novelty_reviewer" not in roles


def test_cross_run_review_earns_its_own_row(stores):
    row = _screen_row()
    row["screen"]["methods"]["cross_run"] = {
        "verdict": "veto", "reasoning": "No matched-history control isolates "
        "longer-term payoff memory from improved instruction following.",
        "role": "methods_reviewer", "vendor": "codex"}
    _write(stores["screen_path"], [row])
    out = cd.distill(**stores)
    vendors = {(r["source"]["role"], r["source"]["vendor_or_model"])
               for r in out["written"] if r["source"]["kind"] == "frontier_screen"}
    assert ("methods_reviewer", "claude") in vendors
    assert ("methods_reviewer", "codex") in vendors


# --- proposals --------------------------------------------------------------

def test_proposal_shape_and_provenance(stores, tmp_path):
    out = cd.distill(**stores)
    agenda = tmp_path / "frontier_agenda.jsonl"
    res = cd.propose(out["written"], agenda_path=agenda)
    assert len(res["proposals"]) == 1        # one per vetoed cluster
    p = res["proposals"][0]
    assert p["proposal_id"].startswith("fa-")
    assert p["proposed_by"] == "distilled:frontier_screen"
    assert p["status"] == "proposed"         # inert until a HUMAN accepts
    assert p["cluster_id"] == "cl-iter-2026-06-05-002"
    assert "— re-scoped:" in p["topic"]
    assert "well-mixed or complete-graph baseline" in p["topic"]
    assert "well-mixed or complete-graph baseline" in p["rationale"]
    # The rationale quotes the veto verbatim, attributed.
    assert "methods_reviewer/claude" in p["rationale"]
    written = [json.loads(l) for l in agenda.read_text().splitlines()]
    assert written == res["proposals"]


def test_proposals_are_idempotent_and_dry_runnable(stores, tmp_path):
    out = cd.distill(**stores)
    agenda = tmp_path / "frontier_agenda.jsonl"
    cd.propose(out["written"], agenda_path=agenda)
    again = cd.propose(out["written"], agenda_path=agenda)
    assert again["proposals"] == []
    assert again["already_present"] == 1
    fresh_agenda = tmp_path / "other_agenda.jsonl"
    dry = cd.propose(out["written"], agenda_path=fresh_agenda, dry_run=True)
    assert len(dry["proposals"]) == 1
    assert not fresh_agenda.exists()


def test_no_proposal_without_a_named_runnable_control(stores):
    """A prior-exists / unfalsifiable kill names no control — proposing an
    experiment there would be generation, which this module never does."""
    out = cd.distill(**stores)
    novelty = [r for r in out["written"] if r["source"]["role"] == "novelty_reviewer"]
    redteam = [r for r in out["written"] if r["source"]["kind"] == "redteam"]
    assert cd.proposals_from_constraints(novelty + redteam, "2026-08-19T00:00:00Z") == []


def test_inconclusive_alone_never_proposes(stores):
    row = _screen_row()
    row["screen"]["methods"]["verdict"] = "inconclusive"
    row["screen"]["novelty"]["verdict"] = "inconclusive"
    _write(stores["screen_path"], [row])
    out = cd.distill(**stores)
    # The knowledge is still recorded, honestly labelled...
    assert any(r["source"]["verdict"] == "inconclusive" for r in out["written"])
    # ...but only a blocking verdict earns a follow-up proposal.
    assert cd.proposals_from_constraints(out["written"], "2026-08-19T00:00:00Z") == []


def test_proposal_cap_reports_the_withheld_remainder(stores, tmp_path):
    out = cd.distill(**stores)
    base = next(r for r in out["written"] if r["flaw_class"] == "missing_control")
    many = []
    for i in range(4):
        clone = json.loads(json.dumps(base))
        clone["cluster_id"] = f"cl-iter-2026-06-05-{i:03d}"
        clone["constraint_id"] = f"dc-clone{i}"
        many.append(clone)
    res = cd.propose(many, agenda_path=tmp_path / "agenda.jsonl", cap=2)
    assert len(res["proposals"]) == 2
    assert res["withheld"] == 2


# --- conditioning projection (read by meta_review behind the DARK gate) -----

def test_conditioning_bullets_match_topic_and_are_labelled(stores):
    cd.distill(**stores)
    bullets = cd.conditioning_bullets(
        "ring network stag hunt convergence imitation",
        stores["constraints_path"])
    assert bullets
    assert all(b.startswith("[constraint from ") for b in bullets)
    assert any("missing controls named:" in b for b in bullets)
    assert len(bullets) <= cd.CONDITION_CAP


def test_conditioning_bullets_never_pad_off_topic(stores):
    cd.distill(**stores)
    assert cd.conditioning_bullets("differential privacy accountant tightness",
                                   stores["constraints_path"]) == []
    assert cd.conditioning_bullets("", stores["constraints_path"]) == []


def test_conditioning_ignores_non_active_rows(stores):
    cd.distill(**stores)
    rows = [json.loads(l) for l in
            stores["constraints_path"].read_text().splitlines()]
    for r in rows:
        r["status"] = "retired"
    _write(stores["constraints_path"], rows)
    assert cd.conditioning_bullets("ring network stag hunt imitation",
                                   stores["constraints_path"]) == []


def test_missing_stores_degrade_to_empty(tmp_path):
    out = cd.distill(screen_path=tmp_path / "nope.jsonl",
                     loop_memory_path=tmp_path / "nope2.jsonl",
                     surfaced_path=tmp_path / "nope3.jsonl",
                     constraints_path=tmp_path / "out.jsonl")
    assert out["written"] == [] and out["skipped"] == 0
    assert not (tmp_path / "out.jsonl").exists()


def test_cli_requires_once(capsys, tmp_path):
    assert cd.main([]) == 2


# === B2 — missing_controls must name a RUNNABLE DESIGN OBJECT ===============
#
# Every string below is VERBATIM from memory/design_constraints.jsonl as the
# pre-fix extractor wrote it (2026-08-19, 112 rows / 50 fragments). The bug:
# `_CONTROL_RE` fired on the mere words comparator / comparison / control, so
# a COMPLAINT about the claim was stored as a control the loop should run —
# including the exact string docs/veto_elevation.md holds up as what must be
# REJECTED. docs/veto_elevation.md §"Which vetoes become research questions"
# is the spec these pin.

LIVE_COMPLAINT_FRAGMENTS = [
    # named in the fix brief
    "The claim mischaracterizes its own comparator",
    "the claim silently depends on missing controls",
    "The term 'non-equilibrium markets' is too vague to serve as a "
    "controlled baseline",
    # the rest of the live pollution, in store order
    "its soundness hinges on controls that cannot be checked from what is given",
    "controls for which component drives the prediction",
    "sample size that do not exist in the record",
    "not a comparison of composition bounds",
    "The hypothesis conflates the baseline (bounded rationality) with the "
    "proposed cause (cognitive load)",
    "making the comparison of 'extinction rates' logically confounded",
    "better modeled' is an underspecified metric that lacks a formal "
    "statistical criterion for comparison",
    "making the comparison logically incoherent",
    "static depth' is too ill-defined to serve as a rigorous control "
    "variable against a temporal frequency metric",
    "making the comparison structurally vague",
    "the convergence of control strategies in LQ games is fundamentally "
    "driven by the interaction between system dynamics",
    "failure to represent' is not defined against a mathematical baseline",
    "the comparison is qualitatively vague rather than quantitatively testable",
]

# The genuine frontier controls — these must survive the fix. Narrowing the
# extractor until it rejects complaints AND these would be a fix that broke
# the feature.
LIVE_GENUINE_CONTROLS = [
    "an ablation that varies history length while holding context size fixed",
    "a control where instructions are held constant across window sizes",
    "sample sizes",
    "no matched-history control",
    "external-memory control",
    "payoff-history ablation",
    "sample size",
    "effect size",
    "matched information content between the narrative",
    "matched token length",
    "randomized condition order",
    "a topology baseline",
    "an N-sweep with multiple network realizations",
    "matched signal variance",
    "randomized noise assignment",
    "a non-Bayesian baseline",
    "comparisons of estimated contribution-time slopes across repeated "
    "independent groups",
    "a well-mixed or complete-graph baseline",
    "an ablation removing neighbor observability (which would eliminate "
    "imitation while leaving the prior intact)",
    "a fixed-horizon vs. unknown-horizon comparison to establish that "
    "backward-induction pressure was ever operative",
    "any sample size or randomization over seeds/ring positions",
    "an otherwise-identical randomized comparison of periodic versus "
    "unpredictable audit schedules",
    "a no-audit or matched-audit baseline",
    "an information-theoretic identifiability argument or empirical "
    "reconstruction rate with baselines",
    "control comparing against inference from unperturbed matchings alone",
    "comparison against random perturbations or prior-only inference",
    "essential controls over market structure",
]


@pytest.mark.parametrize("fragment", LIVE_COMPLAINT_FRAGMENTS)
def test_live_complaint_fragments_are_rejected(fragment):
    """A description of the claim's FAULT is not a control. 16 of the 50
    fragments the pre-fix extractor put in the live store were exactly
    that."""
    assert cd.extract_missing_controls(fragment) == []


@pytest.mark.parametrize("fragment", LIVE_GENUINE_CONTROLS)
def test_live_genuine_controls_are_kept(fragment):
    """...and the fix must not buy that by rejecting the real controls."""
    kept = cd.extract_missing_controls(fragment)
    assert len(kept) == 1
    # A leading "no " is the reviewer's marker for "missing", not part of the
    # object ("no matched-history control" names a matched-history control);
    # everything else survives verbatim.
    assert kept[0] in (fragment, fragment.removeprefix("no "))


# The requirement frames the reviewers actually used. The control is the
# TAIL of "<subject> requires/lacks <control>" and the SUBJECT of "no
# <control> is provided/required" — both are kept, stripped down to the
# design object, still verbatim.
@pytest.mark.parametrize("raw,kept", [
    ("Discriminating between those two mechanisms requires at minimum an "
     "ablation that varies history length while holding context size fixed",
     "an ablation that varies history length while holding context size fixed"),
    ("The claim requires at least an otherwise-identical randomized "
     "comparison of periodic versus unpredictable audit schedules",
     "an otherwise-identical randomized comparison of periodic versus "
     "unpredictable audit schedules"),
    ("The claim also lacks essential controls over market structure",
     "essential controls over market structure"),
    ("an information-theoretic identifiability argument or empirical "
     "reconstruction rate with baselines is required",
     "an information-theoretic identifiability argument or empirical "
     "reconstruction rate with baselines"),
    # This one was stored INVERTED: the source says "no ... effect size IS
    # AVAILABLE to evaluate"; the store said the opposite.
    ("no design, sample size, model set, prompt materials, or effect size "
     "is available to evaluate", "effect size"),
])
def test_requirement_frames_are_reduced_to_the_design_object(raw, kept):
    controls = cd.extract_missing_controls(raw)
    assert kept in controls
    for frag in controls:
        assert frag in " ".join(raw.split())      # still verbatim


# cl-iter-2026-06-05-005, methods_reviewer / claude, verdict "veto" — VERBATIM.
REAL_RDP_VETO = (
    "The claim mischaracterizes its own comparator: RDP composition is not "
    "'additive composition of epsilon-privacy parameters' (that describes "
    "basic/strong composition); RDP composes additively in Renyi divergence, "
    "and Mironov (2017) showed the moments accountant is essentially an "
    "instance of RDP accounting, so the claimed tightness advantage over RDP "
    "rests on a category error rather than a real mechanism. Moreover, the "
    "supporting evidence is incapable of bearing on the claim: the retrieval "
    "surfaced only game-theory/market-microstructure papers, and the "
    "'survives' verdict reflects absence of relevant documents, not a "
    "comparison of composition bounds. No numerical or analytical comparison "
    "of (epsilon, delta) curves under matched noise/subsampling settings is "
    "provided, which is the minimal control the claim silently depends on."
)


def test_parenthesised_tuple_is_never_split_into_shards():
    """Clause-splitting inside "(epsilon, delta)" produced two mangled live
    fragments. Bracket-aware splitting keeps the design object whole."""
    controls = cd.extract_missing_controls(REAL_RDP_VETO)
    assert ("numerical or analytical comparison of (epsilon, delta) curves "
            "under matched noise/subsampling settings") in controls
    assert "numerical or analytical comparison of" not in controls
    assert ("delta) curves under matched noise/subsampling settings is "
            "provided") not in controls
    # ...and the sentence the reviewer opened with is still a complaint.
    assert "The claim mischaracterizes its own comparator" not in controls


def test_redteam_critiques_name_no_runnable_control(stores):
    """All ten live redteam rows that carried a "control" carried a
    complaint. A fatal-flaw critique argues; it does not design."""
    for text in ("The hypothesis presents a false dichotomy; the convergence "
                 "of control strategies in LQ games is fundamentally driven "
                 "by the interaction between system dynamics and estimation "
                 "error.",
                 "The term 'non-equilibrium markets' is too vague to serve as "
                 "a controlled baseline for the claimed effect.",
                 "'better modeled' is an underspecified metric that lacks a "
                 "formal statistical criterion for comparison."):
        assert cd.extract_missing_controls(text) == []


# === B1 — ONE proposal per cluster, ACROSS runs =============================

def _missing_control_row(cluster_id="cl-iter-2026-05-26-008",
                         head="Longer context windows raise cooperation.",
                         controls=("a well-mixed or complete-graph baseline",)):
    return {
        "constraint_id": "dc-" + cluster_id[-4:], "ts": "2026-08-19T00:00:00Z",
        "cluster_id": cluster_id, "claim_head": head,
        "flaw_class": "missing_control", "flaw_class_all": ["missing_control"],
        "missing_controls": list(controls),
        "source": {"kind": "frontier_screen", "role": "methods_reviewer",
                   "vendor_or_model": "claude", "verdict": "veto",
                   "verbatim_quote": "Missing controls include a well-mixed "
                                     "or complete-graph baseline."},
        "status": "active",
    }


def test_proposal_id_is_stable_under_control_drift(tmp_path):
    """A re-screen that names MORE controls changes which control ranks best
    and therefore the rendered topic — it must not mint a second proposal
    for the same cluster (live double-mint, cl-iter-2026-05-26-008)."""
    agenda = tmp_path / "agenda.jsonl"
    first = cd.propose([_missing_control_row()], agenda_path=agenda)
    assert len(first["proposals"]) == 1
    rescreened = _missing_control_row(controls=(
        "a payoff-history ablation",
        "an otherwise-identical randomized comparison of audit schedules",
        "a well-mixed or complete-graph baseline"))
    second = cd.propose([rescreened], agenda_path=agenda)
    assert second["proposals"] == []
    assert second["already_present"] == 1
    assert second["skipped_clusters"] == ["cl-iter-2026-05-26-008"]
    assert len(agenda.read_text().strip().splitlines()) == 1


def test_proposal_id_is_stable_under_claim_head_drift(tmp_path):
    """claim_head drift ALONE minted a second proposal live: a later-surfaced
    finding routinely overrides the loop_memory hypothesis as the head."""
    agenda = tmp_path / "agenda.jsonl"
    cd.propose([_missing_control_row(head="hypothesis text from loop_memory")],
               agenda_path=agenda)
    again = cd.propose(
        [_missing_control_row(head="the surfaced finding's claim, which is "
                                   "a different sentence entirely")],
        agenda_path=agenda)
    assert again["proposals"] == []
    assert again["already_present"] == 1
    assert len(agenda.read_text().strip().splitlines()) == 1


def test_dedupe_sees_rows_minted_by_earlier_runs_and_by_the_cron(tmp_path):
    """The check is against the EXISTING agenda FILE, all rows — including a
    legacy row whose proposal_id was minted under the old topic hash, and a
    row the weekly cron wrote."""
    agenda = tmp_path / "agenda.jsonl"
    _write(agenda, [
        {"proposal_id": "fa-4453269d",      # legacy id: hash of an old topic
         "proposed_by": "distilled:frontier_screen", "status": "proposed",
         "cluster_id": "cl-iter-2026-05-26-008", "topic": "old rendering",
         "ts": "2026-08-19T00:00:00Z"},
        {"proposal_id": "fa-0e162a7c",      # weekly cron, no cluster_id
         "proposed_by": "frontier:codex", "status": "proposed",
         "topic": "Constraint-conditioned mechanism ideation",
         "ts": "2026-08-17T00:00:00Z"},
    ])
    res = cd.propose([_missing_control_row()], agenda_path=agenda)
    assert res["proposals"] == []
    assert res["already_present"] == 1
    assert len(agenda.read_text().strip().splitlines()) == 2   # nothing added


def test_proposal_id_depends_only_on_the_cluster():
    assert (cd.proposal_id_for("cl-iter-2026-05-26-008")
            == cd.proposal_id_for("cl-iter-2026-05-26-008"))
    assert (cd.proposal_id_for("cl-iter-2026-05-26-008")
            != cd.proposal_id_for("cl-iter-2026-05-26-009"))


# === NB1 — the agenda append takes the weekly cron's lock ==================

def test_agenda_append_is_flock_guarded(tmp_path):
    """cron/weekly-frontier-agenda.sh (installed, 30 5 * * 0) flocks this
    file for its whole pass and then appends to the same agenda. A blocked
    --propose REFUSES and reports it; it never writes unlocked."""
    agenda = tmp_path / "agenda.jsonl"
    lock = tmp_path / "agenda.lock"
    holder = lock.open("w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        res = cd.propose([_missing_control_row()], agenda_path=agenda,
                         lock_path=lock, lock_wait_s=0.2)
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()
    assert res["lock_timeout"] is True
    assert res["proposals"] == []
    assert not agenda.exists()          # nothing was interleaved
    # Lock released -> the same call now writes.
    ok = cd.propose([_missing_control_row()], agenda_path=agenda,
                    lock_path=lock, lock_wait_s=0.2)
    assert len(ok["proposals"]) == 1 and ok["lock_timeout"] is False


def test_real_agenda_uses_the_cron_lock_file():
    """Not a sibling lock — the SAME file cron/weekly-frontier-agenda.sh
    holds, or the two writers never contend."""
    assert cd._agenda_lock_path(cd.DEFAULT_AGENDA) == cd.AGENDA_LOCK
    assert cd.AGENDA_LOCK.name == ".frontier-agenda-cron.lock"
    assert cd._agenda_lock_path("/tmp/other.jsonl") == Path("/tmp/other.jsonl.lock")


# === NB2 — a fully overridden CLI run touches NO real store ================

def test_cli_overrides_are_hermetic(tmp_path, monkeypatch):
    """--screen/--loop-memory/--surfaced/--constraints/--agenda together must
    redirect EVERY store. surfaced_path was not threaded through, so an
    overridden run still read memory/surfaced_findings.jsonl."""
    _write(tmp_path / "screen.jsonl", [_screen_row()])
    _write(tmp_path / "memory.jsonl", [_memory_row(), _redteam_row()])
    _write(tmp_path / "surfaced.jsonl", [])

    touched: list[Path] = []
    for name in ("_read_jsonl", "_append_rows", "_rewrite_rows"):
        original = getattr(cd, name)

        def spy(path, *a, _o=original, **kw):
            touched.append(Path(path).resolve())
            return _o(path, *a, **kw)

        monkeypatch.setattr(cd, name, spy)
    original_lock = cd._agenda_lock

    def lock_spy(path, wait_s):
        touched.append(Path(path).resolve())
        return original_lock(path, wait_s)

    monkeypatch.setattr(cd, "_agenda_lock", lock_spy)

    real = [cd.DEFAULT_SCREEN, cd.DEFAULT_LOOP_MEMORY, cd.DEFAULT_SURFACED,
            cd.DEFAULT_CONSTRAINTS, cd.DEFAULT_AGENDA, cd.AGENDA_LOCK]
    before = [(p, p.stat().st_mtime_ns if p.exists() else None) for p in real]

    assert cd.main(["--once", "--propose",
                    "--screen", str(tmp_path / "screen.jsonl"),
                    "--loop-memory", str(tmp_path / "memory.jsonl"),
                    "--surfaced", str(tmp_path / "surfaced.jsonl"),
                    "--constraints", str(tmp_path / "constraints.jsonl"),
                    "--agenda", str(tmp_path / "agenda.jsonl")]) == 0

    assert touched, "the spies never fired — the test proves nothing"
    for path in touched:
        assert tmp_path in path.parents, f"escaped the sandbox: {path}"
    for path, mtime in before:
        assert (path.stat().st_mtime_ns if path.exists() else None) == mtime


# === NB3 — constraint_id hashes the FULL reasoning ========================

def test_two_reasonings_sharing_a_600_char_prefix_do_not_collide(stores):
    """The id used to hash the already-truncated quote, so a same
    cluster/kind/role/vendor pair sharing a 600-char prefix collided and the
    second row was silently dropped as "already distilled"."""
    prefix = ("The record contains no experimental evidence for this claim "
              "and the reviewer therefore cannot evaluate it. ") * 6
    assert len(prefix) > cd.QUOTE_MAX
    row_a, row_b = _screen_row(), _screen_row("cl-iter-2026-06-05-002")
    row_a["screen"]["methods"]["reasoning"] = prefix + "Missing: a well-mixed baseline."
    row_b["screen"]["methods"]["reasoning"] = prefix + "Missing: a matched-history control."
    row_b["screen"].pop("novelty")
    _write(stores["screen_path"], [row_a, row_b])
    out = cd.distill(**stores)
    methods = [r for r in out["written"]
               if r["source"]["role"] == "methods_reviewer"]
    assert len(methods) == 2
    assert len({r["constraint_id"] for r in methods}) == 2
    # The truncated quotes really are identical — the old key's collision.
    assert (methods[0]["source"]["verbatim_quote"]
            == methods[1]["source"]["verbatim_quote"])
    # ...and the distinguishing text survives where it matters.
    assert {tuple(r["missing_controls"]) for r in methods} == {
        ("a well-mixed baseline",), ("a matched-history control",)}


# === --rebuild — the derived store is regenerated, not patched =============

def test_rebuild_rewrites_the_derived_store_and_carries_the_old_id(stores):
    cd.distill(**stores)
    rows = [json.loads(l) for l in
            stores["constraints_path"].read_text().splitlines()]
    stale = dict(rows[0], constraint_id="dc-stale00",
                 missing_controls=["The claim mischaracterizes its own comparator"])
    _write(stores["constraints_path"], rows + [stale])
    assert len(stores["constraints_path"].read_text().strip().splitlines()) == 4

    out = cd.distill(rebuild=True, **stores)
    rebuilt = [json.loads(l) for l in
               stores["constraints_path"].read_text().splitlines()]
    assert out["rebuilt"] is True and out["replaced"] == 4
    assert len(rebuilt) == len(out["written"]) == 3      # the stale row is gone
    assert all("The claim mischaracterizes its own comparator"
               not in (r["missing_controls"] or []) for r in rebuilt)
    # The row whose id moved carries the id an agenda row may still cite.
    moved = [r for r in rebuilt if r.get("legacy_constraint_id")]
    assert [r["legacy_constraint_id"] for r in moved] == ["dc-stale00"]


def test_rebuild_never_touches_the_agenda(stores, tmp_path):
    """frontier_agenda.jsonl is append-only: it records human-facing
    proposals and their lifecycle, not a derived projection."""
    agenda = tmp_path / "agenda.jsonl"
    out = cd.distill(**stores)
    cd.propose(out["written"], agenda_path=agenda)
    before = agenda.read_text()
    cd.distill(rebuild=True, **stores)
    assert agenda.read_text() == before


def test_rebuild_dry_run_writes_nothing(stores):
    cd.distill(**stores)
    before = stores["constraints_path"].read_text()
    out = cd.distill(rebuild=True, dry_run=True, **stores)
    assert out["written"] and stores["constraints_path"].read_text() == before


def test_quote_coverage_flag_is_honest_in_both_directions():
    """Provenance self-verification (integrator, 2026-08-19). 11 of 33 live
    fragments sit past the 600-char quote budget — present in the source,
    absent from the row's own excerpt. The budget is NOT stretched to hide
    that (it is a real budget); the row states whether its excerpt is
    sufficient, so an auditor knows when to open the source ledger."""
    from workers import constraint_distill as cd
    far = ("Preamble. " + ("filler sentence to burn the quote budget. " * 20)
           + "The design requires a well-mixed baseline to separate effects.")
    row = cd._constraint("cl-x", "h", "frontier_screen", "methods_reviewer",
                         "claude", "veto", far, "2026-08-19T00:00:00Z")
    assert row["missing_controls"], "fixture must extract a control"
    assert row["source"]["quote_covers_controls"] is False
    assert len(row["source"]["verbatim_quote"]) <= cd.QUOTE_MAX

    near = "The claim requires a well-mixed baseline. " + ("tail. " * 5)
    row2 = cd._constraint("cl-y", "h", "frontier_screen", "methods_reviewer",
                          "claude", "veto", near, "2026-08-19T00:00:00Z")
    assert row2["source"]["quote_covers_controls"] is True
    assert row2["source"]["verbatim_quote"] == cd._flat(near, cd.QUOTE_MAX)
