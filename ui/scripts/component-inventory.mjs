#!/usr/bin/env node
// Conservative source reachability report; this script never deletes files.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const frontend = path.join(uiRoot, 'frontend');
const src = path.join(frontend, 'src');
const require = createRequire(path.join(frontend, 'package.json'));
const ts = require('typescript');
const extensions = ['.ts', '.tsx', '.js', '.jsx'];
const files = [];
function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(target);
    else if (entry.isFile() && extensions.some(ext => target.endsWith(ext))) files.push(target);
  }
}
walk(src);
const known = new Set(files);
const edges = new Map();
const importers = new Map();
const unresolved = [];
const dynamic = [];
const relative = target => path.relative(frontend, target);
function resolve(from, specifier) {
  const base = path.resolve(path.dirname(from), specifier);
  return [base, ...extensions.map(ext => base + ext),
    ...extensions.map(ext => path.join(base, 'index' + ext))].find(candidate => known.has(candidate));
}
for (const file of files) {
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
  const dependencies = new Set();
  function record(node) {
    if (!node || !ts.isStringLiteralLike(node)) return;
    const specifier = node.text;
    if (!specifier.startsWith('.')) return;
    const target = resolve(file, specifier);
    if (target) {
      dependencies.add(target);
      if (!importers.has(target)) importers.set(target, new Set());
      importers.get(target).add(file);
    } else if (!/\.(css|svg|png|jpe?g|webp|woff2?|json)(\?.*)?$/.test(specifier)) {
      unresolved.push({ source: relative(file), specifier });
    }
  }
  function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) record(node.moduleSpecifier);
    if (ts.isCallExpression(node)) {
      const expression = node.expression.getText(source);
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword || expression === 'require') {
        const argument = node.arguments[0];
        if (argument && ts.isStringLiteralLike(argument)) record(argument);
        else dynamic.push({ source: relative(file), kind: expression });
      } else if (expression.startsWith('import.meta.glob')) {
        dynamic.push({ source: relative(file), kind: expression });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  edges.set(file, dependencies);
}
const entry = path.join(src, 'main.tsx');
const reachable = new Set();
const pending = [entry];
while (pending.length) {
  const file = pending.pop();
  if (reachable.has(file)) continue;
  reachable.add(file);
  for (const next of edges.get(file) ?? []) pending.push(next);
}
const developmentOnly = file => /(?:\.test\.|\.spec\.|\.d\.ts$|\/test(?:s|ing)?\/|\/__tests__\/|\/fixtures\/)/.test(file);
console.log(JSON.stringify({
  schema: 'frontend-source-reachability/v1', entry: relative(entry),
  source_files: files.length, reachable_files: reachable.size,
  interpretation: 'Candidates require review. Type imports count as reachable; dynamic/aliased entrypoints can invalidate deletion conclusions.',
  unresolved_relative_imports: unresolved,
  dynamic_imports_requiring_review: dynamic,
  production_candidates: files.filter(file => !reachable.has(file) && !developmentOnly(file)).sort().map(file => ({
    path: relative(file), importers: [...(importers.get(file) ?? [])].map(relative).sort(),
  })),
}, null, 2));
