"""Generate the boot credit cards (Task TITLE, addenda 5 and 6): the Tripothon card and the Hayba card.

    python Tools/GameFlow/gen_card_specs.py     # writes the four spec files below

Boot order: black -> WBP_Saskarta_EventCard (Tripothon) -> WBP_Saskarta_HaybaCard -> the fire intro
(calligraphy) -> loading (preload) -> title. PC_Saskarta plays the cards (gen_loading_specs.py).

Each card is the same small machine on widget-owned timers (no Tick):
  PlayCard()   CardStart = now, Content transparent, focus on SkipButton, StepTimer -> CardStep (30 Hz)
  CardStep()   t = now - CardStart; Content opacity = min(fade in over FadeIn, fade out after
               FadeIn + Hold over FadeOut); when t passes the end, bDone and the timer stops
  Skip()       SkipButton (click, Enter, Space, gamepad accept): requests the PC's latched opening
               skip, then after SkipAfter (1 s) and before the fade-out, jumps to the fade-out
  IsDone()     pure, bDone
The backdrop (#0C0A08, opaque) never fades, so the cards cut to each other on black.

Writes Tools/GameFlow/specs/WBP_Saskarta_{EventCard,HaybaCard}.{graph,tree}.json.
Build (editor gate held, never during PIE): create the assets (ui_create_widget), then
  node Tools/GameFlow/build_settings_ui.mjs Tools/GameFlow/specs/WBP_Saskarta_EventCard.tree.json --clear
  node Tools/GameFlow/bpgraph.mjs build --reset-graphs Tools/GameFlow/specs/WBP_Saskarta_EventCard.graph.json
and the same for the Hayba card.
"""
import json
import pathlib

from gen_loading_specs import fmt

HERE = pathlib.Path(__file__).resolve().parent
SPECS = HERE / "specs"
UI = "/Game/SaskartaGaea/GameFlow/UI"
PC = "/Game/SaskartaGaea/GameFlow/PC_Saskarta.PC_Saskarta_C"
TEX = UI + "/Textures"
F_AREF = UI + "/Fonts/F_ArefRuqaa.F_ArefRuqaa"
KML = "/Script/Engine.KismetMathLibrary"
KSL = "/Script/Engine.KismetSystemLibrary"
GPS = "/Script/Engine.GameplayStatics"
WIDGET = "/Script/UMG.Widget"

# Addenda 5/6 asked for 0.8 / 2.4 / 0.8 s; task-TIMING-brief.md slows them to 1.2 / 3.5 / 1.2 s.
TIMING = {"FadeIn": 1.2, "Hold": 6.0, "FadeOut": 1.2, "SkipAfter": 1.0}


def lin(hexstr, a=1.0):
    c = [int(hexstr[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [round(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4, 4) for v in c] + [a]


INK = lin("EDE5DA")
BACK = lin("0C0A08")


def call(fn, cls=None):
    return {"call": fn, "class": cls} if cls else {"call": fn}


def graph_spec(asset):
    ev = {
        "graph": "EventGraph",
        "nodes": {
            "skipClicked": {"bound_event": {"target": "SkipButton", "event": "OnClicked"}},
            "skipSteps": {"sequence": 2},
            "owner": call("GetOwningPlayer", "/Script/UMG.Widget"),
            "ownerPC": {"cast": PC},
            "requestOpeningSkip": call("RequestOpeningSkip", PC),
            "skip": call("Skip"),
            "destruct": {"event": "Destruct"},
            "stepGet": {"get": "StepTimer"},
            "stop": call("K2_ClearAndInvalidateTimerHandle", KSL),
        },
        "links": [
            ["skipClicked.then", "skipSteps.execute"],
            ["skipSteps.then_0", "ownerPC.execute"], ["owner.ReturnValue", "ownerPC.Object"],
            ["ownerPC.then", "requestOpeningSkip.execute"], ["ownerPC.AsPC Saskarta", "requestOpeningSkip.self"],
            ["skipSteps.then_1", "skip.execute"],
            ["destruct.then", "stop.execute"], ["stepGet.StepTimer", "stop.Handle"],
        ],
        "defaults": {},
    }
    play = {
        "graph": "PlayCard",
        "nodes": {
            "entry": {"entry": True},
            "now": call("GetTimeSeconds", GPS),
            "setStart": {"set": "CardStart"},
            "setNotDone": {"set": "bDone"},
            "content": {"get": "Content"},
            "clear": call("SetRenderOpacity", WIDGET),
            "skipBtn": {"get": "SkipButton"},
            "focus": call("SetKeyboardFocus", WIDGET),
            "timer": {"timer": True},
            "setTimer": {"set": "StepTimer"},
            # Sound hook (user, 2026-09-28): the cards are silent until the user supplies a sound.
            # Set the CardSound default on the widget; None plays nothing.
            "cardSound": {"get": "CardSound"},
            "playSound": call("SpawnSound2D", GPS),
            "setAudio": {"set": "CardAudio"},
        },
        "links": [
            ["entry.then", "setStart.execute"],
            ["now.ReturnValue", "setStart.CardStart"],
            ["setStart.then", "setNotDone.execute"],
            ["setNotDone.then", "playSound.execute"],
            ["cardSound.CardSound", "playSound.Sound"],
            ["playSound.then", "setAudio.execute"],
            ["playSound.ReturnValue", "setAudio.CardAudio"],
            ["setAudio.then", "clear.execute"],
            ["content.Content", "clear.self"],
            ["clear.then", "focus.execute"],
            ["skipBtn.SkipButton", "focus.self"],
            ["focus.then", "timer.execute"],
            ["timer.then", "setTimer.execute"],
            ["timer.ReturnValue", "setTimer.StepTimer"],
        ],
        "defaults": {"setNotDone.bDone": "false", "clear.InOpacity": "0.0",
                     "timer.FunctionName": "CardStep", "timer.Time": "0.033", "timer.bLooping": "true"},
    }
    step = {
        "graph": "CardStep",
        "nodes": {
            "entry": {"entry": True},
            "now": call("GetTimeSeconds", GPS),
            "start": {"get": "CardStart"},
            "t": call("Subtract_DoubleDouble", KML),
            "fadeIn": {"get": "FadeIn"},
            "hold": {"get": "Hold"},
            "fadeOut": {"get": "FadeOut"},
            "holdEnd": call("Add_DoubleDouble", KML),
            "end": call("Add_DoubleDouble", KML),
            "inA": call("MapRangeClamped", KML),
            "outA": call("MapRangeClamped", KML),
            "alpha": call("FMin", KML),
            "content": {"get": "Content"},
            "show": call("SetRenderOpacity", WIDGET),
            "over": call("GreaterEqual_DoubleDouble", KML),
            "ifOver": {"branch": True},
            "setDone": {"set": "bDone"},
            "stepGet": {"get": "StepTimer"},
            "stop": call("K2_ClearAndInvalidateTimerHandle", KSL),
        },
        "links": [
            ["now.ReturnValue", "t.A"],
            ["start.CardStart", "t.B"],
            ["fadeIn.FadeIn", "holdEnd.A"],
            ["hold.Hold", "holdEnd.B"],
            ["holdEnd.ReturnValue", "end.A"],
            ["fadeOut.FadeOut", "end.B"],
            ["t.ReturnValue", "inA.Value"],
            ["fadeIn.FadeIn", "inA.InRangeB"],
            ["t.ReturnValue", "outA.Value"],
            ["holdEnd.ReturnValue", "outA.InRangeA"],
            ["end.ReturnValue", "outA.InRangeB"],
            ["inA.ReturnValue", "alpha.A"],
            ["outA.ReturnValue", "alpha.B"],
            ["entry.then", "show.execute"],
            ["content.Content", "show.self"],
            ["alpha.ReturnValue", "show.InOpacity"],
            ["t.ReturnValue", "over.A"],
            ["end.ReturnValue", "over.B"],
            ["show.then", "ifOver.execute"],
            ["over.ReturnValue", "ifOver.Condition"],
            ["ifOver.then", "setDone.execute"],
            ["setDone.then", "stop.execute"],
            ["stepGet.StepTimer", "stop.Handle"],
        ],
        "defaults": {"inA.InRangeA": "0.0", "inA.OutRangeA": "0.0", "inA.OutRangeB": "1.0",
                     "outA.OutRangeA": "1.0", "outA.OutRangeB": "0.0", "setDone.bDone": "true"},
    }
    skip = {
        "graph": "Skip",
        "nodes": {
            "entry": {"entry": True},
            "now": call("GetTimeSeconds", GPS),
            "start": {"get": "CardStart"},
            "t": call("Subtract_DoubleDouble", KML),
            "skipAfter": {"get": "SkipAfter"},
            "fadeIn": {"get": "FadeIn"},
            "hold": {"get": "Hold"},
            "holdEnd": call("Add_DoubleDouble", KML),
            "late": call("GreaterEqual_DoubleDouble", KML),
            "early": call("Less_DoubleDouble", KML),
            "ok": call("BooleanAND", KML),
            "ifOk": {"branch": True},
            "newStart": call("Subtract_DoubleDouble", KML),
            "setStart": {"set": "CardStart"},
        },
        "links": [
            ["now.ReturnValue", "t.A"],
            ["start.CardStart", "t.B"],
            ["fadeIn.FadeIn", "holdEnd.A"],
            ["hold.Hold", "holdEnd.B"],
            ["t.ReturnValue", "late.A"],
            ["skipAfter.SkipAfter", "late.B"],
            ["t.ReturnValue", "early.A"],
            ["holdEnd.ReturnValue", "early.B"],
            ["late.ReturnValue", "ok.A"],
            ["early.ReturnValue", "ok.B"],
            ["entry.then", "ifOk.execute"],
            ["ok.ReturnValue", "ifOk.Condition"],
            ["now.ReturnValue", "newStart.A"],
            ["holdEnd.ReturnValue", "newStart.B"],
            ["ifOk.then", "setStart.execute"],
            ["newStart.ReturnValue", "setStart.CardStart"],
        ],
        "defaults": {},
    }
    done = {
        "graph": "IsDone",
        "nodes": {"entry": {"entry": True}, "result": {"result": True}, "d": {"get": "bDone"}},
        "links": [["entry.then", "result.execute"], ["d.bDone", "result.bIsDone"]],
        "defaults": {},
    }
    return {
        "asset": asset,
        "description": "Boot credit card (Task TITLE addenda 5/6). Generated by Tools/GameFlow/gen_card_specs.py; "
                       "PC_Saskarta plays it (PlayCard, polls IsDone).",
        "variables": [
            {"name": "FadeIn", "type": "float", "default": str(TIMING["FadeIn"])},
            {"name": "Hold", "type": "float", "default": str(TIMING["Hold"])},
            {"name": "FadeOut", "type": "float", "default": str(TIMING["FadeOut"])},
            {"name": "SkipAfter", "type": "float", "default": str(TIMING["SkipAfter"])},
            {"name": "CardStart", "type": "float", "default": "0.0"},
            {"name": "bDone", "type": "bool", "default": "false"},
            {"name": "StepTimer", "type": "struct:/Script/Engine.TimerHandle"},
            {"name": "CardSound", "type": "object:/Script/Engine.SoundBase"},
            {"name": "CardAudio", "type": "object:/Script/Engine.AudioComponent"},
        ],
        "functions": [
            {"name": "PlayCard", "inputs": [], "outputs": [], "pure": False},
            {"name": "CardStep", "inputs": [], "outputs": [], "pure": False},
            {"name": "Skip", "inputs": [], "outputs": [], "pure": False},
            {"name": "IsDone", "inputs": [], "outputs": [{"name": "bIsDone", "type": "bool"}], "pure": True},
        ],
        "graphs": [ev, play, step, skip, done],
        "cdo_defaults": {"bIsFocusable": True, "DesiredFocusWidget": {"WidgetName": "SkipButton"}},
    }


def text(name, s, face, size, color, spacing=0, extra=None):
    props = {"Text": s, "Font": {"FontObject": F_AREF, "TypefaceFontName": face, "Size": size, "LetterSpacing": spacing},
             "ColorAndOpacity": {"SpecifiedColor": color}, "Justification": "Center"}
    props.update(extra or {})
    return {"class": "TextBlock", "name": name, "properties": props}


def backdrop():
    none = {"DrawAs": "NoDrawType"}
    zero = {"Left": 0, "Top": 0, "Right": 0, "Bottom": 0}
    return [
        {"class": "Image", "name": "Backdrop", "properties": {"Brush": {"ImageSize": {"X": 1, "Y": 1}, "DrawAs": "Image"}, "ColorAndOpacity": BACK}},
        {"class": "Image", "name": "Glow", "properties": {"Brush": {"ResourceObject": f"{TEX}/T_UI_EmberGlow.T_UI_EmberGlow", "DrawAs": "Image"},
                                                          "ColorAndOpacity": [0.578, 0.162, 0.042, 0.32]}},
        {"class": "Button", "name": "SkipButton", "properties": {"WidgetStyle": {"Normal": none, "Hovered": none, "Pressed": none, "Disabled": none,
                                                                                "NormalPadding": zero, "PressedPadding": zero}}},
    ]


FULL = {"anchors": [0, 0, 1, 1], "position": [0, 0], "size": [0, 0]}
BACK_SLOTS = {
    "Backdrop": {**FULL, "z_order": -3},
    "Glow": {"anchors": [0, 1, 1, 1], "position": [0, -420], "size": [0, 420], "z_order": -2},
    "SkipButton": {**FULL, "z_order": 10},
}


def event_tree():
    logo = {"class": "Image", "name": "EventLogo",
            "properties": {"Brush": {"ResourceObject": f"{TEX}/T_Tripo_Logo.T_Tripo_Logo", "ImageSize": {"X": 600, "Y": 105}, "DrawAs": "Image"}},
            "slot_props": {"horizontal_alignment": "Center", "padding": [0, 0, 0, 44]}}
    caption = text("Caption", "Made for Tripothon S1", "Regular", 30, INK[:3] + [0.72], 40)
    caption["slot_props"] = {"horizontal_alignment": "Center", "padding": [0, 0, 0, 8]}
    second = text("CaptionDetail", "the Tripo AI 3D hackathon", "Regular", 21, INK[:3] + [0.5], 60)
    second["slot_props"] = {"horizontal_alignment": "Center"}
    content = {"class": "VerticalBox", "name": "Content", "properties": {"RenderOpacity": 0.0}, "children": [logo, caption, second]}
    return backdrop() + [content]


def hayba_tree():
    # 22 % of 1080 = 238 px tall; the logo is 1156 x 1400.
    logo = {"class": "Image", "name": "HaybaLogo",
            "properties": {"Brush": {"ResourceObject": f"{TEX}/T_Hayba_Logo.T_Hayba_Logo", "ImageSize": {"X": 196, "Y": 238}, "DrawAs": "Image"}},
            "slot_props": {"horizontal_alignment": "Center", "padding": [0, 0, 0, 40]}}
    caption = text("Caption", "Made with Hayba", "Bold", 34, INK, 50)
    caption["slot_props"] = {"horizontal_alignment": "Center"}
    content = {"class": "VerticalBox", "name": "Content", "properties": {"RenderOpacity": 0.0}, "children": [logo, caption]}
    return backdrop() + [content]


def tree_spec(asset, tree, content_size):
    return {
        "asset": asset,
        "tree": tree,
        "slots": {**BACK_SLOTS, "Content": {"anchors": [0.5, 0.5, 0.5, 0.5], "position": [0, 0], "size": content_size, "alignment": [0.5, 0.5]}},
        "variables": ["Content", "SkipButton"] + (["EventLogo", "Caption", "CaptionDetail"] if "Event" in asset else ["HaybaLogo", "Caption"]),
    }


def dump(path, obj):
    path.write_text(fmt(obj) + "\n", encoding="utf-8")
    print("wrote", path.relative_to(HERE.parents[1]))


def main():
    ev_asset = f"{UI}/WBP_Saskarta_EventCard"
    hb_asset = f"{UI}/WBP_Saskarta_HaybaCard"
    dump(SPECS / "WBP_Saskarta_EventCard.graph.json", graph_spec(ev_asset))
    dump(SPECS / "WBP_Saskarta_HaybaCard.graph.json", graph_spec(hb_asset))
    dump(SPECS / "WBP_Saskarta_EventCard.tree.json", tree_spec(ev_asset, event_tree(), [900, 260]))
    dump(SPECS / "WBP_Saskarta_HaybaCard.tree.json", tree_spec(hb_asset, hayba_tree(), [700, 340]))


if __name__ == "__main__":
    main()
