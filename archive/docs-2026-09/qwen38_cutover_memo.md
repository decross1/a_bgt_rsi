# Qwen 3.6 → 3.8 skeptic-seat cutover memo (ratification-ready, 2026-08-18)

**For:** the owner (G6 gate; inviolate rule 2 — cutover requires explicit
ratification and the D-0zz decision entry, filed at cutover per D-072).
**From:** the primary session, closing the D-072 qualification track.
**Recommendation: CUTOVER APPROVED-READY.** Qwen3.8-27B-NVFP4 (Inferact,
`/mnt/models/qwen3.8-27b-nvfp4-mtp`) meets or beats 3.6 on every locked
gate across the complete battery. Ratify, or name the missing measurement.

## The complete D-0zz battery table

| Stage | Instrument | 3.6-NVFP4 (prod pin) | 3.8-NVFP4 (prod pin) | Locked A/B gate |
| --- | --- | --- | --- | --- |
| 3a skeptic-ladder (22 cases, cap 12288) | stage3a fixed driver | **ALL 3 PASS** (kill ✓ no-false-kill ✓ liveness 22/22) — 08-17 control | **ALL 3 PASS** — 08-17 window C (D-044 citations exact) | ✅ |
| 3b promotion multi-vote (3 pinned candidates, prod budgets) | vote_battery | liveness PASS · empty-at-cap 0 | liveness PASS · empty-at-cap 0 | ✅ 3.8 ≥ 3.6 |
| 3c two-voice attacker (3 pinned findings) | twovoice_battery | all_pass 3/3 | all_pass 3/3 | ✅ |
| 3d restate hook (4 cases, incl. the D-070 3072-cap residual) | restate_battery | all_pass 4/4 | all_pass 4/4 | ✅ |
| Quality cross-check | matched official-FP8 A/B (08-17, MTP off, BF16 KV, frozen provenance) | 3.6-FP8 **kill-pair SPLIT** (f02 survives) | 3.8-FP8 **kill-pair PASS** (both refuted w/ citations) | favors 3.8 |
| Tool probe (10 turns, fixed script) | fp8_ab tool_probe | 9/10 structured (only the deliberate dict-trap fails) | 8/10 (dict-trap + one multi-tool ReadTimeout — latency, not format) | parity-class |

Throughput on record (first local numbers): 23.6 tok/s (3.6-NVFP4+MTP,
eval runtime) · 16.6 tok/s avg-gen (3.8-NVFP4+MTP, prod pin) · ~8 tok/s
(both FP8 arms, MTP off). 3.8 reasons longer per verdict; every 2026-08-17/18
measurement ran inside production budgets without a single empty-at-cap
completion at the D-070 caps.

## What ratifying means (and does not)

- **Changes:** `cron/serve-models.sh` serve_qwen() model path + served name
  to `/mnt/models/qwen3.8-27b-nvfp4-mtp`; the hardcoded-string inventory in
  `docs/qwen38_upgrade_checklist.md` §cutover (registry label sites);
  util per the role_setups Config-1 arithmetic (0.25→0.30 recommended —
  D-057-gated preflights before AND after, MARLIN re-verify).
- **Does NOT change:** the image pin (v0.21.0, verbatim), Gemma (untouched
  end-to-end through every window), model ROLES (G5 — Gemma PI, Qwen
  skeptic), or any promotion-bar constant.
- **Rollback:** 3.6 weights retained ≥30 days (checklist rule); a cutback
  is the same one-function serve edit + restart.

## Honest caveats on the record

1. 3.8 is slower per verdict (longer reasoning tails); the D-070/5c0f783
   budget-wall pairs absorbed this in every battery — but always-on cadence
   cost rises modestly (~1.5-2× wall per skeptic exchange at current caps).
2. The novel_on_01 *inconclusive* on the FP8 quality arm (not-refuted =
   weak no-false-kill) did NOT recur on the NVFP4 prod-pin battery (clean
   survives_attack) — recorded, not hidden.
3. **D-022 correction (append-only, ride-along for the D-0zz entry):**
   D-022's "determinism intact" overstates. Measured 2026-08-17: Gemma is
   not run-to-run byte-deterministic at temp-0 (benign reduction-order
   drift in the MoE Marlin lock-based reduce; zero corruption in ~150-call
   probes); **Qwen is byte-deterministic (0/8)** — and 3.8 inherits the
   FlashInfer path, so skeptic-verdict bitwise reproducibility is expected
   to carry over (spot-verify post-cutover: same-prompt ×2 byte-compare).
4. The eval-runtime work (Window A/B, fp8_ab) used the digest-pinned fork
   image for the FP8 comparison only; every gating row above ran on the
   PRODUCTION image v0.21.0.

## To ratify

Say so, and the cutover executes under the window discipline (pause,
preflight, swap, steady-state preflight 0, MARLIN re-verify, run-log rows),
with the D-0zz decision entry filed carrying this table verbatim plus the
D-022 correction. Until then production stays on 3.6 and nothing moves.
