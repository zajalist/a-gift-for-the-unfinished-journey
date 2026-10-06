"""Generate WBP_Saskarta_Caption: its designer tree and function graphs (LANE5, README_Events.md section 4).

    python Tools/GameFlow/gen_caption_specs.py     # -> specs/WBP_Saskarta_Caption.tree.json + .graph.json

Design (the user, 2026-09-28, the stele UI direction: Aref Ruqaa, ivory on a dark translucent plate, gold):
- Subtitles bottom-centre inside a max width of 60 % of the VIEWPORT (UpdateMaxW: viewport size / DPI scale,
  clamped 640..1150 design px), never more than 2 lines: a long line is cut into timed chunks of even length
  at sentence (then clause, then word) boundaries (CutChunk), each chunk shown for its share of the line's
  duration. The importer strips "(beat)" / "(2 s pause)" directions, and in the lines they sit at sentence ends.
  Layout breaks a 2-line chunk at the sentence (then clause) nearest its middle with a real newline and sizes
  the box to the longer half; with no such boundary the wrap is balanced (text width / lines + slack). So no
  word-per-line wrap, no mid-word break, no orphan.
- English: Aref Ruqaa 30 on a soft feathered dark plate (T_UI_SoftPlate, 9-slice, no hard edge). The
  Saskartan line stays in the graph for source compatibility but is never shown. Speaker: readable gold
  on its own dark plate. Carrier lines: the terminal
  font in amber (the machine voice), with the CARRIER: prefix moved into the label.
- 0.25 s fades; hold = the line + 0.4 s; a new line replaces the old one at once (no overlap).
- Archive header: a small gold letter-spaced tape label top-left (gold tick + soft plate), 4 s, fading.
- Letterbox: 0.8 s ease-in-out; the subtitles ride up above the lower bar.
- Skip: bottom-right, a Space / B key prompt (WBP_Saskarta_KeyPrompt, hold mode) whose gold ring fills while held.
- Key prompts: the event Prompt gets an E / A keycap in front of its line; the B05 controls caption ("W / RT ...")
  is shown as three key prompts (Drive W / RT, Steer A + D / LS, Look mouse / RS) instead of text.

The EventGraph (Construct -> GetEventRunner -> Assign On<Delegate> -> these functions) is built by
Tools/GameFlow/editor/caption_graph.py through the UE 5.8 BlueprintGraphEditor Python API.
Build order: tree (ui_build.mjs --clear), this graph spec (bpgraph --reset-graphs), caption_graph.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from gen_debug_specs import G, KML, KSL, KSTR, KTXT, GS, fn

ROOT = Path(__file__).resolve().parents[2]
WBP = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption"
W = "/Script/UMG.Widget"
TB = "/Script/UMG.TextBlock"
SB = "/Script/UMG.SizeBox"
FONTS = "/Game/SaskartaGaea/GameFlow/UI/Fonts"
AREF = f"{FONTS}/F_ArefRuqaa_Caption.F_ArefRuqaa_Caption"   # Aref Ruqaa + a Cormorant fallback (macrons)
TERM = f"{FONTS}/Font_Terminal.Font_Terminal"
IVORY = [0.8469, 0.7835, 0.7011, 1]
GOLD = [0.86, 0.66, 0.34, 1]
AMBER = [0.95, 0.72, 0.42, 1]

BAR_PX = 139.0            # 2.39:1 inside 16:9 at the 1080 design height
MAX_W = 1150.0            # the subtitle's max text width (design px, DPI-scaled with the screen)
SLACK = 40.0              # box = estimated text width * 1.1 + SLACK: the estimate is prose-average, a real line can run ~8 % wider
EN_SIZE, SKS_SIZE, TERM_SIZE = 23, 16, 20   # Slate points: 23 pt = ~30 px glyphs at 1080p
EN_CHAR, SKS_CHAR, TERM_CHAR = 13.0, 9.4, 11.3   # px per character of prose (ui_measure_text: 12.7, 9.2, 11.0)
CAP_SIZE, CAP_CHAR = 19, 10.6
FILL = 0.80                   # chars per chunk = 2 lines * MaxW / char px * FILL
TEX = "/Game/SaskartaGaea/GameFlow/UI/Textures"
PLATE = f"{TEX}/T_UI_SoftPlate.T_UI_SoftPlate"
RING = "/Game/SaskartaGaea/GameFlow/Materials/M_UI_SkipRing.M_UI_SkipRing"
WLL = "/Script/UMG.WidgetLayoutLibrary"
SCROLL = "/Script/UMG.ScrollBox"
GPS = "/Script/Engine.GameplayStatics"
KEYPROMPT_C = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_KeyPrompt.WBP_Saskarta_KeyPrompt_C"
CONTROLS_PREFIX = "W / RT"     # the B05 controls caption is shown as key prompts, not text
CONTROLS = [("KP_Drive", "Key_W", "None", "Pad_RT", "Drive"), ("KP_Steer", "Key_A", "Key_D", "Pad_LStick", "Steer"),
            ("KP_Look", "Mouse_Move", "None", "Pad_RStick", "Look")]
STEP_S = 0.02
FADE_SPEED = 4.0          # 0.25 s
HOLD_EXTRA_S = 0.4
HEADER_S = 4.0
LB_BLEND_S = 0.8


def text(name, s, font, size, color, opacity=1.0, extra=None, slot=None, typeface="Regular", spacing=0):
    f = {"FontObject": font, "Size": size}
    if typeface and font == AREF:
        f["TypefaceFontName"] = typeface
    if spacing:
        f["LetterSpacing"] = spacing
    p = {"Text": s, "Font": f, "ColorAndOpacity": {"SpecifiedColor": color}, "ShadowOffset": {"X": 1, "Y": 1},
         "ShadowColorAndOpacity": [0, 0, 0, 0.75]}
    if opacity != 1.0:
        p["RenderOpacity"] = opacity
    p.update(extra or {})
    n = {"class": "TextBlock", "name": name, "properties": p}
    if slot:
        n["slot_props"] = slot
    return n


def wrapped(box, name, s, font, size, color, opacity=1.0):
    return {"class": "SizeBox", "name": box, "properties": {"bOverride_WidthOverride": True, "WidthOverride": MAX_W},
            "slot_props": {"horizontal_alignment": "Center"},
            "children": [text(name, s, font, size, color, opacity, {"AutoWrapText": True, "Justification": "Center"})]}


def plate(name, child, pad=(66, 22, 66, 26), alpha=0.62):
    """A soft feathered dark plate: T_UI_SoftPlate (a blurred rounded rect) drawn as a 9-slice box, so its
    edges stay soft at any size. The padding keeps the text over the plate's dense middle."""
    return {"class": "Border", "name": name,
            "properties": {"Background": {"ResourceObject": PLATE, "DrawAs": "Box", "ImageSize": {"X": 190, "Y": 84},
                                          "Margin": {"Left": 0.4, "Top": 0.4, "Right": 0.4, "Bottom": 0.4},
                                          "TintColor": {"SpecifiedColor": [0, 0, 0, alpha]}},
                           "Padding": {"Left": pad[0], "Top": pad[1], "Right": pad[2], "Bottom": pad[3]},
                           "HorizontalAlignment": "HAlign_Center"},
            "children": [child]}


def endcard_content():
    """Use the authored ending's existing cues and credits, without copying their wording here."""
    story = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))
    cues = story["cinematics"]["CIN_25_END_CARD"]["cues"]
    by_id = {c["id"]: c for c in cues if c["type"] == "ShowEndCard"}
    assert set(by_id) == {"Title", "Credits", "CreditsRoll"}
    source = (ROOT / "docs/story/CREDITS_SCREEN.md").read_text(encoding="utf-8")
    lines = source.split("<!-- ROLL:BEGIN -->", 1)[1].split("<!-- ROLL:END -->", 1)[0].strip("\n").splitlines()
    assert lines[0].startswith("```") and lines[-1].startswith("```")
    lines = lines[1:-1]
    assert len(lines) * 0.75 + 4.0 == by_id["CreditsRoll"]["duration_s"]
    return by_id["Credits"]["text"], "\n".join(lines), by_id["CreditsRoll"]["duration_s"]


def endcard_tree() -> dict:
    short, roll, _duration = endcard_content()
    title_art = f"{TEX}/T_Saskarta_TitleName_Ivory.T_Saskarta_TitleName_Ivory"
    rows = []
    for index, line in enumerate(roll.splitlines()):
        name = f"EndCreditRow{index:03d}"
        if not line:
            rows.append({"class": "Spacer", "name": name, "properties": {"Size": {"X": 1, "Y": 28}}})
            continue
        heading = line.endswith(":") or line in ("A game by", "Made for Tripothon S1", "Made with Hayba")
        rows.append(text(name, line, TERM if heading else AREF, 19 if heading else 25,
                         GOLD if heading else IVORY,
                         extra={"AutoWrapText": True, "WrapTextAt": 900, "Justification": "Center",
                                "LineHeightPercentage": 1.15},
                         slot={"horizontal_alignment": "Fill", "padding": [20, 4, 20, 4]}))
    content = {"class": "Overlay", "name": "EndCardContent", "properties": {"RenderOpacity": 0.0}, "children": [
        text("EndCardOverline", "END OF TRANSMISSION", TERM, 17, GOLD,
             slot={"horizontal_alignment": "Center", "vertical_alignment": "Top", "padding": [0, 12, 0, 0]}),
        {"class": "Image", "name": "EndCardTitle",
         "properties": {"Brush": {"ResourceObject": title_art, "DrawAs": "Image",
                                  "ImageSize": {"X": 320, "Y": 519}}, "Visibility": "Collapsed"},
         "slot_props": {"horizontal_alignment": "Center", "vertical_alignment": "Center"}},
        {**text("EndCardCreditsShort", short, AREF, 30, IVORY,
                extra={"Justification": "Center", "Visibility": "Collapsed", "LineHeightPercentage": 1.5,
                       "AutoWrapText": True, "WrapTextAt": 900}),
         "slot_props": {"horizontal_alignment": "Center", "vertical_alignment": "Center"}},
        {"class": "SizeBox", "name": "EndCardRollViewport",
         "properties": {"bOverride_WidthOverride": True, "WidthOverride": 1000,
                        "bOverride_HeightOverride": True, "HeightOverride": 640,
                        "Clipping": "ClipToBounds", "Visibility": "Collapsed"},
         "slot_props": {"horizontal_alignment": "Center", "vertical_alignment": "Center"},
         "children": [{"class": "ScrollBox", "name": "EndCardRollScroll",
                       "properties": {"ScrollBarVisibility": "Collapsed", "AllowOverscroll": False,
                                      "ConsumeMouseWheel": "Never"},
                       "children": [{"class": "Spacer", "name": "EndCardRollLead",
                                     "properties": {"Size": {"X": 1, "Y": 640}}},
                                    {"class": "VerticalBox", "name": "EndCardCreditsRoll", "children": rows},
                                    {"class": "Spacer", "name": "EndCardRollTail",
                                     "properties": {"Size": {"X": 1, "Y": 640}}}]}]},
    ]}
    panel = {"class": "Overlay", "name": "EndCard", "properties": {"Visibility": "Collapsed"}, "children": [
        {"class": "Image", "name": "EndCardBlack",
         "properties": {"Brush": {"ImageSize": {"X": 1, "Y": 1}, "DrawAs": "Image"},
                        "ColorAndOpacity": [0.002, 0.003, 0.002, 1], "RenderOpacity": 1.0},
         "slot_props": {"horizontal_alignment": "Fill", "vertical_alignment": "Fill"}},
        {"class": "ScaleBox", "name": "EndCardSafeScale",
         "properties": {"Stretch": "ScaleToFit", "StretchDirection": "DownOnly"},
         "slot_props": {"horizontal_alignment": "Fill", "vertical_alignment": "Fill", "padding": [100, 72, 100, 72]},
         "children": [{"class": "SizeBox", "name": "EndCardStage",
                       "properties": {"bOverride_WidthOverride": True, "WidthOverride": 1120,
                                      "bOverride_HeightOverride": True, "HeightOverride": 840},
                       "children": [content]}]},
    ]}
    return {"asset": WBP, "tree": [panel],
            "slots": {"EndCard": {"anchors": [0, 0, 1, 1], "position": [0, 0], "size": [0, 0], "z_order": 20}},
            "variables": ["EndCard", "EndCardBlack", "EndCardContent", "EndCardTitle", "EndCardCreditsShort",
                          "EndCardRollViewport", "EndCardRollScroll"]}


def tree() -> dict:
    lb = {"Brush": {"ImageSize": {"X": 1, "Y": 1}, "DrawAs": "Image"}, "ColorAndOpacity": [0, 0, 0, 1],
          "RenderOpacity": 0.0, "Visibility": "HitTestInvisible"}
    subtitle = {"class": "VerticalBox", "name": "SubtitleBox", "properties": {"Visibility": "Collapsed", "RenderOpacity": 0.0}, "children": [
        {**plate("SpeakerPlate", text("SpeakerLabel", "RADIO HOST", AREF, 16, [1, 0.82, 0.5, 1], 1,
                                        {"Justification": "Center", "ShadowOffset": {"X": 2, "Y": 2},
                                         "ShadowColorAndOpacity": [0, 0, 0, 1]},
                                        typeface="Bold", spacing=180), pad=(10, 0, 10, 0), alpha=0.8),
         "slot_props": {"horizontal_alignment": "Center", "padding": [0, 0, 0, 0]}},
        plate("SubtitlePlate", {"class": "VerticalBox", "name": "SubtitleStack", "children": [
            {**wrapped("SaskartanBox", "SaskartanLine", "", AREF, SKS_SIZE, IVORY, 0.6),
             "slot_props": {"horizontal_alignment": "Center", "padding": [0, 0, 0, 6]}},
            wrapped("EnglishBox", "EnglishLine", "Homes may empty; let names remain.", AREF, EN_SIZE, [0.95, 0.92, 0.86, 1]),
            wrapped("CarrierBox", "CarrierLine", "Route lock: Âlaawb.", TERM, TERM_SIZE, AMBER),
        ]}, pad=(40, 4, 40, 10), alpha=0.36),
    ]}
    subtitle["children"][0]["properties"]["BrushColor"] = [1, 1, 1, 0]
    subtitle["children"][1]["properties"]["BrushColor"] = [1, 1, 1, 1]
    subtitle["children"][1]["slot_props"] = {"horizontal_alignment": "Center", "padding": [0, 0, 0, 0]}
    caption = plate("CaptionBox", {**wrapped("CaptionTextBox", "CaptionLine", "W / RT  Drive", AREF, CAP_SIZE, [0.95, 0.92, 0.86, 1])})
    caption["properties"]["Visibility"] = "Collapsed"
    # the event Prompt ("Rise.", "Lay your hand on the mark."): the E / A key prompt in front of the line
    prompt = plate("PromptBox", {"class": "HorizontalBox", "name": "PromptRow", "children": [
        {"class": KEYPROMPT_C, "name": "KP_Prompt", "slot_props": {"vertical_alignment": "Center", "padding": [0, 0, 14, 0]}},
        {**text("PromptLine", "Rise.", AREF, 26, [0.95, 0.92, 0.86, 1], extra={"Justification": "Center"}), "slot_props": {"vertical_alignment": "Center"}},
    ]}, (22, 10, 30, 12))
    prompt["properties"]["Visibility"] = "Collapsed"
    # hold to skip: a Space / B key prompt in hold mode (its ring fills with the runner's skip hold)
    skip = {"class": "HorizontalBox", "name": "SkipBox", "properties": {"RenderOpacity": 0.0, "Visibility": "HitTestInvisible"}, "children": [
        {"class": KEYPROMPT_C, "name": "KP_Skip", "slot_props": {"vertical_alignment": "Center"}},
    ]}
    # the first-drive controls (the B05 caption "W / RT Drive ..."): Drive, Steer, Look key prompts in a row
    controls = {"class": "HorizontalBox", "name": "ControlsRow", "properties": {"Visibility": "Collapsed"}, "children": [
        {"class": KEYPROMPT_C, "name": n, "slot_props": {"vertical_alignment": "Center", "padding": [10, 0, 10, 0]}}
        for n in ("KP_Drive", "KP_Steer", "KP_Look")]}
    # the archive header: a tape label (gold tick, letter-spaced gold caps on a faint soft plate)
    header = plate("HeaderBox", {"class": "HorizontalBox", "name": "HeaderRow", "children": [
        {"class": "Image", "name": "HeaderTick", "properties": {"Brush": {"ImageSize": {"X": 3, "Y": 16}, "DrawAs": "Image"}, "ColorAndOpacity": GOLD},
         "slot_props": {"vertical_alignment": "Center", "padding": [0, 0, 12, 0]}},
        text("HeaderLabel", "ARCHIVE 14 · THE WAITING WATER", AREF, 12, GOLD, 0.95, slot={"vertical_alignment": "Center"}, typeface="Bold", spacing=280),
    ]}, pad=(26, 10, 30, 12), alpha=0.45)
    header["properties"].update({"Visibility": "Collapsed", "RenderOpacity": 0.0})
    ec = endcard_tree()
    result = {
        "asset": WBP,
        "tree": [
            {"class": "Image", "name": "LetterboxTop", "properties": lb},
            {"class": "Image", "name": "LetterboxBottom", "properties": lb},
            subtitle,
            header,
            text("HudLine", "RANGE 3,300 M", TERM, 20, AMBER, extra={"Visibility": "Collapsed"}),
            # the ?-column (storyline-first-light.md 4.2): caption target HudColumn, one entry a line, right margin
            text("HudQuestions", "APRICOT?\nLAMP?", TERM, 18, AMBER, opacity=0.8,
                 extra={"Visibility": "Collapsed", "Justification": "Right"}),
            # the carrier's corner date, always on (draft 4.1, B01): small, dim
            text("HudDate", "1946 AA", TERM, 30, [1, 0.82, 0.55, 1], opacity=1.0, extra={"Visibility": "HitTestInvisible"}),
            text("ScanBlock", "INSCRIPTION 01 · READ\n RZAG-ZRIRIT\n ~ EN: THE WAY", TERM, 18, AMBER,
                 extra={"Visibility": "Collapsed", "AutoWrapText": True, "WrapTextAt": 720}),
            # The stele scan prompt (USaskartaSteleScanner, target "ScanPrompt"): where the reading will print.
            text("ScanPromptLine", "E · SCAN INSCRIPTION", TERM, 18, [0.95, 0.72, 0.42, 0.7],
                 extra={"Visibility": "Collapsed"}),
            caption,
            prompt,
            skip,
            controls,
            *ec["tree"],
        ],
        "slots": {
            "LetterboxTop": {"anchors": [0, 0, 1, 0], "position": [0, 0], "size": [0, BAR_PX], "z_order": 0},
            "LetterboxBottom": {"anchors": [0, 1, 1, 1], "position": [0, 0], "size": [0, BAR_PX], "alignment": [0, 1], "z_order": 0},
            "SubtitleBox": {"anchors": [0.5, 1, 0.5, 1], "position": [0, -56], "alignment": [0.5, 1], "auto_size": True, "z_order": 5},
            "HeaderBox": {"anchors": [0, 0, 0, 0], "position": [40, 40], "auto_size": True, "z_order": 5},
            "HudLine": {"anchors": [0, 0, 0, 0], "position": [64, 92], "auto_size": True, "z_order": 5},
            "HudQuestions": {"anchors": [1, 0, 1, 0], "position": [-64, 140], "alignment": [1, 0], "auto_size": True, "z_order": 5},
            "HudDate": {"anchors": [1, 0, 1, 0], "position": [-64, 92], "alignment": [1, 0], "auto_size": True, "z_order": 5},
            "ScanBlock": {"anchors": [0, 0, 0, 0], "position": [64, 134], "auto_size": True, "z_order": 5},
            "ScanPromptLine": {"anchors": [0, 0, 0, 0], "position": [64, 134], "auto_size": True, "z_order": 5},
            "CaptionBox": {"anchors": [0.5, 1, 0.5, 1], "position": [0, -250], "alignment": [0.5, 1], "auto_size": True, "z_order": 5},
            "PromptBox": {"anchors": [0.5, 0.72, 0.5, 0.72], "position": [0, 0], "alignment": [0.5, 0.5], "auto_size": True, "z_order": 5},
            "SkipBox": {"anchors": [1, 1, 1, 1], "position": [-48, -40], "alignment": [1, 1], "auto_size": True, "z_order": 30},
            "ControlsRow": {"anchors": [0.5, 1, 0.5, 1], "position": [0, -250], "alignment": [0.5, 1], "auto_size": True, "z_order": 5},
            **ec["slots"],
        },
        "variables": ["LetterboxTop", "LetterboxBottom", "SubtitleBox", "SpeakerPlate", "SpeakerLabel", "SaskartanBox", "SaskartanLine",
                      "EnglishBox", "EnglishLine", "CarrierBox", "CarrierLine", "HeaderBox", "HeaderLabel", "HudLine", "HudQuestions", "HudDate", "ScanBlock", "ScanPromptLine", "CaptionBox",
                      "CaptionLine", "CaptionTextBox", "PromptBox", "PromptLine", "SkipBox", "KP_Prompt", "KP_Skip",
                      "ControlsRow", "KP_Drive", "KP_Steer", "KP_Look", *ec["variables"]],
    }
    return result


# ----------------------------------------------------------------------------- graph helpers

def vis(g, widget, visibility):
    w = g.get(widget)
    c = g.call("SetVisibility", W, InVisibility=visibility)
    g.link(f"{w}.{widget}", f"{c}.self")
    return c


def settext(g, widget, text_pin):
    w = g.get(widget)
    c = g.call("SetText", TB)
    g.link(f"{w}.{widget}", f"{c}.self")
    g.link(text_pin, f"{c}.InText")
    return c


def to_text(g, str_pin):
    t = g.call("Conv_StringToText", KTXT)
    g.link(str_pin, f"{t}.InString")
    return f"{t}.ReturnValue"


def timer(g, name, fn_name, seconds_pin=None, seconds=None, loop=False):
    t = g.add({"timer": True}, name)
    g.defaults.update({f"{t}.FunctionName": fn_name, f"{t}.bLooping": "true" if loop else "false"})
    if seconds_pin:
        g.link(seconds_pin, f"{t}.Time")
    else:
        g.defaults[f"{t}.Time"] = str(seconds)
    return t


def clear(g, var):
    h = g.get(var)
    c = g.call("K2_ClearAndInvalidateTimerHandle", KSL)
    g.link(f"{h}.{var}", f"{c}.Handle")
    return c


def endcard_graph() -> dict:
    """Only the new functions, so editor integration leaves existing caption graphs intact."""
    _short, _roll, roll_s = endcard_content()
    functions = [fn("ShowEndCard", [("Id", "name")]), fn("HideEndCard"), fn("ScrollCreditsStep")]
    variables = [{"name": "EndCardRollStartS", "type": "float"},
                 {"name": "EndCardPhaseDurationS", "type": "float", "default": "8.0"},
                 {"name": "bEndCardRolling", "type": "bool", "default": "false"},
                 {"name": "EndCardRollTimer", "type": "struct:/Script/Engine.TimerHandle"}]
    graphs = []

    g = G("HideEndCard")
    e = g.add({"entry": True}, "entry")
    reset = g.call("SetScrollOffset", SCROLL, NewScrollOffset="0.0")
    scroll = g.get("EndCardRollScroll")
    g.link(f"{scroll}.EndCardRollScroll", f"{reset}.self")
    g.chain(e, clear(g, "EndCardRollTimer"), vis(g, "EndCardTitle", "Collapsed"),
            vis(g, "EndCardCreditsShort", "Collapsed"), vis(g, "EndCardRollViewport", "Collapsed"),
            vis(g, "EndCard", "Collapsed"), reset)
    graphs.append(g.spec())

    g = G("ShowEndCard")
    e = g.add({"entry": True}, "entry")
    hide = g.call("HideEndCard")
    g.chain(e, hide)
    # The existing hold-to-skip control stays above the opaque credits stage, including scoped installs.
    skip = g.get("SkipBox")
    slot = g.call("SlotAsCanvasSlot", WLL)
    g.link(f"{skip}.SkipBox", f"{slot}.Widget")
    raise_skip = g.call("SetZOrder", "/Script/UMG.CanvasPanelSlot", InZOrder="30")
    g.link(f"{slot}.ReturnValue", f"{raise_skip}.self")
    g.chain(hide, raise_skip)
    previous = f"{raise_skip}.then"
    for cue, widget in (("Title", "EndCardTitle"), ("Credits", "EndCardCreditsShort"),
                        ("CreditsRoll", "EndCardRollViewport")):
        eq = g.call("EqualEqual_NameName", KML, B=cue)
        g.link(f"{e}.Id", f"{eq}.A")
        br = g.add({"branch": True}, "if" + cue)
        g.link(f"{eq}.ReturnValue", f"{br}.Condition")
        g.link(previous, f"{br}.execute")
        previous = f"{br}.else"
        panel = vis(g, "EndCard", "HitTestInvisible")
        child = vis(g, widget, "HitTestInvisible")
        now = g.call("GetTimeSeconds", GPS)
        start = g.set("EndCardRollStartS")
        g.link(f"{now}.ReturnValue", f"{start}.EndCardRollStartS")
        duration = g.set("EndCardPhaseDurationS", str({"Title": 8.0, "Credits": 7.0, "CreditsRoll": roll_s}[cue]))
        rolling = g.set("bEndCardRolling", "true" if cue == "CreditsRoll" else "false")
        content = g.get("EndCardContent")
        fade_start = g.call("SetRenderOpacity", W, InOpacity="0.0")
        g.link(f"{content}.EndCardContent", f"{fade_start}.self")
        tick = timer(g, "timer" + cue, "ScrollCreditsStep", seconds=STEP_S, loop=True)
        handle = g.set("EndCardRollTimer")
        g.link(f"{tick}.ReturnValue", f"{handle}.EndCardRollTimer")
        g.chain(f"{br}.then", panel, child, start, duration, rolling, fade_start, tick, handle)
    graphs.append(g.spec())

    g = G("ScrollCreditsStep")
    e = g.add({"entry": True}, "entry")
    now = g.call("GetTimeSeconds", GPS)
    start = g.get("EndCardRollStartS")
    elapsed = g.call("Subtract_DoubleDouble", KML)
    g.link(f"{now}.ReturnValue", f"{elapsed}.A")
    g.link(f"{start}.EndCardRollStartS", f"{elapsed}.B")
    duration = g.get("EndCardPhaseDurationS")
    done = g.call("GreaterEqual_DoubleDouble", KML)
    g.link(f"{elapsed}.ReturnValue", f"{done}.A")
    g.link(f"{duration}.EndCardPhaseDurationS", f"{done}.B")
    br = g.add({"branch": True}, "ifRollDone")
    g.link(f"{done}.ReturnValue", f"{br}.Condition")
    g.chain(e, br)
    content = g.get("EndCardContent")
    fade_done = g.call("SetRenderOpacity", W, InOpacity="0.0")
    g.link(f"{content}.EndCardContent", f"{fade_done}.self")
    # Retain the black stage during the three seconds before OpenLevel; never reveal the old final pose.
    g.chain(f"{br}.then", fade_done, clear(g, "EndCardRollTimer"))
    fade_in = g.call("Divide_DoubleDouble", KML, B="1.2")
    g.link(f"{elapsed}.ReturnValue", f"{fade_in}.A")
    remaining = g.call("Subtract_DoubleDouble", KML)
    g.link(f"{duration}.EndCardPhaseDurationS", f"{remaining}.A")
    g.link(f"{elapsed}.ReturnValue", f"{remaining}.B")
    fade_out = g.call("Divide_DoubleDouble", KML, B="1.2")
    g.link(f"{remaining}.ReturnValue", f"{fade_out}.A")
    lesser = g.call("FMin", KML)
    g.link(f"{fade_in}.ReturnValue", f"{lesser}.A")
    g.link(f"{fade_out}.ReturnValue", f"{lesser}.B")
    alpha = g.call("FClamp", KML, Min="0.0", Max="1.0")
    g.link(f"{lesser}.ReturnValue", f"{alpha}.Value")
    fade = g.call("SetRenderOpacity", W)
    g.link(f"{content}.EndCardContent", f"{fade}.self")
    g.link(f"{alpha}.ReturnValue", f"{fade}.InOpacity")
    rolling = g.get("bEndCardRolling")
    br_roll = g.add({"branch": True}, "ifRolling")
    g.link(f"{rolling}.bEndCardRolling", f"{br_roll}.Condition")
    g.chain(f"{br}.else", fade, br_roll)
    scroll = g.get("EndCardRollScroll")
    extent = g.call("GetScrollOffsetOfEnd", SCROLL)
    g.link(f"{scroll}.EndCardRollScroll", f"{extent}.self")
    fraction = g.call("Divide_DoubleDouble", KML, B=str(roll_s))
    g.link(f"{elapsed}.ReturnValue", f"{fraction}.A")
    offset = g.call("Multiply_DoubleDouble", KML)
    g.link(f"{fraction}.ReturnValue", f"{offset}.A")
    g.link(f"{extent}.ReturnValue", f"{offset}.B")
    move = g.call("SetScrollOffset", SCROLL)
    g.link(f"{offset}.ReturnValue", f"{move}.NewScrollOffset")
    g.link(f"{scroll}.EndCardRollScroll", f"{move}.self")
    g.chain(f"{br_roll}.then", move)
    graphs.append(g.spec())
    return {"asset": WBP, "description": "CIN_25 end card only; additive to the caption widget.",
            "variables": variables, "functions": functions, "graphs": graphs}


def build() -> dict:
    variables = [
        {"name": "EnRest", "type": "string"}, {"name": "SksRest", "type": "string"},
        {"name": "TotalLen", "type": "float", "default": "1.0"}, {"name": "LineDur", "type": "float", "default": "3.0"},
        {"name": "bCarrier", "type": "bool", "default": "false"},
        {"name": "SubAlpha", "type": "float", "default": "0.0"}, {"name": "SubTarget", "type": "float", "default": "0.0"},
        {"name": "HeadAlpha", "type": "float", "default": "0.0"}, {"name": "HeadTarget", "type": "float", "default": "0.0"},
        {"name": "LbAlpha", "type": "float", "default": "0.0"}, {"name": "LbTarget", "type": "float", "default": "0.0"},
        {"name": "ChunkTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "HideTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "HeaderTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "FadeTimer", "type": "struct:/Script/Engine.TimerHandle"},
        {"name": "CarrierPrefix", "type": "string", "default": "CARRIER: "},
        {"name": "RadioPrefix", "type": "string", "default": "RADIO · "},
        {"name": "Empty", "type": "string"},
        {"name": "NL", "type": "string", "default": "\n"},
        {"name": "MaxW", "type": "float", "default": str(MAX_W)},
        {"name": "NoLabel", "type": "text"},
        {"name": "bSkipReady", "type": "bool", "default": "false"},
    ] + [{"name": "Label" + n[3:], "type": "text", "default": lab} for n, _g, _g2, _p, lab in CONTROLS] + [
        {"name": "LabelSkip", "type": "text", "default": "Skip"},
    ]
    functions = [
        fn("ShowSubtitle", [("English", "text"), ("Saskartan", "text"), ("Header", "text"), ("Speaker", "name"), ("DurationS", "float")]),
        fn("HideSubtitle"), fn("BeginFadeOut"), fn("NextChunk"), fn("HideHeader"), fn("StartFade"), fn("FadeStep"),
        fn("CutChunk", [("S", "string"), ("CharPx", "float")], [("Chunk", "string"), ("Rest", "string")]),
        fn("Layout", [("Box", "object:/Script/UMG.SizeBox"), ("Chunk", "string"), ("CharPx", "float")], [("Out", "string")]),
        fn("UpdateMaxW"),
        fn("ShowCaption", [("Text", "text"), ("Target", "name")]),
        fn("HideCaption", [("Target", "name")]),
        fn("ShowPrompt", [("Text", "text")]), fn("HidePrompt"),
        fn("SetLetterbox", [("bOn", "bool"), ("BlendS", "float")]),
        fn("SetSkipProgress", [("Fraction", "float")]),
    ]
    graphs = []

    # --- UpdateMaxW: 60 % of the viewport width in design px (viewport px / DPI scale), clamped 640..MAX_W;
    #     MAX_W when there is no viewport yet (0 size).
    g = G("UpdateMaxW")
    e = g.add({"entry": True}, "entry")
    me = g.add({"self": True})
    vs = g.call("GetViewportSize", WLL)
    g.link(f"{me}.self", f"{vs}.WorldContextObject")
    sc = g.call("GetViewportScale", WLL)
    g.link(f"{me}.self", f"{sc}.WorldContextObject")
    bv = g.call("BreakVector2D", KML)
    g.link(f"{vs}.ReturnValue", f"{bv}.InVec")
    scM = g.call("FMax", KML, B="0.1")
    g.link(f"{sc}.ReturnValue", f"{scM}.A")
    dv = g.call("Divide_DoubleDouble", KML)
    g.link(f"{bv}.X", f"{dv}.A")
    g.link(f"{scM}.ReturnValue", f"{dv}.B")
    six = g.call("Multiply_DoubleDouble", KML, B="0.6")
    g.link(f"{dv}.ReturnValue", f"{six}.A")
    cl = g.call("FClamp", KML, Min="640.0", Max=str(MAX_W))
    g.link(f"{six}.ReturnValue", f"{cl}.Value")
    has = g.call("Greater_DoubleDouble", KML, B="1.0")
    g.link(f"{bv}.X", f"{has}.A")
    sel = g.call("SelectFloat", KML, B=str(MAX_W))
    g.link(f"{cl}.ReturnValue", f"{sel}.A")
    g.link(f"{has}.ReturnValue", f"{sel}.bPickA")
    sm = g.set("MaxW")
    g.link(f"{sel}.ReturnValue", f"{sm}.MaxW")
    g.chain(e, sm)
    graphs.append(g.spec())

    # --- CutChunk(S, CharPx) -> Chunk, Rest. MaxChars = 2 lines of MaxW at CharPx (* FILL). Whole if it fits;
    #     else n = ceil(len / MaxChars) even pieces: cut at the last sentence end at or before
    #     Limit = min(MaxChars, even + even / 4) if that is past half the even length, else the last clause
    #     (, ; : -), else the last space. (The importer already removed the stage directions and quotes.)
    g = G("CutChunk")
    e = g.add({"entry": True}, "entry")
    r = g.add({"result": True}, "result")
    S = f"{e}.S"

    def op(fname, a, b=None, **kw):
        n = g.call(fname, KML, **kw)
        g.link(a, f"{n}.A")
        if b is not None:
            g.link(b, f"{n}.B")
        return f"{n}.ReturnValue"

    mw = g.get("MaxW")
    mdiv = op("Divide_DoubleDouble", op("Multiply_DoubleDouble", f"{mw}.MaxW", B=str(2 * FILL)), f"{e}.CharPx")
    maxc = g.call("FTrunc", KML)
    g.link(mdiv, f"{maxc}.A")
    MAXC = f"{maxc}.ReturnValue"
    ln = g.call("Len", KSTR)
    g.link(S, f"{ln}.S")
    L = f"{ln}.ReturnValue"
    short = op("LessEqual_IntInt", L, MAXC)
    # pieces = (L + MaxChars - 1) / MaxChars ; even = (L + pieces - 1) / pieces
    pieces = op("Max", op("Divide_IntInt", op("Subtract_IntInt", op("Add_IntInt", L, MAXC), B="1"), MAXC), B="1")
    even = op("Divide_IntInt", op("Subtract_IntInt", op("Add_IntInt", L, pieces), B="1"), pieces)
    limit = op("Min", op("Add_IntInt", even, op("Divide_IntInt", even, B="4")), MAXC)
    half = op("Divide_IntInt", even, B="2")

    def find(sub):
        f = g.call("FindSubstring", KSTR, Substring=sub, bUseCase="false", bSearchFromEnd="true")
        g.link(S, f"{f}.SearchIn")
        g.link(limit, f"{f}.StartPosition")
        return f"{f}.ReturnValue"

    sent = op("Max", op("Max", find(". "), find("? ")), op("Max", find("! "), find("… ")))
    clause = op("Max", op("Max", find(", "), find("; ")), op("Max", find(": "), find("— ")))
    space = find(" ")
    okS = op("GreaterEqual_IntInt", sent, half)
    okC = op("GreaterEqual_IntInt", clause, half)
    selC = g.call("SelectInt", KML)
    g.link(clause, f"{selC}.A")
    g.link(space, f"{selC}.B")
    g.link(okC, f"{selC}.bPickA")
    selS = g.call("SelectInt", KML)
    g.link(sent, f"{selS}.A")
    g.link(f"{selC}.ReturnValue", f"{selS}.B")
    g.link(okS, f"{selS}.bPickA")
    cut = op("Add_IntInt", f"{selS}.ReturnValue", B="1")
    left = g.call("Left", KSTR)
    g.link(S, f"{left}.SourceString")
    g.link(cut, f"{left}.Count")
    chop = g.call("RightChop", KSTR)
    g.link(S, f"{chop}.SourceString")
    g.link(cut, f"{chop}.Count")
    trimR = g.call("Trim", KSTR)
    g.link(f"{chop}.ReturnValue", f"{trimR}.SourceString")
    trimC = g.call("TrimTrailing", KSTR)
    g.link(f"{left}.ReturnValue", f"{trimC}.SourceString")
    chunkSel = g.call("SelectString", KML)
    g.link(S, f"{chunkSel}.A")
    g.link(f"{trimC}.ReturnValue", f"{chunkSel}.B")
    g.link(short, f"{chunkSel}.bPickA")
    emp = g.get("Empty")
    restSel = g.call("SelectString", KML)
    g.link(f"{emp}.Empty", f"{restSel}.A")
    g.link(f"{trimR}.ReturnValue", f"{restSel}.B")
    g.link(short, f"{restSel}.bPickA")
    g.link(f"{chunkSel}.ReturnValue", f"{r}.Chunk")
    g.link(f"{restSel}.ReturnValue", f"{r}.Rest")
    g.chain(e, r)
    graphs.append(g.spec())

    # --- Layout(Box, Chunk, CharPx) -> Out. One line when it fits (box = text + slack). Two lines: break with a
    #     newline at the sentence (else clause) end nearest the middle (between 38 % and 62 % of the chunk) and
    #     size the box to the longer half; with no such boundary, a balanced wrap (w / ceil(w / MaxW) + slack).
    g = G("Layout")
    e = g.add({"entry": True}, "entry")
    r = g.add({"result": True}, "result")
    C = f"{e}.Chunk"

    def op(fname, a, b=None, **kw):  # noqa: F811 (per graph)
        n = g.call(fname, KML, **kw)
        g.link(a, f"{n}.A")
        if b is not None:
            g.link(b, f"{n}.B")
        return f"{n}.ReturnValue"

    def slen(pin):
        n = g.call("Len", KSTR)
        g.link(pin, f"{n}.S")
        cv = g.call("Conv_IntToDouble", KML)
        g.link(f"{n}.ReturnValue", f"{cv}.InInt")
        return f"{cv}.ReturnValue"

    mw = g.get("MaxW")
    MW = f"{mw}.MaxW"
    Lf = slen(C)
    w = op("Multiply_DoubleDouble", Lf, f"{e}.CharPx")
    one = op("LessEqual_DoubleDouble", op("Multiply_DoubleDouble", w, B="1.1"), op("Subtract_DoubleDouble", MW, B=str(SLACK)))
    hi = g.call("FTrunc", KML)
    g.link(op("Multiply_DoubleDouble", Lf, B="0.62"), f"{hi}.A")
    lo = g.call("FTrunc", KML)
    g.link(op("Multiply_DoubleDouble", Lf, B="0.38"), f"{lo}.A")

    def find2(sub):
        f = g.call("FindSubstring", KSTR, Substring=sub, bUseCase="false", bSearchFromEnd="true")
        g.link(C, f"{f}.SearchIn")
        g.link(f"{hi}.ReturnValue", f"{f}.StartPosition")
        return f"{f}.ReturnValue"

    sent = op("Max", op("Max", find2(". "), find2("? ")), op("Max", find2("! "), find2("… ")))
    clause = op("Max", op("Max", find2(", "), find2("; ")), op("Max", find2(": "), find2("— ")))
    okS = op("GreaterEqual_IntInt", sent, f"{lo}.ReturnValue")
    okC = op("GreaterEqual_IntInt", clause, f"{lo}.ReturnValue")
    pSel = g.call("SelectInt", KML)
    g.link(sent, f"{pSel}.A")
    g.link(clause, f"{pSel}.B")
    g.link(okS, f"{pSel}.bPickA")
    ok2 = op("BooleanOR", okS, okC)
    cut = op("Add_IntInt", f"{pSel}.ReturnValue", B="1")
    left = g.call("Left", KSTR)
    g.link(C, f"{left}.SourceString")
    g.link(cut, f"{left}.Count")
    a = g.call("TrimTrailing", KSTR)
    g.link(f"{left}.ReturnValue", f"{a}.SourceString")
    chop = g.call("RightChop", KSTR)
    g.link(C, f"{chop}.SourceString")
    g.link(cut, f"{chop}.Count")
    b = g.call("Trim", KSTR)
    g.link(f"{chop}.ReturnValue", f"{b}.SourceString")
    nl = g.get("NL")
    j1 = g.call("Concat_StrStr", KSTR)
    g.link(f"{a}.ReturnValue", f"{j1}.A")
    g.link(f"{nl}.NL", f"{j1}.B")
    j2 = g.call("Concat_StrStr", KSTR)
    g.link(f"{j1}.ReturnValue", f"{j2}.A")
    g.link(f"{b}.ReturnValue", f"{j2}.B")
    la, lb = slen(f"{a}.ReturnValue"), slen(f"{b}.ReturnValue")
    wTwo = op("FMin", op("Add_DoubleDouble", op("Multiply_DoubleDouble", op("Multiply_DoubleDouble", op("FMax", la, lb), f"{e}.CharPx"), B="1.1"), B=str(SLACK)), MW)
    lines = g.call("FCeil", KML)
    g.link(op("Divide_DoubleDouble", w, MW), f"{lines}.A")
    linesF = g.call("Conv_IntToDouble", KML)
    g.link(f"{lines}.ReturnValue", f"{linesF}.InInt")
    wBal = op("FMin", op("Add_DoubleDouble", op("Multiply_DoubleDouble", op("Divide_DoubleDouble", w, op("FMax", f"{linesF}.ReturnValue", B="1.0")), B="1.1"), B=str(SLACK)), MW)
    wOne = op("FMin", op("Add_DoubleDouble", op("Multiply_DoubleDouble", w, B="1.1"), B=str(SLACK)), MW)
    w2 = g.call("SelectFloat", KML)
    g.link(wTwo, f"{w2}.A")
    g.link(wBal, f"{w2}.B")
    g.link(ok2, f"{w2}.bPickA")
    wF = g.call("SelectFloat", KML)
    g.link(wOne, f"{wF}.A")
    g.link(f"{w2}.ReturnValue", f"{wF}.B")
    g.link(one, f"{wF}.bPickA")
    t2 = g.call("SelectString", KML)
    g.link(f"{j2}.ReturnValue", f"{t2}.A")
    g.link(C, f"{t2}.B")
    g.link(ok2, f"{t2}.bPickA")
    tF = g.call("SelectString", KML)
    g.link(C, f"{tF}.A")
    g.link(f"{t2}.ReturnValue", f"{tF}.B")
    g.link(one, f"{tF}.bPickA")
    so = g.call("SetWidthOverride", SB)
    g.link(f"{e}.Box", f"{so}.self")
    g.link(f"{wF}.ReturnValue", f"{so}.InWidthOverride")
    g.link(f"{tF}.ReturnValue", f"{r}.Out")
    g.chain(e, so, r)
    graphs.append(g.spec())

    # --- ShowSubtitle: replace any line at once; strip the prefix into the label; chunk; fade in.
    g = G("ShowSubtitle")
    e = g.add({"entry": True}, "entry")
    c1, c2 = clear(g, "HideTimer"), clear(g, "ChunkTimer")
    en = g.call("Conv_TextToString", KTXT)
    g.link(f"{e}.English", f"{en}.InText")
    cp = g.get("CarrierPrefix")
    isC = g.call("StartsWith", KSTR, SearchCase="IgnoreCase")
    g.link(f"{en}.ReturnValue", f"{isC}.SourceString")
    g.link(f"{cp}.CarrierPrefix", f"{isC}.InPrefix")
    setC = g.set("bCarrier")
    g.link(f"{isC}.ReturnValue", f"{setC}.bCarrier")
    rp = g.get("RadioPrefix")
    noC = g.call("Replace", KSTR, SearchCase="IgnoreCase")
    g.link(f"{en}.ReturnValue", f"{noC}.SourceString")
    g.link(f"{cp}.CarrierPrefix", f"{noC}.From")
    emp = g.get("Empty")
    g.link(f"{emp}.Empty", f"{noC}.To")
    noR = g.call("Replace", KSTR, SearchCase="IgnoreCase")
    g.link(f"{noC}.ReturnValue", f"{noR}.SourceString")
    g.link(f"{rp}.RadioPrefix", f"{noR}.From")
    g.link(f"{emp}.Empty", f"{noR}.To")
    sEn = g.set("EnRest")
    g.link(f"{noR}.ReturnValue", f"{sEn}.EnRest")
    sk = g.call("Conv_TextToString", KTXT)
    g.link(f"{e}.Saskartan", f"{sk}.InText")
    sSk = g.set("SksRest")
    g.link(f"{sk}.ReturnValue", f"{sSk}.SksRest")
    ln = g.call("Len", KSTR)
    g.link(f"{noR}.ReturnValue", f"{ln}.S")
    lnF = g.call("Conv_IntToDouble", KML)
    g.link(f"{ln}.ReturnValue", f"{lnF}.InInt")
    lnM = g.call("FMax", KML, B="1.0")
    g.link(f"{lnF}.ReturnValue", f"{lnM}.A")
    sT = g.set("TotalLen")
    g.link(f"{lnM}.ReturnValue", f"{sT}.TotalLen")
    dM = g.call("FMax", KML, B="1.0")
    g.link(f"{e}.DurationS", f"{dM}.A")
    sD = g.set("LineDur")
    g.link(f"{dM}.ReturnValue", f"{sD}.LineDur")
    # speaker label: CARRIER for carrier lines, RADIO HOST for the KEEPER voice slot, else the Speaker name.
    spS = g.call("Conv_NameToString", KSTR)
    g.link(f"{e}.Speaker", f"{spS}.InName")
    carrierName = g.get("CarrierPrefix")
    trimName = g.call("Replace", KSTR, From=": ")  # To stays empty (an empty literal is refused)
    g.link(f"{carrierName}.CarrierPrefix", f"{trimName}.SourceString")
    spSel = g.call("SelectString", KML)
    g.link(f"{trimName}.ReturnValue", f"{spSel}.A")
    g.link(f"{spS}.ReturnValue", f"{spSel}.B")
    g.link(f"{isC}.ReturnValue", f"{spSel}.bPickA")
    isHost = g.call("EqualEqual_StrStr", KSTR, B="KEEPER")
    g.link(f"{spSel}.ReturnValue", f"{isHost}.A")
    hostName = g.call("SelectString", KML, A="RADIO HOST")
    g.link(f"{spSel}.ReturnValue", f"{hostName}.B")
    g.link(f"{isHost}.ReturnValue", f"{hostName}.bPickA")
    up = g.call("ToUpper", KSTR)
    g.link(f"{hostName}.ReturnValue", f"{up}.SourceString")
    spT = settext(g, "SpeakerLabel", to_text(g, f"{up}.ReturnValue"))
    isNone = g.call("EqualEqual_StrStr", KSTR, B="None")
    g.link(f"{spSel}.ReturnValue", f"{isNone}.A")
    spBr = g.add({"branch": True}, "ifNoSpeaker")
    g.link(f"{isNone}.ReturnValue", f"{spBr}.Condition")
    spHide, spShow = vis(g, "SpeakerPlate", "Collapsed"), vis(g, "SpeakerPlate", "HitTestInvisible")
    # carrier vs voice text styles
    cBr = g.add({"branch": True}, "ifCarrier")
    g.link(f"{isC}.ReturnValue", f"{cBr}.Condition")
    a1, a2 = vis(g, "CarrierBox", "HitTestInvisible"), vis(g, "EnglishBox", "Collapsed")
    b1, b2 = vis(g, "CarrierBox", "Collapsed"), vis(g, "EnglishBox", "HitTestInvisible")
    # header
    hEmpty = g.call("TextIsEmpty", KTXT)
    g.link(f"{e}.Header", f"{hEmpty}.InText")
    hBr = g.add({"branch": True}, "ifHeader")
    g.link(f"{hEmpty}.ReturnValue", f"{hBr}.Condition")
    hT = settext(g, "HeaderLabel", f"{e}.Header")
    hV = vis(g, "HeaderBox", "HitTestInvisible")
    hTgt = g.set("HeadTarget", "1.0")
    hTm = timer(g, "headerTimer", "HideHeader", seconds=HEADER_S)
    hSt = g.set("HeaderTimer")
    g.link(f"{hTm}.ReturnValue", f"{hSt}.HeaderTimer")
    nxt = g.call("NextChunk")
    box = vis(g, "SubtitleBox", "HitTestInvisible")
    tgt = g.set("SubTarget", "1.0")
    fade = g.call("StartFade")
    upd = g.call("UpdateMaxW")
    g.chain(e, c1, c2, upd, sEn, sSk, sT, sD, setC, spT, spBr)
    g.chain(f"{spBr}.then", spHide, cBr)
    g.chain(f"{spBr}.else", spShow, cBr)
    g.chain(f"{cBr}.then", a1, a2, hBr)
    g.chain(f"{cBr}.else", b1, b2, hBr)
    g.chain(f"{hBr}.else", hT, hV, hTgt, hTm, hSt, nxt)
    g.chain(f"{hBr}.then", nxt)
    g.chain(nxt, box, tgt, fade)
    graphs.append(g.spec())

    # --- NextChunk: the next <= 2-line piece of each language, balanced; schedules the one after.
    g = G("NextChunk")
    e = g.add({"entry": True}, "entry")
    # CutChunk / Layout are impure: they run on the exec chain first, and the Rest variables are written last.
    er, sr = g.get("EnRest"), g.get("SksRest")
    cutE = g.call("CutChunk", None, CharPx=str(EN_CHAR))
    g.link(f"{er}.EnRest", f"{cutE}.S")
    cutS = g.call("CutChunk", None, CharPx=str(SKS_CHAR))
    g.link(f"{sr}.SksRest", f"{cutS}.S")
    lays = {}
    for box, char, pin in (("EnglishBox", EN_CHAR, f"{cutE}.Chunk"), ("CarrierBox", TERM_CHAR, f"{cutE}.Chunk"), ("SaskartanBox", SKS_CHAR, f"{cutS}.Chunk")):
        b = g.get(box)
        f = g.call("Layout", None, CharPx=str(char))
        g.link(f"{b}.{box}", f"{f}.Box")
        g.link(pin, f"{f}.Chunk")
        lays[box] = f
    t1 = settext(g, "EnglishLine", to_text(g, f"{lays['EnglishBox']}.Out"))
    t2 = settext(g, "CarrierLine", to_text(g, f"{lays['CarrierBox']}.Out"))
    t3 = settext(g, "SaskartanLine", to_text(g, f"{lays['SaskartanBox']}.Out"))
    sE = g.set("EnRest")
    g.link(f"{cutE}.Rest", f"{sE}.EnRest")
    sS = g.set("SksRest")
    g.link(f"{cutS}.Rest", f"{sS}.SksRest")
    skL = g.call("Len", KSTR)
    g.link(f"{cutS}.Chunk", f"{skL}.S")
    skE = g.call("LessEqual_IntInt", KML, B="0")
    g.link(f"{skL}.ReturnValue", f"{skE}.A")
    skBr = g.add({"branch": True}, "ifNoSks")
    g.link(f"{skE}.ReturnValue", f"{skBr}.Condition")
    # Keep the source text for timing, but captions render in English only.
    skH, skV = vis(g, "SaskartanBox", "Collapsed"), vis(g, "SaskartanBox", "Collapsed")
    # more to come? chunk time = LineDur * len(chunk) / TotalLen
    rl = g.call("Len", KSTR)
    g.link(f"{cutE}.Rest", f"{rl}.S")
    more = g.call("Greater_IntInt", KML, B="0")
    g.link(f"{rl}.ReturnValue", f"{more}.A")
    mBr = g.add({"branch": True}, "ifMore")
    g.link(f"{more}.ReturnValue", f"{mBr}.Condition")
    cl = g.call("Len", KSTR)
    g.link(f"{cutE}.Chunk", f"{cl}.S")
    clF = g.call("Conv_IntToDouble", KML)
    g.link(f"{cl}.ReturnValue", f"{clF}.InInt")
    ld, tl = g.get("LineDur"), g.get("TotalLen")
    mul = g.call("Multiply_DoubleDouble", KML)
    g.link(f"{ld}.LineDur", f"{mul}.A")
    g.link(f"{clF}.ReturnValue", f"{mul}.B")
    div = g.call("Divide_DoubleDouble", KML)
    g.link(f"{mul}.ReturnValue", f"{div}.A")
    g.link(f"{tl}.TotalLen", f"{div}.B")
    atLeast = g.call("FMax", KML, B="1.2")
    g.link(f"{div}.ReturnValue", f"{atLeast}.A")
    tm = timer(g, "chunkTimer", "NextChunk", seconds_pin=f"{atLeast}.ReturnValue")
    st = g.set("ChunkTimer")
    g.link(f"{tm}.ReturnValue", f"{st}.ChunkTimer")
    g.chain(e, cutE, cutS, *lays.values(), t1, t2, t3, sE, sS, skBr)
    g.chain(f"{skBr}.then", skH, mBr)
    g.chain(f"{skBr}.else", skV, mBr)
    g.chain(f"{mBr}.then", tm, st)
    graphs.append(g.spec())

    # --- HideSubtitle: hold 0.4 s more, then fade out
    g = G("HideSubtitle")
    e = g.add({"entry": True}, "entry")
    tm = timer(g, "hold", "BeginFadeOut", seconds=HOLD_EXTRA_S)
    st = g.set("HideTimer")
    g.link(f"{tm}.ReturnValue", f"{st}.HideTimer")
    g.chain(e, tm, st)
    graphs.append(g.spec())

    g = G("BeginFadeOut")
    e = g.add({"entry": True}, "entry")
    g.chain(e, clear(g, "ChunkTimer"), g.set("SubTarget", "0.0"), g.call("StartFade"))
    graphs.append(g.spec())

    g = G("HideHeader")
    e = g.add({"entry": True}, "entry")
    g.chain(e, g.set("HeadTarget", "0.0"), g.call("StartFade"))
    graphs.append(g.spec())

    g = G("StartFade")
    e = g.add({"entry": True}, "entry")
    tm = timer(g, "fade", "FadeStep", seconds=STEP_S, loop=True)
    st = g.set("FadeTimer")
    g.link(f"{tm}.ReturnValue", f"{st}.FadeTimer")
    g.chain(e, tm, st)
    graphs.append(g.spec())

    # --- FadeStep: subtitle and header alphas (0.25 s), the letterbox (0.8 s, ease in-out, the
    #     subtitle rides up above the bar); collapses a faded subtitle; stops when everything settled.
    g = G("FadeStep")
    e = g.add({"entry": True}, "entry")
    execs = []

    def step(alpha, target, speed):
        a, t = g.get(alpha), g.get(target)
        it = g.call("FInterpTo_Constant", KML, DeltaTime=str(STEP_S), InterpSpeed=str(speed))
        g.link(f"{a}.{alpha}", f"{it}.Current")
        g.link(f"{t}.{target}", f"{it}.Target")
        s = g.set(alpha)
        g.link(f"{it}.ReturnValue", f"{s}.{alpha}")
        execs.append(s)
        return f"{it}.ReturnValue"

    sa = step("SubAlpha", "SubTarget", FADE_SPEED)
    ha = step("HeadAlpha", "HeadTarget", FADE_SPEED)
    la = step("LbAlpha", "LbTarget", 1.0 / LB_BLEND_S)
    eased = g.call("Ease", KML, A="0.0", B="1.0", EasingFunc="EaseInOut", BlendExp="2.0", Steps="2")
    g.link(la, f"{eased}.Alpha")
    E = f"{eased}.ReturnValue"
    for widget, pin in (("SubtitleBox", sa), ("HeaderBox", ha), ("LetterboxTop", E), ("LetterboxBottom", E)):
        w = g.get(widget)
        c = g.call("SetRenderOpacity", W)
        g.link(f"{w}.{widget}", f"{c}.self")
        g.link(pin, f"{c}.InOpacity")
        execs.append(c)
    off = g.call("Subtract_DoubleDouble", KML, A="1.0")
    g.link(E, f"{off}.B")
    px = g.call("Multiply_DoubleDouble", KML, B=str(BAR_PX))
    g.link(f"{off}.ReturnValue", f"{px}.A")
    neg = g.call("Multiply_DoubleDouble", KML, B="-1.0")
    g.link(f"{px}.ReturnValue", f"{neg}.A")
    up = g.call("Multiply_DoubleDouble", KML, B=str(-BAR_PX))
    g.link(E, f"{up}.A")
    for widget, ypin in (("LetterboxTop", f"{neg}.ReturnValue"), ("LetterboxBottom", f"{px}.ReturnValue"), ("SubtitleBox", f"{up}.ReturnValue")):
        v = g.call("MakeVector2D", KML, X="0.0")
        g.link(ypin, f"{v}.Y")
        w = g.get(widget)
        c = g.call("SetRenderTranslation", W)
        g.link(f"{w}.{widget}", f"{c}.self")
        g.link(f"{v}.ReturnValue", f"{c}.Translation")
        execs.append(c)
    # a faded-out subtitle collapses
    s0 = g.call("LessEqual_DoubleDouble", KML, B="0.001")
    g.link(sa, f"{s0}.A")
    st0 = g.get("SubTarget")
    tz = g.call("LessEqual_DoubleDouble", KML, B="0.001")
    g.link(f"{st0}.SubTarget", f"{tz}.A")
    gone = g.call("BooleanAND", KML)
    g.link(f"{s0}.ReturnValue", f"{gone}.A")
    g.link(f"{tz}.ReturnValue", f"{gone}.B")
    gBr = g.add({"branch": True}, "ifGone")
    g.link(f"{gone}.ReturnValue", f"{gBr}.Condition")
    coll = vis(g, "SubtitleBox", "Collapsed")
    # settled? every alpha at its target
    settled = None
    for alpha, target in (("SubAlpha", "SubTarget"), ("HeadAlpha", "HeadTarget"), ("LbAlpha", "LbTarget")):
        a, t = g.get(alpha), g.get(target)
        ne = g.call("NearlyEqual_FloatFloat", KML, ErrorTolerance="0.0005")
        g.link(f"{a}.{alpha}", f"{ne}.A")
        g.link(f"{t}.{target}", f"{ne}.B")
        if settled is None:
            settled = f"{ne}.ReturnValue"
        else:
            andn = g.call("BooleanAND", KML)
            g.link(settled, f"{andn}.A")
            g.link(f"{ne}.ReturnValue", f"{andn}.B")
            settled = f"{andn}.ReturnValue"
    sBr = g.add({"branch": True}, "ifSettled")
    g.link(settled, f"{sBr}.Condition")
    stop = clear(g, "FadeTimer")
    g.chain(e, *execs, gBr)
    g.chain(f"{gBr}.then", coll, sBr)
    g.chain(f"{gBr}.else", sBr)
    g.chain(f"{sBr}.then", stop)
    graphs.append(g.spec())

    # --- key prompt helpers
    def kp_config(g, widget, glyph, glyph2, pad, label_var, hold, size):
        w = g.get(widget)
        c = g.call("Configure", KEYPROMPT_C, InGlyph=glyph, InGlyph2=glyph2, InGlyphPad=pad, bInHold="true" if hold else "false", InIconSize=str(size))
        g.link(f"{w}.{widget}", f"{c}.self")
        lv = g.get(label_var)
        g.link(f"{lv}.{label_var}", f"{c}.InLabel")
        w2 = g.get(widget)
        sh = g.call("Show", KEYPROMPT_C)
        g.link(f"{w2}.{widget}", f"{sh}.self")
        return c, sh

    def kp_hide(g, widget):
        w = g.get(widget)
        h = g.call("Hide", KEYPROMPT_C)
        g.link(f"{w}.{widget}", f"{h}.self")
        return h

    # --- captions: HUD query, independent stele reading, controls, or plain caption plate
    for name, visibility in (("ShowCaption", "HitTestInvisible"), ("HideCaption", "Collapsed")):
        g = G(name)
        e = g.add({"entry": True}, "entry")
        isHud = g.call("EqualEqual_NameName", KML, B="Hud")
        g.link(f"{e}.Target", f"{isHud}.A")
        isScan = g.call("EqualEqual_NameName", KML, B="Scan")
        g.link(f"{e}.Target", f"{isScan}.A")
        isPrompt = g.call("EqualEqual_NameName", KML, B="ScanPrompt")
        g.link(f"{e}.Target", f"{isPrompt}.A")
        isCol = g.call("EqualEqual_NameName", KML, B="HudColumn")
        g.link(f"{e}.Target", f"{isCol}.A")
        colBr = g.add({"branch": True}, "ifHudColumn")
        g.link(f"{isCol}.ReturnValue", f"{colBr}.Condition")
        br = g.add({"branch": True}, "ifHud")
        scanBr = g.add({"branch": True}, "ifScan")
        promptBr = g.add({"branch": True}, "ifScanPrompt")
        g.link(f"{isPrompt}.ReturnValue", f"{promptBr}.Condition")
        g.link(f"{isHud}.ReturnValue", f"{br}.Condition")
        g.link(f"{isScan}.ReturnValue", f"{scanBr}.Condition")
        # the ?-column first: its own target, persistent until hidden (B18 fades it)
        g.chain(e, colBr)
        g.chain(f"{colBr}.else", br)
        if name == "ShowCaption":
            g.chain(f"{colBr}.then", settext(g, "HudQuestions", f"{e}.Text"), vis(g, "HudQuestions", visibility))
        else:
            g.chain(f"{colBr}.then", vis(g, "HudQuestions", visibility))
        if name == "ShowCaption":
            g.chain(f"{br}.then", settext(g, "HudLine", f"{e}.Text"), vis(g, "HudLine", visibility))
            g.chain(f"{br}.else", scanBr)
            g.chain(f"{scanBr}.then", settext(g, "ScanBlock", f"{e}.Text"), vis(g, "ScanBlock", visibility))
            cl = g.call("Conv_TextToString", KTXT)
            g.link(f"{e}.Text", f"{cl}.InText")
            isCtl = g.call("StartsWith", KSTR, InPrefix=CONTROLS_PREFIX, SearchCase="IgnoreCase")
            g.link(f"{cl}.ReturnValue", f"{isCtl}.SourceString")
            brC = g.add({"branch": True}, "ifControls")
            g.link(f"{isCtl}.ReturnValue", f"{brC}.Condition")
            steps = []
            for w, gl, gl2, pad, _lab in CONTROLS:
                steps += list(kp_config(g, w, gl, gl2, pad, "Label" + w[3:], False, 44))
            b = g.get("CaptionTextBox")
            fit = g.call("Layout", CharPx=str(CAP_CHAR))
            g.link(f"{b}.CaptionTextBox", f"{fit}.Box")
            g.link(f"{cl}.ReturnValue", f"{fit}.Chunk")
            g.chain(f"{scanBr}.else", promptBr)
            g.chain(f"{promptBr}.then", settext(g, "ScanPromptLine", f"{e}.Text"), vis(g, "ScanPromptLine", visibility))
            g.chain(f"{promptBr}.else", brC)
            g.chain(f"{brC}.then", *steps, vis(g, "ControlsRow", visibility))
            g.chain(f"{brC}.else", g.call("UpdateMaxW"), fit, settext(g, "CaptionLine", to_text(g, f"{fit}.Out")), vis(g, "CaptionBox", visibility))
        else:
            g.chain(f"{br}.then", vis(g, "HudLine", visibility))
            g.chain(f"{br}.else", scanBr)
            g.chain(f"{scanBr}.then", vis(g, "ScanBlock", visibility))
            g.chain(f"{scanBr}.else", promptBr)
            g.chain(f"{promptBr}.then", vis(g, "ScanPromptLine", visibility))
            g.chain(f"{promptBr}.else", vis(g, "CaptionBox", visibility), vis(g, "ControlsRow", visibility),
                    *[kp_hide(g, w) for w, *_r in CONTROLS])
        graphs.append(g.spec())

    # --- the event prompt: E / A key prompt + the line
    g = G("ShowPrompt")
    e = g.add({"entry": True}, "entry")
    c, sh = kp_config(g, "KP_Prompt", "Key_E", "None", "Pad_A", "NoLabel", False, 40)
    g.chain(e, c, sh, settext(g, "PromptLine", f"{e}.Text"), vis(g, "PromptBox", "HitTestInvisible"))
    graphs.append(g.spec())

    g = G("HidePrompt")
    e = g.add({"entry": True}, "entry")
    g.chain(e, vis(g, "PromptBox", "Collapsed"), kp_hide(g, "KP_Prompt"))
    graphs.append(g.spec())

    g = G("SetLetterbox")
    e = g.add({"entry": True}, "entry")
    tgt = g.call("SelectFloat", KML, A="1.0", B="0.0")
    g.link(f"{e}.bOn", f"{tgt}.bPickA")
    st = g.set("LbTarget")
    g.link(f"{tgt}.ReturnValue", f"{st}.LbTarget")
    g.chain(e, st, g.call("StartFade"))
    graphs.append(g.spec())

    # --- hold to skip: configure the Space / B hold prompt once, then fill its ring; visible while held
    g = G("SetSkipProgress")
    e = g.add({"entry": True}, "entry")
    rd = g.get("bSkipReady")
    brR = g.add({"branch": True}, "ifReady")
    g.link(f"{rd}.bSkipReady", f"{brR}.Condition")
    c, sh = kp_config(g, "KP_Skip", "Key_Space", "None", "Pad_B", "LabelSkip", True, 36)
    sr = g.set("bSkipReady", "true")
    kp = g.get("KP_Skip")
    hp = g.call("SetHoldProgress", KEYPROMPT_C)
    g.link(f"{kp}.KP_Skip", f"{hp}.self")
    g.link(f"{e}.Fraction", f"{hp}.Fraction")
    pos = g.call("Greater_DoubleDouble", KML, B="0.0")
    g.link(f"{e}.Fraction", f"{pos}.A")
    o = g.call("SelectFloat", KML, A="1.0", B="0.0")
    g.link(f"{pos}.ReturnValue", f"{o}.bPickA")
    box = g.get("SkipBox")
    so = g.call("SetRenderOpacity", W)
    g.link(f"{box}.SkipBox", f"{so}.self")
    g.link(f"{o}.ReturnValue", f"{so}.InOpacity")
    g.chain(e, brR)
    g.chain(f"{brR}.else", c, sh, sr, hp)
    g.chain(f"{brR}.then", hp)
    g.chain(hp, so)
    graphs.append(g.spec())

    ec = endcard_graph()
    return {"asset": WBP, "description": "LANE5 caption layer functions; the runner bindings come from editor/caption_graph.py.",
            "variables": variables + ec["variables"], "functions": functions + ec["functions"],
            "graphs": graphs + ec["graphs"]}


if __name__ == "__main__":
    specs = ROOT / "Tools" / "GameFlow" / "specs"
    (specs / "WBP_Saskarta_Caption.tree.json").write_text(json.dumps(tree(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (specs / "WBP_Saskarta_Caption.graph.json").write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (specs / "WBP_Saskarta_Caption.endcard.tree.json").write_text(
        json.dumps(endcard_tree(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (specs / "WBP_Saskarta_Caption.endcard.graph.json").write_text(
        json.dumps(endcard_graph(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote canonical and scoped end-card tree + graph")
