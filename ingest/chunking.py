"""chunking.py — Day 3 (day3_block2_chunking_and_ingest_script).

Hybrid semantic chunking for textbook ingest:

  * Section boundaries are always honored — a chunk NEVER spans two
    outline sections (the fixed-size splitter runs *per section*
    inside chunk_sections).
  * The fixed-size splitter is then applied to EVERY section,
    regardless of size, so a 368-page book yields enough chunks for
    useful retrieval. With one-chunk-per-section the book produced
    only ~165 chunks; plan.yaml's day3_block2_full_ingest bands the
    collection count at [1500, 3000].

Token estimate is deliberately light: whitespace word count. The
chunk targets are therefore in *words*, not BPE tokens — documented
here so the band is interpretable. No heavyweight tokenizer is
pulled in (CLAUDE.md rule 9: resist abstraction).

TARGET_WORDS / OVERLAP_WORDS are sized from the measured book word
count (~141.9k words across 117 sections) so the full-book chunk
count lands mid-band (~2000-2300). OVERLAP_WORDS is ~15% of
TARGET_WORDS.

EQUATION GUARD: a candidate chunk boundary is never allowed to fall
inside a matched math delimiter. `equation_safe_boundary` scans the
text up to a candidate split point; if an inline `$...$`, `\\[...\\]`,
or `\\begin{equation}...\\end{equation}` pair straddles the boundary,
the boundary is pushed forward to just past the closing delimiter.
"""
import re

TARGET_WORDS = 70   # fixed-size chunk target, in whitespace words
OVERLAP_WORDS = 10  # overlap between consecutive chunks (~15% of target)

# Ordered list of (open, close) math delimiter pairs. `$` is its own
# open/close, so it is handled separately by counting parity.
_BLOCK_PAIRS = [
    (r"\begin{equation}", r"\end{equation}"),
    (r"\begin{equation*}", r"\end{equation*}"),
    (r"\begin{align}", r"\end{align}"),
    (r"\[", r"\]"),
]


def equation_safe_boundary(text: str, boundary: int) -> int:
    """Return a boundary index >= `boundary` that does not split a math pair.

    Scans `text[:boundary]`. If an inline `$...$` is open (odd count of
    unescaped `$`) or a block environment is open (more opens than
    closes), the boundary is advanced past the next closing delimiter.
    Returns len(text) if no safe boundary exists ahead.
    """
    if boundary >= len(text):
        return len(text)

    prefix = text[:boundary]

    # Inline `$...$` — count unescaped dollar signs. Odd => mid-equation.
    dollars = len(re.findall(r"(?<!\\)\$", prefix))
    if dollars % 2 == 1:
        m = re.search(r"(?<!\\)\$", text[boundary:])
        if m is None:
            return len(text)
        return equation_safe_boundary(text, boundary + m.end())

    # Block environments — for each pair, if more opens than closes
    # precede the boundary, advance past the next matching close.
    for open_tok, close_tok in _BLOCK_PAIRS:
        opens = prefix.count(open_tok)
        closes = prefix.count(close_tok)
        if opens > closes:
            idx = text.find(close_tok, boundary)
            if idx == -1:
                return len(text)
            return equation_safe_boundary(text, idx + len(close_tok))

    return boundary


def _word_spans(text):
    """Yield (start, end) char offsets of whitespace-delimited words."""
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def fixed_size_chunks(text, target_words=TARGET_WORDS,
                      overlap_words=OVERLAP_WORDS):
    """Split `text` into ~target_words chunks with overlap_words overlap.

    Boundaries are nudged by `equation_safe_boundary` so no chunk ends
    mid-equation. Returns a list of chunk strings.
    """
    spans = _word_spans(text)
    if not spans:
        return []
    chunks = []
    step = max(1, target_words - overlap_words)
    i = 0
    while i < len(spans):
        end_i = min(i + target_words, len(spans))
        char_end = spans[end_i - 1][1]
        safe_end = equation_safe_boundary(text, char_end)
        char_start = spans[i][0]
        chunk = text[char_start:safe_end].strip()
        if chunk:
            chunks.append(chunk)
        if end_i >= len(spans):
            break
        # Re-anchor the next start to the word after `safe_end` if the
        # equation guard pushed us forward, else use the overlap step.
        next_word = i + step
        while next_word < len(spans) and spans[next_word][0] < safe_end:
            next_word += 1
        i = next_word if next_word > i else i + step
    return chunks


def chunk_sections(sections, book):
    """Chunk a list of section dicts into ChromaDB-ready chunk records.

    `sections` is a list of dicts:
      {chapter, chapter_title, section, part, page_start, page_end, text}

    Hybrid strategy: the fixed-size splitter is applied to EVERY
    section regardless of size, so the book yields a chunk count in
    plan.yaml's [1500, 3000] band. Splitting runs per-section, so a
    chunk never spans two outline sections (semantic boundaries are
    preserved). Sub-chunks inherit the section's metadata.

    Returns a list of dicts: {text, metadata} where metadata has
    book, chapter (int chapter number; 0 for front/back matter),
    chapter_title, section, part, page_range, chunk_index. ChromaDB
    metadata must be str/int/float/bool — never None; missing string
    fields are "".
    """
    out = []
    for sec in sections:
        text = (sec.get("text") or "").strip()
        if not text:
            continue
        page_range = f"{sec['page_start']}-{sec['page_end']}"
        chapter = sec.get("chapter", 0)
        if chapter is None:
            chapter = 0
        # Hybrid: split every section, regardless of word count.
        for piece in fixed_size_chunks(text):
            out.append({
                "text": piece,
                "metadata": {
                    "book": book,
                    "chapter": chapter,
                    "chapter_title": sec.get("chapter_title") or "",
                    "section": sec.get("section") or "",
                    "part": sec.get("part") or "",
                    "page_range": page_range,
                },
            })
    # Global chunk_index assigned in document order.
    for idx, rec in enumerate(out):
        rec["metadata"]["chunk_index"] = idx
    return out
