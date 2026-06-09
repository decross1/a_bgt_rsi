# Independent-skeptic ladder (D-041)

Status: steps 1–2 shipped 2026-06-09 (`orchestrator/novelty_skeptic.py`,
`attack()`); step 3 is DESIGN ONLY this session.

## Why a ladder

The 068 review's central finding: `novelty_classify` and the critic both
reason over the **same** retrieved neighbor set, so their agreement is a
shared blind spot, not corroboration. The skeptic therefore does its
**own retrieval** (`orchestrator.chroma_query.query_top_k`, default
collections — curated by default per Limb D) and is asked to **refute**
the hypothesis: find a contradiction or a restatement in *its own*
retrieved set, or concede survival.

API (frozen interface contract 4):

```python
from orchestrator.novelty_skeptic import attack
attack(hypothesis_text, iteration_id=None, backend="vllm-qwen")
# -> {"attack_verdict": "refuted"|"survives_attack"|"inconclusive",
#     "rationale": str, "contradicting_doc_id": str|None,
#     "backend": str, "model": str}
```

Fail-closed: every failure path (unknown backend, failed retrieval,
wrapper error, unparseable/off-enum output, an unverifiable "refuted"
citation) returns `inconclusive` — never `survives_attack`. Under
`MOCK_LLM` it returns a deterministic stub without touching network or
model. The `iteration_id` is provenance only (threaded into the calls
log as `parent_request_id`); the iteration cache is never read.

## The steps

| Step | Backend | Independence mechanism | Status |
| --- | --- | --- | --- |
| 1 | `vllm-qwen` (Qwen NVFP4-MTP on `:8001`; **default** via `NARA_SKEPTIC_BACKEND`; the `ollama-coder` route is DEMOTED per D-044 — unset `OLLAMA_MODEL` fails closed + double-qwen memory thrash) | Different weights from Gemma — a genuinely independent judge. Past empty-content failures were token starvation; the ladder runs non-default backends at `max_tokens=3072` (the value `finding_promotion` already works with; 512 and 2048 both starved the Qwen reasoning channel, observed 2026-06-09). | Shipped; needs the live test below |
| 2 | `vllm-gemma` | Same weights as the apparatus, so independence is **persona-level only**: a visibly adversarial "HOSTILE REVIEWER #2 / prior-art prosecutor" system prompt, distinct from the critic's methodological-critic persona and from `workers/novelty_skeptic.py`'s second-opinion persona. Weakest rung — a same-model concession is still a self-check; the result's `backend` field keeps that visible. Runs at `max_tokens=512` (non-reasoning persona). | Shipped; fallback if step 1 fails live |
| 3 | Claude (Anthropic, via Agent SDK / Max plan) | Off-box frontier model — strongest independence. | **DESIGN ONLY** (below); build only if steps 1–2 fail live |

Step order is a priority ladder, not a chain: run step 1; drop to step 2
only if step 1 fails its live test; escalate step 3 from design to build
only if both fail.

## Live test (integrator runs this; MOCK_LLM tests cannot stand in)

Battery: `experiments/lit_falsification_battery/cases.jsonl`. The attack
is run per case with `env -u MOCK_LLM` (rule 10) against the real corpus
and the real backend:

```bash
env -u MOCK_LLM ./.venv-chroma/bin/python - <<'EOF'
import json
from orchestrator.novelty_skeptic import attack
cases = {
    # the two falsifiable claims — MUST be refuted
    "falsifiable_01_finite_pd_cooperate": "refuted",
    "falsifiable_02_dominant_tft": "refuted",
    # one true on-domain survivor — must NOT be refuted
    "novel_on_01_quant_lockin": "not_refuted",
}
for line in open("experiments/lit_falsification_battery/cases.jsonl"):
    c = json.loads(line)
    if c["case_id"] in cases:
        out = attack(c["hypothesis"], iteration_id=c["case_id"],
                     backend="vllm-qwen")   # step under test
        print(c["case_id"], "->", json.dumps(out))
EOF
```

Plus the battery survives-cases as a wider sanity sweep
(`novel_on_01..03`, `canary_on_03_llm_gt_hybrid`): none of them may be
`refuted` with a fabricated citation (any `refuted` there must cite a
doc_id the integrator can read and agree contradicts/restates the claim
— logged human sampling, ARCHITECTURE.md §6 step 6).

### Pass/fail criteria (per step, validations never coerced)

A step PASSES only if all three hold on the live run:

1. **Kill check** — both falsifiable claims (`falsifiable_01`,
   `falsifiable_02`) come back `refuted`, each with a
   `contradicting_doc_id` from the skeptic's own retrieved set that a
   human spot-check agrees is a real contradiction/restatement.
2. **No-false-kill check** — the true on-domain survivor
   (`novel_on_01_quant_lockin`) is NOT `refuted` (`survives_attack`
   preferred; `inconclusive` acceptable — it fails closed and the
   consumer treats it as not-corroborated, but log it).
3. **Liveness check** — no empty/unparseable completions across the
   sweep (the token-starvation signature: `finish_reason=length`,
   `content=None`). One unparseable completion = investigate before
   passing; systematic unparseable output = FAIL.

"Close" is a failure (inviolate rule 4): one of two falsifiable claims
refuted is a FAIL for the kill check, not a partial pass. A failed step
is logged (`run_state/week1.run.jsonl`) and the ladder drops one rung
with the `fallback` discipline (explicit, logged, time-capped).

## Step 3 design — Claude via Agent SDK (NOT built this session)

**Surface.** A single chat completion per attack (no tools, no agent
loop), via the official `anthropic` Python SDK — the Agent SDK / Managed
Agents surface is overkill for one-shot judging. Auth via the Max-plan
OAuth profile (`ant auth login` → the SDK's default credential chain
picks up the profile; no static API key on disk). Implementation slot:
a `backend="anthropic"` branch in `attack()` reusing the already
registered D-035 anthropic backend, same return shape, same fail-closed
parsing.

**Model choice.** `claude-opus-4-8` ($5 / $25 per MTok, 2026-05-26
pricing cache). Rationale: the whole point of rung 3 is the strongest
available independent judge after two cheaper rungs failed; per-attack
volume is tiny, so the Opus premium is noise. If cost ever matters,
`claude-sonnet-4-6` ($3 / $15) is the documented downgrade — a deliberate
human decision, not a default.

**Per-attack token estimate.** Prompt = persona (~0.4k) + hypothesis
(~0.2k) + 10 neighbors × ~600-char chunks (~2.5–4k) ≈ **3–6k input**;
output = strict-JSON verdict + adaptive thinking ≈ **≤1k output**.

**Cost model vs the $200 Max plan.** Worst case 6k in / 1k out at Opus
4.8 rates: 6k×$5/1M + 1k×$25/1M ≈ **$0.055 per attack** (typical ~$0.04).
$200 ≈ **3,600+ attacks** — at the apparatus's current cadence (a few
iterations/day, ≤1 attack each) that is years of headroom; even a 100-
attack battery re-run is ~$5.50. Budget is not the constraint; the
governance below is.

**D-014 firewall note.** The runtime never reads the framework brain at
`/home/decross1/projects/agent_system/memory/brain/` — that holds for
this skeptic exactly as for every worker. Separately, step 3 sends
hypothesis text + retrieved corpus chunks **off-box** to Anthropic.
That is an explicit D-014-adjacent / provider-ToS decision **the human
takes** (a gate, inviolate rule 3) before the first live call — it is
not a fallback the apparatus may select on its own.

## Escalation wording (if steps 1 and 2 both fail live)

> Skeptic ladder steps 1 (vllm-qwen, max_tokens=3072) and 2
> (vllm-gemma adversarial persona) FAILED the live battery test on
> <date>: <which criterion failed per step, with run-log refs>. Per
> D-041 the next rung is step 3 (Claude via the Anthropic SDK under the
> $200 Max plan, design in docs/skeptic_ladder.md §Step 3). This is
> blocked on a human gate: sending hypothesis + corpus chunks off-box
> is a D-014/ToS decision. Approve step 3 build, or direct an
> alternative (re-tune step 1 prompting / accept reduced independence).
> HALTING on this gate.
