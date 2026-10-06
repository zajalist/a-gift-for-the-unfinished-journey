#!/usr/bin/env node
// build_settings_ui: builds a designer tree written by gen_settings_specs.mjs
// into its Widget Blueprint through the Hayba plugin's TCP port.
//
//   node Tools/GameFlow/build_settings_ui.mjs <tree.json> [--port N] [--slots-only] [--clear]
//
// --clear removes every widget under the root canvas first (a full rebuild of
// the designer tree; the graphs are rebuilt separately with bpgraph.mjs).
// Steps (on an existing, empty Widget Blueprint): ui_build_tree,
// canvas slots (anchors/position/size), the veil brush, mark the graph's
// widgets as variables, compile and save. Hold the editor gate while it runs.
// Prints one line per step; exits 1 on the first failed step, 3 (before
// connecting) when the target .uasset is read-only on disk: a save of a
// read-only package crashes the editor (bpgraph.mjs, "Limits found live").

import net from 'node:net';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { readOnlyPackages, sharingLockedPackages } from './bpgraph.mjs';

const args = process.argv.slice(2);
const file = args.find((a) => !a.startsWith('--'));
if (!file) {
  console.error('usage: build_settings_ui.mjs <tree.json> [--port N]');
  process.exit(2);
}
const portArg = args.indexOf('--port');
const spec = JSON.parse(readFileSync(file, 'utf8'));
const path = spec.asset;
if (spec.parent_widget_name && args.includes('--clear')) {
  console.error('An additive parent_widget_name spec cannot be combined with --clear. Nothing was sent.');
  process.exit(2);
}

function discoverPort() {
  const dir = join(resolve('.'), 'Saved', 'HaybaMCP', 'instances');
  if (!existsSync(dir)) return undefined;
  const entries = readdirSync(dir).filter((n) => n.endsWith('.json')).map((n) => JSON.parse(readFileSync(join(dir, n), 'utf8')));
  entries.sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  return entries[0]?.port;
}
const port = portArg >= 0 ? Number(args[portArg + 1]) : discoverPort();

for (const { asset, file: onDisk } of readOnlyPackages([path], resolve('.'))) {
  console.error(`READ-ONLY ${asset} (${onDisk}): the final save would crash the editor, so nothing was sent.`);
  console.error("Make it writable first (git lfs lock <file>, the editor's Make Writable, or attrib -r), then rerun.");
  process.exit(3);
}
try {
  const locked = sharingLockedPackages([path], resolve('.'));
  if (locked.length) {
    for (const { asset, file: onDisk, reason } of locked) console.error(`IN USE ${asset} (${onDisk}, ${reason}): nothing was sent.`);
    process.exit(3);
  }
} catch (err) {
  console.error(`${err.message}; nothing was sent.`);
  process.exit(3);
}

let buffer = Buffer.alloc(0);
const pending = new Map();
let counter = 0;
const socket = net.createConnection({ host: '127.0.0.1', port });
await new Promise((ok, fail) => {
  socket.once('connect', ok);
  socket.once('error', fail);
});
socket.on('data', (chunk) => {
  buffer = Buffer.concat([buffer, chunk]);
  while (buffer.length >= 4) {
    const n = buffer.readUInt32BE(0);
    if (buffer.length < 4 + n) return;
    const msg = JSON.parse(buffer.subarray(4, 4 + n).toString('utf8'));
    buffer = buffer.subarray(4 + n);
    pending.get(msg.id)?.(msg);
    pending.delete(msg.id);
  }
});
function send(cmd, params) {
  const id = `ui_${process.pid}_${++counter}`;
  if (/^(?:\[REDACTED:|\[TRUNCATED:|<redacted)/i.test(process.env.HAYBA_LEASE ?? '')) {
    return Promise.resolve({ ok: false, error: 'HAYBA_LEASE contains a redaction marker; use the verified native same-owner route with this field omitted.' });
  }
  const envelope = { cmd, id, params };
  if (process.env.HAYBA_AGENT_ID) envelope.owner = process.env.HAYBA_AGENT_ID;
  if (process.env.HAYBA_LEASE) envelope.lease = process.env.HAYBA_LEASE;
  if (process.env.HAYBA_AUTH) envelope.auth = process.env.HAYBA_AUTH;
  const payload = Buffer.from(JSON.stringify(envelope), 'utf8');
  const header = Buffer.alloc(4);
  header.writeUInt32BE(payload.length, 0);
  return new Promise((done) => {
    const t = setTimeout(() => done({ ok: false, error: `${cmd}: timeout` }), 120_000);
    pending.set(id, (m) => {
      clearTimeout(t);
      done(m.lease_warning || m.data?.lease_warning
        ? { ok: false, error: `${cmd}: native lease warning; stop and inspect live owner/resources/expiry.` }
        : m);
    });
    socket.write(Buffer.concat([header, payload]));
  });
}
function must(step, r) {
  const bad = !r.ok || r.data?.failed > 0 || (Array.isArray(r.data?.unknown_slot_props) && r.data.unknown_slot_props.length);
  console.log(`${bad ? 'FAIL' : 'ok  '} ${step}${bad ? `: ${r.error ?? JSON.stringify(r.data).slice(0, 600)}` : ''}`);
  if (bad) {
    socket.end();
    process.exit(1);
  }
  return r.data;
}

// The asset must exist with an empty root canvas (ui_create_widget); a rebuild
// removes the old top-level widgets first (ui_remove_element).
// Top-level canvas children get their slots afterwards (ui_build_tree takes
// box-slot keys only), so strip them here.
const tree = spec.parent_widget_name ? spec.tree : spec.tree.map((n) => {
  const { slot_props: _slot, ...rest } = n;
  return rest;
});
const slotsOnly = args.includes('--slots-only');
if (args.includes('--clear') && !slotsOnly) {
  // ui_query caps its match list, so a big tree lists only some of the root's children:
  // re-query until the root has none left (LANE3, 2026-09-28: 'Description' survived one pass).
  for (let pass = 0; pass < 10; pass++) {
    const q = must('query tree', await send('ui_query', { path, flatten: true }));
    const list = q.widgets ?? q.results ?? q.matches ?? [];
    const root = list.find((w) => !w.parent)?.name;
    const top = list.filter((w) => root && w.parent === root).map((w) => w.name);
    if (top.length === 0) break;
    for (const name of top) must(`remove ${name}`, await send('ui_mutate_tree', { widget_blueprint_path: path, operation: 'remove', widget_name: name }));
  }
}
if (!slotsOnly) must('build tree', await send('ui_build_tree', {
  widget_blueprint_path: path, tree,
  ...(spec.parent_widget_name ? { parent_widget_name: spec.parent_widget_name } : {}),
}));
for (const move of spec.moves ?? []) {
  must(`move ${move.widget_name}`, await send('ui_mutate_tree', {
    widget_blueprint_path: path, operation: 'move', widget_name: move.widget_name, index: move.index,
  }));
}

// The older specs (P3) relied on an implicit full-screen Veil and Scrim; the
// direction-A specs list every slot themselves.
const fullScreen = { anchors: [0, 0, 1, 1], position: [0, 0], size: [0, 0] };
const legacy = 'veil' in spec ? { Veil: { ...fullScreen, z_order: -2 }, Scrim: { ...fullScreen, z_order: -1 } } : {};
const slots = { ...legacy, ...spec.slots };
for (const [widget, slot] of Object.entries(slots)) {
  // The plugin takes anchors as anchors_min / anchors_max pairs.
  const { anchors, ...rest } = slot;
  const slotProps = anchors ? { anchors_min: anchors.slice(0, 2), anchors_max: anchors.slice(2), ...rest } : rest;
  must(`slot ${widget}`, await send('ui_set_widget_properties', { widget_blueprint_path: path, widget_name: widget, slot_props: slotProps }));
}
for (const [widget, properties] of Object.entries(spec.widget_properties ?? {})) {
  must(`properties ${widget}`, await send('ui_set_widget_properties', { widget_blueprint_path: path, widget_name: widget, properties }));
}
if (spec.veil) must('veil brush', await send('ui_set_widget_properties', {
  widget_blueprint_path: path,
  widget_name: 'Veil',
  properties: { Brush: { ResourceObject: spec.veil, DrawAs: 'Image' } },
}));
for (const v of spec.variables) {
  must(`variable ${v}`, await send('ui_set_variable', { widget_blueprint_path: path, widget_name: v, is_variable: true }));
}
must('compile', await send('ui_compile_widget', { widget_blueprint_path: path }));
must('save', await send('ui_save_widget', { widget_blueprint_path: path }));
socket.end();
