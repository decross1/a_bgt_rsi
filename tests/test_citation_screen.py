"""Tests for tools/citation_screen.py — plan 2026-09-24 work phase, G1.1 screen gate.

Why this exists: review claude-5dea097dd434208a amendment 3 says the G1.1 screen note
"must check that every Prior-work citation resolves, by arXiv id or in the lab paper
store. The structure test cannot catch invented citations." d1's precheck receipt is
already burned and the lane caps its acceptance test at 8 KiB, so the check runs as a
tool at screen time; this file is its test, in Oracle's lane, where there is no cap.

Two cases read the live paper store read-only and skip when it is absent; everything else
is hermetic, with the store and the candidate set as tmp files. The discrimination
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
    + candidate("Three", "Counter-picking strategies in imperfect information games (arXiv:2609.11113)")
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
    assert out["totals"] == {"unverifiable": 0, "uningested": 0, "partial": 0, "mismatch": 0}, out["candidates"]
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


def test_an_author_year_prefix_cannot_swallow_invented_title_text():
    """Review claude-749d39bc3396f628, finding 1 (material). At b30889a the prefix run
    `[^:.)\\n]{0,40}` after the year ate up to 40 characters of *invented* title text, so
    a forgery whose title is qualified verified with the real paper's id — the same class
    as claude-58cad93a58e0b3af amendment 1, entered from the front instead of the back.
    The prefix now ends at the year (or the et-al) plus one separator, so the qualifier
    survives into the title and the citation comes back PARTIAL, never VERIFIED."""
    paper = {"title": "Communication as voting", "arxiv_id": "2609.66666"}
    for forgery in ("Jones 2030, LLM Agents: Communication as Voting",
                    "Smith 2031, A survey of bidding, Auctions as Experiments"):
        status, carried, kind = verdict(forgery, paper,
                                        {"title": "Auctions as experiments",
                                         "arxiv_id": "2609.55555"})
        assert status != "VERIFIED", f"{forgery!r} verified as {kind} — the free-text run is back"
        assert status == "PARTIAL", f"{forgery!r} -> {status}: a real substring must stay a lead"
    # a lowercase name is not citation furniture: only a capped name may be stripped
    assert verdict("jones 2030, Communication as voting", paper)[0] != "VERIFIED"


def test_an_et_al_prefix_and_venue_parenthetical_are_stripped_but_a_colon_is_not():
    """The three pieces of citation furniture, separated: what comes off (a prefix naming
    a year or et al, a trailing venue/arXiv parenthetical, quote and emphasis markers)
    and what stays (a colon inside the title)."""
    paper = {"title": "Communication as voting", "arxiv_id": "2609.66666"}
    for form in ['Jones et al., 2020: "Communication as Voting" (NeurIPS 2024)',
                 "*Communication as voting* (arXiv:2505.14639)",
                 "Smith 2021. Communication as voting.",
                 # review claude-749d39bc3396f628 amendment 1 checked this form against
                 # the live store: the prefix ends at the year, then one separator
                 "Jones et al. (2020). Communication as voting"]:
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
    counted by distinct title, so a re-read paper stays VERIFIED instead of looking
    ambiguous."""
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
    # Review claude-749d39bc3396f628 amendment 1: the author/year prefix must end at the
    # year plus one separator. Restoring the free-text run reopens the seq-113 forgery
    # class from the front, so this pin refuses it independently of prefix_strip.
    "prefix_free_text_run": ('[:.,]\\s*\")', '[^:.)\\n]{0,40}[:.,)]\\s*\")'),
    # Review claude-749d39bc3396f628 amendment 2: emphasis/quote markers become a space.
    "emphasis_to_empty": ('EMPHASIS.sub(" ", chunk or "")', 'EMPHASIS.sub("", chunk or "")'),
}

# The -k expression for the mutated run. `apostrophe` is the emphasis pin's own test:
# deleting the markers instead of spacing them is invisible to the -k set's other names,
# so without this word the guard would ride on another test's pass (finding 3 again).
MUTATION_K = "partial or verified or fragment or colon or prefix or absent or ambiguous or apostrophe"


@pytest.mark.parametrize("guard", sorted(MUTATIONS))
def test_each_stripping_and_identity_guard_is_pinned_by_its_own_mutation(guard, tmp_path):
    """Finding 3: at d04de85 two guards shared one test, so deleting either alone left the
    suite green. Each mutation is applied in a copy under tmp_path and must turn this file
    red — checked by running pytest, not by asserting about it. The copy lives in
    tmp_path, not in the checkout (review claude-749d39bc3396f628, amendment 3): running
    this file at b30889a left five untracked .mut_cs_* directories in the lab root, where
    a later `git add -A` would commit them, and two concurrent runs raced on the rmtree.
    Safe because the -k expression selects no live-store case, so the copy needs neither
    git context nor the live store."""
    old, new = MUTATIONS[guard]
    source = (ROOT / "tools/citation_screen.py").read_text()
    assert source.count(old) == 1, f"{guard}: pattern not found exactly once, the pin is stale"
    work = tmp_path / f"mut_cs_{guard}"
    if work.exists():
        import shutil
        shutil.rmtree(work)
    work.mkdir()
    shutil_copytree(work)
    (work / "tools/citation_screen.py").write_text(source.replace(old, new))
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/test_citation_screen.py",
                           "-k", MUTATION_K,
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


@pytest.mark.skipif(not (cs._main_lab_root() / "run_state/arxiv_ingestion").is_dir(),
                    reason="no live paper store on this machine")
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


def test_a_title_with_an_apostrophe_or_an_underscore_verifies_verbatim():
    """Review claude-749d39bc3396f628, finding 2 (material). normalize() on the stored side
    turns an apostrophe, a quote or an underscore into a space; at b30889a cited_title()
    *deleted* the same characters, so 7 of the live store's 350 distinct titles could never
    verify even when cited word for word — "Approximating Pandora's Knapsack via Simple
    Policies", "Arrow's Impossibility Theorem", "$\\ell_1$ Preferences". The fix is a space
    instead of an empty string; this pins the class hermetically, the raw-title live test
    above pins it against the store."""
    for raw, stored in (
            ("Approximating Pandora's Knapsack via Simple Policies",
             "Approximating Pandora s Knapsack via Simple Policies"),
            ("Approximating Pandora\u2019s Knapsack via Simple Policies",
             "Approximating Pandora s Knapsack via Simple Policies"),
            ("Approximating Pandora's Knapsack via Simple Policies",
             "Approximating Pandora's Knapsack via Simple Policies"),
            ("Arrow's Impossibility Theorem for Social Choice",
             "Arrow's Impossibility Theorem for Social Choice"),
            ("$\\ell_1$ Preferences in Committee Voting",
             "$\\ell_1$ Preferences in Committee Voting"),
            ("*Order effects* in judgment under uncertainty",
             "Order effects in judgment under uncertainty")):
        status, arxiv_id, kind = verdict(raw, {"title": stored, "arxiv_id": "2609.77777"})
        assert status == "VERIFIED", f"{raw!r} -> {status}/{kind}: the cited side must space, not delete"
        assert arxiv_id == "2609.77777"


@pytest.mark.skipif(not (cs._main_lab_root() / "run_state/arxiv_ingestion").is_dir(),
                    reason="no live paper store on this machine")
def test_an_author_year_prefix_forgery_is_refused_against_the_live_store():
    """The review's sweep, as a permanent case. At b30889a 'Jones 2030, LLM Agents: <real
    title>' returned VERIFIED for 350 of 350 distinct live titles; without the free-text
    run, 0 of 350. The same probe over the store the screen will actually read, read-only,
    so the fix cannot rot into a passing unit test over a toy store."""
    store = cs.PaperStore(cs._main_lab_root() / "run_state/arxiv_ingestion").load()
    checked = 0
    for stored in sorted({t for t, _ in store.titles if t}):
        real = store.resolve_title(stored)
        if real[0] != "VERIFIED":
            continue
        for probe in (f"Jones 2030, LLM Agents: {real[1]['title']}",
                      f"Smith 2031, A survey of bidding, {real[1]['title']}"):
            status, _paper, kind = store.resolve_title(probe)
            assert status != "VERIFIED", f"{probe!r} verified as {kind}: the prefix eats titles"
        checked += 1
    assert checked >= 10, f"only {checked} live titles exercised; store shape changed"


@pytest.mark.skipif(not (cs._main_lab_root() / "run_state/arxiv_ingestion").is_dir(),
                    reason="no live paper store on this machine")
def test_real_citations_still_resolve_against_the_live_store():
    """The other side of the same coin: the screen must keep accepting correct citations,
    or it gets ignored. Two live arXiv ids are cited the way a candidate set cites them —
    with an author/year prefix and a venue parenthetical — and must still VERIFIED to
    their own paper. Measured against the live store at this commit."""
    store = cs.PaperStore(cs._main_lab_root() / "run_state/arxiv_ingestion").load()
    # RAW titles, keyed by the raw string so each distinct title is exercised once.
    # Review claude-749d39bc3396f628, finding 2: the version at b30889a iterated the
    # *normalized* titles and `continue`d past anything that failed to verify verbatim,
    # so it could not see the class at all — 7 of 350 raw titles carry an apostrophe or
    # an underscore, and EMPHASIS deleting (rather than spacing) the marker made every
    # one of them UNVERIFIABLE even when quoted exactly. The whole set, not a sample.
    raw: dict[str, dict] = {}
    for _norm, paper in store.titles:
        title = str(paper.get("title") or "").strip()
        if title:
            raw.setdefault(title, paper)
    assert len(raw) >= 10, f"only {len(raw)} raw titles in the live store; shape changed"
    skipped = 0
    for title, paper in sorted(raw.items()):
        arxiv_id = str(paper.get("arxiv_id") or "")
        if store.resolve_title(title)[0] != "VERIFIED" or not arxiv_id:
            skipped += 1   # an ambiguous or id-less row is not this test's subject
            continue
        for form in (title,
                     f"Jones 2030: {title}",
                     f"Jones et al., 2020, {title} (arXiv:{arxiv_id})",
                     f"Jones et al. (2020). {title}",
                     f"*{title}*"):
            status, hit, kind = store.resolve_title(form)
            assert status == "VERIFIED" and hit["arxiv_id"] == arxiv_id, (
                f"a correct citation of a real paper did not resolve: {form!r} -> {status}/{kind}")
    assert len(raw) - skipped >= 10, f"only {len(raw) - skipped} live papers exercised"


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


# --- id + title on one line: review claude-4e67d485544a85df, amendment 3 and finding 1 ---
#
# The measured hole, quoted from the review: at f150a22 a Prior-work line carrying a real
# id and an invented title came out `[INGESTED]` with totals `unverifiable 0 / partial 0 /
# uningested 0`, and the report printed the STORE's title, not the cited one. The bolded
# probe below (id_pair_text, '**Prior work:') covers that shape. The unbolded shape
# ('- Prior work: ...') was NOT covered until review claude-a857cd9b3f5b6c33 (seq 187)
# amendment 1: see test_an_unbolded_prior_work_line_is_screened_not_skipped, which is now
# the test that reproduces the seq 150 probe.

ID_TITLE_K = "id_title"

# Tests that must go red when the id-vs-title check is deleted. Explicit names, because
# `-k id_title` selects on test names and would miss the live-store arm.
MUTATION_NODES = (
    "test_a_real_id_with_an_invented_title_is_a_mismatch_never_ingested",
    "test_a_real_id_with_a_paraphrased_title_is_a_mismatch",
    "test_an_id_and_a_title_from_two_different_stored_papers_is_a_mismatch",
    "test_a_verified_citation_and_a_forgery_in_one_block_cannot_cancel_out",
    "test_main_refuses_a_set_whose_only_gap_is_an_id_title_mismatch",
    "test_a_real_live_id_with_an_invented_title_is_a_mismatch",
)


def id_pair_text(cited: str, arxiv_id: str) -> str:
    """The review's own probe shape: a labelled Prior-work line, an id, a quoted title."""
    return f"## Candidate: Pair\n\n**Prior work:**\n- arXiv:{arxiv_id} \"{cited}\"\n"


def pair_report(tmp_path: Path, cited: str, arxiv_id: str) -> dict:
    return report(tmp_path, id_pair_text(cited, arxiv_id))


def works_of(out: dict) -> list[dict]:
    return out["candidates"][0]["works"]


def write_live_row(tmp_path: Path, row: dict) -> Path:
    """A tmp paper store holding exactly one row taken from the LIVE store.

    The live id+title pairs I want to probe are not in PAPERS, and PAPERS must stay as it
    is: it is the fixture for the three papers every older test screens. So a live probe
    gets its own single-row store. It is still a store the screen built itself from the
    ingestion JSONL shape - nothing here hands the screen a title list.
    """
    root = tmp_path / "live_store"
    (root / "cache").mkdir(parents=True, exist_ok=True)
    (root / "cache" / "live.jsonl").write_text(json.dumps(row) + "\n")
    return root


def live_screen(live_root: Path, tmp_path: Path, probe: str, slug: str = "") -> dict:
    """One probe per file: screen() dedupes cited titles per candidate, so two probes in one
    document would silently drop the second."""
    set_path = tmp_path / f"LIVESET{slug}.md"
    set_path.write_text("# Thesis candidates\n\n## Candidate: Live\n\n**Prior work:**\n"
                        f"- {probe}\n")
    return cs.screen(set_path, cs.PaperStore(live_root).load())


def test_a_real_id_with_an_invented_title_is_a_mismatch_never_ingested(tmp_path):
    """Amendment 3, arm 1: the forgery class, and it must be a residual."""
    out = pair_report(tmp_path, "LLM Agents Always Defect in Public Goods Games", "2609.11111")
    works = works_of(out)
    assert works and works[0]["status"] == "MISMATCH", (
        f"a real id wrapped in an invented title was not refused: "
        f"{[(w['status'], w['cited_title']) for w in works]}")
    assert out["totals"]["mismatch"] >= 1, out["totals"]
    assert "id_title_mismatch_present" in out["residual_gaps"], out["residual_gaps"]
    assert out["totals"]["unverifiable"] == 0, (
        "the forged line must be refused by the id check, not by falling through to the "
        "title search - an unverifiable total could be satisfied by any other bad line")
    assert out["totals"]["partial"] == 0, out["totals"]


def test_a_real_id_with_a_paraphrased_title_is_a_mismatch(tmp_path):
    """The exact error the reading list shipped: '... under Hidden Effort' for the store's
    '... under Moral Hazard and Adverse Selection'. Same shape, live-store pair at the
    next test; here the hermetic equivalent."""
    out = pair_report(tmp_path, "Order effects in judgment under effort", "2609.11111")
    assert works_of(out)[0]["status"] == "MISMATCH", works_of(out)
    assert "id_title_mismatch_present" in out["residual_gaps"]


def test_a_real_id_with_the_exact_title_verifies(tmp_path):
    """Amendment 3: EQUAL means VERIFIED. Citation furniture still comes off first."""
    out = pair_report(tmp_path, "Order effects in judgment under uncertainty", "2609.11111")
    works = works_of(out)
    assert works[0]["status"] == "VERIFIED", works
    assert works[0]["arxiv_id"] == "2609.11111"
    assert out["totals"]["mismatch"] == 0
    assert out["residual_gaps"] == [], out["residual_gaps"]


def test_an_id_and_a_title_from_two_different_stored_papers_is_a_mismatch(tmp_path):
    """Cross-wiring is the sneakiest variant: both halves are real, the pair is not."""
    out = pair_report(tmp_path, "Quantum probability models of cognition: a review",
                      "2609.11113")
    assert works_of(out)[0]["status"] == "MISMATCH", works_of(out)
    assert out["totals"]["mismatch"] >= 1


def test_an_invented_id_with_the_right_title_is_uningested_not_a_clean_pass(tmp_path):
    out = pair_report(tmp_path, "Order effects in judgment under uncertainty", "2609.99999")
    ids = out["candidates"][0]["ids"]
    assert any(i["arxiv_id"] == "2609.99999" and i["status"] == "UNINGESTED" for i in ids), ids
    assert "uningested_ids_present" in out["residual_gaps"], out["residual_gaps"]


def test_an_id_with_no_readable_title_on_the_line_is_never_verified(tmp_path):
    """A line that names an id but whose text strips to nothing cannot be checked, so it
    must not be called VERIFIED. It stays a residual."""
    out = report(tmp_path, "## Candidate: Pair\n\n**Prior work:**\n- arXiv:2609.11111\n")
    assert out["candidates"][0]["ids"][0]["status"] == "INGESTED", out["candidates"][0]["ids"]
    assert out["totals"]["mismatch"] == 0, "a bare id is the id arm's business, not a forgery"
    assert all(w["status"] != "VERIFIED" for w in works_of(out)) or not works_of(out)


def test_a_verified_citation_and_a_forgery_in_one_block_cannot_cancel_out(tmp_path):
    """A screen must not pass a forged citation because another line is clean, and a
    block must not look clean because it also holds one bad line."""
    text = (id_pair_text("Order effects in judgment under uncertainty", "2609.11111")
            + "\n- LLM Agents Always Defect in Public Goods Games (arXiv:2609.11112)\n")
    out = report(tmp_path, text)
    statuses = sorted(w["status"] for w in works_of(out))
    assert "MISMATCH" in statuses, statuses
    assert out["totals"]["mismatch"] == 1, out["totals"]
    assert "id_title_mismatch_present" in out["residual_gaps"]


def test_main_refuses_a_set_whose_only_gap_is_an_id_title_mismatch(tmp_path, capsys):
    """The command the screen note will cite: exit 1 and both titles on the page."""
    set_path = tmp_path / "CANDIDATES.md"
    set_path.write_text("# Thesis candidates\n\n" + id_pair_text(
        "LLM Agents Always Defect in Public Goods Games", "2609.11111"))
    store_root = write_store(tmp_path)
    code = cs.main(["--set", str(set_path), "--store", str(store_root)])
    printed = capsys.readouterr().out
    assert code == 1, f"a forged citation must not exit 0; got {code}"
    assert "MISMATCH" in printed, printed
    assert "cited title:" in printed and "store title:" in printed, (
        "the report must show both sides, or the reader cannot see the forgery")
    assert "Public Goods Games" in printed, "the cited (invented) title must be on the page"


def test_json_report_carries_both_sides_of_a_mismatch(tmp_path):
    set_path = tmp_path / "CANDIDATES.md"
    set_path.write_text("# Thesis candidates\n\n" + id_pair_text(
        "LLM Agents Always Defect in Public Goods Games", "2609.11111"))
    out = cs.screen(set_path, cs.PaperStore(write_store(tmp_path)).load())
    work = works_of(out)[0]
    assert work["cited_title"].startswith("llm agents always defect"), work
    assert "Public Goods" in (work["store_title"] or "") or "public goods" in str(
        work["cited_title"]), work
    assert work["match_kind"] == "id_title_mismatch", work
    assert out["totals"]["mismatch"] == 1


# --- mutation pin: the id-vs-title check must be pinned by its own mutation -----------


def test_removing_the_id_title_check_turns_the_suite_red(tmp_path):
    """Same discipline as the stripping pins above: if the new check is deleted, a test
    must go red. A guard no test can break is a guard that silently rots.

    The mutant is NOT run with `-k id_title`: `-k` matches a test name, not a store id, and
    the live-store test's name does not contain that substring, so a `-k`-filtered mutant
    run would quietly collect one test and pass on it. The filter is an explicit nodeid
    list, and the run asserts it collected more than one test."""
    import shutil
    work = tmp_path / "mut_id_title"
    work.mkdir()
    shutil_copytree(work)
    source = (ROOT / "tools/citation_screen.py").read_text()
    old = '                if carried:'
    assert source.count(old) == 1, "the pin is stale: the id/title branch moved"
    # neuter the check: never take the id arm, so every id+title line falls to title search
    (work / "tools/citation_screen.py").write_text(
        source.replace(old, '                if False:  # MUTANT: id-vs-title check removed'))
    proc = subprocess.run([sys.executable, "-m", "pytest",
                           *[f"tests/test_citation_screen.py::{name}" for name in MUTATION_NODES],
                           "-q", "--no-header", "-p", "no:cacheprovider", "--collect-only"],
                          cwd=work, capture_output=True, text=True, timeout=300)
    collected = len([ln for ln in proc.stdout.splitlines() if "::" in ln])
    assert collected >= 2, f"the pin must exercise more than one arm, collected {collected}"
    proc = subprocess.run([sys.executable, "-m", "pytest",
                           *[f"tests/test_citation_screen.py::{name}" for name in MUTATION_NODES],
                           "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=work, capture_output=True, text=True, timeout=300)
    assert proc.returncode != 0, (
        "deleting the id-vs-title check left the suite green: the check is not pinned\n"
        f"{proc.stdout[-800:]}")


# --- live store: the forgery class measured against the papers the lab really holds ----

@pytest.mark.skipif(not (cs._main_lab_root() / "run_state/arxiv_ingestion").is_dir(),
                    reason="no live paper store on this machine")
def test_a_real_live_id_with_an_invented_title_is_a_mismatch(tmp_path):
    """Amendment 3's requirement, measured against the papers the lab really holds: a real
    id cited under an invented title must be MISMATCH with a nonzero mismatch total, never
    a clean screen and never merely 'a title I could not find'.

    The distinction is the whole content of this test. At f150a22 the same probe was
    already a residual through the title search - `unverifiable 1` - so ANY test that only
    demands a nonzero total was satisfied by the old code and proves nothing about the
    id check. What was missing is the verdict that names the fault: the store holds a
    different title for that exact id. The hermetic twin above asserts the same thing; the
    review measured the behaviour here, so the live arms pin both sides of it."""
    store = cs.PaperStore(cs._main_lab_root() / "run_state/arxiv_ingestion").load()
    # Fixture ids, each one checked into this file's expectation by the assert below: real
    # ids the lab holds, with a title long enough that an invented phrase in place of one of
    # its real phrases cannot resolve by title identity either - so the only arm that can
    # catch arm 2 is the new id-vs-title check. The 2026-09-24 G1.1 reading list is where
    # these came from, which is the point: this is the citation shape d1 will write.
    arxiv_id, real_title = "2609.20404", None
    hit = store.find_arxiv(arxiv_id)
    assert hit is not None, f"live store no longer holds {arxiv_id}; pick another live id"
    real_title = str(hit["title"])
    assert len(cs.cited_title(real_title)) > 40, real_title
    live_root = write_live_row(tmp_path, hit)
    assert store.find_arxiv(arxiv_id) is not None, "fixture must name a live id"

    def works_for(probe: str, slug: str = "") -> tuple[list[dict], dict]:
        out = live_screen(live_root, tmp_path, probe, slug)
        entry = next(i for i in out["candidates"][0]["ids"] if i["arxiv_id"] == arxiv_id)
        assert entry["status"] == "INGESTED", (
            f"{arxiv_id} must resolve in the store the screen reads: {out['store_files']}")
        return works_of(out), out

    # arm 1, amendment 3 verbatim: a live id, an invented title.
    forged, _ = works_for(f'arXiv:{arxiv_id} "LLM Agents Always Defect in Public Goods Games"', "_a")
    assert forged and forged[0]["status"] == "MISMATCH", forged
    assert forged[0]["arxiv_id"] == arxiv_id, forged[0]
    assert cs.cited_title(forged[0]["cited_title"]) == "llm agents always defect in public goods games", forged[0]
    assert cs.cited_title(real_title) == cs.cited_title(forged[0]["store_title"]), (
        "the report must show the store title held for that id")

    # arm 2, amendment 1's real error class: a live title with a real phrase swapped for an
    # invented one, cited beside its own id. This is the error Oracle shipped in seq 149.
    paraphrase, out_p = works_for(f"{arxiv_id} - {real_title[:40]} under Hidden Effort", "_b")
    assert paraphrase and paraphrase[0]["status"] == "MISMATCH", paraphrase
    assert out_p["totals"]["mismatch"] == 1, out_p["totals"]
    assert "id_title_mismatch_present" in out_p["residual_gaps"], out_p["residual_gaps"]

    # arm 3, no false refusals: the same id quoted with the store's own title verifies.
    exact, out_e = works_for(f'arXiv:{arxiv_id} "{real_title}"', "_c")
    assert exact and exact[0]["status"] == "VERIFIED", exact
    assert out_e["totals"]["mismatch"] == 0 and out_e["residual_gaps"] == [], out_e["totals"]

    # arm 4: a forged title with NO id is still caught, by the title arm, unchanged. This
    # probe carries no id, so it is screened straight off the live-derived store.
    no_id_out = live_screen(live_root, tmp_path,
                            '"LLM Agents Always Defect in Public Goods Games"', "_d")
    assert no_id_out["candidates"][0]["ids"] == [], "this probe names no id"
    no_id = works_of(no_id_out)
    assert no_id and no_id[0]["status"] == "UNVERIFIABLE", no_id
    assert no_id[0]["match_kind"] == "absent", no_id[0]


@pytest.mark.skipif(not (cs._main_lab_root() / "run_state/arxiv_ingestion").is_dir(),
                    reason="no live paper store on this machine")
def test_every_live_title_cited_with_its_own_id_verifies(tmp_path):
    """The false-refusal arm: over the whole live store, quoting a stored title beside its
    own id must always be VERIFIED and never MISMATCH. A check that only fires on garbage
    is a check that will be ignored."""
    store = cs.PaperStore(cs._main_lab_root() / "run_state/arxiv_ingestion").load()
    seen, checked = set(), 0
    lines = []
    for paper in store.papers:
        arxiv_id = str(paper.get("arxiv_id") or "")
        title = str(paper.get("title") or "").strip()
        if not title or not arxiv_id or arxiv_id.lower() in seen:
            continue
        seen.add(arxiv_id.lower())
        lines.append(f"- arXiv:{arxiv_id} \"{title}\"")
        checked += 1
    assert checked >= 50, f"only {checked} live id+title pairs available"
    set_path = tmp_path / "LIVE.md"
    set_path.write_text("# Thesis candidates\n\n## Candidate: All\n\n**Prior work:**\n"
                        + "\n".join(lines) + "\n")
    out = cs.screen(set_path, store)
    bad = [w for w in out["candidates"][0]["works"] if w["status"] != "VERIFIED"]
    assert not bad, f"{len(bad)}/{checked} verbatim id+title citations did not verify: {bad[:3]}"
    assert out["totals"]["mismatch"] == 0


# --- review claude-a857cd9b3f5b6c33 (seq 187), amendments 1 and 2 ---------------------
#
# Amendment 1: an UNBOLDED 'Prior work:' label. field_lines() set in_field on the bare
# label, then the very next branch reset it without appending the line's text, so the
# seq 150 finding-1 probe shape ('- Prior work: <text> (arXiv:<id>)') never reached the
# screen at all: totals all zero, exit 0. The three tests below use the unbolded shape
# so the probe is reproduced by tests, not only in a comment (amendment 3).
#
# Amendment 2: the id fallback `carried = [...] or titled_ids`. On a line carrying two
# real citations, a chunk with no id of its own was paired with titled_ids[0], so a
# title could be verified against the wrong paper.


def test_an_unbolded_prior_work_line_is_screened_not_skipped(tmp_path):
    """Amendment 1, the exact probe: a real id, an invented title, no bold anywhere."""
    text = ("## Candidate: Bare\n\n"
            "- Prior work: Anchoring in LLM agents (arXiv:2609.11111)\n"
            "- Falsifier: something\n")
    out = report(tmp_path, text)
    works = out["candidates"][0]["works"]
    assert works, (
        "an unbolded 'Prior work:' line reached the screen with no citation rows at all - "
        "the forgery class the seq 150 probe describes walks through clean")
    assert out["totals"]["mismatch"] >= 1, (
        f"the invented title beside a real id was not a MISMATCH: {works}")


def test_an_unbolded_prior_work_line_with_the_true_title_verifies(tmp_path):
    """Amendment 1, the other arm: screening must not only fire on forgeries."""
    text = ("## Candidate: BareTrue\n\n"
            "- Prior work: Order effects in judgment under uncertainty (arXiv:2609.11111)\n")
    out = report(tmp_path, text)
    works = out["candidates"][0]["works"]
    assert works and works[0]["status"] == "VERIFIED", works


def test_an_unbolded_related_work_line_is_screened(tmp_path):
    text = ("## Candidate: BareRel\n\n"
            "Related work: Quantum probability models of cognition: a review "
            "(arXiv:2609.11111)\n")
    out = report(tmp_path, text)
    assert out["totals"]["mismatch"] >= 1, out["candidates"][0]["works"]


def test_two_citations_on_one_line_never_pair_a_title_with_the_wrong_id(tmp_path):
    """Amendment 2: the second title belongs to 2609.11112. Pairing it with the first id
    on the line would call a real title a mismatch, or the reverse would call a forgery
    verified; either way the pairing must come from the text beside the chunk."""
    text = ("## Candidate: Two\n\n**Prior work:** Order effects in judgment under "
            "uncertainty (arXiv:2609.11111); Anchoring in LLM agents (arXiv:2609.11112)\n")
    out = report(tmp_path, text)
    by_cited = {w["cited"][:40]: w for w in out["candidates"][0]["works"]}
    forged = [w for k, w in by_cited.items() if "Anchoring" in k]
    assert forged, sorted(by_cited)
    assert forged[0]["status"] == "MISMATCH", forged
    assert forged[0]["arxiv_id"] == "2609.11112", (
        f"a forged title was adjudicated against {forged[0]['arxiv_id']}; the line's first "
        f"id is not this chunk's id")
    true = [w for k, w in by_cited.items() if "Order effects" in k]
    assert true and true[0]["status"] == "VERIFIED" and true[0]["arxiv_id"] == "2609.11111", true


def test_a_chunk_with_no_id_of_its_own_on_a_single_id_line_still_uses_that_id(tmp_path):
    """The fallback is still needed: one id on the line, the title phrased beside it."""
    text = ("## Candidate: One\n\n**Prior work:** Order effects in judgment under "
            "uncertainty, arXiv:2609.11111\n")
    out = report(tmp_path, text)
    works = out["candidates"][0]["works"]
    assert works and works[0]["status"] == "VERIFIED", works


def test_two_correct_parenthetical_citations_on_one_line_are_clean(tmp_path):
    text = candidate(
        "Parenthetical pair",
        "Order effects in judgment under uncertainty (arXiv:2609.11111); "
        "Quantum probability models of cognition: a review (arXiv:2609.11112)",
    )
    out = report(tmp_path, text)
    works = works_of(out)
    assert len(works) == 2 and [w["status"] for w in works] == ["VERIFIED", "VERIFIED"], works
    assert [w["arxiv_id"] for w in works] == ["2609.11111", "2609.11112"], works
    assert out["totals"] == {"unverifiable": 0, "uningested": 0, "partial": 0, "mismatch": 0}
    set_path = tmp_path / "CANDIDATES.md"
    assert cs.main(["--set", str(set_path), "--store", str(tmp_path / "arxiv_ingestion")]) == 0


def test_two_correct_id_first_citations_on_one_line_are_clean(tmp_path):
    text = candidate(
        "Id-first pair",
        "2609.11111 - Order effects in judgment under uncertainty; "
        "2609.11112 - Quantum probability models of cognition: a review",
    )
    out = report(tmp_path, text)
    works = works_of(out)
    assert len(works) == 2 and [w["status"] for w in works] == ["VERIFIED", "VERIFIED"], works
    assert [w["arxiv_id"] for w in works] == ["2609.11111", "2609.11112"], works
    assert out["totals"] == {"unverifiable": 0, "uningested": 0, "partial": 0, "mismatch": 0}


def test_second_invented_id_first_title_is_mismatch_never_partial(tmp_path):
    text = candidate(
        "Id-first forgery",
        "2609.11111 - Order effects in judgment under uncertainty; "
        "2609.11112 - Quantum probability models of cognition in LLM agents",
    )
    out = report(tmp_path, text)
    works = works_of(out)
    assert len(works) == 2 and [w["status"] for w in works] == ["VERIFIED", "MISMATCH"], works
    assert works[1]["arxiv_id"] == "2609.11112", works
    assert out["totals"] == {"unverifiable": 0, "uningested": 0, "partial": 0, "mismatch": 1}


def test_two_correct_titles_without_ids_on_one_line_are_clean(tmp_path):
    text = candidate(
        "Title pair",
        "Order effects in judgment under uncertainty; "
        "Quantum probability models of cognition: a review",
    )
    out = report(tmp_path, text)
    works = works_of(out)
    assert len(works) == 2 and [w["status"] for w in works] == ["VERIFIED", "VERIFIED"], works
    assert out["totals"] == {"unverifiable": 0, "uningested": 0, "partial": 0, "mismatch": 0}


def test_bare_prior_work_label_with_clean_list_has_no_gap(tmp_path):
    text = ("## Candidate: Bare list\n\nPrior work:\n"
            "- Order effects in judgment under uncertainty (arXiv:2609.11111)\n"
            "- Quantum probability models of cognition: a review (arXiv:2609.11112)\n")
    out = report(tmp_path, text)
    works = works_of(out)
    assert len(works) == 2 and [w["status"] for w in works] == ["VERIFIED", "VERIFIED"], works
    assert out["totals"] == {"unverifiable": 0, "uningested": 0, "partial": 0, "mismatch": 0}
