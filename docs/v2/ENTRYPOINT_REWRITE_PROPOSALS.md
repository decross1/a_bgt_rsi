# Entrypoint rewrite proposals (2026-09-23)

This session's spawn contract excluded five files from direct edits because
another session holds uncommitted edits to them: `CLAUDE.md`, `START_HERE.md`,
`LOOP_V1.md`, `DECISIONS.md`, and `docs/packet_sdlc.md`. This document
proposes the exact passages to replace in the four of those five that carry
stale current-state claims (LOOP_V0/LOOP_V1-as-active, the Gemma/Qwen pair as
current, or Oracle/Nara framed incorrectly). `DECISIONS.md` is out of scope
entirely — it is append-only decision prose and is never rewritten for
currency.

Line numbers are from this worktree at commit `d18d9ea` (unmodified — these
files were not touched by this session).

---

## 1. `START_HERE.md`

### 1a. "Current state — 2026-09-14" section (lines 24–48)

This entire section describes the pre-Flash, pre-Oracle/Nara-actor-model
deployment. Replace it with a dated section describing the actual deployed
system.

**Replace (lines 24–48):**

```
## Current state — 2026-09-14

- One DGX Spark hosts two resident local endpoints: Gemma on `:8000` and
  Qwen3.8 on `:8001`.
- Nara runs as an event-driven user service. Its coordinator is bounded by a
  lock, ratification sentinel, human pause file, unified-memory preflight, and
  daily action budget. Hourly cron uses the same lock and gate ladder.
- Research claims move through the L0-L5 evidence ladder. Only L4+ can surface;
  only an explicit human verdict earns L5.
- The weekly upgrade controller runs Sunday at 05:30 UTC in review-only mode.
  It may use two subscription frontier sessions to propose and challenge one
  bounded hypothesis. It cannot promote production automatically.
- Named generation profiles exist as explicit evaluation arms. Legacy calls
  that do not select a profile retain their existing deterministic behavior.
- The v2 foundation adds immutable campaign identity, explicit lifecycle receipts,
  legacy isolation, and a measured research funnel. Runtime activation is an
  exact hash-bound pointer; consult `/benchmarks` and
  `run_state/v2_preparation/deployment_receipt.json` for adoption evidence.
- The prepared first campaign is `v2-agentic-game-theory-20260914`. It asks how
  individual versus shared payoff objectives and access to player-identified
  interaction history affect cooperation and utility-consistent behavior in
  repeated public-goods games among model agents. Its 324 CPU records are 81
  scripted-policy assignments under four objective/observation invariance
  conditions, not 324 independent behavior samples. They made no model calls;
  the narrower one-model-seat study remains gated.
```

**With:**

```
## Current state — 2026-09-23

- One DGX Spark hosts one resident local model, Flash
  (`nvidia/Qwen3.8-Flash-Next-NVFP4` on SGLang, `127.0.0.1:30080`, 262,144-token
  context, one running request). The prior Gemma/Qwen vLLM pair (`:8000`/`:8001`)
  stopped 2026-09-19 and is a rollback only. See `docs/FLASH_RESIDENT.md` and
  `docs/MODEL_TOPOLOGY_POLICY.md`.
- Three actors coordinate the lab: **Oracle** (running on Flash) plans the day
  and develops architecture, UI, contracts, and its own system; **Nara** runs
  research continuously (`nara-daemon` plus an hourly cron backstop; no daily
  cap, D-085) and builds lab tools through the lane
  (`orchestrator/nara_lane.py`, a bwrap sandbox, `nara/<id>` branches); the
  **meta-oracle** (Claude Opus 5.5; `tools/meta_oracle_run.sh`) reviews every
  plan, plan item, and branch and merges accepted work. Coordination runs
  through the lab mailbox (`run_state/oracle_nara_mailbox.jsonl`,
  `docs/ORACLE_NARA_MAILBOX.md`). See `DECISIONS.md` D-082, D-084–D-087.
- Nara's coordinator is bounded by a lock, ratification sentinel, human pause
  file, unified-memory preflight, and daily action budget. Hourly cron uses the
  same lock and gate ladder.
- Research claims move through the L0-L5 evidence ladder. Only L4+ can surface;
  only an explicit human verdict earns L5. A thesis separately climbs T
  (theory, OpenSpiel) → S (semi-synthetic) → A (applied proposal, paper trade)
  per D-084.
- The weekly upgrade controller runs Sunday at 05:30 UTC in review-only mode.
  It may use two subscription frontier sessions to propose and challenge one
  bounded hypothesis. It cannot promote production automatically.
- Named generation profiles exist as explicit evaluation arms. Legacy calls
  that do not select a profile retain their existing deterministic behavior.
- The v2 foundation has immutable campaign identity, explicit lifecycle
  receipts, legacy isolation, and a measured research funnel. The active plan
  is `LOOP_V2.md`; direction and refinement protocol are in D-086 and
  `docs/v2/THESIS_BRIEF_2026-09-23.md`. The owner's only required gate is live
  trading (D-084). Runtime activation is an exact hash-bound pointer; consult
  `/benchmarks` and `run_state/v2_preparation/deployment_receipt.json` for
  adoption evidence.
```

(The rest of the bullet — the `v2-agentic-game-theory-20260914` campaign
description — should be re-verified against the currently active campaign
pointer before republishing; it may itself be superseded by a later campaign.
This proposal does not attest to which campaign is active as of 2026-09-23.)

### 1b. Health-check block (lines 71–82)

**Replace:**

```bash
cd /home/decross1/projects/a_bgt_rsi
git status --short
git branch --show-current
git log -1 --oneline
ui/scripts/ui-services.sh status
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
curl -fsS http://127.0.0.1:8700/api/health
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8001/v1/models
```

**With:**

```bash
cd /home/decross1/projects/a_bgt_rsi
git status --short
git branch --show-current
git log -1 --oneline
ui/scripts/ui-services.sh status
systemctl --user show nara-daemon.service \
  -p ActiveState -p SubState -p MainPID -p ExecMainStartTimestamp
systemctl --user status flash-resident.service --no-pager
curl -fsS http://127.0.0.1:8700/api/health
curl -fsS http://127.0.0.1:30080/v1/models
```

(`:8000`/`:8001` checks apply only to the stopped Gemma/Qwen rollback pair —
see `docs/FLASH_RESIDENT.md`.)

### 1c. Historical-docs line (line 20)

**Replace:**

```
`LOOP_V1.md`, `LOOP_V0.md`, `PROJECT_CONTEXT.md`, and the v5 diagrams are
valuable historical inputs. They contain dated implementation claims and are
not a substitute for current code, validated receipts, or a live health check.
```

**With:** (unchanged in substance — already correctly frames these as
historical; no edit required.)

---

## 2. `CLAUDE.md`

### 2a. Gemma/Qwen baseline lines in "V2 maintenance and evidence" (the
paragraph beginning "The owner removed the requirement for two concurrently
resident models on 2026-09-15")

**Replace:**

```
The owner removed the requirement for two concurrently resident models on
2026-09-15. Apply [the model topology amendment](docs/MODEL_TOPOLOGY_POLICY.md):
the current Gemma/Qwen pair is a baseline, and a single-primary candidate may
serve all local roles. Critic quality and diversity are measured separately;
older fixed-role or concurrent-residency rules cannot veto the experiment.
```

**With:**

```
The owner removed the requirement for two concurrently resident models on
2026-09-15 and, on 2026-09-19, selected the single-primary candidate as the
permanent deployment: Flash (`nvidia/Qwen3.8-Flash-Next-NVFP4` on SGLang,
`127.0.0.1:30080`, `flash-resident.service`). Apply
[the model topology amendment](docs/MODEL_TOPOLOGY_POLICY.md). The prior
Gemma/Qwen pair (`:8000`/`:8001`) is stopped and is a rollback baseline only —
see [the Flash resident record](docs/FLASH_RESIDENT.md). Critic quality and
diversity are measured separately; older fixed-role or concurrent-residency
rules cannot veto the experiment.
```

### 2b. Inviolate rule 2 — version pins (the numbered list under "Version pins
are verbatim")

**Replace the rule's lead-in and list** with a split between the production
pin (Flash) and the rollback pin (the existing Gemma/Qwen list, unchanged):

```
2. **Version pins are verbatim.** Canonical list in
   [`ARCHITECTURE.md`](ARCHITECTURE.md) §3.1. The production pin for the
   deployed system is the Flash checkpoint revision
   (`fc694b54fb0174e0913e6adf86691ef85a4ead47`) plus the SGLang image digest
   `sha256:2ee545cf877ae8497c123637e061b6e6313c624e30018f975969b1d554e27f56`
   (see [`docs/FLASH_RESIDENT.md`](docs/FLASH_RESIDENT.md)). The list below
   applies only to the stopped Gemma/Qwen pair, kept as a rollback
   configuration (`ARCHITECTURE.md` §3.1a):
   - vLLM image: `vllm/vllm-openai:v0.21.0` (NOT `:gemma4`,
     `:gemma4-cu130`, or `:v0.20.0` — D-022: v0.21.0 enables Gemma 4
     MTP).
   - OpenShell cluster: `ghcr.io/nvidia/openshell/cluster:0.0.13`.
   - CUDA: 13.0 (NOT 13.2 — gibberish on low-bit quants).
   - Embedding: BGE-M3 (NOT all-MiniLM-L6-v2) — still current, applies to
     both configurations.
   - vLLM MoE backend: `--moe-backend marlin`; startup log MUST
     contain `Using 'MARLIN' NvFp4 MoE backend`. If the log shows
     `CUTLASS_FP4`, the flag did not pick up — STOP.
   - Weights path: `/mnt/models/gemma-4-26b-a4b-nvfp4` (NVFP4, not BF16).
```

### 2c. Operating-model section — name the actors

The "Operating model" section (beginning "One primary session at a time,
plus at most one concurrent UI session...") describes only the primary/UI-
session split; it should name Oracle, Nara, the meta-oracle, and Codex
alongside the Claude-session roles it already documents, matching the
`V2 maintenance and evidence` section's authority already granted above it.
Concretely, add one paragraph after the existing bullet list (after "...are
subject to the **Dynamic Workflow discipline** below."):

```
Outside this Claude-session workflow, three further actors run continuously:
**Oracle** (on Flash) plans the day and develops architecture, UI, contracts,
and its own system; **Nara** runs research continuously and builds lab tools
through the Nara lane (`orchestrator/nara_lane.py`, a bwrap sandbox, `nara/<id>`
branches, reviewed via `config/nara_lane.json`); the **meta-oracle** (Claude
Opus 5.5; `tools/meta_oracle_run.sh`) reviews every plan, plan item, and
branch and merges accepted work. Direct Codex repository-management sessions
retain the standing authority described above. See `DECISIONS.md` D-082,
D-084 through D-087, and `docs/META_ORACLE_DAILY_LOOP.md`.
```

### 2d. Out-of-scope guardrails — the "installed baseline" bullet

**Replace:**

```
- The installed baseline uses **Gemma 4 26B-A4B-NVFP4 as generator/PI**
  and **Qwen (vllm-qwen) as skeptic**. The owner superseded fixed roles
  and required concurrent residency on 2026-09-15; see
  [model topology policy](docs/MODEL_TOPOLOGY_POLICY.md).
  **Frontier CLIs (Claude Max / Codex) are falsifiers only**
  (D-061) — veto/annotate, never generate, never write loop_memory or
  the brain. Reproducibility rule: any call a reader needs to reproduce
  a finding runs on pinned local weights.
```

**With:**

```
- The installed baseline uses **Flash as the shared generator/critic/builder
  checkpoint** (one resident model serves all local roles). The owner
  superseded fixed roles and concurrent-residency requirements on
  2026-09-15 and selected Flash as the permanent deployment on 2026-09-19;
  see [model topology policy](docs/MODEL_TOPOLOGY_POLICY.md) and
  [the Flash resident record](docs/FLASH_RESIDENT.md). The prior
  Gemma-generator/Qwen-skeptic pair is a rollback only.
  **Frontier CLIs (Claude Max / Codex) are falsifiers only**
  (D-061) — veto/annotate, never generate, never write loop_memory or
  the brain. Reproducibility rule: any call a reader needs to reproduce
  a finding runs on pinned local weights.
```

---

## 3. `LOOP_V1.md`

`LOOP_V1.md` is already labeled a historical build record by `START_HERE.md`,
`README.md`, and `docs/v2/DOCUMENTATION_INDEX.md`, and carries no "current
state" framing of its own beyond a few Gemma mentions that are contextually
historical (an A/B-window note near line 274 and a cutover-ratification note
near line 335 — both describe events already in the past tense relative to
the document's own timeline). No rewrite is proposed; a one-line historical
banner in the style of `LOOP_V0.md`'s would be consistent but is optional
since the surrounding docs already correctly label it.

---

## 4. `docs/packet_sdlc.md`

No stale current-state claims were found (no `:8000`/`:8001`, Gemma, Qwen, or
Oracle/Nara framing). Its title references "LOOP_V1 P4" as the phase that
introduced the packet-execution SDLC it documents — that is a historical
decision-phase label, not a claim that LOOP_V1 is the active plan, and needs
no change. No rewrite is proposed.
