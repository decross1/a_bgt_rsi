"""Doc-id → human title resolution for retrieval surfaces.

Why this exists (owner request 2026-08-18, looking at iter-2026-08-18-005's
retrieval card): a neighbor list of bare ids — "2604.15267",
"s2:3f745f82…", "osborne_rubinstein-chunk-850" — tells the reader nothing.
Every id the retrieval worker emits has a real title sitting in Chroma
metadata; this module lets the frontend ask for it in one batch call.

``GET /api/doc_titles?ids=a,b,c`` (comma-separated, ≤50 ids) →
``{id: {title, kind, detail}}``:

  - bare arXiv id ("2404.08492", optionally "…v2") → ``papers_recent``
    metadata, fallback ``ml_intern_fetched``; kind ``paper``; detail is the
    publication year;
  - "s2:<sha>" (Semantic Scholar) → ``ml_intern_fetched``; kind ``s2``;
  - "<stem>-chunk-N" (foundational book chunks, incl. the
    "<stem>_compress-chunk-N" variants) → the owning collection's own
    metadata, composed as "<Book label> — <chapter_title> (pp <page_range>)";
    kind ``book``; detail is the section.

The chunk-id stem does NOT equal the collection name in general
(weibull_egt's ids are "evolutionary-game-theory_compress-chunk-N",
young_1993's are "the_evolution_of_conventions-chunk-N", …), so the
stem → collection map is DERIVED once by listing collections and peeking a
single id from each — never guessed from the id text.

Unresolved ids (unknown shape, or simply not in any collection) are ABSENT
from the response — the frontend keeps the bare id. An over-cap batch is an
explicit 400 (validations are never silently coerced). A missing/broken
Chroma store is an explicit 503, never a silent empty map — the production
:8700 venv (``ui/.venv``) has no ``chromadb``; only a backend served from
``.venv-chroma`` can resolve titles, and the frontend degrades to bare ids
on any non-200.

READ-ONLY metadata access: id-based ``collection.get`` only, and NEVER
``query()`` — no embedding function is ever attached, so the BGE-M3
embedder (~3-5 s + GPU) is never loaded from this path. If
``orchestrator.chroma_query`` already holds a live client in this process
we reuse it; otherwise a metadata-only ``PersistentClient`` is opened on
the SAME path ``chroma_query`` uses.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

MAX_IDS = 50
CACHE_SIZE = 2048

ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")
CHUNK_RE = re.compile(r"^(?P<stem>.+)-chunk-\d+$")

# Paper-shaped collections, in lookup order (curated live-arXiv first).
PAPER_COLLECTIONS = ("papers_recent", "ml_intern_fetched")

# Human-readable labels for the foundational collections. Fallback for an
# unlisted collection is the chunk's own `book` metadata (the raw stem) —
# honest, just less pretty.
BOOK_LABELS = {
    "osborne_rubinstein": "Osborne & Rubinstein, A Course in Game Theory",
    "camerer_bgt": "Camerer, Behavioral Game Theory",
    "weibull_egt": "Weibull, Evolutionary Game Theory",
    "blume_1995": "Blume 1995, Statistical Mechanics of Strategic Interaction",
    "ellison_1993": "Ellison 1993, Learning, Local Interaction, and Coordination",
    "hofbauer_sigmund_1998":
        "Hofbauer & Sigmund 1998, Evolutionary Games and Population Dynamics",
    "kandori_mailath_rob_1993":
        "Kandori, Mailath & Rob 1993, Learning, Mutation, and Long Run "
        "Equilibria in Games",
    "young_1993": "Young 1993, The Evolution of Conventions",
    "van_damme_1994": "van Damme 1994, Evolutionary Game Theory",
}

_PRIMARY_REPO = Path("/home/decross1/projects/a_bgt_rsi")


def _default_chroma_path() -> Path:
    """The SAME path orchestrator.chroma_query uses, when importable."""
    try:
        from orchestrator.chroma_query import CHROMA_PATH
        return Path(CHROMA_PATH)
    except Exception:
        pass
    local = Path(__file__).resolve().parents[2] / "chroma_db"
    # A worktree checkout has no chroma_db/ — the store lives in the
    # primary checkout (it is git-ignored, never versioned).
    return local if local.exists() else _PRIMARY_REPO / "chroma_db"


def _default_client_factory():
    """Reuse chroma_query's already-live client if this process has one
    (never triggers its embedder load — we only read the cached global);
    else open a metadata-only PersistentClient on the same path."""
    try:
        from orchestrator import chroma_query
        if chroma_query._CLIENT is not None:
            return chroma_query._CLIENT
    except Exception:
        pass
    import chromadb  # may raise ModuleNotFoundError → honest 503 upstream
    return chromadb.PersistentClient(path=str(_default_chroma_path()))


def _first_meta(got: Any) -> dict | None:
    """The (ids, metadatas) pair of a collection.get, defensively read."""
    if not isinstance(got, dict) or not got.get("ids"):
        return None
    metas = got.get("metadatas") or []
    meta = metas[0] if metas else {}
    return meta if isinstance(meta, dict) else {}


def _s(meta: dict, key: str) -> str:
    v = meta.get(key)
    return v.strip() if isinstance(v, str) else ""


class _Resolver:
    """Lazy, cached, read-only id → title lookup over one Chroma client."""

    def __init__(self, client_factory: Callable[[], Any], cache_size: int):
        self._factory = client_factory
        self._client: Any = None
        self._collections: dict[str, Any] = {}   # name -> handle (or None)
        self._stem_map: dict[str, str] | None = None  # chunk stem -> coll name
        self._cache: OrderedDict[str, dict | None] = OrderedDict()
        self._cache_size = cache_size

    # ── plumbing ──────────────────────────────────────────────────────────
    def _get_client(self) -> Any:
        if self._client is None:
            try:
                self._client = self._factory()
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"chroma unavailable: {type(exc).__name__}: {exc}",
                ) from exc
        return self._client

    def _collection(self, name: str) -> Any | None:
        if name not in self._collections:
            try:
                self._collections[name] = self._get_client().get_collection(name)
            except HTTPException:
                raise
            except Exception:
                self._collections[name] = None
        return self._collections[name]

    def _stems(self) -> dict[str, str]:
        """Derive chunk-id stem → collection name ONCE, by peeking one id
        from every non-paper collection. Collections whose ids are not
        chunk-shaped (scratch/test collections) simply don't map."""
        if self._stem_map is None:
            stems: dict[str, str] = {}
            for coll in self._get_client().list_collections():
                name = coll if isinstance(coll, str) else getattr(coll, "name", "")
                if not name or name in PAPER_COLLECTIONS:
                    continue
                handle = self._collection(name)
                if handle is None:
                    continue
                try:
                    got = handle.get(limit=1, include=[])
                    ids = got.get("ids") if isinstance(got, dict) else None
                except Exception:
                    continue
                sample = ids[0] if ids else ""
                m = CHUNK_RE.match(sample) if isinstance(sample, str) else None
                if m:
                    stems[m.group("stem")] = name
            self._stem_map = stems
        return self._stem_map

    # ── per-family lookups (return None = confirmed unresolved) ──────────
    def _lookup_paper(self, doc_id: str, kind: str) -> dict | None:
        candidates = [doc_id]
        m = ARXIV_RE.match(doc_id)
        if m and m.group(2):
            candidates.append(m.group(1))  # "2404.08492v2" → bare form too
        for name in PAPER_COLLECTIONS:
            handle = self._collection(name)
            if handle is None:
                continue
            for cand in candidates:
                meta = _first_meta(handle.get(ids=[cand], include=["metadatas"]))
                if meta is None:
                    continue
                title = _s(meta, "title")
                if not title:
                    return None
                year = _s(meta, "publication_date")[:4]
                return {"title": title, "kind": kind, "detail": year}
        return None

    def _lookup_book(self, doc_id: str) -> dict | None:
        m = CHUNK_RE.match(doc_id)
        if m is None:
            return None
        coll_name = self._stems().get(m.group("stem"))
        if coll_name is None:
            return None
        handle = self._collection(coll_name)
        if handle is None:
            return None
        meta = _first_meta(handle.get(ids=[doc_id], include=["metadatas"]))
        if meta is None:
            return None
        label = BOOK_LABELS.get(coll_name) or _s(meta, "book") or coll_name
        title = label
        chapter = _s(meta, "chapter_title")
        if chapter:
            title += f" — {chapter}"
        pages = _s(meta, "page_range")
        if pages:
            title += f" (pp {pages})"
        return {"title": title, "kind": "book", "detail": _s(meta, "section")}

    def _resolve_uncached(self, doc_id: str) -> dict | None:
        if ARXIV_RE.match(doc_id):
            return self._lookup_paper(doc_id, "paper")
        if doc_id.startswith("s2:"):
            return self._lookup_paper(doc_id, "s2")
        return self._lookup_book(doc_id)  # unknown shapes fall out as None

    # ── public ────────────────────────────────────────────────────────────
    def resolve(self, doc_id: str) -> dict | None:
        if doc_id in self._cache:
            self._cache.move_to_end(doc_id)
            return self._cache[doc_id]
        result = self._resolve_uncached(doc_id)
        self._cache[doc_id] = result  # misses cached too (confirmed absent)
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result


def register(app, *, client_factory: Callable[[], Any] | None = None,
             cache_size: int = CACHE_SIZE) -> APIRouter:
    """Attach the doc-titles router (register-fn idiom, as served_models)."""
    resolver = _Resolver(client_factory or _default_client_factory, cache_size)
    router = APIRouter(prefix="/api", tags=["doc_titles"])

    @router.get("/doc_titles")
    def doc_titles(ids: str = ""):
        id_list = [s.strip() for s in ids.split(",") if s.strip()]
        if len(id_list) > MAX_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"too many ids: {len(id_list)} > {MAX_IDS}")
        out: dict[str, dict] = {}
        for doc_id in dict.fromkeys(id_list):  # dedupe, order preserved
            info = resolver.resolve(doc_id)
            if info is not None:
                out[doc_id] = info
        return out

    app.include_router(router)
    return router
