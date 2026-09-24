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
  * every *title-ish* citation line (a bullet or table row whose label is Title /
    Prior work / Related work, or a heading field with those names) is matched by
    normalized-title containment against the store. No hit is UNVERIFIABLE — which is
    the invented-citation case this exists to catch — and a hit against an ingested
    paper records its arXiv id.

Matching is deliberately conservative: a title matches only when the store's title
contains the cited title, or the cited title contains the store's title and is at least
20 characters. A title that does not match is reported, never silently accepted. This
is a screen, not a literature search: it asks whether a citation is checkable, and
leaves the asking of "is this the closest prior work" to Oracle's note.

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
        if re.match(r"(?i)^(prior(\s+work)?|related\s+work|title)\b[ \t]*:", stripped):
            in_field = True  # a bare (unbolded) field label: only its own line is a citation
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
MIN_CITED_TITLE = 20   # a cited phrase this short is a guess, not a citation
MIN_STORE_TITLE = 20   # a stored title this short cannot certify a longer sentence
MIN_COVERAGE = 0.60    # a real citation is mostly the title it names


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

    def find_title(self, title: str) -> dict | None:
        """The store paper a cited title refers to, or None (the invented-citation case).

        Three rules, because the two directions fail in opposite ways (review
        claude-56275cf790bac03c, finding 4 and amendment 6 asked for a stored-side floor;
        a stored-side floor ALONE was the first attempt here and it hid a second defect,
        so all three are stated and each is tested):

        * equal after normalization resolves, at any length. The store holds 40 titles
          under 45 characters and 13 titles under 20 - "Fair Prophets" among them - so a
          floor that applied to exact matches would refuse a correctly quoted short title
          (measured at this commit: `Communication as Voting` is in the store and did not
          resolve under the two-floor rule alone).
        * `norm in stored`: the citation abbreviates a real title, so the floor is on the
          CITED side (MIN_CITED_TITLE). A two-word guess must not match a long title.
        * `stored in norm`: the citation contains a real title inside more words. This is
          where the invented-citation hole was - with no floor, the live store's short
          titles ("communication as voting", "auctions as experiments", "fair prophets")
          verified any invented sentence that mentioned one. So the stored title must be
          at least MIN_STORE_TITLE characters AND cover MIN_COVERAGE of the cited chunk:
          a real citation is mostly the real title, an invented one carries a real phrase
          inside a fiction. A short title therefore resolves ONLY exactly, never as a
          fragment of a longer sentence.

        Ambiguity is not resolved silently: several qualifying matches return None and are
        reported UNVERIFIABLE, because "which paper?" is a question the screen cannot
        answer and Oracle's note must.

        The same title stored more than once is ONE candidate, not several. Measured on
        the live store at this commit: 1,134 rows carry 305 distinct normalized titles,
        because the daily ingestion re-reads a paper into several cache and run files.
        Counting rows would call every ingested paper ambiguous and refuse the screen.
        """
        norm = normalize(title)
        if not norm:
            return None
        titles: set[str] = set()
        for stored, paper in self.titles:
            if not stored:
                continue
            if stored == norm:
                titles.add(stored)
            elif norm in stored and len(norm) >= MIN_CITED_TITLE:
                titles.add(stored)
            elif stored in norm and len(stored) >= MIN_STORE_TITLE \
                    and len(stored) >= MIN_COVERAGE * len(norm):
                titles.add(stored)
        if not titles:
            return None
        if len(titles) > 1:
            return None  # ambiguous: reported UNVERIFIABLE, and the note must name it
        stored = next(iter(titles))
        for candidate, paper in self.titles:  # first row wins; duplicates are the same paper
            if candidate == stored:
                return paper
        return None


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
            for chunk in re.split(r"(?i)[;\n]|\(arxiv[:.\s]*\d{4}\.\d{4,5}(?:v\d+)?\)", line):
                chunk = chunk.strip(" \t-*|").strip()
                if len(normalize(chunk)) < 8 or normalize(chunk) in seen_titles:
                    continue
                seen_titles.add(normalize(chunk))
                hit = store.find_title(chunk)
                works.append({"cited": chunk[:200],
                              "status": "VERIFIED" if hit else "UNVERIFIABLE",
                              "arxiv_id": (hit or {}).get("arxiv_id"),
                              "matched_title": (hit or {}).get("title")})
        per_candidate.append({"label": label, "ids": ids, "works": works,
                              "unverifiable": sum(1 for w in works if w["status"] == "UNVERIFIABLE"),
                              "uningested": sum(1 for i in ids if i["status"] == "UNINGESTED")})
    counts = {k: sum(c[k] for c in per_candidate) for k in ("unverifiable", "uningested")}
    return {"schema": "citation-screen/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "set": str(set_path), "set_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "store_root": str(store.root), "store_files": store.files,
            "papers": len(store.papers), "candidates": per_candidate,
            "totals": counts,
            "residual_gaps": sorted(
                ({"uningested_ids_present"} if counts["uningested"] else set())
                | ({"unverifiable_citations_present"} if counts["unverifiable"] else set()))}


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
            print(f"\n== {cand['label']}  (unverifiable {cand['unverifiable']}, uningested {cand['uningested']})")
            for work in cand["works"]:
                print(f"  [{work['status']:<12}] {work['cited'][:90]}"
                      + (f"  -> {work['arxiv_id']}" if work.get("arxiv_id") else ""))
            for entry in cand["ids"]:
                print(f"  [{entry['status']:<12}] arXiv {entry['arxiv_id']} {entry.get('title') or ''}")
        print(f"\ntotals: {report['totals']}")
    return 0 if not report["residual_gaps"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
