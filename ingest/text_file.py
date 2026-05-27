#!/usr/bin/env python3
"""text_file.py — ingest a plain-text file (e.g. OCR output) into ChromaDB.

Companion to `ingest/textbook.py`. Same chunking + embedding + persistent
client pattern, but skips PDF text extraction — the input is already a
.txt file. Used for sources whose PDF has no embedded text layer (e.g.
scanned papers OCR'd via tesseract):

  pdftoppm -r 300 input.pdf page -png
  for f in page-*.png; do tesseract "$f" "${f%.png}"; done
  cat page-*.txt > full.txt
  python ingest/text_file.py --text full.txt --collection <name> [--pages N]

Run via `.venv-chroma/bin/python ingest/text_file.py ...`.
"""
from __future__ import annotations

import argparse
import os
import sys

# Make `ingest.chunking` importable when this is run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ingest.chunking import chunk_sections  # noqa: E402

BGE_M3_WEIGHTS = "/mnt/models/bge-m3"
CHROMA_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/chroma_db"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--text", required=True, help="path to the .txt file (e.g. OCR output)")
    ap.add_argument("--collection", required=True, help="ChromaDB collection name")
    ap.add_argument("--pages", type=int, default=0,
                    help="optional page count for metadata; 0 if unknown")
    ap.add_argument("--source-note", default="text-file ingest",
                    help="recorded as metadata.source on the collection")
    args = ap.parse_args()

    text = open(args.text, encoding="utf-8", errors="replace").read()
    if not text.strip():
        print(f"FATAL: {args.text} is empty", file=sys.stderr)
        return 1

    # One synthetic "section" covering the whole document — OCR / text
    # files have no PDF outline to drive section boundaries. The
    # fixed-size splitter inside chunk_sections still runs per-section,
    # so the document still gets sub-chunked properly.
    sections = [{
        "chapter": 0,
        "chapter_title": "(text-file ingest; no outline)",
        "section": args.collection,
        "part": "",
        "page_start": 1,
        "page_end": args.pages or 0,
        "text": text,
    }]
    chunks = chunk_sections(sections, book=args.collection)
    if not chunks:
        print(f"FATAL: chunker produced no chunks from {args.text}", file=sys.stderr)
        return 1

    import chromadb
    from chromadb.utils import embedding_functions

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=BGE_M3_WEIGHTS
    )
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    coll = client.get_or_create_collection(
        name=args.collection,
        embedding_function=ef,
        metadata={"embedding_function": "BGE-M3", "source": args.source_note},
    )
    coll.add(
        documents=[c["text"] for c in chunks],
        ids=[f"{args.collection}-chunk-{c['metadata']['chunk_index']}" for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )
    print(f"collection={args.collection} count={coll.count()} "
          f"chars={len(text)} embedding_function=BGE-M3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
