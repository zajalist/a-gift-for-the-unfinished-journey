"""Offline subtitle refinement proposal. Does not contact Unreal or change source specs."""
import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ASSET = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Caption"
WARNING = "/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Subtitle"
TEXTURE = "/Game/SaskartaGaea/GameFlow/UI/Textures/T_UI_SoftPlate.T_UI_SoftPlate"


def command(name, **params):
    return {"command": name, "params": params}


def query(path, pattern=None):
    params = dict(path=path, flatten=True, include_properties=True, include_slot=True, include_guid=True)
    if pattern:
        params["name_pattern"] = pattern
    return command("ui_query", **params)


def props(widget, **properties):
    return command("ui_set_widget_properties", widget_blueprint_path=ASSET,
                   widget_name=widget, properties=properties)


def slot(widget, **layout):
    return command("ui_set_slot_layout", widget_blueprint_path=ASSET,
                   widget_name=widget, **layout)


def margin(left, top, right, bottom):
    return dict(Left=left, Top=top, Right=right, Bottom=bottom)


packet = {
    "status": "prepared_not_installed",
    "asset": ASSET,
    "requested_asset": WARNING,
    "asset_resolution": "Subtitle is the carrier warning widget; Caption contains the screenshot's RADIO HOST, SpeakerLabel and EnglishLine. Root must confirm current runtime owner and actual native tree before applying this Caption-only packet.",
    "expected_widgets": {
        "SubtitleBox": "VerticalBox", "SpeakerPlate": "Border", "SpeakerLabel": "TextBlock",
        "SubtitlePlate": "Border", "SubtitleStack": "VerticalBox", "EnglishBox": "SizeBox",
        "EnglishLine": "TextBlock", "CarrierBox": "SizeBox", "CarrierLine": "TextBlock",
        "SaskartanBox": "SizeBox"
    },
    "expected_parent_relationships": {
        "SpeakerPlate": "SubtitleBox", "SpeakerLabel": "SpeakerPlate",
        "SubtitlePlate": "SubtitleBox", "SubtitleStack": "SubtitlePlate",
        "EnglishBox": "SubtitleStack", "EnglishLine": "EnglishBox",
        "CarrierBox": "SubtitleStack", "CarrierLine": "CarrierBox"
    },
    "preflight": [query(WARNING)] + [query(ASSET, p) for p in ("Subtitle", "Speaker", "English", "Carrier", "Saskartan")],
    "commands": [
        props("SpeakerPlate", BrushColor=[1, 1, 1, 0], Padding=margin(10, 0, 10, 0)),
        slot("SpeakerPlate", padding=[0, 0, 0, 0], fill=0, horizontal_alignment="Center"),
        props("SubtitlePlate", Background={
            "ResourceObject": TEXTURE, "DrawAs": "Box", "ImageSize": {"X": 190, "Y": 84},
            "Margin": margin(0.4, 0.4, 0.4, 0.4),
            "TintColor": {"SpecifiedColor": [0, 0, 0, 0.36]}},
            BrushColor=[1, 1, 1, 1], Padding=margin(40, 4, 40, 10)),
        slot("SubtitlePlate", padding=[0, 0, 0, 0], fill=0, horizontal_alignment="Center")
    ],
    "compile": command("ui_compile_widget", widget_blueprint_path=ASSET, save_on_success=False),
    "save": command("ui_save_widget", widget_blueprint_path=ASSET, compile_first=False),
    "readback": [query(ASSET, p) for p in ("Subtitle", "Speaker", "English", "Carrier")],
    "designer_geometry_readback": [command("ui_layout_snapshot", widget_blueprint_path=ASSET,
        screen_width=w, screen_height=h, widget_names=["SubtitleBox", "SpeakerPlate", "SpeakerLabel",
        "SubtitlePlate", "EnglishBox", "EnglishLine", "CarrierBox", "CarrierLine"], limit=12)
        for w, h in ((1280, 720), (1920, 1080))],
    "preserved_runtime_behavior": [
        "Existing Layout/UpdateMaxW adaptive widths, line breaking, paging and settings-driven font behavior, if present in loaded asset. No Font or fixed WidthOverride writes.",
        "Existing SubtitleBox bottom-centre anchors, auto-size, fade, hold, replacement, visibility and letterbox translation.",
        "Existing Aref Ruqaa dialogue, gold speaker, terminal carrier, and all named widget identities."
    ],
    "acceptance": [
        "Root alone owns editor operations. Apply after PIE is stopped and root has actual current asset state for rollback.",
        "Require exact widget classes/relationships and actual parent class; never rebuild tree or redirect this packet to the warning Subtitle asset.",
        "Keep every preflight/mutation/compile/save/readback receipt. Reject failed_properties, unknown_slot_props, compile errors and unresolved saves. Require package_dirty_after_save=false.",
        "Readback: SpeakerPlate BrushColor alpha0 and Padding10/0/10/0; speaker slot padding0 and SizeRule Auto; SubtitlePlate Background texture/9-slice retained, tint alpha.36, BrushColor alpha1 and Padding40/4/40/10; subtitle slot padding0, center, SizeRule Auto.",
        "Do not force Font.Size, text, WidthOverride, render opacity or runtime visibility for the visual change.",
        "Designer SubtitleBox defaults Collapsed: layout_snapshot may produce zero or missing visible geometry. Such a receipt does not prove runtime layout; actual subtitle PIE capture is required for visual acceptance.",
        "Inspect actual one-line, two-line, carrier, long timed page and no-speaker cues against bright terrain. Speaker should sit in the same centered group with about 4-12 visible pixels to the first dialogue glyph, with no isolated dark speaker box.",
        "At720p/1080p check last line above the viewport edge and cinematic bar; no clipped glyph/feather, hard black strip or scene-wide band. Preserve adaptive line-length behavior; text remains readable at all three settings sizes.",
        "Authored gen_caption_specs.py and Caption graph do not currently contain a SubtitleSize/saskarta.subtitles.size/SetFont connection; settings emits the cvar. Root must read actual loaded behavior before claiming font-size settings work. This patch introduces no font-size regression.",
        "Apply source_sync_proposal.patch only after root's actual native readback acceptance; regenerate tree spec, retaining graph behavior."
    ],
    "prediction_design_pixels": {
        "speaker_to_dialogue_padding_before": 33,
        "speaker_to_dialogue_padding_after": 4,
        "main_plate_horizontal_padding_before": 132,
        "main_plate_horizontal_padding_after": 80,
        "main_plate_vertical_padding_before": 48,
        "main_plate_vertical_padding_after": 14,
        "main_plate_alpha_before": 0.62,
        "main_plate_alpha_after": 0.36,
        "note": "Predictions from source only; font ascenders/descenders and actual DPI affect visible gap."
    }
}
(OUT / "native_packet.json").write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")

source = ROOT / "Tools/GameFlow/gen_caption_specs.py"
before = source.read_text(encoding="utf-8")
old = 'typeface="Bold", spacing=180), pad=(18, 5, 18, 6), alpha=0.8),\n         "slot_props": {"horizontal_alignment": "Center", "padding": [0, 0, 0, 5]}},'
new = 'typeface="Bold", spacing=180), pad=(10, 0, 10, 0), alpha=0.8),\n         "slot_props": {"horizontal_alignment": "Center", "padding": [0, 0, 0, 0]}},'
if before.count(old) != 1:
    raise RuntimeError("Source synchronization anchor changed; proposal requires review.")
after = before.replace(old, new)
old2 = '        ]}),\n    ]}\n    caption = plate'
new2 = '        ]}, pad=(40, 4, 40, 10), alpha=0.36),\n    ]}\n    subtitle["children"][0]["properties"]["BrushColor"] = [1, 1, 1, 0]\n    subtitle["children"][1]["properties"]["BrushColor"] = [1, 1, 1, 1]\n    subtitle["children"][1]["slot_props"] = {"horizontal_alignment": "Center", "padding": [0, 0, 0, 0]}\n    caption = plate'
if after.count(old2) != 1:
    raise RuntimeError("Subtitle synchronization anchor changed; proposal requires review.")
after = after.replace(old2, new2)
patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
    fromfile="a/Tools/GameFlow/gen_caption_specs.py", tofile="b/Tools/GameFlow/gen_caption_specs.py"))
(OUT / "source_sync_proposal.patch").write_text(patch, encoding="utf-8")
print(json.dumps({"status": "prepared_not_installed", "asset": ASSET,
                  "outputs": [str(OUT / "native_packet.json"), str(OUT / "source_sync_proposal.patch")]}))
