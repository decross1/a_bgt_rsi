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
    assert out["totals"] == {"unverifiable": 0, "uningested": 0, "partial": 0}, out["candidates"]
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

# --- title identity: review claude-58cad93a58e0b3af, amendments 1 and 2 -------------
#
# The rule these tests pin is IDENTITY, not containment. The previous block tested
# MIN_STORE_TITLE / MIN_COVERAGE floors, and the review measured the class they let
# through: against the live store, appending a qualifier to a real title verified it
# ("Communication as Voting in LLM Agents" returned a real arXiv id), and the last four
# words of a real title verified as if it were a title. Oracle reproduced both against the
# live store before rewriting this file: see the LIVE-STORE CASE at the bottom, which is
# the only case here that reads run_state/ (read-only).
#
# Each guard gets its OWN mutation pin. That was finding 3: at d04de85 deleting either
# floor alone left 16/16 green, so the two guards were tested jointly and pinned never.

SHORT = "Fair prophets"                       # 13 normalized chars, like the live store's
LONG = "Fair prophets and the cost of calibration in forecasting markets"
COLONISED = "Cursed rationalizability: a new benchmark"


def titles_store(*rows: tuple[dict, dict] | dict):
    """A PaperStore built from titles only — the unit level of resolve_title().

    A bare dict is one paper. A (paper, paper) pair puts two rows for ONE paper object in
    the store, which is how the live ingestion stores the same paper in several files;
    resolve_title() counts candidates by paper, so that shape must stay VERIFIED rather
    than look ambiguous."""
    titles = []
    for row in rows:
        if isinstance(row, tuple):
            paper, _again = row
            titles.extend([(cs.normalize(str(paper["title"])), paper)] * 2)
        else:
            titles.append((cs.normalize(str(row["title"])), row))
    store = cs.PaperStore.__new__(cs.PaperStore)
    store.papers = [p for _t, p in titles]
    store.titles = titles
    return store


def verdict(chunk: str, *papers: dict):
    """(status, arxiv_id, kind) for one cited chunk."""
    status, paper, kind = titles_store(*papers).resolve_title(chunk)
    return status, (paper or {}).get("arxiv_id"), kind


QUALIFIED = ["{} in LLM agents", "{}: a new benchmark", "{} revisited"]


@pytest.mark.parametrize("shape", QUALIFIED)
def test_a_real_title_with_a_qualifier_added_is_partial_never_verified(shape):
    """Amendment 2, first three refusals. This is the invention shape a candidate set is
    most likely to produce, and at d04de85 it verified."""
    cited = shape.format(SHORT)
    status, arxiv_id, _ = verdict(cited, {"title": SHORT, "arxiv_id": "2609.22222"})
    assert status == "PARTIAL", f"{cited!r} resolved as {status}"
    assert arxiv_id == "2609.22222", "a PARTIAL must carry its candidate for adjudication"


def test_a_real_title_with_a_qualifier_is_partial_even_when_the_store_is_shaped_like_live():
    """The same refusal across a store holding titles from 13 to 60 characters, so the
    rule is not an artefact of one short title (amendment 2's store requirement). The
    truncated titles are distinct strings and none contains another, so each probe has
    exactly one candidate and the assertion is about the qualifier, not about ambiguity."""
    shapes = [SHORT, "Communication as voting", "Auctions as experiments",
              "Cursed rationalizability", "Envy freeness and the price of anarchy",
              "Second-best gains from trade in matching markets",
              "Calibration and the geometry of belief"]
    lengths = [len(cs.normalize(s)) for s in shapes]
    assert min(lengths) >= 13 and max(lengths) <= 60, lengths
    assert len({cs.normalize(s) for s in shapes}) == len(shapes)
    # no shape may sit inside another, or a probe would have two candidates and come back
    # ambiguous for a reason that has nothing to do with the qualifier under test
    for a in shapes:
        na = cs.normalize(a)
        for b in shapes:
            nb = cs.normalize(b)
            assert not (na in nb and na != nb), f"{a!r} sits inside {b!r}"
    papers = [{"title": t, "arxiv_id": f"2609.3{n:04d}"} for n, t in enumerate(shapes, start=1)]
    for n, paper in enumerate(papers, start=1):
        assert len(cs.normalize(paper["title"])) in range(13, 61), paper["title"]
        for shape in QUALIFIED:
            cited = shape.format(paper["title"])
            status, carried, _ = verdict(cited, *papers)
            assert status == "PARTIAL", f"{cited!r} -> {status} against a live-shaped store"
            assert carried == paper["arxiv_id"], f"{cited!r} carried the wrong candidate"

def test_a_colon_inside_a_cited_title_does_not_split_it_in_two():
    """Amendment 1's named trap: 'Cursed Rationalizability: A New Benchmark' must NOT
    verify against the stored 'Cursed Rationalizability'. Splitting the cited chunk on
    ':' — the obvious way to strip a subtitle — is exactly what reopens this."""
    assert verdict(COLONISED, {"title": "Cursed rationalizability", "arxiv_id": "1"})[0] == "PARTIAL"
    # and the full title, when the store holds it, resolves normally:
    assert verdict(COLONISED, {"title": COLONISED, "arxiv_id": "2"})[0] == "VERIFIED"


def test_a_fragment_of_a_long_title_is_partial_never_verified():
    """Amendment 2's fourth refusal, its own specimen: a generic phrase long enough to
    clear the old 20-char floor, taken out of a real title."""
    status, arxiv_id, _ = verdict("Trade in Matching Markets",
                                  {"title": "Second-best gains from trade in matching markets",
                                   "arxiv_id": "2609.44444"})
    assert status == "PARTIAL", "a 25-char fragment verified a citation through the old floor"
    assert arxiv_id == "2609.44444"


def test_a_citation_prefixed_with_author_and_year_resolves_at_any_title_length():
    """Amendment 2's two VERIFIED cases. The strip must fire on both the comma and the
    colon form, or the screen refuses correct citations and a screen that cries wolf
    gets ignored."""
    for form in ("Jones 2030, Auctions as Experiments", "Jones 2030: Auctions as Experiments"):
        status, arxiv_id, kind = verdict(form, {"title": "Auctions as experiments",
                                               "arxiv_id": "2609.55555"})
        assert status == "VERIFIED", f"{form!r} did not resolve: {status}"
        assert arxiv_id == "2609.55555" and kind == "exact"


def test_an_et_al_prefix_and_venue_parenthetical_are_stripped_but_a_colon_is_not():
    """The three pieces of citation furniture, separated: what comes off (a prefix naming
    a year or et al, a trailing venue/arXiv parenthetical, quote and emphasis markers)
    and what stays (a colon inside the title)."""
    paper = {"title": "Communication as voting", "arxiv_id": "2609.66666"}
    for form in ['Jones et al., 2020: "Communication as Voting" (NeurIPS 2024)',
                 "*Communication as voting* (arXiv:2505.14639)",
                 "Smith 2021. Communication as voting."]:
        assert verdict(form, paper)[0] == "VERIFIED", form
    assert verdict("Jones et al., 2020: Communication as voting in groups", paper)[0] == "PARTIAL"


def test_an_absent_title_is_unverifiable():
    assert verdict("An invented study of nothing at all",
                   {"title": SHORT, "arxiv_id": "1"})[0] == "UNVERIFIABLE"


def test_an_ambiguous_partial_is_not_resolved_to_the_longest_match():
    """Two distinct stored titles matching one cited phrase is a question the screen
    cannot answer, so it is UNVERIFIABLE with no paper rather than a pick (the first
    version took the longest). Ambiguity is asserted on both arms: exact, and partial."""
    cited = "calibration in forecasting markets"
    long_a = "Fair prophets and the cost of calibration in forecasting markets"
    long_b = "Very justified envy: calibration in forecasting markets after the fact"
    for stored in (long_a, long_b):
        assert cs.normalize(cited) in cs.normalize(stored), stored   # setup, not a guess
    assert verdict(cited, {"title": long_a, "arxiv_id": "1"},
                   {"title": long_b, "arxiv_id": "2"})[0] == "UNVERIFIABLE"
    assert verdict(cited, {"title": long_a, "arxiv_id": "1"})[0] == "PARTIAL"
    # one exact and two partial matches at once: the exact hit wins, as it must, and the
    # assertion that pins the ambiguity guard is the partial-only case two lines above
    assert verdict(cited, {"title": cited, "arxiv_id": "3"},
                   {"title": cited + " in retrospect", "arxiv_id": "4"},
                   {"title": cited + " after the fact", "arxiv_id": "5"}) == ("VERIFIED", "3", "exact")


def test_a_title_stored_twice_is_one_candidate_not_an_ambiguity():
    """The live ingestion re-reads one paper into several files: at this review all 350
    distinct titles in the live store appear 2 to 8 times across its 1,356 rows. Rows are
    counted by paper, so a re-read paper stays VERIFIED instead of looking ambiguous."""
    twice = {"title": LONG, "arxiv_id": "2609.22223"}
    assert verdict(LONG, (twice, twice)) == ("VERIFIED", "2609.22223", "exact")


def test_the_screen_reports_partial_end_to_end_and_blocks_on_it(tmp_path):
    """screen() carries the new status: a qualified-title line is PARTIAL, it lands in
    residual_gaps, and the run exits nonzero — a PARTIAL is adjudicated, never passed."""
    set_path = tmp_path / "CANDIDATES.md"
    set_path.write_text("# Thesis candidates\n\n## Candidate: One\n\n**Prior work:**\n"
                        f"- {SHORT} in LLM agents\n- {SHORT}\n")
    root = tmp_path / "store"
    root.mkdir()
    (root / "papers.jsonl").write_text(json.dumps({"title": SHORT, "arxiv_id": "2609.22222"}) + "\n")
    out = cs.screen(set_path, cs.PaperStore(root).load())
    statuses = sorted(w["status"] for w in out["candidates"][0]["works"])
    assert statuses == ["PARTIAL", "VERIFIED"], out["candidates"]
    assert out["totals"]["partial"] == 1 and out["totals"]["unverifiable"] == 0
    assert "partial_citations_need_adjudication" in out["residual_gaps"]


# --- mutation pins: one per guard, so no guard is carried by another -----------------

MUTATIONS = {
    "identity": ("lambda stored: stored == norm)", "lambda stored: stored == norm or stored in norm)"),
    "prefix_strip": ('text = AUTHOR_YEAR_PREFIX.sub("", text, count=1).strip()', "pass"),
    "paren_strip": ('text = TRAILING_PAREN.sub("", text).strip()', "pass"),
    "colon_not_split": ('return normalize(text)',
                        'return normalize(text.split(":")[0])'),
    "ambiguity": ("if len(partial) == 1:", "if partial:"),
}


@pytest.mark.parametrize("guard", sorted(MUTATIONS))
def test_each_stripping_and_identity_guard_is_pinned_by_its_own_mutation(guard):
    """Finding 3: at d04de85 two guards shared one test, so deleting either alone left the
    suite green. Each mutation is applied in a copy of this worktree and must turn this
    file red — checked by running pytest, not by asserting about it."""
    old, new = MUTATIONS[guard]
    source = (ROOT / "tools/citation_screen.py").read_text()
    assert source.count(old) == 1, f"{guard}: pattern not found exactly once, the pin is stale"
    work = ROOT / f".mut_cs_{guard}"
    if work.exists():
        import shutil
        shutil.rmtree(work)
    work.mkdir()
    shutil_copytree(work)
    (work / "tools/citation_screen.py").write_text(source.replace(old, new))
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/test_citation_screen.py",
                           "-k", "partial or verified or fragment or colon or prefix or absent or ambiguous",
                           "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=work, capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0, (
        f"removing the {guard} guard left the suite green: the guard is not pinned\n{proc.stdout[-800:]}")


def shutil_copytree(work: Path) -> None:
    """Copy just what the mutated run needs: tools/ and this test file."""
    import shutil
    (work / "tools").mkdir()
    for name in ("__init__.py", "citation_screen.py"):
        src = ROOT / "tools" / name
        if src.exists():
            shutil.copy(src, work / "tools" / name)
    (work / "tests").mkdir()
    shutil.copy(ROOT / "tests/test_citation_screen.py", work / "tests/test_citation_screen.py")


def test_the_containment_floors_stay_deleted():
    """The floors this review replaced must not come back by a merge conflict resolution:
    MIN_STORE_TITLE and MIN_COVERAGE are precisely the rule that verified a qualified
    title, and a partial reintroduction would read as a fix."""
    source = (ROOT / "tools/citation_screen.py").read_text()
    for gone in ("MIN_STORE_TITLE =", "MIN_COVERAGE =", "MIN_CITED_TITLE ="):
        assert gone not in source, f"{gone} is back; claude-58cad93a58e0b3af replaced it"


@pytest.mark.parametrize("shape", QUALIFIED)
def test_a_qualified_title_is_refused_against_the_live_store(shape):
    """The review's material findings, against the store the screen will actually read,
    read-only. Reproduced at d04de85 before the rewrite: 'Communication as Voting in LLM
    Agents' returned 2505.14639, and 'Auctions as Experiments revisited' resolved.

    The outcome there is usually UNVERIFIABLE rather than PARTIAL, and reporting that
    honestly is the point: on the live store a short title also sits inside longer stored
    titles, so more than one candidate matches and the screen refuses to pick. What is
    asserted is the property that matters — a qualified title never VERIFIED, and never
    handed back VERIFIED with the real paper's id the way it was at d04de85. Titles are
    read out of the store rather than hard-coded so the case cannot rot."""
    store = cs.PaperStore(cs._main_lab_root() / "run_state/arxiv_ingestion").load()
    checked = 0
    for stored in sorted({t for t, _ in store.titles if t and 13 <= len(t) <= 30}):
        real = store.resolve_title(stored)
        if real[0] != "VERIFIED":
            continue  # a store whose exact title is ambiguous is not this test's subject
        status, paper, kind = store.resolve_title(shape.format(real[1]["title"]))
        assert status != "VERIFIED", f"{stored!r} + qualifier verified as {kind}"
        # a PARTIAL that carries this paper is a lead, which is what PARTIAL is for; what
        # must never happen again is a qualified title returning VERIFIED with the id.
        if status == "UNVERIFIABLE":
            assert paper is None, f"{stored!r}: UNVERIFIABLE must not carry a paper"
        checked += 1
    assert checked >= 10, f"only {checked} live short titles exercised; store shape changed"


@pytest.mark.skipif(not (cs._main_lab_root() / "run_state/arxiv_ingestion").is_dir(),
                    reason="no live paper store on this machine")
def test_real_citations_still_resolve_against_the_live_store():
    """The other side of the same coin: the screen must keep accepting correct citations,
    or it gets ignored. Two live arXiv ids are cited the way a candidate set cites them —
    with an author/year prefix and a venue parenthetical — and must still VERIFIED to
    their own paper. Measured against the live store at this commit."""
    store = cs.PaperStore(cs._main_lab_root() / "run_state/arxiv_ingestion").load()
    real_titles = sorted({t for t, _ in store.titles if t})
    checked = 0
    for stored in real_titles:
        paper = store.resolve_title(stored)
        if paper[0] != "VERIFIED":
            continue
        arxiv_id = paper[1].get("arxiv_id")
        if not arxiv_id:
            continue
        for form in (f"Jones 2030: {stored}", f"Jones et al., 2020, {stored} (arXiv:{arxiv_id})",
                     f"*{stored}*"):
            status, hit, kind = store.resolve_title(form)
            assert status == "VERIFIED" and hit["arxiv_id"] == arxiv_id, (
                f"a correct citation of a real paper did not resolve: {form!r} -> {status}/{kind}")
        checked += 1
        if checked >= 25:
            break
    assert checked >= 10, f"only {checked} live papers exercised; store shape changed"


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
