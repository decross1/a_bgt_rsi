#!/usr/bin/env python3
"""
Ad-hoc ChromaDB query helper.

Inspect and query the local ChromaDB store without writing a one-off
script each time. Three modes:

    # list every collection and its row count
    python3 scripts/query_chroma.py --list

    # show a few raw records from a collection
    python3 scripts/query_chroma.py --collection papers_recent --peek 5

    # semantic query (embeds the query text with BGE-M3)
    python3 scripts/query_chroma.py --collection papers_recent \\
        --query "LLM agents in repeated games" --top-k 5

Defaults: --db-path chroma_db, --collection papers_recent,
--bge-m3-weights /mnt/models/bge-m3. Run it with the chroma venv:

    .venv-chroma/bin/python scripts/query_chroma.py --list

Querying always uses the real BGE-M3 embedding function (it must match
how pipeline/embed_and_store.py built the collection); MOCK_LLM is
irrelevant here and not consulted.
"""
import argparse
import sys
import time


def _client(db_path):
    import chromadb
    return chromadb.PersistentClient(path=db_path)


def cmd_list(client):
    cols = client.list_collections()
    if not cols:
        print("(no collections)")
        return
    for c in cols:
        ef = (c.metadata or {}).get("embedding_function", "?")
        print(f"  {c.name:24} count={c.count():<6} embedding_function={ef}")


def cmd_peek(client, name, n):
    col = client.get_collection(name)
    got = col.get(limit=n, include=["documents", "metadatas"])
    print(f"collection {name!r}: {col.count()} records, showing {len(got['ids'])}")
    for rid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"]):
        meta = meta or {}
        print(f"\n  id={rid}  {meta.get('title', '')[:72]}")
        print(f"  {(doc or '')[:200]}...")


def cmd_query(client, name, query, top_k, weights):
    from chromadb.utils import embedding_functions
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=weights)
    col = client.get_collection(name, embedding_function=ef)
    t0 = time.perf_counter()
    res = col.query(query_texts=[query], n_results=top_k)
    dt = (time.perf_counter() - t0) * 1000.0
    print(f"collection {name!r}  query={query!r}  ({dt:.0f} ms)")
    for rank, (rid, meta, doc, dist) in enumerate(zip(
            res["ids"][0], res["metadatas"][0],
            res["documents"][0], res["distances"][0]), 1):
        meta = meta or {}
        print(f"\n  #{rank}  sim={1.0 - dist:.4f}  id={rid}")
        print(f"      {meta.get('title', '')[:76]}")
        print(f"      {(doc or '')[:200]}...")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db-path", default="chroma_db",
                    help="ChromaDB persistent store directory (default: chroma_db)")
    ap.add_argument("--collection", default="papers_recent",
                    help="collection name (default: papers_recent)")
    ap.add_argument("--list", action="store_true",
                    help="list all collections and counts, then exit")
    ap.add_argument("--peek", type=int, metavar="N",
                    help="show N raw records from the collection")
    ap.add_argument("--query", help="semantic query text")
    ap.add_argument("--top-k", type=int, default=5,
                    help="results to return for --query (default: 5)")
    ap.add_argument("--bge-m3-weights", default="/mnt/models/bge-m3",
                    help="BGE-M3 weights for embedding the query")
    args = ap.parse_args(argv)

    client = _client(args.db_path)
    if args.list:
        cmd_list(client)
    elif args.peek is not None:
        cmd_peek(client, args.collection, args.peek)
    elif args.query:
        cmd_query(client, args.collection, args.query, args.top_k,
                  args.bge_m3_weights)
    else:
        ap.error("nothing to do -- pass --list, --peek N, or --query TEXT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
