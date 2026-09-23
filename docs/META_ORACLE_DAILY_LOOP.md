# Daily loop: Oracle plans, Nara builds and runs, meta-oracle reviews

Status: **approved design, building, 2026-09-22.** Owner answers of 2026-09-22:
*hard gate "for now, but you can override this if you get alot of work that is
passing validation"*; merges: *"you can merge work, again, unless it's like before
where it's clean consistently and your involvement in merge/clean up is easy. Then
permit pi oracle to do it"*; start: build, then a manual dry run. Live now: the
`review` kind and the lane gate (`config/nara_lane.json`).

**Dry run, 2026-09-22 (evening):** every phase ran once by hand (mailbox seq 14–44).
The gate held Nara's d4 three times (two meta `amend` verdicts and the lane's 8 KiB
test cap). Code review caught a branch cut from the wrong base, which would have
merged 35 unreviewed commits. The retro logged 11 findings: 0 severe, 8 material,
3 minor, mostly `missing_context` (fixtures built on assumed file shapes). Not yet
exercised: Nara building an Oracle-planned item (the comms ping proved the build
path). Owner rulings after the dry run: the plan file under `run_state/daily_plans/`
is a named, data-only exception to "Oracle never writes the main checkout"; a v1.2
continuity canary for fixture-shape drift is approved (Oracle builds it); the
Wednesday research gate is **B, the closeout**. Timers wait for a separate
discussion with the owner. It builds on D-082, `docs/ORACLE_NARA_MAILBOX.md` and
`docs/ORACLE_NARA_BUILDOUT_PLAN.md`, and it re-baselines the 2026-09-21 seven-day
plan (`a_bgt_rsi_v2_artifacts/2026-09-21/seven-day-lab-plan-8h/SEVEN_DAY_PLAN.md`).

## 1. Goal and roles

Owner direction, 2026-09-22: each day the Pi Oracle evaluates the lab (state, tools,
research, bottlenecks) and writes a daily plan. The owner does not yet trust a local
125B-A6B model to run this unsupervised for days, so a frontier meta-oracle reviews
the plan and the code, amends what is wrong, and turns Oracle's mistakes into
improvements to Oracle's system.

| Party | Runs on | Owns |
|---|---|---|
| **Oracle** | Pi on local Flash | The daily plan. Development of the lab's architecture and system (`orchestrator/`, `schema/`, `ui/`, services, cron), agent skills and contracts, and `oracle_system`. Works on `oracle/<id>` branches. |
| **Nara** | Local Flash | Everything inside the lab: experiments, internal lab processes, tools the lab needs. **Development** through the lane (fenced paths, `nara/<id>` branches, never merges). **Running** through its existing scheduler and research gates. |
| **Meta-oracle** | Claude Opus 5.5 (`claude -p`, actor `claude`) | Reviews every daily plan and every branch before it merges, and merges accepted branches during Stage 0. Amends plans, and diagnoses Oracle's bad decisions. Never posts plan items and never generates research content or writes loop memory (D-061). |
| **Owner** | — | Authority changes, service installs and research gates. |

Routing rule (checked by the meta-oracle on every item): *is it needed inside the lab
(an experiment, lab process or lab tool)?* → Nara. *Does it change how the lab or
Oracle is built (architecture, contracts, skills, services, UI)?* → Oracle. Anything
touching authority → owner.

## 2. The day (America/Los_Angeles)

| Time | Who | Step | Output |
|---|---|---|---|
| 07:30 | Oracle | **Morning cycle.** Reads the lab state packet (§4), yesterday's plan and receipts, open meta-oracle findings and the week plan. Writes the daily plan (§3). | `run_state/daily_plans/YYYY-MM-DD.json` plus mailbox note `PLAN READY` (path + sha256) |
| 08:00 | Meta-oracle | **Plan review.** Gathers the state packet itself instead of trusting Oracle's summary. Checks each item for routing, evidence, scope, dependencies, the Flash budget and authority. | Mailbox `review`: `accept`, `amend` (concrete item edits) or `reject` (with reasons) |
| after review | Oracle | Posts Nara `plan_item`s for accepted items only. Each waits in the lane until the meta-oracle accepts it. Starts its own items on branches. | Plan items; `oracle/<id>` branches |
| day | Nara | The lane builds its items. The scheduler runs admitted experiment work under the existing research gates. | Receipts |
| 13:00, 18:30 | Meta-oracle | **Code review** of every branch marked `READY FOR REVIEW` (framework code-review skill, `git diff <merge-base>..<sha>`, tests run). | Per-branch `review` verdict |
| after review | Meta-oracle | Merges accepted branches (interactive session) until the trust ramp hands merging to Oracle. | Merges on `main` |
| 21:00 | Oracle | **Evening receipt.** Plan against outcome, carry-overs, blockers. | Mailbox note `DAY CLOSED` |
| 21:30 | Meta-oracle | **Decision review.** Diagnoses each of Oracle's mistakes that day (§5). Also audits for merges that skipped review. | `run_state/meta_oracle_reviews.jsonl` + mailbox note |
| Sun 21:30 | Meta-oracle | **Weekly rollup.** Mistakes by cause, the top system improvement and the Stage-ramp recommendation. | Note to `owner` and a planning input for Oracle |

Flash takes one request at a time. The Oracle cycles and Nara's builds share it, so
the research block keeps the first uninterrupted slot, as in the seven-day plan.

## 3. Daily plan contract (Oracle writes, meta-oracle checks)

```json
{"date": "2026-09-23", "state_packet_sha256": "…",
 "lab_state": [{"claim": "…", "evidence": "path|command|msg_id"}],
 "bottlenecks": [{"what": "…", "evidence": "…", "cost_of_leaving_it": "…"}],
 "carry_over": [{"item": "yesterday id", "disposition": "done|continue|drop", "why": "…"}],
 "week_alignment": "which seven-day outcome today moves",
 "items": [{"id": "d1", "owner": "nara|oracle|owner", "lane": "nara_dev|nara_run|oracle_dev|owner_decision",
            "goal": "G0.1", "repo": "a_bgt_rsi|oracle_system", "title": "…", "summary": "≤90 plain characters for the owner", "why_today": "…",
            "allowed_write_paths": ["…"], "acceptance": "objective check",
            "depends_on": [], "flash_minutes": 10}],
 "not_doing": [{"what": "…", "why": "…"}]}
```

Every item has a plain-language `summary` (at most 90 characters; the dashboard shows it). Every item cites a goal ID from `docs/v2/ALIGNMENT_AND_GOALS.md` §6 (D-084).
Every state claim needs evidence. An item without an objective acceptance check is
itself a review finding. At most 5 items a day in Stage 0.

## 4. Lab state packet

`tools/lab_state_packet.py` (to build) produces a deterministic JSON snapshot that
both Oracle and the meta-oracle read: Flash health and served window, service status
(`nara-daemon`, lane, timers), pause files, mailbox fold, lane status, the research
focus, both repos' heads and unmerged branches, the run-log tail and failures, and
open meta-oracle findings. Neither side's model summary counts as evidence. This is
a good **first Nara item** (lab tool, lane-fenced, pure).

## 5. Decision review: from mistake to system fix

Each of Oracle's mistakes becomes one row in `run_state/meta_oracle_reviews.jsonl`:

```json
{"date": "…", "artifact": "plan d3 | branch sha | msg_id", "what_happened": "…",
 "severity": "minor|material|severe", "evidence": "…",
 "cause": "missing_context|stale_state|wrong_routing|authority_overreach|scope_too_large|factual_error|ignored_constraint|tool_or_infra|model_capability",
 "fix": {"target": "state_packet|prompt|skill|contract|tool|canary|none", "proposal": "…"},
 "status": "open|proposed|adopted|rejected"}
```

- **Cause first, model last.** `model_capability` is recorded only after the
  alternatives are ruled out: the packet lacked the fact, the prompt did not ask for
  it, the contract allowed it, a tool failed. Most local-model failures are fixable
  in the harness.
- **Fixes to Oracle's system are Oracle's development work.** They become next-day
  plan inputs, and the meta-oracle reviews the fix like any other branch. Fixes to
  authority or contracts go to the owner as a `question`.
- **A cause seen twice becomes a regression canary** proposed for Oracle's continuity
  panel. The panel is frozen at v1.1 through 2026-10-19, so additions are versioned
  and owner-approved.

## 6. Trust ramp

| Stage | Rule | To advance |
|---|---|---|
| **0 (start)** | Every plan and every branch is reviewed before it acts or merges. The lane refuses plan items without an accepting review. The meta-oracle merges accepted branches (Oracle's and Nara's) in an interactive session. | 5 consecutive days with no `severe` and at most 1 `material` finding, and zero merges that skipped review |
| **1** | The meta-oracle relaxes what consistently passes, by its own judgment under the owner's 2026-09-22 grant: task classes exempted through `review_optional_task_classes`, and Pi Oracle merging its own accepted branches once they are consistently clean. Each relaxation is announced in a mailbox note with its evidence. | Owner decision from the weekly rollup |
| **2** | Owner-defined | — |

A `severe` finding moves the loop back to Stage 0. The gate is only as strong as
the attribution: Pi runs with full user access and could post a review as `claude`
or edit `config/nara_lane.json`. The retro audits for both.

## 7. Changes needed

| # | Change | Where | Who |
|---|---|---|---|
| C1 | **Built.** Mailbox kind `review` (actors `claude`, `codex`; must reply to a message): `{verdict: accept\|amend\|reject, summary, accepted_items, amendments, findings}` | `orchestrator/oracle_mailbox.py` + tests | meta-oracle session |
| C2 | **Built, live.** Lane gate: a plan item stays open until a `review` replies to it; `accept` runs it, `amend`/`reject` holds it. Policy `config/nara_lane.json` (`require_meta_review`, `review_optional_task_classes`); missing or unreadable → review required | `orchestrator/nara_lane.py` + tests | same |
| C3 | Lab state packet tool | `tools/lab_state_packet.py` | **Nara**, the first real item |
| C4 | **Drafted, untested live** (by the meta-oracle; Oracle reviews it as its own contract). Phases `plan`, `work`, `close`; `pi -p --no-extensions --no-context-files` on local Flash from the lab repo; skips when `run_state/pause_coordinator` or `run_state/pause_oracle_daily` exists | `oracle_system/prompts/daily_loop.md`, `oracle_system/scripts/oracle-daily` | meta-oracle drafted |
| C5 | **Built, untested live.** Meta-oracle prompt and runner (`plan`, `code`, `retro`); `plan` and `code` exit without a model call when nothing awaits review; `claude -p --model claude-opus-5-5 --permission-mode auto` | `agent/prompts/meta_oracle.md`, `tools/meta_oracle_run.sh` | meta-oracle session |
| C6 | systemd timers for C4 and C5 | `~/.config/systemd/user/` | **owner installs** (the classifier blocks Claude from arming agent services) |
| C7 | Authority: ratify Workstream A and add the meta-oracle review role and the merge policy to D-083 | `oracle_system` charter, `DECISIONS.md`, `CLAUDE.md` | Oracle drafts, owner ratifies |
| C8 | One plan of record: during the trial the sealed `oracle-daily-planning` agenda is an input to Oracle's cycle; after the trial week, retire or upgrade it (buildout B3) so there are not two competing daily plans | timer | owner |
| C9 | `nara_run` items need a hand-off into Nara's scheduler; until then, run items are proposals the owner or Nara's existing research path admits | later | — |

## 8. Setup order

1. **Owner decisions** — this document, the Stage 0 rules, and who merges what.
2. Commit today's work (buildout P0.1) so branches start from a known `main`.
3. Build C1, C2, C5 (meta-oracle session) and draft C4. Full suite green and one real smoke.
4. **Dry run, one day, triggered by hand:** Oracle's morning cycle, then the meta
   review, then C3 as Nara's first item, then code review and merge, then the evening
   receipt and decision review. Fix what breaks.
5. Owner installs the C6 timers; Stage 0 starts. Oracle's first live plan re-baselines
   the rest of the seven-day plan (Wed 23 – Sun 27) against current reality: 262K is
   already served, the reserve is 10 GiB, the lane exists, and the meta-oracle
   replaces Codex as reviewer.
6. Sunday: first weekly rollup and stage decision.
