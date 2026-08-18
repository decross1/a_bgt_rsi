"""Qwen A/B battery stages 3b/3c/3d (PREREG_qwen_ab_3bcd_2026-08-18.md, v2 LOCKED).

  vote_battery.py — stage 3b: finding_promotion multi-vote battery over the
                    3 pinned surfaced findings, per-arm calls-log isolation,
                    liveness + empty-at-cap criteria, 60-min arm cap.

Artifacts land in runs/ as <stage>_<arm>_<utc>.json with full provenance;
each arm's wrapper calls land in runs/<arm>.calls.jsonl (never production
logs/calls.jsonl). CLIs REFUSE (exit 2) under MOCK_LLM.
"""
