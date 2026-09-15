# Controller-gated local model comparison

This plan compares two deployable bundles: the existing Gemma/Qwen resident
roles and the previously qualified Mia reduced47k MTP3 Flash candidate.
It reuses all 126 public development cells from the seven-family original
portfolio under new, explicit role policies and output caps. The original
MTP0 run, manifests, scores, and grader code remain immutable. Neither bundle
is promoted by this evaluation.

The resident routes Qwen to science generation, evidence, and selected critics;
Gemma handles topic, coding, tools, historical repairs, and original context.
Flash uses its single registered Mia endpoint for every role. Qwen and Flash
have explicit thinking-off or medium controls, with xhigh only for the
current-critic calls. Gemma uses explicit thinking off; its template does not
support the same reasoning-effort labels. The suite therefore measures whole
model/runtime/policy bundles, not a causal effect of one model weight change.

| Original family | Cells | Policy and per-call output/time cap |
|---|---:|---|
| Objective | 24 | Qwen/Mia medium science, targeted xhigh critic; 1,024 tokens, 75 s |
| Topic | 48 | Gemma/Mia off; 512 tokens, 25 s |
| Context | 4 | Gemma/Mia off; 2,048 tokens, 100 s |
| Portfolio | 16 | Science/evidence medium 6,144 tokens/120 s; coding off 8,192/240 s |
| Diversity | 12 | Exploration medium up to 60 s; control off at registered cap |
| Role effort | 16 | Qwen/Mia critic medium/xhigh; registered caps and timeouts |
| Historical coding | 6 | Gemma/Mia off, 8,192 tokens/240 s |

The exact sum of all possible call timeouts is 9,740 s **per cohort**;
this is a failure ceiling, not an expected duration. The supervised window
sets a smaller absolute work budget and leaves 600 s for restoration. If
that budget or a live safety gate stops the run, every unissued cell is
`not_run` and the cohort is `aborted`; no selective denominator or headline
rate is published. The root controller owns container identity, resource
lease, canaries, live memory checks, cancellation, and exact restoration.

Independent replay rehashes every private local request/SSE transcript and
reruns the unchanged objective, topic, portfolio, diversity, role, and
historical graders. Primary grades are exact raw-contract scores. A
predeclared secondary coding diagnostic may remove one whole outer code
fence or append one missing terminal newline, then reruns the existing
sandbox. It reports raw framing, normalized framing, and executable
correctness separately; it never overwrites the primary result.

Two separate confirmation plans are source-frozen independently from the
primary 126 cells:

* Matched context uses four existing public objective evidence tasks at
  early/middle/late placements. The **total** qualified capacity lanes are
  8,192, 16,384, and 32,768 tokens with 2,048 output reserved. Exact shared
  packets retokenize to 6,015–6,054, 14,019–14,058, and 30,000–30,066
  input tokens across Gemma/Mia. Qwen's qualified 16,384-token resident
  server can fit the 8K/16K packets; Qwen 32K and any 64K quality claim are
  outside current qualification. The generated packet raw SHA is
  `4a6203e9c28ff8f7b74ec21b4d530aceb1430172a049a57912a386f3626b49f9`.
* Fresh confirmation contains six new finite-game arithmetic tasks and six
  distinct one-file Python bug repairs. A code-owned test oracle verifies
  the finite-game expected answers. Each repair runs two focused cases in
  the existing pinned bubblewrap/Python sandbox; all six known-good patches
  were source-tested before model requests. These are new synthetic
  development tasks, not unseen market outcomes or trading evidence.

The content-free paired report is published only when the resident and Mia
windows have the same frozen primary plan, 126 issued/recorded cells each,
verified final state and original-service restoration, clean supervisor
closure, exact raw model transcript replay, and all 126 primary grades
independently replayed. Its fixed `index.json` binds the plan, windows,
terminal state/result/supervision, two runs, two grade-replay receipts,
builder source, and numeric report. The UI may read counts after this
publication; configured server context and observed prompt-token maxima
remain separate fields. No local model outcome had been measured for this
new suite when this design was frozen.
