# Research and adversarial review record

**Date:** 2026-09-14 UTC

**Canonical deliverable:** [Weekly upgrade coding handoff](CODEX_RESEARCH_HANDOFF.md)

## What was actually done

Codex coordinated three independent delegated workstreams: local/runtime baseline audit, benchmark/statistical research, and runtime/model adversarial research. Primary model cards, official releases, source code, benchmark papers and reproducible third-party measurements were checked. The local audit was read-only: no new model generations, model installations, container lifecycle changes, service changes, Git ref updates or scheduler changes were performed by that workstream.

The coordinating session also called **actual Claude Code twice**, through `/usr/bin/claude` version `2.1.143`, using the existing authenticated **Claude Max** route. Both result envelopes reported success and `claude-opus-4-7` as the substantive reviewer model; small Haiku helper usage also appeared in the CLI metadata. The requested alias was `opus` with high effort. This is an observed resolved model, not a claim that it was the newest or strongest available Claude model.

Claude received a bounded review brief, not repository tool access. Tools, hooks, MCP servers and session persistence were disabled for these calls; the working directory was an isolated temporary review directory. API-key variables were removed. Claude did **not** independently browse sources or inspect the repository: its responses explicitly acknowledge that limitation. Codex's research agents performed source and repository verification. The raw review text is preserved in [CLAUDE_REVIEWS.md](CLAUDE_REVIEWS.md), and a minimal machine-readable receipt is in [review_receipt.json](review_receipt.json).

The default `~/.npm-global/bin/claude` launcher, installed as version `2.1.270`, failed because its native binary was missing. The session used the existing working binary; it did not reinstall Claude or change the project's resolver. This fallback is a discovered implementation issue, not a hidden repair. Each review subprocess had a bounded timeout; both completed within it.

The CLI reports nominal token-cost estimates even on subscription usage. Those values are not an invoice and are not treated as incremental metered API spending. No recurring API budget, scheduler activation, or production cutover was enacted by this task.

## The two review rounds

**Round 1:** Claude independently attacked the supplied proposal and proposed its own smaller implementation, statistical gates and game-theory tests. The source findings of the other research agents were not presented as already-settled conclusions in that first review.

**Cross-review:** Codex and the benchmark/runtime agents checked Claude's suggested graders, resource arithmetic, causal comparisons and repository assumptions. Several apparently precise recommendations were wrong or unsupported. The coordinator sent those objections, plus verified model-card and runtime findings, back to Claude.

**Round 2:** Claude explicitly retracted the flawed equilibrium oracle, fixed-percentage QRE recovery test, observational strategy labels, JSON-as-correctness grader, selective alpha spending, local-only scan, disagreement-only candidate admission, and concurrent shadow assumption. It accepted model-specific inference adapters and bounded source-backed research. The team then checked the revision rather than treating agreement as validation.

The final handoff incorporates accepted corrections and rejects remaining unsupported thresholds. The raw reviews are evidence of the review process, **not instructions that supersede the canonical handoff**.

## Disposition of important disagreements

| Issue | Final disposition | What would resolve the empirical remainder |
|---|---|---|
| Everything currently uses temperature zero | Rejected by local source and call-log inspection. Defaults and Nara's direct loop are zero; several roles already override them. | Consolidate effective policies and compare actual role behavior. |
| Qwen is currently constrained to low reasoning effort | Unproven. Local effort is not instrumented; a model-card/template default is not an observed request outcome. | Validate rendered template/request controls and log effective behavior and caps. |
| Shared `reasoning_effort` values across Qwen/Gemma | Rejected. Use per-model/runtime capability adapters and history formatting. | Exact server contract/sentinel tests before live policy trials. |
| Gemma always removes all prior thought content | Corrected in final source review: its card preserves thinking content for tool-call turns. | Tool-turn history and empty-thought-block parser fixtures. |
| SGLang alone delivers the advertised speed gain | Rejected causal attribution. The external result changes runtime, drafter, KV and other settings. | Native-MTP controls and matched target-only/drafter arms; science/tool quality and co-residency trials. |
| Existing weekly frontier cron is inactive | Rejected by crontab and recent logs. Sunday 05:30 UTC agenda is live; an infrastructure-upgrade controller is still missing. | Integration with existing coordinator, global budget/resource ownership and watchdog. |
| One Lemke–Howson run gives all Nash equilibria | Claude retracted. Use exact supplied games and independently checked regret/feasibility; completeness needs a valid enumeration oracle. | Grader property tests and hidden transformations. |
| QRE parameter must be recovered within ±10% | Claude retracted. Finite-sample uncertainty and identifiability invalidate a universal relative bound, especially at zero. | Oracle-calibrated likelihood, residual, coverage and predictive checks. |
| Strategy identity is always inferable from a finite observed path | Claude retracted. Use diagnostic probes or equivalence/abstention answers. | Held-out probe predictions and identifiability checks. |
| A filled JSON design rubric is an objective scientific score | Claude retracted. Schema validates form; numeric execution and calibrated scientific grading validate substance. | Simulated null/alternative behavior and human-reviewed anchors for the remainder. |
| Thirty tasks prove tight noninferiority | Rejected. Small panels are discovery/regression evidence; sample size depends on paired variance, discordance and the target estimand. | Fresh preregistered confirmation sized from pilot estimates. |
| Spend statistical error budget only when a result wins | Claude retracted. All planned confirmatory looks count. | Fixed planned sample initially; reviewed sequential design if later needed. |
| Forty tasks × five repeats × two arms fit two device-hours | Rejected arithmetic/resource assumption. Four hundred runs allow eighteen seconds each, including setup. | Timed vertical slice, then a feasible manifest and budget reservation. |
| Judge-human kappa ≥0.6 on twenty cases establishes valid judging | Not adopted. The threshold is arbitrary here, the sample is small and prevalence affects kappa. | Class-wise errors, uncertainty, audited anchors, executable graders and larger calibration as needed. |
| An OOD panel can be reused after revealing answers | Rejected as sealed confirmation. Revealed tasks move to development/regression; new sealed items are needed. | Predeclared new transformations/templates/domains and a pooling rule. |
| Cross-provider agreement or disagreement should decide admission | Rejected. Evidence and local relevance admit hypotheses; disagreement helps prioritize tests. | Objective falsification and confirmed task outcomes. |
| Every week should generate a PR | Not adopted. A report is mandatory; code/PR work follows a justified concrete change. | A measured benefit or correctness defect worth implementing. |
| Concurrent shadow replay is harmless on one Spark | Rejected as a default. Serialize under an idle resource lease; concurrent replay needs demonstrated fit/isolation. | Resource and interference measurements. |

## Local evidence receipt

Read-only observations were taken against local HEAD `1cb23033708fa1308bc2ddee30a4d38eb454049d` and GitHub remote `main` `6f6c5923f5aba9eb08fa8c63e7dca444934f3b1c`. The local branch was sixteen commits ahead with unrelated dirty files. No fetch or checkout was required to compare those states.

The local audit checked canonical launcher arguments; live models on ports 8000/8001; selected container metadata and boot logs; the image digest file; `/proc/meminfo`; current crontab; relevant daemon/watchdog behavior; and metadata-only aggregation of recent call/frontier ledgers. The canonical handoff records the model table, digest, memory snapshot, active schedule, call-policy exceptions and timeout counts.

Useful source locations for rechecking the findings:

- [`cron/serve-models.sh`](../../../cron/serve-models.sh), [`run_state/vllm_image.digest`](../../../run_state/vllm_image.digest), [`ARCHITECTURE.md`](../../../ARCHITECTURE.md).
- [`agent_wrapper/wrapper.py`](../../../agent_wrapper/wrapper.py), [`orchestrator/nara.py`](../../../orchestrator/nara.py), [`agent_wrapper/backends/ollama_openai.py`](../../../agent_wrapper/backends/ollama_openai.py).
- [`agent_wrapper/frontier_cli.py`](../../../agent_wrapper/frontier_cli.py), [`orchestrator/frontier_agenda.py`](../../../orchestrator/frontier_agenda.py), [`workers/frontier_review.py`](../../../workers/frontier_review.py).
- [`cron/weekly-frontier-agenda.sh`](../../../cron/weekly-frontier-agenda.sh), [`cron/watchdog.sh`](../../../cron/watchdog.sh), [`orchestrator/self_improve.py`](../../../orchestrator/self_improve.py).
- [`docs/qwen38_role_setups.md`](../../qwen38_role_setups.md), [`docs/qwen_fp8_windows_plan.md`](../../qwen_fp8_windows_plan.md), [`tests/test_critic_eval_scoring.py`](../../../tests/test_critic_eval_scoring.py).

No fresh local model speed/quality benchmark was run for this handoff. Historical qualification and current boot/configuration evidence are different forms of evidence. Current Qwen quality under the proposed sampling, larger contexts, new KV or drafter remains an experiment.

## Source inventory and freshness

All external sources below were accessed on **2026-09-14**. Unversioned documentation and issue status may change. The canonical handoff places citations near the claims; this inventory identifies source provenance and dates.

| Evidence | Source and date/version |
|---|---|
| Exact Qwen inference contract | [Qwen3.8-27B official card](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/README.md), release 2026-08-14 |
| Exact Gemma inference/history contract | [Official model card](https://huggingface.co/google/gemma-4-26B-A4B/blob/560dbcf0c2515abf83c1641b43e21bbcf178e2d7/README.md), pinned revision; [generation configuration](https://huggingface.co/google/gemma-4-26B-A4B/blob/560dbcf0c2515abf83c1641b43e21bbcf178e2d7/generation_config.json) |
| Runtime support | [SGLang Qwen cookbook](https://docs.sglang.io/cookbook/autoregressive/Qwen/Qwen3.8-27B); [vLLM 0.21 release](https://github.com/vllm-project/vllm/releases/tag/v0.21.0), 2026-05-15 |
| Separate drafter | [IncoAI DFlash2 card](https://huggingface.co/incoai/Qwen3.8-27B-DFlash2), developer source |
| Target-head compatibility | [SGLang PR #35496](https://github.com/sgl-project/sglang/pull/35496), merged 2026-08-20 |
| Reproducible Spark performance | [Pangoleen configuration](https://github.com/pangoleen/qwen3.8-27b-dgx-spark-dflash2/blob/master/README.md), [results](https://github.com/pangoleen/qwen3.8-27b-dgx-spark-dflash2/blob/master/RESULTS.md), tests dated 2026-09-02; **third-party measurement** |
| Request cleanup | [SGLang PR #35255](https://github.com/sgl-project/sglang/pull/35255), merged 2026-09-04; [0.5.19 source](https://raw.githubusercontent.com/sgl-project/sglang/v0.5.19/python/sglang/srt/managers/tokenizer_manager.py) |
| Concrete unresolved runtime reports | [Thinking divergence #38009](https://github.com/sgl-project/sglang/issues/38009), [transition race #36876](https://github.com/sgl-project/sglang/issues/36876), open when checked; reports are leads, not established local failures |
| Scientific program benchmark | [ScienceAgentBench ICLR 2025 paper](https://proceedings.iclr.cc/paper_files/paper/2025/hash/f12b4df26344f3be803c06b555252efe-Abstract-Conference.html); [verified release record](https://github.com/OSU-NLP-Group/ScienceAgentBench/blob/main/README.md), 2026-04-30 |
| Reproduction reliability/OOD | [CORE-Bench follow-up](https://arxiv.org/abs/2606.26158), preprint v1 2026-06-23 |
| Discovery-stage decomposition | [ResearchBench](https://aclanthology.org/2026.findings-acl.644/), Findings ACL 2026; [current dataset card](https://huggingface.co/datasets/ankilok/ResearchBench/blob/main/README.md) |
| Research replication | [PaperBench release](https://openai.com/index/paperbench/), 2025-04-02; [primary paper](https://cdn.openai.com/papers/22265bac-3191-44e5-b057-7aaacd8e90cd/paperbench.pdf) |
| Terminal/science executable tasks | [Terminal-Bench 4.0](https://www.tbench.ai/news/terminal-bench-4-0), 2026-08-28; [Science 0.1](https://www.tbench.ai/news/terminal-bench-science-0-1), 2026-08-27 |
| Human-time task difficulty | [METR methodology](https://evals.alignment.org/time-horizons/), methodology page checked at current revision |
| Agent eval design | [Anthropic agent-evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), 2026-01-09 |
| Sequential inference | [Johari et al., Always Valid Inference](https://pubsonline.informs.org/doi/10.1287/opre.2021.2135), journal publication 2021 |
| OpenAI API implementation | [Web search](https://developers.openai.com/api/docs/guides/tools-web-search), [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), current official documentation |
| Claude API implementation | [Web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool), [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), current official documentation |
| Actual CLI invocation semantics | [Claude programmatic usage](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference), checked alongside installed help |

## Remaining uncertainty and what changes the verdict

The research establishes worthwhile experiments, not an upgrade. The decision changes only after a validated local trial demonstrates improved target-function success or efficiency with preserved required reliability and headroom. Current open questions are effective reasoning controls on vLLM 0.21, model-specific history behavior through the project scaffold, thinking-mode DFlash quality/performance, dual-resident memory, and a realistic weekly resource envelope.

Optional API mode, a recurring budget and the upgrade scheduler's activation remain design decisions for the implementation packet. Existing maintenance authority covers producing and reviewing that packet and its code; no additional Git/PR permission is implied by those unresolved runtime decisions.
