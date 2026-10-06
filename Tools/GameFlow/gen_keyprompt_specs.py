"""Generate WBP_Saskarta_KeyPrompt: a key/button icon + label, the "professional game look" input prompt
(LANE5, task-PROMPTS-brief.md).

    python Tools/GameFlow/gen_keyprompt_specs.py   # -> specs/WBP_Saskarta_KeyPrompt.tree.json + .graph.json

The glyphs are the rasterised Kenney-based keycaps (Tools/UI/make_input_prompts.py), imported by
Tools/UI/import_input_prompts.py to /Game/SaskartaGaea/UI/Prompts/{Light,Dark}/T_Prompt_<Glyph>.

Layout: a soft umber plate (T_UI_SoftPlate, 55 %) holding [icon (+ a second icon, e.g. A + D)] [label].
The label is Aref Ruqaa (the caption font) 17 pt (~22 px), ivory, with a (1.5, 2) 60 % black shadow.
Hold mode draws the caption's gold ring (M_UI_SkipRing) around the icon; SetHoldProgress fills it.

Use from a host widget's graph: Configure(Glyph, Glyph2, GlyphPad, Label, bHold, IconSize), then Show / Hide.
- Glyph: keyboard glyph (Key_W); Glyph2: an optional second keyboard glyph (Key_D for A + D, else None);
  GlyphPad: the gamepad glyph (Pad_RT), None keeps Glyph.
- Device switching: while shown, a 0.1 s poll of the owning player picks the last device used (any gamepad
  button or stick past 0.25 -> gamepad; any of W A S D E R Space Esc or a mouse move over 2 px -> keyboard)
  and swaps the icon. (Done in the widget, not PC_Saskarta: no shared state, nothing for the carrier lane.)
- First Show only: a 0.9 s pulse (opacity 0 -> 1 in 0.2 s, icon scale 1.25 -> 1.0 -> 1.06 -> 1.0, the plate
  flashing to 80 % and settling at 55 %).
"""
from __future__ import annotations

import json
from pathlib import Path

from gen_debug_specs import G, KML, KSL, KSTR, KTXT, fn

ROOT = Path(__file__).resolve().parents[2]
WBP = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_KeyPrompt"
W = "/Script/UMG.Widget"
IMG = "/Script/UMG.Image"
SB = "/Script/UMG.SizeBox"
BORDER = "/Script/UMG.Border"
UW = "/Script/UMG.UserWidget"
PCC = "/Script/Engine.PlayerController"
AREF = "/Game/SaskartaGaea/GameFlow/UI/Fonts/F_ArefRuqaa_Caption.F_ArefRuqaa_Caption"
PLATE = "/Game/SaskartaGaea/GameFlow/UI/Textures/T_UI_SoftPlate.T_UI_SoftPlate"
RING = "/Game/SaskartaGaea/GameFlow/Materials/M_UI_SkipRing.M_UI_SkipRing"
DEFAULT_ICON = "/Game/SaskartaGaea/UI/Prompts/Light/T_Prompt_Key_W.T_Prompt_Key_W"
PROMPTS = "/Game/SaskartaGaea/UI/Prompts/"
IVORY = [0.84, 0.76, 0.63, 1]          # #ECE2CE in linear
UMBER = (0.0232, 0.0130, 0.0080)       # #2A1E16 in linear
PLATE_A, FLASH_A = 0.55, 0.80
STEP_S, PULSE_S = 0.02, 0.9
PAD_KEYS = ["Gamepad_FaceButton_Bottom", "Gamepad_FaceButton_Right", "Gamepad_FaceButton_Left", "Gamepad_FaceButton_Top",
            "Gamepad_RightTrigger", "Gamepad_LeftTrigger", "Gamepad_Special_Right", "Gamepad_DPad_Up"]
PAD_AXES = ["Gamepad_LeftX", "Gamepad_LeftY", "Gamepad_RightX", "Gamepad_RightY"]
KB_KEYS = ["W", "A", "S", "D", "E", "R", "SpaceBar", "Escape"]


def tree() -> dict:
    icon = lambda n, box, vis="Visible": {  # noqa: E731
        "class": "SizeBox", "name": box,
        "properties": {"bOverride_WidthOverride": True, "WidthOverride": 48, "bOverride_HeightOverride": True, "HeightOverride": 48,
                       "Visibility": vis},
        "slot_props": {"vertical_alignment": "Center"},
        "children": [{"class": "Image", "name": n, "properties": {"Brush": {"ResourceObject": DEFAULT_ICON, "ImageSize": {"X": 48, "Y": 48}, "DrawAs": "Image"}}}]}
    return {
        "asset": WBP,
        "tree": [{
            "class": "Border", "name": "Plate",
            "properties": {"Background": {"ResourceObject": PLATE, "DrawAs": "Box", "ImageSize": {"X": 110, "Y": 60},
                                          "Margin": {"Left": 0.4, "Top": 0.4, "Right": 0.4, "Bottom": 0.4},
                                          "TintColor": {"SpecifiedColor": [*UMBER, PLATE_A]}},
                           "Padding": {"Left": 16, "Top": 8, "Right": 20, "Bottom": 8}, "Visibility": "HitTestInvisible"},
            "children": [{"class": "HorizontalBox", "name": "Row", "children": [
                {"class": "Overlay", "name": "IconStack", "slot_props": {"vertical_alignment": "Center"}, "children": [
                    {"class": "HorizontalBox", "name": "Icons", "children": [icon("Icon", "IconBox"), icon("Icon2", "IconBox2", "Collapsed")]},
                    {"class": "Image", "name": "HoldRing",
                     "properties": {"Brush": {"ResourceObject": RING, "ImageSize": {"X": 62, "Y": 62}, "DrawAs": "Image"}, "Visibility": "Collapsed"},
                     "slot_props": {"horizontal_alignment": "Center", "vertical_alignment": "Center"}},
                ]},
                {"class": "TextBlock", "name": "LabelText",
                 "properties": {"Text": "Drive", "Font": {"FontObject": AREF, "Size": 17, "TypefaceFontName": "Regular"},
                                "ColorAndOpacity": {"SpecifiedColor": IVORY}, "ShadowOffset": {"X": 1.5, "Y": 2},
                                "ShadowColorAndOpacity": [0, 0, 0, 0.6]},
                 "slot_props": {"vertical_alignment": "Center", "padding": [10, 0, 0, 2]}},
            ]}],
        }],
        # The root stays the canvas: a canvas reports its auto-sized children as its desired size, so the prompt
        # sizes to its content inside a host's box.
        "slots": {"Plate": {"anchors": [0, 0, 0, 0], "position": [0, 0], "auto_size": True}},
        "variables": ["Plate", "IconStack", "IconBox", "Icon", "IconBox2", "Icon2", "HoldRing", "LabelText"],
    }


def vis(g, widget, visibility=None, pin=None):
    w = g.get(widget)
    c = g.call("SetVisibility", W, **({"InVisibility": visibility} if visibility else {}))
    g.link(f"{w}.{widget}", f"{c}.self")
    if pin:
        g.link(pin, f"{c}.InVisibility")
    return c


def build() -> dict:
    variables = [
        {"name": "Glyph", "type": "name", "default": "Key_W"}, {"name": "Glyph2", "type": "name", "default": "None"},
        {"name": "GlyphPad", "type": "name", "default": "None"}, {"name": "Label", "type": "text"},
        {"name": "Variant", "type": "name", "default": "Light"}, {"name": "bHold", "type": "bool", "default": "false"},
        {"name": "IconSize", "type": "float", "default": "48.0"}, {"name": "bGamepad", "type": "bool", "default": "false"},
        {"name": "bPulsed", "type": "bool", "default": "false"}, {"name": "PulseT", "type": "float", "default": "0.0"},
        {"name": "PulseTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "PollTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "Root", "type": "string", "default": PROMPTS},
        # hard references to every Light keycap (set on the CDO by editor/keyprompt_preload.py): they load with the
        # widget class, so the by-path lookup in Refresh finds them resident and never flushes async loading in play.
        {"name": "Preload", "type": "array<object:/Script/Engine.Texture2D>"},
    ]
    functions = [
        fn("Configure", [("InGlyph", "name"), ("InGlyph2", "name"), ("InGlyphPad", "name"), ("InLabel", "text"), ("bInHold", "bool"), ("InIconSize", "float")]),
        fn("Refresh"), fn("Show"), fn("Hide"), fn("PulseStep"), fn("PollDevice"),
        fn("GlyphPath", [("InGlyph", "name")], [("Path", "string")], pure=True),
        fn("SetHoldProgress", [("Fraction", "float")]),
    ]
    graphs = []

    # --- GlyphPath(Glyph) -> Root + Variant + "/T_Prompt_" + Glyph + ".T_Prompt_" + Glyph
    g = G("GlyphPath")
    e = g.add({"entry": True}, "entry")
    r = g.add({"result": True}, "result")
    gs = g.call("Conv_NameToString", KSTR)
    g.link(f"{e}.InGlyph", f"{gs}.InName")
    vs = g.call("Conv_NameToString", KSTR)
    g.link(f"{g.get('Variant')}.Variant", f"{vs}.InName")
    parts = [f"{g.get('Root')}.Root", f"{vs}.ReturnValue", None, f"{gs}.ReturnValue", None, f"{gs}.ReturnValue"]
    lits = {2: "/T_Prompt_", 4: ".T_Prompt_"}
    acc = None
    for i, p in enumerate(parts):
        if acc is None:
            acc = p
            continue
        c = g.call("Concat_StrStr", KSTR, **({"B": lits[i]} if p is None else {}))
        g.link(acc, f"{c}.A")
        if p is not None:
            g.link(p, f"{c}.B")
        acc = f"{c}.ReturnValue"
    g.link(acc, f"{r}.Path")
    g.chain(e, r)
    graphs.append(g.spec())

    # --- Configure: store and refresh
    g = G("Configure")
    e = g.add({"entry": True}, "entry")
    sets = []
    for src, var in (("InGlyph", "Glyph"), ("InGlyph2", "Glyph2"), ("InGlyphPad", "GlyphPad"), ("InLabel", "Label"), ("bInHold", "bHold"), ("InIconSize", "IconSize")):
        s = g.set(var)
        g.link(f"{e}.{src}", f"{s}.{var}")
        sets.append(s)
    g.chain(e, *sets, g.call("Refresh"))
    graphs.append(g.spec())

    # --- Refresh: icons (gamepad glyph when the pad is active and one is set), second icon, label, ring, sizes
    g = G("Refresh")
    e = g.add({"entry": True}, "entry")
    noPad = g.call("EqualEqual_NameName", KML, B="None")
    g.link(f"{g.get('GlyphPad')}.GlyphPad", f"{noPad}.A")
    notNoPad = g.call("Not_PreBool", KML)
    g.link(f"{noPad}.ReturnValue", f"{notNoPad}.A")
    useP = g.call("BooleanAND", KML)
    g.link(f"{g.get('bGamepad')}.bGamepad", f"{useP}.A")
    g.link(f"{notNoPad}.ReturnValue", f"{useP}.B")
    sel = g.call("SelectName", KML)
    g.link(f"{g.get('GlyphPad')}.GlyphPad", f"{sel}.A")
    g.link(f"{g.get('Glyph')}.Glyph", f"{sel}.B")
    g.link(f"{useP}.ReturnValue", f"{sel}.bPickA")

    loads = []

    def load(name_pin):
        p = g.call("GlyphPath")
        g.link(name_pin, f"{p}.InGlyph")
        sp = g.call("MakeSoftObjectPath", KSL)
        g.link(f"{p}.Path", f"{sp}.PathString")
        ref = g.call("Conv_SoftObjPathToSoftObjRef", KSL)
        g.link(f"{sp}.ReturnValue", f"{ref}.SoftObjectPath")
        ld = g.call("LoadAsset_Blocking", KSL)  # impure: chained before its SetBrushResourceObject
        g.link(f"{ref}.ReturnValue", f"{ld}.Asset")
        loads.append(ld)
        return f"{ld}.ReturnValue"

    b1 = g.call("SetBrushResourceObject", IMG)
    g.link(f"{g.get('Icon')}.Icon", f"{b1}.self")
    g.link(load(f"{sel}.ReturnValue"), f"{b1}.ResourceObject")
    # second icon: only for the keyboard, only when set
    no2 = g.call("EqualEqual_NameName", KML, B="None")
    g.link(f"{g.get('Glyph2')}.Glyph2", f"{no2}.A")
    hide2 = g.call("BooleanOR", KML)
    g.link(f"{no2}.ReturnValue", f"{hide2}.A")
    g.link(f"{useP}.ReturnValue", f"{hide2}.B")
    br2 = g.add({"branch": True}, "if2")
    g.link(f"{hide2}.ReturnValue", f"{br2}.Condition")
    h2 = vis(g, "IconBox2", "Collapsed")
    b2 = g.call("SetBrushResourceObject", IMG)
    g.link(f"{g.get('Icon2')}.Icon2", f"{b2}.self")
    g.link(load(f"{g.get('Glyph2')}.Glyph2"), f"{b2}.ResourceObject")
    s2 = vis(g, "IconBox2", "HitTestInvisible")
    # label (collapsed when empty)
    lt = g.call("SetText", "/Script/UMG.TextBlock")
    g.link(f"{g.get('LabelText')}.LabelText", f"{lt}.self")
    g.link(f"{g.get('Label')}.Label", f"{lt}.InText")
    emp = g.call("TextIsEmpty", KTXT)
    g.link(f"{g.get('Label')}.Label", f"{emp}.InText")
    brL = g.add({"branch": True}, "ifNoLabel")
    g.link(f"{emp}.ReturnValue", f"{brL}.Condition")
    lH, lS = vis(g, "LabelText", "Collapsed"), vis(g, "LabelText", "HitTestInvisible")
    brR = g.add({"branch": True}, "ifHold")
    g.link(f"{g.get('bHold')}.bHold", f"{brR}.Condition")
    rS, rH = vis(g, "HoldRing", "HitTestInvisible"), vis(g, "HoldRing", "Collapsed")
    sizes = []
    for box in ("IconBox", "IconBox2"):
        for fnm, pin in (("SetWidthOverride", "InWidthOverride"), ("SetHeightOverride", "InHeightOverride")):
            c = g.call(fnm, SB)
            g.link(f"{g.get(box)}.{box}", f"{c}.self")
            g.link(f"{g.get('IconSize')}.IconSize", f"{c}.{pin}")
            sizes.append(c)
    g.chain(e, loads[0], b1, br2)
    g.chain(f"{br2}.then", h2, lt)
    g.chain(f"{br2}.else", loads[1], b2, s2, lt)
    g.chain(lt, brL)
    g.chain(f"{brL}.then", lH, brR)
    g.chain(f"{brL}.else", lS, brR)
    g.chain(f"{brR}.then", rS, sizes[0])
    g.chain(f"{brR}.else", rH, sizes[0])
    g.chain(*sizes)
    graphs.append(g.spec())

    # --- Show: visible, refresh, the pulse once, start the device poll
    g = G("Show")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    sv = g.call("SetVisibility", W, InVisibility="HitTestInvisible")
    g.link(f"{me}.self", f"{sv}.self")
    clr0 = g.call("K2_ClearAndInvalidateTimerHandle", KSL)  # a repeated Show never stacks poll timers
    g.link(f"{g.get('PollTimer')}.PollTimer", f"{clr0}.Handle")
    rf = g.call("Refresh")
    br = g.add({"branch": True}, "ifPulsed")
    g.link(f"{g.get('bPulsed')}.bPulsed", f"{br}.Condition")
    sp = g.set("bPulsed", "true")
    st = g.set("PulseT", "0.0")
    tm = g.add({"timer": True}, "pulseTimer")
    g.defaults.update({f"{tm}.FunctionName": "PulseStep", f"{tm}.Time": str(STEP_S), f"{tm}.bLooping": "true"})
    sh = g.set("PulseTimer")
    g.link(f"{tm}.ReturnValue", f"{sh}.PulseTimer")
    pt = g.add({"timer": True}, "pollTimer")
    g.defaults.update({f"{pt}.FunctionName": "PollDevice", f"{pt}.Time": "0.1", f"{pt}.bLooping": "true"})
    ph = g.set("PollTimer")
    g.link(f"{pt}.ReturnValue", f"{ph}.PollTimer")
    g.chain(e, sv, clr0, rf, br)
    g.chain(f"{br}.else", sp, st, tm, sh, pt)
    g.chain(f"{br}.then", pt)
    g.chain(pt, ph)
    graphs.append(g.spec())

    # --- Hide
    g = G("Hide")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    sv = g.call("SetVisibility", W, InVisibility="Collapsed")
    g.link(f"{me}.self", f"{sv}.self")
    clr = g.call("K2_ClearAndInvalidateTimerHandle", KSL)
    g.link(f"{g.get('PollTimer')}.PollTimer", f"{clr}.Handle")
    g.chain(e, sv, clr)
    graphs.append(g.spec())

    # --- PulseStep: t += step; opacity = min(1, t / 0.2); scale = 1 + 0.25 * max(0, 1 - t / 0.3)
    #     + 0.06 * sin(pi * clamp((t - 0.35) / 0.55, 0, 1)); plate alpha = 0.55 + 0.25 * max(0, 1 - t / 0.5)
    g = G("PulseStep")
    e = g.add({"entry": True}, "entry")

    def op(fname, a, b=None, **kw):
        n = g.call(fname, KML, **kw)
        g.link(a, f"{n}.A")
        if b is not None:
            g.link(b, f"{n}.B")
        return f"{n}.ReturnValue"

    t = op("Add_DoubleDouble", f"{g.get('PulseT')}.PulseT", B=str(STEP_S))
    st = g.set("PulseT")
    g.link(t, f"{st}.PulseT")
    T = f"{g.get('PulseT')}.PulseT"
    opa = op("FMin", op("Divide_DoubleDouble", T, B="0.2"), B="1.0")
    def one_minus(x):
        n = g.call("Subtract_DoubleDouble", KML, A="1.0")
        g.link(x, f"{n}.B")
        return f"{n}.ReturnValue"

    first = op("Multiply_DoubleDouble", op("FMax", one_minus(op("Divide_DoubleDouble", T, B="0.3")), B="0.0"), B="0.25")
    cl = g.call("FClamp", KML, Min="0.0", Max="1.0")
    g.link(op("Divide_DoubleDouble", op("Subtract_DoubleDouble", T, B="0.35"), B="0.55"), f"{cl}.Value")
    sn = g.call("Sin", KML)
    g.link(op("Multiply_DoubleDouble", f"{cl}.ReturnValue", B="3.14159"), f"{sn}.A")
    bump = op("Multiply_DoubleDouble", f"{sn}.ReturnValue", B="0.06")
    sc = op("Add_DoubleDouble", op("Add_DoubleDouble", first, bump), B="1.0")
    alpha = op("Add_DoubleDouble", op("Multiply_DoubleDouble", op("FMax", one_minus(op("Divide_DoubleDouble", T, B="0.5")), B="0.0"), B=str(FLASH_A - PLATE_A)), B=str(PLATE_A))
    me = g.add({"self": True})
    so = g.call("SetRenderOpacity", W)
    g.link(f"{me}.self", f"{so}.self")
    g.link(opa, f"{so}.InOpacity")
    v = g.call("MakeVector2D", KML)
    g.link(sc, f"{v}.X")
    g.link(sc, f"{v}.Y")
    rs = g.call("SetRenderScale", W)
    g.link(f"{g.get('IconStack')}.IconStack", f"{rs}.self")
    g.link(f"{v}.ReturnValue", f"{rs}.Scale")
    col = g.call("MakeColor", KML, R=str(UMBER[0]), G=str(UMBER[1]), B=str(UMBER[2]))
    g.link(alpha, f"{col}.A")
    bc = g.call("SetBrushColor", BORDER)
    g.link(f"{g.get('Plate')}.Plate", f"{bc}.self")
    g.link(f"{col}.ReturnValue", f"{bc}.InBrushColor")
    done = op("GreaterEqual_DoubleDouble", T, B=str(PULSE_S))
    br = g.add({"branch": True}, "ifDone")
    g.link(done, f"{br}.Condition")
    clr = g.call("K2_ClearAndInvalidateTimerHandle", KSL)
    g.link(f"{g.get('PulseTimer')}.PulseTimer", f"{clr}.Handle")
    g.chain(e, st, so, rs, bc, br)
    g.chain(f"{br}.then", clr)
    graphs.append(g.spec())

    # --- PollDevice: last device used
    g = G("PollDevice")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    pc = g.call("GetOwningPlayer", UW)
    g.link(f"{me}.self", f"{pc}.self")
    PC = f"{pc}.ReturnValue"
    owner_valid = g.call("IsValid", KSL, name="ownerValid")
    g.link(PC, f"{owner_valid}.Object")
    owner_gate = g.add({"branch": True}, "ifOwnerValid")
    g.link(f"{owner_valid}.ReturnValue", f"{owner_gate}.Condition")

    def any_of(pins):
        acc = pins[0]
        for p in pins[1:]:
            o = g.call("BooleanOR", KML)
            g.link(acc, f"{o}.A")
            g.link(p, f"{o}.B")
            acc = f"{o}.ReturnValue"
        return acc

    def key_down(k):
        c = g.call("IsInputKeyDown", PCC, Key=k)
        g.link(PC, f"{c}.self")
        return f"{c}.ReturnValue"

    def axis(k):
        c = g.call("GetInputAnalogKeyState", PCC, Key=k)
        g.link(PC, f"{c}.self")
        a = g.call("Abs", KML)
        g.link(f"{c}.ReturnValue", f"{a}.A")
        gt = g.call("Greater_DoubleDouble", KML, B="0.25")
        g.link(f"{a}.ReturnValue", f"{gt}.A")
        return f"{gt}.ReturnValue"

    pad = any_of([key_down(k) for k in PAD_KEYS] + [axis(k) for k in PAD_AXES])
    md = g.call("GetInputMouseDelta", PCC)
    g.link(PC, f"{md}.self")
    mx = g.call("Abs", KML)
    g.link(f"{md}.DeltaX", f"{mx}.A")
    my = g.call("Abs", KML)
    g.link(f"{md}.DeltaY", f"{my}.A")
    msum = g.call("Add_DoubleDouble", KML)
    g.link(f"{mx}.ReturnValue", f"{msum}.A")
    g.link(f"{my}.ReturnValue", f"{msum}.B")
    mv = g.call("Greater_DoubleDouble", KML, B="2.0")
    g.link(f"{msum}.ReturnValue", f"{mv}.A")
    kb = any_of([key_down(k) for k in KB_KEYS] + [f"{mv}.ReturnValue"])
    # new = pad ? true : (kb ? false : bGamepad)  ==  pad OR (NOT kb AND bGamepad)
    nkb = g.call("Not_PreBool", KML)
    g.link(kb, f"{nkb}.A")
    keep = g.call("BooleanAND", KML)
    g.link(f"{nkb}.ReturnValue", f"{keep}.A")
    g.link(f"{g.get('bGamepad')}.bGamepad", f"{keep}.B")
    new = any_of([pad, f"{keep}.ReturnValue"])
    ne = g.call("NotEqual_BoolBool", KML)
    g.link(new, f"{ne}.A")
    g.link(f"{g.get('bGamepad')}.bGamepad", f"{ne}.B")
    br = g.add({"branch": True}, "ifChanged")
    g.link(f"{ne}.ReturnValue", f"{br}.Condition")
    s = g.set("bGamepad")
    g.link(new, f"{s}.bGamepad")
    g.chain(e, owner_gate)
    g.chain(f"{owner_gate}.then", br)
    g.chain(f"{br}.then", s, g.call("Refresh"))
    graphs.append(g.spec())

    # --- SetHoldProgress: the ring material's Pct
    g = G("SetHoldProgress")
    e = g.add({"entry": True}, "entry")
    dm = g.call("GetDynamicMaterial", IMG)
    g.link(f"{g.get('HoldRing')}.HoldRing", f"{dm}.self")
    sp = g.call("SetScalarParameterValue", "/Script/Engine.MaterialInstanceDynamic", ParameterName="Pct")
    g.link(f"{dm}.ReturnValue", f"{sp}.self")
    g.link(f"{e}.Fraction", f"{sp}.Value")
    g.chain(e, dm, sp)
    graphs.append(g.spec())

    # --- EventGraph: Construct -> Refresh (the designer / first frame shows the configured glyph)
    g = G("EventGraph")
    ev = g.add({"event": "Construct"}, "construct")
    g.chain(ev, g.call("Refresh"))
    destruct = g.add({"event": "Destruct"}, "destruct")
    poll_handle = g.get("PollTimer")
    clear_poll = g.call("K2_ClearAndInvalidateTimerHandle", KSL, name="clearPollOnDestruct")
    g.link(f"{poll_handle}.PollTimer", f"{clear_poll}.Handle")
    pulse_handle = g.get("PulseTimer")
    clear_pulse = g.call("K2_ClearAndInvalidateTimerHandle", KSL, name="clearPulseOnDestruct")
    g.link(f"{pulse_handle}.PulseTimer", f"{clear_pulse}.Handle")
    g.chain(destruct, clear_poll, clear_pulse)
    graphs.append(g.spec())

    return {"asset": WBP, "description": "LANE5 key prompt (icon + label). Generated by Tools/GameFlow/gen_keyprompt_specs.py.",
            "variables": variables, "functions": functions, "graphs": graphs}


if __name__ == "__main__":
    specs = ROOT / "Tools" / "GameFlow" / "specs"
    (specs / "WBP_Saskarta_KeyPrompt.tree.json").write_text(json.dumps(tree(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (specs / "WBP_Saskarta_KeyPrompt.graph.json").write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote tree + graph")
