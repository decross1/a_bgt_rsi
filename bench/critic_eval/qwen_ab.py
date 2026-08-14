"""Qwen 3.6 vs 3.8 A/B battery runner — SKELETON (LOOP_V1 P5; NO cutover).

Parameterized side-by-side plan for the roles Qwen actually plays in the
apparatus (see docs/qwen38_upgrade_checklist.md §3, which grounds every stage):

  3a  skeptic-ladder cases        — novelty_skeptic.attack(), pass criteria
                                    verbatim from docs/skeptic_ladder.md
  3b  finding_promotion multi-vote — fixed historical candidates, same rows A/B
  3c  two-voice attacker spot-run  — finding_session attacker stance
  3d  restate_skeptic hook cases   — verified a Qwen role (NARA_SKEPTIC_BACKEND
                                    default "vllm-qwen"; see checklist §3d)

Two modes, mutually exclusive:

  --dry-run  prints the FULL plan (models, serve commands, stages, pass
             criteria refs, memory notes) and exits 0. Touches nothing:
             no docker, no model, no network. This is the only mode tests
             exercise.
  --live     the real A/B window entry point. It REFUSES to proceed unless
             (a) the candidate weights exist under --models-root and
             (b) the preflight memory guard (preflight_mem.sh, D-057) passes.
             Even then it does NOT serve anything — the A/B serve window is a
             HUMAN GATE (LOOP_V1 P5); on a clean preflight it prints the exact
             serve command for the human to run and exits 0. Refusals exit 1
             with a REFUSE line (fail-closed, never silent).

The refusal path is deliberately fail-closed: a missing/unreadable preflight
script or memory source is a refusal (exit 1), never a skipped check.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Control (A) = current production; candidate (B) = upgrade target.
# Names match docs/qwen38_upgrade_checklist.md §0/§1 and cron/serve-models.sh.
MODEL_A = "qwen3.6-27b-nvfp4-mtp"
MODEL_B = "qwen3.8-27b-nvfp4-mtp"
DEFAULT_MODELS_ROOT = Path("/mnt/models")
PREFLIGHT_SH = REPO_ROOT / "experiments" / "exp008_qat_eval" / "preflight_mem.sh"
# On-box Qwen need at --gpu-memory-utilization 0.25 (preflight_mem.sh header).
QWEN_NEED_GIB = 30
VLLM_IMAGE = "vllm/vllm-openai:v0.21.0"  # inviolate pin (CLAUDE.md rule 2)

BATTERY_STAGES = [
    {
        "stage": "3a_skeptic_ladder",
        "entry": "orchestrator.novelty_skeptic.attack(backend='vllm-qwen')",
        "cases": "experiments/lit_falsification_battery/cases.jsonl",
        "criteria": "docs/skeptic_ladder.md §Pass/fail (kill / no-false-kill / "
                    "liveness) — verbatim; 'close' is a FAIL (rule 4)",
    },
    {
        "stage": "3b_promotion_multivote",
        "entry": "orchestrator/finding_promotion.py --backend vllm-qwen",
        "cases": "FIXED historical candidates (same loop_memory rows for A and B)",
        "criteria": "quorum kept where A attains it; no adjudicated-outcome "
                    "flips without human-accepted rationale",
    },
    {
        "stage": "3c_twovoice_attacker",
        "entry": "orchestrator/finding_session.py (attacker stance = vllm-qwen)",
        "cases": "one real two-voice session per model, same finding",
        "criteria": "attacker stays adversarial, parses cleanly, cites "
                    "(human spot-check)",
    },
    {
        "stage": "3d_restate_hook",
        "entry": "orchestrator.restate_skeptic.restate_attack(backend='vllm-qwen')",
        "cases": "residual-2 rediscovery cases (module docstring)",
        "criteria": "restate_verdict grounded: 'restated' only with a "
                    "restating_doc_id from the retrieved set",
    },
]


def serve_command(model_name: str, models_root: Path) -> str:
    """The exact docker run for an A/B qwen server — serve_qwen() flags from
    cron/serve-models.sh with only the model path/name parameterized. The 3.8
    speculative method / parsers are the §1 OPEN QUESTION: if v0.21.0 lacks
    them, that is a pin amendment (rule 2), never a flag workaround."""
    weights = models_root / model_name
    return (
        f"docker run -d --name vllm-qwen-ab --restart unless-stopped --gpus all"
        f" -p 8001:8000 -v {weights}:/models/{model_name} {VLLM_IMAGE}"
        f" --model /models/{model_name} --served-model-name {model_name}"
        f" --trust-remote-code --quantization modelopt --language-model-only"
        f" --max-model-len 16384 --max-num-seqs 2 --kv-cache-dtype fp8"
        f" --gpu-memory-utilization 0.25 --reasoning-parser qwen3"
        f" --speculative-config"
        f" '{{\"method\":\"qwen3_5_mtp\",\"num_speculative_tokens\":3}}'"
        f" --enable-auto-tool-choice --tool-call-parser qwen3_coder"
    )


def build_plan(models_root: Path) -> dict:
    """Assemble the full A/B plan as data (rendered by render_plan)."""
    return {
        "model_a": MODEL_A,
        "model_b": MODEL_B,
        "models_root": str(models_root),
        "weights_a_present": (models_root / MODEL_A).is_dir(),
        "weights_b_present": (models_root / MODEL_B).is_dir(),
        "preflight": f"bash {PREFLIGHT_SH} {QWEN_NEED_GIB} must return 0 "
                     f"before EITHER serve (OS_MARGIN hard-pinned; D-057)",
        "serve_a": serve_command(MODEL_A, models_root),
        "serve_b": serve_command(MODEL_B, models_root),
        "memory_note": "A/B window may require stopping vllm-gemma4 to "
                       "co-reside; restore it after and re-verify the MARLIN "
                       "line. NEVER thin the 30 GiB margin (rule 7).",
        "stages": BATTERY_STAGES,
        "gates": "weight acquisition / A/B serve window / cutover ratification "
                 "are HUMAN GATES (LOOP_V1 P5); this runner never serves.",
    }


def render_plan(plan: dict) -> str:
    lines = [
        "=== Qwen A/B battery plan (dry-run; nothing executed) ===",
        f"control  A: {plan['model_a']}  "
        f"(weights present: {plan['weights_a_present']})",
        f"candidate B: {plan['model_b']}  "
        f"(weights present: {plan['weights_b_present']})",
        f"models root: {plan['models_root']}",
        f"preflight:   {plan['preflight']}",
        f"memory:      {plan['memory_note']}",
        f"serve A:     {plan['serve_a']}",
        f"serve B:     {plan['serve_b']}",
        "stages:",
    ]
    for s in plan["stages"]:
        lines.append(f"  [{s['stage']}]")
        lines.append(f"    entry:    {s['entry']}")
        lines.append(f"    cases:    {s['cases']}")
        lines.append(f"    criteria: {s['criteria']}")
    lines.append(f"gates: {plan['gates']}")
    return "\n".join(lines)


def run_preflight(need_gib: int = QWEN_NEED_GIB) -> tuple[int, str]:
    """Run the D-057 memory guard. Fail-CLOSED: a missing script or any
    subprocess error refuses (rc 2), it never skips the check."""
    if not PREFLIGHT_SH.is_file():
        return 2, f"preflight script missing: {PREFLIGHT_SH} (fail-closed)"
    try:
        proc = subprocess.run(
            ["bash", str(PREFLIGHT_SH), str(need_gib)],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, f"preflight invocation failed: {type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stderr or proc.stdout).strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Qwen 3.6 vs 3.8 A/B battery runner (skeleton; see "
                    "docs/qwen38_upgrade_checklist.md)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="print the full A/B plan; execute nothing")
    mode.add_argument("--live", action="store_true",
                      help="live A/B entry: weights + preflight checks, then "
                           "print the human-gated serve command")
    ap.add_argument("--models-root", type=Path, default=DEFAULT_MODELS_ROOT,
                    help=f"weights root (default {DEFAULT_MODELS_ROOT})")
    args = ap.parse_args(argv)

    plan = build_plan(args.models_root)

    if args.dry_run:
        print(render_plan(plan))
        return 0

    # --live: fail-closed gate sequence. Order matters — cheapest first.
    if not plan["weights_b_present"]:
        print(f"REFUSE live: candidate weights not found at "
              f"{args.models_root / MODEL_B} — acquisition is a human gate "
              f"(checklist §1); nothing served.")
        return 1
    rc, msg = run_preflight()
    if rc != 0:
        print(f"REFUSE live: preflight_mem rc={rc}: {msg} — nothing served.")
        return 1
    print(f"preflight PASS: {msg}")
    print("Live A/B serve window is a HUMAN GATE (LOOP_V1 P5). This runner "
          "does not serve. Human executes:")
    print(f"  {plan['serve_b']}")
    print("then runs the battery stages against :8001 per the checklist §3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
