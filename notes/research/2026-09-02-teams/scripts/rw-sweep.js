export const meta = {
  name: 'rw-sweep',
  description: 'Team 1 W1a: multi-modal related-work sweep (by-system, by-mechanism, by-venue, by-critique) with completeness critic, loop-until-dry',
  phases: [
    { title: 'Sweep', detail: '14 modality sweepers, primary sources fetched' },
    { title: 'Sweep-critic', detail: 'completeness critic + targeted rounds until dry (K=2, cap 3)' },
  ],
}

const WF = 'related-work-2026-09'
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

const SWEEP = withLog({
  modality: { type: 'string' },
  queries_run: { type: 'array', items: { type: 'string' } },
  hits: { type: 'array', items: { type: 'string' } },
  dead_ends: { type: 'array', items: { type: 'string' } },
  hit_count: { type: 'integer' },
}, ['modality', 'queries_run', 'hits', 'dead_ends', 'hit_count'])

const SWEEP_CRITIC = withLog({
  missing_systems: { type: 'array', items: { type: 'string' } },
  missing_modalities: { type: 'array', items: { type: 'string' } },
  next_queries: { type: 'array', items: { type: 'string' } },
  verdict: { type: 'string', enum: ['complete', 'incomplete'] },
}, ['missing_systems', 'missing_modalities', 'next_queries', 'verdict'])

const MODALITIES = [
  { id: 'system:owner-named', brief: 'The owner-named systems: Google/DeepMind AI co-scientist (Feb 2025), Kosmos (Edison Scientific/FutureHouse, Nov 2025), XScientist (arXiv 2607.12301, Jul 2026 — verify this is real and what it is), Sakana AI Scientist v1 and v2 (and v2 ICLR-workshop acceptance). Find each primary source, its newest version, and any 2026 follow-ups.' },
  { id: 'system:futurehouse-family', brief: 'FutureHouse and Edison family: Robin, PaperQA2, Crow/Falcon/Owl/Phoenix agents, Coscientist (Boiko/Gomes 2023), Virtual Lab (Zou lab). Find primary sources and 2025-2026 updates.' },
  { id: 'system:agentic-discovery', brief: 'Agent Laboratory, AlphaEvolve, FunSearch, DeepScientist, InternAgent/NovelSeek, Ai2 CodeScientist, Denario, Curie, Jr. AI Scientist, ScientistOne, Agon, SCP, aiXiv, Autoscience Mira/ERA, and any other end-to-end autonomous-research system published 2025-2026.' },
  { id: 'mechanism:novelty', brief: 'Novelty evaluation and rediscovery detection in AI-for-science systems: literature-grounded novelty checks, rediscovery rates, LLM-vs-human novelty judgments, and measured failure rates.' },
  { id: 'mechanism:evidence-ladders', brief: 'Evidence ladders, claim verification, traceable claims, structured world models, and tiered confidence in autonomous research systems (e.g. Kosmos traceability, evidence levels, verification pipelines).' },
  { id: 'mechanism:critic-calibration', brief: 'Self-calibration of LLM critics and reviewers: reviewer reliability studies, calibration batteries, adversarial red-teaming of hypotheses, and reported over/under-permissiveness of automated critics.' },
  { id: 'mechanism:topic-selection', brief: 'Topic selection, research-agenda planning, and drift control in autonomous research loops: how systems choose what to work on next, keep on-domain, and avoid runaway or off-field exploration.' },
  { id: 'mechanism:human-gating', brief: 'Human-in-the-loop gating, interruption budgets, and expert oversight in AI co-scientist systems: what humans decide, how often, and how systems avoid flooding the human.' },
  { id: 'mechanism:memory-world-model', brief: 'Memory, world models, idea ledgers, archives (MAP-Elites / quality-diversity), and knowledge accumulation across long-running autonomous research runs.' },
  { id: 'mechanism:budgeted-planning', brief: 'Budgeted planning, compute-aware supervisors, cost accounting, and scheduling in multi-agent research systems; reported cost per finding and hardware requirements; open-weight/local-hardware setups.' },
  { id: 'venue:ml-2025-2026', brief: 'Venue sweep: NeurIPS 2025, ICLR 2026, ICML 2026 (incl. the AI4Science workshop "AI Scientists – Tools, Co-authors, or Founders?"), Agents4Science 2025/2026 — papers and workshop reports on AI scientists and autonomous discovery.' },
  { id: 'venue:nature-science-2025-2026', brief: 'Venue sweep: Nature, Science, Nature Portfolio journals and their news/editorial coverage of AI scientists, autonomous labs, and AI co-scientists in 2025-2026.' },
  { id: 'critique:reproducibility', brief: 'Critical responses: reproducibility and quality critiques of the AI Scientist (Beel et al. 2025 and successors), audits of generated papers, "AI slop" concerns, benchmark critiques (MLR-Bench, AstaBench, ForeSci).' },
  { id: 'critique:llm-as-reviewer', brief: 'Critical literature on LLM-as-reviewer reliability, LLM judges in science, circular self-evaluation (Elo tournaments), and governance/skepticism about autonomous science (2024-2026).' },
]

const seedText = args.seeds.map(s => '- ' + s).join('\n')
const sweeperPrompt = (m, extraQueries) => `You are workflow:${WF}/sweep:${m.id}. Today is ${args.today}; include work through 2026-09.
${args.forbidden}

CONTEXT — the apparatus you are sweeping FOR:
${args.brief}

ALREADY KNOWN SEEDS (do NOT re-surface these as new unless you find a NEWER version or a critique of them; DO verify any you touch):
${seedText}

TASK — modality "${m.id}": ${m.brief}
${extraQueries && extraQueries.length ? 'TARGETED QUERIES the completeness critic asked for (run these first, then your own):\n' + extraQueries.map(q => '- ' + q).join('\n') : ''}
Run >= 8 distinct queries with WebSearch, then WebFetch the primary page for every hit to confirm its name, date, org, and what it is. PRIMARY SOURCES ONLY in hits (arXiv abs/html, publisher page, org blog, GitHub). Aggregators/newsletters go in dead_ends unless they are the only source (say so).
Each hits row is one string with EXACTLY this field order, separated by " || ":
name || primary_url || YYYY-MM || kind(system|critique|benchmark|survey|venue) || org || one-line what it is || why it bears on THIS apparatus (name the pathology P1-P5 or mechanism it speaks to)
Each dead_ends row: query || what came back || why rejected.
DONE-CONDITION: >= 8 queries logged in queries_run; every hit has a primary_url you actually fetched; hit_count == hits.length; nothing invented — if a named system cannot be found, say exactly that in dead_ends.
Fill log_*: log_observable_expected = ">=8 queries, every hit fetched"; log_observable_actual = what actually happened (counts, failures).`

const criticPrompt = (hits, deadEnds, round) => `You are workflow:${WF}/sweep-critic:r${round}. Today is ${args.today}.
${args.forbidden}

CONTEXT: ${args.brief}

The sweep so far surfaced these deduplicated hits (name || url || date || kind || org || what || why):
${hits.map(h => '- ' + h).join('\n')}

Dead ends reported: ${deadEnds.length}
${deadEnds.slice(0, 40).map(d => '- ' + d).join('\n')}

Owner-named systems that MUST be covered: AI co-scientist (Google/DeepMind), Kosmos, XScientist / "X-scientist", Sakana AI Scientist v1+v2. Also expected: Coscientist, Virtual Lab, FutureHouse Robin/PaperQA2/Crow-Falcon-Owl, Agent Laboratory, AlphaEvolve/FunSearch, DeepScientist, InternAgent/NovelSeek, CodeScientist, Denario, Curie, MLR-Bench/AstaBench/Agents4Science, the skeptical literature (Beel et al., LLM-as-reviewer reliability), and 2026 systems (XScientist, Agon, ScientistOne, ForeSci, SCP, Jr. AI Scientist, aiXiv, Mira/ERA).
Which named systems are MISSING from the hits? Which modalities look thin (a mechanism with < 3 hits, no 2026 coverage, no critique coverage)? Propose <= 6 targeted next_queries (each a concrete search string, optionally prefixed "modality-id: "). verdict = complete only if every owner-named system is present with a fetched primary URL and every mechanism has >= 3 hits.`

const seen = new Map()
const key = (row) => {
  const parts = row.split(' || ')
  const name = (parts[0] || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  const url = (parts[1] || '').toLowerCase()
  const arx = (url.match(/(\d{4}\.\d{4,5})/) || [])[1]
  return arx ? 'arxiv:' + arx : 'name:' + name.slice(0, 40)
}
const allHits = []
const allDead = []
const ingest = (res, tag) => {
  let fresh = 0
  for (const r of res.filter(Boolean)) {
    for (const h of (r.hits || [])) { const k = key(h); if (seen.has(k)) continue; seen.set(k, h); allHits.push(h); fresh++ }
    for (const d of (r.dead_ends || [])) allDead.push(`${r.modality}: ${d}`)
  }
  log(`${tag}: ${fresh} fresh hits (total ${allHits.length})`)
  return fresh
}

phase('Sweep')
const round1 = await parallel(MODALITIES.map(m => () => agent(sweeperPrompt(m, []), { schema: SWEEP, label: `sweep:${m.id}`, phase: 'Sweep', effort: 'high' })))
round1.forEach((r, i) => logRow(`rw_sweep_${MODALITIES[i].id}`, `sweep:${MODALITIES[i].id}`, r))
const nulls1 = round1.filter(r => !r).length
if (nulls1) log(`round 1: ${nulls1} sweepers returned null`)
ingest(round1, 'round 1')

phase('Sweep-critic')
const critics = []
let dry = 0, round = 1
while (dry < 2 && round < 3) {
  const critic = await agent(criticPrompt(allHits, allDead, round), { schema: SWEEP_CRITIC, label: `critic:r${round}`, phase: 'Sweep-critic', effort: 'high' })
  logRow(`rw_sweep_critic_r${round}`, `sweep-critic:r${round}`, critic)
  critics.push(critic)
  if (!critic || critic.verdict === 'complete' || !(critic.next_queries || []).length) { log(`critic r${round}: ${critic ? critic.verdict : 'null'} — stopping`); break }
  round++
  const buckets = new Map()
  for (const q of critic.next_queries.slice(0, 6)) {
    const m = q.match(/^([a-z-]+:[a-z0-9-]+):\s*(.+)$/i)
    const mid = m && MODALITIES.find(x => x.id === m[1]) ? m[1] : 'targeted'
    const qq = m ? m[2] : q
    if (!buckets.has(mid)) buckets.set(mid, [])
    buckets.get(mid).push(qq)
  }
  const jobs = [...buckets.entries()].map(([mid, qs]) => () => {
    const m = MODALITIES.find(x => x.id === mid) || { id: `targeted:r${round}`, brief: 'Targeted follow-up queries from the completeness critic: ' + qs.join('; ') }
    return agent(sweeperPrompt(m, qs), { schema: SWEEP, label: `sweep:r${round}:${m.id}`, phase: 'Sweep-critic', effort: 'high' })
  })
  const res = await parallel(jobs)
  res.forEach((r, i) => logRow(`rw_sweep_r${round}_${i}`, `sweep:r${round}:${[...buckets.keys()][i]}`, r))
  const fresh = ingest(res, `round ${round}`)
  if (fresh === 0) dry++; else dry = 0
}
if (round >= 3 && dry < 2) log('sweep hit the 3-round cap before going dry — coverage may not be exhaustive')

return { targets: allHits, hit_count: allHits.length, dead_ends: allDead, critics, runlog_rows: RUNLOG }