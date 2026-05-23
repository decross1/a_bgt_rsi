"""
Day 6 worker: summarize a paper from the papers_recent ChromaDB collection
in ~100 words via Gemma 4 (called through agent_wrapper.wrapper.call_sync).

Runs in a child process spawned by
orchestrator.openclaw_runner.OrchestratorClient. The wrapper record is
appended to logs/day6.jsonl with parent_request_id = the orchestrator's
worker_invocation request_id, so tools/inspect_run.py can stitch the full
causal chain (orchestrator_dispatch -> worker_invocation -> wrapper_call
-> orchestrator_receipt).
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# papers_recent stores one record per paper; chunk_id == arxiv_id, the
# abstract is in `documents`, metadata holds title/category/etc.
_COLLECTION = "papers_recent"


def _load_paper(arxiv_id, db_path):
    """Return (abstract, title, category) for arxiv_id from papers_recent.
    Raises ValueError on a missing id or an empty abstract."""
    import chromadb
    client = chromadb.PersistentClient(path=str(db_path))
    col = client.get_collection(_COLLECTION)
    res = col.get(ids=[arxiv_id])
    if not res["ids"]:
        raise ValueError(
            f"arxiv_id {arxiv_id!r} not in collection {_COLLECTION!r}")
    abstract = res["documents"][0] or ""
    if not abstract.strip():
        raise ValueError(
            f"arxiv_id {arxiv_id!r}: empty abstract in {_COLLECTION!r}")
    md = res["metadatas"][0] or {}
    return abstract, md.get("title", ""), md.get("category", "")


def summarize(arxiv_id, log_path, db_path, parent_request_id):
    """Worker entry. Returns a dict the orchestrator unpacks:
      {status: 'passed'|'error', errors: [str], summary: str|None,
       wrapper_request_id: str|None}
    No exceptions escape -- callers in the parent process must not crash
    on worker failure."""
    try:
        abstract, title, category = _load_paper(arxiv_id, db_path)
    except Exception as exc:
        return {
            "status": "error",
            "errors": [f"load_paper failed for {arxiv_id}: "
                       f"{type(exc).__name__}: {exc}"],
            "summary": None,
            "wrapper_request_id": None,
        }

    try:
        from agent_wrapper.wrapper import call_sync
        prompt = (
            "Summarize the following paper abstract in approximately 100 "
            "words. Preserve technical specifics (methods, claims, "
            "quantities). Plain prose; no preamble, no bullet list.\n\n"
            f"Title: {title}\n"
            f"Category: {category}\n\n"
            f"Abstract:\n{abstract}"
        )
        record = call_sync(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=300,
            caller_tag="day6_summarize_paper",
            parent_request_id=parent_request_id,
            log_path=str(log_path),
        )
    except Exception as exc:
        return {
            "status": "error",
            "errors": [f"wrapper call_sync failed for {arxiv_id}: "
                       f"{type(exc).__name__}: {exc}"],
            "summary": None,
            "wrapper_request_id": None,
        }

    return {
        "status": "passed",
        "errors": [],
        "summary": record["completion"],
        "wrapper_request_id": record["request_id"],
    }
