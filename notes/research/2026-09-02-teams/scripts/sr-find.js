export const meta = {
  name: 'sr-find',
  description: 'Team 3 W2a: adversarial systems review — attack the scout map, find + reproduce findings per lane (measure-first and trace-first), miss-hunt until dry',
  phases: [
    { title: 'Map-attack', detail: 'verify / correct every scout fact at HEAD' },
    { title: 'Find', detail: '2 finders per lane with distinct methods; every finding reproduced with a command' },
    { title: 'Miss-hunt', detail: 'per-lane "what did the scout miss" rounds until 2 dry (cap 4)' },
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

const FINDINGS = withLog({
  lane: { type: 'string' }, method: { type: 'string', enum: ['measure', 'trace', 'miss-hunt'] },
  findings_json: { type: 'string' },
  finding_count: { type: 'integer' },
  commands_run: { type: 'array', items: { type: 'string' } },
  could_not_reproduce: { type: 'array', items: { type: 'string' } },
  cycle_live_during_measurement: { type: 'boolean' },
}, ['lane', 'method', 'findings_json', 'finding_count', 'commands_run', 'could_not_reproduce', 'cycle_live_during_measurement'])

const MAP_ATTACK = withLog({
  chunk: { type: 'string' },
  checks_json: { type: 'string' },
  errata_count: { type: 'integer' }, verified_count: { type: 'integer' },
}, ['chunk', 'checks_json', 'errata_count', 'verified_count'])

const FINDING_KEYS = 'title, file_line ("path:L1-L2" at HEAD), claim, repro_cmd, repro_output (verbatim, <=1500 chars), measurement (e.g. "88 MB/day"), time_to_impact ("disk full in ~410 d at current df" | "n/a"), severity_proposed (S0|S1|S2|S3), severity_rationale, effort_proposed (E0|E1|E2|E3), tier (P|S), fix_sketch (<=3 sentences, smallest bounded change), scout_status (new|verifies|extends|corrects|contradicts), governing_decision ("D-063" | "none"), confidence (0-1)'

const mapAttackPrompt = (chunk, i) => `You are workflow:${WF}/map:${i}. cd /home/decross1/projects/a_bgt_rsi (HEAD ${args.head}; the loop is LIVE).
${args.forbidden}

A scout produced the factual map below. ATTACK it: for every factual claim with a file:line or a number, verify it at HEAD (\`git show ${args.head}:<path> | sed -n 'a,bp'\`, \`wc -l\`, \`ls -la\`, \`python3 -c\` over ledgers, \`journalctl --user -u nara-daemon\`, \`systemctl --user show\`). Classify each as verified | corrected (give corrected_cite/number) | stale (was true, changed since) | unverifiable (say why). Known errata already found: ${args.known_errata}
Return checks_json as a JSON array of objects with EXACTLY these keys: scout_claim, status, corrected_cite, command, output_excerpt (<=300 chars). errata_count = corrected+stale; verified_count = verified.

SCOUT MAP CHUNK ${i}:
${chunk}`

const finderPrompt = (lane, method, errata) => `You are workflow:${WF}/find:${lane.id}:${method}. cd /home/decross1/projects/a_bgt_rsi (HEAD ${args.head}; the loop is LIVE — daemon restarted 03:22Z today; hourly cron at :00).
${args.forbidden}

APPARATUS IN BRIEF + OPERATING SCALE: ${args.brief} ONE DGX Spark, ONE human, hourly cron + event daemon, ~24 cycles/day, <=60 budget units/day. "Unscalable" must be argued against MEASURED growth (bytes/day, ms/row x cadence), never against imagined scale.

LANE ${lane.id} — ${lane.name}. LENS: ${lane.lens}
SEEDS already mapped by the scout (ATTACK them: verify, extend, correct — do not merely restate): ${lane.seeds}
REPRODUCTION STANDARD for this lane: ${lane.repro}
KNOWN ERRATA in the scout map (from the map-attack agents): ${errata}

METHOD ${method}: ${method === 'measure' ? 'START FROM THE LEDGERS AND PROCESSES — measure first (sizes, rates, counts, timings, fd tables, journald), then find the code that produces the number.' : 'START FROM THE CODE PATH — read the modules in this lane end-to-end, trace the control/data flow, then measure what the code implies.'}

SEVERITY RUBRIC (scale-honest): ${args.rubric}

Every finding MUST carry: a file:line you opened with sed -n; a repro_cmd you actually ran; its verbatim output; a measurement; a time_to_impact; severity per the rubric with rationale; the smallest bounded fix (rule 8: a config line, a guard, a rotation, a cap — never a refactor); the entrenchment tier (D-062: spine/schema/pins/cron/serve-models.sh/CLAUDE.md/DECISIONS.md/run_state semantics = S, else P); and the governing DECISION if one exists (grep '^## D-' DECISIONS.md). Also list what you tried and could NOT reproduce in could_not_reproduce. Empty findings are acceptable; invented ones are not.
findings_json = a JSON array of objects with EXACTLY these keys: ${FINDING_KEYS}.
DONE-CONDITION: >= ${lane.min_findings || 4} distinct findings or an explicit "lane exhausted" with the commands that show it; finding_count == length of findings_json; cycle_live_during_measurement set from \`tail -3 logs/nara-daemon.log\` and \`tail -2 logs/coordinator-cron.log\`.`

const missHuntPrompt = (lane, seenTitles, errata, round) => `You are workflow:${WF}/miss:${lane.id}:r${round}. cd /home/decross1/projects/a_bgt_rsi (HEAD ${args.head}; the loop is LIVE).
${args.forbidden}

APPARATUS + SCALE: ${args.brief} ONE box, ONE human, ~24 cycles/day.
LANE ${lane.id} — ${lane.name}. LENS: ${lane.lens}. REPRO STANDARD: ${lane.repro}
SEVERITY RUBRIC: ${args.rubric}
KNOWN ERRATA: ${errata}

ALREADY FOUND in this lane and its neighbours (do NOT restate any of these; a restatement counts as zero):
${seenTitles.map(t => '- ' + t).join('\n')}

Your job is ONLY what is NOT in that list: a different file, a different mechanism, a different failure mode, an interaction between lanes, a growth rate nobody measured, a swallowed error nobody traced, a scout claim nobody attacked. Reproduce everything with a command and verbatim output. If you find nothing new after a real search (list the commands), return an empty findings_json "[]" with finding_count 0 — an empty list is a valid, honest result; an invented finding is not.
findings_json objects have EXACTLY these keys: ${FINDING_KEYS}. method = "miss-hunt".`

const seen = new Map()
const all = []
const key = f => `${String(f.file_line || '').split(':')[0]}|${Math.floor((parseInt(String(f.file_line || '').split(':')[1]) || 0) / 30)}|${String(f.title || '').toLowerCase().slice(0, 40)}`
const ingest = (res, tag) => {
  let fresh = 0
  for (const r of res.filter(Boolean)) {
    let arr = []
    try { arr = JSON.parse(r.findings_json) } catch (e) { log(`${tag}: unparsable findings_json from ${r.lane}/${r.method}`); continue }
    if (!Array.isArray(arr)) continue
    for (const f of arr) {
      if (!f || !f.title) continue
      const k = key(f); if (seen.has(k)) continue
      seen.set(k, f.title); f.finding_id = `F${all.length + 1}`; f.lane = r.lane; f.method = r.method; all.push(f); fresh++
    }
  }
  return fresh
}

phase('Map-attack')
const errataRes = (await parallel(args.scout_chunks.map((c, i) => () => agent(mapAttackPrompt(c, i), { schema: MAP_ATTACK, phase: 'Map-attack', label: `map:${i}`, effort: 'high' })))).filter(Boolean)
errataRes.forEach((e, i) => logRow(`sr_map_${i}`, `map:${i}`, e))
const errataText = errataRes.map(e => {
  try { return JSON.parse(e.checks_json).filter(c => c.status !== 'verified').map(c => `${c.status}: ${c.scout_claim} -> ${c.corrected_cite || ''}`).join('; ') } catch (err) { return '' }
}).filter(Boolean).join(' | ').slice(0, 4000) || args.known_errata
log(`map-attack: ${errataRes.reduce((n, e) => n + (e.verified_count || 0), 0)} verified, ${errataRes.reduce((n, e) => n + (e.errata_count || 0), 0)} errata`)

phase('Find')
const LANES = args.lanes
const round1 = await parallel(LANES.flatMap(l => ['measure', 'trace'].map(m => () => agent(finderPrompt(l, m, errataText), { schema: FINDINGS, phase: 'Find', label: `find:${l.id}:${m}`, effort: 'high' }))))
round1.forEach((r, i) => { const l = LANES[Math.floor(i / 2)]; const m = i % 2 ? 'trace' : 'measure'; logRow(`sr_find_${l.id}_${m}`, `find:${l.id}:${m}`, r) })
log(`round 1: ${ingest(round1, 'r1')} findings (nulls: ${round1.filter(r => !r).length})`)

phase('Miss-hunt')
let dry = 0, round = 0
while (dry < 2 && round < 4) {
  round++
  const titles = [...seen.values()]
  const res = await parallel(LANES.map(l => () => agent(missHuntPrompt(l, titles, errataText, round), { schema: FINDINGS, phase: 'Miss-hunt', label: `miss:${l.id}:r${round}`, effort: 'high' })))
  res.forEach((r, i) => logRow(`sr_miss_${LANES[i].id}_r${round}`, `miss:${LANES[i].id}:r${round}`, r))
  const fresh = ingest(res, `miss r${round}`)
  log(`miss-hunt round ${round}: ${fresh} fresh (total ${all.length})`)
  if (fresh === 0) dry++; else dry = 0
}
if (round === 4 && dry < 2) log('miss-hunt hit the 4-round cap before going dry — coverage NOT exhaustive')

return { findings: all, finding_count: all.length, map_errata: errataRes, errata_text: errataText, runlog_rows: RUNLOG }
