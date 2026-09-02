export const meta = {
  name: 'rw-deepread',
  description: 'Team 1 W1b: one deep-read profile per related-work target, two citation refuters per profile, tiebreaker on disagreement, bounded re-read',
  phases: [
    { title: 'Deep-read', detail: 'fixed-field profile per target, every field cited' },
    { title: 'Refute', detail: 'primary-source + independent-source refuters, tiebreak on disagreement' },
    { title: 'Re-read', detail: 'profiles with >30% struck citations get one bounded re-read + re-refute' },
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

const PROFILE = withLog({
  system: { type: 'string' }, org: { type: 'string' }, first_public_date: { type: 'string' },
  primary_url: { type: 'string' }, arxiv_id_or_doi: { type: 'string' },
  architecture: { type: 'string' },
  generator_critic_separation: { type: 'string' },
  novelty_method: { type: 'string' },
  evidence_verification_method: { type: 'string' },
  memory_world_model: { type: 'string' },
  human_role: { type: 'string' },
  topic_selection_and_drift_control: { type: 'string' },
  cost_hardware_budgeting: { type: 'string' },
  evaluation_claims: { type: 'string' },
  known_failures_critiques: { type: 'string' },
  openness: { type: 'string' },
  may_memo_reconfirmed: { type: 'string' },
  citations: { type: 'array', items: { type: 'string' } },
  unresolved: { type: 'array', items: { type: 'string' } },
}, ['system', 'org', 'first_public_date', 'primary_url', 'arxiv_id_or_doi', 'architecture', 'generator_critic_separation', 'novelty_method', 'evidence_verification_method', 'memory_world_model', 'human_role', 'topic_selection_and_drift_control', 'cost_hardware_budgeting', 'evaluation_claims', 'known_failures_critiques', 'openness', 'citations', 'unresolved'])

const CITE_VERDICT = withLog({
  system: { type: 'string' }, refuter: { type: 'string', enum: ['primary', 'independent', 'arbiter'] },
  citation_ids: { type: 'array', items: { type: 'string' } },
  url_resolves: { type: 'array', items: { type: 'boolean' } },
  quote_found: { type: 'array', items: { type: 'boolean' } },
  claim_supported: { type: 'array', items: { type: 'boolean' } },
  notes: { type: 'array', items: { type: 'string' } },
  refuted_fields: { type: 'array', items: { type: 'string' } },
  fetch_failures: { type: 'array', items: { type: 'string' } },
}, ['system', 'refuter', 'citation_ids', 'url_resolves', 'quote_found', 'claim_supported', 'notes', 'refuted_fields', 'fetch_failures'])

const FILE_MAP = `hypothesize -> workers/hypothesize.py (+ workers/meta_review.py conditioning, workers/failure_match.py); retrieve -> workers/retrieve_literature.py, workers/ml_intern.py (Semantic Scholar), cron/daily-arxiv.sh, pipeline/arxiv_scraper.py; novelty -> workers/novelty_classify.py, orchestrator/novelty_skeptic.py, docs/novelty_two_axis_rubric.md; critic -> workers/critic.py, workers/critic_loop_v0.py, workers/debate.py, workers/refine_cycle.py; redteam -> workers/redteam_critic.py (+ bench/redteam_cal, D-076/D-077); ladder -> workers/evidence_ladder.py (D-059), orchestrator/finding_promotion.py; ledger -> workers/idea_ledger.py, workers/idea_judge.py, workers/idea_projection.py (D-060); frontier falsifiers -> agent_wrapper/frontier_cli.py, workers/frontier_review.py, orchestrator/frontier_agenda.py, workers/constraint_distill.py (D-061); planner/budget -> orchestrator/coordinator.py, orchestrator/nara_daemon.py, cron/run-coordinator.sh (D-063); topics -> orchestrator/morning_topic.py, orchestrator/topicality.py, orchestrator/domain_anchor.py, docs/research_planning_layer.md (the docket); human gates -> orchestrator/gate_cli.py, ui/backend/attest.py; calibration -> bench/critic_cal, experiments/PREREG_*.md; self-improvement -> orchestrator/self_improve.py (D-066), orchestrator/packet_dispatcher.py (D-062)`

const slugOf = (t) => t.split(' || ')[0].toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40)

const deepReadPrompt = (t) => {
  const [name, url, date] = t.split(' || ')
  const isCoSci = /co-scientist|coscientist/i.test(name) && /google|deepmind/i.test(t)
  return `You are workflow:${WF}/deepread:${slugOf(t)}. Today is ${args.today}.
${args.forbidden}

TARGET: ${name} — ${url} (${date || 'date unknown'}). Row as surfaced by the sweep: ${t}
Read the primary source(s) IN FULL via WebFetch (arXiv abs AND html/pdf where available, org blog, GitHub README) and at least one independent critique or evaluation if one exists.

COMPARE AGAINST THIS APPARATUS:
${args.brief}
Its file map (name the file/step a mechanism would touch): ${FILE_MAP}
${isCoSci ? 'ALSO read the repo file notes/research/2026-05-19-adversarial-review/1_adversarial_review_memo.md (the existing co-scientist critique: C1 self-evaluation circularity, C2 no truth feedback, C3 generate-and-filter, C4 expert-in-loop hides autonomy gap, O1-O3, M1-M5) and state in may_memo_reconfirmed which items you re-confirm or contradict from the primary source.' : 'Set may_memo_reconfirmed to "n/a".'}

RULES: every profile field ends with citation tags like [c1][c2]; each citations row is one string in EXACTLY this format: "c<N> || <url> || <verbatim quote of at most 25 words copied from the fetched text> || supports: <field name>". Quotes WILL be substring-checked by two refuters — copy exactly, no paraphrase, no ellipses. Unknown -> write "not stated in sources" and list the field in unresolved. Never infer a date, venue, cost, or number. Prefer the paper over the blog when they disagree and say they disagree.
DONE-CONDITION: all core fields filled-or-unresolved; >= 6 citations; every citation url fetched by you; first_public_date as YYYY-MM.
Fill log_*: log_observable_expected = "fixed-field profile, every field cited, >=6 fetched citations".`
}

const refutePrompt = (p, lens, ids) => `You are workflow:${WF}/refute:${lens}:${slugOf(p.system + ' || ')}. Today is ${args.today}.
${args.forbidden}

Try to REFUTE this related-work profile of "${p.system}" (${p.primary_url}).
${lens === 'primary' ? 'LENS primary: fetch ONLY the primary paper/abs/html for every citation; for arXiv ids also run `curl -s "http://export.arxiv.org/api/query?id_list=<id>"` to confirm title and date.' : lens === 'independent' ? 'LENS independent: fetch the org blog, GitHub README, press coverage, and any critique; check the citations against those AND attack the profile\'s characterizations (is "no human in the loop" actually stated? is a cost figure the paper\'s or a journalist\'s? is the date the first public version?).' : 'LENS arbiter: the two refuters disagreed on the citations listed below; fetch each URL once more and rule.'}
For EACH citation id below, return parallel arrays (same length, same order as citation_ids): url_resolves (did the URL fetch with content), quote_found (is the quote a verbatim substring of the fetched text after whitespace normalization; case-insensitive), claim_supported (does the profile FIELD's claim actually follow from that quote). DEFAULT TO false IF UNCERTAIN OR THE FETCH FAILS (record the failure in fetch_failures).
Then list refuted_fields as "field :: why (with your own counter-citation url)" for any profile field you can show is wrong or unsupported.
Citations to check (${ids.length}):
${p.citations.filter(c => ids.includes(c.split(' || ')[0].trim())).map(c => '- ' + c).join('\n')}
Profile fields (for claim_supported): architecture=${p.architecture}\ngenerator_critic_separation=${p.generator_critic_separation}\nnovelty_method=${p.novelty_method}\nevidence_verification_method=${p.evidence_verification_method}\nmemory_world_model=${p.memory_world_model}\nhuman_role=${p.human_role}\ntopic_selection_and_drift_control=${p.topic_selection_and_drift_control}\ncost_hardware_budgeting=${p.cost_hardware_budgeting}\nevaluation_claims=${p.evaluation_claims}\nknown_failures_critiques=${p.known_failures_critiques}\nopenness=${p.openness}\nfirst_public_date=${p.first_public_date}
Set refuter="${lens}", system="${p.system}", citation_ids exactly = [${ids.map(i => '"' + i + '"').join(', ')}].`

const citeId = (c) => (c.split(' || ')[0] || '').trim()
function mergeVerdicts(p, vs) {
  const ids = p.citations.map(citeId)
  const per = {}
  for (const id of ids) per[id] = {}
  for (const v of vs) {
    (v.citation_ids || []).forEach((id, i) => {
      if (!(id in per)) return
      const ok = !!(v.url_resolves && v.url_resolves[i]) && !!(v.quote_found && v.quote_found[i]) && !!(v.claim_supported && v.claim_supported[i])
      per[id][v.refuter] = ok
    })
  }
  const verified = [], struck = [], disagreements = []
  for (const id of ids) {
    const a = per[id].primary, b = per[id].independent
    if (a === true && b === true) verified.push(id)
    else if (a === false && b === false) struck.push(id)
    else if (a === undefined && b === undefined) struck.push(id)
    else disagreements.push(id)
  }
  const refutedFields = vs.flatMap(v => v.refuted_fields || [])
  return { verified, struck, disagreements, refutedFields, get struckFraction() { return ids.length ? (this.struck.length) / ids.length : 0 } }
}
function applyTiebreak(merged, tb) {
  if (!tb) { merged.struck.push(...merged.disagreements); merged.disagreements = []; return }
  ;(tb.citation_ids || []).forEach((id, i) => {
    const ok = !!(tb.url_resolves && tb.url_resolves[i]) && !!(tb.quote_found && tb.quote_found[i]) && !!(tb.claim_supported && tb.claim_supported[i])
    const k = merged.disagreements.indexOf(id)
    if (k >= 0) { merged.disagreements.splice(k, 1); (ok ? merged.verified : merged.struck).push(id) }
  })
  merged.struck.push(...merged.disagreements); merged.disagreements = []
  merged.refutedFields.push(...(tb.refuted_fields || []))
}

const refuteBoth = async (p, slug, tag) => {
  const ids = p.citations.map(citeId)
  const vs = (await parallel(['primary', 'independent'].map(lens => () =>
    agent(refutePrompt(p, lens, ids), { schema: CITE_VERDICT, phase: 'Refute', label: `refute:${lens}:${slug}${tag}`, effort: 'high' })))).filter(Boolean)
  vs.forEach(v => logRow(`rw_refute_${slug}_${v.refuter}${tag}`, `refute:${v.refuter}:${slug}${tag}`, v))
  const merged = mergeVerdicts(p, vs)
  if (merged.disagreements.length) {
    const tb = await agent(refutePrompt(p, 'arbiter', merged.disagreements), { schema: CITE_VERDICT, phase: 'Refute', label: `tiebreak:${slug}${tag}`, effort: 'high' })
    logRow(`rw_tiebreak_${slug}${tag}`, `tiebreak:${slug}${tag}`, tb)
    applyTiebreak(merged, tb)
  }
  return { vs, merged }
}

const results = await pipeline(args.targets,
  async (t) => {
    const slug = slugOf(t)
    const p = await agent(deepReadPrompt(t), { schema: PROFILE, phase: 'Deep-read', label: `read:${slug}`, effort: 'high' })
    logRow(`rw_deepread_${slug}`, `deepread:${slug}`, p)
    return { slug, target: t, p }
  },
  async (r) => {
    if (!r || !r.p) return r ? { ...r, merged: null } : null
    const { vs, merged } = await refuteBoth(r.p, r.slug, '')
    return { ...r, verdicts: vs, merged }
  },
  async (r) => {
    if (!r || !r.p || !r.merged) return r
    let out = { ...r, reread: false }
    if (r.merged.struckFraction > 0.3) {
      log(`re-read ${r.slug}: ${Math.round(r.merged.struckFraction * 100)}% of citations struck`)
      const notes = r.verdicts.flatMap(v => (v.notes || []).concat(v.refuted_fields || [])).slice(0, 40)
      const p2 = await agent(deepReadPrompt(r.target) + `\n\nTHIS IS A RE-READ. A previous profile had ${r.merged.struck.length}/${r.p.citations.length} citations struck by refuters. Their notes:\n${notes.map(n => '- ' + n).join('\n')}\nCopy quotes EXACTLY from fetched text; drop any claim you cannot quote.`, { schema: PROFILE, phase: 'Re-read', label: `reread:${r.slug}`, effort: 'high' })
      logRow(`rw_reread_${r.slug}`, `reread:${r.slug}`, p2)
      if (p2) {
        const { vs, merged } = await refuteBoth(p2, r.slug, ':r2')
        out = { ...r, p: p2, verdicts: vs, merged, reread: true, first_profile_struck_fraction: r.merged.struckFraction }
      }
    }
    return out
  })

const kept = results.filter(Boolean)
const withProfile = kept.filter(r => r.p)
const nulls = args.targets.length - withProfile.length
log(`profiles: ${withProfile.length}/${args.targets.length} (nulls: ${nulls}); re-reads: ${withProfile.filter(r => r.reread).length}`)
const summary = withProfile.map(r => ({
  slug: r.slug, system: r.p.system, target: r.target,
  citations_total: r.p.citations.length,
  verified: r.merged ? r.merged.verified.length : 0,
  struck: r.merged ? r.merged.struck.length : r.p.citations.length,
  reread: !!r.reread,
}))
return {
  profiles: withProfile.map(r => ({ slug: r.slug, target: r.target, profile: r.p, verified_ids: r.merged ? r.merged.verified : [], struck_ids: r.merged ? r.merged.struck : [], refuted_fields: r.merged ? r.merged.refutedFields : [], reread: !!r.reread, verdicts: r.verdicts || [] })),
  summary, nulls, runlog_rows: RUNLOG,
}
