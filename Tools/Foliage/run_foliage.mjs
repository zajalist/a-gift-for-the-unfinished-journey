#!/usr/bin/env node
// Runner for the Task V4 foliage scripts, over Hayba's raw TCP port (python_run).
//
//   node Tools/Foliage/run_foliage.mjs convert <job ...|all>   convert_to_static.py per job,
//        called repeatedly (one bounded step per call) until it prints CONVERT DONE
//        (or CONVERT FAILED, which stops that job)
//   node Tools/Foliage/run_foliage.mjs py <file.py> [KEY=VALUE ...]
//        send a python_run script; each KEY=VALUE rewrites a line that starts
//        with "KEY = " into "KEY = VALUE" (VALUE is a Python literal, or
//        @path for a file's code lines as a list of strings)
//
// Jobs live in Tools/Foliage/foliage_jobs.json. Each python_run is one request
// with Hayba's 5 s cooperative deadline, so a job converts one mesh over several calls.
// The editor gate (Tools/GameFlow/editor_gate.py) must be held by the caller.
// Nothing here saves packages; save with Tools/Foliage/save_packages.py.
//
// Node 20+, no dependencies.

import net from 'node:net';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.HAYBA_PORT ?? 52342);

function pyLiteral(value) {
  if (typeof value === 'boolean') return value ? 'True' : 'False';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return `'${value}'`;
  if (Array.isArray(value)) return `[${value.map(pyLiteral).join(', ')}]`;
  return `{${Object.entries(value).map(([k, v]) => `'${k}': ${pyLiteral(v)}`).join(', ')}}`;
}

// KEY=@path passes a file's code lines (comment-only and blank lines dropped)
// as a Python list of strings: python_run scripts may not open files.
function fileValue(value) {
  if (!value.startsWith('@')) return value;
  const lines = readFileSync(value.slice(1), 'utf8').split(/\r?\n/)
    .filter((l) => l.trim() !== '' && !l.trim().startsWith('//'));
  for (const l of lines) if (/['\\]/.test(l)) throw new Error(`${value}: quote or backslash in ${l}`);
  return pyLiteral(lines);
}

// Rewrite "NAME = ..." lines. Every name must match exactly one line.
export function rewrite(script, assignments) {
  const lines = script.split('\n');
  for (const [name, value] of Object.entries(assignments)) {
    const hits = lines.map((l, i) => (l.startsWith(`${name} = `) ? i : -1)).filter((i) => i >= 0);
    if (hits.length !== 1) throw new Error(`expected one "${name} = " line, found ${hits.length}`);
    lines[hits[0]] = `${name} = ${value}`;
  }
  return lines.join('\n');
}

function connect() {
  const socket = net.createConnection({ host: '127.0.0.1', port: PORT });
  let buffer = Buffer.alloc(0);
  const pending = new Map();
  socket.on('data', (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    while (buffer.length >= 4) {
      const len = buffer.readUInt32BE(0);
      if (buffer.length < 4 + len) return;
      const msg = JSON.parse(buffer.subarray(4, 4 + len).toString('utf8'));
      buffer = buffer.subarray(4 + len);
      const done = pending.get(msg.id);
      if (done) { pending.delete(msg.id); done(msg); }
    }
  });
  let n = 0;
  const send = (cmd, params) => new Promise((resolve) => {
    const id = `foliage_${process.pid}_${++n}`;
    const payload = Buffer.from(JSON.stringify({ cmd, id, params }), 'utf8');
    const header = Buffer.alloc(4);
    header.writeUInt32BE(payload.length, 0);
    const timer = setTimeout(() => { pending.delete(id); resolve({ ok: false, error: 'timeout' }); }, 180000);
    pending.set(id, (m) => { clearTimeout(timer); resolve(m); });
    socket.write(Buffer.concat([header, payload]));
  });
  return new Promise((resolve, reject) => {
    socket.on('connect', () => resolve({ send, close: () => socket.end() }));
    socket.on('error', reject);
  });
}

function show(label, r) {
  if (r.ok) {
    process.stdout.write(`${label}: ${r.data.stdout ?? ''}${r.data.stderr ? `\nSTDERR ${r.data.stderr}` : ''}\n`);
  } else {
    process.stdout.write(`${label}: FAILED ${JSON.stringify(r.error ?? r.data)}\n`);
  }
  return r.ok;
}

async function main() {
  const [cmd, ...args] = process.argv.slice(2);
  const client = await connect();
  let failures = 0;
  if (cmd === 'convert') {
    const jobs = JSON.parse(readFileSync(join(HERE, 'foliage_jobs.json'), 'utf8'));
    const names = args[0] === 'all' ? Object.keys(jobs) : args;
    const source = readFileSync(join(HERE, 'convert_to_static.py'), 'utf8');
    for (const name of names) {
      const job = jobs[name];
      if (!job) throw new Error(`unknown job ${name}`);
      const script = rewrite(source, { JOB: pyLiteral({ src: job.src, dst: job.dst }) });
      // convert_to_static.py does one bounded step per call; repeat until DONE.
      // Work in progress from an earlier, interrupted run is dropped first.
      // A deadline refusal after the LOD step is tolerated (the LOD build is
      // native and can outlive 5 s): the next call only checks the result.
      await client.send('python_run', { script: `import unreal
if hasattr(unreal, 'saskarta_v4_convert'):
    unreal.saskarta_v4_convert.pop('${job.dst}', None)
` });
      let done = false;
      for (let step = 0; step < 40 && !done; step++) {
        const r = await client.send('python_run', { script });
        const out = r.ok ? r.data.stdout ?? '' : '';
        if (r.ok) process.stdout.write(`${name} [${step}]: ${out.trim()}
`);
        else if (String(r.error).includes('execution_deadline')) process.stdout.write(`${name} [${step}]: deadline (native build still ran), re-checking
`);
        else { process.stdout.write(`${name} [${step}]: FAILED ${JSON.stringify(r.error ?? r.data)}
`); break; }
        done = out.includes('CONVERT DONE');
        if (out.includes('CONVERT FAILED')) break;
      }
      if (!done) failures++;
    }
  } else if (cmd === 'py') {
    const [file, ...pairs] = args;
    const assignments = Object.fromEntries(pairs.map((p) => [p.slice(0, p.indexOf('=')), fileValue(p.slice(p.indexOf('=') + 1))]));
    const script = rewrite(readFileSync(file, 'utf8'), assignments);
    if (!show(file, await client.send('python_run', { script }))) failures++;
  } else {
    throw new Error('usage: run_foliage.mjs convert <job ...|all> | py <file.py> [KEY=VALUE ...]');
  }
  client.close();
  process.exit(failures ? 1 : 0);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
