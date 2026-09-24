"""Screen the citations in a thesis candidate set against sources the lab really holds.

Plan 2026-09-24, work-phase follow-up to review claude-5dea097dd434208a amendment 3:
"the screen note must check that every Prior-work citation resolves, by arXiv id or in
the lab paper store. The structure test cannot catch invented citations."

Why a tool and not a note: d1's precheck receipt is already burned (one green stub run
per test sha, and the 8 KiB cap is spent), so the same check cannot be attached to that
plan item. A tool the screen runs has no cap and no receipt, and its output is the
evidence the screen note cites — the note then names a command and its output, which is
the rule this loop adopted after the 2026-09-23 factual_error findings.

What it does, per candidate block in a Markdown candidate set:
  * every bare arXiv id is looked up in the ingested paper store; an id that is not
    there is UNINGESTED (it may exist, but the lab cannot read it), and a malformed id
    is MALFORMED;
  * a citation that carries BOTH an arXiv id and a title is checked by ID: the title the
    store holds for that id must equal the title on that line. Equal means VERIFIED.
    Anything else is MISMATCH, which is a residual and is never INGESTED. This is the
    check that stops a real id wrapped around an invented title - review
    claude-4e67d485544a85df finding 1: at f150a22 the screen resolved such a line by id
    alone, printed the store's title instead of the cited one, and reported
    `unverifiable 0 / partial 0 / uningested 0`, i.e. a clean screen over a forged
    citation. A title with a resolvable id is also no longer counted as a title-citation,
    so one forged line cannot hide inside an `unverifiable >= 1` total.
  * every *title-ish* citation line (a bullet or table row whose label is Title /
    Prior work / Related work, or a heading field with those names) is resolved against
    the store by TITLE IDENTITY, not by containment.

What VERIFIED means, stated plainly because the difference matters: the screen checks
that a cited TITLE exists in the store. It does not check author, year, venue, or
whether the cited claim is what that paper says. VERIFIED means "the title resolves",
NOT "the citation is correct".

Why containment was dropped. Review claude-58cad93a58e0b3af (amendment 1) killed the
20-char / 60% containment rule this file shipped at d04de85, and the measured class is
the invention shape a candidate set is most likely to produce: append a qualifier to a
real title and the real title verified the fiction. Reproduced against the live store at
d04de85: 'Communication as Voting in LLM Agents' and 'Auctions as Experiments revisited'
both returned a real arXiv id. So VERIFIED now requires the normalized cited title to
EQUAL a stored title, after the prefix/suffix stripping in cited_title(). Containment in
either direction is PARTIAL: it is never VERIFIED, it is counted as a residual gap, and
it carries the candidate arXiv id so Oracle's screen note adjudicates it by hand. A
substring that resolves is a lead, not a citation.

This is a screen, not a literature search: it asks whether a citation is checkable, and
leaves the asking of "is this the closest prior work" to Oracle's note. D-061: adjudying
a PARTIAL is that note's job, and this tool never upgrades one itself.

D-061: this tool contains no research judgment. It reads two directories of files and
prints a table.

    python -m tools.citation_screen --set notes/research/.../CANDIDATES.md --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARXIV_ANY = re.compile(r"(?i)\b(\d{4}\.\d{4,5}(?:v\d+)?)\b")
FIELD_LABEL = re.compile(r"(?i)^(prior(?:\s+work)?|related\s+work|title)\b")
CANDIDATE_HEADING = re.compile(r"(?im)^[ \t]*#{1,6}[ \t]*[^\n]*\bcandidates?\b[^\n]*$")
HEADING = re.compile(r"(?im)^[ \t]*#{1,6}[ \t]*(.+?)[ \t]*$")
BULLET = re.compile(r"^(?:[-*]|\d+[.)])[ \t]+")
LABELLED = re.compile(r"(?i)^(?:[-*][ \t]+)?\*{1,2}(prior(?:\s+work)?|related\s+work|title)"
                      r"[^*\n]*\*{0,2}[ \t]*:[ \t]*(.*)$")
FIELD_STILL_RUNNING = re.compile(r"(?i)^(?:[-*][ \t]+)?\*{1,2}[A-Za-z][^*\n]{1,60}\*{1,2}[ \t]*:")
ANY_LABELLED_FIELD = re.compile(r"(?i)^(?:[-*][ \t]+)?\*{1,2}[A-Za-z][^*\n]{1,60}\*{0,2}[ \t]*:[ \t]*(.*)$")


def field_lines(block: str) -> list[str]:
    """The content lines of every Prior-work / Related-work field in one candidate.

    Heading, labelled-line and table-row shapes all appear in the brief's template, so
    all three are read. A field runs to the next field or heading, which is why its
    bullets are screened and the next field's prose (a Falsifier sentence, say) is not —
    screening prose as a citation would manufacture UNVERIFIABLE rows and train the
    screen to be ignored.
    """
    lines, capture, in_field = [], False, False
    for raw in block.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        heading = HEADING.match(stripped) if stripped.startswith("#") else None
        if heading:
            in_field = bool(FIELD_LABEL.match(heading.group(1).strip()))
            capture = in_field
            if capture:
                tail = heading.group(1)[len(FIELD_LABEL.match(heading.group(1)).group(0)):].strip(" :|-")
                if tail:
                    lines.append(tail)
            continue
        if stripped.startswith("#"):  # a heading that is not a field label ends the field
            capture = False
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")] if stripped.startswith("|") else None
        if cells:
            label = cells[0].strip("* ").strip()
            if FIELD_LABEL.match(label):
                if label.lower().startswith("prior") or label.lower().startswith("related"):
                    capture = True
                    if len(cells) > 1 and cells[1]:
                        lines.append(cells[1])
                else:
                    capture = False
                continue
            if label.strip("* ").lower() in ("field",):
                capture = False
                continue
            if capture and len(cells) == 1:  # a wrapped continuation row of the same field
                lines.append(cells[0])
                continue
            continue
        if stripped.startswith("---") or set(stripped) <= {"-", ":", " "}:
            continue
        if re.match(r"(?i)^(?:[-*][ \t]+)?(prior(\s+work)?|related\s+work)\b[ \t]*:", stripped):
            # An UNBOLDED field label with text after the colon is a citation line, and the
            # text must reach the screen. It used to be dropped: this branch set in_field,
            # the branch below matched the same line as ANY_LABELLED_FIELD and reset
            # in_field without appending anything, so the seq 150 finding-1 probe
            # ('- Prior work: <invented title> (arXiv:<real id>)') screened as clean.
            # Review claude-a857cd9b3f5b6c33 (seq 187), amendment 1. 'Title:' stays out:
            # a title is not a prior-work citation, and screening it manufactures rows.
            tail = stripped.split(":", 1)[1].strip()
            if tail:
                lines.append(BULLET.sub("", tail))
            capture = True
            in_field = False
            continue
        match = ANY_LABELLED_FIELD.match(stripped)
        if match:
            named = LABELLED.match(stripped)
            if named and named.group(1).lower().startswith(("prior", "related")):
                capture = True
                if named.group(2).strip():
                    lines.append(named.group(2).strip())
            else:
                capture = False  # some other field's label: the Prior-work field has ended
            continue
        if FIELD_STILL_RUNNING.match(stripped) or in_field:
            in_field = False
            capture = False
            continue
        if capture:
            lines.append(BULLET.sub("", stripped))
    return [ln.strip(" \t|*") for ln in lines if ln.strip(" \t|*")]


def _main_lab_root() -> Path:
    """The checkout the daily loops run from, not the worktree this file sits in.

    run_state/ is runtime data and is absent from a fresh worktree, so a screen run from
    one would find an empty paper store and report 2 (refused, not silently empty) rather
    than silently reporting that no citation matched. Same rule the lane applies to
    precheck receipts: runtime data is read where it lives.

    Resolved through git, the same way the lane resolves it (nara_lane._main_lab_root(),
    merged on oracle/2026-09-24-d3): `git rev-parse --git-common-dir` names the main
    working tree from any linked worktree. The old rule, `ROOT.parent.parent / "a_bgt_rsi"`,
    was wrong for any checkout not exactly two levels below projects/ - and `git worktree
    add` puts precheck and Nara worktrees wherever the caller chose (review
    claude-56275cf790bac03c, amendment 6, second half). It is reimplemented here rather
    than imported, so the screen stays usable and hermetic when only this file is present.
    """
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ROOT
    if not common or not Path(common).is_dir():
        return ROOT
    path = Path(common)
    root = path.parent if path.name == ".git" else path
    return root if root.is_dir() else ROOT


def normalize(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — enough for title containment."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", title.lower()).split())


# Containment floors (review claude-56275cf790bac03c, amendment 6). Measured on the live
# store at this commit: 1,134 papers over 14 files, shortest title 13 characters, 40 titles
# under 45. Without the stored-side floor an invented citation that merely mentions one of
# those short titles verified itself.
# The containment floors (MIN_STORE_TITLE, MIN_COVERAGE, MIN_CITED_TITLE) are gone on
# purpose: review claude-58cad93a58e0b3af amendment 1 showed a qualified real title clears
# them, and amendment 2 showed each guard was unpinned by its own test. Identity is the
# rule; anything shorter or longer than a stored title is PARTIAL and comes to a human.
MIN_CITED_CHUNK = 8    # below this a chunk is noise ("see also"), not a title citation

# A leading "Smith 2031," / "Jones et al., 2020:" prefix, a trailing "(arXiv:2505.14639)"
# or "(NeurIPS 2024)" venue parenthetical, and quote or emphasis markers are formatting
# around the title, not part of it. The year/et-al requirement is what keeps a real title
# that merely starts with a word from being eaten: the prefix must look like a citation.
# Review claude-749d39bc3396f628, finding 1: the free-text run `[^:.)\n]{0,40}` after the
# year let a prefix swallow invented title text, so 'Jones 2030, LLM Agents: <real title>'
# verified as the real paper — the seq-113 amendment-1 forgery class, entered from the
# front. The prefix now must END at the year (or the et-al) plus one separator; nothing
# between the year and the title is eaten. `(?i)` is gone so the name must start capped.
AUTHOR_YEAR_PREFIX = re.compile(
    r"^\s*[A-Z][A-Za-z'’\-]+"
    r"(?:\s+(?:&|and)\s+[A-Z][A-Za-z'’\-]+|,\s*[A-Z][A-Za-z'’\-]+)*"
    r"(?:\s+et\s+al\.?)?,?\s*\(?(?:\d{4}[a-z]?|'\d{2})\)?\s*[:.,]\s*")
TRAILING_PAREN = re.compile(r"\s*\((?:[^()]*(?:arxiv|proceedings|journal|conference|workshop|"
                            r"neurips|icml|iclr|aaai|aamas|ecma|arxiv\.org)[^()]*)\)\s*$", re.I)
EMPHASIS = re.compile(r"[*_`]{1,3}|[“”\"']")


def cited_title(chunk: str) -> str:
    """The normalized title a citation chunk points at, with citation furniture removed.

    Deliberately does NOT split on ':'. Amendment 1: splitting on the colon would let
    'Cursed Rationalizability: A New Benchmark' resolve to the stored 'Cursed
    Rationalizability' — which is exactly the qualified-title forgery this pass exists to
    refuse. A colon inside the title therefore stays in the title, and if the whole thing
    is not in the store it comes back unmatched and lands in PARTIAL/UNVERIFIABLE.
    """
    # Review claude-749d39bc3396f628, finding 2: markers become a SPACE, not nothing.
    # normalize() turns a stored title's apostrophe or underscore into a space, so the
    # cited side has to as well — otherwise "Approximating Pandora's Knapsack ..." and
    # "$\\ell_1$ Preferences" can never verify, even when cited verbatim.
    text = EMPHASIS.sub(" ", chunk or "")
    text = TRAILING_PAREN.sub("", text).strip()
    text = AUTHOR_YEAR_PREFIX.sub("", text, count=1).strip()
    text = re.sub(r"\s+", " ", text).strip(" \t-|:.,·")
    return normalize(text)


class PaperStore:
    """The lab's paper store: the JSONL files the daily arXiv ingestion writes.

    Two shapes are read because the lab writes both: a cache file whose rows are papers,
    and a per-run `papers.jsonl` with a schema line followed by paper rows. Nothing else
    is trusted as a source of titles — an author-written list of "prior work" is the
    thing being screened, not a source.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.papers: list[dict] = []
        self.files: list[str] = []

    def load(self) -> "PaperStore":
        for path in sorted(self.root.rglob("*.jsonl")):
            rows = []
            for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    print(f"warning: {path} line {number} is not JSON, skipped", file=sys.stderr)
                    continue
                if not isinstance(row, dict) or "title" not in row:
                    continue  # schema/provenance/summary rows carry no title
                rows.append(row)
            if rows:
                self.files.append(str(path.relative_to(self.root)) if self.root in path.parents else str(path))
                self.papers.extend(rows)
        self.by_arxiv = {str(p.get("arxiv_id")).lower(): p for p in self.papers if p.get("arxiv_id")}
        self.titles = [(normalize(str(p["title"])), p) for p in self.papers if str(p.get("title", "")).strip()]
        return self

    def find_arxiv(self, arxiv_id: str) -> dict | None:
        wanted = arxiv_id.lower()
        bare = re.sub(r"v\d+$", "", wanted)
        for key, paper in self.by_arxiv.items():
            if key == wanted or re.sub(r"v\d+$", "", key) == bare:
                return paper
        return None

    def resolve_title(self, chunk: str) -> tuple[str, dict | None, str]:
        """('VERIFIED' | 'PARTIAL' | 'UNVERIFIABLE', paper, kind) for one cited chunk.

        VERIFIED only when the stripped cited title equals a stored title exactly (see
        cited_title(): citation furniture comes off, a colon inside the title does not).
        Any containment, in either direction, is PARTIAL and carries the candidate paper
        so the screen note can adjudicate; a PARTIAL is a residual gap, never a pass. A
        substring that resolves is a lead, not a citation — that is the whole content of
        review claude-58cad93a58e0b3af amendment 1, which replaced this function's 20-char
        / 60% containment floors after they were measured verifying a real title with a
        qualifier bolted onto it.

        Candidates are counted by DISTINCT STORED TITLE, never by row. The daily
        ingestion re-reads one paper into several cache and run files, so at this review
        the live store's 1,356 rows carry 350 distinct normalized titles and every one of
        them appears 2 to 8 times; counting rows would call every stored paper ambiguous
        and refuse the screen.

        Ambiguity is reported, never resolved: when one cited string matches more than one
        distinct stored title the screen returns UNVERIFIABLE with no paper and names the
        kind, because "which paper?" is not a question this tool can answer — the first
        version of this function silently took the longest match. Measured on the live
        store, all 17 of its titles of 13-30 characters sit inside a longer stored title,
        so that arm is common, not exotic: a qualified short title comes back UNVERIFIABLE
        there rather than PARTIAL, and a PARTIAL carrying one candidate is earned, not
        assumed.
        """
        norm = cited_title(chunk)
        if not norm:
            return "UNVERIFIABLE", None, "no_title"
        # _by_title keys by stored title, so an exact match is never a set of more than
        # one: `len(exact) > 1` was unreachable and the review asked for it gone
        # (claude-749d39bc3396f628, amendment 4). Only the partial arm can be ambiguous.
        exact = _by_title(self.titles, lambda stored: stored == norm)
        if exact:
            return "VERIFIED", next(iter(exact.values())), "exact"
        partial = _by_title(self.titles,
                            lambda stored: bool(stored) and (stored in norm or norm in stored))
        if len(partial) == 1:
            return "PARTIAL", next(iter(partial.values())), "contains"
        if partial:
            return "UNVERIFIABLE", None, "ambiguous_partial"
        return "UNVERIFIABLE", None, "absent"


def _by_title(titles: list[tuple[str, dict]], matches) -> dict[str, dict]:
    """{normalized stored title: one paper} for every stored title `matches` accepts.

    Keyed by title so one paper's duplicate rows collapse to a single candidate. The paper
    kept is the first row seen for that title.
    """
    out: dict[str, dict] = {}
    for stored, paper in titles:
        if matches(stored) and stored not in out:
            out[stored] = paper
    return out

def title_without_ids(cited: str, ids: list[str]) -> str:
    r"""A citation chunk with its arXiv id token(s) cut out, so the id text itself can never
    be mistaken for part of the title.

    Cutting the id rather than the whole `arXiv:` prefix is deliberate: `arXiv:` is a
    legitimate substring of a real stored title ('... based on the AR-Xiv data platform')
    and replacing the bare digits alone would leave the prefix glued to the title. Two
    passes, because a bare `2609.20789` does not match `arXiv[:.\s]*<id>`: the greedy pass
    eats the whole `arXiv:<id>` token (and a separator the id regex could not match, so
    'arXiv 2609.11112' leaves no stray 'arXiv' glued to the title), the second pass eats a
    bare id. The citation is a substring of the line the id was found on, so one of the two
    always hits. `cited_title()` then strips the separator left behind.
    """
    text = cited or ""
    for arxiv_id in ids:
        text = re.sub(r"(?i)arXiv[:.\s]*" + re.escape(arxiv_id), " ", text)
        text = re.sub(r"(?<![\d.])" + re.escape(arxiv_id) + r"(?![\d.])", " ", text)
    return text


def pair_status(cited: str, arxiv_id: str, store: "PaperStore") -> tuple[str, dict | None, str]:
    """('VERIFIED' | 'MISMATCH' | 'ID_NOT_IN_STORE', store paper, store title) for one
    citation chunk that carries an arXiv id.

    The store title held for `arxiv_id` is the authority; the cited text is compared to it
    with the same furniture-stripping used everywhere else in this file - the id token is
    cut out first (title_without_ids), then cited_title() removes an author-year prefix, a
    venue parenthetical and quote/emphasis markers, and normalize() blanks punctuation, so
    a verbatim citation of a title containing an apostrophe or an underscore still
    compares equal. Title-to-title only: an id's SHAPE is never evidence about a title.

    Why the rule is asymmetric, and why that is not a hole. This check targets the failure
    we were actually caught in (review claude-4e67d485544a85df finding 2): a real id with
    an altered or invented title on the same line. Demanding that every bare id also carry
    a title would make every legitimate id-only citation illegal, and the id arm already
    reports UNINGESTED for an id the lab cannot read. So: an id absent from the store is
    left to the id arm (ID_NOT_IN_STORE, no double-count); a chunk with an id and no
    title text at all is not a title citation and is not screened as one, and stays a
    residual through the id arm's own status; any title text that is not the store's title
    for that id is MISMATCH.
    """
    paper = store.find_arxiv(arxiv_id)
    if paper is None:
        return "ID_NOT_IN_STORE", None, ""
    stored = str(paper.get("title", ""))
    want = cited_title(title_without_ids(cited, [arxiv_id]))
    if not want:
        return "NO_TITLE", paper, stored
    if want == cited_title(stored):
        return "VERIFIED", paper, stored
    return "MISMATCH", paper, stored


def line_ids(line: str, store: "PaperStore") -> tuple[list[dict], list[str]]:
    """(id entries, arXiv ids the store holds a title for) for one citation line.

    The entries have the same shape as the document-level id rows, so a reader sees one
    convention rather than two. The second list is what the title-vs-id check runs
    against - and it must be the line, not the chunk: the split below cuts citations apart
    on ';' or a newline, and a trailing ';' can push the id into a fragment that the title
    chunk no longer contains. If the id were not found there, the forged title would be
    adjudicated by the title search and come back UNVERIFIABLE: still a residual, but a
    generic one, and the report would never say 'you cited this id under a title that id
    does not carry' - the exact sentence a fabricated citation needs.
    """
    entries, titled = [], []
    for arxiv_id in ARXIV_ANY.findall(line):
        hit = store.find_arxiv(arxiv_id)
        entries.append({"arxiv_id": arxiv_id,
                        "status": "INGESTED" if hit else "UNINGESTED",
                        "title": (hit or {}).get("title")})
        if hit and str(hit.get("title", "")).strip():
            titled.append(arxiv_id)
    return entries, titled


def candidates(text: str) -> list[tuple[str, str]]:
    """(label, block) per candidate section. A document title naming `candidates` is not one."""
    starts = [m.start() for m in CANDIDATE_HEADING.finditer(text) if m.start() > 0]
    out = []
    for start in starts:
        end = min([e for e in starts if e > start], default=len(text))
        block = text[start:end]
        heading = HEADING.match(block.strip())
        out.append(((heading.group(1) if heading else block.splitlines()[0]).strip(), block))
    return out


def screen(set_path: Path, store: PaperStore) -> dict:
    text = set_path.read_text()
    per_candidate = []
    for label, block in candidates(text):
        ids, works = [], []
        for arxiv_id in ARXIV_ANY.findall(block):
            hit = store.find_arxiv(arxiv_id)
            ids.append({"arxiv_id": arxiv_id,
                        "status": "INGESTED" if hit else "UNINGESTED",
                        "title": (hit or {}).get("title")})
        seen_titles: set[str] = set()
        for line in field_lines(block):
            line_entries, titled_ids = line_ids(line, store)
            for entry in line_entries:
                if entry["arxiv_id"] not in {seen["arxiv_id"] for seen in ids}:
                    ids.append(entry)
            # Amendment 2 (review claude-a857cd9b3f5b6c33, seq 187): pair each chunk with
            # the id whose parenthetical actually ends it, never with the line's first id.
            # `carried = [...] or titled_ids` let a forged second title be adjudicated
            # against the first citation's id, which could read a forgery as VERIFIED.
            # The id is taken from the text INCLUDING the removed parenthetical, so an
            # uningested id still binds its own chunk instead of falling to the title arm.
            PARENTHETICAL = r"\((arxiv[:.\s]*\d{4}\.\d{4,5}(?:v\d+)?(?:,\s*arxiv[:.\s]*\d{4}\.\d{4,5}(?:v\d+)?)*)\)"
            pieces = re.split(PARENTHETICAL, line, flags=re.I)
            for index in range(0, len(pieces), 2):
                piece = pieces[index]
                beside = pieces[index + 1] if index + 1 < len(pieces) else ""
                subchunks = piece.split(";")
                for subindex, chunk in enumerate(subchunks):
                    chunk = chunk.strip(" \t-*|").strip()
                    if len(normalize(chunk)) < MIN_CITED_CHUNK or normalize(chunk) in seen_titles:
                        continue
                    seen_titles.add(normalize(chunk))
                    own = ARXIV_ANY.findall(chunk)
                    if beside and subindex == len(subchunks) - 1:
                        own = ARXIV_ANY.findall(beside) or own
                    carried = (own or [a for a in titled_ids if a in chunk]
                               or (titled_ids if len(titled_ids) == 1 else []))
                    if carried:
                        pair, pair_paper, stored_title = pair_status(chunk, carried[0], store)
                        if pair == "NO_TITLE":
                            # an id with no title text beside it is the id arm's business; do
                            # not invent a title-citation row for it
                            continue
                        cited_only = title_without_ids(chunk, carried)
                        works.append({"cited": chunk[:200],
                                      "cited_title": cited_title(cited_only),
                                      "status": pair,
                                      "match_kind": "id_title" if pair == "VERIFIED" else "id_title_" + pair.lower(),
                                      "arxiv_id": carried[0],
                                      "matched_title": (pair_paper or {}).get("title"),
                                      "store_title": stored_title or None,
                                      "detail": stored_title if pair == "MISMATCH" else None})
                        continue
                    status, paper, kind = store.resolve_title(chunk)
                    works.append({"cited": chunk[:200],
                                  "cited_title": cited_title(chunk),
                                  "status": status,
                                  "match_kind": kind,
                                  "arxiv_id": (paper or {}).get("arxiv_id"),
                                  "matched_title": (paper or {}).get("title")})
        per_candidate.append({"label": label, "ids": ids, "works": works,
                              "unverifiable": sum(1 for w in works if w["status"] == "UNVERIFIABLE"),
                              "partial": sum(1 for w in works if w["status"] == "PARTIAL"),
                              "mismatch": sum(1 for w in works if w["status"] == "MISMATCH"),
                              "uningested": sum(1 for i in ids if i["status"] == "UNINGESTED")})
    counts = {k: sum(c[k] for c in per_candidate)
              for k in ("unverifiable", "partial", "mismatch", "uningested")}
    return {"schema": "citation-screen/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "set": str(set_path), "set_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "store_root": str(store.root), "store_files": store.files,
            "papers": len(store.papers), "candidates": per_candidate,
            "totals": counts,
            "residual_gaps": sorted(
                ({"uningested_ids_present"} if counts["uningested"] else set())
                | ({"unverifiable_citations_present"} if counts["unverifiable"] else set())
                # a MISMATCH is a real id cited under a title that id does not carry: a
                # fabricated citation, not a gap in the store, and never an INGESTED
                | ({"id_title_mismatch_present"} if counts["mismatch"] else set())
                # a PARTIAL is a lead that needs a human, so it blocks a clean screen too
                | ({"partial_citations_need_adjudication"} if counts["partial"] else set()))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", required=True, help="candidate-set markdown file")
    parser.add_argument("--store", default=str(_main_lab_root() / "run_state/arxiv_ingestion"),
                        help="paper-store root (default: the main lab root's run_state/arxiv_ingestion)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    set_path = Path(args.set)
    if not set_path.is_file():
        print(f"candidate set does not exist: {set_path}", file=sys.stderr)
        return 2
    store = PaperStore(Path(args.store)).load()
    if not store.papers:
        print(f"paper store holds no papers: {args.store}", file=sys.stderr)
        return 2
    report = screen(set_path, store)
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"{report['papers']} papers in {len(store.files)} store files; "
              f"{len(report['candidates'])} candidates screened")
        for cand in report["candidates"]:
            print(f"\n== {cand['label']}  (unverifiable {cand['unverifiable']}, "
                  f"partial {cand['partial']}, uningested {cand['uningested']})")
            for work in cand["works"]:
                print(f"  [{work['status']:<12}] {work['cited'][:90]}"
                      + (f"  -> {work['arxiv_id']} ({work['match_kind']})"
                         if work.get("arxiv_id") else f"  ({work['match_kind']})"))
                if work["status"] == "MISMATCH":
                    # name both sides, or the reader cannot see the forgery (review
                    # claude-4e67d485544a85df, finding 1: the old print showed only the
                    # store title, so a clean-looking line hid the invented citation)
                    print(f"                 cited title: {work['cited_title']}\n"
                          f"                 store title: {work['store_title']}")
            for entry in cand["ids"]:
                print(f"  [{entry['status']:<12}] arXiv {entry['arxiv_id']} {entry.get('title') or ''}")
        print(f"\ntotals: {report['totals']}")
    return 0 if not report["residual_gaps"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
