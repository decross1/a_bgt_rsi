import { chromium } from '/home/decross1/projects/ui_overhaul_gallery/tools/node_modules/playwright/index.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
const OUT = '/tmp/claude-1000/-home-decross1-projects-a-bgt-rsi/fb6a3b4d-c6c2-437e-8b34-f1160d6a5099/scratchpad/ui_shots';
const BASE = 'http://localhost:5173';
const IDS = JSON.parse(process.argv[2]);
const ROUTES = [
  ['pulse', '/', 'main, body'],
  ['ladder', '/ladder', 'svg'],
  ['dossier-index', '/dossier', 'main, body'],
  ['dossier-gate', `/dossier/${IDS.gate}`, 'main, body'],
  ['dossier-finding', `/dossier/${IDS.finding}`, 'main, body'],
  ['dossier-bubble', `/dossier/${IDS.bubble}`, 'main, body'],
  ['channel', '/channel', 'main, body'],
  ['cycles', '/cycles', 'main, body'],
  ['graph', '/graph', '.react-flow, main, body'],
  ['experiments', '/experiments', 'main, body'],
  ['experiment-detail', `/experiments/${IDS.exp}`, 'main, body'],
  ['model-io', '/model-io', 'table, main, body'],
  ['inspector', `/chain/req/${IDS.req}`, 'main, body'],
];
mkdirSync(OUT, { recursive: true });
let browser;
try { browser = await chromium.launch(); } catch (e) { browser = await chromium.launch({ args: ['--no-sandbox'] }); }
const report = {};
for (const [name, path, ready] of ROUTES) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('console', m => m.type() === 'error' && errors.push(m.text().slice(0, 300)));
  page.on('pageerror', e => errors.push('pageerror: ' + e.message.slice(0, 300)));
  try {
    await page.goto(BASE + path, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForSelector(ready, { timeout: 8000 }).catch(() => errors.push(`ready-selector timeout: ${ready}`));
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/${name}.png`, clip: { x: 0, y: 0, width: 1440, height: 900 } });
    await page.screenshot({ path: `${OUT}/${name}_full.png`, fullPage: true });
  } catch (e) { errors.push('nav: ' + e.message.slice(0, 300)); }
  report[name] = { url: BASE + path, errors };
  await page.close();
}
const states = [
  ['banner-red', '/', { level: 'red', reasons: ['loop_stalled'], updated_at: '2026-09-02T03:00:00Z' }],
  ['banner-stale', '/', { level: 'ok', reasons: [], updated_at: '2026-08-30T00:00:00Z' }],
];
for (const [name, path, alert] of states) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.route('**/api/loop_alert', r => r.fulfill({ json: alert }));
  try { await page.goto(BASE + path, { waitUntil: 'networkidle', timeout: 30000 }); await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/${name}.png`, clip: { x: 0, y: 0, width: 1440, height: 900 } }); } catch (e) { report[name] = { errors: [e.message.slice(0,200)] }; }
  await page.close();
}
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.route('**/api/human_todo', r => r.fulfill({ json: { items: [], counts: {} } }));
  try { await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 30000 }); await page.waitForTimeout(2500);
    await page.screenshot({ path: `${OUT}/owe-empty.png`, clip: { x: 0, y: 0, width: 1440, height: 900 } }); } catch (e) { report['owe-empty'] = { errors: [e.message.slice(0,200)] }; }
  await page.close();
}
{
  const p = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try { await p.goto(BASE + '/ladder', { waitUntil: 'networkidle', timeout: 30000 }); await p.waitForTimeout(2000);
    await p.click('summary:has-text("engine")').catch(() => {}); await p.waitForTimeout(400);
    await p.screenshot({ path: `${OUT}/nav-engine-open.png`, clip: { x: 0, y: 0, width: 1440, height: 400 } });
    await p.keyboard.press('Control+K'); await p.waitForTimeout(500);
    await p.screenshot({ path: `${OUT}/palette-open.png`, clip: { x: 0, y: 0, width: 1440, height: 900 } }); } catch (e) { report['interaction'] = { errors: [e.message.slice(0,200)] }; }
  await p.close();
}
await browser.close();
writeFileSync(`${OUT}/console-report.json`, JSON.stringify(report, null, 2));
console.log('done', Object.keys(report).length);
