#!/usr/bin/env python3
"""
Unit tests for pipeline/embed_and_store.py.

Covers the pure logic only -- dedup, the deterministic stub embedder,
JSONL loading, and the ChromaDB add() payload via a fake collection.
BGE-M3 and ChromaDB are never imported here: the module loads both
lazily, so neither needs to be installed.

Run standalone:
    python3 tests/test_embed_and_store.py
or under pytest:
    pytest tests/test_embed_and_store.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import embed_and_store  # noqa: E402


def _paper(arxiv_id, abstract="An abstract.", **extra):
    paper = {
        "title": "A Title",
        "abstract": abstract,
        "authors": ["Ada Lovelace"],
        "arxiv_id": arxiv_id,
        "semantic_scholar_id": f"s2-{arxiv_id}" if arxiv_id else None,
        "citation_count": 3,
        "category": "cs.GT",
        "publication_date": "2026-05-15",
    }
    paper.update(extra)
    return paper


class FakeCollection:
    """Captures the arguments of a single add() call."""

    name = "papers_recent"

    def __init__(self):
        self.added = None

    def add(self, ids, documents, embeddings, metadatas):
        self.added = {
            "ids": ids,
            "documents": documents,
            "embeddings": embeddings,
            "metadatas": metadatas,
        }


class DedupeTest(unittest.TestCase):

    def test_drops_papers_already_in_collection(self):
        kept, n_dup, n_no_id, n_no_abs = embed_and_store.dedupe(
            [_paper("a"), _paper("b")], existing_ids=["a"])
        self.assertEqual([p["arxiv_id"] for p in kept], ["b"])
        self.assertEqual((n_dup, n_no_id, n_no_abs), (1, 0, 0))

    def test_drops_within_batch_duplicates(self):
        kept, n_dup, _, _ = embed_and_store.dedupe(
            [_paper("a"), _paper("a")], existing_ids=[])
        self.assertEqual(len(kept), 1)
        self.assertEqual(n_dup, 1)

    def test_missing_id_counted_separately_from_duplicates(self):
        """A paper with no arxiv_id is a no-id case, not a duplicate."""
        kept, n_dup, n_no_id, n_no_abs = embed_and_store.dedupe(
            [_paper(None), _paper("b")], existing_ids=[])
        self.assertEqual([p["arxiv_id"] for p in kept], ["b"])
        self.assertEqual((n_dup, n_no_id, n_no_abs), (0, 1, 0))

    def test_drops_papers_without_an_abstract(self):
        kept, _, _, n_no_abs = embed_and_store.dedupe(
            [_paper("a", abstract=""), _paper("b", abstract=None),
             _paper("c")], existing_ids=[])
        self.assertEqual([p["arxiv_id"] for p in kept], ["c"])
        self.assertEqual(n_no_abs, 2)


class MockEmbedderTest(unittest.TestCase):

    def test_dimension_matches_bge_m3(self):
        vectors = embed_and_store._MockEmbedder().encode(["one", "two"])
        self.assertEqual(len(vectors), 2)
        self.assertTrue(all(len(v) == embed_and_store._BGE_M3_DIM for v in vectors))

    def test_deterministic_per_text(self):
        embedder = embed_and_store._MockEmbedder()
        self.assertEqual(embedder.encode(["same"]), embedder.encode(["same"]))
        self.assertNotEqual(embedder.encode(["a"]), embedder.encode(["b"]))

    def test_get_embedder_returns_stub_under_mock_llm(self):
        prior = os.environ.get("MOCK_LLM")
        os.environ["MOCK_LLM"] = "1"
        try:
            embedder = embed_and_store.get_embedder("/unused/path")
        finally:
            if prior is None:
                del os.environ["MOCK_LLM"]
            else:
                os.environ["MOCK_LLM"] = prior
        self.assertIsInstance(embedder, embed_and_store._MockEmbedder)
        self.assertEqual(embedder.name, "BGE-M3")


class LoadPapersTest(unittest.TestCase):

    def test_loads_jsonl_skipping_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "papers.jsonl")
            Path(path).write_text(
                json.dumps(_paper("a")) + "\n\n" + json.dumps(_paper("b")) + "\n",
                encoding="utf-8")
            papers = embed_and_store.load_papers(path)
        self.assertEqual([p["arxiv_id"] for p in papers], ["a", "b"])

    def test_malformed_line_raises_with_line_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.jsonl")
            Path(path).write_text("{not json}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                embed_and_store.load_papers(path)


class StoreTest(unittest.TestCase):

    def test_store_passes_explicit_embeddings_and_scalar_metadata(self):
        collection = FakeCollection()
        papers = [_paper("2405.001"), _paper("2405.002")]
        n = embed_and_store.store(collection, papers, embed_and_store._MockEmbedder())

        self.assertEqual(n, 2)
        self.assertEqual(collection.added["ids"], ["2405.001", "2405.002"])
        self.assertEqual(collection.added["documents"],
                         [p["abstract"] for p in papers])
        # Embeddings are supplied explicitly -- never left to ChromaDB.
        self.assertEqual(len(collection.added["embeddings"]), 2)
        # ChromaDB metadata values must be scalars; authors is joined.
        for meta in collection.added["metadatas"]:
            for value in meta.values():
                self.assertIsInstance(value, (str, int, float, bool))

    def test_store_noop_on_empty_input(self):
        collection = FakeCollection()
        n = embed_and_store.store(collection, [], embed_and_store._MockEmbedder())
        self.assertEqual(n, 0)
        self.assertIsNone(collection.added)


if __name__ == "__main__":
    unittest.main()
