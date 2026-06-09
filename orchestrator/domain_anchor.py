"""Domain-anchor cosine — the missing off-domain signal for the T1a gate.

The 2026-06-09 lit-falsification battery showed the relevance gate is
lexical-overlap-only and vocabulary-gameable: off-domain probes
`fase_off_01` (overlap 0.127) and `fase_off_02` (0.193) sailed through
while the real bug sat at 0.043. Raw neighbor cosines don't separate
either (BGE-M3 clusters 0.53-0.74). The signal that *does* separate is
the hypothesis's cosine to a GLOBAL CENTROID of the human-curated
foundational corpus — the "domain anchor".

This module is the runtime reader. The anchor itself is built OFFLINE by
`scripts/build_domain_anchor.py` (run serially by the integrator against
the real Chroma store) and lands at `run_state/domain_anchor.json`.

Contract (consumed by orchestrator/nara.py at the two relevance call
sites):

  - load_anchor(path=None)  -> dict | None  (module-level cached per path;
                               None with a logged reason when missing or
                               malformed)
  - anchor_cosine(text)     -> float | None (None when MOCK_LLM is set,
                               the anchor is missing, or embedding fails —
                               each None path logs a DISTINCT reason)

A None anchor_cosine flows into workers/retrieval_relevance.py where the
anchor rules (R3/R4) simply do not fire — the gate degrades to its legacy
lexical behavior, never crashes (explicit fallback, inviolate rule 7).

Embedding reuses the lazily-cached BGE-M3 embedder in
orchestrator/chroma_query.py (`_load_real_client`); no second embedder
load, no re-embedding of the corpus.

Cache note: a load result (including None) is cached for the process
lifetime per path. Orchestrator processes are per-iteration short-lived,
so a freshly built anchor is picked up on the next iteration.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ANCHOR_PATH = REPO_ROOT / "run_state" / "domain_anchor.json"

# Per-path cache: str(path) -> dict | None (None cached too; see module note).
_ANCHOR_CACHE: dict[str, dict | None] = {}


def load_anchor(path: str | Path | None = None) -> dict | None:
    """Load + validate the anchor JSON. Cached per path. None on any problem
    (each with a distinct logged reason); never raises."""
    p = Path(path) if path is not None else DEFAULT_ANCHOR_PATH
    key = str(p)
    if key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[key]

    anchor: dict | None = None
    if not p.exists():
        logger.warning(
            "domain_anchor: anchor file missing at %s "
            "(integrator runs scripts/build_domain_anchor.py to create it); "
            "anchor rules disabled", p,
        )
    else:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "domain_anchor: anchor file unreadable/malformed JSON at %s: %r; "
                "anchor rules disabled", p, exc,
            )
            data = None
        if data is not None:
            vec = data.get("vector") if isinstance(data, dict) else None
            if (
                isinstance(vec, list)
                and len(vec) > 0
                and all(isinstance(x, (int, float)) for x in vec)
                and data.get("dim") == len(vec)
            ):
                anchor = data
            else:
                logger.warning(
                    "domain_anchor: anchor at %s fails shape check "
                    "(need numeric 'vector' with matching 'dim'); "
                    "anchor rules disabled", p,
                )

    _ANCHOR_CACHE[key] = anchor
    return anchor


def anchor_cosine(text: str, path: str | Path | None = None) -> float | None:
    """Cosine of BGE-M3(text) to the domain anchor; None when unavailable.

    None paths (each logged distinctly): MOCK_LLM set; anchor missing or
    malformed; empty/non-str text; embedder load or embed failure; dim
    mismatch. The caller treats None as 'anchor signal unavailable'.
    """
    if os.environ.get("MOCK_LLM"):
        logger.info(
            "domain_anchor: MOCK_LLM set — embedder stubbed; anchor_cosine -> None"
        )
        return None

    anchor = load_anchor(path)
    if anchor is None:
        logger.warning("domain_anchor: no usable anchor; anchor_cosine -> None")
        return None

    if not isinstance(text, str) or not text.strip():
        logger.warning("domain_anchor: empty/non-str text; anchor_cosine -> None")
        return None

    try:
        # One consumer: import chroma_query's private lazy loader rather than
        # widening its public surface (Limb D owns that file this session).
        from orchestrator.chroma_query import _load_real_client
        embedder, _ = _load_real_client()
        vec = [float(x) for x in embedder([text])[0]]
    except Exception as exc:
        logger.warning(
            "domain_anchor: embedding failed (%r); anchor_cosine -> None", exc
        )
        return None

    avec = anchor["vector"]
    if len(vec) != len(avec):
        logger.warning(
            "domain_anchor: dim mismatch (embed=%d anchor=%d); anchor_cosine -> None",
            len(vec), len(avec),
        )
        return None

    dot = sum(a * b for a, b in zip(vec, avec))
    na = math.sqrt(sum(a * a for a in vec))
    nb = math.sqrt(sum(b * b for b in avec))
    if na == 0.0 or nb == 0.0:
        logger.warning(
            "domain_anchor: zero-norm vector (embed=%s anchor=%s); "
            "anchor_cosine -> None", na, nb,
        )
        return None
    return round(dot / (na * nb), 4)
