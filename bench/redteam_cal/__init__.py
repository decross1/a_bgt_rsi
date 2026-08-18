"""D-075 R1a redteam calibration battery (bench).

Prereg: experiments/PREREG_redteam_cal_2026-08-18.md (v2). Contents:

- build_fixtures.py : deterministic resolver/generator for fixtures.jsonl
- fixtures.jsonl    : the 24-row frozen manifest (12 known-good / 12 known-bad)
- revised_prompt.txt: the gemma-revised system prompt (frozen at lock)
- driver.py         : per-arm run driver (gemma-current / gemma-revised / qwen38)

The manifest and revised prompt LOCK in the same commit; the driver reads
only fixtures.jsonl. No arm is run by the build agent — the integrator
locks first, then runs.
"""
