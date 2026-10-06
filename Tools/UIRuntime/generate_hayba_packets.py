"""Generate native Hayba UMG packets offline; no editor or graphics work."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "specs"
BASE = "/Game/SaskartaGaea/GameFlow/UI"
FONT = BASE + "/Fonts/Font_Terminal.Font_Terminal"
CAPTION = BASE + "/Fonts/F_ArefRuqaa_Caption.F_ArefRuqaa_Caption"


def node(cls, name, children=None, props=None, slot=None):
    result = {"class": cls, "name": name}
    if children is not None: result["children"] = children
    if props: result["properties"] = props
    if slot: result["slot_props"] = slot
    return result


def text(name, value, size, caption=False, collapsed=False):
    props = {"Text": value, "Font": {"FontObject": CAPTION if caption else FONT, "Size": size},
             "ColorAndOpacity": {"SpecifiedColor": [.94, .91, .81, 1]},
             "ShadowColorAndOpacity": [0, 0, 0, .92], "ShadowOffset": {"X": 1.5, "Y": 2}}
    if collapsed: props["Visibility"] = "Collapsed"
    return node("TextBlock", name, props=props)


def box(name, children, width=None, height=None):
    props = {}
    if width is not None: props.update(bOverride_WidthOverride=True, WidthOverride=width)
    if height is not None: props.update(bOverride_HeightOverride=True, HeightOverride=height)
    return node("SizeBox", name, children, props)


def panel(name, content):
    return node("Border", name, [node("VerticalBox", name + "Content", content)],
                {"BrushColor": [0, 0, 0, 0], "Padding": {"Left": 0, "Top": 5, "Right": 0, "Bottom": 5}},
                {"padding": [0, 0, 0, 6]})


def collect(nodes):
    found = {}
    for item in nodes:
        found[item["name"]] = item["class"].rsplit(".", 1)[-1]
        found.update(collect(item.get("children", [])))
    return found


def packet(name, parent, tree, slots):
    asset = BASE + "/" + name
    return {"asset": asset, "create": {"path": BASE, "name": name, "parent_class": "/Script/SaskartaCore." + parent},
            "tree": tree, "slots": slots, "variables": [], "expected_parent": "/Script/SaskartaCore." + parent,
            "expected_widgets": collect(tree), "strict_compile": True, "force_save": True}


accent = box("WarningAccentBounds", [node("Border", "PowerWarningAccent", props={"BrushColor": [1, .74, .28, 1]})], 320, 2)
accent["slot_props"] = {"padding": [0, 0, 0, 5]}
loads = text("PowerLoads", "Stop to recharge the biofuel cell.", 16)
loads["properties"]["AutoWrapText"] = True
notices = panel("PowerNotices", [accent, text("PowerWarningTitle", "[!] Low charge", 20), loads])
segments = []
for index in range(7):
    segment = box("BatterySegmentBounds" + str(index), [node("ProgressBar", "BatterySegment" + str(index), props={
        "Percent": 1 if index < 5 else 0, "FillColorAndOpacity": [.63, .88, .66, 1]})], 32, 10)
    segment["slot_props"] = {"padding": [0, 0, 4, 0]}
    segments.append(segment)
gauge = node("HorizontalBox", "BatteryGauge", segments, slot={"padding": [0, 5, 0, 5]})
battery = panel("BatteryInspection", [text("BatteryLabel", "BIOFUEL CELL", 14), text("BatteryPercent", "72%", 30), gauge, text("BatteryState", "RANGE 1.2 KM", 16)])
columns = []
for prefix, title, scale in (("Speed", "SPEED 18.7 KM/H", "0 - 40 KM/H"), ("Altitude", "ALT -351.3 M", "-355 - -349 M")):
    columns.append(node("VerticalBox", prefix + "Column", [text("Actual" + prefix, title, 22), text(prefix + "Scale", scale, 14),
        node("/Script/SaskartaCore.SaskartaTelemetryGraph", prefix + "Trace")], slot={"fill": 1, "padding": [0, 0, 12, 0]}))
instruments = panel("DrivingInstruments", [node("HorizontalBox", "TelemetryColumns", columns), text("AltitudeDatum", "ALT: WORLD DATUM . RPM 800", 14), text("TelemetryToggle", "H . HIDE . LAST 12 S", 14)])
power_tree = [box("PowerDisplay", [node("VerticalBox", "PowerContent", [notices, battery, instruments])], 420)]
power_packet = packet("WBP_Saskarta_Power", "SaskartaPowerWidget", power_tree, {"PowerDisplay": {"anchors": [0, 0, 0, 0], "position": [28, 40], "size": [420, 300], "auto_size": True}})

motor_tree = [node("CanvasPanel", "MotorScreen", [
    node("Border", "MotorGlass", props={"BrushColor": [0, 0, 0, 0]}),
    node("/Script/SaskartaCore.SaskartaMotorRetainer", "MotorPhosphor", [node("/Script/SaskartaCore.SaskartaMotorDiagram", "MotorMechanism")], {"bRetainRender": False})
], {"RenderTransformPivot": {"X": 0, "Y": 1}, "RenderTransform": {"Scale": {"X": .66, "Y": .66}}})]
motor_packet = packet("WBP_Saskarta_Motor", "SaskartaMotorResonanceWidget", motor_tree, {
    "MotorScreen": {"anchors": [0, 1, 0, 1], "alignment": [0, 1], "position": [28, -232], "size": [720, 384]},
    "MotorGlass": {"position": [0, 0], "size": [720, 384]}, "MotorPhosphor": {"position": [0, 0], "size": [720, 384]}})

glyph_names = ("Key_W", "Key_S", "Key_A", "Key_D", "Mouse_Move")
groups = []
for group in range(7):
    content = []
    for within in range(2):
        index = group * 2 + within
        image_props = {}
        if index < len(glyph_names):
            name = "T_Prompt_" + glyph_names[index]
            image_props["Brush"] = {"ResourceObject": "/Game/SaskartaGaea/UI/Prompts/Light/" + name + "." + name, "DrawAs": "Image"}
        image = node("Image", "HintGlyph" + str(index), props=image_props)
        bounds = box("HintGlyphBox" + str(index), [image], 38, 38)
        if index >= len(glyph_names): bounds.setdefault("properties", {})["Visibility"] = "Collapsed"
        bounds["slot_props"] = {"padding": [2, 0, 2, 0], "vertical_alignment": "Center"}
        content.append(bounds)
    caption = text("HintCaption" + str(group), ("DRIVE", "STEER", "LOOK")[group] if group < 3 else "", 17, caption=True, collapsed=group >= 3)
    caption["properties"].update(Justification="Left", WrapTextAt=620)
    caption["slot_props"] = {"padding": [8, 0, 22, 0], "vertical_alignment": "Center"}
    content.append(caption)
    groups.append(node("HorizontalBox", "HintGroup" + str(group), content, slot={"vertical_alignment": "Center"}))
hint_row = node("HorizontalBox", "HintRow", groups, slot={"horizontal_alignment": "Left", "vertical_alignment": "Center"})
hint_accent = box("HintAccentBounds", [node("Border", "HintAccent", props={"BrushColor": [.82, .65, .36, .85]})], 48, 2)
hint_accent["slot_props"] = {"padding": [0, 0, 0, 6]}
hint_header = text("HintSystemHeader", "SYSTEM / CARRIER ASSIST", 12)
hint_header["properties"]["ColorAndOpacity"] = {"SpecifiedColor": [.84, .76, .59, .95]}
hint_header["slot_props"] = {"padding": [0, 0, 0, 5]}
hint_bounds = box("HintBounds", [node("VerticalBox", "HintNotification", [hint_accent, hint_header, hint_row])], 660, 84)
hints_tree = [node("ScaleBox", "HintFit", [hint_bounds], {"Stretch": "ScaleToFit", "StretchDirection": "DownOnly"})]
hints_packet = packet("WBP_Saskarta_GameplayHints", "SaskartaGameplayHintWidget", hints_tree, {
    "HintFit": {"anchors": [0, 1, 0, 1], "alignment": [0, 1], "position": [28, -32], "size": [660, 84]}})

repair_fields = [text("ReceiverTitle", "CISTERN / RECEIVER ALIGNMENT", 24), text("RepairStage", "1 / AIM THE AERIAL", 22),
    text("RepairValues", "AERIAL +0 DEG   TUNE +0.00   SIGNAL 0%", 17),
    box("SignalBounds", [node("ProgressBar", "SignalBar", props={"FillColorAndOpacity": [.63, .88, .66, 1], "bIsVariable": False})], height=8),
    text("RepairInstructions", "TURN THE AERIAL THROUGH THE STATIC", 17),
    text("EnvelopeLabel", "LIVE VOICE ENVELOPE", 13),
    node("/Script/SaskartaCore.SaskartaTelemetryGraph", "EnvelopeGraph", props={"bIsVariable": False}),
    text("RepairStability", "FIND THE STRONG SIGNAL", 16),
    box("StabilityBounds", [node("ProgressBar", "StabilityBar", props={"FillColorAndOpacity": [.63, .88, .66, 1], "bIsVariable": False})], height=6),
    text("RepairExit", "T CLOSE . ESC PAUSE", 13)]
for item in repair_fields:
    item["slot_props"] = {"padding": [0, 0, 0, 10]}
repair_card = node("CanvasPanel", "RepairCard", [node("Border", "ReceiverGlass", [node("VerticalBox", "ReceiverContent", repair_fields)],
    {"BrushColor": [.008, .009, .006, .55], "Padding": {"Left": 20, "Top": 18, "Right": 20, "Bottom": 18}},
    {"anchors_min": [0, 0], "anchors_max": [1, 1], "position": [0, 0], "size": [0, 0]})])
repair_title = text("ReceptionHeader", "SYSTEM / RECEPTION DRIFT", 12)
repair_title["properties"]["ColorAndOpacity"] = {"SpecifiedColor": [.84, .76, .59, .95]}
repair_title["slot_props"] = {"padding": [0, 0, 0, 7]}
repair_glyph = box("ReceptionGlyphBounds", [node("Overlay", "ReceptionKeyPlate", [
    node("Image", "ReceptionGlyph", props={"Brush": {
        "ResourceObject": "/Game/SaskartaGaea/UI/Prompts/Light/T_Prompt_Pad_Y.T_Prompt_Pad_Y", "DrawAs": "Image"}, "Visibility": "Collapsed"}),
    text("ReceptionKey", "T", 22)])], 38, 38)
repair_glyph["slot_props"] = {"vertical_alignment": "Center", "padding": [0, 0, 10, 0]}
repair_text = text("ReceptionAction", "PARK TO ADJUST THE AERIAL", 17, caption=True)
repair_text["slot_props"] = {"vertical_alignment": "Center"}
repair_accent = box("ReceptionAccentBounds", [node("Border", "ReceptionAccent", props={"BrushColor": [.82, .65, .36, .85]})], 48, 2)
repair_accent["slot_props"] = {"padding": [0, 0, 0, 6]}
repair_prompt = node("Border", "ReceptionPrompt", [node("VerticalBox", "ReceptionNotification", [repair_accent, repair_title,
    node("HorizontalBox", "ReceptionControls", [repair_glyph, repair_text])])], {"BrushColor": [0, 0, 0, 0]})
repair_packet = packet("WBP_Saskarta_RadioRepair", "SaskartaRadioRepairWidget", [repair_card, repair_prompt], {
    "RepairCard": {"anchors": [.5, .5, .5, .5], "alignment": [.5, .5], "position": [0, -28], "size": [680, 420]},
    "ReceptionPrompt": {"anchors": [0, 1, 0, 1], "alignment": [0, 1], "position": [28, -132], "size": [620, 84]}})

OUT.mkdir(parents=True, exist_ok=True)
for entry in (power_packet, motor_packet, hints_packet, repair_packet):
    filename = OUT / (entry["create"]["name"] + ".tree.json")
    filename.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    print(str(filename) + " | " + str(len(entry["expected_widgets"])) + " widgets")
