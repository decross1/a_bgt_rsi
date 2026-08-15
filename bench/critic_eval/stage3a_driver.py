"""Stage-3a skeptic-ladder sweep for the Qwen A/B window (one-shot driver).

Runs orchestrator.novelty_skeptic.attack (backend vllm-qwen, i.e. whatever
model is serving on :8001) over ALL 22 lit-falsification battery cases and
scores the D-044 ladder criteria VERBATIM (docs/skeptic_ladder.md):
  kill          — falsifiable_01_finite_pd_cooperate AND
                  falsifiable_02_dominant_tft both `refuted` WITH a
                  contradicting_doc_id
  no_false_kill — novel_on_01_quant_lockin NOT `refuted`
                  (survives_attack preferred; inconclusive acceptable+logged)
  liveness      — zero unparseable/empty completions across the sweep
"Close" is a FAIL (rule 4). Results -> bench/critic_eval/runs/.

Run: env -u MOCK_LLM .venv-chroma/bin/python <this file> <served_model_label>
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/home/decross1/projects/a_bgt_rsi")
sys.path.insert(0, str(REPO))

from orchestrator.novelty_skeptic import attack  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "unlabeled"

# A/B seam: the registry hard-pins vllm-qwen to the 3.6 model name
# (agent_wrapper/wrapper.py:96-100), but the window serves whichever model
# `label` names on :8001. Re-register so every call targets — and LOGS —
# the actually-served model (first 3.8 run failed 22/22 on the name
# mismatch; the liveness check caught it exactly as designed).
if label != "unlabeled":
    from agent_wrapper.backends import register_backend
    from agent_wrapper.backends.ollama_openai import OllamaBackend
    import agent_wrapper.wrapper  # noqa: F401  (ensures base registrations ran)
    register_backend(OllamaBackend(
        name="vllm-qwen",
        base_url="http://127.0.0.1:8001/v1",
        model=label,
    ))
cases = [json.loads(l) for l in
         open(REPO / "experiments/lit_falsification_battery/cases.jsonl")]

rows = []
t0 = time.perf_counter()
for i, c in enumerate(cases, 1):
    t = time.perf_counter()
    r = attack(c["hypothesis"], iteration_id=f"qwen_ab_{label}_{c['case_id']}")
    rows.append({
        "case_id": c["case_id"],
        "expected_critic": c["expected_critic"],
        "verdict": r.get("verdict"),
        "contradicting_doc_id": r.get("contradicting_doc_id"),
        "reason_head": str(r.get("reason") or r.get("rationale") or "")[:160],
        "raw_status": r.get("status"),
        "seconds": round(time.perf_counter() - t, 1),
    })
    print(f"[{i:2}/22] {c['case_id']:38} -> {r.get('verdict')} "
          f"({rows[-1]['seconds']}s)", flush=True)

by = {r["case_id"]: r for r in rows}
kill_ok = all(
    by[cid]["verdict"] == "refuted" and by[cid]["contradicting_doc_id"]
    for cid in ("falsifiable_01_finite_pd_cooperate", "falsifiable_02_dominant_tft")
)
nfk = by["novel_on_01_quant_lockin"]["verdict"]
no_false_kill_ok = nfk != "refuted"
unparseable = [r["case_id"] for r in rows
               if not r["verdict"] or r["raw_status"] in ("error", "empty")]
liveness_ok = len(unparseable) == 0

result = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "served_model": label,
    "checks": {
        "kill": {"pass": kill_ok},
        "no_false_kill": {"pass": no_false_kill_ok, "novel_on_01_verdict": nfk},
        "liveness": {"pass": liveness_ok, "unparseable": unparseable},
    },
    "all_pass": kill_ok and no_false_kill_ok and liveness_ok,
    "verdict_by_expected": {},
    "total_seconds": round(time.perf_counter() - t0, 1),
    "rows": rows,
}
for r in rows:
    result["verdict_by_expected"].setdefault(r["expected_critic"], []).append(r["verdict"])

out = REPO / "bench/critic_eval/runs" / (
    f"stage3a_{label}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(result, indent=2))
print(json.dumps(result["checks"], indent=1))
print("all_pass:", result["all_pass"], f"({result['total_seconds']}s)")
print("wrote", out)
