"""gen_first_light_road: First Light along the road (docs/story/drafts/storyline-first-light.md section 4) as data.

    python Tools/GameFlow/gen_first_light_road.py          # write everything below (idempotent)
    python Tools/GameFlow/gen_first_light_road.py --check  # exit 1 if a file would change

Writes:
- docs/story/story-events.json
    hud_beats: the Q road result lines (no ? and no ?-column since ROUTE_BOARD_V3.md),
      and the wreck lines 01-06 (ShowHudQuery on the runner's HUD lane,
      USaskartaEventRunner / SaskartaHudQueryLogic.h); WR01 also plays CV_WRECK_01;
    cinematic cues: CIN_01 MOUNTAIN? / NO MATCH / MOUNTAIN √ (the canon scan), CIN_P17 STEP 4 √ (Q10A),
      CIN_06 wreck 02 + CV_WRECK_02, CIN_15 LIGHT √ ON (Q19) and SUN -3 . NOT YET (Q20);
    B18: the status lines (NAMES / HEARD, target HudStatus) fade first thing in the collapse.
- docs/story/carrier-voice-lines.json: CV_BOOT_02 (new handover text), CV_WRECK_01, CV_WRECK_02.
- Tools/GameFlow/specs/BPC_CarrierVision*.json: Boot2Line HANDOVER - CARRIER 07 / UNITS 01-06 LOST,
  BootSubHeader with the date 1946 AA (the boot strings stay uppercase ASCII: check_terminal_glyphs.py).
- Tools/World/first_light_marks.json: wrecks 01-06, the depot mouth and grates G0-G4 with world positions from
  docs/story/road-profile.json (placed later by Tools/World/place_first_light_marks.py).
"""
from __future__ import annotations

import bisect
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVENTS = ROOT / "docs" / "story" / "story-events.json"
VOICE = ROOT / "docs" / "story" / "carrier-voice-lines.json"
PROFILE = ROOT / "docs" / "story" / "road-profile.json"
SPECS = ROOT / "Tools" / "GameFlow" / "specs"
MARKS = ROOT / "Tools" / "World" / "first_light_marks.json"

DATE = "1946 AA"
BOOT2 = "HANDOVER - CARRIER 07 / UNITS 01-06 LOST"
SUBHEADER = "(C) HIGHLAND ROUTE AUTHORITY  " + DATE
SOURCE = "docs/story/drafts/storyline-first-light.md 4.2"


def q(qid, text, result="", dur=0.0, res_s=0.0, target="", at=None):
    a = {"type": "ShowHudQuery", "id": qid, "text": text}
    if result:
        a["result"] = result
    if dur:
        a["duration_s"] = dur
    if res_s:
        a["value"] = res_s
    if target:
        a["target_tag"] = target
    if at is not None:
        a = {"at_s": at, **a}
    return a


def wreck(n, dur=3.0, at=None):
    return q(f"WRECK_{n:02d}", f"CARRIER {n:02d} . NO RESPONSE", dur=dur, target="HudPriority", at=at)


# Road lines: (beat id, road m, [actions], note). ROUTE_BOARD_V3.md: no ? anywhere and no ?-column; a site keeps
# only its result line (the board's own arrival text names the place or its number). CRT glyphs: letters, digits,
# | . ^ √ - ' % [ ] and ' . ' between fields.
ROAD = [
    ("Q01_STONE", 490, [q("Q01", "STONE √ INSCRIBED", dur=3.0)], "V2 promise stones (B03), after the G03 glance"),
    ("Q02_APRICOT", 600, [q("Q02", "ROOF . NO FRUIT", dur=3.0)], "the Âsekîne house by the second bend (S-01)"),
    ("Q03_LAMP", 830, [q("Q03", "HOOK . NO LAMP", dur=3.0)], "V3 convoy, the last cart (S-02); dropped with V3 if the stretch set is cut"),
    ("Q05_GATE", 1240, [q("Q05", "POST 2 . NO WALL", dur=3.0)], "V4, the Waiting Water's gate (S-04), under RADIO_B05_01"),
    ("Q06_GOAT", 1760, [q("Q06", "HORN 1 . IN SCREE", dur=3.0)], "ridge climb (S-05), scree left, 52 m after GP_O08_PUMPS"),
    ("Q08_HERON_POOLS", 2545, [q("Q08A", "6-8 √", dur=1.5), q("Q08", "PLATE . 6-8 √", dur=3.0)],
     "V5 plate 6-8 on the arch (6-8), after B08's lines; waits for PH_O06_SPUR"),
    ("Q09_BAG", 2600, [q("Q09A", "BENCH √", dur=1.5), q("Q09", "LABEL . ILLEGIBLE", dur=3.0)], "V5 platform (S-07), after G09"),
    ("Q11_ECHO", 3090, [q("Q11", "ECHO √ 2", dur=3.0)], "Tarsan (V6 or S17); drop with Q10 if neither is built"),
    ("Q12_WAYSTATION", 3405, [q("Q12", "PIT . COLD", dur=2.5), q("Q13", "RUST RING . HEARTHSTONE", dur=3.0),
                              q("Q14", "FLAG √", dur=2.0)],
     "V7 after CIN_11's hand-back: the lane holds them under the cinematic, then runs them in order (done by ~3,460)"),
    ("Q15_BEND_1", 3680, [q("Q15_1", "BEND 1", dur=2.5)], "the Long Stair count; bend marks evenly spaced to 4,015, align to the hairpins live"),
    ("Q15_BEND_2", 3765, [q("Q15_2", "BEND 2", dur=2.5)], ""),
    ("Q15_BEND_3", 3845, [q("Q15_3", "BEND 3", dur=2.5)], ""),
    ("Q15_BEND_4", 3930, [q("Q15_4", "BEND 4", dur=2.5)], "wreck 04 at 3,900 goes first if both are up"),
    ("Q15_BEND_5", 4010, [q("Q15_5", "BEND 5", dur=2.5)], ""),
    ("Q16_WALL", 4100, [q("Q16A", "WALL √ LEFT", dur=1.5), q("Q16", "ACOUSTIC . WIND", dur=2.5)], "the crest wall"),
    ("Q17_GOAT", 4300, [q("Q17", "RANGE 640 M . UNCONFIRMED", dur=3.0)], "a goat on a far ridge; sightline check live"),
]

# Wrecks: (unit, road m, lateral m (+ right of travel), silt 0..1, where, voice line)
WRECKS = [
    (1, 1000, -6.0, 0.55, "valley floor, 60 m before the Waiting Water", "CV_WRECK_01"),
    (2, 2000, 5.0, 0.45, "ridge crest, in CIN_06's frame", "CV_WRECK_02"),
    (3, 3550, -4.0, 0.3, "foot of the 79 % pitch", ""),
    (4, 3900, 5.0, 0.2, "between the hairpins", ""),
    (5, 4400, -4.0, 0.1, "top of the climb, before B14", ""),
    (6, 4650, 3.5, 0.0, "the shoulder, during the failing steps (text only)", ""),
]

GRATES = [
    ("G0", 0, -3.0, "at the depot mouth, on the tow track"),
    ("G1", 150, 4.5, "verge, right"),
    ("G2", 1220, -3.5, "the dry channel bed (align to SM_B01_channel01 live)"),
    ("G3", 2540, 0.0, "under the 6-8 arch, stamped with a number"),
    ("G4", 3050, 6.0, "Tarsan floor over the city (S17); the verge if no cistern is built"),
]

CINE_CUES = {
    # the canon scan teaches the query format (draft 4.1, B01): shot 3, the rejected ridge, shot 4
    "CIN_01_DIRECTIVE": [q("CIN01_Q1", "MOUNTAIN?", dur=2.4, at=9.6), q("CIN01_Q2", "NO MATCH", dur=2.4, at=12.3),
                         q("CIN01_Q3", "MOUNTAIN √", dur=1.6, at=16.9)],
    # ROUTE_BOARD_V3.md cut the ?-column: WATER (an English place name) and FULL go; STEP 4 stays
    "CIN_P07_WAITING_WATER": [],
    "CIN_P17_CISTERN": [q("Q10A", "STEP 4 √", dur=2.0, at=7.0)],
    "CIN_06_ROAD_AHEAD": [wreck(2, dur=2.5, at=13.4), {"at_s": 13.6, "type": "PlayCarrierLine", "id": "CV_WRECK_02"}],
    "CIN_15_IN_RANGE": [q("Q19", "LIGHT √ ON", dur=2.0, at=3.0),
                        q("Q20", "SUN -3 . NOT YET", dur=2.0, at=8.0)],
}
CUE_IDS = {a["id"] for cues in CINE_CUES.values() for a in cues} | {"Q04", "Q10"}  # cut in V3: removed from their cues


# ----------------------------------------------------------------------------- road math
class Road:
    def __init__(self):
        s = json.loads(PROFILE.read_text(encoding="utf-8"))["samples"]
        self.s = s
        self.d = [x["dist_m"] for x in s]

    def at(self, road_m):
        i = max(1, min(len(self.d) - 1, bisect.bisect_left(self.d, road_m)))
        a, b = self.s[i - 1], self.s[i]
        t = (road_m - a["dist_m"]) / max(b["dist_m"] - a["dist_m"], 1e-6)
        t = max(0.0, min(1.0, t))
        lerp = lambda k: a[k] + (b[k] - a[k]) * t  # noqa: E731
        dyaw = (b["heading_ue_yaw"] - a["heading_ue_yaw"] + 180) % 360 - 180
        return {"ue_m": round(lerp("ue_spline_distance_m"), 1), "x_cm": lerp("x_cm"), "y_cm": lerp("y_cm"),
                "z_m": lerp("terrain_z_m"), "yaw": a["heading_ue_yaw"] + dyaw * t}

    def world(self, road_m, lateral_m):
        p = self.at(road_m)
        yaw = math.radians(p["yaw"])
        # UE: forward (cos, sin); right of travel = (-sin, cos)
        x = p["x_cm"] - math.sin(yaw) * lateral_m * 100.0
        y = p["y_cm"] + math.cos(yaw) * lateral_m * 100.0
        return [round(x, 1), round(y, 1), round(p["z_m"] * 100.0, 1)], round(p["yaw"], 1), p["ue_m"]


# ----------------------------------------------------------------------------- builders
def hud_beats(road):
    out = []
    for bid, m, actions, note in ROAD:
        out.append({"id": bid, "distance_m": m, "ue_distance_from_p0_m": road.at(m)["ue_m"], "trigger": "pass",
                    "one_shot": True, "actions": actions, "notes": (note + "; " if note else "") + SOURCE})
    for n, m, _lat, _silt, where, line in WRECKS:
        if n == 2:
            continue  # inside CIN_06 (cues)
        acts = [wreck(n)]
        beat = {"id": f"WR{n:02d}_CARRIER_{n:02d}", "distance_m": m, "ue_distance_from_p0_m": road.at(m)["ue_m"],
                "trigger": "pass", "one_shot": True, "actions": acts,
                "notes": where + "; storyline-first-light.md 4.3"}
        if line:
            acts[0]["parallel"] = True
            acts.append({"type": "PlayCarrierLine", "id": line})
            beat["max_lateness_s"] = 6
            beat["notes"] += "; a carrier line: ducks the show -6 dB, never cuts it"
        out.append(beat)
    out.sort(key=lambda b: b["distance_m"])
    return out


def patch_events(d, road):
    d["hud_beats"] = hud_beats(road)
    for cid, cues in CINE_CUES.items():
        c = d["cinematics"][cid]
        keep = [x for x in c.get("cues", []) if x.get("id") not in CUE_IDS]
        c["cues"] = sorted(keep + cues, key=lambda x: x.get("at_s", 0.0))
    fade = {"type": "ShowHudQuery", "id": "HUD_STATUS_FADE", "target_tag": "HudStatus", "value": 0, "parallel": True}
    b18 = next(b for b in d["beats"] if b["id"] == "B18_COLLAPSE")
    b18["actions"] = [fade] + [a for a in b18["actions"] if a.get("id") not in ("HUD_COLUMN_FADE", "HUD_STATUS_FADE")]
    return d


def patch_voice(v):
    lines = v["lines"]
    boot2 = next(x for x in lines if x["id"] == "CV_BOOT_02")
    boot2["text"] = "Handover. Carrier seven. Units one to six: lost."
    boot2["when"] = ("First boot, boot-log line 2 (" + BOOT2 + "). B01. Pre-mixed with the other CV_BOOT lines into CV_BOOT "
                     "(0.4 s gaps). Re-record: the text changed 2026-09-29 (storyline-first-light.md 4.6).")
    new = [
        {"id": "CV_WRECK_01", "text": "Carrier one. No response.",
         "when": "Wreck 01 at road 1,000 (WR01_CARRIER_01, hud_beats), with CARRIER 01 . NO RESPONSE on HudLine. Ducks the show, never cuts it; ends before CIN_P07 (1,060).",
         "style": "system", "record": "mvp"},
        {"id": "CV_WRECK_02", "text": "Carrier two. No response.",
         "when": "Wreck 02 at road 2,000, inside CIN_06_ROAD_AHEAD at 13.6 s, after CV_ROUTE_01.",
         "style": "system", "record": "mvp"},
    ]
    ids = {x["id"] for x in new}
    kept = [x for x in lines if x["id"] not in ids]
    at = next(i for i, x in enumerate(kept) if x["id"] == "CV_ROUTE_01") + 1
    v["lines"] = kept[:at] + new + kept[at:]
    return v


def patch_spec(s):
    for var in s.get("variables", []):
        if var.get("name") == "Boot2Line":
            var["default"] = BOOT2
        elif var.get("name") == "BootSubHeader":
            var["default"] = SUBHEADER
    return s


def marks(road):
    items = []
    for n, m, lat, silt, where, line in WRECKS:
        loc, yaw, ue = road.world(m, lat)
        items.append({"id": f"WRECK_{n:02d}", "kind": "wreck", "road_m": m, "ue_m": ue, "lateral_m": lat, "silt": silt,
                      "loc_cm": loc, "yaw": yaw, "sink_cm": round(silt * 60.0, 1), "stencil": f"{n:02d}",
                      "voice": line, "where": where})
    for gid, m, lat, where in GRATES:
        loc, yaw, ue = road.world(m, lat)
        items.append({"id": gid, "kind": "grate", "road_m": m, "ue_m": ue, "lateral_m": lat, "loc_cm": loc, "yaw": yaw,
                      "breath_s": 7.0, "where": where})
    # the depot mouth: behind the capsule, cut into the slope, facing up-road (CIN_01 shot 2 background only)
    loc, yaw, ue = road.world(0, 0)
    back = math.radians(yaw)
    mouth = [round(loc[0] - math.cos(back) * 2500, 1), round(loc[1] - math.sin(back) * 2500, 1), loc[2]]
    items.append({"id": "DEPOT_MOUTH", "kind": "mouth", "road_m": -25, "ue_m": None, "loc_cm": mouth, "yaw": yaw,
                  "bays": 7, "where": "25 m behind the boot point, facing up-road; bays 01-06 empty and silted, 07 fresh"})
    return {
        "generated_by": "Tools/GameFlow/gen_first_light_road.py",
        "design": "docs/story/drafts/storyline-first-light.md 4.3-4.4",
        "level": "/Game/level/Saskarta_WP",
        "conventions": {"loc_cm": "road-profile.json terrain point + lateral offset (right of travel +); z is the terrain, "
                                  "the placer traces down from +20 m", "yaw": "UE yaw of travel (up-road)"},
        "assets": {
            "wreck_mesh": "/Game/SaskartaGaea/Characters/Carrier/SK_Carrier.SK_Carrier",
            "wreck_pose": "/Game/SaskartaGaea/Characters/Carrier/Anims/A_Carrier_Shutdown.A_Carrier_Shutdown",
            "wreck_note": "posed once and frozen (no tick, no anim update); swap for a baked static husk when one exists",
            "grate_frame": "/Game/SaskartaGaea/Environment/Batch01/SM_B01_floor01.SM_B01_floor01",
            "grate_plate": "/Engine/BasicShapes/Plane.Plane",
            "grate_material": "/Game/MedievalVillage/Materials/MI_Metal.MI_Metal",  # was the teal-green MI_SquareGrid_Inst (the author: "green rectangle")
            "dust": None,  # the EasyAtmos grate "breath" read as falling leaves (the author); off until a real dust effect exists
            "mouth_arch": "/Game/SaskartaGaea/Environment/Batch01/SM_B01_arch01.SM_B01_arch01",
            "mouth_wall": "/Game/SaskartaGaea/Environment/Batch01/SM_B01_wall01.SM_B01_wall01",
            "bay_cradle": "/Game/SaskartaGaea/Environment/Tripo02/SM_T2_carrier_cradle.SM_T2_carrier_cradle",
            "tow_track": "/Game/SaskartaGaea/Environment/Batch01/SM_B01_rail01.SM_B01_rail01",
            "stencil_mi": "/Game/SaskartaGaea/Story/FirstLight/MI_FL_Stencil_",
            "dust_bp": "/Game/EasyAtmos/Blueprints/BP_EasyAtmos.BP_EasyAtmos",
        },
        "cull_distance_cm": {"wreck": 12000, "grate": 6000, "dust": 4000, "mouth": 15000},
        "items": items,
    }


def dump(obj, indent):
    return json.dumps(obj, indent=indent, ensure_ascii=False) + "\n"


def main(check=False):
    road = Road()
    changed = []

    def write(path, text):
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old != text:
            changed.append(path.relative_to(ROOT).as_posix())
            if not check:
                path.write_text(text, encoding="utf-8", newline="\n")

    write(EVENTS, dump(patch_events(json.loads(EVENTS.read_text(encoding="utf-8")), road), 2))
    write(VOICE, dump(patch_voice(json.loads(VOICE.read_text(encoding="utf-8"))), 2))
    for name in ("BPC_CarrierVision.json", "BPC_CarrierVision.bootpacing.json", "BPC_CarrierVision.opening_skip.json"):
        p = SPECS / name
        s = json.loads(p.read_text(encoding="utf-8"))
        indent = 2 if p.read_text(encoding="utf-8").startswith("{\n  ") else 1
        write(p, dump(patch_spec(s), indent))
    write(MARKS, dump(marks(road), 1))
    print(("would change: " if check else "wrote: ") + (", ".join(changed) or "nothing"))
    return 1 if (check and changed) else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
