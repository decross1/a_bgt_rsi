export const meta = {
  name: 'sr-verify-synth',
  description: 'Team 3 W2b: 3 lens-refuters per finding (real / material / honest), two rankers + reconciler under a scale-honest rubric, synthesis, completeness critic',
  phases: [
    { title: 'Refute', detail: '3 lens refuters per finding, majority kills' },
    { title: 'Rank', detail: 'severity-first + effort-first rankers, reconciler' },
    { title: 'Synthesize', detail: 'doc body with four buckets + owner triage; completeness critic' },
  ],
}

const WF = 'systems-review-2026-09'
const RUNLOG = []
const LOG_FIELDS = {
  log_status: { type: 'string', enum: ['passed', 'failed', 'inconclusive', 'completed'] },
  log_observable_expected: { type: 'string' },
  log_observable_actual: { type: 'string' },
  log_duration_ms: { type: 'integer' },
  log_started_at: { type: 'string' },
}
const withLog = (props, required) => ({
  type: 'object', additionalProperties: false,
  properties: { ...props, ...LOG_FIELDS },
  required: [...required, 'log_status', 'log_observable_expected', 'log_observable_actual', 'log_duration_ms', 'log_started_at'],
})
function logRow(taskId, role, r) {
  if (!r) { RUNLOG.push({ task_id: taskId, agent: `workflow:${WF}/${role}`, status: 'failed', observable_actual: 'agent returned null (skipped or terminal error)', observable_expected: 'structured output', duration_ms: null }); return }
  RUNLOG.push({ task_id: taskId, agent: `workflow:${WF}/${role}`, status: r.log_status, observable_actual: r.log_observable_actual, observable_expected: r.log_observable_expected, duration_ms: r.log_duration_ms, started_at: r.log_started_at })
}

const VERDICT = withLog({
  finding_id: { type: 'string' }, lens: { type: 'string', enum: ['real', 'material', 'honest'] },
  refuted: { type: 'boolean' }, reason: { type: 'string' },
  rerun_cmd: { type: 'string' }, rerun_output: { type: 'string' },
  severity_cap: { type: 'string', enum: ['none', 'S1', 'S2', 'S3'] },
  file_line_exists_at_head: { type: 'boolean' },
}, ['finding_id', 'lens', 'refuted', 'reason', 'rerun_cmd', 'rerun_output', 'severity_cap', 'file_line_exists_at_head'])
const RANK = withLog({
  ranker: { type: 'string' },
  ranking_json: { type: 'string' },
  merges: { type: 'array', items: { type: 'string' } },
}, ['ranker', 'ranking_json', 'merges'])
const SYNTH2 = withLog({
  doc_markdown: { type: 'string' },
  owner_triage: { type: 'array', items: { type: 'string' } },
  bucket_counts: { type: 'string' },
  killed_summary: { type: 'array', items: { type: 'string' } },
}, ['doc_markdown', 'owner_triage', 'bucket_counts', 'killed_summary'])
const CRITIC2 = withLog({
  scout_items_without_verdict: { type: 'array', items: { type: 'string' } },
  lanes_thin: { type: 'array', items: { type: 'string' } },
  findings_with_unverified_repro: { type: 'array', items: { type: 'string' } },
  next_round_prompts: { type: 'array', items: { type: 'string' } },
  verdict: { type: 'string', enum: ['complete', 'incomplete'] },
}, ['scout_items_without_verdict', 'lanes_thin', 'findings_with_unverified_repro', 'next_round_prompts', 'verdict'])

const LENS_BRIEF = {
  real: 'lens=real: open the file at HEAD (`git show ' + args.head + ':<path> | sed -n \'<a>,<b>p\'`), set file_line_exists_at_head, re-run repro_cmd yourself (ONLY if it is read-only — grep it for > >> tee rm mv cp touch mkdir open( -X POST pytest "env -u" :8000 :8001 PersistentClient; if not read-only, refuse to run it and refute on the honest ground), paste rerun_output, and decide whether the CLAIM actually follows from the code + output (not merely that the output exists).',
  material: 'lens=material: assume ONE box, ONE user, ~24 cycles/day, <=60 budget units/day. Recompute time_to_impact from the finder\'s numbers plus `df -h /`, cadence from `crontab -l` and `tail -50 logs/nara-daemon.log`, and the daily budget. If the finder gave no measurement, refute. Set severity_cap if the finding is S3-at-this-scale (say the number that makes it so) or must be capped lower than proposed.',
  honest: 'lens=honest: is repro_cmd read-only (grep it for > >> tee rm mv cp touch mkdir open( -X POST pytest "env -u" :8000 :8001 PersistentClient)? Was repro_output pasted verbatim or paraphrased (re-run a read-only part and compare)? Was the window cherry-picked (compare a different window or day)? Was the measurement taken while a cycle ran without saying so (cross-check logs/nara-daemon.log timestamps)? Is the fix_sketch actually bounded (rule 8) or a refactor in disguise?',
}

const refutePrompt = (f, lens) => `You are workflow:${WF}/refute:${lens}:${f.finding_id}. cd /home/decross1/projects/a_bgt_rsi (HEAD ${args.head}; the loop is LIVE).
${args.forbidden}
FINDING (JSON): ${JSON.stringify(f)}
Your job is to REFUTE it. Default to refuted=true if uncertain.
${LENS_BRIEF[lens]}
SEVERITY RUBRIC: ${args.rubric}
Return finding_id="${f.finding_id}", lens="${lens}".`

const rankPrompt = (order, findings) => `You are workflow:${WF}/rank:${order}. cd /home/decross1/projects/a_bgt_rsi.
${args.forbidden}
Apply the rubric to every surviving finding (each carries its three refuter verdicts). Ordering discipline: ${order === 'severity-first' ? 'severity, then time_to_impact ascending, then effort ascending' : 'effort ascending within severity bands, then time_to_impact'}. Merge near-duplicates (name both ids in merges as "Fx <- Fy: why"). Tier S automatically routes to the design-question bucket unless S0. Respect any severity_cap a material refuter set (explain if you override it).
BUCKETS: fix-now = S0 (any E) or S1 with E0/E1; fix-soon = S1 with E2/E3, S2 with E0/E1; design-question-for-owner = any Tier S touch, S2 with E2+, anything relitigating a ratified D-entry, or findings with exactly one refuter dissenting on materiality; wont-fix-at-this-scale = S3 (state the number).
SEVERITY RUBRIC: ${args.rubric}
ranking_json = JSON array of objects with EXACTLY these keys: finding_id, severity, effort, tier, bucket, rank, rationale, merged_into ("" if none).
FINDINGS:
${JSON.stringify(findings)}`

const reconcilePrompt = (r1, r2, findings) => `You are workflow:${WF}/rank:reconcile.
${args.forbidden}
Two rankers produced rankings. Where they differ by >= 1 severity level or bucket, decide and justify in the rationale (cite the refuter verdicts and the rubric). Where they agree, keep it. Output the FINAL ranking_json (same keys: finding_id, severity, effort, tier, bucket, rank, rationale, merged_into) covering every finding id exactly once, and merges as the union.
SEVERITY RUBRIC: ${args.rubric}
RANKER severity-first: ${r1 ? r1.ranking_json : 'n/a'}
RANKER effort-first: ${r2 ? r2.ranking_json : 'n/a'}
FINDINGS (with verdicts): ${JSON.stringify(findings)}`

const synthPrompt = (ranking, findings, killed, errata) => `You are workflow:${WF}/synth. cd /home/decross1/projects/a_bgt_rsi (HEAD ${args.head}).
${args.forbidden}
Write docs/systems_review_2026-09.md as doc_markdown using EXACTLY this structure:
1. Header block (the primary fills runIds): "> Produced ${args.today} by Dynamic Workflows sr-find + sr-verify-synth (N agents). Tree at ${args.head}. READ-ONLY review; no code changed. Load-bearing numbers independently re-verified by the primary (see §Verification tally)."
2. Method (lanes, 2 finders + miss-hunt, 3-lens refute, rubric summary, scale statement: one box / one human).
3. Scout-map errata table (from: ${errata.slice(0, 3000)}).
4. Four buckets — fix-now / fix-soon / design-question-for-owner / wont-fix-at-this-scale — each a table with rows: rank | id | title | file:line | measurement + time_to_impact | S/E/tier | governing D | smallest bounded fix; followed by one short paragraph per fix-now item with the repro command and trimmed output and the refuter notes (including the lone dissent if any).
5. "Owner triage (proposed)" table, <= 10 rows: T<n> | id | one-line | bucket | smallest fix | tier | governing D (the owner files these; the primary does not self-enqueue, D-046).
6. "What the scout missed" (scout_status=new) and "What the scout got wrong" (corrects/contradicts).
7. Open design questions.
8. Killed findings appendix: id | title | majority reason.
9. Verification tally (placeholder for the primary).
Also return owner_triage rows as "T<n> || finding_id || one-line || bucket || smallest fix || tier || governing D", bucket_counts as "fix-now a / fix-soon b / design c / wontfix d / killed e", and killed_summary.
FINAL RANKING: ${ranking}
SURVIVING FINDINGS (with verdicts): ${JSON.stringify(findings)}
KILLED: ${JSON.stringify(killed)}`

const criticPrompt = (doc, findings, killed, lanes) => `You are workflow:${WF}/critic.
${args.forbidden}
Completeness critic for the systems review. Check: (1) every scout-map item (list: ${args.scout_items.join(' ;; ')}) has a verdict somewhere (verified / corrected / killed / found) — list scout_items_without_verdict; (2) lanes_thin: lanes (${lanes.join(', ')}) with < 2 surviving findings and no explicit exhaustion statement; (3) findings_with_unverified_repro: fix-now items whose repro was not re-run by a real-lens refuter with pasted output; (4) next_round_prompts: <= 6 concrete finder prompts for what is still missing. verdict = complete only if (1)-(3) are empty.
DOC: ${doc}
SURVIVING: ${findings.map(f => `${f.finding_id} [${f.lane}] ${f.title}`).join('\n')}
KILLED: ${killed.map(f => `${f.finding_id} [${f.lane}] ${f.title}`).join('\n')}`

phase('Refute')
const verified = (await pipeline(args.findings, async (f) => {
  const vs = (await parallel(['real', 'material', 'honest'].map(lens => () => agent(refutePrompt(f, lens), { schema: VERDICT, phase: 'Refute', label: `refute:${lens}:${f.finding_id}`, effort: 'high' })))).filter(Boolean)
  vs.forEach(v => logRow(`sr_refute_${f.finding_id}_${v.lens}`, `refute:${v.lens}:${f.finding_id}`, v))
  const notRefuted = vs.filter(v => !v.refuted).length
  const survives = vs.length >= 2 && notRefuted >= 2
  const caps = vs.map(v => v.severity_cap).filter(c => c && c !== 'none')
  return { ...f, verdicts: vs.map(v => ({ lens: v.lens, refuted: v.refuted, reason: v.reason.slice(0, 600), rerun_cmd: v.rerun_cmd, rerun_output: (v.rerun_output || '').slice(0, 800), severity_cap: v.severity_cap, file_line_exists_at_head: v.file_line_exists_at_head })), survives, severity_caps: caps }
})).filter(Boolean)
const surviving = verified.filter(f => f.survives)
const killed = verified.filter(f => !f.survives)
log(`refute: ${surviving.length} survive / ${killed.length} killed of ${verified.length}`)

phase('Rank')
const [r1, r2] = await parallel([
  () => agent(rankPrompt('severity-first', surviving), { schema: RANK, phase: 'Rank', label: 'rank:severity-first', effort: 'high' }),
  () => agent(rankPrompt('effort-first', surviving), { schema: RANK, phase: 'Rank', label: 'rank:effort-first', effort: 'high' }),
])
logRow('sr_rank_severity', 'rank:severity-first', r1); logRow('sr_rank_effort', 'rank:effort-first', r2)
const rec = await agent(reconcilePrompt(r1, r2, surviving), { schema: RANK, phase: 'Rank', label: 'rank:reconcile', effort: 'max' })
logRow('sr_rank_reconcile', 'rank:reconcile', rec)
const ranking = rec ? rec.ranking_json : (r1 ? r1.ranking_json : '[]')

phase('Synthesize')
const synth = await agent(synthPrompt(ranking, surviving, killed.map(k => ({ finding_id: k.finding_id, lane: k.lane, title: k.title, file_line: k.file_line, verdicts: k.verdicts.map(v => `${v.lens}:${v.refuted ? 'refuted' : 'stands'} — ${v.reason.slice(0, 200)}`) })), args.errata_text || ''), { schema: SYNTH2, phase: 'Synthesize', label: 'synth', effort: 'max' })
logRow('sr_synth', 'synth', synth)
const lanes = [...new Set(args.findings.map(f => f.lane))]
const critic = await agent(criticPrompt(synth ? synth.doc_markdown : '', surviving, killed, lanes), { schema: CRITIC2, phase: 'Synthesize', label: 'critic', effort: 'max' })
logRow('sr_critic', 'critic', critic)

return {
  doc_markdown: synth ? synth.doc_markdown : null,
  owner_triage: synth ? synth.owner_triage : [],
  bucket_counts: synth ? synth.bucket_counts : null,
  ranking_json: ranking, merges: rec ? rec.merges : [],
  surviving, killed: killed.map(k => ({ finding_id: k.finding_id, lane: k.lane, title: k.title, file_line: k.file_line, verdicts: k.verdicts })),
  critic, runlog_rows: RUNLOG,
}
