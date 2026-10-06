#!/usr/bin/env node
// gen_settings_specs: writes the Task P3 settings-menu specs from one control table.
//
//   node Tools/GameFlow/gen_settings_specs.mjs [--pc | --title-only | --apply-only]
//
// Writes, under Tools/GameFlow/specs:
//   SG_Saskarta_Display.json            SaveGame: Brightness + motion blur (no header change, R40)
//   BFL_SaskartaSettings.json           pure helpers (resolution <-> string, frame cap), display/audio apply
//   WBP_Saskarta_Settings.graph.json    the settings menu's graphs
//   WBP_Saskarta_Settings.tree.json     its designer tree (Hayba ui_build_tree input)
//   WBP_Saskarta_Pause.graph.json       the Esc pause menu's graphs
//   WBP_Saskarta_Pause.tree.json        its designer tree
//   WBP_Saskarta_Title.graph.json       the title's buttons (adds SettingsButton)
// With --pc only, it also writes PC_Saskarta.p3.json (the scoped PC spec: only the graphs P3 adds
// or changes) and patches PC_Saskarta.json (the full spec) with the same P3 additions. Other
// lanes edit both PC specs after P3 (EnterPlaying's title-radio steps, BeginIntro, the
// Pause-in-Human fix), and P3's copy of those graphs would drop that work, so a Settings
// regeneration leaves them alone (2026-09-28).
//
// The control table (CONTROLS) is the single source for the rows, the bound
// events, the handlers and the refresh functions, so a new control is one entry.
// Blueprint cannot read USaskartaGameUserSettings' properties without new
// UFUNCTIONs (R40), so reads go through the "saskarta.*" console-variable
// mirrors that ApplySaskartaSettings publishes, and writes go through
// KismetSystemLibrary's Set*PropertyByName.

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SPECS = join(HERE, 'specs');

// ─── Paths ───────────────────────────────────────────────────────────────────
const GF = '/Game/SaskartaGaea/GameFlow';
const UI = `${GF}/UI`;
const KSL = '/Script/Engine.KismetSystemLibrary';
const KML = '/Script/Engine.KismetMathLibrary';
const KSTR = '/Script/Engine.KismetStringLibrary';
const KTXT = '/Script/Engine.KismetTextLibrary';
const GSTAT = '/Script/Engine.GameplayStatics';
const GUSC = '/Script/Engine.GameUserSettings';
const SGUS = '/Script/SaskartaCore.SaskartaGameUserSettings';
const STORY = '/Script/SaskartaCore.SaskartaStorySettings';
const WIDGET = '/Script/UMG.Widget';
const USERW = '/Script/UMG.UserWidget';
const TEXTB = '/Script/UMG.TextBlock';
const SLIDER = '/Script/UMG.Slider';
const CHECK = '/Script/UMG.CheckBox';
const COMBO = '/Script/UMG.ComboBoxString';
const SWITCHER = '/Script/UMG.WidgetSwitcher';
const WBL = '/Script/UMG.WidgetBlueprintLibrary';
const MENUW = '/Script/SaskartaCore.SaskartaMenuWidget';
const PCC = `${GF}/PC_Saskarta.PC_Saskarta_C`;
const BFL = `${GF}/BFL_SaskartaSettings.BFL_SaskartaSettings_C`;
const SGD = `${GF}/SG_Saskarta_Display.SG_Saskarta_Display_C`;
const SETTINGS_W = `${UI}/WBP_Saskarta_Settings.WBP_Saskarta_Settings_C`;
const PAUSE_W = `${UI}/WBP_Saskarta_Pause.WBP_Saskarta_Pause_C`;
const MIX = '/Game/SaskartaGaea/Audio/SMix_Saskarta_Settings.SMix_Saskarta_Settings';
const MASTER_CLASS = '/Engine/EngineSounds/Master.Master';
const DISPLAY_SLOT = 'SaskartaDisplay';

// ─── Look (Task TITLE addendum 2: mock-up direction A "The stele") ───────────
// SourceArt/UI/ui-directions-mockup.html gives the proportions in cqw (1 % of the
// frame width, 19.2 px at the 1920 x 1080 design size) and the colours; the
// lettering is the user's pick, Aref Ruqaa (Bold for headings/menus, Regular for
// row labels and descriptions). Colours are converted from sRGB hex to linear,
// because FLinearColor / FSlateColor are linear.
const F_AREF = `${UI}/Fonts/F_ArefRuqaa.F_ArefRuqaa`;
const TEX = `${UI}/Textures`;
const tex = (n) => `${TEX}/${n}.${n}`;
const lin = (hex, a = 1) => {
  const c = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  return [...c.map((v) => Number((v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4).toFixed(4))), a];
};
const INK = lin('EDE5DA'); // --ink
const MUTE = lin('A99D8F'); // --mute
const GOLD = lin('E8B070'); // --gold
const SUBINK = lin('E4D9CB'); // the title's subtitle
const SCRIM = lin('0C0A08', 0.74); // settings / pause scrim
const IVORY = INK;
const TAUPE = MUTE;
const VEIL = null; // the old radiation veil is gone in direction A

// ─── The control table ───────────────────────────────────────────────────────
// kind: combo | slider | check | button
// write: how a change reaches the settings (see handlerGraph)
// read:  how refresh reads the current value (see refreshGraph)
const QUALITY = ['Low', 'Medium', 'High', 'Epic', 'Cinematic'];
const TABS = [
  {
    key: 'Display',
    rows: [
      { id: 'WindowMode', label: 'Window mode', kind: 'combo', options: ['Fullscreen', 'Windowed Fullscreen', 'Windowed'], write: { windowMode: true }, read: { windowMode: true } },
      { def: '1920x1080', id: 'Resolution', label: 'Resolution', kind: 'combo', options: ['1280x720', '1600x900', '1920x1080', '2560x1440', '3840x2160'], write: { resolution: true }, read: { resolution: true } },
      { id: 'VSync', label: 'VSync', kind: 'check', write: { gus: 'SetVSyncEnabled', pin: 'bEnable' }, read: { gusBool: 'IsVSyncEnabled' } },
      { def: '60', id: 'FrameCap', label: 'Frame rate cap', kind: 'combo', options: ['30', '45', '60'], write: { frameCap: true }, read: { frameCap: true } },
      { def: 2.2, id: 'Brightness', label: 'Brightness', kind: 'slider', min: 1.6, max: 2.8, step: 0.05, dec: 2, write: { display: 'SetBrightness', pin: 'Value' }, read: { display: 'GetBrightness', out: 'Value' } },
      { def: 90, id: 'FieldOfView', label: 'Field of view', kind: 'slider', min: 70, max: 110, step: 1, dec: 0, write: { prop: 'FieldOfView', type: 'double' }, read: { cvar: 'saskarta.fov', fallback: 90 } },
      { def: true, id: 'MotionBlur', label: 'Motion blur', kind: 'check', write: { display: 'SetMotionBlur', pin: 'bOn' }, read: { displayBool: 'GetMotionBlur', out: 'bOn' } },
    ],
  },
  {
    key: 'Upscaling',
    rows: [
      { id: 'Method', label: 'Method', kind: 'combo', options: ['TSR', 'Native'], write: { method: true }, read: { method: true } },
      { id: 'Mode', label: 'Mode', kind: 'combo', options: ['Quality', 'Balanced', 'Performance'], write: { prop: 'UpscalerMode', type: 'int' }, read: { cvarIndex: 'saskarta.upscaler.mode', fallback: 0 } },
      { def: 0.2, id: 'Sharpness', label: 'Sharpness', kind: 'slider', min: 0, max: 1, step: 0.05, dec: 2, write: { prop: 'Sharpness', type: 'double' }, read: { cvar: 'saskarta.upscaler.sharpness', fallback: 0.2 } },
      { id: 'FrameGen', label: 'Frame generation', kind: 'check', write: { prop: 'bFrameGeneration', type: 'bool' }, read: { cvarBool: 'saskarta.upscaler.framegen', fallback: 0 } },
    ],
  },
  {
    key: 'Graphics',
    rows: [
      { def: 'High', id: 'Preset', label: 'Preset', kind: 'combo', options: [...QUALITY, 'Custom'], write: { preset: true }, read: { preset: true } },
      { id: 'AutoDetect', label: 'Auto-detect', kind: 'button', text: 'RUN BENCHMARK', write: { autoDetect: true } },
      // Task PERF-AUTO: the adaptive-quality governor (USaskartaPerfGovernor) and its target.
      { def: true, id: 'AdaptiveQuality', label: 'Adaptive quality', kind: 'check', write: { prop: 'bAdaptiveQuality', type: 'bool' }, read: { cvarBool: 'saskarta.adaptive', fallback: 1 } },
      { def: '60', id: 'AdaptiveTarget', label: 'Target frame rate', kind: 'combo', options: ['30', '60', 'Display'], write: { prop: 'AdaptiveTargetMode', type: 'int' }, read: { cvarIndex: 'saskarta.adaptive.target', fallback: 1 } },
      ...[
        ['ViewDistance', 'View distance'],
        ['Shadow', 'Shadows'],
        ['GlobalIllumination', 'Global lighting'],
        ['Reflection', 'Reflections'],
        ['Texture', 'Textures'],
        ['VisualEffect', 'Effects'],
        ['PostProcessing', 'Post-processing'],
      ].map(([g, label]) => ({ id: `${g}Quality`, label, kind: 'combo', options: QUALITY, def: 'High', write: { quality: g }, read: { quality: g } })),
      // debounce: every slider step writes the value at once, but the preview waits until the slider
      // rests for 0.3 s. A foliage step changes foliage.LODDistanceScale / grass.DensityScale, and the
      // first one's callback recreates the render state of every component (an 18-27 s D3D12 stall
      // measured at PIE start, PERF-URGENT), so a drag must not apply each of its 20 steps.
      { def: 1, id: 'FoliageDensity', label: 'Foliage density', kind: 'slider', debounce: true, min: 0.25, max: 1, step: 0.05, dec: 2, write: { prop: 'FoliageDensity', type: 'double' }, read: { cvar: 'saskarta.foliage.density', fallback: 1 } },
      { def: 1, id: 'FoliageDistance', label: 'Foliage distance', kind: 'slider', debounce: true, min: 0.5, max: 1.5, step: 0.05, dec: -1, write: { prop: 'FoliageDistance', type: 'double' }, read: { cvar: 'saskarta.foliage.distance', fallback: 1 } },
      { def: 'Volumetric', id: 'Clouds', label: 'Clouds', kind: 'combo', options: ['2D layer', 'Volumetric'], write: { prop: 'CloudMode', type: 'int' }, read: { cvarIndex: 'saskarta.clouds', fallback: 1 } },
    ],
  },
  {
    key: 'Audio',
    rows: [
      ['Master', 'Master'],
      ['Ambience', 'Ambience'],
      ['Voice', 'Voice and radio'],
      ['Effects', 'Effects'],
    ].map(([n, label]) => ({ id: `${n}Volume`, label, kind: 'slider', min: 0, max: 1, step: 0.05, dec: 2, def: 1, write: { prop: `${n}Volume`, type: 'double' }, read: { cvar: `saskarta.volume.${n.toLowerCase()}`, fallback: 1 } })).concat([
      // README_Events §6: the Low Voice station (USaskartaStorySettings; each setter saves its own ini section).
      { def: true, id: 'RadioStation', label: 'Radio station', kind: 'check', write: { story: 'SetRadioStation', pin: 'bOn' }, read: { cvarBool: 'saskarta.radio', fallback: 1 } },
      { def: 0.8, id: 'StationVolume', label: 'Station volume', kind: 'slider', min: 0, max: 1, step: 0.05, dec: 2, write: { story: 'SetStationVolume', pin: 'Volume' }, read: { cvar: 'saskarta.volume.station', fallback: 0.8 } },
    ]),
  },
  {
    key: 'Accessibility',
    rows: [
      { def: true, id: 'Subtitles', label: 'Subtitles', kind: 'check', write: { prop: 'bSubtitles', type: 'bool' }, read: { cvarBool: 'saskarta.subtitles', fallback: 1 } },
      { def: 'Medium', id: 'SubtitleSize', label: 'Subtitle size', kind: 'combo', options: ['Small', 'Medium', 'Large'], write: { prop: 'SubtitleSize', type: 'int' }, read: { cvarIndex: 'saskarta.subtitles.size', fallback: 1 } },
      { id: 'ReduceFlashing', label: 'Reduce flashing', kind: 'check', write: { prop: 'bReduceFlashing', type: 'bool' }, read: { cvarBool: 'r.Saskarta.ReduceFlashing', fallback: 0, always: true } },
      // Retained for old widget/save compatibility; current subtitles show English only.
      { hidden: true, def: true, id: 'ShowSaskartan', label: 'Show Saskartan', kind: 'check', write: { story: 'SetShowSaskartan', pin: 'bOn' }, read: { cvarBool: 'saskarta.subtitles.saskartan', fallback: 1 } },
      // LANE4: the carrier camera's sensor look (M_PP_SensorCRT on PPV_Saskarta_Sensor): scanlines, grain, the
      // damaged glass. Needs USaskartaGameUserSettings.SensorFilter (int 0-3) + the saskarta.sensorfilter mirror,
      // and the apply side sets MI_PP_SensorCRT Amount 0 / 0.35 / 0.6 / 0.85 (LANE5 builds the widget).
      { def: 'Medium', id: 'SensorFilter', label: 'Sensor filter', kind: 'combo', options: ['Off', 'Low', 'Medium', 'High'], write: { prop: 'SensorFilter', type: 'int' }, read: { cvarIndex: 'saskarta.sensorfilter', fallback: 2 } },
      { def: 1, id: 'CameraShake', label: 'Camera shake', kind: 'slider', min: 0, max: 1, step: 0.05, dec: 2, write: { prop: 'CameraShake', type: 'double' }, read: { cvar: 'saskarta.camerashake', fallback: 1 } },
    ],
  },
];
// One line per row, shown under the list while the row is focused or hovered.
const DESC = {
  WindowMode: 'Fullscreen gives the steadiest frame rate. Applies after the keep-or-revert check.',
  Resolution: 'The size of the rendered image. Applies after the keep-or-revert check.',
  VSync: 'Waits for the screen before showing a frame: no tearing, a little more input delay.',
  FrameCap: 'The game never runs above 60 fps, so your GPU keeps room for a recorder or a stream. Lower it to save power and keep the fans quiet.',
  Brightness: 'Raise it until the road stays readable in the darkest dusk.',
  FieldOfView: 'How wide the carrier sees. Wider shows more of the valley.',
  MotionBlur: 'Softens fast camera turns.',
  Method: 'How the image is scaled up to your screen. TSR is the engine’s own.',
  Mode: 'Quality renders more pixels; Performance renders fewer and runs faster.',
  Sharpness: 'Crispens the upscaled image. Too much makes the grass shimmer.',
  FrameGen: 'Adds generated frames between real ones on supported cards.',
  Preset: 'Sets every quality group at once. Change one group and it reads Custom. Cinematic is for screenshots.',
  AutoDetect: 'Measures this machine and picks settings for it.',
  AdaptiveQuality: 'Lowers resolution, then detail, when the frame rate drops, and restores it when there is room.',
  AdaptiveTarget: 'The frame rate adaptive quality holds. Display follows the frame rate cap or the screen.',
  ViewDistanceQuality: 'How far the world keeps its detail.',
  ShadowQuality: 'The sharpness and reach of shadows.',
  GlobalIlluminationQuality: 'How light bounces off the ground and the mountain.',
  ReflectionQuality: 'Reflections on wet road and water.',
  TextureQuality: 'Texture detail. Lower it if your card runs out of memory.',
  VisualEffectQuality: 'Fire, embers, dust and weather effects.',
  PostProcessingQuality: 'Bloom, depth of field and the lens.',
  FoliageDensity: 'How much grass and brush grows near the road. Lower values raise the frame rate on slower cards.',
  FoliageDistance: 'How far away grass and brush still draw.',
  Clouds: 'Volumetric clouds look deeper; the 2D layer is much cheaper.',
  MasterVolume: 'Everything you hear.',
  AmbienceVolume: 'Wind, the valley and the weather.',
  VoiceVolume: 'The carrier’s voice and the radio.',
  EffectsVolume: 'Steps, the terminal and the world’s sounds.',
  ShowSaskartan: 'Shows the spoken Saskartan above the English, for the lines said in it.',
  SensorFilter: 'How strongly the carrier camera shows its age: scanlines, grain and the cracked glass at the edges.',
  RadioStation: 'Ilaawb: an old station that plays between the story’s calls.',
  StationVolume: 'How loud the station plays, under the story and the carrier.',
  Subtitles: 'Shows what the radio and the carrier say.',
  SubtitleSize: 'How large the subtitles are.',
  ReduceFlashing: 'Tones down lightning and other bright flashes.',
  CameraShake: 'How much the view shakes. Zero keeps it still.',
};
const ROWS = TABS.flatMap((t) => t.rows.map((r) => ({ ...r, tab: t.key, desc: DESC[r.id] ?? '' })));
const ctl = (r) => `${r.id}${{ combo: 'Combo', slider: 'Slider', check: 'Check', button: 'Button' }[r.kind]}`;

/** JSON in the specs' hand style: a value that fits on one line stays on one line. */
function fmt(v, indent = '') {
  const inline = (x) => {
    if (Array.isArray(x)) return x.length ? `[${x.map(inline).join(', ')}]` : '[]';
    if (x && typeof x === 'object') {
      const e = Object.entries(x);
      return e.length ? `{ ${e.map(([k, y]) => `${JSON.stringify(k)}: ${inline(y)}`).join(', ')} }` : '{}';
    }
    return JSON.stringify(x);
  };
  const one = inline(v);
  if (indent.length + one.length <= 150 || !v || typeof v !== 'object') return one;
  const next = `${indent}  `;
  if (Array.isArray(v)) return `[\n${v.map((x) => next + fmt(x, next)).join(',\n')}\n${indent}]`;
  return `{\n${Object.entries(v).map(([k, x]) => `${next}${JSON.stringify(k)}: ${fmt(x, next)}`).join(',\n')}\n${indent}}`;
}

// ─── Graph builder ───────────────────────────────────────────────────────────
class Graph {
  constructor(name) {
    this.graph = name;
    this.nodes = {};
    this.links = [];
    this.defaults = {};
    this.seq = 0;
  }
  add(id, spec) {
    if (this.nodes[id]) throw new Error(`${this.graph}: duplicate node ${id}`);
    this.nodes[id] = spec;
    return id;
  }
  /** A fresh id with a prefix. */
  id(prefix) {
    return `${prefix}${++this.seq}`;
  }
  call(fn, cls, defaults = {}, prefix = fn) {
    const id = this.add(this.id(prefix[0].toLowerCase() + prefix.slice(1)), cls ? { call: fn, class: cls } : { call: fn });
    for (const [k, v] of Object.entries(defaults)) this.def(`${id}.${k}`, v);
    return id;
  }
  get(v) {
    return this.add(this.id(`get${v}`), { get: v });
  }
  set(v) {
    return this.add(this.id(`set${v}`), { set: v });
  }
  link(a, b) {
    this.links.push([a, b]);
  }
  def(k, v) {
    this.defaults[k] = String(v);
  }
  /** Link exec: a.then (or given pin) -> b.execute, for a chain of node ids / "node.pin". */
  exec(...steps) {
    for (let i = 0; i + 1 < steps.length; i++) {
      const from = steps[i].includes('.') ? steps[i] : `${steps[i]}.then`;
      const to = steps[i + 1].includes('.') ? steps[i + 1] : `${steps[i + 1]}.execute`;
      this.link(from, to);
    }
  }
  json() {
    return { graph: this.graph, nodes: this.nodes, links: this.links, defaults: this.defaults };
  }
}

// A pure getter of a widget member (control or variable), linked into `pin`.
const wire = (g, varName, pin) => {
  const n = g.get(varName);
  g.link(`${n}.${varName}`, pin);
  return n;
};

/**
 * Exec chain with branches: `steps` holds node ids and `{ join: [pins] }`
 * markers. A node's `then` feeds the next node; a join marker replaces that
 * with its pins (a branch's two ends meeting again at the next node).
 */
function chain(g, steps) {
  let outs = [];
  steps.forEach((s, i) => {
    if (typeof s === 'object') {
      outs = s.join;
      return;
    }
    if (i > 0) for (const o of outs) g.link(o, `${s}.execute`);
    outs = [`${s}.then`];
  });
}

// ─── SG_Saskarta_Display ─────────────────────────────────────────────────────
function saveGameSpec() {
  const getB = new Graph('GetBrightness');
  getB.add('entry', { entry: true });
  getB.add('result', { result: true });
  getB.exec('entry', 'result');
  wire(getB, 'Brightness', 'result.Value');
  const getM = new Graph('GetMotionBlur');
  getM.add('entry', { entry: true });
  getM.add('result', { result: true });
  getM.exec('entry', 'result');
  wire(getM, 'bMotionBlur', 'result.bOn');
  const setB = new Graph('SetBrightness');
  setB.add('entry', { entry: true });
  setB.add('s', { set: 'Brightness' });
  setB.exec('entry', 's');
  setB.link('entry.Value', 's.Brightness');
  const setM = new Graph('SetMotionBlur');
  setM.add('entry', { entry: true });
  setM.add('s', { set: 'bMotionBlur' });
  setM.exec('entry', 's');
  setM.link('entry.bOn', 's.bMotionBlur');
  return {
    asset: `${GF}/SG_Saskarta_Display`,
    create: { parent: '/Script/Engine.SaveGame' },
    description: 'Display extras the settings class has no property for (R40: no header changes in run 3): brightness (the engine gamma, 2.2 = neutral) and motion blur. Saved to slot SaskartaDisplay by BFL_SaskartaSettings.',
    variables: [
      { name: 'Brightness', type: 'float', default: '2.2' },
      { name: 'bMotionBlur', type: 'bool', default: 'true' },
    ],
    functions: [
      { name: 'GetBrightness', inputs: [], outputs: [{ name: 'Value', type: 'float' }], pure: true },
      { name: 'GetMotionBlur', inputs: [], outputs: [{ name: 'bOn', type: 'bool' }], pure: true },
      { name: 'SetBrightness', inputs: [{ name: 'Value', type: 'float' }], outputs: [], pure: false },
      { name: 'SetMotionBlur', inputs: [{ name: 'bOn', type: 'bool' }], outputs: [], pure: false },
    ],
    graphs: [getB, getM, setB, setM].map((g) => g.json()),
  };
}

// ─── BFL_SaskartaSettings ────────────────────────────────────────────────────
function bflSpec() {
  const graphs = [];

  // LoadDisplay() -> Display: the saved slot, or a fresh object when there is none
  // (or it does not cast, e.g. a corrupt save).
  {
    const g = new Graph('LoadDisplay');
    g.add('entry', { entry: true });
    g.add('result', { result: true });
    g.add('exists', { call: 'DoesSaveGameExist', class: GSTAT });
    g.add('br', { branch: true });
    g.add('load', { call: 'LoadGameFromSlot', class: GSTAT });
    g.add('castLoaded', { cast: SGD });
    g.add('create', { call: 'CreateSaveGameObject', class: GSTAT });
    g.add('castCreated', { cast: SGD });
    g.add('valid', { call: 'IsValid', class: KSL });
    g.add('pick', { call: 'SelectObject', class: KML });
    g.add('castFinal', { cast: SGD });
    g.def('exists.SlotName', DISPLAY_SLOT);
    g.def('exists.UserIndex', 0);
    g.def('load.SlotName', DISPLAY_SLOT);
    g.def('load.UserIndex', 0);
    g.def('create.SaveGameClass', SGD);
    g.exec('entry', 'exists', 'br'); // DoesSaveGameExist is impure
    g.link('exists.ReturnValue', 'br.Condition');
    g.exec('br', 'load', 'castLoaded', 'castFinal', 'result');
    g.link('load.ReturnValue', 'castLoaded.Object');
    g.link('castLoaded.CastFailed', 'create.execute');
    g.link('br.else', 'create.execute');
    g.exec('create', 'castCreated', 'castFinal');
    g.link('create.ReturnValue', 'castCreated.Object');
    g.link('castLoaded.AsSG Saskarta Display', 'valid.Object');
    g.link('castLoaded.AsSG Saskarta Display', 'pick.A');
    g.link('castCreated.AsSG Saskarta Display', 'pick.B');
    g.link('valid.ReturnValue', 'pick.bSelectA');
    g.link('pick.ReturnValue', 'castFinal.Object');
    g.link('castFinal.AsSG Saskarta Display', 'result.Display');
    graphs.push(g);
  }
  // SaveDisplay(Display)
  {
    const g = new Graph('SaveDisplay');
    g.add('entry', { entry: true });
    g.add('save', { call: 'SaveGameToSlot', class: GSTAT });
    g.def('save.SlotName', DISPLAY_SLOT);
    g.def('save.UserIndex', 0);
    g.exec('entry', 'save');
    g.link('entry.Display', 'save.SaveGameObject');
    graphs.push(g);
  }
  // ApplyDisplay(Display): "gamma <Brightness>" and r.MotionBlur.Amount (-1 = the
  // post-process volume's own amount, 0 = off).
  {
    const g = new Graph('ApplyDisplay');
    g.add('entry', { entry: true });
    g.add('valid', { call: 'IsValid', class: KSL });
    g.add('br', { branch: true });
    g.add('gamma', { call: 'GetBrightness', class: SGD });
    g.add('gammaStr', { call: 'Conv_DoubleToString', class: KSTR });
    g.add('gammaCmd', { call: 'Concat_StrStr', class: KSTR });
    g.add('runGamma', { call: 'ExecuteConsoleCommand', class: KSL });
    g.add('blur', { call: 'GetMotionBlur', class: SGD });
    g.add('blurCmd', { call: 'SelectString', class: KML });
    g.add('runBlur', { call: 'ExecuteConsoleCommand', class: KSL });
    g.exec('entry', 'br', 'runGamma', 'runBlur');
    g.link('entry.Display', 'valid.Object');
    g.link('valid.ReturnValue', 'br.Condition');
    g.link('entry.Display', 'gamma.self');
    g.link('gamma.Value', 'gammaStr.InDouble');
    g.def('gammaCmd.A', 'gamma ');
    g.link('gammaStr.ReturnValue', 'gammaCmd.B');
    g.link('gammaCmd.ReturnValue', 'runGamma.Command');
    g.link('entry.Display', 'blur.self');
    g.def('blurCmd.A', 'r.MotionBlur.Amount -1');
    g.def('blurCmd.B', 'r.MotionBlur.Amount 0');
    g.link('blur.bOn', 'blurCmd.bPickA');
    g.link('blurCmd.ReturnValue', 'runBlur.Command');
    graphs.push(g);
  }
  // ApplyAudio(): the master volume through a sound-mix override on the engine's
  // Master sound class (every sound without its own class plays through it).
  // Voice is routed through SC_Voice with master * voice. Ambience and effects retain their existing routing.
  {
    const g = new Graph('ApplyAudio');
    g.add('entry', { entry: true });
    g.add('master', { call: 'GetConsoleVariableFloatValue', class: KSL });
    g.add('override', { call: 'SetSoundMixClassOverride', class: GSTAT });
    g.add('push', { call: 'PushSoundMixModifier', class: GSTAT });
    g.def('master.VariableName', 'saskarta.volume.master');
    g.def('override.InSoundMixModifier', MIX);
    g.def('override.InSoundClass', MASTER_CLASS);
    g.def('override.Pitch', '1.0');
    g.def('override.FadeInTime', '0.0');
    g.def('override.bApplyToChildren', 'true');
    g.def('push.InSoundMixModifier', MIX);
    g.add('voice', { call: 'GetConsoleVariableFloatValue', class: KSL });
    g.add('voiceGain', { call: 'Multiply_DoubleDouble', class: KML });
    g.add('voiceOverride', { call: 'SetSoundMixClassOverride', class: GSTAT });
    g.def('voice.VariableName', 'saskarta.volume.voice');
    g.def('voiceOverride.InSoundMixModifier', MIX);
    g.def('voiceOverride.InSoundClass', '/Game/SaskartaGaea/Audio/SC_Voice.SC_Voice');
    g.def('voiceOverride.Pitch', '1.0');
    g.def('voiceOverride.FadeInTime', '0.0');
    g.def('voiceOverride.bApplyToChildren', 'true');
    // SC_Voice is its own root class. Apply master explicitly, so no engine Master asset needs editing.
    g.exec('entry', 'master', 'override', 'voice', 'voiceOverride', 'push');
    g.link('master.ReturnValue', 'override.Volume');
    g.link('master.ReturnValue', 'voiceGain.A');
    g.link('voice.ReturnValue', 'voiceGain.B');
    g.link('voiceGain.ReturnValue', 'voiceOverride.Volume');
    graphs.push(g);
  }
  // ResolutionToString(Resolution) -> Text  ("1920x1080")
  {
    const g = new Graph('ResolutionToString');
    g.add('entry', { entry: true });
    g.add('result', { result: true });
    g.add('v', { call: 'Conv_IntPointToVector2D', class: KML });
    g.add('brk', { call: 'BreakVector2D', class: KML });
    g.add('rx', { call: 'Round', class: KML });
    g.add('ry', { call: 'Round', class: KML });
    g.add('sx', { call: 'Conv_IntToString', class: KSTR });
    g.add('sy', { call: 'Conv_IntToString', class: KSTR });
    g.add('cx', { call: 'Concat_StrStr', class: KSTR });
    g.add('cxy', { call: 'Concat_StrStr', class: KSTR });
    g.exec('entry', 'result');
    g.link('entry.Resolution', 'v.InIntPoint');
    g.link('v.ReturnValue', 'brk.InVec');
    g.link('brk.X', 'rx.A');
    g.link('brk.Y', 'ry.A');
    g.link('rx.ReturnValue', 'sx.InInt');
    g.link('ry.ReturnValue', 'sy.InInt');
    g.link('sx.ReturnValue', 'cx.A');
    g.def('cx.B', 'x');
    g.link('cx.ReturnValue', 'cxy.A');
    g.link('sy.ReturnValue', 'cxy.B');
    g.link('cxy.ReturnValue', 'result.Text');
    graphs.push(g);
  }
  // StringToResolution(Text) -> Resolution  ("2560x1440" -> (2560,1440))
  {
    const g = new Graph('StringToResolution');
    g.add('entry', { entry: true });
    g.add('result', { result: true });
    g.add('split', { call: 'Split', class: KSTR });
    g.add('dx', { call: 'Conv_StringToDouble', class: KSTR });
    g.add('dy', { call: 'Conv_StringToDouble', class: KSTR });
    g.add('mk', { call: 'MakeVector2D', class: KML });
    g.add('ip', { call: 'Conv_Vector2DToIntPoint', class: KML });
    g.exec('entry', 'result');
    g.link('entry.Text', 'split.SourceString');
    g.def('split.InStr', 'x');
    g.link('split.LeftS', 'dx.InString');
    g.link('split.RightS', 'dy.InString');
    g.link('dx.ReturnValue', 'mk.X');
    g.link('dy.ReturnValue', 'mk.Y');
    g.link('mk.ReturnValue', 'ip.InVector2D');
    g.link('ip.ReturnValue', 'result.Resolution');
    graphs.push(g);
  }
  // FrameCapToString(Limit) -> Text  (0 -> "Unlimited", 80.0 -> "80")
  {
    const g = new Graph('FrameCapToString');
    g.add('entry', { entry: true });
    g.add('result', { result: true });
    g.add('r', { call: 'Round', class: KML });
    g.add('s', { call: 'Conv_IntToString', class: KSTR });
    g.add('none', { call: 'LessEqual_IntInt', class: KML });
    g.add('pick', { call: 'SelectString', class: KML });
    g.exec('entry', 'result');
    g.link('entry.Limit', 'r.A');
    g.link('r.ReturnValue', 's.InInt');
    g.link('r.ReturnValue', 'none.A');
    g.def('none.B', 0);
    g.def('pick.A', 'Unlimited');
    g.link('s.ReturnValue', 'pick.B');
    g.link('none.ReturnValue', 'pick.bPickA');
    g.link('pick.ReturnValue', 'result.Text');
    graphs.push(g);
  }
  return {
    asset: `${GF}/BFL_SaskartaSettings`,
    create: { parent: '/Script/Engine.BlueprintFunctionLibrary' },
    description: 'Task P3 helpers shared by WBP_Saskarta_Settings and PC_Saskarta. The pure string helpers are tested from editor Python (Tools/GameFlow/tests/test_settings_bfl.py).',
    functions: [
      { name: 'LoadDisplay', inputs: [], outputs: [{ name: 'Display', type: `object:${SGD}` }], pure: false },
      { name: 'SaveDisplay', inputs: [{ name: 'Display', type: `object:${SGD}` }], outputs: [], pure: false },
      { name: 'ApplyDisplay', inputs: [{ name: 'Display', type: `object:${SGD}` }], outputs: [], pure: false },
      { name: 'ApplyAudio', inputs: [], outputs: [], pure: false },
      { name: 'ResolutionToString', inputs: [{ name: 'Resolution', type: 'struct:/Script/CoreUObject.IntPoint' }], outputs: [{ name: 'Text', type: 'string' }], pure: true },
      { name: 'StringToResolution', inputs: [{ name: 'Text', type: 'string' }], outputs: [{ name: 'Resolution', type: 'struct:/Script/CoreUObject.IntPoint' }], pure: true },
      { name: 'FrameCapToString', inputs: [{ name: 'Limit', type: 'float' }], outputs: [{ name: 'Text', type: 'string' }], pure: true },
    ],
    graphs: graphs.map((g) => g.json()),
  };
}

// ─── WBP_Saskarta_Settings graphs ────────────────────────────────────────────

/**
 * Handler On<Id>(<param>): guard on bRefreshing, write, then preview.
 *
 * Two previews (2026-09-28, "Settings is a bit broken"): a row that only writes a Saskarta
 * property (`prop`: volumes, FOV, upscaler, subtitles, sensor filter, camera shake, foliage,
 * clouds) calls PreviewLight, which publishes the Saskarta CVars, the audio mix and the FOV.
 * Only the engine settings (VSync, frame cap, quality groups, preset) call the full Preview,
 * whose ApplyNonResolutionSettings also re-applies every scalability group and makes the
 * adaptive-quality governor drop all its steps. Slider OnValueChanged fires on every step of a
 * drag (and on every held-key repeat), so the full Preview on a slider re-applied the whole
 * engine state up to 20 times per drag.
 */
function handlerGraph(r) {
  const g = new Graph(`On${r.id}`);
  g.add('entry', { entry: true });
  const notRefreshing = g.call('Not_PreBool', KML, {}, 'notRefreshing');
  wire(g, 'bRefreshing', `${notRefreshing}.A`);
  const guard = g.add('guard', { branch: true });
  g.link(`${notRefreshing}.ReturnValue`, 'guard.Condition');
  g.exec('entry', 'guard');
  const w = r.write;
  let last = 'guard'; // exec tail
  const then = (id) => {
    g.exec(last, id);
    last = id;
  };
  const settingsTo = (pin) => wire(g, 'Settings', pin);
  const gusTo = (pin) => wire(g, 'GUS', pin);
  // 'full' = Preview, 'light' = PreviewLight, 'debounce' = PreviewLight 0.3 s after the last step, false = none.
  let preview = 'full';

  if (r.kind === 'slider') {
    const show = g.call('ShowValue', null, { Decimals: r.dec }, 'showValue');
    wire(g, `${r.id}Value`, `${show}.Label`);
    g.link('entry.Value', `${show}.Value`);
    then(show);
  }
  const value = r.kind === 'slider' ? 'entry.Value' : r.kind === 'check' ? 'entry.bOn' : null;

  if (w.prop) {
    const fn = { double: 'SetDoublePropertyByName', int: 'SetIntPropertyByName', bool: 'SetBoolPropertyByName' }[w.type];
    const s = g.call(fn, KSL, { PropertyName: w.prop }, 'write');
    settingsTo(`${s}.Object`);
    if (r.kind === 'combo') {
      const idx = g.call('GetSelectedIndex', COMBO, {}, 'index');
      wire(g, ctl(r), `${idx}.self`);
      g.link(`${idx}.ReturnValue`, `${s}.Value`);
    } else g.link(value, `${s}.Value`);
    then(s);
    preview = r.debounce ? 'debounce' : 'light';
  } else if (w.story) {
    // Static setters on USaskartaStorySettings: they save and update the saskarta.* mirrors themselves.
    const s = g.call(w.story, STORY, {}, 'write');
    g.link(value, `${s}.${w.pin}`);
    then(s);
    preview = false;
  } else if (w.gus) {
    const s = g.call(w.gus, GUSC, {}, 'write');
    gusTo(`${s}.self`);
    g.link(value, `${s}.${w.pin}`);
    then(s);
  } else if (w.display) {
    const s = g.call(w.display, SGD, {}, 'write');
    wire(g, 'Display', `${s}.self`);
    g.link(value, `${s}.${w.pin}`);
    then(s);
    const apply = g.call('ApplyDisplay', BFL, {}, 'applyDisplay');
    wire(g, 'Display', `${apply}.Display`);
    then(apply);
    preview = false;
  } else if (w.windowMode) {
    // EWindowMode: 0 Fullscreen, 1 WindowedFullscreen, 2 Windowed. An int cannot
    // feed an enum pin without a conversion node, so each mode is a literal call.
    const idx = g.call('GetSelectedIndex', COMBO, {}, 'index');
    wire(g, ctl(r), `${idx}.self`);
    const modes = ['Fullscreen', 'WindowedFullscreen', 'Windowed'];
    const is0 = g.call('EqualEqual_IntInt', KML, { B: 0 }, 'is');
    const is1 = g.call('EqualEqual_IntInt', KML, { B: 1 }, 'is');
    g.link(`${idx}.ReturnValue`, `${is0}.A`);
    g.link(`${idx}.ReturnValue`, `${is1}.A`);
    const b0 = g.add('br0', { branch: true });
    const b1 = g.add('br1', { branch: true });
    g.link(`${is0}.ReturnValue`, 'br0.Condition');
    g.link(`${is1}.ReturnValue`, 'br1.Condition');
    g.exec(last, b0);
    const setters = modes.map((m) => {
      const s = g.call('SetFullscreenMode', GUSC, { InFullscreenMode: m }, `mode${m}`);
      gusTo(`${s}.self`);
      return s;
    });
    g.link('br0.then', `${setters[0]}.execute`);
    g.link('br0.else', 'br1.execute');
    g.link('br1.then', `${setters[1]}.execute`);
    g.link('br1.else', `${setters[2]}.execute`);
    last = null;
    preview = false; // applied (with the 15 s countdown) by ApplyPending
  } else if (w.resolution) {
    const conv = g.call('StringToResolution', BFL, {}, 'parse');
    g.link('entry.Item', `${conv}.Text`);
    const s = g.call('SetScreenResolution', GUSC, {}, 'write');
    gusTo(`${s}.self`);
    g.link(`${conv}.Resolution`, `${s}.Resolution`);
    then(s);
    preview = false;
  } else if (w.frameCap) {
    // The options are 30 / 45 / 60 (the C++ hard cap is 60); refresh snaps any saved value to them.
    const d = g.call('Conv_StringToDouble', KSTR, {}, 'parse');
    g.link('entry.Item', `${d}.InString`);
    const s = g.call('SetFrameRateLimit', GUSC, {}, 'write');
    gusTo(`${s}.self`);
    g.link(`${d}.ReturnValue`, `${s}.NewLimit`);
    then(s);
  } else if (w.method) {
    // Option text -> UpscalerMethod (0 TSR, 1 DLSS, 2 Native). DLSS is listed only
    // when IsDlssAvailable() (Init adds it).
    const isNative = g.call('EqualEqual_StrStr', KSTR, { B: 'Native' }, 'isNative');
    const isDlss = g.call('EqualEqual_StrStr', KSTR, { B: 'DLSS' }, 'isDlss');
    g.link('entry.Item', `${isNative}.A`);
    g.link('entry.Item', `${isDlss}.A`);
    const dl = g.call('SelectInt', KML, { A: 1, B: 0 }, 'pickDlss');
    g.link(`${isDlss}.ReturnValue`, `${dl}.bPickA`);
    const m = g.call('SelectInt', KML, { A: 2 }, 'pickNative');
    g.link(`${dl}.ReturnValue`, `${m}.B`);
    g.link(`${isNative}.ReturnValue`, `${m}.bPickA`);
    const s = g.call('SetIntPropertyByName', KSL, { PropertyName: 'UpscalerMethod' }, 'write');
    settingsTo(`${s}.Object`);
    g.link(`${m}.ReturnValue`, `${s}.Value`);
    then(s);
    const notNative = g.call('Not_PreBool', KML, {}, 'notNative');
    g.link(`${isNative}.ReturnValue`, `${notNative}.A`);
    const en = g.call('SetIsEnabled', WIDGET, {}, 'enableMode');
    wire(g, 'ModeCombo', `${en}.self`);
    g.link(`${notNative}.ReturnValue`, `${en}.bInIsEnabled`);
    then(en);
    preview = 'light';
  } else if (w.preset) {
    const idx = g.call('GetSelectedIndex', COMBO, {}, 'index');
    wire(g, ctl(r), `${idx}.self`);
    const isLevel = g.call('Less_IntInt', KML, { B: 5 }, 'isLevel');
    g.link(`${idx}.ReturnValue`, `${isLevel}.A`);
    const b = g.add('brLevel', { branch: true });
    g.link(`${isLevel}.ReturnValue`, 'brLevel.Condition');
    then(b);
    const s = g.call('SetOverallScalabilityLevel', GUSC, {}, 'write');
    gusTo(`${s}.self`);
    g.link(`${idx}.ReturnValue`, `${s}.Value`);
    g.link('brLevel.then', `${s}.execute`);
    last = s;
    // The PresetFoliage table (foliage density / distance, clouds per level) is applied by
    // USaskartaGameUserSettings::SetOverallScalabilityLevel (virtual, so this call reaches it).
    // No ApplySettings here any more (2026-09-28): it also applied a pending resolution or
    // window mode at once, without the keep-or-revert check, and saved every unapplied change,
    // so Revert / Back could no longer undo them. The menu's Apply does that.
    // Preview first: it publishes the saskarta.foliage.* mirrors that RefreshGraphics reads.
    then(g.call('Preview', null, {}, 'preview'));
    const quiet = g.add('quietOn', { set: 'bRefreshing' });
    g.def('quietOn.bRefreshing', 'true');
    then(quiet);
    const rg = g.call('RefreshGraphics', null, {}, 'refresh');
    then(rg);
    const loud = g.add('quietOff', { set: 'bRefreshing' });
    g.def('quietOff.bRefreshing', 'false');
    then(loud);
    preview = false;
    // "Custom" (index 5) changes nothing by itself.
  } else if (w.quality) {
    const idx = g.call('GetSelectedIndex', COMBO, {}, 'index');
    wire(g, ctl(r), `${idx}.self`);
    const s = g.call(`Set${w.quality}Quality`, GUSC, {}, 'write');
    gusTo(`${s}.self`);
    g.link(`${idx}.ReturnValue`, `${s}.Value`);
    then(s);
    const quiet = g.add('quietOn', { set: 'bRefreshing' });
    g.def('quietOn.bRefreshing', 'true');
    then(quiet);
    const rp = g.call('RefreshPreset', null, {}, 'refresh');
    then(rp);
    const loud = g.add('quietOff', { set: 'bRefreshing' });
    g.def('quietOff.bRefreshing', 'false');
    then(loud);
  } else if (w.autoDetect) {
    // SCALABILITY.md BP hookup 1: USaskartaGameUserSettings::RunAutoDetect gathers the specs,
    // classifies the GPU, applies the recommended preset and caps, and saves on its own.
    // Its ApplySettings would also apply an unapplied resolution / window mode pick without the
    // keep-or-revert check, so that pick is dropped first (RevertVideoMode: back to the last
    // confirmed mode). Then every tab is re-read: the detection also sets the upscaler, the
    // frame cap and VSync (Display / Upscaling), not only the Graphics rows. RefreshAll mutes
    // the handlers itself.
    const drop = g.call('RevertVideoMode', GUSC, {}, 'dropPendingMode');
    gusTo(`${drop}.self`);
    then(drop);
    const bench = g.call('RunAutoDetect', SGUS, {}, 'bench');
    settingsTo(`${bench}.self`);
    then(bench);
    then(g.call('RefreshAll', null, {}, 'refresh'));
    preview = false;
  } else throw new Error(`no write rule for ${r.id}`);

  if (preview && last) {
    if (preview === 'debounce') {
      // A non-looping timer by function name: setting it again restarts it (K2_SetTimer finds the
      // existing timer for the same object and function), so only the last step of a drag applies.
      const t = g.add('previewSoon', { timer: true });
      g.def('previewSoon.FunctionName', 'PreviewLight');
      g.def('previewSoon.Time', '0.3');
      g.def('previewSoon.bLooping', 'false');
      then(t);
    } else then(g.call(preview === 'light' ? 'PreviewLight' : 'Preview', null, {}, 'preview'));
  }
  return g;
}

const HANDLER_INPUT = {
  combo: [{ name: 'Item', type: 'string' }],
  slider: [{ name: 'Value', type: 'float' }],
  check: [{ name: 'bOn', type: 'bool' }],
  button: [],
};
const BOUND_EVENT = { combo: 'OnSelectionChanged', slider: 'OnValueChanged', check: 'OnCheckStateChanged', button: 'OnClicked' };
const EVENT_OUT = { combo: 'SelectedItem', slider: 'Value', check: 'bIsChecked', button: null };

/** Adds the read of one row to a refresh graph; returns the exec node (or null). */
function readRow(g, r) {
  const rd = r.read;
  if (!rd) return [];
  const gusTo = (pin) => wire(g, 'GUS', pin);
  const steps = [];
  // ReadSetting(Name, Fallback): the mirror cvar, or Fallback before the
  // settings class is live (R43).
  const readF = (name, fallback) => {
    const n = g.call(rd.always ? 'ReadCVar' : 'ReadSetting', null, { Name: name, Fallback: fallback }, 'read');
    return `${n}.Value`;
  };
  if (r.kind === 'slider') {
    let valuePin;
    if (rd.cvar) valuePin = readF(rd.cvar, rd.fallback);
    else if (rd.display) {
      const n = g.call(rd.display, SGD, {}, 'readDisplay');
      wire(g, 'Display', `${n}.self`);
      valuePin = `${n}.${rd.out}`;
    }
    const show = g.call('ShowSlider', null, { Decimals: r.dec }, `show${r.id}`);
    wire(g, ctl(r), `${show}.Slider`);
    wire(g, `${r.id}Value`, `${show}.Label`);
    g.link(valuePin, `${show}.Value`);
    steps.push(show);
  } else if (r.kind === 'check') {
    let boolPin;
    if (rd.gusBool) {
      const n = g.call(rd.gusBool, GUSC, {}, 'readGus');
      gusTo(`${n}.self`);
      boolPin = `${n}.ReturnValue`;
    } else if (rd.displayBool) {
      const n = g.call(rd.displayBool, SGD, {}, 'readDisplay');
      wire(g, 'Display', `${n}.self`);
      boolPin = `${n}.${rd.out}`;
    } else {
      const gt = g.call('Greater_DoubleDouble', KML, { B: '0.5' }, 'isOn');
      g.link(readF(rd.cvarBool, rd.fallback), `${gt}.A`);
      boolPin = `${gt}.ReturnValue`;
    }
    const s = g.call('SetIsChecked', CHECK, {}, `check${r.id}`);
    wire(g, ctl(r), `${s}.self`);
    g.link(boolPin, `${s}.InIsChecked`);
    steps.push(s);
  } else if (r.kind === 'combo') {
    const combo = ctl(r);
    if (rd.cvarIndex || rd.quality || rd.windowMode) {
      let idxPin;
      if (rd.cvarIndex) {
        const rn = g.call('Round', KML, {}, 'round');
        g.link(readF(rd.cvarIndex, rd.fallback), `${rn}.A`);
        idxPin = `${rn}.ReturnValue`;
      } else if (rd.quality) {
        const n = g.call(`Get${rd.quality}Quality`, GUSC, {}, 'readGus');
        gusTo(`${n}.self`);
        idxPin = `${n}.ReturnValue`;
      } else {
        const n = g.call('GetFullscreenMode', GUSC, {}, 'readGus');
        gusTo(`${n}.self`);
        const b = g.call('Conv_ByteToInt', KML, {}, 'modeIndex');
        g.link(`${n}.ReturnValue`, `${b}.InByte`);
        idxPin = `${b}.ReturnValue`;
      }
      const s = g.call('SetSelectedIndex', COMBO, {}, `select${r.id}`);
      wire(g, combo, `${s}.self`);
      g.link(idxPin, `${s}.Index`);
      steps.push(s);
    } else if (rd.resolution) {
      const n = g.call('GetScreenResolution', GUSC, {}, 'readGus');
      gusTo(`${n}.self`);
      const c = g.call('ResolutionToString', BFL, {}, 'asText');
      g.link(`${n}.ReturnValue`, `${c}.Resolution`);
      const s = g.call('SelectOrAdd', null, {}, `select${r.id}`);
      wire(g, combo, `${s}.Combo`);
      g.link(`${c}.Text`, `${s}.Option`);
      steps.push(s);
    } else if (rd.frameCap) {
      // The saved limit snapped to the listed caps, 30 / 45 / 60 (2026-09-28). The C++ turns 0
      // (uncapped, also the default of a fresh settings object) and anything above 60 into 60 when
      // it applies, and auto-detect may store a display rate such as 50. SelectOrAdd used to append
      // those as extra options ("Unlimited", "50") that the ◀ ▶ arrows could then reach.
      const n = g.call('GetFrameRateLimit', GUSC, {}, 'readGus');
      gusTo(`${n}.self`);
      const rn = g.call('Round', KML, {}, 'round');
      g.link(`${n}.ReturnValue`, `${rn}.A`);
      const upTo = (limit) => {
        const le = g.call('LessEqual_IntInt', KML, { B: limit }, 'capAtMost');
        g.link(`${rn}.ReturnValue`, `${le}.A`);
        return `${le}.ReturnValue`;
      };
      const s45 = g.call('SelectString', KML, { A: '45', B: '60' }, 'cap45');
      g.link(upTo(52), `${s45}.bPickA`);
      const s30 = g.call('SelectString', KML, { A: '30' }, 'cap30');
      g.link(`${s45}.ReturnValue`, `${s30}.B`);
      g.link(upTo(37), `${s30}.bPickA`);
      const sNone = g.call('SelectString', KML, { A: '60' }, 'capNone');
      g.link(`${s30}.ReturnValue`, `${sNone}.B`);
      g.link(upTo(0), `${sNone}.bPickA`);
      const s = g.call('SetSelectedOption', COMBO, {}, `select${r.id}`);
      wire(g, combo, `${s}.self`);
      g.link(`${sNone}.ReturnValue`, `${s}.Option`);
      steps.push(s);
    } else if (rd.method) {
      const rn = g.call('Round', KML, {}, 'round');
      g.link(readF('saskarta.upscaler.method', 0), `${rn}.A`);
      const isNative = g.call('EqualEqual_IntInt', KML, { B: 2 }, 'isNative');
      const isDlss = g.call('EqualEqual_IntInt', KML, { B: 1 }, 'isDlss');
      g.link(`${rn}.ReturnValue`, `${isNative}.A`);
      g.link(`${rn}.ReturnValue`, `${isDlss}.A`);
      const dl = g.call('SelectString', KML, { A: 'DLSS', B: 'TSR' }, 'pickDlss');
      g.link(`${isDlss}.ReturnValue`, `${dl}.bPickA`);
      const nat = g.call('SelectString', KML, { A: 'Native' }, 'pickNative');
      g.link(`${dl}.ReturnValue`, `${nat}.B`);
      g.link(`${isNative}.ReturnValue`, `${nat}.bPickA`);
      const s = g.call('SetSelectedOption', COMBO, {}, 'selectMethod');
      wire(g, combo, `${s}.self`);
      g.link(`${nat}.ReturnValue`, `${s}.Option`);
      steps.push(s);
      const notNative = g.call('Not_PreBool', KML, {}, 'notNative');
      g.link(`${isNative}.ReturnValue`, `${notNative}.A`);
      const en = g.call('SetIsEnabled', WIDGET, {}, 'enableMode');
      wire(g, 'ModeCombo', `${en}.self`);
      g.link(`${notNative}.ReturnValue`, `${en}.bInIsEnabled`);
      steps.push(en);
    } else if (rd.preset) {
      steps.push(g.call('RefreshPreset', null, {}, 'refreshPreset'));
    }
  }
  return steps;
}

function refreshGraph(name, rows) {
  const g = new Graph(name);
  g.add('entry', { entry: true });
  const steps = ['entry'];
  for (const r of rows) steps.push(...readRow(g, r));
  // SCALABILITY.md BP hookup 2: the "Detected: ..." line. GetDetectedSummary is added to
  // USaskartaGameUserSettings in the source and exists only after the next plugin build (editor
  // closed); set SASKARTA_DETECTED_SUMMARY=1 when regenerating after that build.
  if (process.env.SASKARTA_DETECTED_SUMMARY === '1' && rows.some((r) => r.id === 'AutoDetect')) {
    const sum = g.call('GetDetectedSummary', SGUS, {}, 'detectedSummary');
    wire(g, 'Settings', `${sum}.self`);
    const set = g.call('SetText', TEXTB, {}, 'setDetected');
    wire(g, 'DetectedText', `${set}.self`);
    g.link(`${sum}.ReturnValue`, `${set}.InText`);
    const vis = g.call('SetVisibility', WIDGET, { InVisibility: 'HitTestInvisible' }, 'showDetected');
    wire(g, 'DetectedText', `${vis}.self`);
    steps.push(set, vis);
  }
  g.exec(...steps);
  return g;
}

function settingsGraphs() {
  const graphs = [];
  const functions = [];
  const fn = (name, inputs = [], outputs = [], pure = false) => functions.push({ name, inputs, outputs, pure });

  // EventGraph: Construct -> Init; every control's bound event -> its handler;
  // tab buttons -> OpenTab; Apply / Revert / Back / Keep / Revert-now buttons.
  const ev = new Graph('EventGraph');
  ev.add('construct', { event: 'Construct' });
  ev.add('init', { call: 'Init' });
  ev.exec('construct', 'init');
  ev.add('destruct', { event: 'Destruct' });
  ev.add('stopFocus', { call: 'K2_ClearAndInvalidateTimerHandle', class: KSL });
  wire(ev, 'FocusTimer', 'stopFocus.Handle');
  ev.exec('destruct', 'stopFocus');
  for (const r of ROWS) {
    const e = ev.add(`on${r.id}Event`, { bound_event: { target: ctl(r), event: BOUND_EVENT[r.kind] } });
    const h = ev.add(`on${r.id}Call`, { call: `On${r.id}` });
    ev.exec(e, h);
    if (EVENT_OUT[r.kind]) ev.link(`${e}.${EVENT_OUT[r.kind]}`, `${h}.${HANDLER_INPUT[r.kind][0].name}`);
  }
  for (const t of TABS) {
    const e = ev.add(`tab${t.key}Event`, { bound_event: { target: `Tab${t.key}Button`, event: 'OnClicked' } });
    const h = ev.add(`tab${t.key}Call`, { call: 'OpenTab' });
    ev.exec(e, h);
    ev.def(`${h}.TabName`, t.key);
  }
  for (const [button, fnName] of [['ApplyButton', 'ApplyPending'], ['RevertButton', 'RevertPending'], ['BackButton', 'Back'], ['KeepButton', 'KeepResolution'], ['RevertNowButton', 'RevertResolution']]) {
    const e = ev.add(`${button}Event`, { bound_event: { target: button, event: 'OnClicked' } });
    const h = ev.add(`${button}Call`, { call: fnName });
    ev.exec(e, h);
  }
  // The ◀ ▶ arrows beside every combo.
  for (const r of ROWS.filter((x) => x.kind === 'combo')) {
    for (const [side, step] of [['Prev', -1], ['Next', 1]]) {
      const e = ev.add(`${r.id}${side}Event`, { bound_event: { target: `${r.id}${side}`, event: 'OnClicked' } });
      const h = ev.add(`${r.id}${side}Call`, { call: 'Cycle' });
      ev.exec(e, h);
      wire(ev, ctl(r), `${h}.Combo`);
      ev.def(`${h}.Step`, step);
    }
  }
  graphs.push(ev);

  // Handlers.
  for (const r of ROWS) {
    fn(`On${r.id}`, HANDLER_INPUT[r.kind]);
    graphs.push(handlerGraph(r));
  }

  // Init(): settings objects, DLSS option, display extras, first refresh, first tab.
  {
    fn('Init');
    const g = new Graph('Init');
    g.add('entry', { entry: true });
    g.add('gus', { call: 'GetGameUserSettings', class: GUSC });
    g.add('setGus', { set: 'GUS' });
    g.add('sask', { call: 'GetSaskartaSettings', class: SGUS });
    g.add('setSask', { set: 'Settings' });
    g.add('dlss', { call: 'IsDlssAvailable', class: SGUS });
    g.add('setDlss', { set: 'bDlss' });
    g.add('br', { branch: true });
    g.add('addDlss', { call: 'AddOption', class: COMBO });
    g.add('hideFrameGen', { call: 'SetVisibility', class: WIDGET });
    g.add('load', { call: 'LoadDisplay', class: BFL });
    g.add('setDisplay', { set: 'Display' });
    g.add('refresh', { call: 'RefreshAll' });
    g.add('tab', { call: 'OpenTab' });
    g.link('gus.ReturnValue', 'setGus.GUS');
    g.link('sask.ReturnValue', 'setSask.Settings');
    g.link('dlss.ReturnValue', 'setDlss.bDlss');
    g.link('setDlss.Output_Get', 'br.Condition');
    wire(g, 'MethodCombo', 'addDlss.self');
    g.def('addDlss.Option', 'DLSS');
    wire(g, 'FrameGenRow', 'hideFrameGen.self');
    g.def('hideFrameGen.InVisibility', 'Collapsed');
    g.link('load.Display', 'setDisplay.Display');
    g.def('tab.TabName', 'Display');
    g.exec('entry', 'gus', 'setGus', 'setSask', 'setDlss', 'br', 'addDlss', 'load');
    g.link('br.else', 'hideFrameGen.execute');
    g.exec('hideFrameGen', 'load');
    // Direction A: the focus poll (row glow, description line, tab follow)
    // and keyboard / gamepad focus on the first tab.
    g.add('focusTimer', { timer: true });
    g.def('focusTimer.FunctionName', 'UpdateFocus');
    g.def('focusTimer.Time', '0.05');
    g.def('focusTimer.bLooping', 'true');
    g.add('setFocusTimer', { set: 'FocusTimer' });
    g.link('focusTimer.ReturnValue', 'setFocusTimer.FocusTimer');
    g.add('focusFirst', { call: 'SetKeyboardFocus', class: WIDGET });
    wire(g, 'TabDisplayButton', 'focusFirst.self');
    g.exec('load', 'setDisplay', 'refresh', 'tab', 'focusTimer', 'setFocusTimer', 'focusFirst');
    graphs.push(g);
  }

  // Cycle(Combo, Step): the ◀ ▶ selector arrows step a combo through its
  // options (wrapping). SetSelectedIndex fires OnSelectionChanged, so the row's
  // own handler applies the value exactly as a pick from the list would.
  {
    fn('Cycle', [{ name: 'Combo', type: `object:${COMBO}` }, { name: 'Step', type: 'int' }]);
    const g = new Graph('Cycle');
    g.add('entry', { entry: true });
    g.add('count', { call: 'GetOptionCount', class: COMBO });
    g.link('entry.Combo', 'count.self');
    g.add('index', { call: 'GetSelectedIndex', class: COMBO });
    g.link('entry.Combo', 'index.self');
    g.add('plusStep', { call: 'Add_IntInt', class: KML });
    g.link('index.ReturnValue', 'plusStep.A');
    g.link('entry.Step', 'plusStep.B');
    g.add('plusCount', { call: 'Add_IntInt', class: KML });
    g.link('plusStep.ReturnValue', 'plusCount.A');
    g.link('count.ReturnValue', 'plusCount.B');
    g.add('wrap', { call: 'Percent_IntInt', class: KML });
    g.link('plusCount.ReturnValue', 'wrap.A');
    g.link('count.ReturnValue', 'wrap.B');
    g.add('select', { call: 'SetSelectedIndex', class: COMBO });
    g.link('entry.Combo', 'select.self');
    g.link('wrap.ReturnValue', 'select.Index');
    g.exec('entry', 'select');
    graphs.push(g);
  }

  // UpdateFocus(): every 50 ms. Per tab page, a row that is hovered or holds
  // the keyboard / gamepad focus lights its gold glow and writes its one-line
  // description; a tab button that receives focus opens its page; the footer
  // chips brighten when hovered or focused.
  {
    fn('UpdateFocus');
    const g = new Graph('UpdateFocus');
    g.add('entry', { entry: true });
    const steps = ['entry'];
    for (const t of TABS) steps.push(g.call(`UpdateFocus${t.key}`, null, {}, `rows${t.key}`));
    TABS.forEach((t) => {
      const has = g.call('HasKeyboardFocus', WIDGET, {}, `focus${t.key}`);
      wire(g, `Tab${t.key}Button`, `${has}.self`);
      const same = g.call('EqualEqual_NameName', KML, { B: t.key }, `open${t.key}`);
      wire(g, 'ActiveTab', `${same}.A`);
      const notSame = g.call('Not_PreBool', KML, {}, `other${t.key}`);
      g.link(`${same}.ReturnValue`, `${notSame}.A`);
      const both = g.call('BooleanAND', KML, {}, `follow${t.key}`);
      g.link(`${has}.ReturnValue`, `${both}.A`);
      g.link(`${notSame}.ReturnValue`, `${both}.B`);
      const br = g.add(g.id(`ifFollow${t.key}`), { branch: true });
      g.link(`${both}.ReturnValue`, `${br}.Condition`);
      const open = g.call('OpenTab', null, { TabName: t.key }, `openTab${t.key}`);
      g.link(`${br}.then`, `${open}.execute`);
      steps.push(`${br}`);
      // both branch outputs continue the chain
      steps.push({ join: [`${br}.else`, `${open}.then`] });
    });
    for (const b of ['Apply', 'Revert', 'Back']) {
      const hov = g.call('IsHovered', WIDGET, {}, `hover${b}`);
      wire(g, `${b}Button`, `${hov}.self`);
      const foc = g.call('HasKeyboardFocus', WIDGET, {}, `focus${b}`);
      wire(g, `${b}Button`, `${foc}.self`);
      const on = g.call('BooleanOR', KML, {}, `on${b}`);
      g.link(`${hov}.ReturnValue`, `${on}.A`);
      g.link(`${foc}.ReturnValue`, `${on}.B`);
      const a = g.call('SelectFloat', KML, { A: '1.0', B: '0.62' }, `alpha${b}`);
      g.link(`${on}.ReturnValue`, `${a}.bPickA`);
      const o = g.call('SetRenderOpacity', WIDGET, {}, `fade${b}`);
      wire(g, `${b}Button`, `${o}.self`);
      g.link(`${a}.ReturnValue`, `${o}.InOpacity`);
      steps.push(o);
    }
    chain(g, steps);
    graphs.push(g);
  }
  for (const t of TABS) {
    fn(`UpdateFocus${t.key}`);
    const g = new Graph(`UpdateFocus${t.key}`);
    g.add('entry', { entry: true });
    const steps = ['entry'];
    const focused = [];
    for (const r of t.rows.map((x) => ROWS.find((y) => y.id === x.id))) {
      const hov = g.call('IsHovered', WIDGET, {}, `hover${r.id}`);
      wire(g, `${r.id}Row`, `${hov}.self`);
      const foc = g.call('HasFocusedDescendants', WIDGET, {}, `focus${r.id}`);
      wire(g, `${r.id}Row`, `${foc}.self`);
      // One highlighted row: the focused row glows fully; a row that is only hovered shows a faint
      // 0.3 glow (hover and focus both painted full before, so two rows lit at once).
      const hv = g.call('SelectFloat', KML, { A: '0.3', B: '0.0' }, `hoverGlow${r.id}`);
      g.link(`${hov}.ReturnValue`, `${hv}.bPickA`);
      const a = g.call('SelectFloat', KML, { A: '1.0' }, `glow${r.id}`);
      g.link(`${foc}.ReturnValue`, `${a}.bPickA`);
      g.link(`${hv}.ReturnValue`, `${a}.B`);
      const o = g.call('SetRenderOpacity', WIDGET, {}, `showGlow${r.id}`);
      wire(g, `${r.id}Glow`, `${o}.self`);
      g.link(`${a}.ReturnValue`, `${o}.InOpacity`);
      // The description: a hovered row writes it first, then (second pass, below) the focused
      // row writes it again, so the keyboard / gamepad row wins over a mouse resting elsewhere
      // (before, the later row in the list won, and the line followed the mouse).
      const br = g.add(g.id(`ifHover${r.id}`), { branch: true });
      g.link(`${hov}.ReturnValue`, `${br}.Condition`);
      const say = g.call('SetText', TEXTB, { InText: r.desc }, `describe${r.id}`);
      wire(g, 'Description', `${say}.self`);
      g.link(`${br}.then`, `${say}.execute`);
      steps.push(o, br, { join: [`${br}.else`, `${say}.then`] });
      focused.push([r, foc]);
    }
    for (const [r, foc] of focused) {
      const br = g.add(g.id(`ifFocus${r.id}`), { branch: true });
      g.link(`${foc}.ReturnValue`, `${br}.Condition`);
      const say = g.call('SetText', TEXTB, { InText: r.desc }, `describeFocus${r.id}`);
      wire(g, 'Description', `${say}.self`);
      g.link(`${br}.then`, `${say}.execute`);
      steps.push(br, { join: [`${br}.else`, `${say}.then`] });
    }
    chain(g, steps);
    graphs.push(g);
  }

  // SetReturn(ReturnWidget, FocusWidget): the menu that opened this page. It
  // collapsed itself (one layer at a time); Back shows it again and gives the
  // focus back to the button that opened Settings.
  {
    fn('SetReturn', [{ name: 'ReturnWidget', type: `object:${USERW}` }, { name: 'FocusWidget', type: `object:${WIDGET}` }]);
    const g = new Graph('SetReturn');
    g.add('entry', { entry: true });
    g.add('setTo', { set: 'ReturnTo' });
    g.link('entry.ReturnWidget', 'setTo.ReturnTo');
    g.add('setFocus', { set: 'ReturnFocus' });
    g.link('entry.FocusWidget', 'setFocus.ReturnFocus');
    g.exec('entry', 'setTo', 'setFocus');
    graphs.push(g);
  }

  // RefreshAll(): publish the mirrors, then read every tab with handlers muted.
  {
    fn('RefreshAll');
    const g = new Graph('RefreshAll');
    g.add('entry', { entry: true });
    g.add('quietOn', { set: 'bRefreshing' });
    g.def('quietOn.bRefreshing', 'true');
    g.add('valid', { call: 'IsValid', class: KSL });
    wire(g, 'Settings', 'valid.Object');
    g.add('br', { branch: true });
    g.link('valid.ReturnValue', 'br.Condition');
    g.add('publish', { call: 'ApplySaskartaSettings', class: SGUS });
    wire(g, 'Settings', 'publish.self');
    const tabs = TABS.map((t) => g.add(`refresh${t.key}`, { call: `Refresh${t.key}` }));
    g.add('quietOff', { set: 'bRefreshing' });
    g.def('quietOff.bRefreshing', 'false');
    g.exec('entry', 'quietOn', 'br', 'publish', tabs[0]);
    g.link('br.else', `${tabs[0]}.execute`);
    g.exec(...tabs, 'quietOff');
    graphs.push(g);
  }
  for (const t of TABS) {
    fn(`Refresh${t.key}`);
    graphs.push(refreshGraph(`Refresh${t.key}`, t.rows));
  }
  // RefreshPreset(): the preset combo shows Custom (5) when the groups differ (-1).
  {
    fn('RefreshPreset');
    const g = new Graph('RefreshPreset');
    g.add('entry', { entry: true });
    g.add('overall', { call: 'GetOverallScalabilityLevel', class: GUSC });
    wire(g, 'GUS', 'overall.self');
    g.add('custom', { call: 'Less_IntInt', class: KML });
    g.def('custom.B', 0);
    g.add('pick', { call: 'SelectInt', class: KML });
    g.def('pick.A', 5);
    g.add('select', { call: 'SetSelectedIndex', class: COMBO });
    wire(g, 'PresetCombo', 'select.self');
    g.link('overall.ReturnValue', 'custom.A');
    g.link('overall.ReturnValue', 'pick.B');
    g.link('custom.ReturnValue', 'pick.bPickA');
    g.link('pick.ReturnValue', 'select.Index');
    g.exec('entry', 'select');
    graphs.push(g);
  }
  // ReadSetting(Name, Fallback) -> Value (pure): the mirror cvar once the
  // Saskarta settings class is live, Fallback before (R43).
  {
    fn('ReadSetting', [{ name: 'Name', type: 'string' }, { name: 'Fallback', type: 'float' }], [{ name: 'Value', type: 'float' }], true);
    const g = new Graph('ReadSetting');
    g.add('entry', { entry: true });
    g.add('result', { result: true });
    g.add('cv', { call: 'GetConsoleVariableFloatValue', class: KSL });
    g.add('valid', { call: 'IsValid', class: KSL });
    wire(g, 'Settings', 'valid.Object');
    g.add('pick', { call: 'SelectFloat', class: KML });
    g.link('entry.Name', 'cv.VariableName');
    g.link('cv.ReturnValue', 'pick.A');
    g.link('entry.Fallback', 'pick.B');
    g.link('valid.ReturnValue', 'pick.bPickA');
    g.link('pick.ReturnValue', 'result.Value');
    g.exec('entry', 'cv', 'result'); // GetConsoleVariableFloatValue is impure
    graphs.push(g);
  }
  // ReadCVar(Name, Fallback) -> Value (pure): a cvar registered at module load.
  {
    fn('ReadCVar', [{ name: 'Name', type: 'string' }, { name: 'Fallback', type: 'float' }], [{ name: 'Value', type: 'float' }], true);
    const g = new Graph('ReadCVar');
    g.add('entry', { entry: true });
    g.add('result', { result: true });
    g.add('cv', { call: 'GetConsoleVariableFloatValue', class: KSL });
    g.link('entry.Name', 'cv.VariableName');
    g.link('cv.ReturnValue', 'result.Value');
    g.exec('entry', 'cv', 'result');
    graphs.push(g);
  }
  // ShowValue(Label, Value, Decimals) and ShowSlider(Slider, Label, Value, Decimals).
  {
    fn('ShowValue', [{ name: 'Label', type: `object:${TEXTB}` }, { name: 'Value', type: 'float' }, { name: 'Decimals', type: 'int' }]);
    const g = new Graph('ShowValue');
    g.add('entry', { entry: true });
    g.add('txt', { call: 'Conv_DoubleToText', class: KTXT });
    g.add('set', { call: 'SetText', class: TEXTB });
    g.link('entry.Value', 'txt.Value');
    g.def('txt.RoundingMode', 'HalfToEven');
    g.def('txt.bAlwaysSign', 'false');
    g.def('txt.bUseGrouping', 'false');
    g.def('txt.MinimumIntegralDigits', 1);
    g.def('txt.MaximumIntegralDigits', 324);
    g.link('entry.Decimals', 'txt.MinimumFractionalDigits');
    g.link('entry.Decimals', 'txt.MaximumFractionalDigits');
    g.link('entry.Label', 'set.self');
    g.link('txt.ReturnValue', 'set.InText');
    // Decimals < 0: a percentage (the foliage distance multiplier 1.0 reads 100 %, its knob mid-track
    // of 50-150 %, so the number and the knob agree; user report).
    g.add('isPct', { call: 'Less_IntInt', class: KML });
    g.link('entry.Decimals', 'isPct.A');
    g.def('isPct.B', 0);
    g.add('ifPct', { branch: true });
    g.link('isPct.ReturnValue', 'ifPct.Condition');
    g.add('pct', { call: 'Multiply_DoubleDouble', class: KML });
    g.link('entry.Value', 'pct.A');
    g.def('pct.B', '100.0');
    g.add('pctRound', { call: 'Round', class: KML });
    g.link('pct.ReturnValue', 'pctRound.A');
    g.add('pctStr', { call: 'Conv_IntToString', class: KSTR });
    g.link('pctRound.ReturnValue', 'pctStr.InInt');
    g.add('pctCat', { call: 'Concat_StrStr', class: KSTR });
    g.link('pctStr.ReturnValue', 'pctCat.A');
    g.def('pctCat.B', ' %');
    g.add('pctTxt', { call: 'Conv_StringToText', class: KTXT });
    g.link('pctCat.ReturnValue', 'pctTxt.InString');
    g.add('setPct', { call: 'SetText', class: TEXTB });
    g.link('entry.Label', 'setPct.self');
    g.link('pctTxt.ReturnValue', 'setPct.InText');
    g.exec('entry', 'ifPct');
    g.link('ifPct.then', 'setPct.execute');
    g.link('ifPct.else', 'set.execute');
    graphs.push(g);
  }
  {
    fn('ShowSlider', [{ name: 'Slider', type: `object:${SLIDER}` }, { name: 'Label', type: `object:${TEXTB}` }, { name: 'Value', type: 'float' }, { name: 'Decimals', type: 'int' }]);
    const g = new Graph('ShowSlider');
    g.add('entry', { entry: true });
    g.add('set', { call: 'SetValue', class: SLIDER });
    g.add('show', { call: 'ShowValue' });
    g.link('entry.Slider', 'set.self');
    g.link('entry.Value', 'set.InValue');
    g.link('entry.Label', 'show.Label');
    g.link('entry.Value', 'show.Value');
    g.link('entry.Decimals', 'show.Decimals');
    g.exec('entry', 'set', 'show');
    graphs.push(g);
  }
  // SelectOrAdd(Combo, Option): selects Option, adding it first when it is not
  // listed (a desktop resolution or frame cap outside the presets).
  {
    fn('SelectOrAdd', [{ name: 'Combo', type: `object:${COMBO}` }, { name: 'Option', type: 'string' }]);
    const g = new Graph('SelectOrAdd');
    g.add('entry', { entry: true });
    g.add('find', { call: 'FindOptionIndex', class: COMBO });
    g.add('missing', { call: 'Less_IntInt', class: KML });
    g.def('missing.B', 0);
    g.add('br', { branch: true });
    g.add('add', { call: 'AddOption', class: COMBO });
    g.add('select', { call: 'SetSelectedOption', class: COMBO });
    g.link('entry.Combo', 'find.self');
    g.link('entry.Option', 'find.Option');
    g.link('find.ReturnValue', 'missing.A');
    g.link('missing.ReturnValue', 'br.Condition');
    g.link('entry.Combo', 'add.self');
    g.link('entry.Option', 'add.Option');
    g.link('entry.Combo', 'select.self');
    g.link('entry.Option', 'select.Option');
    g.exec('entry', 'br', 'add', 'select');
    g.link('br.else', 'select.execute');
    graphs.push(g);
  }
  // Preview(): live preview of everything but resolution and window mode.
  {
    fn('Preview');
    const g = new Graph('Preview');
    g.add('entry', { entry: true });
    g.add('valid', { call: 'IsValid', class: KSL });
    wire(g, 'Settings', 'valid.Object');
    g.add('br', { branch: true });
    g.link('valid.ReturnValue', 'br.Condition');
    g.add('publish', { call: 'ApplySaskartaSettings', class: SGUS });
    wire(g, 'Settings', 'publish.self');
    g.add('audio', { call: 'ApplyAudio', class: BFL });
    g.add('groups', { call: 'ApplyNonResolutionSettings', class: GUSC });
    wire(g, 'GUS', 'groups.self');
    g.add('owner', { call: 'GetOwningPlayer', class: WIDGET });
    g.add('castPC', { cast: PCC });
    g.add('fov', { call: 'ApplyPlayerFOV', class: PCC });
    g.link('owner.ReturnValue', 'castPC.Object');
    g.link('castPC.AsPC Saskarta', 'fov.self');
    g.exec('entry', 'br', 'publish', 'audio', 'groups', 'castPC', 'fov');
    g.link('br.else', 'groups.execute');
    graphs.push(g);
  }
  // PreviewLight(): the Saskarta properties only (the saskarta.* CVars and what they drive, the
  // audio mix, the FOV). No ApplyNonResolutionSettings, so the engine groups are not re-applied
  // and the governor keeps its steps. See handlerGraph.
  {
    fn('PreviewLight');
    const g = new Graph('PreviewLight');
    g.add('entry', { entry: true });
    g.add('valid', { call: 'IsValid', class: KSL });
    wire(g, 'Settings', 'valid.Object');
    g.add('br', { branch: true });
    g.link('valid.ReturnValue', 'br.Condition');
    g.add('publish', { call: 'ApplySaskartaSettings', class: SGUS });
    wire(g, 'Settings', 'publish.self');
    g.add('audio', { call: 'ApplyAudio', class: BFL });
    g.add('owner', { call: 'GetOwningPlayer', class: WIDGET });
    g.add('castPC', { cast: PCC });
    g.add('fov', { call: 'ApplyPlayerFOV', class: PCC });
    g.link('owner.ReturnValue', 'castPC.Object');
    g.link('castPC.AsPC Saskarta', 'fov.self');
    // Before the settings class is live (R43) the saskarta.* mirrors do not exist, and ApplyAudio
    // would read master volume 0: skip straight to the FOV.
    g.exec('entry', 'br', 'publish', 'audio', 'castPC', 'fov');
    g.link('br.else', 'castPC.execute');
    graphs.push(g);
  }
  // OpenTab(TabName): switcher page plus the tab labels' opacity.
  {
    fn('OpenTab', [{ name: 'TabName', type: 'name' }]);
    const g = new Graph('OpenTab');
    g.add('entry', { entry: true });
    const eqs = TABS.map((t, i) => {
      const e = g.call('EqualEqual_NameName', KML, { B: t.key }, `is${t.key}`);
      g.link('entry.TabName', `${e}.A`);
      return e;
    });
    const brs = TABS.map((t) => g.add(`br${t.key}`, { branch: true }));
    const pages = TABS.map((t, i) => {
      const p = g.call('SetActiveWidgetIndex', SWITCHER, { Index: i }, `page${t.key}`);
      wire(g, 'TabSwitcher', `${p}.self`);
      return p;
    });
    // Direction A: the active tab's label is full ink, the others 50 %, and a
    // gold bar marks the active one.
    const opac = TABS.flatMap((t, i) => {
      const sel = g.call('SelectFloat', KML, { A: '1.0', B: '0.5' }, `alpha${t.key}`);
      g.link(`${eqs[i]}.ReturnValue`, `${sel}.bPickA`);
      const o = g.call('SetRenderOpacity', WIDGET, {}, `fade${t.key}`);
      wire(g, `Tab${t.key}Label`, `${o}.self`);
      g.link(`${sel}.ReturnValue`, `${o}.InOpacity`);
      const barSel = g.call('SelectFloat', KML, { A: '1.0', B: '0.0' }, `bar${t.key}`);
      g.link(`${eqs[i]}.ReturnValue`, `${barSel}.bPickA`);
      const b = g.call('SetRenderOpacity', WIDGET, {}, `showBar${t.key}`);
      wire(g, `Tab${t.key}Bar`, `${b}.self`);
      g.link(`${barSel}.ReturnValue`, `${b}.InOpacity`);
      return [o, b];
    });
    g.add('setActive', { set: 'ActiveTab' });
    g.link('entry.TabName', 'setActive.ActiveTab');
    g.exec('entry', 'setActive', ...opac, brs[0]);
    TABS.forEach((t, i) => {
      g.link(`${eqs[i]}.ReturnValue`, `${brs[i]}.Condition`);
      g.link(`${brs[i]}.then`, `${pages[i]}.execute`);
      if (i + 1 < TABS.length) g.link(`${brs[i]}.else`, `${brs[i + 1]}.execute`);
    });
    graphs.push(g);
  }
  // ApplyPending(): apply + save everything; a resolution or window-mode change
  // starts the 15 s keep-or-revert countdown.
  {
    fn('ApplyPending');
    const g = new Graph('ApplyPending');
    g.add('entry', { entry: true });
    // A display change = the resolution or window mode differs from the last confirmed one
    // (KeepResolution confirms it, RevertResolution goes back to it). Not the engine's
    // IsFullscreenModeDirty: that compares with the viewport's live window mode, and the
    // in-editor PIE viewport is always Windowed, so every Apply in PIE opened the countdown.
    g.add('resNow', { call: 'GetScreenResolution', class: GUSC });
    g.add('resKept', { call: 'GetLastConfirmedScreenResolution', class: GUSC });
    wire(g, 'GUS', 'resNow.self');
    wire(g, 'GUS', 'resKept.self');
    g.add('resDirty', { call: 'NotEqual_IntPointIntPoint', class: KML });
    g.link('resNow.ReturnValue', 'resDirty.A');
    g.link('resKept.ReturnValue', 'resDirty.B');
    g.add('modeNow', { call: 'GetFullscreenMode', class: GUSC });
    g.add('modeKept', { call: 'GetLastConfirmedFullscreenMode', class: GUSC });
    wire(g, 'GUS', 'modeNow.self');
    wire(g, 'GUS', 'modeKept.self');
    g.add('modeNowIndex', { call: 'Conv_ByteToInt', class: KML });
    g.add('modeKeptIndex', { call: 'Conv_ByteToInt', class: KML });
    g.link('modeNow.ReturnValue', 'modeNowIndex.InByte');
    g.link('modeKept.ReturnValue', 'modeKeptIndex.InByte');
    g.add('modeDirty', { call: 'NotEqual_IntInt', class: KML });
    g.link('modeNowIndex.ReturnValue', 'modeDirty.A');
    g.link('modeKeptIndex.ReturnValue', 'modeDirty.B');
    g.add('dirty', { call: 'BooleanOR', class: KML });
    g.link('resDirty.ReturnValue', 'dirty.A');
    g.link('modeDirty.ReturnValue', 'dirty.B');
    g.add('setPending', { set: 'bResolutionPending' });
    g.link('dirty.ReturnValue', 'setPending.bResolutionPending');
    g.add('apply', { call: 'ApplySettings', class: GUSC });
    wire(g, 'GUS', 'apply.self');
    g.def('apply.bCheckForCommandLineOverrides', 'false');
    g.add('saveDisplay', { call: 'SaveDisplay', class: BFL });
    wire(g, 'Display', 'saveDisplay.Display');
    // ApplySettings already applies non-resolution settings and saves them. Only
    // the audio/FOV update remains; replaying Preview would apply all groups twice.
    g.add('preview', { call: 'PreviewLight' });
    // Show what was applied and saved: the C++ normalises some values on apply (the frame cap
    // is clamped to 60), and the rows must never show a value other than the saved one.
    g.add('refresh', { call: 'RefreshAll' });
    g.add('br', { branch: true });
    wire(g, 'bResolutionPending', 'br.Condition');
    g.add('countdown', { call: 'StartResolutionCountdown' });
    g.exec('entry', 'setPending', 'apply', 'saveDisplay', 'preview', 'refresh', 'br', 'countdown');
    graphs.push(g);
  }
  // StartResolutionCountdown(): 15 s, one tick per second, then revert unless kept.
  {
    fn('StartResolutionCountdown');
    const g = new Graph('StartResolutionCountdown');
    g.add('entry', { entry: true });
    g.add('setLeft', { set: 'CountdownLeft' });
    wire(g, 'CountdownSeconds', 'setLeft.CountdownLeft');
    g.add('show', { call: 'SetVisibility', class: WIDGET });
    wire(g, 'ConfirmOverlay', 'show.self');
    g.def('show.InVisibility', 'Visible');
    g.add('text', { call: 'UpdateCountdown' });
    g.add('timer', { timer: true });
    g.def('timer.FunctionName', 'CountdownTick');
    g.def('timer.Time', '1.0');
    g.def('timer.bLooping', 'true');
    g.add('setTimer', { set: 'CountdownTimer' });
    g.link('timer.ReturnValue', 'setTimer.CountdownTimer');
    g.exec('entry', 'setLeft', 'show', 'text', 'timer', 'setTimer');
    graphs.push(g);
  }
  {
    fn('UpdateCountdown');
    const g = new Graph('UpdateCountdown');
    g.add('entry', { entry: true });
    g.add('n', { call: 'Conv_IntToString', class: KSTR });
    wire(g, 'CountdownLeft', 'n.InInt');
    g.add('a', { call: 'Concat_StrStr', class: KSTR });
    g.def('a.A', 'REVERTING IN ');
    g.link('n.ReturnValue', 'a.B');
    g.add('b', { call: 'Concat_StrStr', class: KSTR });
    g.link('a.ReturnValue', 'b.A');
    g.def('b.B', ' S');
    g.add('t', { call: 'Conv_StringToText', class: KTXT });
    g.link('b.ReturnValue', 't.InString');
    g.add('set', { call: 'SetText', class: TEXTB });
    wire(g, 'CountdownText', 'set.self');
    g.link('t.ReturnValue', 'set.InText');
    g.exec('entry', 'set');
    graphs.push(g);
  }
  {
    fn('CountdownTick');
    const g = new Graph('CountdownTick');
    g.add('entry', { entry: true });
    g.add('dec', { call: 'Subtract_IntInt', class: KML });
    wire(g, 'CountdownLeft', 'dec.A');
    g.def('dec.B', 1);
    g.add('setLeft', { set: 'CountdownLeft' });
    g.link('dec.ReturnValue', 'setLeft.CountdownLeft');
    g.add('text', { call: 'UpdateCountdown' });
    g.add('done', { call: 'LessEqual_IntInt', class: KML });
    wire(g, 'CountdownLeft', 'done.A');
    g.def('done.B', 0);
    g.add('br', { branch: true });
    g.link('done.ReturnValue', 'br.Condition');
    g.add('revert', { call: 'RevertResolution' });
    g.exec('entry', 'setLeft', 'text', 'br', 'revert');
    graphs.push(g);
  }
  // StopCountdown(): clear the timer, zero the count, hide the overlay.
  {
    fn('StopCountdown');
    const g = new Graph('StopCountdown');
    g.add('entry', { entry: true });
    g.add('clear', { call: 'K2_ClearAndInvalidateTimerHandle', class: KSL });
    wire(g, 'CountdownTimer', 'clear.Handle');
    g.add('zero', { set: 'CountdownLeft' });
    g.def('zero.CountdownLeft', 0);
    g.add('hide', { call: 'SetVisibility', class: WIDGET });
    wire(g, 'ConfirmOverlay', 'hide.self');
    g.def('hide.InVisibility', 'Collapsed');
    g.exec('entry', 'clear', 'zero', 'hide');
    graphs.push(g);
  }
  {
    fn('KeepResolution');
    const g = new Graph('KeepResolution');
    g.add('entry', { entry: true });
    g.add('stop', { call: 'StopCountdown' });
    g.add('confirm', { call: 'ConfirmVideoMode', class: GUSC });
    wire(g, 'GUS', 'confirm.self');
    g.add('save', { call: 'SaveSettings', class: GUSC });
    wire(g, 'GUS', 'save.self');
    g.exec('entry', 'stop', 'confirm', 'save');
    graphs.push(g);
  }
  {
    fn('RevertResolution');
    const g = new Graph('RevertResolution');
    g.add('entry', { entry: true });
    g.add('stop', { call: 'StopCountdown' });
    g.add('revert', { call: 'RevertVideoMode', class: GUSC });
    wire(g, 'GUS', 'revert.self');
    g.add('apply', { call: 'ApplyResolutionSettings', class: GUSC });
    wire(g, 'GUS', 'apply.self');
    g.def('apply.bCheckForCommandLineOverrides', 'false');
    g.add('save', { call: 'SaveSettings', class: GUSC });
    wire(g, 'GUS', 'save.self');
    g.add('refresh', { call: 'RefreshAll' });
    g.exec('entry', 'stop', 'revert', 'apply', 'save', 'refresh');
    graphs.push(g);
  }
  // RevertPending(): drop unapplied changes by reloading what was last saved.
  {
    fn('RevertPending');
    const g = new Graph('RevertPending');
    g.add('entry', { entry: true });
    g.add('counting', { call: 'Greater_IntInt', class: KML });
    wire(g, 'CountdownLeft', 'counting.A');
    g.def('counting.B', 0);
    g.add('br', { branch: true });
    g.link('counting.ReturnValue', 'br.Condition');
    g.add('revertRes', { call: 'RevertResolution' });
    g.add('load', { call: 'LoadSettings', class: GUSC });
    wire(g, 'GUS', 'load.self');
    g.def('load.bForceReload', 'true');
    g.add('loadDisplay', { call: 'LoadDisplay', class: BFL });
    g.add('setDisplay', { set: 'Display' });
    g.link('loadDisplay.Display', 'setDisplay.Display');
    g.add('applyDisplay', { call: 'ApplyDisplay', class: BFL });
    wire(g, 'Display', 'applyDisplay.Display');
    g.add('preview', { call: 'Preview' });
    g.add('refresh', { call: 'RefreshAll' });
    g.exec('entry', 'br', 'revertRes', 'load', 'loadDisplay', 'setDisplay', 'applyDisplay', 'preview', 'refresh');
    g.link('br.else', 'load.execute');
    graphs.push(g);
  }
  {
    fn('Back');
    const g = new Graph('Back');
    g.add('entry', { entry: true });
    // Unapplied changes: ask "Apply changes?" first, whichever way Back was reached (the footer's
    // Back clicked or pressed, the pause menu's Esc). Before, only Esc from the tab list asked
    // and the footer's Back discarded silently. The C++ parent (USaskartaMenuWidget) owns the
    // dirty flag and the prompt; its Discard / Apply clear the flag before they call Back again.
    // Without a prompt in the tree ShowApplyPrompt returns false, and Back reverts and leaves.
    g.add('askDirty', { call: 'HasUnappliedChanges', class: MENUW });
    g.add('ifDirty', { branch: true });
    g.link('askDirty.ReturnValue', 'ifDirty.Condition');
    g.add('prompt', { call: 'ShowApplyPrompt', class: MENUW });
    g.add('ifPrompt', { branch: true });
    g.link('prompt.ReturnValue', 'ifPrompt.Condition');
    g.exec('entry', 'askDirty', 'ifDirty', 'prompt', 'ifPrompt');
    g.link('ifDirty.else', 'revert.execute');
    g.link('ifPrompt.else', 'revert.execute');
    g.add('revert', { call: 'RevertPending' });
    g.add('stopFocus', { call: 'K2_ClearAndInvalidateTimerHandle', class: KSL });
    wire(g, 'FocusTimer', 'stopFocus.Handle');
    g.add('remove', { call: 'RemoveFromParent', class: WIDGET });
    // One layer at a time: show the opener again and give the focus back.
    g.add('hasReturn', { call: 'IsValid', class: KSL });
    wire(g, 'ReturnTo', 'hasReturn.Object');
    g.add('ifReturn', { branch: true });
    g.link('hasReturn.ReturnValue', 'ifReturn.Condition');
    g.add('show', { call: 'SetVisibility', class: WIDGET });
    wire(g, 'ReturnTo', 'show.self');
    g.def('show.InVisibility', 'SelfHitTestInvisible');
    g.add('hasFocus', { call: 'IsValid', class: KSL });
    wire(g, 'ReturnFocus', 'hasFocus.Object');
    g.add('ifFocus', { branch: true });
    g.link('hasFocus.ReturnValue', 'ifFocus.Condition');
    g.add('refocus', { call: 'SetKeyboardFocus', class: WIDGET });
    wire(g, 'ReturnFocus', 'refocus.self');
    g.exec('revert', 'stopFocus', 'remove', 'ifReturn', 'show', 'ifFocus', 'refocus');
    g.link('ifReturn.else', 'ifFocus.execute');
    graphs.push(g);
  }

  const variables = [
    { name: 'GUS', type: `object:${GUSC}` },
    { name: 'Settings', type: `object:${SGUS}` },
    { name: 'Display', type: `object:${SGD}` },
    { name: 'bDlss', type: 'bool', default: 'false' },
    { name: 'bRefreshing', type: 'bool', default: 'false' },
    { name: 'bResolutionPending', type: 'bool', default: 'false' },
    { name: 'CountdownSeconds', type: 'int', default: '15' },
    { name: 'CountdownLeft', type: 'int', default: '0' },
    { name: 'CountdownTimer', type: 'struct:/Script/Engine.TimerHandle' },
    { name: 'FocusTimer', type: 'struct:/Script/Engine.TimerHandle' },
    { name: 'ActiveTab', type: 'name', default: 'Display' },
    { name: 'ReturnTo', type: `object:${USERW}` },
    { name: 'ReturnFocus', type: `object:${WIDGET}` },
  ];
  return {
    asset: `${UI}/WBP_Saskarta_Settings`,
    description: 'Task P3 settings menu. Generated by Tools/GameFlow/gen_settings_specs.mjs from its control table; do not edit by hand. The designer tree is WBP_Saskarta_Settings.tree.json (Hayba ui_build_tree).',
    variables,
    functions,
    graphs: graphs.map((g) => g.json()),
    cdo_defaults: { bIsFocusable: true, bAutoRegister: true, PollInterval: 0.05, DesiredFocusWidget: { WidgetName: 'TabDisplayButton' } },
  };
}

/**
 * Direction A menu focus, shared by the title and the pause menu. Each entry
 * `n` is a `${n}Button` holding a `${n}Mark` (the gold focus line) and a
 * `${n}Label`. Hovering a button gives it the keyboard focus, so mouse, keys
 * and gamepad share one focus; a 50 ms timer shows the focused entry in full
 * ink with its mark and the others at 60 %. Adds the events to `ev` and
 * returns the UpdateMenuFocus graph.
 */
function menuFocus(ev, names) {
  ev.add('menuConstruct', { event: 'Construct' });
  ev.add('menuTimer', { timer: true });
  ev.def('menuTimer.FunctionName', 'UpdateMenuFocus');
  ev.def('menuTimer.Time', '0.05');
  ev.def('menuTimer.bLooping', 'true');
  ev.add('setMenuTimer', { set: 'MenuFocusTimer' });
  ev.link('menuTimer.ReturnValue', 'setMenuTimer.MenuFocusTimer');
  ev.exec('menuConstruct', 'menuTimer', 'setMenuTimer');
  ev.add('menuDestruct', { event: 'Destruct' });
  ev.add('menuStop', { call: 'K2_ClearAndInvalidateTimerHandle', class: KSL });
  wire(ev, 'MenuFocusTimer', 'menuStop.Handle');
  ev.exec('menuDestruct', 'menuStop');
  for (const n of names) {
    ev.add(`${n}Hovered`, { bound_event: { target: `${n}Button`, event: 'OnHovered' } });
    ev.add(`${n}TakeFocus`, { call: 'SetKeyboardFocus', class: WIDGET });
    wire(ev, `${n}Button`, `${n}TakeFocus.self`);
    ev.exec(`${n}Hovered`, `${n}TakeFocus`);
  }
  const g = new Graph('UpdateMenuFocus');
  g.add('entry', { entry: true });
  const steps = ['entry'];
  for (const n of names) {
    const has = g.call('HasKeyboardFocus', WIDGET, {}, `focus${n}`);
    wire(g, `${n}Button`, `${has}.self`);
    const a = g.call('SelectFloat', KML, { A: '1.0', B: '0.6' }, `ink${n}`);
    g.link(`${has}.ReturnValue`, `${a}.bPickA`);
    const o = g.call('SetRenderOpacity', WIDGET, {}, `fade${n}`);
    wire(g, `${n}Label`, `${o}.self`);
    g.link(`${a}.ReturnValue`, `${o}.InOpacity`);
    const m = g.call('SelectFloat', KML, { A: '1.0', B: '0.0' }, `mark${n}`);
    g.link(`${has}.ReturnValue`, `${m}.bPickA`);
    const s = g.call('SetRenderOpacity', WIDGET, {}, `showMark${n}`);
    wire(g, `${n}Mark`, `${s}.self`);
    g.link(`${m}.ReturnValue`, `${s}.InOpacity`);
    steps.push(o, s);
  }
  chain(g, steps);
  return g;
}

// ─── WBP_Saskarta_Pause graphs ───────────────────────────────────────────────
function pauseGraphs() {
  const ev = new Graph('EventGraph');
  ev.add('resumeClicked', { bound_event: { target: 'ResumeButton', event: 'OnClicked' } });
  ev.add('resumeOwner', { call: 'GetOwningPlayer', class: WIDGET });
  ev.add('resumeCast', { cast: PCC });
  ev.add('resume', { call: 'ClosePause', class: PCC });
  ev.exec('resumeClicked', 'resumeCast', 'resume');
  ev.link('resumeOwner.ReturnValue', 'resumeCast.Object');
  ev.link('resumeCast.AsPC Saskarta', 'resume.self');
  ev.add('settingsClicked', { bound_event: { target: 'SettingsButton', event: 'OnClicked' } });
  ev.add('openSettings', { call: 'OpenSettings' });
  ev.exec('settingsClicked', 'openSettings');
  ev.add('quitClicked', { bound_event: { target: 'QuitButton', event: 'OnClicked' } });
  ev.add('quitOwner', { call: 'GetOwningPlayer', class: WIDGET });
  ev.add('quitCast', { cast: PCC });
  ev.add('quit', { call: 'QuitToTitle', class: PCC });
  ev.exec('quitClicked', 'quitCast', 'quit');
  ev.link('quitOwner.ReturnValue', 'quitCast.Object');
  ev.link('quitCast.AsPC Saskarta', 'quit.self');

  const open = new Graph('OpenSettings');
  open.add('entry', { entry: true });
  open.add('owner', { call: 'GetOwningPlayer', class: WIDGET });
  open.add('create', { create_widget: SETTINGS_W });
  open.add('store', { set: 'SettingsWidget' });
  open.add('show', { call: 'AddToViewport', class: USERW });
  open.def('show.ZOrder', 400);
  open.link('owner.ReturnValue', 'create.OwningPlayer');
  open.link('create.ReturnValue', 'store.SettingsWidget');
  open.link('store.Output_Get', 'show.self');
  // One layer at a time: the pause panel collapses while Settings is open.
  open.add('hide', { call: 'SetVisibility', class: WIDGET });
  open.def('hide.InVisibility', 'Collapsed');
  open.add('me', { self: true });
  open.add('setReturn', { call: 'SetReturn', class: SETTINGS_W });
  open.link('store.Output_Get', 'setReturn.self');
  open.link('me.self', 'setReturn.ReturnWidget');
  wire(open, 'SettingsButton', 'setReturn.FocusWidget');
  open.exec('entry', 'hide', 'create', 'store', 'setReturn', 'show');
  const menu = menuFocus(ev, ['Resume', 'Settings', 'Quit']);
  // Radio (README_Radio Part D): PC_Saskarta adds the menu on OpenPause and removes it on
  // ClosePause, so Construct/Destruct are the open/close. The station pauses every sound with it.
  const STATION = '/Script/SaskartaCore.SaskartaRadioStation';
  for (const [tag, after, paused] of [['radioOpen', 'setMenuTimer', 'true'], ['radioClose', 'menuStop', 'false']]) {
    ev.add(`${tag}Me`, { self: true });
    ev.add(`${tag}Station`, { call: 'GetRadioStation', class: STATION });
    ev.link(`${tag}Me.self`, `${tag}Station.WorldContextObject`);
    ev.add(`${tag}Valid`, { call: 'IsValid', class: KSL });
    ev.link(`${tag}Station.ReturnValue`, `${tag}Valid.Object`);
    ev.add(`${tag}If`, { branch: true });
    ev.link(`${tag}Valid.ReturnValue`, `${tag}If.Condition`);
    ev.add(`${tag}Notify`, { call: 'NotifyPaused', class: STATION });
    ev.link(`${tag}Station.ReturnValue`, `${tag}Notify.self`);
    ev.def(`${tag}Notify.bPaused`, paused);
    ev.exec(after, `${tag}If`, `${tag}Notify`);
  }

  // HandleEscape(): Esc while paused closes the settings page if it is open
  // (Back reverts unapplied changes), otherwise resumes.
  const esc = new Graph('HandleEscape');
  esc.add('entry', { entry: true });
  esc.add('valid', { call: 'IsValid', class: KSL });
  wire(esc, 'SettingsWidget', 'valid.Object');
  esc.add('br', { branch: true });
  esc.link('valid.ReturnValue', 'br.Condition');
  esc.add('inView', { call: 'IsInViewport', class: WIDGET });
  wire(esc, 'SettingsWidget', 'inView.self');
  esc.add('br2', { branch: true });
  esc.link('inView.ReturnValue', 'br2.Condition');
  esc.add('back', { call: 'Back', class: SETTINGS_W });
  wire(esc, 'SettingsWidget', 'back.self');
  esc.add('owner', { call: 'GetOwningPlayer', class: WIDGET });
  esc.add('cast', { cast: PCC });
  esc.add('resume', { call: 'ClosePause', class: PCC });
  esc.link('owner.ReturnValue', 'cast.Object');
  esc.link('cast.AsPC Saskarta', 'resume.self');
  esc.exec('entry', 'br', 'br2', 'back');
  esc.link('br.else', 'cast.execute');
  esc.link('br2.else', 'cast.execute');
  esc.exec('cast', 'resume');

  return {
    asset: `${UI}/WBP_Saskarta_Pause`,
    description: 'Task P3 Esc pause menu: Resume, Settings, Quit to title. OpenPause accepts Playing or Human; ClosePause restores PausedFrom.',
    variables: [{ name: 'SettingsWidget', type: `object:${SETTINGS_W}` }, { name: 'MenuFocusTimer', type: 'struct:/Script/Engine.TimerHandle' }],
    functions: [
      { name: 'OpenSettings', inputs: [], outputs: [], pure: false },
      { name: 'HandleEscape', inputs: [], outputs: [], pure: false },
      { name: 'UpdateMenuFocus', inputs: [], outputs: [], pure: false },
    ],
    graphs: [ev, open, esc, menu].map((g) => g.json()),
    cdo_defaults: { bIsFocusable: true, DesiredFocusWidget: { WidgetName: 'ResumeButton' } },
  };
}

// ─── WBP_Saskarta_Title graph ────────────────────────────────────────────────
function titleSpec() {
  const ev = new Graph('EventGraph');
  ev.add('continueClicked', { bound_event: { target: 'ContinueButton', event: 'OnClicked' } });
  ev.add('continueOwner', { call: 'GetOwningPlayer', class: WIDGET });
  ev.add('continuePC', { cast: PCC });
  ev.add('continueGame', { call: 'ContinueGame', class: PCC });
  ev.add('continueResult', { branch: true });
  ev.add('continueFailed', { call: 'SetText', class: TEXTB });
  ev.exec('continueClicked', 'continuePC', 'continueGame', 'continueResult');
  ev.link('continueOwner.ReturnValue', 'continuePC.Object');
  ev.link('continuePC.AsPC Saskarta', 'continueGame.self');
  ev.link('continueGame.bRestored', 'continueResult.Condition');
  ev.exec('continueResult.else', 'continueFailed');
  ev.link('continuePC.CastFailed', 'continueFailed.execute');
  wire(ev, 'ContinueLabel', 'continueFailed.self');
  ev.def('continueFailed.InText', 'Could not continue');
  ev.add('startClicked', { bound_event: { target: 'StartButton', event: 'OnClicked' } });
  ev.add('startOwner', { call: 'GetOwningPlayer', class: WIDGET });
  ev.add('castCarrierPC', { cast: PCC });
  ev.add('startGame', { call: 'StartGame', class: PCC });
  ev.exec('startClicked', 'castCarrierPC', 'startGame');
  ev.link('startOwner.ReturnValue', 'castCarrierPC.Object');
  ev.link('castCarrierPC.AsPC Saskarta', 'startGame.self');
  ev.add('quitClicked', { bound_event: { target: 'QuitButton', event: 'OnClicked' } });
  ev.add('quitOwner', { call: 'GetOwningPlayer', class: WIDGET });
  ev.add('quitGame', { call: 'QuitGame', class: KSL });
  ev.exec('quitClicked', 'quitGame');
  ev.link('quitOwner.ReturnValue', 'quitGame.SpecificPlayer');
  ev.def('quitGame.QuitPreference', 'Quit');
  ev.def('quitGame.bIgnorePlatformRestrictions', 'false');
  // Settings: one layer at a time. The title collapses (art, subtitle, menu,
  // hints and its shade), and the settings page's Back shows it again and
  // refocuses the Settings entry.
  ev.add('settingsClicked', { bound_event: { target: 'SettingsButton', event: 'OnClicked' } });
  ev.add('hideTitle', { call: 'SetVisibility', class: WIDGET });
  ev.def('hideTitle.InVisibility', 'Collapsed');
  ev.add('settingsOwner', { call: 'GetOwningPlayer', class: WIDGET });
  ev.add('createSettings', { create_widget: SETTINGS_W });
  ev.link('settingsOwner.ReturnValue', 'createSettings.OwningPlayer');
  ev.add('me', { self: true });
  ev.add('setReturn', { call: 'SetReturn', class: SETTINGS_W });
  ev.link('createSettings.ReturnValue', 'setReturn.self');
  ev.link('me.self', 'setReturn.ReturnWidget');
  wire(ev, 'SettingsButton', 'setReturn.FocusWidget');
  ev.add('showSettings', { call: 'AddToViewport', class: USERW });
  ev.link('createSettings.ReturnValue', 'showSettings.self');
  ev.def('showSettings.ZOrder', '200');
  ev.exec('settingsClicked', 'hideTitle', 'createSettings', 'setReturn', 'showSettings');
  const menu = menuFocus(ev, ['Continue', 'Start', 'Settings', 'Quit']);
  // Check only when this title instance is constructed. Disabled rows are skipped
  // by SaskartaMenuWidget; a failed/corrupt restore leaves the title usable.
  ev.add('continueExists', { call: 'DoesSaveGameExist', class: GSTAT });
  ev.add('continueEnabled', { call: 'SetIsEnabled', class: WIDGET });
  ev.def('continueExists.SlotName', 'Saskarta_Run');
  ev.def('continueExists.UserIndex', 0);
  wire(ev, 'ContinueButton', 'continueEnabled.self');
  ev.link('continueExists.ReturnValue', 'continueEnabled.bInIsEnabled');
  ev.links = ev.links.filter(([from, to]) => from !== 'menuConstruct.then' || to !== 'menuTimer.execute');
  ev.exec('menuConstruct', 'continueExists', 'continueEnabled', 'menuTimer');
  return {
    asset: `${UI}/WBP_Saskarta_Title`,
    description: 'Title menu: Continue / Begin / Settings / Quit with shared focus and an Enter / A select hint. Native menu input handles both devices; no Blueprint key-event device switch is assumed. Continue is enabled only for an existing run slot and retains the title on restore failure. Build PC_Saskarta.continue.json before these graphs. Generated by Tools/GameFlow/gen_settings_specs.mjs.',
    variables: [{ name: 'MenuFocusTimer', type: 'struct:/Script/Engine.TimerHandle' }],
    functions: [{ name: 'UpdateMenuFocus', inputs: [], outputs: [], pure: false }],
    graphs: [ev.json(), menu.json()],
    cdo_defaults: { bIsFocusable: true, DesiredFocusWidget: { WidgetName: 'StartButton' } },
  };
}

// ─── PC_Saskarta additions ───────────────────────────────────────────────────
const PC_VARIABLES = [
  { name: 'PauseWidget', type: `object:${PAUSE_W}` },
  { name: 'PausedFrom', type: 'name', default: 'Playing' },
  { name: 'PauseKeyTimer', type: 'struct:/Script/Engine.TimerHandle' },
  { name: 'PauseKeyInterval', type: 'float', default: '0.05' },
  { name: 'bPauseKeyHeld', type: 'bool', default: 'false' },
  { name: 'OpeningSkipTimer', type: 'struct:/Script/Engine.TimerHandle' },
  { name: 'OpeningSkipInterval', type: 'float', default: '0.05' },
  { name: 'bOpeningSkipRequested', type: 'bool', default: 'false' },
  { name: 'SkipRevealBurnTime', type: 'float', default: '0.25' },
];
const PC_FUNCTIONS = ['ApplyStartupSettings', 'EnterPlaying', 'PollPauseKey', 'TogglePause', 'OpenPause', 'ClosePause', 'QuitToTitle', 'ApplyPlayerFOV'].map((name) => ({ name, pure: false, inputs: [], outputs: [] }));

function pcGraphs() {
  const graphs = [];
  // ApplyStartupSettings(): the engine applies only the non-resolution settings at
  // startup, which skips the Saskarta override; publish the Saskarta cvars, the
  // master volume and the display extras here.
  {
    const g = new Graph('ApplyStartupSettings');
    g.add('entry', { entry: true });
    g.add('sask', { call: 'GetSaskartaSettings', class: SGUS });
    g.add('valid', { call: 'IsValid', class: KSL });
    g.link('sask.ReturnValue', 'valid.Object');
    g.add('br', { branch: true });
    g.link('valid.ReturnValue', 'br.Condition');
    g.add('publish', { call: 'ApplySaskartaSettings', class: SGUS });
    g.link('sask.ReturnValue', 'publish.self');
    g.add('audio', { call: 'ApplyAudio', class: BFL });
    g.add('load', { call: 'LoadDisplay', class: BFL });
    g.add('apply', { call: 'ApplyDisplay', class: BFL });
    g.link('load.Display', 'apply.Display');
    g.exec('entry', 'br', 'publish', 'audio', 'load', 'apply');
    g.link('br.else', 'load.execute');
    graphs.push(g);
  }
  // EnterPlaying(): stop the opening poll, restore the Title budget/audio listener, then start Esc polling and apply FOV.
  {
    const g = new Graph('EnterPlaying');
    g.add('entry', { entry: true });
    g.add('openingSkipGet', { get: 'OpeningSkipTimer' });
    g.add('stopOpeningSkip', { call: 'K2_ClearAndInvalidateTimerHandle', class: KSL });
    g.link('openingSkipGet.OpeningSkipTimer', 'stopOpeningSkip.Handle');
    g.add('timer', { timer: true });
    wire(g, 'PauseKeyInterval', 'timer.Time');
    g.def('timer.FunctionName', 'PollPauseKey');
    g.def('timer.bLooping', 'true');
    g.add('store', { set: 'PauseKeyTimer' });
    g.link('timer.ReturnValue', 'store.PauseKeyTimer');
    g.add('fov', { call: 'ApplyPlayerFOV' });
    g.add('resumeTitleGov', { call: 'GetPerfGovernor', class: '/Script/SaskartaCore.SaskartaPerfGovernor' });
    g.add('resumeTitle', { call: 'SetSuspended', class: '/Script/SaskartaCore.SaskartaPerfGovernor' });
    g.link('resumeTitleGov.ReturnValue', 'resumeTitle.self');
    g.link('entry.then', 'resumeTitleGov.execute');
    g.link('resumeTitleGov.then', 'resumeTitle.execute');
    g.add('me', { self: true });
    g.add('unmuteWorld', { call: 'ClearAudioListenerOverride', class: '/Script/Engine.PlayerController' });
    g.link('me.self', 'resumeTitleGov.WorldContext');
    g.link('me.self', 'unmuteWorld.self');
    g.def('resumeTitle.Reason', 'Title');
    g.def('resumeTitle.bSuspend', 'false');
    g.exec('resumeTitle', 'stopOpeningSkip', 'unmuteWorld', 'timer', 'store', 'fov');
    graphs.push(g);
  }
  // PollPauseKey(): Escape edge (down now, up last poll) -> TogglePause. A timer,
  // not Tick; the controller sees keys only in GameOnly / GameAndUI input modes.
  {
    const g = new Graph('PollPauseKey');
    g.add('entry', { entry: true });
    g.add('down', { call: 'IsInputKeyDown', class: '/Script/Engine.PlayerController' });
    g.def('down.Key', 'Escape');
    g.add('wasUp', { call: 'Not_PreBool', class: KML });
    wire(g, 'bPauseKeyHeld', 'wasUp.A');
    g.add('pressed', { call: 'BooleanAND', class: KML });
    g.link('down.ReturnValue', 'pressed.A');
    g.link('wasUp.ReturnValue', 'pressed.B');
    g.add('setPressed', { set: 'bPauseKeyHeld' });
    g.link('down.ReturnValue', 'setPressed.bPauseKeyHeld');
    // Read `pressed` into a branch BEFORE the held flag is updated.
    g.add('br', { branch: true });
    g.link('pressed.ReturnValue', 'br.Condition');
    g.add('toggle', { call: 'TogglePause' });
    g.add('seq', { sequence: 2 });
    g.exec('entry', 'seq');
    g.link('seq.then_0', 'br.execute');
    g.link('br.then', 'toggle.execute');
    g.link('seq.then_1', 'setPressed.execute');
    graphs.push(g);
  }
  {
    const g = new Graph('TogglePause');
    g.add('entry', { entry: true });
    g.add('isPlaying', { call: 'EqualEqual_NameName', class: KML });
    wire(g, 'FlowState', 'isPlaying.A');
    g.def('isPlaying.B', 'Playing');
    g.add('isPaused', { call: 'EqualEqual_NameName', class: KML });
    wire(g, 'FlowState', 'isPaused.A');
    g.def('isPaused.B', 'Paused');
    g.add('br', { branch: true });
    g.add('br2', { branch: true });
    g.add('isPlayingHuman', { call: 'EqualEqual_NameName', class: KML });
    g.add('getFlowStateH', { get: 'FlowState' });
    g.add('orHuman', { call: 'BooleanOR', class: KML });
    g.link('getFlowStateH.FlowState', 'isPlayingHuman.A');
    g.def('isPlayingHuman.B', 'Human');
    g.link('isPlaying.ReturnValue', 'orHuman.A');
    g.link('isPlayingHuman.ReturnValue', 'orHuman.B');
    g.link('orHuman.ReturnValue', 'br.Condition');
    g.link('isPaused.ReturnValue', 'br2.Condition');
    g.add('open', { call: 'OpenPause' });
    g.add('esc', { call: 'HandleEscape', class: PAUSE_W });
    wire(g, 'PauseWidget', 'esc.self');
    g.exec('entry', 'br', 'open');
    g.link('br.else', 'br2.execute');
    g.link('br2.then', 'esc.execute');
    graphs.push(g);
  }
  // OpenPause(): accepts Playing or Human and remembers which mode to resume. The world keeps running
  // (a paused world would also stop the 15 s resolution countdown's timer);
  // the carrier stands still because move and look input are ignored.
  {
    const g = new Graph('OpenPause');
    g.add('entry', { entry: true });
    g.add('isPlaying', { call: 'EqualEqual_NameName', class: KML });
    wire(g, 'FlowState', 'isPlaying.A');
    g.def('isPlaying.B', 'Playing');
    g.add('guard', { branch: true });
    g.add('isPlayingHuman', { call: 'EqualEqual_NameName', class: KML });
    g.add('getFlowStateH', { get: 'FlowState' });
    g.add('orHuman', { call: 'BooleanOR', class: KML });
    g.link('getFlowStateH.FlowState', 'isPlayingHuman.A');
    g.def('isPlayingHuman.B', 'Human');
    g.link('isPlaying.ReturnValue', 'orHuman.A');
    g.link('isPlayingHuman.ReturnValue', 'orHuman.B');
    g.link('orHuman.ReturnValue', 'guard.Condition');
    g.add('getFlowStateF', { get: 'FlowState' });
    g.add('savePrev', { set: 'PausedFrom' });
    g.link('getFlowStateF.FlowState', 'savePrev.PausedFrom');
    g.add('toPaused', { set: 'FlowState' });
    g.def('toPaused.FlowState', 'Paused');
    g.add('noMove', { call: 'SetIgnoreMoveInput', class: '/Script/Engine.Controller' });
    g.def('noMove.bNewMoveInput', 'true');
    g.add('noLook', { call: 'SetIgnoreLookInput', class: '/Script/Engine.Controller' });
    g.def('noLook.bNewLookInput', 'true');
    g.add('valid', { call: 'IsValid', class: KSL });
    wire(g, 'PauseWidget', 'valid.Object');
    g.add('have', { branch: true });
    g.link('valid.ReturnValue', 'have.Condition');
    g.add('create', { create_widget: PAUSE_W });
    g.add('me', { self: true });
    g.link('me.self', 'create.OwningPlayer');
    g.add('store', { set: 'PauseWidget' });
    g.link('create.ReturnValue', 'store.PauseWidget');
    g.add('show', { call: 'AddToViewport', class: USERW });
    wire(g, 'PauseWidget', 'show.self');
    g.def('show.ZOrder', 300);
    g.add('mode', { call: 'SetInputMode_GameAndUIEx', class: WBL });
    g.add('me2', { self: true });
    g.link('me2.self', 'mode.PlayerController');
    wire(g, 'PauseWidget', 'mode.InWidgetToFocus');
    g.def('mode.InMouseLockMode', 'DoNotLock');
    g.def('mode.bHideCursorDuringCapture', 'false');
    g.add('cursor', { set: 'bShowMouseCursor' });
    g.def('cursor.bShowMouseCursor', 'true');
    g.exec('entry', 'guard', 'savePrev', 'toPaused', 'noMove', 'noLook', 'have', 'show', 'mode', 'cursor');
    g.link('have.else', 'create.execute');
    g.exec('create', 'store', 'show');
    graphs.push(g);
  }
  {
    const g = new Graph('ClosePause');
    g.add('entry', { entry: true });
    g.add('isPaused', { call: 'EqualEqual_NameName', class: KML });
    wire(g, 'FlowState', 'isPaused.A');
    g.def('isPaused.B', 'Paused');
    g.add('guard', { branch: true });
    g.link('isPaused.ReturnValue', 'guard.Condition');
    g.add('remove', { call: 'RemoveFromParent', class: WIDGET });
    wire(g, 'PauseWidget', 'remove.self');
    g.add('input', { call: 'ResetIgnoreInputFlags', class: '/Script/Engine.Controller' });
    g.add('mode', { call: 'SetInputMode_GameOnly', class: WBL });
    g.add('me', { self: true });
    g.link('me.self', 'mode.PlayerController');
    g.add('cursor', { set: 'bShowMouseCursor' });
    g.def('cursor.bShowMouseCursor', 'false');
    g.add('toPlaying', { set: 'FlowState' });
    g.add('getPausedFrom', { get: 'PausedFrom' });
    g.link('getPausedFrom.PausedFrom', 'toPlaying.FlowState');
    g.add('fov', { call: 'ApplyPlayerFOV' });
    g.exec('entry', 'guard', 'remove', 'input', 'mode', 'cursor', 'toPlaying', 'fov');
    graphs.push(g);
  }
  // QuitToTitle(): reload the level; the new controller runs intro -> title.
  {
    const g = new Graph('QuitToTitle');
    g.add('entry', { entry: true });
    g.add('name', { call: 'GetCurrentLevelName', class: GSTAT });
    g.def('name.bRemovePrefixString', 'true');
    g.add('asName', { call: 'Conv_StringToName', class: KSTR });
    g.link('name.ReturnValue', 'asName.InString');
    g.add('open', { call: 'OpenLevel', class: GSTAT });
    g.link('asName.ReturnValue', 'open.LevelName');
    g.def('open.bAbsolute', 'true');
    g.exec('entry', 'name', 'open');
    graphs.push(g);
  }
  // ApplyPlayerFOV(): only while the carrier's own camera is the view (Playing or
  // Paused), so the title's cine camera keeps its lens.
  {
    const g = new Graph('ApplyPlayerFOV');
    g.add('entry', { entry: true });
    g.add('isPlaying', { call: 'EqualEqual_NameName', class: KML });
    wire(g, 'FlowState', 'isPlaying.A');
    g.def('isPlaying.B', 'Playing');
    g.add('isPaused', { call: 'EqualEqual_NameName', class: KML });
    wire(g, 'FlowState', 'isPaused.A');
    g.def('isPaused.B', 'Paused');
    g.add('live', { call: 'BooleanOR', class: KML });
    g.link('isPlaying.ReturnValue', 'live.A');
    g.link('isPaused.ReturnValue', 'live.B');
    g.add('fov', { call: 'GetConsoleVariableFloatValue', class: KSL });
    g.def('fov.VariableName', 'saskarta.fov');
    g.add('set', { call: 'Greater_DoubleDouble', class: KML });
    g.link('fov.ReturnValue', 'set.A');
    g.def('set.B', '1.0');
    g.add('both', { call: 'BooleanAND', class: KML });
    g.link('live.ReturnValue', 'both.A');
    g.link('set.ReturnValue', 'both.B');
    g.add('br', { branch: true });
    g.link('both.ReturnValue', 'br.Condition');
    // PlayerCameraManager::SetFOV is not Blueprint-callable (found live, Task TITLE), and the
    // carrier's CameraComponent FOV wins over the camera manager's anyway: set it there.
    g.add('pawn', { call: 'K2_GetPawn', class: '/Script/Engine.Controller' });
    g.add('comp', { call: 'GetComponentByClass', class: '/Script/Engine.Actor' });
    g.link('pawn.ReturnValue', 'comp.self');
    g.def('comp.ComponentClass', '/Script/Engine.CameraComponent');
    g.add('castCam', { cast: '/Script/Engine.CameraComponent' });
    g.link('comp.ReturnValue', 'castCam.Object');
    g.add('apply', { call: 'SetFieldOfView', class: '/Script/Engine.CameraComponent' });
    g.link('castCam.AsCamera Component', 'apply.self');
    g.link('fov.ReturnValue', 'apply.InFieldOfView');
    g.exec('entry', 'fov', 'br', 'castCam', 'apply');
    graphs.push(g);
  }
  return graphs.map((g) => g.json());
}

/** Insert `nodeId` (a call to fnName) into `graph` right after the exec pin `after`. */
function insertAfter(graph, after, nodeId, fnName) {
  graph.nodes[nodeId] = { call: fnName };
  const i = graph.links.findIndex((l) => l[0] === after);
  if (i < 0) throw new Error(`${graph.graph}: no link from ${after}`);
  const next = graph.links[i][1];
  graph.links.splice(i, 1, [after, `${nodeId}.execute`], [`${nodeId}.then`, next]);
}

function patchPc() {
  const file = join(SPECS, 'PC_Saskarta.json');
  const pc = JSON.parse(readFileSync(file, 'utf8'));
  const has = (arr, name) => arr.some((x) => x.name === name);
  for (const v of PC_VARIABLES) if (!has(pc.variables, v.name)) pc.variables.push(v);
  for (const f of PC_FUNCTIONS) if (!has(pc.functions, f.name)) pc.functions.push(f);
  const fresh = pcGraphs();
  for (const g of fresh) {
    const i = pc.graphs.findIndex((x) => x.graph === g.graph);
    if (i >= 0) pc.graphs[i] = g;
    else pc.graphs.push(g);
  }
  // BeginIntro: publish settings once the intro starts (after its once-guard).
  const intro = pc.graphs.find((x) => x.graph === 'BeginIntro');
  if (!intro.nodes.applyStartup) {
    // setStarted runs once, on the guard's first pass (ifStarted.else).
    insertAfter(intro, 'setStarted.then', 'applyStartup', 'ApplyStartupSettings');
  }
  // TryGround: once FlowState = Playing, start Esc polling and apply the FOV.
  const ground = pc.graphs.find((x) => x.graph === 'TryGround');
  if (!ground.nodes.enterPlaying) {
    ground.nodes.enterPlaying = { call: 'EnterPlaying' };
    ground.links.push(['toPlaying.then', 'enterPlaying.execute']);
  }
  writeFileSync(file, `${fmt(pc)}\n`);
  // The scoped spec rebuilt with --reset-graphs: only the graphs P3 touches.
  const touched = new Set([...PC_FUNCTIONS.map((f) => f.name), 'BeginIntro', 'TryGround']);
  const scoped = {
    asset: pc.asset,
    description: 'Scoped rebuild for Task P3 (generated): the PC graphs P3 adds or changes. Build with --reset-graphs; the other PC graphs are untouched. PC_Saskarta.json holds the same graphs.',
    variables: pc.variables,
    functions: pc.functions.filter((f) => touched.has(f.name)),
    graphs: pc.graphs.filter((g) => touched.has(g.graph)),
  };
  return scoped;
}

// ─── Designer trees (Hayba ui_build_tree) ────────────────────────────────────
// Direction A "the stele" at the 1920 x 1080 design size; 1 cqw = 19.2 px.
const font = (obj, size, spacing = 0, face = 'Bold') => ({ FontObject: obj, TypefaceFontName: face, Size: size, LetterSpacing: spacing });
const bold = (size, spacing = 0) => font(F_AREF, size, spacing, 'Bold');
const regular = (size, spacing = 0) => font(F_AREF, size, spacing, 'Regular');
const color = (c) => ({ SpecifiedColor: c });
const alpha = (c, a) => [c[0], c[1], c[2], a];
const text = (name, str, fontSpec, c, extra = {}) => ({ class: 'TextBlock', name, properties: { Text: str, Font: fontSpec, ColorAndOpacity: color(c), ...extra } });
const brush = (name, w, h, extra = {}) => ({ ResourceObject: tex(name), ImageSize: { X: w, Y: h }, DrawAs: 'Image', ...extra });
const image = (name, brushSpec, extra = {}) => ({ class: 'Image', name, properties: { Brush: brushSpec, ...extra } });
const solid = (name, c, w = 1, h = 1, extra = {}) => ({ class: 'Image', name, properties: { Brush: { ImageSize: { X: w, Y: h }, DrawAs: 'Image' }, ColorAndOpacity: c, ...extra } });
const NONE = { DrawAs: 'NoDrawType' };
const ZERO = { Left: 0, Top: 0, Right: 0, Bottom: 0 };
const pad = (l, t = l, r = l, b = t) => ({ Left: l, Top: t, Right: r, Bottom: b });
// Text-only buttons: no plate at all; focus and hover are drawn by the
// widget's own mark / opacity poll (menuFocus, UpdateFocus).
const PLAIN_BUTTON = { WidgetStyle: { Normal: NONE, Hovered: NONE, Pressed: NONE, Disabled: NONE, NormalPadding: ZERO, PressedPadding: ZERO } };
// Key-hint chips (footer actions, the benchmark button): 1 px ivory outline at
// 35 %, gold when hovered.
const chipBrush = (tint) => ({ ResourceObject: tex('T_UI_Chip'), DrawAs: 'Box', Margin: pad(0.25), TintColor: color(tint) });
const CHIP_BUTTON = {
  WidgetStyle: {
    Normal: chipBrush(alpha(INK, 0.35)),
    Hovered: chipBrush(alpha(GOLD, 0.95)),
    Pressed: chipBrush(GOLD),
    Disabled: chipBrush(alpha(INK, 0.12)),
    NormalPadding: pad(16, 2, 16, 8),
    PressedPadding: pad(16, 2, 16, 8),
  },
};
const chipButton = (name, label, str, size = 17) => ({
  class: 'Button',
  name,
  properties: CHIP_BUTTON,
  children: [text(label, str, regular(size, 40), alpha(INK, 0.9), { Justification: 'Center' })],
});
// The ◀ ▶ selector arrows: a plain button (gold wash on hover) around a 12 x 14 gold glyph,
// padded to a 28 x 34 hit target.
const arrowButton = (name, side) => ({
  class: 'Button',
  name,
  properties: {
    // No hover/pressed brush: Slate paints Hovered while the button holds keyboard focus, which drew
    // a filled square behind only the focused row's right arrow (user screenshot). The row glow is the
    // highlight; the arrows stay bare glyphs on both sides.
    WidgetStyle: {
      Normal: NONE,
      Hovered: NONE,
      Pressed: NONE,
      Disabled: NONE,
      NormalPadding: pad(8, 13, 8, 7),
      PressedPadding: pad(8, 13, 8, 7),
    },
  },
  children: [image(`${name}Glyph`, brush(`T_UI_Arrow_${side}`, 12, 14))],
  slot_props: { vertical_alignment: 'Center' },
});
const COMBO_STYLE = {
  WidgetStyle: {
    ComboButtonStyle: {
      ButtonStyle: {
        Normal: NONE,
        Hovered: { DrawAs: 'Image', TintColor: color(alpha(GOLD, 0.10)) },
        Pressed: { DrawAs: 'Image', TintColor: color(alpha(GOLD, 0.18)) },
        NormalPadding: ZERO,
        PressedPadding: ZERO,
      },
      DownArrowImage: NONE,
      MenuBorderBrush: { DrawAs: 'Image', TintColor: color(lin('17130F', 0.97)) },
      MenuBorderPadding: pad(0, 4),
    },
  },
  ContentPadding: pad(4, 0, 4, 8), // lifts Aref Ruqaa's low-sitting value text onto the label's line
  ForegroundColor: color(INK),
  ItemStyle: {
    TextColor: color(INK),
    SelectedTextColor: color(INK),
    EvenRowBackground: { DrawAs: 'Image', TintColor: color(lin('17130F', 0.97)) },
    OddRowBackground: { DrawAs: 'Image', TintColor: color(lin('1C1713', 0.97)) },
    EvenRowBackgroundHovered: { DrawAs: 'Image', TintColor: color(alpha(GOLD, 0.16)) },
    OddRowBackgroundHovered: { DrawAs: 'Image', TintColor: color(alpha(GOLD, 0.16)) },
    ActiveBrush: { DrawAs: 'Image', TintColor: color(alpha(GOLD, 0.24)) },
    ActiveHoveredBrush: { DrawAs: 'Image', TintColor: color(alpha(GOLD, 0.3)) },
  },
};
const toggleStyle = () => {
  const off = brush('T_UI_Toggle_Off', 61, 29);
  const on = brush('T_UI_Toggle_On', 61, 29);
  const offHover = brush('T_UI_Toggle_Off', 61, 29, { TintColor: color([1.4, 1.3, 1.2, 1]) });
  return {
    WidgetStyle: {
      CheckBoxType: 'CheckBox',
      UncheckedImage: off, UncheckedHoveredImage: offHover, UncheckedPressedImage: off,
      CheckedImage: on, CheckedHoveredImage: on, CheckedPressedImage: on,
      UndeterminedImage: off, UndeterminedHoveredImage: off, UndeterminedPressedImage: off,
      Padding: ZERO,
    },
  };
};
const SLIDER_STYLE = {
  WidgetStyle: {
    NormalBarImage: { DrawAs: 'Image', TintColor: color([1, 1, 1, 1]) },
    HoveredBarImage: { DrawAs: 'Image', TintColor: color([1, 1, 1, 1]) },
    DisabledBarImage: { DrawAs: 'Image', TintColor: color([1, 1, 1, 0.4]) },
    NormalThumbImage: brush('T_UI_Knob', 24, 24),
    HoveredThumbImage: brush('T_UI_Knob', 24, 24),
    DisabledThumbImage: brush('T_UI_Knob', 24, 24, { TintColor: color([1, 1, 1, 0.4]) }),
    BarThickness: 2,
  },
  SliderBarColor: alpha(GOLD, 0.7),
  SliderHandleColor: INK,
};

// A settings row (direction A): label left, control in a 19 cqw column right,
// a thin separator, and a gold gradient that the focus poll shows.
// SCALABILITY.md BP hookup 2: the "Detected: <GPU>, <VRAM>, recommended: <level>" line under the
// benchmark row. Not a row (no control), so the menu navigation skips it. Collapsed until
// RefreshGraphics fills it (needs USaskartaGameUserSettings::GetDetectedSummary, next plugin build).
const detectedLine = () => ({ ...text('DetectedText', '', regular(17, 40), alpha(MUTE, 0.9), { Visibility: 'Collapsed' }), slot_props: { padding: [18, 2, 0, 10] } });

function rowTree(r) {
  let control;
  if (r.kind === 'combo') {
    control = {
      class: 'HorizontalBox',
      name: `${r.id}Selector`,
      children: [
        arrowButton(`${r.id}Prev`, 'L'),
        { class: 'ComboBoxString', name: ctl(r), properties: { DefaultOptions: r.options, SelectedOption: r.def ?? r.options[0], Font: regular(18, 60), ...COMBO_STYLE }, slot_props: { fill: 1, vertical_alignment: 'Center' } },
        arrowButton(`${r.id}Next`, 'R'),
      ],
    };
  } else if (r.kind === 'slider') {
    control = {
      class: 'HorizontalBox',
      name: `${r.id}Track`,
      children: [
        { class: 'Slider', name: ctl(r), properties: { MinValue: r.min, MaxValue: r.max, StepSize: r.step, Value: r.def ?? r.min, MouseUsesStep: true, IsFocusable: true, ...SLIDER_STYLE }, slot_props: { fill: 1, vertical_alignment: 'Center' } },
        { class: 'SizeBox', name: `${r.id}ValueBox`, properties: { bOverride_WidthOverride: true, WidthOverride: 64 }, slot_props: { vertical_alignment: 'Center' }, children: [text(`${r.id}Value`, r.dec < 0 ? `${Math.round((r.def ?? r.min) * 100)} %` : (r.def ?? r.min).toFixed(r.dec), regular(18), alpha(INK, 0.85), { Justification: 'Right' })] },
      ],
    };
  } else if (r.kind === 'check') {
    control = { class: 'CheckBox', name: ctl(r), properties: { CheckedState: r.def ? 'Checked' : 'Unchecked', ...toggleStyle() } };
  } else {
    control = chipButton(ctl(r), `${r.id}ButtonLabel`, r.text.charAt(0) + r.text.slice(1).toLowerCase(), 16);
  }
  const controlSlot = r.kind === 'check' || r.kind === 'button' ? { horizontal_alignment: 'Left', vertical_alignment: 'Center' } : { vertical_alignment: 'Center' };
  return {
    class: 'Overlay',
    name: `${r.id}Row`,
    properties: { Visibility: r.hidden ? 'Collapsed' : 'Visible' },
    children: [
      { ...image(`${r.id}Glow`, brush('T_UI_RowGlow', 256, 8), { RenderOpacity: 0 }), slot_props: { horizontal_alignment: 'Fill', vertical_alignment: 'Fill' } },
      { ...solid(`${r.id}Sep`, alpha(INK, 0.07), 1, 1), slot_props: { horizontal_alignment: 'Fill', vertical_alignment: 'Bottom' } },
      {
        class: 'HorizontalBox',
        name: `${r.id}Line`,
        slot_props: { horizontal_alignment: 'Fill', vertical_alignment: 'Fill', padding: [18, 9, 0, 9] },
        children: [
          // The control box is 250 px so the longest label (Show original Saskartan, ~215 px) still fits
          // beside it when the page is narrow (1166 x 838: the page is ~509 px wide).
          { ...text(`${r.id}Label`, r.label, regular(20, 20), alpha(INK, 0.86)), slot_props: { fill: 1, vertical_alignment: 'Center', padding: [0, 0, 12, 0] } },
          // Min height, not a fixed height: a fixed 36 px clipped the bottom of the combo's value text
          // ("TSR", "Quality") once its content padding lifted it (user screenshot, 1166x838).
          { class: 'SizeBox', name: `${r.id}ControlBox`, properties: { bOverride_WidthOverride: true, WidthOverride: 250, bOverride_MinDesiredHeight: true, MinDesiredHeight: 36 }, slot_props: { vertical_alignment: 'Center' }, children: [{ ...control, slot_props: controlSlot }] },
        ],
      },
    ],
  };
}

const fullScreen = { anchors: [0, 0, 1, 1], position: [0, 0], size: [0, 0] };
// The settings and pause backdrop: a full-screen background blur, then a
// #0C0A08 scrim at 74 %, so the scene never competes with the text.
const backdrop = () => [
  { class: 'BackgroundBlur', name: 'Blur', properties: { BlurStrength: 10, bApplyAlphaToBlur: true } },
  solid('Scrim', SCRIM),
];
const BACKDROP_SLOTS = { Blur: { ...fullScreen, z_order: -3 }, Scrim: { ...fullScreen, z_order: -2 } };

function settingsTree() {
  const tabs = TABS.map((t) => ({
    class: 'Button',
    name: `Tab${t.key}Button`,
    properties: PLAIN_BUTTON,
    slot_props: { padding: [0, 0, 0, 22], horizontal_alignment: 'Left' },
    children: [{
      class: 'HorizontalBox',
      name: `Tab${t.key}Box`,
      children: [
        { ...solid(`Tab${t.key}Bar`, GOLD, 2, 22, { RenderOpacity: 0 }), slot_props: { vertical_alignment: 'Center' } },
        { ...text(`Tab${t.key}Label`, t.key, bold(19, 60), INK), slot_props: { vertical_alignment: 'Center', padding: [24, 0, 0, 0] } },
      ],
    }],
  }));
  const pages = TABS.map((t) => ({
    class: 'ScrollBox',
    name: `${t.key}Page`,
    children: [{ class: 'VerticalBox', name: `${t.key}List`, children: t.rows.flatMap((r) => (r.id === 'AutoDetect' ? [rowTree(r), detectedLine()] : [rowTree(r)])) }],
  }));
  return [
    ...backdrop(),
    solid('SideRule', alpha(INK, 0.08)),
    solid('FootRule', alpha(INK, 0.08)),
    image('Mini', brush('T_Saskarta_TitleName_Ivory', 118, 192), { RenderOpacity: 0.18 }),
    text('Heading', 'Settings', bold(38, 20), INK),
    { class: 'VerticalBox', name: 'TabBar', children: tabs },
    { class: 'WidgetSwitcher', name: 'TabSwitcher', children: pages },
    text('Description', '', regular(19, 10), MUTE, { AutoWrapText: true }),
    {
      class: 'HorizontalBox',
      name: 'Actions',
      children: [
        { class: 'Spacer', name: 'ActionsSpacer', slot_props: { fill: 1 } },
        { ...chipButton('ApplyButton', 'ApplyLabel', 'Apply'), slot_props: { padding: [0, 0, 28, 0], vertical_alignment: 'Center' } },
        { ...chipButton('RevertButton', 'RevertLabel', 'Revert'), slot_props: { padding: [0, 0, 28, 0], vertical_alignment: 'Center' } },
        { ...chipButton('BackButton', 'BackLabel', 'Back'), slot_props: { vertical_alignment: 'Center' } },
      ],
    },
    // "Applied" / "Reverted" after the footer's Apply / Revert and the keep-or-revert check
    // (USaskartaMenuWidget::OnShowToast finds it by name, shows it for 2 s, collapses it again).
    // Without it those clicks gave no visible sign at all (FallbackToastName is None, because the
    // description line is rewritten every 50 ms).
    text('Toast', '', regular(19, 40), GOLD, { Visibility: 'Collapsed', Justification: 'Right' }),
    // The keep-or-revert check covers the whole page: blur + 60 % scrim behind an opaque panel,
    // and the overlay (Visible) takes every click, so the rows behind are not hit-testable.
    {
      class: 'Overlay',
      name: 'ConfirmOverlay',
      properties: { Visibility: 'Collapsed' },
      children: [
        { class: 'BackgroundBlur', name: 'ConfirmBlur', properties: { BlurStrength: 6 }, slot_props: { horizontal_alignment: 'Fill', vertical_alignment: 'Fill' } },
        { ...solid('ConfirmScrim', lin('0C0A08', 0.6)), slot_props: { horizontal_alignment: 'Fill', vertical_alignment: 'Fill' } },
        {
          class: 'Border',
          name: 'ConfirmPanel',
          properties: { BrushColor: lin('17130F', 1.0), Padding: pad(56, 40) },
          slot_props: { horizontal_alignment: 'Center', vertical_alignment: 'Center' },
          children: [
            {
              class: 'VerticalBox',
              name: 'ConfirmBox',
              children: [
                text('ConfirmHeading', 'Keep these display settings?', bold(26, 20), INK),
                { ...text('CountdownText', 'REVERTING IN 15 S', regular(19, 40), MUTE), slot_props: { padding: [0, 12, 0, 26] } },
                {
                  class: 'HorizontalBox',
                  name: 'ConfirmActions',
                  children: [
                    { ...chipButton('KeepButton', 'KeepLabel', 'Keep'), slot_props: { padding: [0, 0, 24, 0] } },
                    chipButton('RevertNowButton', 'RevertNowLabel', 'Revert'),
                  ],
                },
              ],
            },
          ],
        },
      ],
    },
    // Task MENUINPUT 2c: the "Apply changes?" prompt. USaskartaMenuWidget shows/hides it and
    // handles its three buttons (order matters: Apply, Discard, Cancel); no graph needed.
    {
      class: 'Overlay',
      name: 'PromptOverlay',
      properties: { Visibility: 'Collapsed' },
      children: [
        { class: 'BackgroundBlur', name: 'PromptBlur', properties: { BlurStrength: 6 }, slot_props: { horizontal_alignment: 'Fill', vertical_alignment: 'Fill' } },
        { ...solid('PromptScrim', lin('0C0A08', 0.6)), slot_props: { horizontal_alignment: 'Fill', vertical_alignment: 'Fill' } },
        {
          class: 'Border',
          name: 'PromptPanel',
          properties: { BrushColor: lin('17130F', 1.0), Padding: pad(56, 40) },
          slot_props: { horizontal_alignment: 'Center', vertical_alignment: 'Center' },
          children: [{
            class: 'VerticalBox',
            name: 'PromptBox',
            children: [
              text('PromptHeading', 'Apply changes?', bold(26, 20), INK),
              { ...text('PromptBody', 'Some settings have changed but are not applied.', regular(19, 40), MUTE), slot_props: { padding: [0, 12, 0, 26] } },
              {
                class: 'HorizontalBox',
                name: 'PromptActions',
                children: [
                  { ...chipButton('PromptApplyButton', 'PromptApplyLabel', 'Apply'), slot_props: { padding: [0, 0, 24, 0] } },
                  { ...chipButton('PromptDiscardButton', 'PromptDiscardLabel', 'Discard'), slot_props: { padding: [0, 0, 24, 0] } },
                  chipButton('PromptCancelButton', 'PromptCancelLabel', 'Cancel'),
                ],
              },
            ],
          }],
        },
      ],
    },
  ];
}

/** Canvas slots applied after the build. */
const SETTINGS_SLOTS = {
  ...BACKDROP_SLOTS,
  SideRule: { anchors: [0, 0, 0, 1], position: [461, 0], size: [1, 0] },
  FootRule: { anchors: [0, 1, 1, 1], position: [0, -104], size: [0, 1] },
  Mini: { anchors: [0, 1, 0, 1], position: [96, -300], size: [118, 192] },
  Heading: { anchors: [0, 0, 0, 0], position: [96, 80], size: [340, 64] },
  TabBar: { anchors: [0, 0, 0, 0], position: [96, 184], size: [340, 360] },
  TabSwitcher: { anchors: [0, 0, 1, 1], position: [542, 88], size: [115, 230] },
  Description: { anchors: [0, 1, 1, 1], position: [560, -190], size: [115, 60] },
  Actions: { anchors: [1, 1, 1, 1], position: [-67, -52], size: [620, 48], alignment: [1, 0.5] },
  // On the footer line, right-aligned just left of the three chips (they take about 330 px).
  Toast: { anchors: [1, 1, 1, 1], position: [-430, -52], size: [320, 40], alignment: [1, 0.5] },
  ConfirmOverlay: { ...fullScreen, z_order: 10 },
  PromptOverlay: { ...fullScreen, z_order: 11 },
};

// A stele menu entry: the gold focus mark and the label (menuFocus drives both).
const menuEntry = (n, str, size = 30) => ({
  class: 'Button',
  name: `${n}Button`,
  properties: PLAIN_BUTTON,
  slot_props: { padding: [0, 0, 0, 30], horizontal_alignment: 'Left' },
  children: [{
    class: 'HorizontalBox',
    name: `${n}Entry`,
    children: [
      { ...image(`${n}Mark`, brush('T_UI_FocusMark', 48, 24), { RenderOpacity: 0 }), slot_props: { vertical_alignment: 'Center' } },
      { ...text(`${n}Label`, str, bold(size, 50), INK, { RenderOpacity: 0.6 }), slot_props: { vertical_alignment: 'Center', padding: [6, 0, 0, 0] } },
    ],
  }],
});

// The native menu consumes navigation/accept in PreviewKeyDown and has no
// Blueprint device query. Keep both supported accept controls visible.
const TITLE_ACCEPT_HINT = 'Enter / A';
function titleTree() {
  return [
    image('Scrim', brush('T_UI_TitleScrim', 1024, 576)),
    image('TitleShadow', brush('T_Saskarta_TitleName_Shadow', 464, 704), { ColorAndOpacity: [1, 1, 1, 0.6] }),
    image('TitleArt', brush('T_Saskarta_TitleName_Ivory', 360, 584)),
    // The Latin name stays in the tree (collapsed) for tools and fallbacks.
    text('Title', 'Najzen dînefferesen, enisetre', bold(22), INK, { Visibility: 'Collapsed', RenderOpacity: 0, AutoWrapText: true }),
    // No subtitle (user, 2026-09-27): the Saskartan calligraphy is the one and only title.
    { class: 'VerticalBox', name: 'Menu', children: [menuEntry('Continue', 'Continue'), menuEntry('Start', 'Begin'), menuEntry('Settings', 'Settings'), menuEntry('Quit', 'Quit')] },
    {
      class: 'HorizontalBox',
      name: 'Hints',
      properties: { RenderOpacity: 0.85 },
      children: [
        { class: 'Spacer', name: 'HintsSpacer', slot_props: { fill: 1 } },
        { class: 'Border', name: 'HintEnterChip', properties: { Background: chipBrush(alpha(INK, 0.35)), Padding: pad(10, 0, 10, 3) }, slot_props: { vertical_alignment: 'Center' }, children: [text('HintEnterKey', TITLE_ACCEPT_HINT, regular(15, 20), alpha(INK, 0.85))] },
        { ...text('HintEnterLabel', 'Select', regular(16, 60), alpha(INK, 0.55)), slot_props: { vertical_alignment: 'Center', padding: [12, 0, 0, 0] } },
      ],
    },
  ];
}
const TITLE_SLOTS = {
  Scrim: { ...fullScreen, z_order: -2 },
  // The calligraphy alone, vertically centred on the left third (stele): 360 x 584 at 1080p.
  TitleShadow: { anchors: [0, 0.5, 0, 0.5], position: [87, -330], size: [436, 661], z_order: -1 },
  TitleArt: { anchors: [0, 0.5, 0, 0.5], position: [125, -300], size: [360, 584] },
  Title: { anchors: [0, 0.5, 0, 0.5], position: [125, -300], size: [360, 584] },
  Menu: { anchors: [0, 0.5, 0, 0.5], position: [580, -110], size: [420, 400] },
  Hints: { anchors: [1, 1, 1, 1], position: [-67, -50], size: [420, 32], alignment: [1, 0.5] },
};

function pauseTree() {
  return [
    ...backdrop(),
    image('Mini', brush('T_Saskarta_TitleName_Ivory', 118, 192), { RenderOpacity: 0.18 }),
    text('Heading', 'Paused', bold(44, 30), INK),
    { class: 'VerticalBox', name: 'Menu', children: [menuEntry('Resume', 'Resume'), menuEntry('Settings', 'Settings'), menuEntry('Quit', 'Quit to title')] },
  ];
}
const PAUSE_SLOTS = {
  ...BACKDROP_SLOTS,
  Mini: { anchors: [0, 1, 0, 1], position: [96, -269], size: [118, 192] },
  Heading: { anchors: [0, 0.5, 0, 0.5], position: [125, -190], size: [520, 70] },
  Menu: { anchors: [0, 0.5, 0, 0.5], position: [110, -84], size: [520, 300] },
};

// ─── Write ───────────────────────────────────────────────────────────────────
const out = (name, value) => writeFileSync(join(SPECS, name), `${fmt(value)}\n`);
if (process.argv.includes('--apply-only')) {
  const generated = settingsGraphs();
  const graph = generated.graphs.find((g) => g.graph === 'ApplyPending');
  const source = JSON.parse(readFileSync(join(SPECS, 'WBP_Saskarta_Settings.graph.json'), 'utf8'));
  source.graphs = source.graphs.map((g) => g.graph === graph.graph ? graph : g);
  out('WBP_Saskarta_Settings.graph.json', source);
  out('WBP_Saskarta_Settings.apply.json', {
    asset: generated.asset,
    description: 'Scoped ApplyPending fix: apply/save engine settings once, then audio/FOV and row refresh. No designer tree changes.',
    functions: generated.functions.filter((f) => f.name === graph.graph),
    graphs: [graph],
  });
  console.log('Generated scoped ApplyPending graph and updated its full source spec.');
  process.exit(0);
}
const menuVars = (names) => names.flatMap((n) => [`${n}Button`, `${n}Label`, `${n}Mark`]);
out('WBP_Saskarta_Title.graph.json', titleSpec());
out('WBP_Saskarta_Title.tree.json', {
  asset: `${UI}/WBP_Saskarta_Title`,
  tree: titleTree(),
  slots: TITLE_SLOTS,
  variables: [...menuVars(['Continue', 'Start', 'Settings', 'Quit']), 'Title', 'TitleArt'],
});
out('WBP_Saskarta_Title.continue.tree.json', {
  asset: `${UI}/WBP_Saskarta_Title`,
  parent_widget_name: 'Menu',
  tree: [menuEntry('Continue', 'Continue')],
  moves: [{ widget_name: 'ContinueButton', index: 0 }],
  slots: { Menu: TITLE_SLOTS.Menu },
  variables: menuVars(['Continue']),
  widget_properties: { HintEnterKey: { Text: TITLE_ACCEPT_HINT } },
});
out('WBP_Saskarta_Settings.english_only.properties.json', {
  asset: `${UI}/WBP_Saskarta_Settings`,
  description: 'Property-only update: hide the obsolete original-language toggle while preserving existing widgets and graphs.',
  tree: [],
  variables: [],
  widget_properties: { ShowSaskartanRow: { Visibility: 'Collapsed' } },
});
if (process.argv.includes('--title-only')) {
  console.log('Generated title tree and graphs only.');
  process.exit(0);
}
out('SG_Saskarta_Display.json', saveGameSpec());
out('BFL_SaskartaSettings.json', bflSpec());
out('WBP_Saskarta_Settings.graph.json', settingsGraphs());
out('WBP_Saskarta_Pause.graph.json', pauseGraphs());
if (process.argv.includes('--pc')) out('PC_Saskarta.p3.json', patchPc());
out('WBP_Saskarta_Settings.tree.json', {
  asset: `${UI}/WBP_Saskarta_Settings`,
  tree: settingsTree(),
  slots: SETTINGS_SLOTS,
  variables: [...ROWS.map(ctl), ...ROWS.map((r) => `${r.id}Row`), ...ROWS.map((r) => `${r.id}Glow`), ...ROWS.filter((r) => r.kind === 'slider').map((r) => `${r.id}Value`),
    ...ROWS.filter((r) => r.kind === 'combo').flatMap((r) => [`${r.id}Prev`, `${r.id}Next`]),
    ...TABS.flatMap((t) => [`Tab${t.key}Button`, `Tab${t.key}Label`, `Tab${t.key}Bar`]), 'TabSwitcher', 'Description', 'ApplyButton', 'RevertButton', 'BackButton', 'ConfirmOverlay', 'CountdownText', 'KeepButton', 'RevertNowButton', 'PromptOverlay', 'DetectedText'],
});
out('WBP_Saskarta_Pause.tree.json', {
  asset: `${UI}/WBP_Saskarta_Pause`,
  tree: pauseTree(),
  slots: PAUSE_SLOTS,
  variables: menuVars(['Resume', 'Settings', 'Quit']),
});
console.log(`rows ${ROWS.length}, tabs ${TABS.length}`);
