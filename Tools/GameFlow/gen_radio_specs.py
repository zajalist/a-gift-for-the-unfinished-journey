"""Generate the player-facing radio specs (LANE5, README_Radio.md).

    python Tools/GameFlow/gen_radio_specs.py

Outputs (Tools/GameFlow/specs/):
  WBP_Saskarta_Radio.tree.json    the small diegetic radio panel (bottom right)
  WBP_Saskarta_Radio.graph.json   its poll loop: the R / D-pad-up toggle, the signal meter, the fade
  BP_Saskarta_HUD.json            the HUD class that puts the panel on screen (GM_Saskarta.HUDClass)

The station itself is C++ (USaskartaRadioStation + DA_Station). This panel only reads it
(GetReceptionQuality, IsAudible), flips the existing setting (USaskartaStorySettings.SetRadioStation,
mirrored in the cvar saskarta.radio, saved in GameUserSettings) and plays the knob click and the static
in/out bursts. The station reacts on its own 0.25 s clock: off fades it over 1 s, on runs its tune sweep.
"""
from __future__ import annotations

import json
from pathlib import Path

from gen_debug_specs import G, KML, KSL, KSTR, KTXT, GS, RUNNER, fn, runner

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "Tools" / "GameFlow" / "specs"

WBP = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Radio"
WBP_C = WBP + ".WBP_Saskarta_Radio_C"
HUD = "/Game/SaskartaGaea/GameFlow/BP_Saskarta_HUD"
STATION = "/Script/SaskartaCore.SaskartaRadioStation"
SETTINGS = "/Script/SaskartaCore.SaskartaStorySettings"
PCB = "/Script/Engine.PlayerController"

MONO = "/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal.Font_Terminal"
IVORY = [0.70, 0.65, 0.54, 0.92]
EMBER = [0.76, 0.44, 0.19, 0.95]
DIM_EMBER = [0.49, 0.30, 0.16, 0.76]
SOFT_PLATE = "/Game/SaskartaGaea/GameFlow/UI/Textures/T_UI_SoftPlate.T_UI_SoftPlate"
# Build editor/radio_crt.py before ui_build_tree. Keep the scrim outside the effect.
RADIO_CRT = "/Game/SaskartaGaea/GameFlow/Materials/MI_UI_RadioCRT.MI_UI_RadioCRT"

RFX = "/Game/SaskartaGaea/Audio/Radio"   # task RADIOFX, imported from Saved/GameAudio/Radio
SFX_KNOB_ON = f"{RFX}/SFX_Radio_Knob_On_01.SFX_Radio_Knob_On_01"
SFX_KNOB_OFF = f"{RFX}/SFX_Radio_Knob_Off_01.SFX_Radio_Knob_Off_01"
SFX_IN = f"{RFX}/SFX_Radio_Power_On_Bloom.SFX_Radio_Power_On_Bloom"
SFX_OUT = f"{RFX}/SFX_Radio_Power_Off_Collapse.SFX_Radio_Power_Off_Collapse"

KEYPROMPT_C = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_KeyPrompt.WBP_Saskarta_KeyPrompt_C"
# OnRadioGlitch one-shots (the station itself does the dips, the static swell and the pitch): two variants each,
# picked at random; volume = base x intensity. PitchJitter has no sound.
GLITCHES = ["Dropout", "Crackle", "NoiseBurst", "PitchJitter", "Drift", "Squeal"]
GLITCH_SFX = {
    "Dropout": ("SFX_Radio_Dropout_01", "SFX_Radio_Dropout_04", 0.55),
    "Crackle": ("SFX_Radio_Tune_Click_02", "SFX_Radio_Tune_Click_03", 0.35),
    "NoiseBurst": ("SFX_Radio_Lightning_02", "SFX_Radio_Lightning_03", 0.3),
    "Drift": ("SFX_Radio_Tune_Sweep_02", "SFX_Radio_Tune_Sweep_04", 0.25),
    "Squeal": ("SFX_Radio_Tune_BandScan_01", "SFX_Radio_Tune_Sweep_05", 0.2),
}
SHOW_S = 4.0
POLL_S = 0.1  # PERF-URGENT: 10 Hz (was 20 Hz); the opacity interp uses the same step


def text(name, s, size, color, tracking=0):
    return {"class": "TextBlock", "name": name,
            "properties": {"Text": s, "Font": {"FontObject": MONO, "Size": size, "LetterSpacing": tracking},
                           "ColorAndOpacity": {"SpecifiedColor": color}}}


def tree() -> dict:
    return {
        "asset": WBP,
        "tree": [
            {"class": "Border", "name": "Panel",
             "properties": {"BrushColor": [0, 0, 0, 0], "Padding": {"Left": 0, "Top": 0, "Right": 0, "Bottom": 0},
                            "RenderOpacity": 0.0, "Visibility": "HitTestInvisible"},
             "children": [
                 {"class": "Overlay", "name": "PanelLayers", "children": [
                     {"class": "Border", "name": "ScreenScrim",
                      "properties": {"Background": {"ResourceObject": SOFT_PLATE, "DrawAs": "Box",
                                                     "ImageSize": {"X": 304, "Y": 104},
                                                     "Margin": {"Left": 0.4, "Top": 0.4, "Right": 0.4, "Bottom": 0.4},
                                                     "TintColor": {"SpecifiedColor": [0.018, 0.013, 0.009, 0.64]}},
                                     "Visibility": "HitTestInvisible"}},
                     {"class": "RetainerBox", "name": "RadioScreen",
                      "properties": {"EffectMaterial": RADIO_CRT, "TextureParameter": "Texture",
                                     "RenderOnInvalidation": True, "RenderOnPhase": False},
                      "slot_props": {"padding": [10, 6, 10, 6]},
                      "children": [
                          {"class": "VerticalBox", "name": "Layout", "children": [
                              {"class": "HorizontalBox", "name": "Dial", "children": [
                                  {"class": "SizeBox", "name": "StationNameBox",
                                   "properties": {"bOverride_WidthOverride": True, "WidthOverride": 96},
                                   "slot_props": {"vertical_alignment": "Center"},
                                   "children": [{**text("StationName", "ILAAWB", 16, EMBER, 18),
                                                 "slot_props": {"vertical_alignment": "Center"}}]},
                                  {"class": "Spacer", "name": "DialGap", "slot_props": {"fill": 1}},
                                  {**text("FreqText", "94.3 FM", 18, IVORY, 12),
                                   "slot_props": {"vertical_alignment": "Center"}},
                              ]},
                              {"class": "SizeBox", "name": "TopRuleBox",
                               "properties": {"bOverride_HeightOverride": True, "HeightOverride": 1},
                               "slot_props": {"padding": [0, 1, 0, 2]},
                               "children": [{"class": "Border", "name": "TopRule",
                                             "properties": {"BrushColor": [0.43, 0.25, 0.12, 0.48]}}]},
                              {**text("ScaleText", "88     90     94     98    108", 13, DIM_EMBER, 10),
                               "slot_props": {"padding": [1, 0, 0, 1]}},
                              {"class": "SizeBox", "name": "SignalTrack",
                               "properties": {"bOverride_HeightOverride": True, "HeightOverride": 3},
                               "slot_props": {"padding": [0, 0, 0, 3]},
                               "children": [{"class": "ProgressBar", "name": "SignalBar",
                                             "properties": {"Percent": 0.8, "FillColorAndOpacity": [1, 1, 1, 1],
                                                            "BarFillType": "LeftToRight",
                                                            "WidgetStyle": {
                                                                "BackgroundImage": {"DrawAs": "Image", "TintColor": {"SpecifiedColor": [0.18, 0.11, 0.06, 0.34]}},
                                                                "FillImage": {"DrawAs": "Image", "TintColor": {"SpecifiedColor": EMBER}},
                                                                "MarqueeImage": {"DrawAs": "NoDrawType"}}}}]},
                              {"class": "HorizontalBox", "name": "PowerRow", "children": [
                                  {**text("NowText", "on air", 16, IVORY),
                                   "slot_props": {"vertical_alignment": "Center"}},
                                  {"class": "Spacer", "name": "StateGap", "slot_props": {"fill": 1}},
                                  {**text("PowerText", "ON", 15, EMBER, 12),
                                   "slot_props": {"vertical_alignment": "Center", "padding": [0, 0, 6, 0]}},
                                  {"class": "SizeBox", "name": "RadioKeyCompact",
                                   "properties": {"bOverride_HeightOverride": True, "HeightOverride": 36},
                                   "slot_props": {"vertical_alignment": "Center"},
                                   "children": [{"class": KEYPROMPT_C, "name": "RadioKey"}]},
                              ]},
                          ]},
                      ]},
                 ]},
             ]},
        ],
        "slots": {"Panel": {"anchors": [1, 1, 1, 1], "position": [-340, -140], "size": [304, 104]}},
        "variables": ["Panel", "SignalBar", "NowText", "PowerText", "RadioKey"],
    }


def graph() -> dict:
    variables = [
        {"name": "PollTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "bROld", "type": "bool", "default": "false"},
        {"name": "bUpOld", "type": "bool", "default": "false"},
        {"name": "ShownUntil", "type": "float", "default": "0.0"},
        {"name": "Opacity", "type": "float", "default": "0.0"},
        {"name": "bLastAudible", "type": "bool", "default": "false"},
        {"name": "bLastOn", "type": "bool", "default": "true"},
        {"name": "TextOn", "type": "text", "default": "ON"},
        {"name": "TextOff", "type": "text", "default": "OFF"},
        {"name": "TextArchive", "type": "text", "default": "INCOMING ARCHIVE"},
        {"name": "NoLabel", "type": "text"},
        {"name": "TextAir", "type": "text", "default": "on air"},
        {"name": "TextStatic", "type": "text", "default": "static . . ."},
        {"name": "TextSilent", "type": "text", "default": "no signal"},
    ]
    functions = [fn("Poll"), fn("Toggle"), fn("ShowFor4s"),
                 fn("HandleForcedOn", [("BeatId", "name")]), fn("HandleForcedOff", [("bRadioOnAfter", "bool")]),
                 fn("HandleGlitch", [("Type", "enum:/Script/SaskartaCore.ESaskartaRadioGlitch"), ("DurationS", "float"), ("Intensity", "float")])]
    graphs = []

    # Construct -> Poll every POLL_S (0.1 s)
    g = G("EventGraph")
    ev = g.add({"event": "Construct"}, "construct")
    tm = g.add({"timer": True}, "timer")
    g.defaults.update({f"{tm}.FunctionName": "Poll", f"{tm}.Time": str(POLL_S), f"{tm}.bLooping": "true"})
    st = g.set("PollTimer")
    g.link(f"{tm}.ReturnValue", f"{st}.PollTimer")
    rk = g.get("RadioKey")
    cfg = g.call("Configure", KEYPROMPT_C, InGlyph="Key_R", InGlyph2="None", InGlyphPad="Pad_DPad_Up", bInHold="false", InIconSize="20.0")
    g.link(f"{rk}.RadioKey", f"{cfg}.self")
    nl = g.get("NoLabel")
    g.link(f"{nl}.NoLabel", f"{cfg}.InLabel")
    rk2 = g.get("RadioKey")
    shw = g.call("Show", KEYPROMPT_C)
    g.link(f"{rk2}.RadioKey", f"{shw}.self")
    g.chain(ev, tm, st, cfg, shw)
    destruct = g.add({"event": "Destruct"}, "destruct")
    poll_handle = g.get("PollTimer")
    clear_poll = g.call("K2_ClearAndInvalidateTimerHandle", KSL, name="clearPollOnDestruct")
    g.link(f"{poll_handle}.PollTimer", f"{clear_poll}.Handle")
    g.chain(destruct, clear_poll)
    graphs.append(g.spec())

    def station(g):
        me = g.add({"self": True})
        stn = g.call("GetRadioStation", STATION)
        g.link(f"{me}.self", f"{stn}.WorldContextObject")
        return f"{stn}.ReturnValue"

    def sound(g, path, vol):
        me = g.add({"self": True})
        n = g.call("PlaySound2D", GS, Sound=path, VolumeMultiplier=str(vol))
        g.link(f"{me}.self", f"{n}.WorldContextObject")
        return n

    # HandleForcedOn: an archive line forces the radio on: knob + bloom; the panel stays up (Poll) while forced
    g = G("HandleForcedOn")
    e = g.add({"entry": True}, "entry")
    g.chain(e, sound(g, SFX_KNOB_ON, 0.8), sound(g, SFX_IN, 0.6), g.call("ShowFor4s"))
    graphs.append(g.spec())

    # HandleForcedOff: back to the player's state; if the radio was off: knob + collapse
    g = G("HandleForcedOff")
    e = g.add({"entry": True}, "entry")
    br = g.add({"branch": True}, "ifOnAfter")
    g.link(f"{e}.bRadioOnAfter", f"{br}.Condition")
    g.chain(e, br)
    g.chain(f"{br}.else", sound(g, SFX_KNOB_OFF, 0.8), sound(g, SFX_OUT, 0.6), g.call("ShowFor4s"))
    graphs.append(g.spec())

    # HandleGlitch: a one-shot per glitch type (random of two variants), scaled by the intensity
    g = G("HandleGlitch")
    e = g.add({"entry": True}, "entry")
    prev = None
    for kind, (a, b, base) in GLITCH_SFX.items():
        tb = g.call("Conv_ByteToInt", KML)
        g.link(f"{e}.Type", f"{tb}.InByte")
        eq = g.call("EqualEqual_IntInt", KML, B=str(GLITCHES.index(kind)))
        g.link(f"{tb}.ReturnValue", f"{eq}.A")
        br = g.add({"branch": True}, "if" + kind)
        g.link(f"{eq}.ReturnValue", f"{br}.Condition")
        rb = g.call("RandomBool", KML)
        so = g.call("SelectObject", KML, A=f"{RFX}/{a}.{a}", B=f"{RFX}/{b}.{b}")
        g.link(f"{rb}.ReturnValue", f"{so}.bSelectA")
        cast = g.add({"cast": "/Script/Engine.SoundBase"}, "cast" + kind)
        g.link(f"{so}.ReturnValue", f"{cast}.Object")
        vol = g.call("Multiply_DoubleDouble", KML, B=str(base))
        g.link(f"{e}.Intensity", f"{vol}.A")
        me = g.add({"self": True})
        ps = g.call("PlaySound2D", GS)
        g.link(f"{me}.self", f"{ps}.WorldContextObject")
        g.link(f"{cast}.As", f"{ps}.Sound")
        g.link(f"{vol}.ReturnValue", f"{ps}.VolumeMultiplier")
        g.chain(e if prev is None else f"{prev}.else", br)
        g.chain(f"{br}.then", cast, ps)
        prev = br
    graphs.append(g.spec())

    # ShowFor4s: ShownUntil = now + 4
    g = G("ShowFor4s")
    e = g.add({"entry": True}, "entry")
    now = g.call("GetTimeSeconds", GS)
    me = g.add({"self": True})
    g.link(f"{me}.self", f"{now}.WorldContextObject")
    add = g.call("Add_DoubleDouble", KML, B=str(SHOW_S))
    g.link(f"{now}.ReturnValue", f"{add}.A")
    s = g.set("ShownUntil")
    g.link(f"{add}.ReturnValue", f"{s}.ShownUntil")
    g.chain(e, s)
    graphs.append(g.spec())

    # Toggle: only in Playing; flip the setting; click + static burst; show
    g = G("Toggle")
    e = g.add({"entry": True}, "entry")
    r = runner(g)
    runner_valid = g.call("IsValid", KSL, name="runnerValid")
    g.link(f"{r}.ReturnValue", f"{runner_valid}.Object")
    runner_gate = g.add({"branch": True}, "ifRunnerValid")
    fs = g.call("GetFlowState", RUNNER)
    g.link(f"{r}.ReturnValue", f"{fs}.self")
    playing = g.call("EqualEqual_NameName", KML, B="Playing")
    g.link(f"{fs}.ReturnValue", f"{playing}.A")
    br = g.add({"branch": True}, "ifPlaying")
    g.link(f"{playing}.ReturnValue", f"{br}.Condition")
    stn0 = station(g)
    station_valid = g.call("IsValid", KSL, name="stationValid")
    g.link(stn0, f"{station_valid}.Object")
    station_gate = g.add({"branch": True}, "ifStationValid")
    on = g.call("IsRadioOn", STATION)
    g.link(stn0, f"{on}.self")
    notOn = g.call("Not_PreBool", KML)
    g.link(f"{on}.ReturnValue", f"{notOn}.A")
    setr = g.call("SetRadioOn", STATION)
    g.link(stn0, f"{setr}.self")
    g.link(f"{notOn}.ReturnValue", f"{setr}.bOn")
    ifOn = g.add({"branch": True}, "ifNowOn")
    g.link(f"{notOn}.ReturnValue", f"{ifOn}.Condition")
    me2 = g.add({"self": True})
    kOn = g.call("PlaySound2D", GS, Sound=SFX_KNOB_ON, VolumeMultiplier="0.8")
    sIn = g.call("PlaySound2D", GS, Sound=SFX_IN, VolumeMultiplier="0.7")
    kOff = g.call("PlaySound2D", GS, Sound=SFX_KNOB_OFF, VolumeMultiplier="0.8")
    sOut = g.call("PlaySound2D", GS, Sound=SFX_OUT, VolumeMultiplier="0.7")
    for n in (kOn, sIn, kOff, sOut):
        g.link(f"{me2}.self", f"{n}.WorldContextObject")
    show = g.call("ShowFor4s")
    show2 = g.call("ShowFor4s")
    g.link(f"{runner_valid}.ReturnValue", f"{runner_gate}.Condition")
    g.link(f"{station_valid}.ReturnValue", f"{station_gate}.Condition")
    g.chain(e, runner_gate)
    g.chain(f"{runner_gate}.then", station_gate)
    g.chain(f"{station_gate}.then", br)
    g.chain(f"{br}.then", setr, ifOn)
    g.chain(f"{ifOn}.then", kOn, sIn, show)
    g.chain(f"{ifOn}.else", kOff, sOut, show2)
    graphs.append(g.spec())

    # Poll: key edges, state-change flash, meter, texts, fade
    g = G("Poll")
    e = g.add({"entry": True}, "entry")
    pc = g.call("GetOwningPlayer", "/Script/UMG.Widget")
    owner_valid = g.call("IsValid", KSL, name="ownerValid")
    g.link(f"{pc}.ReturnValue", f"{owner_valid}.Object")
    owner_gate = g.add({"branch": True}, "ifOwnerValid")
    g.link(f"{owner_valid}.ReturnValue", f"{owner_gate}.Condition")
    stnGuard = station(g)
    station_valid = g.call("IsValid", KSL, name="stationValid")
    g.link(stnGuard, f"{station_valid}.Object")
    station_gate = g.add({"branch": True}, "ifStationValid")
    g.link(f"{station_valid}.ReturnValue", f"{station_gate}.Condition")
    rGuard = runner(g)
    runner_valid = g.call("IsValid", KSL, name="runnerValid")
    g.link(f"{rGuard}.ReturnValue", f"{runner_valid}.Object")
    runner_gate = g.add({"branch": True}, "ifRunnerValid")
    g.link(f"{runner_valid}.ReturnValue", f"{runner_gate}.Condition")
    kR = g.call("IsInputKeyDown", PCB, Key="R")
    g.link(f"{pc}.ReturnValue", f"{kR}.self")
    kU = g.call("IsInputKeyDown", PCB, Key="Gamepad_DPad_Up")
    g.link(f"{pc}.ReturnValue", f"{kU}.self")
    oldR = g.get("bROld")
    oldU = g.get("bUpOld")
    nR = g.call("Not_PreBool", KML)
    g.link(f"{oldR}.bROld", f"{nR}.A")
    nU = g.call("Not_PreBool", KML)
    g.link(f"{oldU}.bUpOld", f"{nU}.A")
    edgeR = g.call("BooleanAND", KML)
    g.link(f"{kR}.ReturnValue", f"{edgeR}.A")
    g.link(f"{nR}.ReturnValue", f"{edgeR}.B")
    edgeU = g.call("BooleanAND", KML)
    g.link(f"{kU}.ReturnValue", f"{edgeU}.A")
    g.link(f"{nU}.ReturnValue", f"{edgeU}.B")
    edge = g.call("BooleanOR", KML)
    g.link(f"{edgeR}.ReturnValue", f"{edge}.A")
    g.link(f"{edgeU}.ReturnValue", f"{edge}.B")
    brKey = g.add({"branch": True}, "ifPressed")
    g.link(f"{edge}.ReturnValue", f"{brKey}.Condition")
    tog = g.call("Toggle")
    sR = g.set("bROld")
    g.link(f"{kR}.ReturnValue", f"{sR}.bROld")
    sU = g.set("bUpOld")
    g.link(f"{kU}.ReturnValue", f"{sU}.bUpOld")

    # state change -> show
    me = g.add({"self": True})
    stn = g.call("GetRadioStation", STATION)
    g.link(f"{me}.self", f"{stn}.WorldContextObject")
    aud = g.call("IsAudible", STATION)
    g.link(f"{stn}.ReturnValue", f"{aud}.self")
    q = g.call("GetReceptionQuality", STATION)
    g.link(f"{stn}.ReturnValue", f"{q}.self")
    on = g.call("IsRadioEffectivelyOn", STATION)
    g.link(f"{stn}.ReturnValue", f"{on}.self")
    forced = g.call("IsRadioForcedOn", STATION)
    g.link(f"{stn}.ReturnValue", f"{forced}.self")
    la = g.get("bLastAudible")
    lo = g.get("bLastOn")
    ca = g.call("NotEqual_BoolBool", KML)
    g.link(f"{aud}.ReturnValue", f"{ca}.A")
    g.link(f"{la}.bLastAudible", f"{ca}.B")
    co = g.call("NotEqual_BoolBool", KML)
    g.link(f"{on}.ReturnValue", f"{co}.A")
    g.link(f"{lo}.bLastOn", f"{co}.B")
    changed = g.call("BooleanOR", KML)
    g.link(f"{ca}.ReturnValue", f"{changed}.A")
    g.link(f"{co}.ReturnValue", f"{changed}.B")
    brCh = g.add({"branch": True}, "ifChanged")
    g.link(f"{changed}.ReturnValue", f"{brCh}.Condition")
    show = g.call("ShowFor4s")
    sLa = g.set("bLastAudible")
    g.link(f"{aud}.ReturnValue", f"{sLa}.bLastAudible")
    sLo = g.set("bLastOn")
    g.link(f"{on}.ReturnValue", f"{sLo}.bLastOn")

    # meter (0 when off)
    qOn = g.call("SelectFloat", KML, B="0.0")
    g.link(f"{q}.ReturnValue", f"{qOn}.A")
    g.link(f"{on}.ReturnValue", f"{qOn}.bPickA")
    bar = g.get("SignalBar")
    setP = g.call("SetPercent", "/Script/UMG.ProgressBar")
    g.link(f"{bar}.SignalBar", f"{setP}.self")
    g.link(f"{qOn}.ReturnValue", f"{setP}.InPercent")

    # now text: off -> "no signal"; audible -> "on air"; else "static . . ."
    tAir, tSt, tSil = g.get("TextAir"), g.get("TextStatic"), g.get("TextSilent")
    s1 = g.call("SelectText", KML)
    g.link(f"{tAir}.TextAir", f"{s1}.A")
    g.link(f"{tSt}.TextStatic", f"{s1}.B")
    g.link(f"{aud}.ReturnValue", f"{s1}.bPickA")
    s2 = g.call("SelectText", KML)
    g.link(f"{s1}.ReturnValue", f"{s2}.A")
    g.link(f"{tSil}.TextSilent", f"{s2}.B")
    g.link(f"{on}.ReturnValue", f"{s2}.bPickA")
    nowT = g.get("NowText")
    setNow = g.call("SetText", "/Script/UMG.TextBlock")
    g.link(f"{nowT}.NowText", f"{setNow}.self")
    g.link(f"{s2}.ReturnValue", f"{setNow}.InText")
    tOn, tOff = g.get("TextOn"), g.get("TextOff")
    s3a = g.call("SelectText", KML)
    g.link(f"{tOn}.TextOn", f"{s3a}.A")
    g.link(f"{tOff}.TextOff", f"{s3a}.B")
    g.link(f"{on}.ReturnValue", f"{s3a}.bPickA")
    tArc = g.get("TextArchive")
    s3 = g.call("SelectText", KML)
    g.link(f"{tArc}.TextArchive", f"{s3}.A")
    g.link(f"{s3a}.ReturnValue", f"{s3}.B")
    g.link(f"{forced}.ReturnValue", f"{s3}.bPickA")
    powT = g.get("PowerText")
    setPow = g.call("SetText", "/Script/UMG.TextBlock")
    g.link(f"{powT}.PowerText", f"{setPow}.self")
    g.link(f"{s3}.ReturnValue", f"{setPow}.InText")

    # fade: target 1 while shown or R held, and only while FlowState is Playing
    now = g.call("GetTimeSeconds", GS)
    me3 = g.add({"self": True})
    g.link(f"{me3}.self", f"{now}.WorldContextObject")
    su = g.get("ShownUntil")
    shown = g.call("Less_DoubleDouble", KML)
    g.link(f"{now}.ReturnValue", f"{shown}.A")
    g.link(f"{su}.ShownUntil", f"{shown}.B")
    vis0 = g.call("BooleanOR", KML)
    g.link(f"{shown}.ReturnValue", f"{vis0}.A")
    g.link(f"{kR}.ReturnValue", f"{vis0}.B")
    vis = g.call("BooleanOR", KML)
    g.link(f"{vis0}.ReturnValue", f"{vis}.A")
    g.link(f"{forced}.ReturnValue", f"{vis}.B")
    r = runner(g)
    fs = g.call("GetFlowState", RUNNER)
    g.link(f"{r}.ReturnValue", f"{fs}.self")
    playing = g.call("EqualEqual_NameName", KML, B="Playing")
    g.link(f"{fs}.ReturnValue", f"{playing}.A")
    want = g.call("BooleanAND", KML)
    g.link(f"{vis}.ReturnValue", f"{want}.A")
    g.link(f"{playing}.ReturnValue", f"{want}.B")
    tgt = g.call("SelectFloat", KML, A="1.0", B="0.0")
    g.link(f"{want}.ReturnValue", f"{tgt}.bPickA")
    op = g.get("Opacity")
    interp = g.call("FInterpTo_Constant", KML, DeltaTime=str(POLL_S), InterpSpeed="2.5")
    g.link(f"{op}.Opacity", f"{interp}.Current")
    g.link(f"{tgt}.ReturnValue", f"{interp}.Target")
    sOp = g.set("Opacity")
    g.link(f"{interp}.ReturnValue", f"{sOp}.Opacity")
    op2 = g.get("Opacity")
    panel = g.get("Panel")
    setO = g.call("SetRenderOpacity", "/Script/UMG.Widget")
    g.link(f"{panel}.Panel", f"{setO}.self")
    g.link(f"{op2}.Opacity", f"{setO}.InOpacity")

    g.chain(e, owner_gate)
    g.chain(f"{owner_gate}.then", station_gate)
    g.chain(f"{station_gate}.then", runner_gate)
    g.chain(f"{runner_gate}.then", brKey)
    g.chain(f"{brKey}.then", tog, sR)
    g.chain(f"{brKey}.else", sR)
    g.chain(sR, sU, brCh)
    g.chain(f"{brCh}.then", show, sLa)
    g.chain(f"{brCh}.else", sLa)
    # the meter, texts and opacity are only touched while the panel is (or is becoming) visible
    opv = g.get("Opacity")
    act = g.call("Greater_DoubleDouble", KML, B="0.001")
    g.link(f"{opv}.Opacity", f"{act}.A")
    live = g.call("BooleanOR", KML)
    g.link(f"{act}.ReturnValue", f"{live}.A")
    g.link(f"{want}.ReturnValue", f"{live}.B")
    brLive = g.add({"branch": True}, "ifLive")
    g.link(f"{live}.ReturnValue", f"{brLive}.Condition")
    g.chain(sLa, sLo, brLive)
    g.chain(f"{brLive}.then", setP, setNow, setPow, sOp, setO)
    graphs.append(g.spec())

    return {
        "asset": WBP,
        "description": "LANE5 radio panel: R / D-pad up toggles the Low Voice (USaskartaStorySettings.SetRadioStation), "
                       "shows the dial, signal and state for 4 s after any change, while R is held and while a story line forces it on "
                       "(INCOMING ARCHIVE); the station's OnRadioForced*/OnRadioGlitch are bound by editor/radio_bind.py. README_Radio.md.",
        "variables": variables,
        "functions": functions,
        "graphs": graphs,
    }


def hud() -> dict:
    g = G("EventGraph")
    ev = g.add({"event": "ReceiveBeginPlay"}, "begin")
    pc = g.call("GetOwningPlayerController", "/Script/Engine.HUD")
    cw = g.add({"create_widget": WBP_C}, "create")
    g.link(f"{pc}.ReturnValue", f"{cw}.OwningPlayer")
    show = g.call("AddToViewport", "/Script/UMG.UserWidget", ZOrder="40")
    g.link(f"{cw}.ReturnValue", f"{show}.self")
    # LANE5: the story caption layer (subtitles, letterbox, HUD line, prompt, skip ring) bound to the runner.
    cap = g.add({"create_widget": "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption.WBP_Saskarta_Caption_C"}, "createCaption")
    g.link(f"{pc}.ReturnValue", f"{cap}.OwningPlayer")
    show2 = g.call("AddToViewport", "/Script/UMG.UserWidget", ZOrder="30")
    g.link(f"{cap}.ReturnValue", f"{show2}.self")
    # LANE5: the title-screen radio (hidden; plays only while FlowState is Title)
    tr = g.add({"create_widget": "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_TitleRadio.WBP_Saskarta_TitleRadio_C"}, "createTitleRadio")
    g.link(f"{pc}.ReturnValue", f"{tr}.OwningPlayer")
    show3 = g.call("AddToViewport", "/Script/UMG.UserWidget", ZOrder="1")
    g.link(f"{tr}.ReturnValue", f"{show3}.self")
    g.chain(ev, cw, show, cap, show2, tr, show3)
    return {
        "asset": HUD,
        "create": {"parent": "/Script/Engine.HUD"},
        "description": "LANE5: puts WBP_Saskarta_Radio, WBP_Saskarta_Caption and the hidden WBP_Saskarta_TitleRadio on screen for the whole run. GM_Saskarta.HUDClass = this.",
        "graphs": [g.spec()],
    }


def main():
    for name, obj in (("WBP_Saskarta_Radio.tree.json", tree()), ("WBP_Saskarta_Radio.graph.json", graph()), ("BP_Saskarta_HUD.json", hud())):
        (SPECS / name).write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8")
        print("wrote", SPECS / name)


if __name__ == "__main__":
    main()
