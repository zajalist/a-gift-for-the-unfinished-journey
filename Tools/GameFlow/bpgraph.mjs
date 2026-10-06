#!/usr/bin/env node
// bpgraph: build Blueprint graphs from JSON specs through the Hayba plugin's TCP port.
//
//   node Tools/GameFlow/bpgraph.mjs check <spec.json ...>
//   node Tools/GameFlow/bpgraph.mjs build [--port N] [--project DIR] [--reset-graphs] <spec.json ...>
//
// `check` is offline: it validates the spec format described in
// docs/superpowers/plans/2026-09-26-saskarta-game-flow.md ("Graph spec format").
// `build` drives the live editor in passes across ALL given specs, so blueprints
// built together can reference and call each other:
//
//   1 skeleton  create assets, add missing variables, components and functions,
//               compile every asset (save).
//   2 graphs    optionally clear each graph (--reset-graphs), place event nodes,
//               compile (so custom events become callable), place the other nodes,
//               set pin defaults, then link.
//   3 finish    CDO defaults, compile every asset (save), collect compile errors.
//   4 verify    read every graph back and confirm each spec link is a real edge.
//
// A reply is a claim: every mutation is checked against the reply's own readback
// (verified / compiled_clean), and pass 4 re-reads the graphs from the editor.
// Progress goes to stderr, the JSON report to stdout. Exit code 0 only when every
// asset compiled, every node exists and every spec link was found. Exit code 3:
// a target package is read-only or another Unreal process may hold it open;
// nothing was sent.
//
// Limits found live (UE 5.8, Hayba 2026-09-26):
// - A literal on a by-ref input (e.g. Conv_TextToString.InText) is refused by the
//   schema; wire a variable get into it instead.
// - Text-pin literals DO stick, but the plugin's readback compares DefaultValue,
//   not DefaultTextValue, so they are reported as warnings, not verified.
// - The spec has no way to set component template properties (a component's
//   Sound or bAutoActivate); cdo_defaults reaches only the class default object.
// - Without --reset-graphs a graph that already holds nodes or links is refused,
//   so a rerun never duplicates a build.
// - A compile-and-save of a read-only package crashes the editor: the save fails
//   ("Cannot remove ... as it is read only!"), Hayba's SEH guard swallows the
//   appError, and the next frame dies in StaticFindObjectFast (P3, 2026-09-27).
//   .gitattributes marks *.uasset LFS-lockable, so every committed asset is
//   checked out read-only. `build` therefore checks every target package on disk
//   first and refuses the whole run, before connecting, if any is read-only.
// - A standalone -game process holding the same assets caused Windows sharing
//   violation 32 on 2026-09-28. The process guard also refuses concurrent project
//   processes before connecting; exclusive-open probes would reject the editor itself.
//
// Node 20+, no dependencies.

import net from 'node:net';
import { accessSync, constants as fsConstants, existsSync, readdirSync, readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// ─── Spec text ───────────────────────────────────────────────────────────────

/**
 * Parse JSON (with // and /* *\/ comments allowed) and report duplicate object
 * keys. JSON.parse keeps the last of two equal keys, which silently drops a
 * node from a spec; this parser names every duplicate instead.
 * Returns { value, duplicates: string[] }; throws SyntaxError with line/column.
 */
export function parseSpecText(text) {
  let i = 0;
  const duplicates = [];

  const where = () => {
    const before = text.slice(0, i).split('\n');
    return `line ${before.length}, column ${before[before.length - 1].length + 1}`;
  };
  const fail = (message) => {
    throw new SyntaxError(`${message} at ${where()}`);
  };

  function skipSpace() {
    for (;;) {
      const c = text[i];
      if (c === ' ' || c === '\t' || c === '\n' || c === '\r' || c === '﻿') i++;
      else if (c === '/' && text[i + 1] === '/') {
        while (i < text.length && text[i] !== '\n') i++;
      } else if (c === '/' && text[i + 1] === '*') {
        const end = text.indexOf('*/', i + 2);
        if (end < 0) fail('unterminated /* comment');
        i = end + 2;
      } else return;
    }
  }

  const STRING = /"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/y;
  const NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;

  function parseString() {
    STRING.lastIndex = i;
    const m = STRING.exec(text);
    if (!m) fail('bad string');
    i = STRING.lastIndex;
    return JSON.parse(m[0]);
  }

  function parseValue(path) {
    skipSpace();
    const c = text[i];
    if (c === '{') return parseObject(path);
    if (c === '[') return parseArray(path);
    if (c === '"') return parseString();
    if (c === '-' || (c >= '0' && c <= '9')) {
      NUMBER.lastIndex = i;
      const m = NUMBER.exec(text);
      if (!m) fail('bad number');
      i = NUMBER.lastIndex;
      return Number(m[0]);
    }
    for (const [word, v] of [['true', true], ['false', false], ['null', null]]) {
      if (text.startsWith(word, i)) {
        i += word.length;
        return v;
      }
    }
    return fail(c === undefined ? 'unexpected end of input' : `unexpected ${JSON.stringify(c)}`);
  }

  function parseObject(path) {
    i++; // {
    const out = {};
    const seen = new Set();
    skipSpace();
    if (text[i] === '}') {
      i++;
      return out;
    }
    for (;;) {
      skipSpace();
      if (text[i] !== '"') fail('expected a property name in double quotes');
      const key = parseString();
      if (seen.has(key)) duplicates.push(`${path || '(root)'}: duplicate key "${key}"`);
      seen.add(key);
      skipSpace();
      if (text[i] !== ':') fail("expected ':'");
      i++;
      const v = parseValue(path ? `${path}.${key}` : key);
      Object.defineProperty(out, key, { value: v, enumerable: true, writable: true, configurable: true });
      skipSpace();
      if (text[i] === ',') {
        i++;
        skipSpace();
        if (text[i] === '}') fail('trailing comma');
        continue;
      }
      if (text[i] === '}') {
        i++;
        return out;
      }
      fail("expected ',' or '}'");
    }
  }

  function parseArray(path) {
    i++; // [
    const out = [];
    skipSpace();
    if (text[i] === ']') {
      i++;
      return out;
    }
    for (;;) {
      out.push(parseValue(`${path}[${out.length}]`));
      skipSpace();
      if (text[i] === ',') {
        i++;
        skipSpace();
        if (text[i] === ']') fail('trailing comma');
        continue;
      }
      if (text[i] === ']') {
        i++;
        return out;
      }
      fail("expected ',' or ']'");
    }
  }

  const value = parseValue('');
  skipSpace();
  if (i < text.length) fail('unexpected text after the JSON value');
  return { value, duplicates };
}

// ─── Hayba type grammar (mirror of HaybaBlueprintOps::ParseTypeSpec) ─────────

const SCALAR_TYPES = new Map([
  ['bool', 'bool'], ['boolean', 'bool'],
  ['int', 'int'], ['integer', 'int'], ['int32', 'int'],
  ['int64', 'int64'],
  ['float', 'real'], ['double', 'real'], ['real', 'real'],
  ['string', 'string'], ['fstring', 'string'],
  ['name', 'name'], ['fname', 'name'],
  ['text', 'text'], ['ftext', 'text'],
  ['byte', 'byte'], ['uint8', 'byte'],
]);
const ENGINE_STRUCTS = new Map([
  ['vector', '/Script/CoreUObject.Vector'],
  ['rotator', '/Script/CoreUObject.Rotator'],
  ['transform', '/Script/CoreUObject.Transform'],
  ['linear_color', '/Script/CoreUObject.LinearColor'],
  ['linearcolor', '/Script/CoreUObject.LinearColor'],
  ['vector2d', '/Script/CoreUObject.Vector2D'],
]);
const REFERENCE_KINDS = new Set(['object', 'class', 'soft_object', 'soft_class', 'struct', 'enum']);

/** The pin category Hayba's blueprint_get_info reports for a parsed type. */
const CATEGORY_OF_KIND = {
  bool: 'bool', int: 'int', int64: 'int64', real: 'real', string: 'string', name: 'name', text: 'text',
  byte: 'byte', enum: 'byte', struct: 'struct', object: 'object', class: 'class',
  soft_object: 'softobject', soft_class: 'softclass',
};

/**
 * Parse a Hayba type string. Returns { kind, path, array } or { error }.
 * Stricter than the plugin in one way: an object/class reference into /Game must
 * name the generated class (ending in _C), because the plugin's LoadClass of the
 * asset path fails live with a less direct message.
 */
export function parseType(spec) {
  if (typeof spec !== 'string') return { error: 'type must be a string' };
  const s = spec.trim();
  if (!s) return { error: 'empty type' };
  if (/^array</i.test(s)) {
    if (!s.endsWith('>')) return { error: `'${spec}' opens array< but never closes it` };
    const inner = s.slice(6, -1).trim();
    if (/^array</i.test(inner)) return { error: `'${spec}': arrays of arrays are not a Blueprint type` };
    const t = parseType(inner);
    return t.error ? t : { ...t, array: true };
  }
  const colon = s.indexOf(':');
  if (colon >= 0) {
    const prefix = s.slice(0, colon).trim().toLowerCase();
    const path = s.slice(colon + 1).trim();
    if (!REFERENCE_KINDS.has(prefix)) return { error: `'${spec}': unknown reference kind '${prefix}'` };
    if (!path.startsWith('/')) return { error: `'${spec}' needs a full path after '${prefix}:'` };
    if (['object', 'class', 'soft_object', 'soft_class'].includes(prefix) && path.startsWith('/Game/') && !/\.[A-Za-z_]\w*_C$/.test(path)) {
      return { error: `'${spec}': a Blueprint class path ends in .Name_C, e.g. /Game/Dir/BP_X.BP_X_C` };
    }
    return { kind: prefix, path, array: false };
  }
  const lower = s.toLowerCase();
  if (SCALAR_TYPES.has(lower)) return { kind: SCALAR_TYPES.get(lower), path: '', array: false };
  if (ENGINE_STRUCTS.has(lower)) return { kind: 'struct', path: ENGINE_STRUCTS.get(lower), array: false };
  return {
    error: `unknown type '${spec}' (accepted: bool, int, int64, float, double, string, name, text, byte, vector, rotator, transform, linear_color, vector2d, object:/class:/soft_object:/soft_class:/struct:/enum:<path>, array<...>)`,
  };
}

// ─── Spec validation ─────────────────────────────────────────────────────────

const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PIN = /^[A-Za-z_](?:[A-Za-z0-9_ /]*[A-Za-z0-9_])?$/; // '/' for template pins such as 'Left / Right'
const ENDPOINT = /^([A-Za-z_][A-Za-z0-9_]*)\.(.+)$/;
const RESERVED_PARAMS = new Set(['execute', 'then', 'self']);

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isScalar = (v) => typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean';
const lc = (s) => String(s).toLowerCase();
const loose = (s) => String(s).toLowerCase().replace(/\s+/g, '');

/** A class path the plugin can LoadClass: /Script/Module.Class, or /Game/...Name_C. */
function classPathProblem(path) {
  if (typeof path !== 'string' || !path.startsWith('/')) return 'must be a class path starting with /';
  if (path.startsWith('/Game/') && !/\.[A-Za-z_]\w*_C$/.test(path)) return 'a Blueprint class path ends in .Name_C, e.g. /Game/Dir/BP_X.BP_X_C';
  if (path.startsWith('/Script/') && !/^\/Script\/\w+\.\w+$/.test(path)) return 'a native class path looks like /Script/Module.Class';
  return null;
}

/** Node kinds: how the kind's value is checked, which extra keys it allows, and
 *  whether the node has input pins (link target) or output pins (link source). */
const NODE_KINDS = {
  entry: { value: (v) => v === true || 'must be true', extras: [], inputs: false, outputs: true, functionOnly: true },
  result: { value: (v) => v === true || 'must be true', extras: [], inputs: true, outputs: false, functionOnly: true },
  event: { value: (v) => (typeof v === 'string' && v.trim() !== '') || 'must name an overridable event, e.g. "ReceiveBeginPlay"', extras: [], inputs: false, outputs: true, eventOnly: true },
  custom_event: { value: (v) => (typeof v === 'string' && IDENT.test(v)) || 'must be an identifier', extras: ['inputs'], inputs: false, outputs: true, eventOnly: true },
  bound_event: {
    value: (v) => (isObj(v) && typeof v.target === 'string' && IDENT.test(v.target) && typeof v.event === 'string' && IDENT.test(v.event)
      && Object.keys(v).every((k) => k === 'target' || k === 'event')) || 'must be {"target": <component/widget variable>, "event": <delegate>}',
    extras: [], inputs: false, outputs: true, eventOnly: true,
  },
  call: { value: (v) => (typeof v === 'string' && IDENT.test(v)) || 'must be a function name', extras: ['class'], inputs: true, outputs: true },
  get: { value: (v) => (typeof v === 'string' && IDENT.test(v)) || 'must be a variable name', extras: [], inputs: false, outputs: true },
  set: { value: (v) => (typeof v === 'string' && IDENT.test(v)) || 'must be a variable name', extras: [], inputs: true, outputs: true },
  branch: { value: (v) => v === true || 'must be true', extras: [], inputs: true, outputs: true },
  sequence: { value: (v) => (Number.isInteger(v) && v >= 2 && v <= 32) || 'must be the number of outputs, 2..32', extras: [], inputs: true, outputs: true },
  select: { value: (v) => (Number.isInteger(v) && v >= 2 && v <= 32) || 'must be the number of options, 2..32', extras: [], inputs: true, outputs: true },
  self: { value: (v) => v === true || 'must be true', extras: [], inputs: false, outputs: true },
  cast: { value: (v) => classPathProblem(v) === null || `class ${classPathProblem(v)}`, extras: [], inputs: true, outputs: true },
  create_widget: { value: (v) => classPathProblem(v) === null || `class ${classPathProblem(v)}`, extras: [], inputs: true, outputs: true },
  timer: { value: (v) => v === true || 'must be true', extras: [], inputs: true, outputs: true },
};
export const NODE_KIND_NAMES = Object.keys(NODE_KINDS);
const EVENT_KINDS = new Set(['event', 'custom_event', 'bound_event']);
const POSITION_KEYS = new Set(['x', 'y']);

/** The one kind key of a node spec, or null. */
export function nodeKind(node) {
  if (!isObj(node)) return null;
  const kinds = Object.keys(node).filter((k) => k in NODE_KINDS);
  return kinds.length === 1 ? kinds[0] : null;
}

/** Split "node.Pin"; null when the syntax is wrong. */
export function parseEndpoint(endpoint) {
  if (typeof endpoint !== 'string') return null;
  const m = ENDPOINT.exec(endpoint);
  if (!m || !PIN.test(m[2])) return null;
  return { node: m[1], pin: m[2] };
}

/** Problems with a {name, type} parameter list (function inputs/outputs, event inputs). */
function checkParams(list, where, errors, namesSoFar = []) {
  if (list === undefined) return namesSoFar;
  if (!Array.isArray(list)) {
    errors.push(`${where}: must be an array of {"name", "type"}`);
    return namesSoFar;
  }
  if (list.length > 32) errors.push(`${where}: ${list.length} entries; the plugin's limit is 32`);
  const names = [...namesSoFar];
  list.forEach((p, i) => {
    const at = `${where}[${i}]`;
    if (!isObj(p) || typeof p.name !== 'string' || typeof p.type !== 'string') {
      errors.push(`${at}: must be {"name": string, "type": string}`);
      return;
    }
    for (const k of Object.keys(p)) if (k !== 'name' && k !== 'type') errors.push(`${at}: unknown key "${k}"`);
    const name = p.name.trim();
    if (!PIN.test(name)) errors.push(`${at}: name "${p.name}" is not a valid pin name`); // template functions use names like "Left / Right"
    else if (RESERVED_PARAMS.has(lc(name))) errors.push(`${at}: "${name}" is reserved (every node already has a pin by that name)`);
    else if (names.some((n) => lc(n) === lc(name))) errors.push(`${at}: duplicate parameter name "${name}" (names compare case-insensitively)`);
    names.push(name);
    const t = parseType(p.type);
    if (t.error) errors.push(`${at}: ${t.error}`);
  });
  return names;
}

const TOP_KEYS = new Set(['asset', 'create', 'variables', 'components', 'functions', 'graphs', 'cdo_defaults', 'description', '$comment']);

/**
 * Validate one spec. `input` is the parsed object or the spec's text.
 * Returns an array of problems; empty means the spec is valid.
 */
export function check(input) {
  const errors = [];
  let spec = input;
  if (typeof input === 'string') {
    try {
      const parsed = parseSpecText(input);
      errors.push(...parsed.duplicates);
      spec = parsed.value;
    } catch (err) {
      return [`not valid JSON: ${err.message}`];
    }
  }
  if (!isObj(spec)) return [...errors, 'a spec must be a JSON object'];

  for (const k of Object.keys(spec)) if (!TOP_KEYS.has(k)) errors.push(`unknown top-level key "${k}"`);

  if (typeof spec.asset !== 'string' || !/^\/Game(\/[A-Za-z_][A-Za-z0-9_]*)+$/.test(spec.asset)) {
    errors.push('asset: must be a package path like /Game/Dir/BP_Name (no .Name suffix)');
  }

  if (spec.create !== undefined) {
    if (!isObj(spec.create)) errors.push('create: must be {"parent": <class path>}');
    else {
      for (const k of Object.keys(spec.create)) if (k !== 'parent') errors.push(`create: unknown key "${k}"`);
      const problem = classPathProblem(spec.create.parent);
      if (problem) errors.push(`create.parent: ${problem}`);
    }
  }

  // Member names share one namespace on the generated class.
  const members = new Map(); // lower name -> "variable X" etc.
  const claim = (name, what, where) => {
    const prior = members.get(lc(name));
    if (prior) errors.push(`${where}: "${name}" duplicates ${prior}`);
    else members.set(lc(name), `${what} "${name}"`);
  };

  const variables = spec.variables ?? [];
  if (!Array.isArray(variables)) errors.push('variables: must be an array');
  else variables.forEach((v, i) => {
    const at = `variables[${i}]`;
    if (!isObj(v)) return errors.push(`${at}: must be {"name", "type", "default"?}`);
    for (const k of Object.keys(v)) if (!['name', 'type', 'default'].includes(k)) errors.push(`${at}: unknown key "${k}"`);
    if (typeof v.name !== 'string' || !IDENT.test(v.name)) errors.push(`${at}: name must be an identifier`);
    else claim(v.name, 'variable', at);
    const t = parseType(v.type);
    if (t.error) errors.push(`${at} (${v.name}): ${t.error}`);
    if ('default' in v && v.default === null) errors.push(`${at} (${v.name}): default must not be null`);
  });

  const components = spec.components ?? [];
  if (!Array.isArray(components)) errors.push('components: must be an array');
  else components.forEach((c, i) => {
    const at = `components[${i}]`;
    if (!isObj(c)) return errors.push(`${at}: must be {"name", "class"}`);
    for (const k of Object.keys(c)) if (k !== 'name' && k !== 'class') errors.push(`${at}: unknown key "${k}"`);
    if (typeof c.name !== 'string' || !IDENT.test(c.name)) errors.push(`${at}: name must be an identifier`);
    else claim(c.name, 'component', at);
    const problem = classPathProblem(c.class);
    if (problem) errors.push(`${at} (${c.name}).class: ${problem}`);
  });

  const functions = new Map(); // lower name -> function spec
  const fnList = spec.functions ?? [];
  if (!Array.isArray(fnList)) errors.push('functions: must be an array');
  else fnList.forEach((f, i) => {
    const at = `functions[${i}]`;
    if (!isObj(f)) return errors.push(`${at}: must be {"name", "inputs"?, "outputs"?, "pure"?}`);
    for (const k of Object.keys(f)) if (!['name', 'inputs', 'outputs', 'pure'].includes(k)) errors.push(`${at}: unknown key "${k}"`);
    if (typeof f.name !== 'string' || !IDENT.test(f.name)) return errors.push(`${at}: name must be an identifier`);
    claim(f.name, 'function', at);
    functions.set(lc(f.name), f);
    const names = checkParams(f.inputs, `${at} (${f.name}).inputs`, errors);
    checkParams(f.outputs, `${at} (${f.name}).outputs`, errors, names);
    if (f.pure !== undefined && typeof f.pure !== 'boolean') errors.push(`${at} (${f.name}).pure: must be true or false`);
  });

  const graphs = spec.graphs ?? [];
  const seenGraphs = new Set();
  const customEvents = new Map();
  if (!Array.isArray(graphs)) errors.push('graphs: must be an array');
  else graphs.forEach((g, gi) => {
    let at = `graphs[${gi}]`;
    if (!isObj(g)) return errors.push(`${at}: must be {"graph", "nodes", "links"?, "defaults"?}`);
    for (const k of Object.keys(g)) if (!['graph', 'nodes', 'links', 'defaults'].includes(k)) errors.push(`${at}: unknown key "${k}"`);
    if (typeof g.graph !== 'string' || !g.graph) return errors.push(`${at}: graph must be "EventGraph" or a declared function name`);
    at = `graph ${g.graph}`;
    if (seenGraphs.has(lc(g.graph))) errors.push(`${at}: listed twice`);
    seenGraphs.add(lc(g.graph));
    const isEvent = lc(g.graph) === 'eventgraph';
    const fn = functions.get(lc(g.graph));
    if (!isEvent && !fn) errors.push(`${at}: not "EventGraph" and not a function declared in "functions"`);
    const hasOutputs = Array.isArray(fn?.outputs) && fn.outputs.length > 0;

    const nodes = g.nodes;
    const kinds = new Map(); // node name -> kind
    if (!isObj(nodes)) errors.push(`${at}: nodes must be an object of name -> node`);
    else for (const [name, node] of Object.entries(nodes)) {
      const nat = `${at} node "${name}"`;
      if (!IDENT.test(name)) errors.push(`${nat}: node names must be identifiers`);
      if (!isObj(node)) {
        errors.push(`${nat}: must be an object with one kind key (${NODE_KIND_NAMES.join(', ')})`);
        continue;
      }
      const present = Object.keys(node).filter((k) => k in NODE_KINDS);
      if (present.length !== 1) {
        const unknown = Object.keys(node).filter((k) => !(k in NODE_KINDS) && !POSITION_KEYS.has(k) && k !== 'class' && k !== 'inputs');
        errors.push(present.length === 0
          ? `${nat}: unknown node kind${unknown.length ? ` "${unknown.join('", "')}"` : ''}; valid kinds: ${NODE_KIND_NAMES.join(', ')}`
          : `${nat}: has ${present.length} kind keys (${present.join(', ')}); a node has exactly one`);
        continue;
      }
      const kind = present[0];
      kinds.set(name, kind);
      const rule = NODE_KINDS[kind];
      const verdict = rule.value(node[kind]);
      if (verdict !== true) errors.push(`${nat}: "${kind}" ${verdict}`);
      for (const k of Object.keys(node)) {
        if (k === kind || POSITION_KEYS.has(k) || rule.extras.includes(k)) continue;
        errors.push(`${nat}: key "${k}" is not valid on a ${kind} node`);
      }
      for (const k of POSITION_KEYS) if (k in node && !Number.isFinite(node[k])) errors.push(`${nat}: ${k} must be a number`);
      if (kind === 'call' && node.class !== undefined) {
        const problem = classPathProblem(node.class);
        if (problem) errors.push(`${nat}: class ${problem}`);
      }
      if (kind === 'custom_event') {
        checkParams(node.inputs, `${nat}.inputs`, errors);
        const evName = node.custom_event;
        if (typeof evName === 'string') {
          if (customEvents.has(lc(evName))) errors.push(`${nat}: custom event "${evName}" is declared twice (also ${customEvents.get(lc(evName))})`);
          else customEvents.set(lc(evName), nat);
          if (members.has(lc(evName))) errors.push(`${nat}: custom event "${evName}" duplicates ${members.get(lc(evName))}`);
        }
      }
      if (rule.eventOnly && !isEvent) errors.push(`${nat}: ${kind} nodes live in the EventGraph, not a function graph`);
      if (rule.functionOnly && isEvent) errors.push(`${nat}: ${kind} nodes exist only in function graphs, not the EventGraph`);
      if (kind === 'result' && fn && !hasOutputs) errors.push(`${nat}: function ${fn.name} declares no outputs, so it has no result node`);
    }
    const countKind = (k) => [...kinds.values()].filter((v) => v === k).length;
    if (countKind('entry') > 1) errors.push(`${at}: more than one entry node`);
    if (countKind('result') > 1) errors.push(`${at}: more than one result node`);

    // Links: "node.Pin" output -> "node.Pin" input, both nodes declared.
    const targets = new Map();
    const execSources = new Map();
    const linkKeys = new Set();
    const linked = new Set();
    const links = g.links ?? [];
    if (!Array.isArray(links)) errors.push(`${at}: links must be an array of ["from.Pin", "to.Pin"]`);
    else links.forEach((link, li) => {
      const lat = `${at} links[${li}]`;
      if (!Array.isArray(link) || link.length !== 2 || !link.every((e) => typeof e === 'string')) {
        return errors.push(`${lat}: must be ["from.Pin", "to.Pin"]`);
      }
      const [a, b] = link.map(parseEndpoint);
      if (!a) errors.push(`${lat}: "${link[0]}" is not "node.Pin"`);
      if (!b) errors.push(`${lat}: "${link[1]}" is not "node.Pin"`);
      if (!a || !b) return;
      const text = `${link[0]} -> ${link[1]}`;
      for (const [end, role] of [[a, 'from'], [b, 'to']]) {
        if (!isObj(nodes) || !(end.node in nodes)) errors.push(`${lat} (${text}): ${role} node "${end.node}" is not declared in nodes`);
      }
      const ka = kinds.get(a.node);
      const kb = kinds.get(b.node);
      if (ka && !NODE_KINDS[ka].outputs) errors.push(`${lat} (${text}): a ${ka} node has no output pins to link from`);
      if (kb && !NODE_KINDS[kb].inputs) errors.push(`${lat} (${text}): a ${kb} node has no input pins to link to`);
      if (lc(a.pin) === 'execute') errors.push(`${lat} (${text}): "execute" is an input pin; links run output -> input`);
      if (/^(then|else|then_\d+|castfailed)$/i.test(b.pin)) errors.push(`${lat} (${text}): "${b.pin}" is an output pin; links run output -> input`);
      if (a.node === b.node) errors.push(`${lat} (${text}): links a node to itself`);
      const key = `${loose(link[0])}>${loose(link[1])}`;
      if (linkKeys.has(key)) errors.push(`${lat} (${text}): duplicate link`);
      linkKeys.add(key);
      // A data input takes one link; an exec output drives one node.
      const tkey = `${b.node}.${loose(b.pin)}`;
      if (lc(b.pin) !== 'execute') {
        if (targets.has(tkey)) errors.push(`${lat} (${text}): input ${link[1]} is already linked from ${targets.get(tkey)}`);
        targets.set(tkey, link[0]);
      }
      if (/^(then|else|then_\d+|castfailed)$/i.test(a.pin)) {
        const skey = `${a.node}.${lc(a.pin)}`;
        if (execSources.has(skey)) errors.push(`${lat} (${text}): exec output ${link[0]} already drives ${execSources.get(skey)}`);
        execSources.set(skey, link[1]);
      }
      linked.add(tkey);
    });

    const defaults = g.defaults ?? {};
    if (!isObj(defaults)) errors.push(`${at}: defaults must be an object of "node.Pin" -> value`);
    else for (const [endpoint, value] of Object.entries(defaults)) {
      const dat = `${at} defaults["${endpoint}"]`;
      const e = parseEndpoint(endpoint);
      if (!e) {
        errors.push(`${dat}: key is not "node.Pin"`);
        continue;
      }
      if (!isObj(nodes) || !(e.node in nodes)) errors.push(`${dat}: node "${e.node}" is not declared in nodes`);
      const k = kinds.get(e.node);
      if (k && !NODE_KINDS[k].inputs) errors.push(`${dat}: a ${k} node has no input pins to set`);
      if (!isScalar(value)) errors.push(`${dat}: value must be a string, number or boolean`);
      if (linked.has(`${e.node}.${loose(e.pin)}`)) errors.push(`${dat}: the pin is also linked; a literal on a linked pin is ignored`);
    }
  });

  if (spec.cdo_defaults !== undefined) {
    if (!isObj(spec.cdo_defaults) || Object.keys(spec.cdo_defaults).length === 0) errors.push('cdo_defaults: must be a non-empty object of property -> value');
    else for (const [k, v] of Object.entries(spec.cdo_defaults)) {
      if (!IDENT.test(k)) errors.push(`cdo_defaults["${k}"]: property names are identifiers`);
      if (v === null) errors.push(`cdo_defaults["${k}"]: value must not be null`);
    }
  }
  return errors;
}

/** Problems that span specs built together (the same asset twice). */
export function checkAcross(entries) {
  const errors = [];
  const seen = new Map();
  for (const { file, spec } of entries) {
    if (!isObj(spec) || typeof spec.asset !== 'string') continue;
    const key = lc(spec.asset);
    if (seen.has(key)) errors.push(`${file}: asset ${spec.asset} is also built by ${seen.get(key)}`);
    else seen.set(key, file);
  }
  return errors;
}

// ─── Pins and layout (pure helpers used by build) ────────────────────────────

/**
 * Find the real pin a spec names. Exact name first, then case/space-insensitive,
 * then (cast nodes) "As" for the single output whose name starts with "As".
 * `pins` are Hayba pin descriptions {name, direction}. Returns { name } or { error }.
 */
export function resolvePin(pins, wanted, direction, { cast = false } = {}) {
  const candidates = (pins ?? []).filter((p) => p.direction === direction);
  const exact = candidates.find((p) => p.name === wanted);
  if (exact) return { name: exact.name };
  const near = candidates.filter((p) => loose(p.name) === loose(wanted));
  if (near.length === 1) return { name: near[0].name };
  if (near.length > 1) return { error: `"${wanted}" matches several ${direction} pins: ${near.map((p) => p.name).join(', ')}` };
  if (cast && loose(wanted) === 'as') {
    const as = candidates.filter((p) => /^as/i.test(p.name));
    if (as.length === 1) return { name: as[0].name };
  }
  const names = candidates.map((p) => `"${p.name}"`).join(', ') || '(none)';
  return { error: `no ${direction} pin "${wanted}"; its ${direction} pins are ${names}` };
}

/** Layered positions: a node sits one column right of the nodes that feed it;
 *  a node fed by nothing sits just left of its first consumer. */
export function layoutNodes(names, links) {
  const depth = new Map(names.map((n) => [n, 0]));
  const edges = [];
  for (const link of links ?? []) {
    const a = parseEndpoint(link?.[0]);
    const b = parseEndpoint(link?.[1]);
    if (a && b && a.node !== b.node && depth.has(a.node) && depth.has(b.node)) edges.push([a.node, b.node]);
  }
  const limit = names.length;
  for (let pass = 0; pass < limit; pass++) {
    let changed = false;
    for (const [u, v] of edges) {
      if (depth.get(v) < depth.get(u) + 1 && depth.get(u) + 1 <= limit) {
        depth.set(v, depth.get(u) + 1);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const fed = new Set(edges.map(([, v]) => v));
  for (const n of names) {
    if (fed.has(n)) continue;
    const next = edges.filter(([u]) => u === n).map(([, v]) => depth.get(v));
    if (next.length) depth.set(n, Math.max(0, Math.min(...next) - 1));
  }
  const rows = new Map();
  const out = {};
  for (const n of names) {
    const d = depth.get(n);
    const row = rows.get(d) ?? 0;
    rows.set(d, row + 1);
    out[n] = { x: 320 + d * 360, y: row * 220 };
  }
  return out;
}

/** The function entry and result nodes of an inspected function graph. */
export function findTerminals(nodes, functionName, known = {}) {
  const byId = (id) => (id ? nodes.find((n) => n.node_id === id) : undefined);
  const inputs = (n) => n.pins.filter((p) => p.direction === 'input');
  const outputs = (n) => n.pins.filter((p) => p.direction === 'output');
  const entry = byId(known.entry)
    ?? nodes.find((n) => loose(n.title) === loose(functionName) && inputs(n).length === 0 && n.pins.some((p) => p.name === 'then'));
  const results = nodes.filter((n) => n.title === 'Return Node' && outputs(n).length === 0 && n.pins.some((p) => p.name === 'execute'));
  const result = byId(known.result) ?? results[0];
  return { entry, result, resultCount: results.length };
}

/**
 * Where an existing function's signature (read from its entry/result pins)
 * differs from the spec's. Hayba cannot edit a signature, so any difference is
 * an error. Returns messages; empty when they match.
 */
export function signatureProblems(terminals, fnSpec) {
  // Function libraries add a hidden __WorldContext parameter; it is not part of the spec.
  const have = (node, dir, skip) => (node?.pins ?? [])
    .filter((p) => p.direction === dir && p.name !== skip && p.type !== 'delegate' && !p.name.startsWith('__'))
    .map((p) => lc(p.name)).sort();
  const want = (list) => (list ?? []).map((p) => lc(p.name)).sort();
  const problems = [];
  const name = fnSpec.name;
  if (!terminals.entry) problems.push(`function ${name} exists but has no recognisable entry node`);
  else if (have(terminals.entry, 'output', 'then').join() !== want(fnSpec.inputs).join()) {
    problems.push(`function ${name} exists with inputs [${have(terminals.entry, 'output', 'then')}], spec says [${want(fnSpec.inputs)}]; Hayba cannot change a signature`);
  }
  if (have(terminals.result, 'input', 'execute').join() !== want(fnSpec.outputs).join()) {
    problems.push(`function ${name} exists with outputs [${have(terminals.result, 'input', 'execute')}], spec says [${want(fnSpec.outputs)}]; Hayba cannot change a signature`);
  }
  return problems;
}

// ─── Package files on disk ───────────────────────────────────────────────────

/** The .uasset file a /Game package path lives in. */
export function packageFile(asset, project) {
  return join(project, 'Content', ...asset.replace(/^\/Game\//, '').split('/')) + '.uasset';
}

/**
 * The target packages that exist on disk but cannot be written (read-only
 * attribute, e.g. an LFS-lockable asset that is not locked). A package that does
 * not exist yet is writable: it is created by the build. Returns
 * [{ asset, file }]. `canWrite` is injectable for tests.
 */
export function readOnlyPackages(assets, project, canWrite = (file) => {
  try {
    accessSync(file, fsConstants.W_OK);
    return true;
  } catch {
    return false;
  }
}, exists = existsSync) {
  const out = [];
  for (const asset of assets) {
    const file = packageFile(asset, project);
    if (exists(file) && !canWrite(file)) out.push({ asset, file });
  }
  return out;
}

/** Refuse saves while another Unreal process for this project may hold packages open. */
export function sharingLockedPackages(assets, project) {
  if (process.platform !== 'win32') return [];
  const files = [...new Set(assets.map((asset) => packageFile(asset, project)).filter(existsSync))];
  if (files.length === 0) return [];
  const probe = join(dirname(fileURLToPath(import.meta.url)), 'probe_package_locks.py');
  const result = spawnSync('python', [probe, project, ...files], { encoding: 'utf8' });
  if (result.error || result.status !== 0) {
    throw new Error(`package lock probe failed: ${result.error?.message ?? result.stderr?.trim() ?? result.status}`);
  }
  const unavailable = new Map(JSON.parse(result.stdout).map(({ file, reason }) => [file.toLowerCase(), reason]));
  return assets.flatMap((asset) => {
    const file = packageFile(asset, project);
    const reason = unavailable.get(file.toLowerCase());
    return reason === undefined ? [] : [{ asset, file, reason }];
  });
}

// ─── Hayba connection ────────────────────────────────────────────────────────

function isAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM';
  }
}

/** The port of the newest registry entry whose editor is still running. */
export function discoverPort(project) {
  const dir = join(project, 'Saved', 'HaybaMCP', 'instances');
  if (!existsSync(dir)) return undefined;
  const live = [];
  for (const f of readdirSync(dir).filter((n) => n.endsWith('.json'))) {
    try {
      const entry = JSON.parse(readFileSync(join(dir, f), 'utf8'));
      if (Number.isInteger(entry.port) && Number.isInteger(entry.pid) && isAlive(entry.pid)) live.push(entry);
    } catch {
      // a half-written registry file is not a port
    }
  }
  live.sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  return live[0]?.port;
}

export class HaybaClient {
  constructor(port, timeoutMs = 60_000) {
    this.port = port;
    this.timeoutMs = timeoutMs;
    this.pending = new Map();
    this.buffer = Buffer.alloc(0);
    this.counter = 0;
    this.calls = 0;
    this.blockedReason = null;
  }

  connect() {
    return new Promise((ok, fail) => {
      let connected = false;
      this.socket = net.createConnection({ host: '127.0.0.1', port: this.port }, () => {
        connected = true;
        ok();
      });
      // After connecting, an error is followed by 'close', which fails every pending call.
      this.socket.on('error', (err) => {
        if (!connected) fail(err);
      });
      this.socket.on('data', (chunk) => this.onData(chunk));
      this.socket.on('close', () => {
        for (const [, waiter] of this.pending) waiter({ ok: false, error: 'connection closed' });
        this.pending.clear();
      });
    });
  }

  onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 4) {
      const length = this.buffer.readUInt32BE(0);
      if (this.buffer.length < 4 + length) return;
      let message;
      try {
        message = JSON.parse(this.buffer.subarray(4, 4 + length).toString('utf8'));
      } catch {
        message = { ok: false, error: 'unparseable reply' };
      }
      this.buffer = this.buffer.subarray(4 + length);
      const waiter = this.pending.get(message.id);
      if (waiter) {
        this.pending.delete(message.id);
        waiter(message);
      }
    }
  }

  /** Send one command. Resolves { ok, data, error } — never rejects. A reply the
   *  compile gate short-circuited ("bp_compile_required") is reported as a failure. */
  send(cmd, params = {}) {
    if (this.blockedReason) return Promise.resolve({ ok: false, error: this.blockedReason });
    if (!this.socket || this.socket.destroyed) return Promise.resolve({ ok: false, error: `${cmd}: connection closed` });
    const id = `bpgraph_${process.pid}_${++this.counter}`;
    const envelope = { cmd, id, params };
    if (/^(?:\[REDACTED:|\[TRUNCATED:|<redacted)/i.test(process.env.HAYBA_LEASE ?? '')) {
      return Promise.resolve({ ok: false, error: `${cmd}: HAYBA_LEASE contains a redaction marker. Use a valid token or the verified native same-owner route with this field omitted.` });
    }
    if (process.env.HAYBA_LEASE) envelope.lease = process.env.HAYBA_LEASE;
    if (process.env.HAYBA_AGENT_ID) envelope.owner = process.env.HAYBA_AGENT_ID;
    if (process.env.HAYBA_AUTH) envelope.auth = process.env.HAYBA_AUTH;
    const payload = Buffer.from(JSON.stringify(envelope), 'utf8');
    const header = Buffer.alloc(4);
    header.writeUInt32BE(payload.length, 0);
    this.calls++;
    return new Promise((done) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        done({ ok: false, error: `${cmd}: no reply within ${this.timeoutMs / 1000} s` });
      }, this.timeoutMs);
      this.pending.set(id, (message) => {
        clearTimeout(timer);
        if (message.lease_warning || message.data?.lease_warning || message.code === 'lease_conflict') {
          this.blockedReason = `${cmd}: native lease warning/conflict; no further requests will be sent. Inspect the live owner/resource/expiry.`;
          done({ ok: false, error: this.blockedReason });
        } else if (message.ok && message.data?.status === 'bp_compile_required') {
          done({ ok: false, error: `${cmd}: blocked — ${message.data.hint ?? 'the blueprint failed its last compile'}`, data: message.data });
        } else done({ ok: Boolean(message.ok), data: message.data, error: message.error });
      });
      this.socket.write(Buffer.concat([header, payload]));
    });
  }

  close() {
    this.socket?.end();
  }
}

// ─── Build ───────────────────────────────────────────────────────────────────

const leafName = (asset) => asset.slice(asset.lastIndexOf('/') + 1);
/** Compare class paths spelled differently: drop _C and the .Name of /Game paths. */
const normClass = (p) => {
  let s = String(p ?? '').replace(/_C$/, '');
  if (s.startsWith('/Game/') && s.includes('.')) s = s.slice(0, s.indexOf('.'));
  return lc(s);
};
const defaultText = (v) => (typeof v === 'string' ? v : typeof v === 'number' || typeof v === 'boolean' ? String(v) : undefined);
/** Does the stored literal mean the requested one? ("2" vs "2.0", "True" vs "true") */
const sameLiteral = (applied, wanted) => {
  if (applied === wanted) return true;
  if (typeof applied !== 'string') return false;
  if (lc(applied) === lc(wanted)) return true;
  const a = Number(applied);
  const b = Number(wanted);
  return applied.trim() !== '' && String(wanted).trim() !== '' && Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 1e-6;
};

/**
 * Build specs into the live editor. `entries` are { file, spec } (already
 * checked). Returns the report; never throws for editor-side failures.
 */
export async function build(entries, client, { resetGraphs = false, log = () => {} } = {}) {
  const assets = entries.map(({ file, spec }) => ({
    file, spec, path: spec.asset, name: leafName(spec.asset),
    errors: [], warnings: [], dead: false,
    fn: new Map(), pendingDefaults: {}, skeletonCompileOk: null,
    compile: null, graphs: [], placedCustomEvents: false,
  }));
  const error = (a, msg) => {
    a.errors.push(msg);
    log(`  ERROR ${a.name}: ${msg}`);
  };
  const warn = (a, msg) => {
    a.warnings.push(msg);
    log(`  warn  ${a.name}: ${msg}`);
  };
  const live = () => assets.filter((a) => !a.dead);
  const send = (cmd, params) => client.send(cmd, params);

  // ── Pass 1: skeleton ──────────────────────────────────────────────────────
  log('pass 1: skeleton');
  for (const a of assets) {
    let info = await send('blueprint_get_info', { path: a.path });
    if (!info.ok) {
      if (!a.spec.create) {
        error(a, `does not exist and the spec has no "create": ${info.error}`);
        a.dead = true;
        continue;
      }
      const r = await send('blueprint_create', { name: a.name, package_path: a.path, parent_class_path: a.spec.create.parent });
      if (!r.ok) {
        error(a, `blueprint_create failed: ${r.error}`);
        a.dead = true;
        continue;
      }
      if (r.data?.saved !== true) warn(a, `created but not saved: ${r.data?.save_error ?? 'saved=false'}`);
      log(`  created ${r.data?.path} (${r.data?.blueprint_type})`);
      info = await send('blueprint_get_info', { path: a.path });
      if (!info.ok) {
        error(a, `created but cannot be read back: ${info.error}`);
        a.dead = true;
        continue;
      }
    } else if (a.spec.create && normClass(info.data.parent_class) !== normClass(a.spec.create.parent)) {
      warn(a, `exists with parent ${info.data.parent_class}, spec says ${a.spec.create.parent} (not reparented)`);
    }
    a.info = info.data;
  }

  for (const a of live()) {
    const haveVars = new Map((a.info.variables ?? []).map((v) => [lc(v.name), v]));
    for (const v of a.spec.variables ?? []) {
      const wantedCategory = CATEGORY_OF_KIND[parseType(v.type).kind];
      const existing = haveVars.get(lc(v.name));
      if (existing) {
        if (wantedCategory && lc(existing.type) !== wantedCategory) {
          error(a, `variable ${v.name} exists as ${existing.type}, spec says ${v.type}`);
        }
        continue;
      }
      const text = defaultText(v.default);
      const params = { path: a.path, variable_name: v.name, variable_type: v.type };
      if (text !== undefined && text !== '') params.default_value = text;
      const r = await send('blueprint_add_variable', params);
      if (!r.ok) {
        // blueprint_get_info lists at most 50 variables, so a variable past the
        // cap looks missing; the plugin then refuses the duplicate. Keep it as is.
        if (/already exists/.test(String(r.error))) warn(a, `variable ${v.name} already exists (not listed by blueprint_get_info); kept unchanged`);
        else error(a, `add variable ${v.name}: ${r.error}`);
        continue;
      }
      const hasDefault = v.default !== undefined;
      if (r.data?.verified === true && (text !== undefined || !hasDefault)) {
        log(`  + variable ${v.name}: ${v.type}${params.default_value !== undefined ? ` = ${r.data.default_value ?? params.default_value}` : ''}`);
      } else if (hasDefault) {
        a.pendingDefaults[v.name] = v.default;
        log(`  + variable ${v.name}: ${v.type} (default via blueprint_set_defaults${r.data?.warning ? `: ${r.data.warning}` : ''})`);
      } else {
        error(a, `add variable ${v.name}: not verified (${JSON.stringify(r.data)})`);
      }
    }

    const haveComps = new Set((a.info.components ?? []).map((c) => lc(c.name)));
    for (const c of a.spec.components ?? []) {
      if (haveComps.has(lc(c.name))) continue;
      const r = await send('blueprint_add_component', { path: a.path, component_class_path: c.class, component_name: c.name });
      if (!r.ok || r.data?.verified !== true) error(a, `add component ${c.name}: ${r.error ?? JSON.stringify(r.data)}`);
      else log(`  + component ${c.name}: ${c.class}`);
    }

    const haveFns = new Set((a.info.functions ?? []).map(lc));
    for (const f of a.spec.functions ?? []) {
      const inputs = f.inputs ?? [];
      const outputs = f.outputs ?? [];
      let existing = haveFns.has(lc(f.name));
      if (!existing) {
        const r = await send('blueprint_add_function', { path: a.path, function_name: f.name, inputs, outputs, pure: f.pure === true });
        // blueprint_get_info caps its function list. Inspect the graph when the
        // plugin reports a duplicate, and verify its signature before using it.
        if (!r.ok && /already exists/i.test(String(r.error))) existing = true;
        else if (!r.ok || r.data?.verified !== true) {
          error(a, `add function ${f.name}: ${r.error ?? JSON.stringify(r.data)}`);
          continue;
        } else {
          a.fn.set(lc(f.name), { entry: r.data.entry_node_id, result: r.data.result_node_id });
          log(`  + function ${f.name}(${inputs.map((p) => p.name)}) -> (${outputs.map((p) => p.name)})${f.pure ? ' pure' : ''}`);
        }
      }
      if (existing) {
        // Hayba cannot edit a signature, so an existing function must already match.
        const g = await send('blueprint_inspect_graph', { path: a.path, graph_name: f.name });
        if (!g.ok) {
          error(a, `function ${f.name} exists but its graph cannot be read: ${g.error}`);
          continue;
        }
        const t = findTerminals(g.data.nodes, f.name);
        for (const problem of signatureProblems(t, f)) error(a, problem);
        a.fn.set(lc(f.name), { entry: t.entry?.node_id, result: t.result?.node_id });
      }
    }
  }

  for (const a of live()) {
    const r = await send('blueprint_compile', { path: a.path, save: true });
    a.skeletonCompileOk = r.ok && r.data?.ok === true;
    if (!a.skeletonCompileOk) {
      const why = r.ok ? (r.data?.errors ?? []).join(' | ') : r.error;
      if (resetGraphs) warn(a, `skeleton compile failed (graphs will be reset): ${why}`);
      else error(a, `skeleton compile failed: ${why}`);
    } else log(`  compiled ${a.name}${r.data?.saved ? ' (saved)' : ''}`);
    if (Object.keys(a.pendingDefaults).length > 0) {
      const d = await send('blueprint_set_defaults', { path: a.path, properties: a.pendingDefaults });
      if (!d.ok || d.data?.verified !== true || d.data?.failed > 0) {
        error(a, `variable defaults ${Object.keys(a.pendingDefaults).join(', ')}: ${d.error ?? `skipped=${JSON.stringify(d.data?.skipped)} verification_failed=${JSON.stringify(d.data?.verification_failed)}`}`);
      } else log(`  defaults ${Object.keys(a.pendingDefaults).join(', ')} set on the CDO`);
    }
  }

  // ── Pass 2: graphs ────────────────────────────────────────────────────────
  log(`pass 2: graphs${resetGraphs ? ' (reset)' : ''}`);
  for (const a of live()) {
    for (const gspec of a.spec.graphs ?? []) {
      const isEvent = lc(gspec.graph) === 'eventgraph';
      const g = {
        spec: gspec, name: gspec.graph, isEvent, skip: false,
        ids: {}, kinds: {}, pins: {}, links: [], defaultsExpected: Object.keys(gspec.defaults ?? {}).length, defaultsVerified: 0,
      };
      for (const [n, node] of Object.entries(gspec.nodes)) g.kinds[n] = nodeKind(node);
      a.graphs.push(g);
      const params = { path: a.path, graph_name: g.name };
      let r = await send('blueprint_inspect_graph', params);
      if (!r.ok) {
        error(a, `graph ${g.name}: ${r.error}`);
        g.skip = true;
        continue;
      }
      const terminals = isEvent ? {} : findTerminals(r.data.nodes, g.name, a.fn.get(lc(g.name)) ?? {});
      const keep = new Set([terminals.entry?.node_id, terminals.result?.node_id].filter(Boolean));
      if (!isEvent && terminals.resultCount > 1) warn(a, `graph ${g.name} has ${terminals.resultCount} return nodes; using ${terminals.result.node_id}`);
      if (resetGraphs) {
        let removed = 0;
        // The inspect reply holds at most 50 nodes: remove in rounds until the
        // reported node_count is down to the kept terminals.
        for (let round = 0; round < 10 && r.ok; round++) {
          const doomed = r.data.nodes.filter((n) => !keep.has(n.node_id));
          if (doomed.length === 0) break;
          let removedThisRound = 0;
          for (const n of doomed) {
            const rm = await send('blueprint_remove_node', { ...params, node_id: n.node_id });
            if (rm.ok && rm.data?.verified === true) { removed++; removedThisRound++; }
            else warn(a, `graph ${g.name}: could not remove "${n.title}" (${n.node_id}): ${rm.error ?? JSON.stringify(rm.data)}`);
          }
          r = await send('blueprint_inspect_graph', params);
          if (removedThisRound === 0) break;
        }
        const left = r.ok ? r.data.nodes.filter((n) => !keep.has(n.node_id)) : [];
        if (!r.ok) {
          error(a, `graph ${g.name}: cannot re-read after reset: ${r.error}`);
          g.skip = true;
          continue;
        }
        log(`  reset ${a.name}.${g.name}: removed ${removed}${left.length ? `, ${left.length} could not be removed` : ''}`);
      } else {
        // Building into a graph that already holds a build would duplicate it.
        const autoLink = (e) => e.from_node === terminals.entry?.node_id && e.to_node === terminals.result?.node_id && e.from_pin === 'then';
        const touched = new Set(r.data.edges.filter((e) => !autoLink(e)).flatMap((e) => [e.from_node, e.to_node]));
        const ghost = (n) => /^Event /.test(n.title) && !touched.has(n.node_id);
        const extra = r.data.nodes.filter((n) => !keep.has(n.node_id) && !ghost(n));
        const edges = r.data.edges.filter((e) => !autoLink(e));
        if (extra.length > 0 || edges.length > 0) {
          error(a, `graph ${g.name} already has ${extra.length} node(s) and ${edges.length} link(s); rerun with --reset-graphs to rebuild it`);
          g.skip = true;
          continue;
        }
      }
      for (const [n, kind] of Object.entries(g.kinds)) {
        if (kind === 'entry' || kind === 'result') {
          const node = kind === 'entry' ? terminals.entry : terminals.result;
          if (!node) error(a, `graph ${g.name}: no function ${kind} node found for "${n}"`);
          else g.ids[n] = node.node_id;
        }
      }
      g.layout = layoutNodes(Object.keys(gspec.nodes), gspec.links);
    }
  }

  // Events first: a custom event is only callable by name once compiled.
  for (const a of live()) {
    for (const g of a.graphs.filter((x) => !x.skip)) {
      for (const [n, node] of Object.entries(g.spec.nodes)) {
        const kind = g.kinds[n];
        if (!EVENT_KINDS.has(kind)) continue;
        const pos = { x: node.x ?? g.layout[n].x, y: node.y ?? g.layout[n].y };
        const base = { path: a.path, graph_name: g.name, ...pos };
        let r;
        if (kind === 'event') r = await send('blueprint_add_event', { ...base, event_name: node.event });
        else if (kind === 'custom_event') {
          r = await send('blueprint_add_custom_event', { ...base, event_name: node.custom_event, inputs: node.inputs ?? [] });
          if (r.ok) a.placedCustomEvents = true;
        } else r = await send('blueprint_add_bound_event', { ...base, target: node.bound_event.target, event_name: node.bound_event.event });
        if (!r.ok || r.data?.verified !== true) {
          error(a, `graph ${g.name}: node "${n}" (${kind}): ${r.error ?? JSON.stringify(r.data)}`);
          continue;
        }
        g.ids[n] = r.data.node_id;
        g.pins[r.data.node_id] = r.data.pins;
        log(`  + ${a.name}.${g.name} ${n}: ${r.data.title}${r.data.already_existed ? ' (existing node)' : ''}`);
      }
    }
  }
  for (const a of live().filter((x) => x.placedCustomEvents)) {
    const r = await send('blueprint_compile', { path: a.path, save: false });
    if (!r.ok || r.data?.ok !== true) {
      error(a, `compile after placing events failed: ${r.error ?? (r.data?.errors ?? []).join(' | ')}`);
      for (const g of a.graphs) g.skip = true;
    }
  }

  const KIND_PARAMS = {
    call: (node) => ({ node_type: 'call_function', function_name: node.call, ...(node.class ? { class_path: node.class } : {}) }),
    get: (node) => ({ node_type: 'variable_get', variable_name: node.get }),
    set: (node) => ({ node_type: 'variable_set', variable_name: node.set }),
    branch: () => ({ node_type: 'branch' }),
    sequence: (node) => ({ node_type: 'sequence', option_count: node.sequence }),
    select: (node) => ({ node_type: 'select', option_count: node.select }),
    self: () => ({ node_type: 'self' }),
    cast: (node) => ({ node_type: 'cast', class_path: node.cast }),
    create_widget: (node) => ({ node_type: 'create_widget', class_path: node.create_widget }),
    timer: () => ({ node_type: 'timer_by_function' }),
  };
  for (const a of live()) {
    for (const g of a.graphs.filter((x) => !x.skip)) {
      for (const [n, node] of Object.entries(g.spec.nodes)) {
        const kind = g.kinds[n];
        if (!(kind in KIND_PARAMS)) continue;
        const pos = { x: node.x ?? g.layout[n].x, y: node.y ?? g.layout[n].y };
        const r = await send('blueprint_add_node', { path: a.path, graph_name: g.name, ...pos, ...KIND_PARAMS[kind](node) });
        if (!r.ok || r.data?.verified === false || !r.data?.node_id) {
          error(a, `graph ${g.name}: node "${n}" (${kind}): ${r.error ?? JSON.stringify(r.data)}`);
          continue;
        }
        g.ids[n] = r.data.node_id;
        // blueprint_inspect_graph returns at most 50 nodes, so keep the pins the
        // placement reply reports; refreshPins only overwrites the nodes it sees.
        if (Array.isArray(r.data.pins)) g.pins[r.data.node_id] = r.data.pins;
        log(`  + ${a.name}.${g.name} ${n}: ${r.data.title}`);
      }
    }
  }

  // Pins as they are now (placement, class pins and compiles can rebuild them).
  const refreshPins = async (a, g) => {
    const r = await send('blueprint_inspect_graph', { path: a.path, graph_name: g.name });
    if (!r.ok) {
      error(a, `graph ${g.name}: cannot read pins: ${r.error}`);
      return false;
    }
    for (const node of r.data.nodes) g.pins[node.node_id] = node.pins;
    if (r.data._truncated) log(`  note ${a.name}.${g.name}: inspect truncated (${r.data.node_count} nodes, ${r.data.edge_count} edges); pins of unseen nodes come from placement`);
    return true;
  };

  for (const a of live()) {
    for (const g of a.graphs.filter((x) => !x.skip)) {
      if (!(await refreshPins(a, g))) continue;
      for (const [endpoint, value] of Object.entries(g.spec.defaults ?? {})) {
        const e = parseEndpoint(endpoint);
        const id = g.ids[e.node];
        if (!id) continue; // node placement already failed and was reported
        const pin = resolvePin(g.pins[id], e.pin, 'input', { cast: g.kinds[e.node] === 'cast' });
        if (pin.error) {
          error(a, `graph ${g.name}: default ${endpoint}: ${pin.error}`);
          continue;
        }
        const wanted = String(value);
        const r = await send('blueprint_set_pin_default', { path: a.path, graph_name: g.name, node_id: id, pin_name: pin.name, value: wanted });
        if (!r.ok) {
          error(a, `graph ${g.name}: default ${endpoint} = ${wanted}: ${r.error}`);
        } else if (r.data?.verified === true || sameLiteral(r.data?.applied, wanted)) {
          g.defaultsVerified++;
        } else {
          const pinType = (g.pins[id] ?? []).find((p) => p.name === pin.name)?.type;
          // A text literal is stored as FText, which the plugin's readback does not see.
          if (pinType === 'text') {
            warn(a, `graph ${g.name}: default ${endpoint} = ${wanted} set on a text pin; the plugin cannot read text literals back (applied="${r.data?.applied ?? ''}")`);
          } else error(a, `graph ${g.name}: default ${endpoint} = ${wanted} did not stick (applied="${r.data?.applied ?? ''}")`);
        }
      }
      for (const link of g.spec.links ?? []) {
        const [from, to] = link.map(parseEndpoint);
        const record = { text: `${link[0]} -> ${link[1]}`, from: null, to: null, problem: null };
        g.links.push(record);
        const fromId = g.ids[from.node];
        const toId = g.ids[to.node];
        if (!fromId || !toId) {
          record.problem = `node ${!fromId ? from.node : to.node} was not placed`;
          continue;
        }
        const fp = resolvePin(g.pins[fromId], from.pin, 'output', { cast: g.kinds[from.node] === 'cast' });
        const tp = resolvePin(g.pins[toId], to.pin, 'input', { cast: g.kinds[to.node] === 'cast' });
        if (fp.error || tp.error) {
          record.problem = [fp.error && `${from.node}: ${fp.error}`, tp.error && `${to.node}: ${tp.error}`].filter(Boolean).join('; ');
          error(a, `graph ${g.name}: link ${record.text}: ${record.problem}`);
          continue;
        }
        record.from = { id: fromId, pin: fp.name };
        record.to = { id: toId, pin: tp.name };
        const r = await send('blueprint_connect_nodes', {
          path: a.path, graph_name: g.name, from_node: fromId, from_pin: fp.name, to_node: toId, to_pin: tp.name,
        });
        if (!r.ok || r.data?.verified !== true) {
          record.problem = r.error ?? JSON.stringify(r.data);
          error(a, `graph ${g.name}: link ${record.text}: ${record.problem}`);
        }
      }
      log(`  wired ${a.name}.${g.name}: ${g.links.filter((l) => !l.problem).length}/${g.links.length} links, ${g.defaultsVerified}/${g.defaultsExpected} defaults`);
    }
  }

  // ── Pass 3: CDO defaults and the final compile ────────────────────────────
  log('pass 3: defaults and compile');
  for (const a of live()) {
    if (a.spec.cdo_defaults) {
      const r = await send('blueprint_set_defaults', { path: a.path, properties: a.spec.cdo_defaults });
      if (!r.ok || r.data?.verified !== true || r.data?.failed > 0) {
        error(a, `cdo_defaults: ${r.error ?? `skipped=${JSON.stringify(r.data?.skipped)} verification_failed=${JSON.stringify(r.data?.verification_failed)}`}`);
      } else log(`  cdo ${a.name}: ${r.data.set.join(', ')}`);
    }
  }
  for (const a of live()) {
    const r = await send('blueprint_compile', { path: a.path, save: true });
    a.compile = {
      ok: r.ok && r.data?.ok === true,
      saved: r.data?.saved === true,
      errors: r.ok ? r.data?.errors ?? [] : [r.error],
      warnings: r.data?.warnings ?? [],
    };
    if (!a.compile.ok) error(a, `compile failed: ${a.compile.errors.join(' | ')}`);
    else {
      if (!a.compile.saved) error(a, `compiled but not saved: ${r.data?.save_error ?? 'saved=false'}`);
      log(`  compiled ${a.name}: ${a.compile.errors.length} errors, ${a.compile.warnings.length} warnings${a.compile.saved ? ', saved' : ''}`);
    }
  }

  // ── Pass 4: verify by readback ────────────────────────────────────────────
  log('pass 4: verify');
  const graphReports = [];
  for (const a of assets) {
    for (const g of a.graphs) {
      const expected = Object.keys(g.spec.nodes).length;
      const report = {
        asset: a.path, graph: g.name, nodes: 0, nodes_expected: expected,
        links_expected: (g.spec.links ?? []).length, links_found: 0, missing: [],
        defaults_expected: g.defaultsExpected, defaults_verified: g.defaultsVerified,
        compile_ok: a.compile?.ok === true,
      };
      graphReports.push(report);
      if (g.skip) {
        report.missing = (g.spec.links ?? []).map((l) => `${l[0]} -> ${l[1]} (graph not built)`);
        continue;
      }
      const r = await send('blueprint_inspect_graph', { path: a.path, graph_name: g.name });
      if (!r.ok) {
        report.missing = g.links.map((l) => `${l.text} (graph unreadable: ${r.error})`);
        continue;
      }
      // blueprint_inspect_graph caps nodes and edges at 50 (reply._truncated).
      // In a truncated graph, a node or link it does not show is accepted when
      // the placement or blueprint_connect_nodes reply verified it (pass 2).
      const truncated = Boolean(r.data._truncated);
      if (truncated) report.inspect_truncated = { node_count: r.data.node_count, edge_count: r.data.edge_count };
      const present = new Set(r.data.nodes.map((n) => n.node_id));
      const placed = Object.values(g.ids).filter(Boolean).length;
      report.nodes = truncated ? Math.min(placed, r.data.node_count) : Object.values(g.ids).filter((id) => present.has(id)).length;
      const missingNodes = Object.keys(g.spec.nodes).filter((n) => !g.ids[n] || (!truncated && !present.has(g.ids[n])));
      if (missingNodes.length) report.missing_nodes = missingNodes;
      const edges = new Set(r.data.edges.map((e) => `${e.from_node}|${e.from_pin}|${e.to_node}|${e.to_pin}`));
      for (const l of g.links) {
        if (l.from && l.to && edges.has(`${l.from.id}|${l.from.pin}|${l.to.id}|${l.to.pin}`)) report.links_found++;
        else if (truncated && l.from && l.to && !l.problem) {
          report.links_found++;
          report.links_connect_verified = (report.links_connect_verified ?? 0) + 1;
        } else report.missing.push(l.problem ? `${l.text} (${l.problem})` : l.text);
      }
      if (truncated && r.data.edge_count < report.links_found) report.missing.push(`edge_count ${r.data.edge_count} < ${report.links_found} links found`);
      // A new blueprint's BeginPlay/Tick are disabled "ghost" nodes that wiring
      // enables; a disabled event compiles clean and never runs, so read it back.
      for (const [n, node] of Object.entries(g.spec.nodes)) {
        if (g.kinds[n] !== 'event' || !g.ids[n]) continue;
        if (!(g.spec.links ?? []).some((l) => parseEndpoint(l[0])?.node === n)) continue;
        const e = await send('blueprint_add_event', { path: a.path, graph_name: g.name, event_name: node.event });
        if (!e.ok || e.data?.node_id !== g.ids[n] || e.data?.enabled !== true) {
          report.missing.push(`${n} (${node.event}) is not an enabled event node: ${e.error ?? `node_id=${e.data?.node_id} enabled=${e.data?.enabled}`}`);
        } else report.events_enabled = (report.events_enabled ?? 0) + 1;
      }
    }
  }

  const assetReports = assets.map((a) => ({
    asset: a.path,
    compile_ok: a.compile?.ok === true,
    saved: a.compile?.saved === true,
    compile_errors: a.compile?.errors ?? [],
    compile_warnings: a.compile?.warnings ?? [],
    errors: a.errors,
    warnings: a.warnings,
  }));
  const ok = assetReports.every((x) => x.compile_ok && x.saved && x.errors.length === 0)
    && graphReports.every((x) => x.missing.length === 0 && x.nodes === x.nodes_expected && x.links_found === x.links_expected);
  return { ok, reset_graphs: resetGraphs, assets: assetReports, graphs: graphReports };
}

// ─── CLI ─────────────────────────────────────────────────────────────────────

const USAGE = `usage:
  node Tools/GameFlow/bpgraph.mjs check <spec.json ...>
  node Tools/GameFlow/bpgraph.mjs build [--port N] [--project DIR] [--reset-graphs] <spec.json ...>`;

function loadSpecs(files) {
  const entries = [];
  const problems = [];
  for (const file of files) {
    let text;
    try {
      text = readFileSync(file, 'utf8');
    } catch (err) {
      problems.push(`${file}: cannot read (${err.code ?? err.message})`);
      continue;
    }
    const errors = check(text);
    if (errors.length) problems.push(...errors.map((e) => `${file}: ${e}`));
    else entries.push({ file, spec: parseSpecText(text).value });
  }
  problems.push(...checkAcross(entries));
  return { entries, problems };
}

async function main(argv) {
  const [command, ...rest] = argv;
  const opts = { files: [], resetGraphs: false };
  for (let i = 0; i < rest.length; i++) {
    const arg = rest[i];
    if (arg === '--port') opts.port = Number(rest[++i]);
    else if (arg === '--project') opts.project = rest[++i];
    else if (arg === '--reset-graphs') opts.resetGraphs = true;
    else if (arg.startsWith('--')) {
      console.error(`unknown option ${arg}\n${USAGE}`);
      return 2;
    } else opts.files.push(arg);
  }
  if (!['check', 'build'].includes(command) || opts.files.length === 0 || (opts.port !== undefined && !Number.isInteger(opts.port))) {
    console.error(USAGE);
    return 2;
  }

  const { entries, problems } = loadSpecs(opts.files);
  if (command === 'check') {
    for (const p of problems) console.log(`FAIL ${p}`);
    for (const e of entries) if (!problems.some((p) => p.startsWith(`${e.file}:`))) console.log(`ok   ${e.file}`);
    return problems.length === 0 ? 0 : 1;
  }
  if (problems.length) {
    for (const p of problems) console.error(`FAIL ${p}`);
    console.error('bpgraph: specs do not pass check; nothing was sent to the editor');
    return 1;
  }

  const project = resolve(opts.project ?? join(dirname(fileURLToPath(import.meta.url)), '..', '..'));
  // Every pass compiles with save: true. Refuse before touching the editor.
  const locked = readOnlyPackages(entries.map((e) => e.spec.asset), project);
  if (locked.length) {
    for (const { asset, file } of locked) console.error(`READ-ONLY ${asset} (${file})`);
    console.error('bpgraph: a save of a read-only package crashes the editor, so nothing was sent.\n'
      + "Make each file writable first (git lfs lock <file>, the editor's Make Writable, or attrib -r), then rerun.");
    return 3;
  }
  let sharingLocked;
  try {
    sharingLocked = sharingLockedPackages(entries.map((e) => e.spec.asset), project);
  } catch (err) {
    console.error(`bpgraph: ${err.message}; nothing was sent to the editor`);
    return 3;
  }
  if (sharingLocked.length) {
    for (const { asset, file, reason } of sharingLocked) console.error(`IN USE ${asset} (${file}, ${reason})`);
    console.error('bpgraph: close the other process before saving these packages; nothing was sent to the editor.');
    return 3;
  }
  const port = opts.port ?? discoverPort(project) ?? 52342;
  const client = new HaybaClient(port);
  try {
    await client.connect();
  } catch (err) {
    console.error(`bpgraph: no Hayba plugin listening on 127.0.0.1:${port} (${err.code ?? err.message}). Is the editor running?`);
    return 2;
  }
  console.error(`bpgraph: Hayba on 127.0.0.1:${port}, ${entries.length} spec(s)`);
  const started = Date.now();
  let report;
  try {
    report = await build(entries, client, { resetGraphs: opts.resetGraphs, log: (m) => console.error(m) });
  } finally {
    client.close();
  }
  console.error(`bpgraph: ${client.calls} commands in ${((Date.now() - started) / 1000).toFixed(1)} s — ${report.ok ? 'OK' : 'FAILED'}`);
  console.log(JSON.stringify(report, null, 2));
  return report.ok ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).then((code) => process.exit(code), (err) => {
    console.error(err);
    process.exit(2);
  });
}
