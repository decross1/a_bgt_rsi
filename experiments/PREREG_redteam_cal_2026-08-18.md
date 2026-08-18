# Pre-registration — redteam calibration battery (D-075 R1a)

Status: DRAFT pending one adversarial critique; LOCKS at the commit
carrying the applied fixes. Executes D-075 R1a: the redteam said
fatal_flaw on 52/52 parsed August runs (zero genuine proceeds since June)
— an instrument with no discrimination. The fatal_flaw hard cap STAYS
until this battery's verdict (never silently dropped). D-075 pre-ratifies
the consequence: re-seat on the independent skeptic backend if Gemma
fails.

## Arms (evaluated in order; first arm passing ALL bars wins)

1. **gemma-current** — the production redteam exactly as deployed
   (workers/redteam_critic.py prompt, vllm-gemma backend).
2. **gemma-revised** — ONE honest prompt revision (the builder authors it;
   design intent: "fatal_flaw means the claim CANNOT be rescued by any
   reasonable experiment — a fixable weakness is `proceed` with critique";
   revision text frozen in the driver as a constant before any call).
3. **qwen38** — the gemma-current prompt on backend vllm-qwen
   (qwen3.8-27b-nvfp4-mtp), the D-075 re-seat candidate.

Order encodes the tie-break: local status quo preferred; the re-seat only
wins if both Gemma arms fail.

## Fixtures (24; ids pinned by the builder in its report, resolution
rules here)

- **Known-good (12)** — a competent methodologist would say `proceed`:
  (a) the 3 hypotheses behind the only genuine historical proceeds (June
  2026 rows — builder resolves from loop_memory); (b) the exp003 Vickrey
  claim (empirically confirmed at 100% truthful-bid); (c) the 3
  expected-survives battery cases (novel_on_01/02/03 hypothesis texts);
  (d) 5 constructed sound claims (well-operationalized, falsifiable,
  clearly-scoped — written by the builder, frozen as constants,
  domain-matched to the corpus).
- **Known-bad (12)** — genuinely fatal, not merely weak: (a) the
  iter-2026-08-18-005 attribution-confound claim (redteam's own
  historically-validated catch); (b) 5 planted-flaw constructions per the
  day-9 critic battery pattern (circular claim, unfalsifiable clause,
  undefined metric, confounded "rather than", contradiction with a known
  theorem); (c) the 2 nonsense battery cases (word-salad,
  not-a-question); (d) 4 historical claims killed on VERIFIED grounds
  (frontier-vetoed or experiment-refuted with recorded reasons — builder
  resolves, listing the evidence per pick).

Each fixture = {id, hypothesis_text, label, provenance}. Labels are
frozen at lock; a disputed label is removed before lock, never after.

## Protocol

One redteam call per fixture per arm (production budgets), fresh
interpreter per arm, calls-log isolation (`LOOP_V0_CALLS_LOG` per arm),
env -u MOCK_LLM, artifacts to bench/redteam_cal/runs/ with full
provenance. Verdicts recorded as returned (`fatal_flaw` / `proceed` /
`unscored` per D-075 R1b).

## Bars (LOCKED at commit; each evaluated independently — rule 4)

Per arm:
1. **Parse health:** unscored rate ≤ 10% (unscored rows are excluded from
   the discrimination denominators and reported).
2. **Catches the bad:** fatal_flaw on ≥ 75% of parsed known-bad.
3. **Passes the good:** fatal_flaw on ≤ 35% of parsed known-good (i.e.
   proceed ≥ 65%).
4. **Not a coin with a bias:** the arm's fatal_flaw rates on good vs bad
   differ by ≥ 30 percentage points.

**Adoption rule:** the first arm in order passing all four bars becomes
the production redteam configuration (a prompt swap and/or the
pre-ratified backend re-seat — no further ratification needed per D-075;
the change is committed with this battery's table). If NO arm passes:
the cap's disposition returns to the owner with the table — options
pre-stated as (i) keep cap + redteam stays sole L1 gate knowing its
character, (ii) demote fatal_flaw to advisory-at-L1 while keeping the L4
`proceed` requirement (the D-053 lesson stated: this must NOT recreate
the advisory-ignored pathology — L4 still blocks), (iii) commission a
new instrument. No option auto-executes.

## Reporting

Verdict matrix (24×3), per-bar pass/fail per arm, confusion tables,
per-fixture verdicts with rationales digested, wall/tok per call
(first Qwen-3.8-as-redteam timing data), plus the exact production diff
the winning arm implies. Run-log rows per arm; results feed the D-0zz…
successor decision entry only via the adoption rule above.
