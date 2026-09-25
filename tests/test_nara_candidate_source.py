"""Red-first acceptance contract for the raw G1.1 Nara candidate source."""

import hashlib
import json
import re
import stat
from pathlib import Path


OUTPUT = Path("notes/nara_candidates.json")
SCHEMA = "nara-thesis-candidate-source/v1"
SET_ID = "g11-information-beliefs-r2-20260925"
IDENTITY = re.compile(r"[a-z0-9][a-z0-9-]{2,95}\Z")
LENSES = {"behavioral_economics", "quantum_information", "strategic_games"}
SOURCES = {
    "docs/v2/THESIS_BRIEF_2026-09-23.md": "f1bea860949a7e4430af20425446331c2ba72652dd2c718aafd32684b5291a58",
    "notes/research/2026-09-25-c1-source-disposition/DISPOSITION.md": "567e5a64e28c419e2504f37b0ba29d035e0b7c4530ce667c8c768a759a3d06c1",
    "notes/research/2026-09-25-c1-neighbor-prior-art/C1_EXACT_CLAIM_MATRIX.md": "0e5c86e6277b613b689b2ac83352771d4c3868288ff0e83444630c279b6db3f0",
    "notes/research/2026-09-24-t-gate-choice/T_GATE_CHOICE.md": "1766b07ac41d6d4141817ebdf84e9be9254562a6a86450e456ec296d85a30708",
    "notes/research/2026-09-24-t-gate-choice/C3_PRIOR_ART_MATRIX.md": "24f16a4d6563cf783f96241488faab9fa82d2129336483ce443182ded1875f9b",
    "notes/research/2026-09-25-c3-payoff-screen/C3_IDENTITY_ADAPTER_SCREEN.md": "b1590271b33f335a44b0b0f241d0293056c38fd11ec2a93c04e02a6b6b1e79d7",
    "notes/research/2026-09-15-flash-and-applied-research/PIPELINE_AUDIT.md": "dd56604c48d249efab53858a1e21fc5c730d72c4717bbc588f480e87a3bf4b14",
    "notes/research/2026-09-15-flash-and-applied-research/TRADING_RESEARCH_PLAN.md": "028cc4f8bf2718b0735b5f41f695f19198fd8a4808b9a53c12e61c9f8406f161",
    "experiments/exp007_polymarket/notes.md": "25428fd8ba53085c4dffb0fd8ad5a59fb62ee372f318042b3e5ff8c04f2ad6a4",
}
BANNED_KEYS = {
    "winner", "rank", "ranking", "focus", "focus_id", "chosen_candidate_id",
    "selection_reason", "execution_authorized", "scientific_credit",
}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"duplicate JSON key: {key}"
        result[key] = value
    return result


def _constant(value):
    raise AssertionError(f"non-finite JSON value: {value}")


def _exact(value, fields, label):
    assert isinstance(value, dict) and set(value) == fields, f"invalid {label} fields"


def _text(value, label, maximum=1800):
    assert isinstance(value, str) and value.strip() and len(value) <= maximum, f"invalid {label}"


def _identity(value, label):
    assert isinstance(value, str) and IDENTITY.fullmatch(value), f"invalid {label}"


def _walk(value):
    if isinstance(value, dict):
        assert not (set(value) & BANNED_KEYS), "raw source contains a selection or authority field"
        for item in value.values():
            _walk(item)
    elif isinstance(value, list):
        for item in value:
            _walk(item)


def _prior(value):
    _exact(value, {"status", "summary", "sources"}, "prior_work")
    assert value["status"] in {"verified", "unknown", "contradicted"}
    _text(value["summary"], "prior_work summary")
    sources = value["sources"]
    assert isinstance(sources, list) and 1 <= len(sources) <= 12, "candidate is not source-bound"
    for source in sources:
        _exact(source, {"locator", "claim", "source_path", "source_sha256"}, "prior source")
        _text(source["locator"], "prior locator", 800)
        _text(source["claim"], "prior claim", 1200)
        path = source["source_path"]
        assert path in SOURCES, "prior source is outside the nine declared inputs"
        raw = Path(path).read_bytes()
        expected = SOURCES[path]
        assert hashlib.sha256(raw).hexdigest() == expected, f"base evidence changed: {path}"
        assert source["source_sha256"] == expected, f"unpinned prior source: {path}"
        assert source["locator"].encode("utf-8") in raw, f"locator is not literal in source: {path}"


def _conviction(value):
    probability_fields = {"p_pass_t", "p_pass_s", "p_pass_a", "p_dead_end"}
    _exact(value, probability_fields | {"interest_0_10", "reasons"}, "conviction")
    for key in probability_fields:
        item = value[key]
        assert type(item) in {int, float} and 0 <= item <= 1, f"invalid {key}"
    interest = value["interest_0_10"]
    assert type(interest) in {int, float} and 0 <= interest <= 10, "invalid interest"
    _exact(value["reasons"], probability_fields | {"interest_0_10"}, "conviction reasons")
    for reason in value["reasons"].values():
        _text(reason, "conviction reason", 1200)


def _card(card):
    fields = {
        "candidate_id", "title", "lenses", "mechanism", "theory", "experiment",
        "applied", "prior_work", "anomaly_branches", "estimated_flash_hours", "conviction",
    }
    _exact(card, fields, "candidate")
    _identity(card["candidate_id"], "candidate_id")
    assert len(card["candidate_id"]) <= 89
    _text(card["title"], "title")
    lenses = card["lenses"]
    assert isinstance(lenses, list) and 1 <= len(lenses) <= 3
    assert set(lenses) <= LENSES and len(lenses) == len(set(lenses)), "invalid lenses"
    _text(card["mechanism"], "mechanism")

    theory_fields = {
        "game", "players", "actions", "information_structure", "solution_concept",
        "benchmark", "prediction", "falsifier", "predeclared_decision_rule",
    }
    _exact(card["theory"], theory_fields, "theory")
    for value in card["theory"].values():
        _text(value, "theory value")

    experiment = card["experiment"]
    _exact(experiment, {"benchmark", "arms", "sample_plan", "outcome", "falsifier"}, "experiment")
    for key in ("benchmark", "outcome", "falsifier"):
        _text(experiment[key], f"experiment {key}")
    arms = experiment["arms"]
    assert isinstance(arms, list) and 2 <= len(arms) <= 12
    arm_ids = []
    for arm in arms:
        _exact(arm, {"arm_id", "treatment"}, "experiment arm")
        _identity(arm["arm_id"], "arm_id")
        _text(arm["treatment"], "arm treatment")
        arm_ids.append(arm["arm_id"])
    assert len(arm_ids) == len(set(arm_ids)), "duplicate arm_id"
    sample = experiment["sample_plan"]
    _exact(sample, {"unit", "target_n", "missingness"}, "sample_plan")
    _text(sample["unit"], "sample unit")
    _text(sample["missingness"], "sample missingness")
    assert type(sample["target_n"]) is int and sample["target_n"] >= 1

    applied = card["applied"]
    _exact(applied, {"venue", "data", "as_of", "measurement", "limitation"}, "applied")
    for value in applied.values():
        _text(value, "applied value")
    _prior(card["prior_work"])
    branches = card["anomaly_branches"]
    assert isinstance(branches, list) and 2 <= len(branches) <= 8
    for branch in branches:
        _exact(branch, {"outcome", "next_hypothesis"}, "anomaly branch")
        _text(branch["outcome"], "anomaly outcome")
        _text(branch["next_hypothesis"], "next hypothesis")
    hours = card["estimated_flash_hours"]
    assert type(hours) in {int, float} and 0 < hours <= 24, "invalid estimated_flash_hours"
    _conviction(card["conviction"])


def test_nara_candidate_source():
    info = OUTPUT.lstat()
    assert stat.S_ISREG(info.st_mode), "candidate source must be a regular file"
    assert info.st_size <= 48 * 1024, "candidate source exceeds 48 KiB"
    payload = json.loads(
        OUTPUT.read_bytes(), object_pairs_hook=_pairs, parse_constant=_constant,
    )
    _exact(payload, {"schema_version", "set_id", "candidates"}, "raw source")
    assert payload["schema_version"] == SCHEMA
    assert payload["set_id"] == SET_ID
    candidates = payload["candidates"]
    assert isinstance(candidates, list) and 3 <= len(candidates) <= 5
    for card in candidates:
        _card(card)
    ids = [card["candidate_id"] for card in candidates]
    assert len(ids) == len(set(ids)), "duplicate candidate_id"
    _walk(payload)
