"""FP8 A/B qualification-window instrumentation (D-072).

Spec: docs/qwen_fp8_windows_plan.md (Windows A/B + the "Build gaps" list).

  driver.py     — sentinel-first 22-case battery against a vLLM endpoint
                  (:8002) with STOP conditions and frozen provenance.
  tool_probe.py — deterministic 10-turn tool-call probe (role_setups R5),
                  identical script both arms.

Run artifacts land under bench/fp8_ab/runs/ (created at runtime, never
committed).
"""
