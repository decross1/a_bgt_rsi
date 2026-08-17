"""FP8 A/B window battery driver (D-072 Windows A/B).

Spec: docs/qwen_fp8_windows_plan.md. Runs the 22-case lit-falsification
battery against a vLLM OpenAI endpoint (:8002), SENTINELS FIRST in the
plan's pinned order, evaluates the plan's STOP conditions after every
call, and writes one frozen-provenance JSON artifact per arm to
bench/fp8_ab/runs/.

Reused, not forked: the stage-3a case contract (cases.jsonl); attack()'s
parse logic composed from the same imported primitives (see
parse_attack_completion); attack()'s exact prompt bytes (persona +
_format_neighbors); parse_prometheus for the /metrics scrape (counter
names copied verbatim from vllm_metrics.py:33-36 rather than importing
ui-private names across the session boundary).

Determinism across arms is by construction: case order = pinned sentinels
then cases.jsonl file order; per-case seed = --seed base + the case's
index IN cases.jsonl (file position, not run position — a sentinel keeps
its seed between --sentinels-only and --full). Sampling pinned 0.2/0.95
(production skeptic sampling, frozen). The driver makes NO LLM-wrapper
calls: all I/O goes through the injected HTTP + retrieval callables
(tests inject fakes; the CLI wires the real ones).

Run: env -u MOCK_LLM .venv-chroma/bin/python -m bench.fp8_ab.driver \
  --endpoint http://127.0.0.1:8002/v1 --model qwen3.6-27b-fp8 \
  --arm-label fp8_36 --image-digest sha256:... --model-revision e89b... \
  --sentinels-only
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_wrapper.cleanup import strip_channel_markup  # noqa: E402
from orchestrator.novelty_skeptic import (  # noqa: E402
    ALLOWED_ATTACK_VERDICTS, ATTACK_RETRIEVAL_K, QWEN_ATTACK_PERSONA)
from ui.sampler.sources.vllm_metrics import parse_prometheus  # noqa: E402
from workers.novelty_skeptic import (  # noqa: E402
    _extract_json_object, _format_neighbors)

CASES_PATH = REPO_ROOT / "experiments/lit_falsification_battery/cases.jsonl"
RUNS_DIR = Path(__file__).resolve().parent / "runs"

# The six pinned sentinels, IN THE PLAN'S ORDER (qwen_fp8_windows_plan.md
# Window B step 1), resolved to exact cases.jsonl ids at build time
# 2026-08-17: the plan's shorthand "falsifiable_01" names the unique case
# falsifiable_01_finite_pd_cooperate (the D-044 kill pair's first member;
# stage3a_driver.py scores exactly that id); the other five are verbatim.
# resolve_sentinels() re-verifies against the live file — never guesses.
SENTINEL_IDS = (
    "novel_on_01_quant_lockin",
    "redisc_on_01_tft_reciprocity",
    "canary_on_01_ultimatum_plain",
    "falsifiable_01_finite_pd_cooperate",
    "falsifiable_02_dominant_tft",
    "camo_off_04_raft_punishment",
)

# Frozen sampling (plan Window B step 2) + caps.
TEMPERATURE = 0.2
TOP_P = 0.95
DEFAULT_CAP = 12288
DEFAULT_SEED_BASE = 20260818
WALL_CAP_S = 600.0        # plan STOP: per-call wall > 10 min
HTTP_TIMEOUT_S = 630.0    # above the wall cap so the wall check fires first

# Spec-decode counter candidates — copied verbatim from
# ui/sampler/sources/vllm_metrics.py:33-36 (the scrape pattern this reuses).
SPEC_ACCEPTED_CANDIDATES = ("vllm:spec_decode_num_accepted_tokens_total",
                            "vllm:spec_decode_num_accepted_tokens")
SPEC_DRAFT_CANDIDATES = ("vllm:spec_decode_num_draft_tokens_total",
                         "vllm:spec_decode_num_draft_tokens")


class SentinelResolutionError(RuntimeError):
    """A pinned sentinel id has no exact match in cases.jsonl."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cases(path: Path | str = CASES_PATH) -> tuple[list[dict], str]:
    """(cases, sha256-of-file-bytes) — the sha goes into provenance."""
    path = Path(path)
    raw = path.read_bytes()
    cases = [json.loads(line) for line in raw.decode("utf-8").splitlines()
             if line.strip()]
    return cases, hashlib.sha256(raw).hexdigest()


def resolve_sentinels(available_ids: set[str]) -> None:
    """Every pinned sentinel must match a case id EXACTLY; any mismatch
    raises listing candidates (prefix relatives + fuzzy near-misses).
    Never substitutes — the fix is a human re-pin, not a guess (plan)."""
    problems = []
    for sid in SENTINEL_IDS:
        if sid in available_ids:
            continue
        candidates = sorted(
            cid for cid in available_ids
            if cid.startswith(sid) or sid.startswith(cid)
        ) or difflib.get_close_matches(sid, sorted(available_ids), n=5,
                                       cutoff=0.4)
        problems.append(f"sentinel {sid!r} has NO exact match in cases.jsonl;"
                        f" candidates: {candidates or '(none)'}")
    if problems:
        raise SentinelResolutionError(
            "pinned sentinel resolution failed — refusing to guess "
            "(docs/qwen_fp8_windows_plan.md Window B step 1):\n  "
            + "\n  ".join(problems))


def build_run_order(cases: list[dict], full: bool) -> list[tuple[int, dict]]:
    """[(file_index, case), ...]: the six sentinels in plan order, then
    (--full only) every remaining case in cases.jsonl file order."""
    resolve_sentinels({c["case_id"] for c in cases})
    by_id = {c["case_id"]: (i, c) for i, c in enumerate(cases)}
    order = [by_id[sid] for sid in SENTINEL_IDS]
    if full:
        order += [(i, c) for i, c in enumerate(cases)
                  if c["case_id"] not in SENTINEL_IDS]
    return order


def prompt_messages(case: dict, neighbors: list[dict]) -> list[dict]:
    """EXACTLY attack()'s prompt assembly (novelty_skeptic.py:224-231),
    Qwen persona — identical prompt bytes are the frozen-provenance basis."""
    user_content = (
        f"Hypothesis:\n{case['hypothesis'].strip()}\n\n"
        f"Your retrieved neighbors ({len(neighbors)}):\n"
        f"{_format_neighbors(neighbors)}\n"
    )
    return [{"role": "system", "content": QWEN_ATTACK_PERSONA},
            {"role": "user", "content": user_content}]


def prompt_sha256(messages: list[dict]) -> str:
    """sha256 over canonical JSON of the messages array (sorted keys, no
    whitespace, raw unicode) — the per-case prompt fingerprint."""
    canon = json.dumps(messages, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    return _sha256_text(canon)


def parse_attack_completion(completion: str, valid_doc_ids: set[str]) -> dict:
    """attack()'s completion->verdict block (novelty_skeptic.py:259-298),
    composed from the same imported primitives: extractor, channel-markup
    fallback, enum check, citation verification, refuted-without-doc
    downgrade (rule 4). parse_status derives exactly as stage3a_driver
    derives raw_status (the "(unparseable or off-enum" prefix)."""
    completion = completion or ""
    payload = _extract_json_object(completion)
    if payload is None:
        payload = _extract_json_object(strip_channel_markup(completion))
    if (not isinstance(payload, dict)
            or payload.get("attack_verdict") not in ALLOWED_ATTACK_VERDICTS):
        return {
            "attack_verdict": "inconclusive",
            "rationale": (
                "(unparseable or off-enum skeptic output; defaulting to "
                "inconclusive) " + strip_channel_markup(completion[:800] or "")
            ).strip(),
            "contradicting_doc_id": None,
            "parse_status": "unparseable",
        }
    verdict = payload["attack_verdict"]
    rationale = payload.get("rationale")
    if not isinstance(rationale, str):
        rationale = ""
    rationale = rationale.strip()[:2000]
    doc_id_raw = payload.get("contradicting_doc_id")
    doc_id = (doc_id_raw.strip() or None) if isinstance(doc_id_raw, str) else None
    if doc_id is not None and doc_id not in valid_doc_ids:
        doc_id = None  # unverifiable citation
    if verdict == "refuted" and doc_id is None:
        return {
            "attack_verdict": "inconclusive",
            "rationale": (
                "(skeptic claimed 'refuted' but cited no doc_id from its "
                "retrieved set; downgraded) " + rationale).strip(),
            "contradicting_doc_id": None,
            "parse_status": "ok",
        }
    if verdict != "refuted":
        doc_id = None
    return {"attack_verdict": verdict, "rationale": rationale,
            "contradicting_doc_id": doc_id, "parse_status": "ok"}


def metrics_url_of(endpoint: str) -> str:
    """http://host:port/v1 -> http://host:port/metrics"""
    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}/metrics"


def scrape_spec_counters(http, metrics_url: str) -> dict:
    """Spec-decode acceptance counters via /metrics (vllm_metrics pattern).
    Absent counters stay None (JSON null) — MTP-off arms export none; null
    means 'not exported', NEVER a fabricated zero. A failed scrape records
    scrape_error and nulls; it does not abort the arm."""
    out = {"spec_decode_num_accepted_tokens_total": None,
           "spec_decode_num_draft_tokens_total": None,
           "scraped_at": _utc_now(), "scrape_error": None}
    try:
        status, body = http("GET", metrics_url, None, 10.0)
    except Exception as exc:  # noqa: BLE001 — recorded, never invented
        out["scrape_error"] = f"{type(exc).__name__}: {exc}"
        return out
    if status != 200:
        out["scrape_error"] = f"HTTP {status}"
        return out
    metrics = parse_prometheus(body if isinstance(body, str) else str(body))
    for key, names in (
            ("spec_decode_num_accepted_tokens_total", SPEC_ACCEPTED_CANDIDATES),
            ("spec_decode_num_draft_tokens_total", SPEC_DRAFT_CANDIDATES)):
        for name in names:
            if name in metrics:
                out[key] = metrics[name]
                break
    return out


def _default_http(method: str, url: str, payload=None,
                  timeout: float = HTTP_TIMEOUT_S):
    """The ONE real HTTP seam — tests inject a fake with this signature.
    Returns (status_code, parsed_json_or_text); raises on transport error."""
    import requests  # lazy: hermetic tests never import it
    resp = requests.request(method, url, json=payload, timeout=timeout)
    ctype = resp.headers.get("content-type", "")
    body = resp.json() if "json" in ctype else resp.text
    return resp.status_code, body


def _default_retrieve(hypothesis_text: str) -> list[dict]:
    """attack()'s own-retrieval step (novelty_skeptic.py:200-219): default
    collections, k=ATTACK_RETRIEVAL_K. Raises on anything unusable — a
    retrieval hole breaks frozen provenance, so the arm STOPS fail-closed
    rather than running an ungrounded prompt."""
    from orchestrator.chroma_query import query_top_k  # lazy: needs chroma
    ret = query_top_k(hypothesis_text.strip(), k=ATTACK_RETRIEVAL_K)
    neighbors = (ret.get("result") or {}).get("neighbors") or []
    if ret.get("status") != "passed" or not neighbors:
        raise RuntimeError(
            f"retrieval unusable (status={ret.get('status')!r}, "
            f"errors={ret.get('errors')!r})")
    return neighbors


@dataclass
class RunConfig:
    arm_label: str
    model: str
    endpoint: str
    cap: int = DEFAULT_CAP
    full: bool = False
    seed_base: int = DEFAULT_SEED_BASE
    image_digest: str = ""
    model_revision: str = ""
    cases_path: str = str(CASES_PATH)
    cases_sha256: str = ""


def run_case(idx: int, case: dict, cfg: RunConfig, http, retrieve, clock):
    """One battery call. Returns (record, stop) where stop is None or
    {"reason", "case_id", "detail"} — any non-None stop aborts the arm."""
    rec = {
        "case_id": case["case_id"],
        "case_index": idx,
        "sentinel": case["case_id"] in SENTINEL_IDS,
        "expected_critic": case.get("expected_critic"),
        "seed": cfg.seed_base + idx,
        "sampling": {"temperature": TEMPERATURE, "top_p": TOP_P,
                     "max_tokens": cfg.cap},
    }

    def stop(reason, detail):
        return rec, {"reason": reason, "case_id": case["case_id"],
                     "detail": detail}

    try:
        neighbors = retrieve(case["hypothesis"])
    except Exception as exc:  # noqa: BLE001 — recorded as the stop reason
        return stop("retrieval_error", f"{type(exc).__name__}: {exc}")
    if not neighbors:
        return stop("retrieval_error", "retrieval returned zero neighbors")
    rec["retrieved_docs"] = [
        {"doc_id": n.get("doc_id"),
         "sha256": _sha256_text(n.get("chunk_text") or "")}
        for n in neighbors]
    valid_doc_ids = {n.get("doc_id") for n in neighbors
                     if isinstance(n.get("doc_id"), str)}
    rec["retrieved_doc_ids"] = sorted(valid_doc_ids)

    messages = prompt_messages(case, neighbors)
    rec["prompt_sha256"] = prompt_sha256(messages)
    payload = {"model": cfg.model, "messages": messages,
               "temperature": TEMPERATURE, "top_p": TOP_P,
               "max_tokens": cfg.cap, "seed": rec["seed"]}

    t0 = clock()
    try:
        status, body = http("POST",
                            cfg.endpoint.rstrip("/") + "/chat/completions",
                            payload, HTTP_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — transport failure = STOP
        rec["wall_s"] = round(clock() - t0, 3)
        reason = "cuda_error" if "cuda" in str(exc).lower() else "http_error"
        return stop(reason, f"{type(exc).__name__}: {exc}")
    wall = clock() - t0
    rec["wall_s"] = round(wall, 3)
    rec["http_status"] = status

    if status != 200:
        body_text = body if isinstance(body, str) else json.dumps(body)
        rec["error_body_head"] = body_text[:400]
        lowered = body_text.lower()
        reason = ("cuda_error"
                  if "cuda" in lowered or "out of memory" in lowered
                  else "http_error")
        return stop(reason, f"HTTP {status}: {body_text[:200]}")
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        keys = sorted(body) if isinstance(body, dict) else type(body).__name__
        return stop("missing_call_record",
                    f"response lacks choices[0].message; got: {keys}")

    usage = body.get("usage") or {}
    out_tokens = usage.get("completion_tokens")
    rec["output_tokens"] = out_tokens
    rec["tok_s"] = (round(out_tokens / wall, 2)
                    if isinstance(out_tokens, (int, float)) and wall > 0
                    else None)

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return stop("empty_completion",
                    f"completion empty (output_tokens={out_tokens})")

    parsed = parse_attack_completion(content, valid_doc_ids)
    rec.update({"parse_status": parsed["parse_status"],
                "attack_verdict": parsed["attack_verdict"],
                "contradicting_doc_id": parsed["contradicting_doc_id"],
                "rationale_head": parsed["rationale"][:160]})

    if wall > WALL_CAP_S:
        return stop("wall_exceeded", f"{wall:.1f}s > {WALL_CAP_S:.0f}s cap")
    return rec, None


def run_arm(cases: list[dict], cfg: RunConfig, http=None, retrieve=None,
            clock=time.perf_counter) -> dict:
    """Run one arm; returns the artifact dict (partial when stopped)."""
    http = http or _default_http
    retrieve = retrieve or _default_retrieve
    order = build_run_order(cases, cfg.full)   # raises before any call
    murl = metrics_url_of(cfg.endpoint)
    artifact = {
        "schema": "fp8_ab.battery.v1",
        "generated_at": _utc_now(),
        "arm_label": cfg.arm_label,
        "mode": "full" if cfg.full else "sentinels_only",
        "provenance": {
            "image_digest": cfg.image_digest,
            "model_revision": cfg.model_revision,
            "endpoint": cfg.endpoint,
            "served_model": cfg.model,
            "cases_path": str(cfg.cases_path),
            "cases_sha256": cfg.cases_sha256,
            "sentinel_ids": list(SENTINEL_IDS),
            "seed_base": cfg.seed_base,
            "sampling": {"temperature": TEMPERATURE, "top_p": TOP_P,
                         "max_tokens": cfg.cap},
            "wall_cap_s": WALL_CAP_S,
            "effective_config": asdict(cfg),
        },
        "metrics_before": scrape_spec_counters(http, murl),
        "cases": [],
        "stop_reason": None,
        "completed": False,
    }
    t0 = clock()
    for idx, case in order:
        rec, stop = run_case(idx, case, cfg, http, retrieve, clock)
        artifact["cases"].append(rec)
        if stop is not None:
            artifact["stop_reason"] = stop
            print(f"STOP [{stop['reason']}] at {stop['case_id']}: "
                  f"{stop['detail']}", flush=True)
            break
        print(f"[{len(artifact['cases']):2}/{len(order)}] "
              f"{rec['case_id']:38} -> {rec['attack_verdict']} "
              f"({rec['wall_s']}s, {rec['tok_s']} tok/s)", flush=True)
    else:
        artifact["completed"] = True
    artifact["metrics_after"] = scrape_spec_counters(http, murl)
    artifact["total_wall_s"] = round(clock() - t0, 1)
    ran = artifact["cases"]
    artifact["summary"] = {
        "cases_run": len(ran),
        "cases_planned": len(order),
        "parse_ok": sum(1 for r in ran if r.get("parse_status") == "ok"),
        "unparseable": [r["case_id"] for r in ran
                        if r.get("parse_status") == "unparseable"],
        "verdicts": {r["case_id"]: r.get("attack_verdict") for r in ran},
    }
    return artifact


def write_artifact(artifact: dict, out_path: Path | str) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False))
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="FP8 A/B window battery driver (D-072; "
                    "docs/qwen_fp8_windows_plan.md)")
    ap.add_argument("--endpoint", default="http://127.0.0.1:8002/v1")
    ap.add_argument("--model", required=True,
                    help="served model name (per-arm)")
    ap.add_argument("--arm-label", required=True)
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED_BASE,
                    help="seed base; per-case seed = base + cases.jsonl index")
    ap.add_argument("--image-digest", required=True,
                    help="eval image digest (frozen provenance)")
    ap.add_argument("--model-revision", required=True,
                    help="weights revision (frozen provenance)")
    ap.add_argument("--cases", default=str(CASES_PATH))
    ap.add_argument("--out", default=None,
                    help="artifact path (default runs/<arm>_<utc>.json)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sentinels-only", action="store_true")
    mode.add_argument("--full", action="store_true")
    args = ap.parse_args(argv)

    if os.environ.get("MOCK_LLM"):
        print("REFUSE: MOCK_LLM is set — stubbed embedders would silently "
              "fake the skeptic's retrieval (provenance poison). Re-run "
              "with `env -u MOCK_LLM` (CLAUDE.md rule 10).")
        return 2

    cases, cases_sha = load_cases(args.cases)
    cfg = RunConfig(arm_label=args.arm_label, model=args.model,
                    endpoint=args.endpoint, cap=args.cap, full=args.full,
                    seed_base=args.seed, image_digest=args.image_digest,
                    model_revision=args.model_revision,
                    cases_path=args.cases, cases_sha256=cases_sha)
    artifact = run_arm(cases, cfg)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else RUNS_DIR / f"{args.arm_label}_{stamp}.json"
    write_artifact(artifact, out)
    print(json.dumps(artifact["summary"], indent=1))
    print("stop_reason:", artifact["stop_reason"])
    print("wrote", out)
    return 0 if artifact["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
