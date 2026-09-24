"""Tests for tools/citation_screen.py — plan 2026-09-24 work phase, G1.1 screen gate.

Why this exists: review claude-5dea097dd434208a amendment 3 says the G1.1 screen note
"must check that every Prior-work citation resolves, by arXiv id or in the lab paper
store. The structure test cannot catch invented citations." d1's precheck receipt is
already burned and the lane caps its acceptance test at 8 KiB, so the check runs as a
tool at screen time; this file is its test, in Oracle's lane, where there is no cap.

Every case is hermetic: the store and the candidate set are tmp files. The discrimination
canary (retro fix SKILL 5, cause factual_error) is test_a_clean_set_passes_a_mutated_set_fails,
which proves the screen is not vacuous by mutating a passing set four ways.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import citation_screen as cs  # noqa: E402

PAPERS = [
    {"title": "Order effects in judgment under uncertainty", "arxiv_id": "2609.11111",
     "authors": ["A. Person"], "category": "cs.GT", "citation_count": 3,
     "publication_date": "2026-09-01", "abstract": "…", "semantic_scholar_id": "None"},
    {"title": "Quantum probability models of cognition: a review", "arxiv_id": "2609.11112",
     "authors": ["B. Person"], "category": "q-fin.GN", "citation_count": 0,
     "publication_date": "2026-09-02", "abstract": "…", "semantic_scholar_id": "None"},
    {"title": "Counter-picking strategies in imperfect information games", "arxiv_id": "2609.11113",
     "authors": ["C. Person"], "category": "cs.MA", "citation_count": 1,
     "publication_date": "2026-09-03", "abstract": "…", "semantic_scholar_id": "None"},
]


def write_store(tmp_path: Path) -> Path:
    root = tmp_path / "arxiv_ingestion"
    (root / "runs" / "daily").mkdir(parents=True)
    cache = root / "cache"
    cache.mkdir()
    (cache / "a.jsonl").write_text("".join(json.dumps(p) + "\n" for p in PAPERS[:2]))
    run = [{"schema": "arxiv-daily-run/v1", "run_id": "daily"}] + PAPERS[2:]
    (root / "runs" / "daily" / "papers.jsonl").write_text("".join(json.dumps(r) + "\n" for r in run))
    return root


def candidate(name: str, prior: str) -> str:
    return f"""## Candidate: {name}

**Question and mechanism:** does belief order change the answer.

**Prior work:**
- {prior}
"""


CLEAN = (
    candidate("One", "Order effects in judgment under uncertainty (arXiv:2609.11111)")
    + candidate("Two", "Quantum probability models of cognition: a review")
    + candidate("Three", "Counter-picking strategies in imperfect information games (arXiv 2609.11112)")
)


def make(tmp_path: Path, text: str) -> Path:
    store = tmp_path / "store"
    store.mkdir()
    (tmp_path / "papers.jsonl").write_text("".join(json.dumps(p) + "\n" for p in PAPERS))
    set_path = tmp_path / "CANDIDATES.md"
    set_path.write_text("# Thesis candidates\n\n" + text)
    return set_path


def report(tmp_path: Path, text: str) -> dict:
    store_root = write_store(tmp_path)
    return cs.screen(make(tmp_path, CLEAN if text is None else text), cs.PaperStore(store_root).load())


def test_store_reads_both_ingestion_shapes(tmp_path):
    store = cs.PaperStore(write_store(tmp_path)).load()
    assert len(store.papers) == 3, "two from the cache file, one from the run's papers.jsonl"
    assert store.find_arxiv("2609.11112")["title"].startswith("Quantum probability")
    assert store.find_arxiv("2609.11113v2"), "a version suffix must still resolve"
    assert store.find_arxiv("2609.99999") is None


def test_a_clean_set_resolves_every_citation(tmp_path):
    out = report(tmp_path, None)
    assert len(out["candidates"]) == 3
    assert out["totals"] == {"unverifiable": 0, "uningested": 0}, out["candidates"]
    assert out["residual_gaps"] == []
    assert out["set_sha256"], "the note must be able to cite the bytes it screened"


@pytest.mark.parametrize("mutated,expect", [
    ("## Candidate: One\n\n**Prior work:**\n- Anchoring in LLM confidence calibration\n", "unverifiable"),
    ("## Candidate: One\n\n**Prior work:**\n- Order effects in judgment (arXiv:2609.99999)\n", "uningested"),
])
def test_a_mutation_turns_the_screen_red(tmp_path, mutated, expect):
    text = CLEAN.replace(CLEAN.split("## Candidate: Two")[0], mutated)
    out = report(tmp_path, text)
    assert out["totals"][expect] >= 1, "the screen must not pass an invented citation"
    assert out["residual_gaps"], "a residual gap must be named, not implied"


def test_prose_alone_is_not_a_citation_source(tmp_path):
    """A paper named only in another candidate's prose does not make it verified."""
    text = CLEAN.replace("Counter-picking strategies in imperfect information games (arXiv 2609.11112)",
                         "Store title quoted in prose: Counter-picking strategies in imperfect information games")
    out = report(tmp_path, text)
    assert out["totals"]["unverifiable"] == 0, out["candidates"]


def test_field_labels_are_the_only_lines_screened(tmp_path):
    """Falsifier/anomaly prose must not be matched as a citation — no false UNVERIFIABLE."""
    text = CLEAN + """## Candidate: Four

**Question and mechanism:** a mechanism.

**Prior work:**
- Order effects in judgment under uncertainty

**Falsifier:** if the exact Bayesian posterior already reproduces the effect there is nothing left.
"""
    out = report(tmp_path, text)
    assert out["totals"]["unverifiable"] == 0, out["candidates"][-1]["works"]


def test_table_row_prior_work_is_read(tmp_path):
    text = """| Field | Content |
|---|---|
| Title | Belief order effects |
| Prior work | Quantum probability models of cognition: a review |
"""
    out = report(tmp_path, "## Candidate: Five\n\n" + text)
    assert out["totals"]["unverifiable"] == 0, out["candidates"]


def test_main_reports_and_exits_nonzero_on_a_gap(tmp_path, capsys):
    store_root = write_store(tmp_path)
    set_path = make(tmp_path, CLEAN.replace("Order effects in judgment under uncertainty (arXiv:2609.11111)",
                                            "A study the lab has never heard of"))
    code = cs.main(["--set", str(set_path), "--store", str(store_root), "--json"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 1 and printed["totals"]["unverifiable"] == 1
    assert cs.main(["--set", str(tmp_path / "nowhere.md"), "--store", str(store_root)]) == 2


def test_missing_store_is_refused_not_silently_passing(tmp_path, capsys):
    set_path = make(tmp_path, CLEAN)
    empty = tmp_path / "empty_store"
    empty.mkdir()
    assert cs.main(["--set", str(set_path), "--store", str(empty)]) == 2
    assert "no papers" in capsys.readouterr().err


# ── the invented-citation hole the containment rule used to open ──────────────
# Review claude-56275cf790bac03c, finding 4 and amendment 6. `stored in norm` had no
# floor, so a stored title of ANY length that appeared inside a cited line verified it.
# The live store holds short titles ("communication as voting", "auctions as
# experiments", "fair prophets"), so an invented sentence that merely mentions one of
# them passed the screen - which is the exact case the screen exists to catch.

SHORT = "Fair prophets"                       # 11 normalized chars, like the live store's
LONG = "Fair prophets and the cost of calibration in forecasting markets"


def short_store(tmp_path: Path) -> Path:
    """A store holding one SHORT title plus one long one, like the live store's shape."""
    root = tmp_path / "store"
    root.mkdir()
    papers = [{"title": SHORT, "arxiv_id": "2609.22222"},
              {"title": LONG, "arxiv_id": "2609.22223"}]
    (root / "papers.jsonl").write_text("".join(json.dumps(p) + "\n" for p in papers))
    return root


def find(text: str, *papers: dict):
    store = cs.PaperStore.__new__(cs.PaperStore)
    store.papers = list(papers)
    store.titles = [(cs.normalize(str(p["title"])), p) for p in papers]
    return store.find_title(text)


def test_a_short_stored_title_inside_a_longer_invented_citation_does_not_verify_it():
    """The meta-oracle's repro, at the unit level: a short real title inside an invented
    sentence must not VERIFY it."""
    invented = "Smith 2031: An invented study of fair prophets among LLM forecasters"
    assert find(invented, {"title": SHORT, "arxiv_id": "2609.22222"}) is None, (
        "a stored title shorter than the cited chunk verified an invented citation")
    # and a short title never certifies a longer sentence, however plausible it reads:
    # below MIN_STORE_TITLE there is no fragment match in either direction
    assert find(SHORT + ": a survey", {"title": SHORT, "arxiv_id": "2609.22222"}) is None


def test_an_exact_short_title_still_resolves():
    assert find(SHORT, {"title": SHORT, "arxiv_id": "2609.22222"})["arxiv_id"] == "2609.22222"
    assert find(LONG, {"title": LONG, "arxiv_id": "2609.22223"})["arxiv_id"] == "2609.22223"


def test_a_two_word_guess_does_not_match_a_long_stored_title():
    """The other direction keeps its floor: an abbreviation this short is a guess."""
    assert find("fair prophets", {"title": LONG, "arxiv_id": "2609.22223"}) is None


def test_a_title_stored_twice_is_one_candidate_not_an_ambiguity():
    """The live ingestion re-reads a paper into several files: 1,134 rows at this commit
    carry 305 distinct normalized titles. Rows must not be read as distinct candidates,
    or every ingested paper would come back ambiguous."""
    twice = {"title": LONG, "arxiv_id": "2609.22223"}
    assert find(LONG, twice, dict(twice))["arxiv_id"] == "2609.22223"


def test_two_different_matching_titles_are_not_resolved_silently():
    """Two distinct stored titles both matching one cited phrase is a question the screen
    cannot answer, so it reports UNVERIFIABLE rather than picking one (the first version
    of find_title picked the longest). The case is written at find_title's own rule -
    `norm in stored`, the citation abbreviates a real title - and the setup asserts that
    both titles really match, so a future edit that makes them stop matching cannot turn
    this into a passing test that tests nothing."""
    cited = "calibration in forecasting markets"          # 30 chars, clears MIN_CITED_TITLE
    long_a = "Fair prophets and the cost of calibration in forecasting markets"
    long_b = "Very justified envy: calibration in forecasting markets after the fact"
    assert cs.MIN_CITED_TITLE <= len(cs.normalize(cited))
    for stored in (long_a, long_b):
        assert cs.normalize(cited) in cs.normalize(stored), stored
    assert find(cited, {"title": long_a, "arxiv_id": "1"},
                {"title": long_b, "arxiv_id": "2"}) is None
    # with the rival removed the same phrase resolves, so ambiguity is the reason
    assert find(cited, {"title": long_a, "arxiv_id": "1"})["arxiv_id"] == "1"


def test_the_screen_refuses_the_short_title_invention_end_to_end(tmp_path):
    """The same defect through screen(), not just find_title(): the invented line must be
    UNVERIFIABLE and the run must exit nonzero, since that is the report the note cites."""
    set_path = tmp_path / "CANDIDATES.md"
    set_path.write_text(
        "# Thesis candidates\n\n## Candidate: One\n\n**Prior work:**\n"
        "- Smith 2031: An invented study of fair prophets among LLM forecasters\n")
    out = cs.screen(set_path, cs.PaperStore(short_store(tmp_path)).load())
    assert out["totals"]["unverifiable"] == 1, out["candidates"]
    assert out["residual_gaps"]


def test_main_lab_root_follows_git_and_falls_back_to_root(tmp_path, monkeypatch):
    """run_state/ is absent from a worktree, so the store must resolve to the main working
    tree, and the resolution must not depend on a directory shape. Two arms (review
    claude-56275cf790bac03c, amendment 6, second half):

    * outside any repository - here, a scratch path with no git in it - git answers with
      nothing usable and the function returns ROOT. That is the safe direction: an empty
      store is refused with exit 2, never read as "no paper matched".
    * inside a linked worktree, git's common dir names the main working tree, whatever
      depth the worktree happens to sit at. `ROOT.parent.parent / "a_bgt_rsi"` was only
      right for a checkout two levels below projects/, and `git worktree add` puts precheck
      and Nara worktrees wherever the caller pointed them.

    The repo path is passed to `git init` rather than made with cwd=..., because macOS
    hands back a symlinks-resolved /private/tmp path that git then prints, and the
    comparison below is about identity, not spelling."""
    scratch = tmp_path / "deep" / "nest" / "of" / "worktree"
    scratch.mkdir(parents=True)
    monkeypatch.setattr(cs, "ROOT", scratch)
    assert cs._main_lab_root() == scratch, "outside a repository the fallback must be ROOT"

    main = tmp_path / "lab"
    (main / "run_state").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True)
    subprocess.run(["git", "-C", str(main), "commit", "-q", "--allow-empty", "-m", "init"],
                   env={**__import__("os").environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}, check=True)
    linked = tmp_path / "somewhere" / "else" / "nested" / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "--detach", str(linked), "HEAD"], check=True)
    monkeypatch.setattr(cs, "ROOT", linked)
    resolved = cs._main_lab_root()
    assert resolved == main or resolved.resolve() == main.resolve(), (
        f"a linked worktree resolved the store to {resolved}, not the main working tree {main}")
