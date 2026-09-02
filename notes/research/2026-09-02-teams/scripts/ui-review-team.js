export const meta = {
  name: 'ui-review-team',
  description: 'Team 4 WF1: page-by-page UI/UX review — sweep by 3 lenses, 3 lens-refuters per finding, per-surface synthesis, flows, comparables, color science, work-order assembly',
  phases: [
    { title: 'Sweep', detail: '13 surfaces x 3 lenses + 3 flow tracers + 13 comparables + 2 color science + 1 docs' },
    { title: 'Verify', detail: '3 perspective-diverse refuters per finding, majority rule' },
    { title: 'Synthesize', detail: 'per-surface scorecards + change lists; token plan; assembler; critic; cite check' },
  ],
}

const WF = 'ui-review-2026-09'
const RUNLOG = []
const PRE = args.preamble
const SHOTS = args.shots
const SURFACES = args.surfaces
const PER_SURFACE_CAP = 8
const PER_FLOW_CAP = 6

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
  surface: { type: 'string' }, lens: { type: 'string' }, ethos_statement: { type: 'string' },
  score_a: { type: 'number' }, score_b: { type: 'number' }, score_c: { type: 'number' }, score_d: { type: 'number' },
  score_e: { type: 'number' }, score_f: { type: 'number' }, score_g: { type: 'number' }, score_h: { type: 'number' },
  findings_tsv: { type: 'string' }, findings_count: { type: 'integer' }, screenshots_used: { type: 'string' }, notes: { type: 'string' },
}, ['surface', 'lens', 'findings_tsv', 'findings_count', 'score_a', 'score_b', 'score_c', 'score_d', 'score_e', 'score_f', 'score_g', 'score_h'])
const VERDICT = withLog({
  refuted: { type: 'boolean' }, lens: { type: 'string' }, reason: { type: 'string' },
  corrected_cite: { type: 'string' }, confidence: { type: 'number' },
}, ['refuted', 'lens', 'reason'])
const CARDS = withLog({
  product: { type: 'string' }, urls_checked: { type: 'string' }, cards_tsv: { type: 'string' }, cards_count: { type: 'integer' },
}, ['product', 'urls_checked', 'cards_tsv', 'cards_count'])
const SYNTH = withLog({
  surface: { type: 'string' }, ethos_statement: { type: 'string' }, composite: { type: 'number' },
  scorecard_row: { type: 'string' }, ranked_findings_md: { type: 'string' }, change_list_md: { type: 'string' },
  acceptance_md: { type: 'string' }, screens_md: { type: 'string' }, proposals_for_ui_plan_md: { type: 'string' },
}, ['surface', 'composite', 'scorecard_row', 'ranked_findings_md', 'change_list_md', 'acceptance_md'])
const MD = withLog({ markdown: { type: 'string' }, issues: { type: 'string' } }, ['markdown'])

const LENSES = [
  { id: 'ethos-flow', rubric: 'a,b,e', brief: 'Ethos (does every element serve the stated purpose for the stated reader in the stated moment?), hierarchy vs the F-pattern / owe-first thesis (what is read first at 1440x900, is the hero the biggest and highest-contrast element, how many px until the first owed item), and the owner flows this page touches (count clicks/pages/scroll-px, find dead ends and hidden entries).' },
  { id: 'pattern-color-a11y', rubric: 'c,d,h', brief: 'Pattern consistency (R0 primitives vs rolled-own chrome, which token system each file uses, raw Tailwind color utilities on this page — grep them and count), color theory (palette coherence in oklch, semantic discipline: does any hue do two jobs on this page — status vs identity vs verdict vs accent; contrast using the table plus any pair you compute; colorblind safety of the encodings and whether text always accompanies color), and a11y (roles/landmarks/headings, focus order, aria-current, keyboard reach).' },
  { id: 'states-jargon', rubric: 'f,g', brief: 'Jargon legibility (quote every term a non-author meets: rung/L0-L5, D-059/D-052 citations, undecidable, bubble, spawn, graveyard/kill code/unrung, raw iter-/sf-/cl- ids, endpoint paths as copy) with a tooltip/glossary strategy, and states (loading, empty, error/skew, stale via pollhub vs raw setInterval, motion incl. reduced-motion) and copy honesty.' },
]

const parseTsv = (s) => (s || '').split('\n').map(l => l.split('\t')).filter(c => c.length >= 10)
  .map(c => ({ sev: c[0].trim(), rubric: c[1].trim(), title: c[2].trim(), cite: c[3].trim(), sel: c[4].trim(), shot: c[5].trim(), evidence: c[6].trim(), fix: c[7].trim(), files: c[8].trim(), bounded: c[9].trim() }))
const fkey = f => `${f.cite}|${f.title.toLowerCase().slice(0, 60)}`
const sevRank = { high: 0, med: 1, medium: 1, low: 2 }
const REFUTE = (ethos) => [
  ['reality', 'Open the cited file at d1c4a6e (`git show d1c4a6e:<path> | sed -n \'<line>p\'`) and Read the screenshot. Refute if the cite is wrong, the element does not render, or the image contradicts the claim. If you find the real line, give corrected_cite as path:line.'],
  ['materiality', `Given the ethos "${ethos}" and the owner's three acts (clear a gate verdict, answer a bubble-up, rule on an agenda item), refute if fixing this would not change what the owner reads or does on this surface.`],
  ['boundedness', 'Refute if the proposed fix requires backend/spine changes, a new dependency, or writes outside ui/ + ui_plan.md — unless the finding is explicitly tagged [needs primary seam] (then it stands but is routed to the proposals block).'],
]

const sweepStage = async (s) => {
  const outs = (await parallel(LENSES.map(L => () => agent(
    `${PRE}\nSURFACE ${s.id} (${s.route}). ETHOS: ${s.ethos}\nFILES (verify with ls; a name may differ slightly — find it): ${s.files.join(', ')}\nSCREENSHOTS: ${s.shots.map(x => SHOTS + '/' + x).join(', ')}\nYou are workflow:${WF}/sweep:${s.id}/${L.id}. LENS ${L.id} (rubric dims ${L.rubric}): ${L.brief}\nScore ONLY your rubric dims 0-4 (0 = absent/contradicted, 2 = partially honored, 4 = fully honored with evidence); set the other dims to -1. Return 6-14 findings as TSV lines with EXACTLY 10 tab-separated fields:\nseverity(high|med|low)\trubric(a..h)\ttitle\tfile:line\tselector-or-dash\tscreenshot-path-or-dash\tevidence\tproposed_fix\tfix_files\tbounded(yes|no)\nEvery file:line verified with sed -n before returning. findings_count must equal the number of TSV lines.`,
    { schema: FINDINGS, label: `sweep ${s.id}/${L.id}`, phase: 'Sweep', effort: 'high' })))).filter(Boolean)
  outs.forEach(o => logRow(`ui_sweep_${s.id}_${o.lens}`, `sweep:${s.id}/${o.lens}`, o))
  const seen = new Set(), findings = []
  for (const o of outs) for (const f of parseTsv(o.findings_tsv)) { const k = fkey(f); if (!seen.has(k)) { seen.add(k); findings.push({ ...f, lens: o.lens }) } }
  findings.sort((a, b) => (sevRank[a.sev] ?? 3) - (sevRank[b.sev] ?? 3))
  const cap = s.id.startsWith('flow-') ? PER_FLOW_CAP : PER_SURFACE_CAP
  if (findings.length > cap) log(`${s.id}: ${findings.length} findings, verifying top ${cap} by severity (dropped ${findings.length - cap}, kept in raw)`)
  return { s, outs, findings: findings.slice(0, cap), dropped: findings.slice(cap) }
}

const verifyStage = async (r) => {
  if (!r) return null
  const verified = await parallel(r.findings.map((f, i) => () =>
    parallel(REFUTE(r.s.ethos).map(([lens, brief]) => () => agent(
      `${PRE}\nSURFACE ${r.s.id} (${r.s.route}). FINDING ${i + 1}: ${f.title}\nCITE ${f.cite} · selector ${f.sel} · screenshot ${f.shot}\nEVIDENCE: ${f.evidence}\nPROPOSED FIX: ${f.fix} (files: ${f.files}; bounded=${f.bounded})\nYou are workflow:${WF}/refute:${r.s.id}#${i + 1}/${lens}. ${brief}\nTry hard to REFUTE. Default refuted=true if uncertain. Give a one-paragraph reason with the evidence you checked.`,
      { schema: VERDICT, label: `refute ${r.s.id}#${i + 1}/${lens}`, phase: 'Verify', effort: 'medium' })))
      .then(vs => {
        const ok = vs.filter(Boolean)
        ok.forEach(v => logRow(`ui_refute_${r.s.id}_${i + 1}_${v.lens}`, `refute:${r.s.id}#${i + 1}/${v.lens}`, v))
        const cite = (ok.find(v => v.corrected_cite && v.corrected_cite.includes(':')) || {}).corrected_cite
        return { ...f, id: `${r.s.id}-${i + 1}`, cite: cite || f.cite, votes: ok.map(v => `${v.lens}:${v.refuted ? 'refuted' : 'stands'}`).join(' '), survives: ok.filter(v => !v.refuted).length >= 2 && ok.length >= 2 }
      })))
  return { ...r, verified: verified.filter(Boolean) }
}

const synthStage = async (r) => {
  if (!r) return null
  const kept = r.verified.filter(v => v.survives), killed = r.verified.filter(v => !v.survives)
  log(`${r.s.id}: ${kept.length} verified / ${killed.length} refuted`)
  const scores = r.outs.map(o => ({ lens: o.lens, a: o.score_a, b: o.score_b, c: o.score_c, d: o.score_d, e: o.score_e, f: o.score_f, g: o.score_g, h: o.score_h }))
  const synth = await agent(
    `${PRE}\nYou are workflow:${WF}/synth:${r.s.id}. SURFACE ${r.s.id} (${r.s.route}). ETHOS: ${r.s.ethos}. On an owner flow: ${r.s.onFlow ? 'yes' : 'no'}.\nLENS SCORES (-1 = not scored by that lens): ${JSON.stringify(scores)}\nVERIFIED FINDINGS (JSON): ${JSON.stringify(kept)}\nREFUTED (exclude; mention only if a pattern): ${JSON.stringify(killed.map(k => k.title))}\nProduce this surface's work-order section: ethos_statement (1-2 sentences); composite = 2a+2b+c+d+3e+f+g+h using each dim's max over lenses that scored it (if not on an owner flow, omit e and renormalize to /48); scorecard_row as one markdown table row '| surface | a | b | c | d | e | f | g | h | composite |'; ranked_findings_md (id · severity · title · file:line · screenshot · votes); change_list_md as checkbox lines with file paths (tag [needs primary seam] where a fix leaves ui/ + ui_plan.md); acceptance_md naming existing vitest suites (run \`ls ui/frontend/tests\`) plus new pins; screens_md listing the screenshot paths used; proposals_for_ui_plan_md.`,
    { schema: SYNTH, label: `synth ${r.s.id}`, phase: 'Synthesize', effort: 'high' })
  logRow(`ui_synth_${r.s.id}`, `synth:${r.s.id}`, synth)
  return { surface: r.s.id, synth, kept, killed, dropped: r.dropped }
}

const pagesLane = () => pipeline(SURFACES, sweepStage, verifyStage, synthStage)

const flowsLane = () => pipeline(args.flows,
  async (fl) => {
    const o = await agent(`${PRE}\nYou are workflow:${WF}/flow:${fl.id}. TRACE the owner act "${fl.id}" from / end-to-end: ${fl.brief}\nUse the screenshots and the source (Pulse.tsx, OweCard.tsx, DossierIndex.tsx, DossierReader.tsx, BubbleAckForm.tsx, ModelIO.tsx, FrontierReviews.tsx, App.tsx, design/CommandPalette.tsx). Count clicks, pages, scroll-px (from the _full.png heights), keyboard reach via ⌘K, dead ends, and where the act is hidden. Put the count table in notes. Score dims a,b,e (others -1). Return 4-8 findings as TSV lines with EXACTLY 10 tab-separated fields: severity\trubric\ttitle\tfile:line\tselector-or-dash\tscreenshot-path-or-dash\tevidence\tproposed_fix\tfix_files\tbounded.`, { schema: FINDINGS, label: `flow ${fl.id}`, phase: 'Sweep', effort: 'high' })
    logRow(`ui_flow_${fl.id}`, `flow:${fl.id}`, o)
    if (!o) return null
    const findings = parseTsv(o.findings_tsv).map(f => ({ ...f, lens: 'flow' })).slice(0, PER_FLOW_CAP)
    return { s: { id: `flow-${fl.id}`, route: '/', ethos: 'the owner completes this act in the fewest honest steps', onFlow: true }, outs: [o], findings, dropped: [] }
  },
  verifyStage, synthStage)

const cardsLane = () => pipeline(args.products, async (p) => {
  const c = await agent(`${PRE}\nYou are workflow:${WF}/comparable:${p.name}. PRODUCT: ${p.name}. Our matching surfaces: ${p.matches}. Use WebSearch + WebFetch on official docs/blog/help/design-system pages (record every URL with its HTTP status in urls_checked as 'status url' lines). Return 3-6 pattern cards as TSV lines with EXACTLY 8 tab-separated fields: pattern_name\tour_page\twhat_it_does\twhy_it_works\tborrow_as(concrete change + our file)\tevidence_url\teffort(S|M|L)\trisk. No essays; no invented screenshots; every evidence_url must have been fetched by you.`, { schema: CARDS, label: `comparable ${p.name}`, phase: 'Sweep', effort: 'medium' })
  logRow(`ui_comparable_${p.name.replace(/[^a-z0-9]+/gi, '_').toLowerCase()}`, `comparable:${p.name}`, c)
  return c
})

const colorLane = () => parallel([
  () => agent(`${PRE}\nYou are workflow:${WF}/color:contrast. Enumerate EVERY text/background color pair actually used in ui/frontend/src (grep Tailwind text-*/bg-* on the same element and var(--…) pairs; include the chips.tsx tone maps and LoopAlertBanner), convert oklch->sRGB with the OKLab matrices in python3 (Tailwind 4 zinc/emerald/amber/red/sky/rose values are oklch in node_modules/tailwindcss/theme.css — read them), compute WCAG ratios, and return the full table as markdown plus a ranked list of pairs < 4.5:1 with file:line for each use.`, { schema: MD, label: 'contrast table', phase: 'Sweep', effort: 'high' }).then(r => { logRow('ui_color_contrast', 'color:contrast', r); return r }),
  () => agent(`${PRE}\nYou are workflow:${WF}/color:colorblind. Simulate deuteranopia/protanopia/tritanopia (Machado 2009 matrices, python3) for the status set (--status-ok/warn/bad/info/idle in design/tokens.css), the verdict/novelty/gate chip tones in components/chips.tsx, RungGlyph (design/RungGlyph.tsx) and the voice hues (channel.css:20-24). Report ΔE2000 between every pair under each simulation, flag pairs < 15, and check whether text accompanies each color use (cite lines). Propose the minimal remap that keeps the R0 rules.`, { schema: MD, label: 'colorblind sim', phase: 'Sweep', effort: 'high' }).then(r => { logRow('ui_color_colorblind', 'color:colorblind', r); return r }),
  () => agent(`${PRE}\nYou are workflow:${WF}/docs:drift. Verify each docs-drift claim with exact lines and propose replacement text: ui/README.md cites ui/.venv-ui (absent; the backend runs under .venv-chroma); ui/backend/README.md lists phantom endpoints /api/chain/{task_id} and /api/recent_tasks vs the real routes (grep @app./@router. in ui/backend/*.py); ui/frontend/README.md lists dead panels and /chain/:taskId; ui_plan.md:8 §LOOP_V0 'active section' is dead (current entries near line 4054+); OweStrip.tsx unmounted but tested (tests/test_owe_strip.tsx); ui/frontend/dist stale (git ls-files ui/frontend/dist; mtime); index.html <title> vs the wordmark; index.css body font-family duplicate of design/tokens.css. Return a markdown checklist with file:line and replacement text.`, { schema: MD, label: 'docs drift', phase: 'Sweep', effort: 'low' }).then(r => { logRow('ui_docs_drift', 'docs:drift', r); return r }),
])

const [pages, flows, cards, color] = await parallel([pagesLane, flowsLane, cardsLane, colorLane])
const pagesOk = (pages || []).filter(Boolean)
const flowsOk = (flows || []).filter(Boolean)
const cardsOk = (cards || []).filter(Boolean)
const colorOk = color || []
log(`lanes done: pages ${pagesOk.length}/${SURFACES.length}, flows ${flowsOk.length}/${args.flows.length}, cards ${cardsOk.length}/${args.products.length}, color ${colorOk.filter(Boolean).length}/3`)

phase('Synthesize')
const ranked = pagesOk.map(p => ({ id: p.surface, composite: p.synth ? p.synth.composite : 99 })).sort((a, b) => a.composite - b.composite)
const weakest = args.weakest_override || ranked.slice(0, 3).map(r => r.id)
log(`weakest by composite: ${ranked.slice(0, 6).map(r => `${r.id}=${r.composite}`).join(', ')} -> mockups for ${weakest.join(', ')}`)

const tokensPage = pagesOk.find(p => p.surface === 'tokens')
const tokenPlan = await agent(`${PRE}\nYou are workflow:${WF}/synth:token-plan. From the contrast table, the colorblind report, and the tokens-surface synthesis, write the CONSOLIDATED palette proposal for the token-sheet artboard: every R0 token with oklch + hex + contrast vs --bg and --surface-1; the mapping table Tailwind utility -> token (text-zinc-500/600/700, bg-*-950 chip families -> --status-*-bg, etc.); the legacy src/tokens.css retirement plan; what stays status-only; what the voice hues become. Markdown.\nCONTRAST: ${colorOk[0] ? colorOk[0].markdown : 'n/a'}\nCOLORBLIND: ${colorOk[1] ? colorOk[1].markdown : 'n/a'}\nTOKENS SYNTH: ${tokensPage && tokensPage.synth ? JSON.stringify(tokensPage.synth) : 'n/a'}`, { schema: MD, label: 'token consolidation', phase: 'Synthesize', effort: 'high' })
logRow('ui_token_plan', 'synth:token-plan', tokenPlan)

const assembled = await agent(`${PRE}\nYou are workflow:${WF}/synth:assembler. Assemble the work order markdown EXACTLY in this template:\n${args.workorder_template}\nInputs — page syntheses: ${JSON.stringify(pagesOk.map(p => p.synth))}\nFlow syntheses: ${JSON.stringify(flowsOk.map(f => f.synth))}\nPattern cards: ${JSON.stringify(cardsOk.map(c => ({ product: c.product, cards_tsv: c.cards_tsv })))}\nToken plan: ${tokenPlan ? tokenPlan.markdown : 'n/a'}\nDocs drift: ${colorOk[2] ? colorOk[2].markdown : 'n/a'}\nWeakest three (mockups): ${weakest.join(', ')}.\nKeep every file:line and screenshot path verbatim. UI-session scope only; route anything else to the [needs primary seam] block. The scorecard table is sorted weakest first.`, { schema: MD, label: 'work-order assembler', phase: 'Synthesize', effort: 'high' })
logRow('ui_assembler', 'synth:assembler', assembled)

const [critic, cites] = await parallel([
  () => agent(`${PRE}\nYou are workflow:${WF}/critic:completeness. Completeness critic: what is missing from this work order — a rubric dimension not scored for some surface, a surface with zero verified findings, an owner act without a before/after count, a screenshot never referenced, a comparable with no borrowed pattern, a contrast failure not in any change list, a jargon term without a strategy? Return the gap list as markdown (specific, with what to add).\n${assembled ? assembled.markdown : ''}`, { schema: MD, label: 'completeness critic', phase: 'Synthesize', effort: 'high' }).then(r => { logRow('ui_critic', 'critic:completeness', r); return r }),
  () => agent(`${PRE}\nYou are workflow:${WF}/critic:cites. Citation verifier: for EVERY path:line in the markdown run \`git show d1c4a6e:<path> | sed -n '<line>p'\` and confirm the quoted element is on that line (±0); for every URL run \`curl -sI --max-time 10 <url> | head -1\`; for every screenshot path run \`ls -l\`. Return a markdown table of failures with corrections (and the totals checked).\n${assembled ? assembled.markdown : ''}`, { schema: MD, label: 'cite verifier', phase: 'Synthesize', effort: 'medium' }).then(r => { logRow('ui_cites', 'critic:cites', r); return r }),
])

return {
  ranked, weakest,
  workorder_md: assembled ? assembled.markdown : null,
  critic: critic ? critic.markdown : null,
  cite_check: cites ? cites.markdown : null,
  token_plan_md: tokenPlan ? tokenPlan.markdown : null,
  pages: pagesOk.map(p => ({ surface: p.surface, synth: p.synth, kept: p.kept, killed: p.killed.map(k => ({ id: k.id, title: k.title, votes: k.votes })), dropped: p.dropped.length })),
  flows: flowsOk.map(f => ({ surface: f.surface, synth: f.synth, kept: f.kept, killed: f.killed.map(k => ({ id: k.id, title: k.title, votes: k.votes })) })),
  cards: cardsOk, color: colorOk,
  runlog_rows: RUNLOG,
}