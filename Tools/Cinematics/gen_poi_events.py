"""POI discovery beats (task CINEPOI): write them into docs/story/story-events.json and the glance targets.

    python Tools/Cinematics/gen_poi_events.py          # (re)write; idempotent
    python Tools/Cinematics/gen_poi_events.py --check  # exit 1 if the files are not what this script writes

Design: docs/story/POI_CINEMATICS.md. What it writes:
- `cinematics`: CIN_P04_AIRSHIP, CIN_P07_WAITING_WATER, CIN_06F_CREST_FORT (CIN_06 + a 4 s fort prelude, B06
  plays it instead of CIN_06 when the PoiCine tag is on), CIN_P15_WORKS, CIN_P17_CISTERN, CIN_PO01_LOW_VOICE.
  Their camera plans are in build_cinematics.py (POI_PLANS); durations and assets are read from the plans.
- `glances`: GP_* (road, at a spur junction or a far landmark) and GZ_* (off-road, on entering a POI zone).
- `optional_beats`: P* (road pass or `volume:POI_Oxx`), gated by the feature tags
  PoiCine (the cinematics), PoiGlance (the glances), PoiHud (the carrier's HUD log lines) and ScanPulse (the
  gameplay scan-pulse hook on the carrier). Nothing fires until the editor lane turns a tag on.
- `beats[B06_ROAD_AHEAD].actions`: CIN_06 (excludes PoiCine) + CIN_06F (requires PoiCine).
- Tools/GameFlow/glance_targets.json and the TARGETS line of Tools/GameFlow/editor/place_glance_targets.py.

`volume:<Id>` triggers need the SaskartaCore importer change (SaskartaStoryImport.cpp, CINEPOI) built at the
next closed-editor window; until then they import as None and never fire.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_cinematics as bc  # noqa: E402

STORY = REPO / "docs" / "story" / "story-events.json"
GLANCE_JSON = REPO / "Tools" / "GameFlow" / "glance_targets.json"
GLANCE_PY = REPO / "Tools" / "GameFlow" / "editor" / "place_glance_targets.py"
TETHER = REPO / "Tools" / "World" / "tether_paths.json"
SEQ = "/Game/SaskartaGaea/GameFlow/Cinematics/"
PING, PING_LONG = "SFX_Carrier_ScanPing", "SFX_Carrier_ScanPing_Long"
POI_PREFIXES = ("CIN_P", "CIN_06F", "GP_", "GZ_", "P0", "P1", "PH_", "PZ_")


def hud(at, text, dur=2.5):
    return {"at_s": at, "type": "ShowCaption", "target_tag": "Hud", "text": text, "duration_s": dur}


def sfx(at, sid=PING):
    return {"at_s": at, "type": "PlaySfx", "id": sid}


def cine(cid, beat, cues, *, letterbox=False, final_state=None, relative=True, blend_in=0.0, note=""):
    plan = bc.PLANS[cid]()
    d = {"beat": beat, "tier": "poi", "sequence": SEQ + plan["asset"], "duration_s": plan["duration"],
         "priority": "Cinematic", "blend_in_s": blend_in, "blend_out_s": plan["blend_out"], "letterbox": letterbox,
         "skip": "HoldAlways", "skip_min_s": 1.0, "stop_pawn": True, "keep_station_playing": True, "relative_to_pawn": relative,
         "hand_back": "CarrierPOV", "requires_tags": ["PoiCine"], "cues": cues, "final_state": final_state or []}
    if note:
        d["note"] = note
    return d


def poi_cinematics(story: dict) -> dict:
    c06 = story["cinematics"]["CIN_06_ROAD_AHEAD"]
    cues06f = [sfx(1.4), hud(2.0, "FORT · ITSET ITSET · UNGARRISONED", 2.0)]
    for c in c06["cues"]:
        c2 = dict(c)
        c2["at_s"] = round(c["at_s"] + 4.0, 2)
        cues06f.append(c2)
    return {
        "CIN_P04_AIRSHIP": cine("CIN_P04_AIRSHIP", "P04_AIRSHIP", [
            sfx(2.2, PING_LONG), hud(3.3, "HULL · RIGID · NO LIFT", 2.0), hud(5.6, "OBSERVATORY · SHUTTERS OPEN", 2.0)]),
        "CIN_P07_WAITING_WATER": cine("CIN_P07_WAITING_WATER", "P07_WAITING_WATER", [
            sfx(0.4), hud(1.4, "CHANNEL · DRY", 2.0), {"at_s": 2.5, "type": "ShowLetterbox", "value": 1},
            {"at_s": 6.9, "type": "ShowLetterbox", "value": 0}, hud(7.3, "REFINERY · COLD", 1.8)],
            note="One deliberate EXT (shot 2): the carrier small at the village edge. Letterbox only on that shot."),
        "CIN_06F_CREST_FORT": cine("CIN_06F_CREST_FORT", "B06_ROAD_AHEAD", cues06f, letterbox=True,
                                   final_state=c06.get("final_state", []),
                                   note="CIN_06 exactly, shifted +4 s after a POV fort prelude. Replaces CIN_06 in B06 when PoiCine is on."),
        "CIN_P15_WORKS": cine("CIN_P15_WORKS", "P15_WORKS", [
            sfx(1.6, PING_LONG), hud(2.6, "WORKS · FURNACE COLD", 2.2), {"at_s": 5.0, "type": "ShowLetterbox", "value": 1},
            {"at_s": 8.4, "type": "ShowLetterbox", "value": 0}]),
        "CIN_P17_CISTERN": cine("CIN_P17_CISTERN", "P17_CISTERN", [
            sfx(0.6), hud(1.2, "TARSAN · LEVEL 0 %", 2.4), {"at_s": 2.0, "type": "ShowLetterbox", "value": 1},
            {"at_s": 6.9, "type": "ShowLetterbox", "value": 0}]),
        "CIN_PO01_LOW_VOICE": cine("CIN_PO01_LOW_VOICE", "PZ_O01_LOW_VOICE", [
            {"at_s": 0.4, "type": "PlaySfx", "id": "SFX_TapeClick"}], letterbox=True, relative=False, blend_in=1.0,
            final_state=[{"type": "ShowCaption", "target_tag": "Hud", "text": "ILAAWB · SOURCE: NOT HERE", "duration_s": 3.0}],
            note="World frame (off-road). EXT only; the carrier is never in frame."),
    }


GLANCES = {
    # id: (site, group, key, rise, ease_in, hold)
    "GP_O09_GRAVEYARD": ("O09_CartGraveyard", "cradles", None, 0.5, 1.2, 1.5),
    "GP_O08_PUMPS": ("O08_WindPumps", "pumps", None, 0.8, 1.5, 2.0),
    "GZ_O03_BRIDGE": ("O03_BrokenBridge", "span", None, 0.6, 1.2, 1.8),
    "GZ_O06_DAM": ("O06_OldDam", "sluices", None, 0.6, 1.2, 1.8),
    "GZ_O09_CRADLES": ("O09_CartGraveyard", "cradles", None, 0.6, 1.2, 2.0),
    "GZ_O10_STILL": ("O10_ChemistWorkshop", "still", "T2_biofuel_still", 0.6, 1.2, 1.5),
    "GZ_O14_DOVECOTE": ("O14_GranaryHamlet", "dovecote", None, 0.7, 1.2, 1.5),
}


def glance_tag(gid: str) -> str:
    return "Saskarta.Glance.Poi" + "".join(w.capitalize() for w in gid.split("_")[1:])


def road_beat(bid, road_m, actions, tags, notes, max_late=None):
    b = {"id": bid, "distance_m": road_m, "ue_distance_from_p0_m": round(bc.ue_m_for_road_m(road_m), 1),
         "trigger": "pass", "requires_tags": tags, "one_shot": True, "tier": "poi", "actions": actions, "notes": notes}
    if max_late is not None:
        b["max_lateness_s"] = max_late
    return b


def zone_beat(pid, zone, actions, tags, notes):
    cx, cy, cz = zone["centre_cm"]
    r = zone["radius_cm"]
    return {"id": f"PZ_{pid}", "trigger": f"volume:POI_{pid}", "requires_tags": tags, "one_shot": True, "tier": "poi",
            "max_lateness_s": 6.0,
            "volume": {"trigger_id": f"POI_{pid}", "centre_cm": [cx, cy, cz], "extent_cm": [round(r * 0.75), round(r * 0.75), 3000],
                       "note": "ASaskartaEventVolume, box inside the explore zone; Gameplay folder, not spatially loaded"},
            "actions": actions, "notes": notes}


def glance_actions(gid, text, pulse=True):
    a = [{"type": "Glance", "id": gid, "parallel": True, "requires_tags": ["PoiGlance"]}]
    if pulse:
        a.append({"type": "CallHook", "id": "ScanPulse", "target_tag": "Pawn", "requires_tags": ["ScanPulse"]})
        a.append({"type": "PlaySfx", "id": PING, "requires_tags": ["ScanPulse"]})
    a.append({"type": "ShowCaption", "target_tag": "Hud", "text": text, "duration_s": 3.0, "requires_tags": ["PoiHud"]})
    return a


def hud_beat(bid, road_m, text, notes):
    return road_beat(bid, road_m, [{"type": "ShowCaption", "target_tag": "Hud", "text": text, "duration_s": 3.5}],
                     ["PoiHud"], notes)


def poi_beats() -> list:
    zones = {z["id"]: z for z in json.loads(TETHER.read_text(encoding="utf-8"))["zones"]}
    spur = {p["id"]: p for p in json.loads(TETHER.read_text(encoding="utf-8"))["paths"]}
    grade = next(s for s in bc._samples() if s["dist_m"] >= 3650)["slope_pct"]
    B = [
        hud_beat("PH_O14_SPUR", 100, f"SPUR · GRANARY HAMLET · {spur['O14']['length_m']} M", "Tether path O14 leaves here (left)."),
        road_beat("P04_AIRSHIP", 700, [{"type": "PlayCinematic", "id": "CIN_P04_AIRSHIP"}], ["PoiCine"],
                  "Airship (-90 deg, 790 m) and observatory (-72 deg, 1.2 km); both in terrain sight 550-710 m only. 250 m after G03 (the one spacing exception).",
                  max_late=3.0),
        hud_beat("PH_O01_SPUR", 725, f"SPUR · ILAAWB POST · {spur['O01']['length_m']} M", "Tether path O01 leaves here (right)."),
        hud_beat("PH_S05_CONVOY", 790, "CARTS · 5 · LEFT LOADED", "The convoy stands on the road; no camera move needed."),
        road_beat("P07_WAITING_WATER", 1060, [{"type": "PlayCinematic", "id": "CIN_P07_WAITING_WATER"}], ["PoiCine"],
                  "The village 160-220 m ahead-right; B05's RADIO_B05_01 still plays at 1,220 inside the village.", max_late=3.0),
        road_beat("P09_GRAVEYARD_SPUR", 1400, glance_actions("GP_O09_GRAVEYARD", f"SPUR · CARAVAN GRAVEYARD · {spur['O09']['length_m']} M"),
                  ["PoiGlance"], "At the O09 junction: the eyes find the rows of carts, inviting the detour.", max_late=4.0),
        road_beat("P08_WINDPUMPS", 1690, glance_actions("GP_O08_PUMPS", "PUMPS · 5 · NO LOAD"), ["PoiGlance"],
                  "The wind-pump ridge (+82 deg, 970 m, +10 deg up); the sails turn (AMBIENT_ANIMATION.md).", max_late=4.0),
        road_beat("P15_WORKS", 2260, [{"type": "PlayCinematic", "id": "CIN_P15_WORKS"}], ["PoiCine"],
                  "The descent into the basin: the Works 360 m ahead-right and below.", max_late=3.0),
        hud_beat("PH_S12_CHECKPOINT", 2330, "CHECKPOINT · UNMANNED", "The carrier drives through the barrier line."),
        hud_beat("PH_O12_RELAY", 2440, "RELAY 01 · SILENT", "The old relay (the first Âlaawb) ahead-right on its hill, 1.3 km."),
        hud_beat("PH_O06_SPUR", 2525, f"SPUR · OLD DAM · {spur['O06']['length_m']} M", "Tether path O06 leaves here (right)."),
        hud_beat("PH_O03_SPUR", 2775, f"SPUR · BROKEN BRIDGE · {spur['O03']['length_m']} M", "Tether path O03 leaves here (right)."),
        road_beat("P17_CISTERN", 2980, [{"type": "PlayCinematic", "id": "CIN_P17_CISTERN"}], ["PoiCine"],
                  "The dry cistern 70-80 m ahead-right, sunk; B10's radio (3,050) follows it.", max_late=3.0),
        hud_beat("PH_O10_SPUR", 3225, f"SPUR · WORKSHOP · {spur['O10']['length_m']} M", "Tether path O10 leaves here (left)."),
        hud_beat("PH_S20_STAIR", 3640, f"GRADE {abs(grade):.0f} % · STEPS", "The Long Stair; B12's knee fault is at 3,600."),
    ]
    Z = [
        zone_beat("O01", zones["O01"], [{"type": "PlayCinematic", "id": "CIN_PO01_LOW_VOICE"}], ["PoiCine"],
                  "The Ilaawb post: the station's name on a dead building."),
        zone_beat("O03", zones["O03"], glance_actions("GZ_O03_BRIDGE", "BRIDGE · SPAN DOWN · RIVER DRY"), ["PoiGlance"], "Broken bridge."),
        zone_beat("O06", zones["O06"], glance_actions("GZ_O06_DAM", "DAM · RESERVOIR 0 %"), ["PoiGlance"], "Old dam."),
        zone_beat("O09", zones["O09"], glance_actions("GZ_O09_CRADLES", "CRADLES · 2 · EMPTY"), ["PoiGlance"],
                  "The caravan graveyard's two carrier cradles."),
        zone_beat("O10", zones["O10"], glance_actions("GZ_O10_STILL", "STILL · COLD"), ["PoiGlance"], "Chemist's workshop."),
        zone_beat("O14", zones["O14"], glance_actions("GZ_O14_DOVECOTE", "DOVECOTE · EMPTY"), ["PoiGlance"], "Granary hamlet."),
    ]
    return B + Z


def glance_defs() -> tuple[dict, dict]:
    gl, targets = {}, {}
    for gid, (site, group, key, rise, ease, hold) in GLANCES.items():
        tag = glance_tag(gid)
        gl[gid] = {"beat": ("PZ_" if gid.startswith("GZ_") else "P") + gid.split("_")[1], "target_tag": tag,
                   "ease_in_s": ease, "hold_s": hold, "lock_move": False, "tier": "poi"}
        targets[tag] = [round(v) for v in bc.site_point(site, group, key=key, rise=rise)]
    gl["GP_O09_GRAVEYARD"]["beat"] = "P09_GRAVEYARD_SPUR"
    gl["GP_O08_PUMPS"]["beat"] = "P08_WINDPUMPS"
    return gl, targets


def is_poi_id(i: str) -> bool:
    return i.startswith(POI_PREFIXES)


def build(story: dict, glance_targets: dict) -> tuple[dict, dict]:
    story = json.loads(json.dumps(story))
    old_poi = {k: v for k, v in story["cinematics"].items() if is_poi_id(k)}
    story["cinematics"] = {k: v for k, v in story["cinematics"].items() if not is_poi_id(k)}
    new_poi = poi_cinematics(story)
    # ShowHudQuery cues belong to Tools/GameFlow/gen_first_light_road.py (the ?-column queries Q04, Q10, Q10A):
    # carry them over so the two generators can run in either order.
    for cid, c in new_poi.items():
        ids = {x.get("id") for x in c["cues"]}
        kept = [x for x in old_poi.get(cid, {}).get("cues", []) if x.get("type") == "ShowHudQuery" and x.get("id") not in ids]
        c["cues"] = sorted(c["cues"] + kept, key=lambda x: x.get("at_s", 0.0))
    story["cinematics"].update(new_poi)
    gl, targets = glance_defs()
    story["glances"] = {k: v for k, v in story["glances"].items() if not is_poi_id(k)}
    story["glances"].update(gl)
    story["optional_beats"] = [b for b in story["optional_beats"] if not is_poi_id(b["id"])] + poi_beats()
    b06 = next(b for b in story["beats"] if b["id"] == "B06_ROAD_AHEAD")
    b06["actions"] = [
        {"type": "PlayCinematic", "id": "CIN_06_ROAD_AHEAD", "excludes_tags": ["PoiCine"],
         "note": "CV_ROUTE_01 and the crest gust are cued inside. Final state: Checkpoint CP1_CREST."},
        {"type": "PlayCinematic", "id": "CIN_06F_CREST_FORT", "requires_tags": ["PoiCine"],
         "note": "POI_CINEMATICS.md: CIN_06 with the Crest Fortress prelude (+4 s); same cues +4 s, same final state."},
    ]
    gt = {k: v for k, v in glance_targets.items() if not k.startswith("Saskarta.Glance.Poi")}
    gt.update(targets)
    return story, gt


def dump(d) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False) + "\n"


def glance_py(text: str, targets: dict) -> str:
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("TARGETS = "):
            lines[i] = "TARGETS = " + json.dumps(targets)
    return "\n".join(lines)


def main() -> int:
    story = json.loads(STORY.read_text(encoding="utf-8"))
    gt = json.loads(GLANCE_JSON.read_text(encoding="utf-8"))
    new_story, new_gt = build(story, gt)
    outs = {STORY: dump(new_story), GLANCE_JSON: json.dumps(new_gt, indent=1) + "\n",
            GLANCE_PY: glance_py(GLANCE_PY.read_text(encoding="utf-8"), new_gt)}
    if "--check" in sys.argv:
        stale = [p.name for p, t in outs.items() if p.read_text(encoding="utf-8") != t]
        print("stale:", stale if stale else "none")
        return 1 if stale else 0
    for p, t in outs.items():
        p.write_text(t, encoding="utf-8", newline="\n")
    print("wrote", ", ".join(p.name for p in outs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
