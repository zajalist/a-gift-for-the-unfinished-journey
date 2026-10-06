#!/usr/bin/env node
// verify_settings_asset: offline check that a built widget blueprint holds its graph spec's text.
//
//   node Tools/GameFlow/verify_settings_asset.mjs [spec.graph.json] [asset.uasset]
//   (defaults: specs/WBP_Saskarta_Settings.graph.json and its Content/ .uasset)
//
// A bpgraph build that is killed half-way still compiles clean (the Kismet compiler prunes the
// unwired nodes), so neither the compile nor the log shows it (2026-09-28: 26 Settings functions
// were empty). A wired graph keeps every pin default in the asset, so this scans the .uasset
// bytes for each string default of the spec (row descriptions, ReadSetting names, property and
// timer function names) and for each graph (function) name, as ANSI and as UTF-16LE (UE stores a
// string as UTF-16 when it has a non-ASCII character, e.g. an apostrophe ’). Exit 0 when all are
// present, 1 when some are missing (they are listed). It reads files only; no editor needed.

import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');
const specPath = process.argv[2] ?? join(HERE, 'specs', 'WBP_Saskarta_Settings.graph.json');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const assetPath = process.argv[3] ?? join(ROOT, 'Content', `${spec.asset.replace(/^\/Game\//, '')}.uasset`);
const bytes = readFileSync(assetPath);

// Pins whose literal is a meaningful, distinctive string.
const STRING_PINS = /\.(InText|Name|PropertyName|FunctionName|VariableName|Option|A|B)$/;
const expected = new Map(); // text -> where
for (const g of spec.graphs) {
  expected.set(g.graph, `graph ${g.graph}`);
  for (const [pin, value] of Object.entries(g.defaults ?? {})) {
    if (!STRING_PINS.test(pin)) continue;
    const v = String(value);
    // Skip numbers, booleans, enum literals and short tokens that would match by chance.
    if (v.length < 6 || /^-?[\d.]+$/.test(v) || v === 'true' || v === 'false') continue;
    if (!expected.has(v)) expected.set(v, `${g.graph} ${pin}`);
  }
}

const has = (text) => {
  const ascii = /^[\x00-\x7f]*$/.test(text);
  if (ascii && bytes.includes(Buffer.from(text, 'latin1'))) return true;
  return bytes.includes(Buffer.from(text, 'utf16le'));
};

const missing = [...expected].filter(([text]) => !has(text));
console.log(`${assetPath}\n  ${expected.size - missing.length} / ${expected.size} spec strings and graph names found`);
for (const [text, where] of missing) console.log(`  MISSING ${JSON.stringify(text.length > 70 ? `${text.slice(0, 67)}...` : text)}  (${where})`);
process.exit(missing.length ? 1 : 0);
