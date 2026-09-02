export const meta = {
  name: 'rw-synthesis',
  description: 'Team 1 W1c: judge-panel synthesis of verified related-work profiles, draft decision entries with governance refuters, completeness critic',
  phases: [
    { title: 'Synthesize', detail: '3 angles: mechanism-first, failure-first, cost/solo-first' },
    { title: 'Judge', detail: '3 judges score all attempts; merger builds the final' },
    { title: 'Draft', detail: 'one DRAFT-D entry per mechanism + governance refuter' },
    { title: 'Critic', detail: 'completeness critic over the final doc' },
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

const SYNTH = withLog({
  angle: { type: 'string' },
  table_rows: { type: 'array', items: { type: 'string' } },
  mechanisms: { type: 'array', items: { type: 'string' } },
  positioning: { type: 'string' },
  doc_markdown: { type: 'string' },
  excluded_unverified: { type: 'array', items: { type: 'string' } },
}, ['angle', 'table_rows', 'mechanisms', 'positioning', 'doc_markdown', 'excluded_unverified'])
const JUDGE = withLog({
  attempt: { type: 'string' }, score_0_100: { type: 'integer' }, strengths: { type: 'string' }, weaknesses: { type: 'string' },
  graft_from_others: { type: 'array', items: { type: 'string' } }, factual_errors: { type: 'array', items: { type: 'string' } },
}, ['attempt', 'score_0_100', 'strengths', 'weaknesses', 'graft_from_others', 'factual_errors'])
const DRAFT = withLog({
  draft_id: { type: 'string' }, title: { type: 'string' }, stance: { type: 'string', enum: ['adopt', 'reject', 'defer'] },
  markdown: { type: 'string' },
  touches: { type: 'array', items: { type: 'string' } },
  amends: { type: 'array', items: { type: 'string' } },
  contradicts: { type: 'array', items: { type: 'string' } },
  evidence_refs: { type: 'array', items: { type: 'string' } },
}, ['draft_id', 'title', 'stance', 'markdown', 'touches', 'amends', 'contradicts', 'evidence_refs'])
const GOV = withLog({
  draft_id: { type: 'string' }, refuted: { type: 'boolean' }, decision_refs_accurate: { type: 'boolean' },
  violations: { type: 'array', items: { type: 'string' } }, format_ok: { type: 'boolean' }, reason: { type: 'string' },
}, ['draft_id', 'refuted', 'decision_refs_accurate', 'violations', 'format_ok', 'reason'])
const CRITIC = withLog({
  missing_systems: { type: 'array', items: { type: 'string' } },
  unverified_load_bearing_claims: { type: 'array', items: { type: 'string' } },
  mechanisms_without_file_target: { type: 'array', items: { type: 'string' } },
  pathologies_unaddressed: { type: 'array', items: { type: 'string' } },
  next_round: { type: 'array', items: { type: 'string' } },
  verdict: { type: 'string', enum: ['complete', 'incomplete'] },
}, ['missing_systems', 'unverified_load_bearing_claims', 'mechanisms_without_file_target', 'pathologies_unaddressed', 'next_round', 'verdict'])

// Build the verified view of each profile: keep only verified citations; flag fields whose refuters raised objections.
const verifiedView = (p) => {
  const prof = p.profile
  const okIds = new Set(p.verified_ids || [])
  const cites = (prof.citations || []).filter(c => okIds.has((c.split(' || ')[0] || '').trim()))
  const struck = (prof.citations || []).filter(c => !okIds.has((c.split(' || ')[0] || '').trim()))
  const fields = ['architecture', 'generator_critic_separation', 'novelty_method', 'evidence_verification_method', 'memory_world_model', 'human_role', 'topic_selection_and_drift_control', 'cost_hardware_budgeting', 'evaluation_claims', 'known_failures_critiques', 'openness']
  const lines = [`### ${prof.system} (${prof.org}; ${prof.first_public_date}; ${prof.primary_url}; ${prof.arxiv_id_or_doi})`]
  for (const f of fields) {
    const v = String(prof[f] || '')
    const tags = (v.match(/\[c\d+\]/g) || []).map(t => t.slice(1, -1))
    const anyVerified = tags.some(t => okIds.has(t))
    const objected = (p.refuted_fields || []).some(rf => rf.toLowerCase().startsWith(f.toLowerCase()))
    lines.push(`- ${f}: ${v} ${tags.length && !anyVerified ? '[UNVERIFIED — all citations struck]' : ''}${objected ? ' [REFUTER OBJECTION: ' + (p.refuted_fields || []).filter(rf => rf.toLowerCase().startsWith(f.toLowerCase())).join('; ').slice(0, 300) + ']' : ''}`)
  }
  if (prof.may_memo_reconfirmed && prof.may_memo_reconfirmed !== 'n/a') lines.push(`- may_memo_reconfirmed: ${prof.may_memo_reconfirmed}`)
  lines.push(`- VERIFIED citations (${cites.length}): ${cites.join(' ;; ')}`)
  if (struck.length) lines.push(`- STRUCK citations (${struck.length}, do not use): ${struck.map(c => c.split(' || ')[0]).join(', ')}`)
  if ((prof.unresolved || []).length) lines.push(`- unresolved: ${prof.unresolved.join(', ')}`)
  return lines.join('\n')
}
const PROFILES_TEXT = args.profiles.map(verifiedView).join('\n\n')

const ANGLES = [
  ['mechanism-first', 'What is borrowable and where does it plug in: for every peer mechanism, name the file/step HERE it would change and the D-entry it amends or contradicts.'],
  ['failure-first', 'What pathologies of OURS (P1-P5) have peers solved, and what pathologies of THEIRS do we avoid by design; be explicit about what we do worse.'],
  ['cost-solo-first', 'What survives on one box, one human, open weights, with frontier models as falsifiers only (D-061): rank mechanisms by feasibility at this scale; reject what needs a lab.'],
]

const synthPrompt = (angle, brief) => `You are workflow:${WF}/synth:${angle}. Today is ${args.today}.
${args.forbidden}

THIS APPARATUS: ${args.brief}
Its file map: ${args.file_map}
Existing critique to EXTEND (not re-derive): the May 2026 adversarial memo at notes/research/2026-05-19-adversarial-review/1_adversarial_review_memo.md (read it).
Governance you must respect or explicitly argue to supersede: D-011 (no auto-paper / no LLM-as-reviewer for novelty), D-059 (evidence ladder), D-060 (idea ledger + MAP-Elites; LLM judge gated behind calibration), D-061 (frontier = falsifiers only), D-062 (task packets + entrenchment tiers), D-063 (always-on), D-076/D-077 (redteam calibration results), ARCHITECTURE.md §8 exclusions (no RSI, no tree search, no same-model novelty grading), inviolate rule 8 (bounded change).

VERIFIED PROFILES (unverified fields are tagged; NEVER cite a struck citation; treat [UNVERIFIED] fields as unknown):
${PROFILES_TEXT}

ANGLE "${angle}": ${brief}
Produce:
- table_rows: one string per system, EXACTLY these " || "-separated fields: system || generator/critic split || novelty method || evidence/verification || memory || human role || topic/drift control || cost/hardware || THIS apparatus better at || THIS apparatus worse at || [c-refs used]
- mechanisms: <= 12 strings, EXACTLY: M<k> || mechanism (one line) || source systems [c-refs] || target file/step HERE (must exist — run ls) || amends D-xxx | contradicts D-xxx | new || adopt|reject|defer || pathology it addresses (P1-P5 or none) || one-line risk
- positioning: 300-600 words on where this apparatus sits relative to the field (use the research_program_v2 framing: solo researcher, one box, skeptical literature given equal weight, apparatus-as-contribution), honest about what we do worse.
- doc_markdown: a full draft of docs/related_work_2026-09.md: title, method note, the comparison table (markdown), positioning, mechanisms section (one subsection per mechanism with the file it touches and the decision it amends), "what we do worse", "what no peer solves", references list (verified citations only, url + date).
- excluded_unverified: the claims you left out because they were unverified.`

const judgePrompt = (attempts, j) => `You are workflow:${WF}/judge:${j}. Today is ${args.today}.
${args.forbidden}
Score each synthesis attempt 0-100 on: (1) every table cell traceable to a verified citation; (2) every mechanism names a REAL file/step here — run \`ls\`/\`grep\` in /home/decross1/projects/a_bgt_rsi for each target and penalize phantoms; (3) honesty about what this apparatus does worse; (4) respects ARCHITECTURE §8 / D-011 / D-061 unless it explicitly argues to supersede with evidence; (5) each of the five pathologies P1-P5 is mapped to a peer solution or an explicit "no peer solves this"; (6) prose quality for a research audience. Name factual errors with the row/mechanism id. graft_from_others: the specific rows/mechanisms from the OTHER attempts worth lifting into the winner.
Score ONE attempt per call — this call is for attempt "${attempts.name}":
${attempts.text}
Other attempts for graft comparison (summaries):
${attempts.others}`

const mergePrompt = (winner, judges, all) => `You are workflow:${WF}/merge. Today is ${args.today}.
${args.forbidden}
Build the FINAL docs/related_work_2026-09.md body from the winning attempt plus the grafts the judges named, fixing every factual error they listed. Keep only verified citations. Output the same SYNTH fields; mechanisms <= 12 with the exact " || " format; doc_markdown complete and self-contained; positioning 300-600 words. Add a short "Verification tally" placeholder section the primary will fill, and a "Struck claims" appendix listing excluded_unverified.
WINNER (${winner.angle}):
${winner.doc_markdown}
WINNER mechanisms: ${winner.mechanisms.join('\n')}
JUDGE NOTES: ${judges.map(j => `[${j.attempt}: ${j.score_0_100}] strengths: ${j.strengths} | weaknesses: ${j.weaknesses} | grafts: ${(j.graft_from_others || []).join('; ')} | errors: ${(j.factual_errors || []).join('; ')}`).join('\n')}
OTHER ATTEMPTS' mechanisms and table rows (for grafting):
${all.filter(a => a.angle !== winner.angle).map(a => `-- ${a.angle} --\n${a.mechanisms.join('\n')}\n${a.table_rows.join('\n')}`).join('\n')}`

const DRAFT_TEMPLATE = `## DRAFT-D-0NN — <title>
**Status:** DRAFT — not appended to DECISIONS.md; owner ratifies, edits, or strikes.
**Date.** ${args.today} (drafted by workflow related-work-2026-09; source: docs/related_work_2026-09.md §M<k>).
**Context.** <the measured pathology here + what the peer system does, with [c-refs]>
**Decision.** <adopt X at <file:symbol / loop step> | explicitly reject X because … | defer until …>
**Alternatives.** <>=2, incl. "do nothing">
**Rationale.** <why, tied to research_program_v2 (solo / one-box / skeptical-equal-weight) and to the measured numbers>
**Reversibility.** <env flag / module constant / overlay; what removes it>
**Supersedes / amends.** <D-xxx or "none"; if it contradicts D-011 / D-061 / ARCHITECTURE §8 say so explicitly>
**Touches.** <files; entrenchment tier per D-062 (Tier S needs owner ratification)>`

const draftPrompt = (m, n) => `You are workflow:${WF}/draft:${n}. Today is ${args.today}.
${args.forbidden}
Write ONE draft decision entry for this mechanism, in EXACTLY this template (fill every field; DRAFT-D-0${n}):
${DRAFT_TEMPLATE}
MECHANISM: ${m}
THIS APPARATUS: ${args.brief}
File map: ${args.file_map}
Before writing: \`ls\` every file you name; \`grep -n '^## D-' /home/decross1/projects/a_bgt_rsi/DECISIONS.md\` and read the D-entries you cite (sed -n) so "amends/contradicts" is accurate. Cite only [c-refs] that appear in the verified profiles below (by system + citation id).
VERIFIED PROFILES (abbreviated): ${PROFILES_TEXT.slice(0, 60000)}
Return draft_id="DRAFT-D-0${n}", stance, markdown (the full entry), touches (file:symbol), amends (D-xxx), contradicts (D-xxx or ARCHITECTURE §8 bullet), evidence_refs (system:cN).`

const govPrompt = (d) => `You are workflow:${WF}/gov-refute:${d.draft_id}. Today is ${args.today}.
${args.forbidden}
Try to REFUTE this draft decision on GOVERNANCE grounds. Open /home/decross1/projects/a_bgt_rsi/DECISIONS.md and ARCHITECTURE.md and confirm every D-entry the draft cites says what the draft claims (decision_refs_accurate). Check the draft does not quietly cross D-011 (auto-paper / LLM-as-reviewer for novelty), D-061 (frontier never generates, never writes loop_memory or the brain), ARCHITECTURE §8 (no RSI, no tree search, no same-model novelty grading, no auto-publish without the Step-8 gate), or inviolate rule 8 (bounded change) — list violations. Check every file in touches exists (ls). Check format_ok against the seven-field template. refuted=true if any violation is real, a cited D-entry is misdescribed, or a touched file is a phantom. Default to refuted if uncertain.
DRAFT:
${d.markdown}
touches: ${d.touches.join(', ')} | amends: ${d.amends.join(', ')} | contradicts: ${d.contradicts.join(', ')}`

const criticPrompt = (doc, mechanisms, drafts) => `You are workflow:${WF}/critic. Today is ${args.today}.
${args.forbidden}
Completeness critic for docs/related_work_2026-09.md. Owner-named systems that MUST be present with a fetched primary URL: AI co-scientist (Google/DeepMind), Kosmos, XScientist / "X-scientist", Sakana AI Scientist v1 and v2. Also expected: Coscientist, Virtual Lab, FutureHouse Robin/PaperQA2, Agent Laboratory, AlphaEvolve/FunSearch, DeepScientist, InternAgent/NovelSeek, CodeScientist, Denario, Curie, MLR-Bench/AstaBench/Agents4Science, skeptical literature (Beel et al., LLM-as-reviewer), 2026 systems (Agon, ScientistOne, ForeSci, SCP, Jr. AI Scientist, aiXiv, Mira/ERA).
Check: (1) missing_systems; (2) unverified_load_bearing_claims — table cells or mechanism justifications that lean on an [UNVERIFIED] field or a struck citation; (3) mechanisms_without_file_target — run ls for each target; (4) pathologies_unaddressed — each of P1 topic drift, P2 L0 pile-up / undecidable critic, P3 redteam kills nothing, P4 163 unanswered bubble-ups, P5 frontier reviewers dark/fail-open must map to >= 1 peer solution or an explicit "no peer solves this"; (5) next_round: <= 5 concrete targets (name || url) for a bounded deep-read round. verdict = complete only if (1)-(4) are empty.
DOC:
${doc}
MECHANISMS: ${mechanisms.join('\n')}
DRAFTS: ${drafts.map(d => `${d.draft_id} ${d.stance} ${d.title} [gov: ${d.gov ? (d.gov.refuted ? 'REFUTED — ' + d.gov.reason.slice(0, 200) : 'stands') : 'n/a'}]`).join('\n')}`

phase('Synthesize')
const attempts = (await parallel(ANGLES.map(([angle, brief]) => () => agent(synthPrompt(angle, brief), { schema: SYNTH, phase: 'Synthesize', label: `synth:${angle}`, effort: 'max' })))).filter(Boolean)
attempts.forEach(a => logRow(`rw_synth_${a.angle}`, `synth:${a.angle}`, a))
if (!attempts.length) return { error: 'no synthesis attempts survived', runlog_rows: RUNLOG }

phase('Judge')
const judgeJobs = []
attempts.forEach(a => [1, 2, 3].forEach(j => judgeJobs.push({ a, j })))
const judgeRes = (await parallel(judgeJobs.map(({ a, j }) => () => agent(judgePrompt({ name: a.angle, text: a.doc_markdown + '\nMECHANISMS:\n' + a.mechanisms.join('\n'), others: attempts.filter(x => x.angle !== a.angle).map(x => `[${x.angle}] ${x.positioning.slice(0, 800)}\n${x.mechanisms.join('\n')}`).join('\n\n') }, j), { schema: JUDGE, phase: 'Judge', label: `judge:${j}:${a.angle}`, effort: 'high' })))).filter(Boolean)
judgeRes.forEach(r => logRow(`rw_judge_${r.attempt}`, `judge:${r.attempt}`, r))
const scores = {}
for (const r of judgeRes) { scores[r.attempt] = (scores[r.attempt] || []).concat(r.score_0_100) }
const mean = (xs) => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
const winner = attempts.map(a => ({ a, s: mean(scores[a.angle] || []) })).sort((x, y) => y.s - x.s)[0].a
log(`judge scores: ${attempts.map(a => `${a.angle}=${mean(scores[a.angle] || []).toFixed(0)}`).join(', ')} -> winner ${winner.angle}`)
const merged = await agent(mergePrompt(winner, judgeRes, attempts), { schema: SYNTH, phase: 'Judge', label: 'merge', effort: 'max' })
logRow('rw_merge', 'merge', merged)
const finalDoc = merged || winner

phase('Draft')
const mechanisms = (finalDoc.mechanisms || []).slice(0, 12)
const drafts = await pipeline(mechanisms,
  async (m, _, i) => { const d = await agent(draftPrompt(m, 78 + i), { schema: DRAFT, phase: 'Draft', label: `draft:${78 + i}`, effort: 'high' }); logRow(`rw_draft_${78 + i}`, `draft:${78 + i}`, d); return d },
  async (d) => { if (!d) return null; const g = await agent(govPrompt(d), { schema: GOV, phase: 'Draft', label: `gov:${d.draft_id}`, effort: 'high' }); logRow(`rw_gov_${d.draft_id}`, `gov-refute:${d.draft_id}`, g); return { ...d, gov: g } })
const draftsOk = drafts.filter(Boolean)
log(`drafts: ${draftsOk.length} written, ${draftsOk.filter(d => d.gov && d.gov.refuted).length} refuted on governance grounds`)

phase('Critic')
const critic = await agent(criticPrompt(finalDoc.doc_markdown, mechanisms, draftsOk), { schema: CRITIC, phase: 'Critic', label: 'critic', effort: 'max' })
logRow('rw_critic', 'critic', critic)

return {
  doc_markdown: finalDoc.doc_markdown, table_rows: finalDoc.table_rows, mechanisms, positioning: finalDoc.positioning,
  excluded_unverified: finalDoc.excluded_unverified, winner: winner.angle, judge_scores: scores,
  attempts: attempts.map(a => ({ angle: a.angle, mechanisms: a.mechanisms, positioning: a.positioning })),
  drafts: draftsOk, critic, runlog_rows: RUNLOG,
}
