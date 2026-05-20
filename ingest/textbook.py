#!/usr/bin/env python3
"""textbook.py — Day 3 (day3_block2_chunking_and_ingest_script).

CLI ingest driver: PDF -> per-page text -> semantic chunks -> ChromaDB.

Extraction uses pypdfium2 (plan escalation ladder: pypdfium2 -> pymupdf
-> nougat; first choice). The PDF outline (bookmarks) drives semantic
section boundaries; absent an outline, chunking.py falls back to
fixed-size chunks.

ChromaDB lives at localhost:8001 — host default 8000 is the vLLM
endpoint (CLAUDE.md). The embedder is BGE-M3 from local weights, never
the all-MiniLM-L6-v2 default (inviolate rule 2).

Run via `.venv-chroma/bin/python ingest/textbook.py ...` (also works
under bare python3 if pypdfium2/chromadb are importable).
"""
import argparse
import json
import os
import random
import re
import sys
from datetime import datetime, timezone

import pypdfium2 as pdfium

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingest.chunking import chunk_sections  # noqa: E402

BGE_M3_WEIGHTS = "/mnt/models/bge-m3"
CHROMA_HOST = "localhost"
CHROMA_PORT = 8001
DRY_RUN_SAMPLE = 5
RNG_SEED = 1337


# De-hyphenation: pypdfium2 renders this PDF's soft line-break
# hyphens as U+FFFE (a Unicode non-character), not U+002D. The
# artifact splits a single word across a line break:
#   "the￾ory", "con￾sequence", "My￾erson".
# BGE-M3 would embed "the￾ory" as a different token than
# "theory", hurting retrieval — so we rejoin the halves here.
# The artifact may be followed by whitespace/newline (the line
# break itself); we strip the artifact AND that trailing
# whitespace so the two halves fuse into one word. Legitimate
# U+002D hyphens ("out-of-date") are untouched.
_HYPHEN_ARTIFACT = "￾"
_DEHYPHEN_RE = re.compile(_HYPHEN_ARTIFACT + r"\s*")


def dehyphenate(text):
    """Rejoin words split by the U+FFFE line-break hyphenation artifact."""
    return _DEHYPHEN_RE.sub("", text)


def extract_pages(pdf):
    """Return a list of page text strings, indexed by page number - 1.

    Text is de-hyphenated on extraction (see `dehyphenate`).
    """
    pages = []
    for i in range(len(pdf)):
        page = pdf.get_page(i)
        textpage = page.get_textpage()
        pages.append(dehyphenate(textpage.get_text_range()))
        textpage.close()
        page.close()
    return pages


# A bookmark is a CHAPTER if its title is a leading integer + space
# ("6 Extensive Games ...", "1.1 Game Theory" -> chapter 1 via the
# leading "1"). It is a PART if its title is a leading Roman numeral
# + space ("II Extensive Games ..."). Parts carry no chapter number;
# back matter ("Preface", "References", "Index") matches neither.
_CHAPTER_RE = re.compile(r"^(\d+)\s")
_PART_RE = re.compile(r"^[IVXLC]+\s")


def _chapter_number(title):
    """Return the integer chapter number from a title, or None."""
    m = _CHAPTER_RE.match(title or "")
    return int(m.group(1)) if m else None


def derive_sections(pdf, page_texts):
    """Build section dicts from the PDF outline (bookmarks).

    The outline mixes Parts ("I Strategic Games"), Chapters
    ("6 Extensive Games ...", numbered with a leading integer) and
    subsections ("6.2 Subgame Perfect Equilibrium"). A bookmark is a
    chapter iff its title starts with an integer + space; the chapter
    *number* is that integer. Parts start with a Roman numeral and
    carry no chapter number. As we walk the marks we maintain the
    current chapter and part; every section row inherits the current
    chapter number (so Chapter 6's subsections get chapter=6, not the
    enclosing Part's name).

    A section spans from its start page to the page just before the
    next bookmark.

    Returns (sections, used_toc). If the PDF has no outline, returns a
    single whole-book pseudo-section and used_toc=False so chunking.py
    applies the fixed-size fallback.
    """
    toc = list(pdf.get_toc())
    n_pages = len(page_texts)

    def _whole_book():
        return ([{
            "chapter": 0, "chapter_title": "", "section": "", "part": "",
            "page_start": 1, "page_end": n_pages,
            "text": "\n".join(page_texts),
        }], False)

    if not toc:
        return _whole_book()

    # Resolve each bookmark to (level, title, page_index).
    marks = []
    for bm in toc:
        dest = bm.get_dest()
        page_idx = dest.get_index() if dest is not None else None
        if page_idx is None:
            continue
        marks.append({
            "level": bm.level,
            "title": (bm.get_title() or "").strip(),
            "page": page_idx,  # 0-based
        })
    if not marks:
        return _whole_book()

    sections = []
    current_chapter = 0       # int chapter number; 0 = back/front matter
    current_chapter_title = ""
    current_part = ""
    for j, mk in enumerate(marks):
        title = mk["title"]
        ch_num = _chapter_number(title)
        if ch_num is not None:
            current_chapter = ch_num
            current_chapter_title = title
        elif _PART_RE.match(title):
            current_part = title
            # A Part heading itself is not chapter content; the next
            # numbered bookmark resets the chapter. Until then any
            # section under the Part inherits no chapter number.
            current_chapter = 0
            current_chapter_title = ""
        # Section ends at the page before the next mark, else last page.
        start = mk["page"]
        end = (marks[j + 1]["page"] - 1) if j + 1 < len(marks) else n_pages - 1
        if end < start:
            end = start
        text = "\n".join(page_texts[start:end + 1])
        sections.append({
            "chapter": current_chapter,
            "chapter_title": current_chapter_title,
            "section": title,
            "part": current_part,
            "page_start": start + 1,   # 1-based for human-readable metadata
            "page_end": end + 1,
            "text": text,
        })
    return sections, True


def filter_chapters(sections, chapters_csv):
    """Restrict `sections` to the requested chapter numbers (CSV string)."""
    wanted = set()
    for c in chapters_csv.split(","):
        c = c.strip()
        if c.isdigit():
            wanted.add(int(c))
    kept = [s for s in sections if s.get("chapter") in wanted]
    return kept


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True, help="path to the textbook PDF")
    ap.add_argument("--chapters",
                    help="comma-separated chapter numbers, e.g. '1' or '1,2,3'")
    ap.add_argument("--dry-run", action="store_true",
                    help="extract+chunk only; print stats; no ChromaDB")
    ap.add_argument("--collection", help="ChromaDB collection name for a real ingest")
    ap.add_argument("--output-manifest", help="path to write the ingest manifest JSON")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"FATAL: PDF not found: {args.pdf}", file=sys.stderr)
        return 1

    pdf = pdfium.PdfDocument(args.pdf)
    book = os.path.splitext(os.path.basename(args.pdf))[0]
    page_texts = extract_pages(pdf)
    sections, used_toc = derive_sections(pdf, page_texts)

    if args.chapters:
        if not used_toc:
            print("WARNING: --chapters requested but PDF has no outline; "
                  "ignoring the filter and chunking the whole book.",
                  file=sys.stderr)
        else:
            sections = filter_chapters(sections, args.chapters)
            if not sections:
                print(f"FATAL: no sections matched chapters {args.chapters!r}",
                      file=sys.stderr)
                return 1

    chunks = chunk_sections(sections, book)
    if not chunks:
        print("FATAL: extraction produced zero chunks", file=sys.stderr)
        return 1

    lengths = [len(c["text"]) for c in chunks]

    if args.dry_run:
        mean_len = sum(lengths) / len(lengths)
        print(f"strategy={'toc' if used_toc else 'fixed-size-fallback'}")
        print(f"chunk_count={len(chunks)}")
        print(f"mean_chunk_chars={mean_len:.1f}")
        print(f"max_chunk_chars={max(lengths)}")
        rng = random.Random(RNG_SEED)
        sample = rng.sample(chunks, min(DRY_RUN_SAMPLE, len(chunks)))
        for k, c in enumerate(sample):
            md = c["metadata"]
            print(f"\n--- sample chunk {k} "
                  f"[ch={md['chapter']!r} ({md['chapter_title']!r}) "
                  f"sec={md['section']!r} "
                  f"pages={md['page_range']} idx={md['chunk_index']}] ---")
            print(c["text"][:600])
        return 0

    if not args.collection:
        print("FATAL: a real ingest needs --collection (or use --dry-run)",
              file=sys.stderr)
        return 1

    # Real ingest — connect to ChromaDB and add the chunks.
    import chromadb
    from chromadb.utils import embedding_functions

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=BGE_M3_WEIGHTS
    )
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    coll = client.get_or_create_collection(
        name=args.collection,
        embedding_function=ef,
        metadata={"embedding_function": "BGE-M3"},
    )
    coll.add(
        documents=[c["text"] for c in chunks],
        ids=[f"{book}-chunk-{c['metadata']['chunk_index']}" for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )

    per_chapter = {}
    for c in chunks:
        key = c["metadata"]["chapter"] or "(none)"
        per_chapter[key] = per_chapter.get(key, 0) + 1

    print(f"collection={args.collection} count={coll.count()} "
          f"embedding_function={(coll.metadata or {}).get('embedding_function')}")

    if args.output_manifest:
        manifest = {
            "pdf": os.path.abspath(args.pdf),
            "book": book,
            "collection": args.collection,
            "total_chunks": len(chunks),
            "per_chapter_counts": per_chapter,
            "strategy": "toc" if used_toc else "fixed-size-fallback",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.output_manifest)),
                    exist_ok=True)
        with open(args.output_manifest, "w") as fh:
            json.dump(manifest, fh, indent=2)
        print(f"manifest written to {args.output_manifest}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
