// Offline tests for bpgraph.mjs: node --test Tools/GameFlow/bpgraph.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { build, check, checkAcross, parseSpecText, parseType, resolvePin, layoutNodes, findTerminals, signatureProblems, packageFile, readOnlyPackages } from './bpgraph.mjs';
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/** A spec that uses every node kind; each test breaks one thing in a copy. */
function sample() {
  return {
    asset: '/Game/SaskartaGaea/GameFlow/BPC_Sample',
    create: { parent: '/Script/Engine.ActorComponent' },
    variables: [
      { name: 'Zone', type: 'name', default: 'Safe' },
      { name: 'CheckInterval', type: 'float', default: 0.2 },
      { name: 'CheckTimer', type: 'struct:/Script/Engine.TimerHandle' },
      { name: 'Road', type: 'object:/Script/Engine.SplineComponent' },
      { name: 'Lines', type: 'array<text>' },
      { name: 'Title', type: 'object:/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Title.WBP_Saskarta_Title_C' },
    ],
    components: [{ name: 'TitleMusic', class: '/Script/Engine.AudioComponent' }],
    functions: [
      { name: 'CheckRoad', inputs: [], outputs: [], pure: false },
      { name: 'Twice', inputs: [{ name: 'In', type: 'float' }], outputs: [{ name: 'Out', type: 'float' }], pure: true },
    ],
    graphs: [
      {
        graph: 'CheckRoad',
        nodes: {
          entry: { entry: true },
          g: { get: 'Zone' },
          cmp: { call: 'EqualEqual_NameName', class: '/Script/Engine.KismetMathLibrary' },
          br: { branch: true },
          s: { set: 'Zone' },
          c: { cast: '/Game/SaskartaGaea/GameFlow/PC_Saskarta.PC_Saskarta_C' },
          owner: { call: 'GetOwner', class: '/Script/Engine.ActorComponent' },
        },
        links: [
          ['entry.then', 'br.execute'],
          ['g.Zone', 'cmp.A'],
          ['cmp.ReturnValue', 'br.Condition'],
          ['br.then', 's.execute'],
          ['br.else', 'c.execute'],
          ['owner.ReturnValue', 'c.Object'],
        ],
        defaults: { 'cmp.B': 'Warning', 's.Zone': 'Breach' },
      },
      {
        graph: 'Twice',
        nodes: {
          entry: { entry: true },
          result: { result: true },
          mul: { call: 'Multiply_DoubleDouble', class: '/Script/Engine.KismetMathLibrary' },
        },
        links: [['entry.then', 'result.execute'], ['entry.In', 'mul.A'], ['mul.ReturnValue', 'result.Out']],
        defaults: { 'mul.B': 2 },
      },
      {
        graph: 'EventGraph',
        nodes: {
          bp: { event: 'ReceiveBeginPlay' },
          tick: { custom_event: 'OnTick', inputs: [{ name: 'Amount', type: 'float' }] },
          click: { bound_event: { target: 'StartButton', event: 'OnClicked' } },
          seq: { sequence: 3 },
          sel: { select: 2 },
          me: { self: true },
          w: { create_widget: '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Title.WBP_Saskarta_Title_C', x: 900, y: 0 },
          t: { timer: true },
          mine: { call: 'CheckRoad' },
        },
        links: [
          ['bp.then', 'seq.execute'],
          ['seq.then_0', 't.execute'],
          ['seq.then_1', 'w.execute'],
          ['seq.then_2', 'mine.execute'],
          ['me.self', 't.Object'],
          ['tick.then', 'mine.execute'],
        ],
        defaults: { 't.FunctionName': 'CheckRoad', 't.Time': '0.2', 't.bLooping': true },
      },
    ],
    cdo_defaults: { PrimaryComponentTick: { bCanEverTick: false } },
  };
}

const clone = (v) => structuredClone(v);
const graph = (spec, name) => spec.graphs.find((g) => g.graph === name);
const rejects = (spec, pattern) => {
  const errors = check(spec);
  assert.ok(errors.some((e) => pattern.test(e)), `expected an error matching ${pattern}, got:\n  ${errors.join('\n  ') || '(no errors)'}`);
};

test('accepts a valid spec that uses every node kind', () => {
  assert.deepEqual(check(sample()), []);
});

test('accepts the same spec as JSON text, with comments', () => {
  const text = `// header comment\n${JSON.stringify(sample(), null, 2).replace('"asset"', '/* the package */ "asset"')}`;
  assert.deepEqual(check(text), []);
});

test('rejects an unknown node kind', () => {
  const spec = clone(sample());
  graph(spec, 'EventGraph').nodes.d = { delay: 0.5 };
  rejects(spec, /node "d": unknown node kind "delay"/);
});

test('rejects a node with two kinds', () => {
  const spec = clone(sample());
  graph(spec, 'EventGraph').nodes.d = { branch: true, self: true };
  rejects(spec, /node "d": has 2 kind keys/);
});

test('rejects a link to an undeclared node', () => {
  const spec = clone(sample());
  graph(spec, 'CheckRoad').links.push(['s.Output_Get', 'ghost.A']);
  rejects(spec, /to node "ghost" is not declared/);
});

test('rejects a link from an undeclared node', () => {
  const spec = clone(sample());
  graph(spec, 'CheckRoad').links.push(['nobody.ReturnValue', 'cmp.B']);
  rejects(spec, /from node "nobody" is not declared/);
});

test('rejects bad "node.Pin" syntax', () => {
  for (const bad of ['brexecute', 'br.', '.execute', 'br.exe.cute', 'br. execute', '1br.execute']) {
    const spec = clone(sample());
    graph(spec, 'CheckRoad').links.push(['entry.then', bad]);
    rejects(spec, new RegExp(`"${bad.replace(/[.]/g, '\\.')}" is not "node\\.Pin"`));
  }
});

test('rejects bad pin syntax in a defaults key', () => {
  const spec = clone(sample());
  graph(spec, 'EventGraph').defaults['t'] = '1';
  rejects(spec, /defaults\["t"\]: key is not "node\.Pin"/);
});

test('rejects a bad type string', () => {
  for (const [type, pattern] of [
    ['vector3', /unknown type 'vector3'/],
    ['obj:/Script/Engine.Actor', /unknown reference kind 'obj'/],
    ['object:Engine.Actor', /needs a full path/],
    ['array<float', /never closes/],
    ['array<array<int>>', /arrays of arrays/],
    ['object:/Game/UI/WBP_Title', /ends in \.Name_C/],
  ]) {
    const spec = clone(sample());
    spec.variables.push({ name: 'Bad', type });
    rejects(spec, pattern);
  }
});

test('rejects a bad type in a function signature and a custom event input', () => {
  const spec = clone(sample());
  spec.functions[1].outputs[0].type = 'flaot';
  graph(spec, 'EventGraph').nodes.tick.inputs[0].type = 'numbr';
  rejects(spec, /outputs\[0\]: unknown type 'flaot'/);
  rejects(spec, /inputs\[0\]: unknown type 'numbr'/);
});

test('rejects an entry node in the EventGraph', () => {
  const spec = clone(sample());
  graph(spec, 'EventGraph').nodes.entry = { entry: true };
  rejects(spec, /node "entry": entry nodes exist only in function graphs/);
});

test('rejects a result node when the function declares no outputs', () => {
  const spec = clone(sample());
  graph(spec, 'CheckRoad').nodes.result = { result: true };
  rejects(spec, /CheckRoad declares no outputs/);
});

test('rejects event nodes in a function graph', () => {
  const spec = clone(sample());
  graph(spec, 'Twice').nodes.go = { custom_event: 'Go' };
  rejects(spec, /custom_event nodes live in the EventGraph/);
});

test('rejects a graph for an undeclared function', () => {
  const spec = clone(sample());
  spec.graphs.push({ graph: 'Nope', nodes: { entry: { entry: true } } });
  rejects(spec, /graph Nope: not "EventGraph" and not a function declared/);
});

test('rejects duplicate names', () => {
  const spec = clone(sample());
  spec.variables.push({ name: 'zone', type: 'name' });
  spec.functions.push({ name: 'TitleMusic' });
  graph(spec, 'EventGraph').nodes.tock = { custom_event: 'ontick' };
  spec.graphs.push({ graph: 'twice', nodes: {} });
  rejects(spec, /"zone" duplicates variable "Zone"/);
  rejects(spec, /"TitleMusic" duplicates component "TitleMusic"/);
  rejects(spec, /custom event "ontick" is declared twice/);
  rejects(spec, /graph twice: listed twice/);
});

test('rejects duplicate node names that JSON.parse would silently merge', () => {
  const text = JSON.stringify(sample()).replace('"g":{"get":"Zone"}', '"g":{"get":"Zone"},"g":{"branch":true}');
  const errors = check(text);
  assert.ok(errors.some((e) => /graphs\[0\]\.nodes: duplicate key "g"/.test(e)), errors.join('\n'));
});

test('rejects duplicate parameter names and reserved ones', () => {
  const spec = clone(sample());
  spec.functions[1].outputs.push({ name: 'in', type: 'float' });
  spec.functions[0].inputs.push({ name: 'Then', type: 'bool' });
  rejects(spec, /duplicate parameter name "in"/);
  rejects(spec, /"Then" is reserved/);
});

test('rejects links that run the wrong way or double-drive a pin', () => {
  const spec = clone(sample());
  const g = graph(spec, 'CheckRoad');
  g.links.push(['br.execute', 's.execute']);
  g.links.push(['g.Zone', 'cmp.A']);
  g.links.push(['entry.then', 'c.execute']);
  g.links.push(['s.Output_Get', 'entry.then']);
  rejects(spec, /"execute" is an input pin/);
  rejects(spec, /duplicate link/);
  rejects(spec, /exec output entry\.then already drives br\.execute/);
  rejects(spec, /a entry node has no input pins/);
});

test('rejects a literal on a pin that is also linked', () => {
  const spec = clone(sample());
  graph(spec, 'CheckRoad').defaults['cmp.A'] = 'Safe';
  rejects(spec, /defaults\["cmp\.A"\]: the pin is also linked/);
});

test('rejects bad shapes and bad class paths', () => {
  rejects({ ...sample(), asset: '/Game/X/BP_Y.BP_Y' }, /asset: must be a package path/);
  rejects({ ...sample(), create: { parent: '/Game/FirstPerson/BP_FirstPersonPlayerController' } }, /create\.parent: a Blueprint class path ends in \.Name_C/);
  rejects({ ...sample(), variabels: [] }, /unknown top-level key "variabels"/);
  const spec = clone(sample());
  graph(spec, 'EventGraph').nodes.seq = { sequence: 1 };
  graph(spec, 'EventGraph').links[0] = ['bp.then', 'seq.execute'];
  rejects(spec, /"sequence" must be the number of outputs, 2\.\.32/);
  assert.match(check('{"asset": "/Game/X", }')[0], /not valid JSON: trailing comma at line 1/);
});

test('checkAcross rejects one asset built by two specs', () => {
  const errors = checkAcross([{ file: 'a.json', spec: sample() }, { file: 'b.json', spec: sample() }]);
  assert.match(errors[0], /b\.json: asset .* is also built by a\.json/);
});

test('parseType follows the Hayba grammar', () => {
  assert.deepEqual(parseType('Float'), { kind: 'real', path: '', array: false });
  assert.deepEqual(parseType(' linear_color '), { kind: 'struct', path: '/Script/CoreUObject.LinearColor', array: false });
  assert.deepEqual(parseType('array<object:/Script/Engine.Actor>'), { kind: 'object', path: '/Script/Engine.Actor', array: true });
  assert.deepEqual(parseType('enum:/Game/Enums/E_State'), { kind: 'enum', path: '/Game/Enums/E_State', array: false });
  assert.ok(parseType('').error);
});

test('parseSpecText reports line and column', () => {
  assert.throws(() => parseSpecText('{\n  "a": tru\n}'), /line 2, column 8/);
});

test('resolvePin: exact, then loose, then the cast "As" shorthand', () => {
  const cast = [
    { name: 'execute', direction: 'input' }, { name: 'Object', direction: 'input' },
    { name: 'then', direction: 'output' }, { name: 'CastFailed', direction: 'output' },
    { name: 'AsPlayer Controller', direction: 'output' }, { name: 'bSuccess', direction: 'output' },
  ];
  assert.deepEqual(resolvePin(cast, 'Object', 'input'), { name: 'Object' });
  assert.deepEqual(resolvePin(cast, 'object', 'input'), { name: 'Object' });
  assert.deepEqual(resolvePin(cast, 'AsPlayerController', 'output'), { name: 'AsPlayer Controller' });
  assert.deepEqual(resolvePin(cast, 'As', 'output', { cast: true }), { name: 'AsPlayer Controller' });
  assert.match(resolvePin(cast, 'As', 'output').error, /no output pin "As"/);
  const miss = resolvePin(cast, 'Obj', 'input', { cast: true });
  assert.match(miss.error, /its input pins are "execute", "Object"/);
  assert.match(resolvePin(cast, 'then', 'input').error, /no input pin "then"/);
});

test('layoutNodes places consumers right of their sources', () => {
  const pos = layoutNodes(['a', 'b', 'c', 'g'], [['a.then', 'b.execute'], ['b.then', 'c.execute'], ['g.V', 'c.X']]);
  assert.ok(pos.a.x < pos.b.x && pos.b.x < pos.c.x);
  assert.equal(pos.g.x, pos.b.x);
});

test('signatureProblems ignores a library function\'s hidden world context and catches real differences', () => {
  // As read live from a BlueprintFunctionLibrary's Twice(In) -> Out.
  const terminals = {
    entry: { pins: [{ name: 'then', direction: 'output' }, { name: '__WorldContext', direction: 'output' }, { name: 'In', direction: 'output' }] },
    result: { pins: [{ name: 'execute', direction: 'input' }, { name: 'Out', direction: 'input' }] },
  };
  const twice = { name: 'Twice', inputs: [{ name: 'In', type: 'float' }], outputs: [{ name: 'Out', type: 'float' }] };
  assert.deepEqual(signatureProblems(terminals, twice), []);
  assert.match(signatureProblems(terminals, { ...twice, inputs: [{ name: 'Value', type: 'float' }] })[0], /inputs \[in\], spec says \[value\]/);
  assert.match(signatureProblems(terminals, { ...twice, outputs: [] })[0], /outputs \[out\], spec says \[\]/);
  assert.match(signatureProblems({}, twice)[0], /no recognisable entry node/);
});

test('findTerminals recognises function entry and result nodes', () => {
  const nodes = [
    { node_id: 'E', title: 'Compute Respawn', pins: [{ name: 'then', direction: 'output' }, { name: 'StepCm', direction: 'output' }] },
    { node_id: 'X', title: 'Branch', pins: [{ name: 'execute', direction: 'input' }, { name: 'then', direction: 'output' }] },
    { node_id: 'R', title: 'Return Node', pins: [{ name: 'execute', direction: 'input' }, { name: 'Found', direction: 'input' }] },
  ];
  const t = findTerminals(nodes, 'ComputeRespawn');
  assert.equal(t.entry.node_id, 'E');
  assert.equal(t.result.node_id, 'R');
  assert.equal(findTerminals(nodes, 'Other', { entry: 'E' }).entry.node_id, 'E');
});

test('packageFile maps a /Game package to its .uasset under Content', () => {
  assert.equal(packageFile('/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Title', 'D:/P'),
    join('D:/P', 'Content', 'SaskartaGaea', 'GameFlow', 'UI', 'WBP_Saskarta_Title.uasset'));
});

test('build verifies functions omitted from the capped info response', async () => {
  const calls = [];
  const client = { send: async (cmd) => {
    calls.push(cmd);
    if (cmd === 'blueprint_get_info') return { ok: true, data: { functions: [] } };
    if (cmd === 'blueprint_add_function') return { ok: false, error: 'Function Back already exists' };
    if (cmd === 'blueprint_inspect_graph') return { ok: true, data: { nodes: [
      { node_id: 'entry', title: 'Back', pins: [{ name: 'then', direction: 'output' }] },
    ], edges: [] } };
    if (cmd === 'blueprint_compile') return { ok: true, data: { ok: true, saved: true } };
    throw new Error(`unexpected ${cmd}`);
  } };
  const spec = { asset: '/Game/UI/Menu', functions: [{ name: 'Back' }], graphs: [] };
  const report = await build([{ file: 'menu.json', spec }], client);
  assert.equal(report.ok, true);
  assert.ok(calls.includes('blueprint_inspect_graph'));
  spec.functions[0].inputs = [{ name: 'Changed', type: 'bool' }];
  const mismatch = await build([{ file: 'menu.json', spec }], client);
  assert.equal(mismatch.ok, false);
  assert.match(mismatch.assets[0].errors.join(), /spec says \[changed\]/);
});

test('readOnlyPackages flags an existing read-only package and passes a missing one', () => {
  const project = mkdtempSync(join(tmpdir(), 'bpgraph-ro-'));
  try {
    mkdirSync(join(project, 'Content', 'UI'), { recursive: true });
    const locked = join(project, 'Content', 'UI', 'WBP_Locked.uasset');
    const open = join(project, 'Content', 'UI', 'WBP_Open.uasset');
    writeFileSync(locked, 'x');
    writeFileSync(open, 'x');
    chmodSync(locked, 0o444); // on Windows this sets the read-only attribute
    const found = readOnlyPackages(['/Game/UI/WBP_Locked', '/Game/UI/WBP_Open', '/Game/UI/WBP_New'], project);
    assert.deepEqual(found, [{ asset: '/Game/UI/WBP_Locked', file: locked }]);
    chmodSync(locked, 0o666);
  } finally {
    rmSync(project, { recursive: true, force: true });
  }
});
