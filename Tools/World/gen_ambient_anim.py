"""Ambient motion for the placed set dressing (task CINEPOI): which placed actor moves, how, and what it costs.

    python Tools/World/gen_ambient_anim.py           # writes Tools/World/ambient_anim.json
    python Tools/World/gen_ambient_anim.py --check   # exit 1 if the file is stale

Design: docs/world/AMBIENT_ANIMATION.md. Input: Tools/World/setdress_sites.json (placements with id, key, group,
folder), except S17, which uses its installed V2 water-stone group record. Each RULE matches placements by asset
key (and optionally group) and assigns one METHOD. Every method
is GPU-side (a WPO mode of the new material function MF_Saskarta_PropMotion reading MPC_Saskarta_Wind, a
translucent card, or a pixel-shader glint) except `rotating_component` (engine URotatingMovementComponent with
bUpdateOnlyIfRendered). No Niagara, no skeletal meshes, no Blueprint Tick.

Distance: every WPO item sets the component's World Position Offset Disable Distance (default 15,000 cm) and
Shadow Cache Invalidation Behavior = Static (the motion never re-renders virtual shadow map pages); every card
sets Max Draw Distance (default 15,000 cm). The three far-only landmarks carry their own distance (they are
only ever seen from 800 m and more) and say so in `distance_note`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITES = HERE / "setdress_sites.json"
S17_V2 = HERE / "setdress_v2_groups" / "water_stone_features.json"
OUT = HERE / "ambient_anim.json"

NEAR_CM = 15000          # 150 m: WPO disable distance and card max draw distance
MF = "/Game/SaskartaGaea/Materials/Motion/MF_Saskarta_PropMotion"
MASTER = "/Game/SaskartaGaea/Materials/Motion/M_Saskarta_PropMotion"
CARD_MAT = "/Game/SaskartaGaea/Materials/Motion/M_Saskarta_DustWisp"
CARD_MESH = "/Engine/BasicShapes/Plane"

# Method costs, measured or bounded from comparable work in this project (FOLIAGE.md: the SaskartaWind WPO node
# adds +27..+29 vertex-shader instructions; pixel shader unchanged). gpu_us is per item on screen at 1440p on the
# RTX 5070 when the item is inside its distance, rounded up; 0 outside it.
METHODS = {
    "wpo_cloth": {"mode": "Cloth", "gpu_us": 3, "vs_instr": 35, "what": "normal-direction ripple, weighted by distance from the pinned edge, phase from world position + GustPhase"},
    "wpo_pivot_sway": {"mode": "Sway", "gpu_us": 2, "vs_instr": 30, "what": "rigid rotation about the mesh's top edge (object bounds), axis perpendicular to WindDirection"},
    "wpo_wheel_creak": {"mode": "Wheel", "gpu_us": 2, "vs_instr": 30, "what": "rigid rotation of a few degrees about the axle through the bounds centre, driven by the gust (snaps back slowly)"},
    "wpo_rotor": {"mode": "Rotor", "gpu_us": 3, "vs_instr": 40, "what": "continuous rotation of the vertices inside the rotor sphere (local-space mask) about the hub axis; rate = base x WindStrength x gust"},
    "wpo_mast_bend": {"mode": "Bend", "gpu_us": 2, "vs_instr": 25, "what": "cantilever bend, offset = amp x z01^2 along WindDirection"},
    "cable_new": {"mode": "Cable", "gpu_us": 2, "vs_instr": 25, "what": "NEW thin guy-wire meshes (a 16-ring tube, imported from an offline OBJ); catenary sway = amp x sin(pi x t) along the wire"},
    "card_dust_wisp": {"mode": "Card", "gpu_us": 20, "vs_instr": 0, "what": "NEW 2 x 4 m translucent unlit card (Plane) at the stack top: panning noise, depth fade, alpha gated by gust; ash/dust lifted off the stack, never smoke"},
    "card_dust_sift": {"mode": "Card", "gpu_us": 12, "vs_instr": 0, "what": "NEW 1 x 3 m vertical card under a broken edge: a thin fall of grit that appears only in gusts (alpha = saturate(gust - 0.6) x 3)"},
    "ps_glint": {"mode": "Glint", "gpu_us": 1, "vs_instr": 0, "what": "pixel-shader emissive glint when the sun-mirror-camera angle lines up (dot of reflected sun and view > 0.995), plus a slow 0.3 deg WPO wobble"},
    "rotating_component": {"mode": "RotatingMovement", "gpu_us": 0, "vs_instr": 0, "what": "URotatingMovementComponent, bUpdateOnlyIfRendered true; the actor must be Movable"},
}

# key regex, group regex (None = any), method, params, notes. First match wins. Indoors and fallen items are
# excluded by group (interior, back_room, v8).
RULES = [
    (r"^TRIPO_Flag$", None, "wpo_cloth", {"pin": "pole", "amp_cm": 25, "freq_hz": 1.3}, "banner/flag: the long torn cloth snaps from the pole side"),
    (r"^MV_Cloth_0[12]$", r"^(?!interior|back_room).*", "wpo_cloth", {"pin": "top", "amp_cm": 12, "freq_hz": 1.0}, "hanging cloth strip or luggage cover"),
    (r"^(AB_Tent_A|AB_Damaged_Tent_A)$", r"^canvas$", "wpo_cloth", {"pin": "edges", "amp_cm": 80, "freq_hz": 0.25},
     "the airship's torn envelope canvas: a slow billow (far landmark, amplitude sized to read at 800 m in CIN_P04's 15 deg zoom)"),
    (r"^(AB_Tent_A|AB_Damaged_Tent_A|AB_Tent_B_Cloth_low|AB_Tent_C_Cloth|AB_Tent_Cloth_B_frame|MV_Annex_Tarp_01|MV_cart_tarp)$", None,
     "wpo_cloth", {"pin": "edges", "amp_cm": 6, "freq_hz": 0.8}, "stall/tent/tarp roof: a ripple between the poles, torn flaps lift in gusts"),
    (r"^B01_sign0[23]$", None, "wpo_pivot_sway", {"amp_deg": 0.8, "freq_hz": 2.2}, "loose board on its post: a small rattle about the top nail (set amp 0 if the board is fixed flush)"),
    (r"^PH_lantern$", r"^lantern$", "wpo_pivot_sway", {"amp_deg": 5.0, "freq_hz": 0.6, "lit": False},
     "hung lantern swings; UNLIT (REACT_POI_WAYSTATION_02: 'the fire at the waystation's gone out'); see the lit option in the doc"),
    (r"^MV_Rope_01$", r"^lantern$", "wpo_pivot_sway", {"amp_deg": 5.0, "freq_hz": 0.6}, "the lantern's rope: same pivot and phase as the lantern"),
    (r"^(B01_wheel01)$", r"^mill$", "wpo_wheel_creak", {"amp_deg": 3.0, "axis": "local_y", "rise_s": 0.8, "return_s": 3.0},
     "the dead water wheel: creaks a few degrees forward in a gust and settles back"),
    (r"^T2_water_wheel$", None, "wpo_wheel_creak", {"amp_deg": 4.0, "axis": "local_y", "rise_s": 0.8, "return_s": 3.0}, "the dam's dry mill wheel"),
    (r"^MV_Woodmill_Wheel$", None, "wpo_wheel_creak", {"amp_deg": 2.0, "axis": "local_y", "rise_s": 0.6, "return_s": 2.0}, "the Works' pulley wheel rocks on its rope"),
    (r"^T2_wind_pump$", None, "wpo_rotor", {"rev_s": 0.35, "rotor_centre_local_cm": [0, 0, 1050], "rotor_radius_cm": 220, "tail_yaw_deg": 5.0, "speed_jitter": 0.15},
     "wind-pump sails turning, lifting nothing (verify the hub height/axis on the Tripo mesh; set rotor_centre_local_cm)"),
    (r"^T2_relay_tower$", r"^tower$", "wpo_mast_bend", {"amp_cm": 18, "freq_hz": 0.4}, "the old relay (26 m) leans a hand's width in gusts"),
    (r"^T2_signal_mirror$", None, "ps_glint", {"threshold": 0.995, "wobble_deg": 0.3}, "the signal mirror still catches the low sun"),
    (r"^(AB_Pillar_low|MV_Chimney|AB_Pillar_A_01)$", r"^(hall|house|workshop)$", "card_dust_wisp", {"cards": 1, "size_m": [2, 4], "rise_cm_s": 40},
     "chimney/stack top: dust and old ash lifted by the wind (not smoke: nobody keeps a fire)"),
    (r"^(AB_BrokenStructer|AB_Damaged_Minarate|B01_ruin01)$", None, "card_dust_sift", {"cards": 1, "size_m": [1, 3]},
     "grit sifting from a broken edge in gusts"),
]

# Extra items that are not a placement: new meshes to add next to a placed actor.
EXTRAS = [
    {"site": "O12_OldRelay", "group": "tower", "anchor_key": "T2_relay_tower", "method": "cable_new",
     "params": {"wires": 4, "amp_cm": 30, "freq_hz": 0.5, "anchor_radius_m": 9}, "note": "four guy wires from the 26 m tower to ground anchors"},
    {"site": "O01_LowVoicePost", "group": "mast", "anchor_key": "T2_relay_tower", "method": "cable_new",
     "params": {"wires": 3, "amp_cm": 12, "freq_hz": 0.7, "anchor_radius_m": 4}, "note": "the post's small mast: three stays to the fence posts"},
    {"site": "S20_LongStair", "group": "rockfall_3605", "anchor_key": None, "method": "card_dust_sift",
     "params": {"cards": 1, "size_m": [1, 3]}, "note": "a trickle of grit down the rockfall above the first switchback"},
    {"site": "S20_LongStair", "group": "rockfall_3695", "anchor_key": None, "method": "card_dust_sift",
     "params": {"cards": 1, "size_m": [1, 3]}, "note": "the same above the second"},
]

FAR = {  # site -> (distance cm, why)
    "O08_WindPumps": (260000, "seen only from the road at 940-1,700 m; 5 meshes"),
    "O12_OldRelay": (250000, "seen only from 620-2,500 m; 1 tower + 4 wires"),
    "O04_Airship": (230000, "seen only from 790-2,300 m; 2 canvas meshes"),
    "O11_MirrorHill": (250000, "pixel-shader glint; seen from 1,400-2,500 m"),
}
MAX_SIFT_PER_SITE = 2


def near_enough(s: dict) -> bool:
    """Motion that is culled at 150 m only matters where the carrier (on the road, a tether path or in a zone)
    comes within 150 m. Far-only landmarks are listed in FAR with their own distance."""
    if s["id"] in FAR:
        return True
    poi = s.get("poi")
    if poi:
        return bool(poi.get("reachable"))
    return abs(s.get("lateral_m") or 0) <= 150.0 - min(s.get("radius_m", 0), 60)


def build() -> dict:
    data = json.loads(SITES.read_text(encoding="utf-8"))
    s17 = next(site for site in json.loads(S17_V2.read_text(encoding="utf-8"))["sites"]
               if site["id"] == "S17_DryCistern")
    rules = [(re.compile(k), re.compile(g) if g else None, m, p, n) for k, g, m, p, n in RULES]
    sites_out = []
    totals = {m: 0 for m in METHODS}
    for s in data["sites"]:
        if s["id"] == "S17_DryCistern":
            s = s17
        if not near_enough(s):
            continue
        items, sift = [], 0
        for pl in s["placements"]:
            if pl["key"] == "T2_relay_tower" and pl["size_m"][2] < max(pl["size_m"][:2]):
                continue                                   # the fallen tower section lies still
            for kre, gre, method, params, note in rules:
                if not kre.match(pl["key"]) or (gre and not gre.match(pl["group"])):
                    continue
                if method == "card_dust_sift":
                    if sift >= MAX_SIFT_PER_SITE:
                        break
                    sift += 1
                far = FAR.get(s["id"])
                dist = far[0] if far else NEAR_CM
                it = {"placement": pl["id"], "key": pl["key"], "asset": pl["asset"], "group": pl["group"], "folder": pl["folder"],
                      "method": method, "params": params, "note": note}
                if method.startswith("wpo_") or method in ("ps_glint",):
                    it["wpo_disable_distance_cm"] = dist
                    it["shadow_cache_invalidation"] = "Static"
                    it["material"] = {"parent": MASTER, "function": MF, "mode": METHODS[method]["mode"]}
                elif method.startswith("card_"):
                    it["card"] = {"mesh": CARD_MESH, "material": CARD_MAT, "max_draw_distance_cm": dist,
                                  "place": "top of the anchor's bounds" if method == "card_dust_wisp" else "under the anchor's highest broken edge"}
                if far:
                    it["distance_note"] = far[1]
                items.append(it)
                totals[method] += 1
                break
        for ex in EXTRAS:
            if ex["site"] != s["id"]:
                continue
            anchor = next((p for p in s["placements"] if p["group"] == ex["group"] and (ex["anchor_key"] is None or p["key"] == ex["anchor_key"])), None)
            far = FAR.get(s["id"])
            dist = far[0] if far else NEAR_CM
            it = {"placement": None, "anchor": anchor["id"] if anchor else None, "group": ex["group"],
                  "folder": anchor["folder"] if anchor else None, "method": ex["method"], "params": ex["params"], "note": ex["note"],
                  "new": True}
            if ex["method"] == "cable_new":
                it["wpo_disable_distance_cm"] = dist
                it["shadow_cache_invalidation"] = "Static"
                it["material"] = {"parent": MASTER, "function": MF, "mode": "Cable"}
                n = ex["params"]["wires"]
            else:
                it["card"] = {"mesh": CARD_MESH, "material": CARD_MAT, "max_draw_distance_cm": dist, "place": "on the rockfall face"}
                n = 1
            if far:
                it["distance_note"] = far[1]
            items.append(it)
            totals[ex["method"]] += n
        if not items:
            continue
        us = sum(METHODS[i["method"]]["gpu_us"] * (i["params"].get("wires", 1) if i["method"] == "cable_new" else 1) for i in items)
        sites_out.append({"site": s["id"], "name": s["name"], "road_m": s["road_m"], "layer": s.get("layer", "road"),
                          "items": items, "count": len(items), "gpu_us_all_on_screen": us})
    worst = max(sites_out, key=lambda x: x["gpu_us_all_on_screen"])
    return {
        "generated_by": "Tools/World/gen_ambient_anim.py",
        "doc": "docs/world/AMBIENT_ANIMATION.md",
        "wind": {"mpc": "/Game/SaskartaGaea/Foliage/MPC_Saskarta_Wind", "params": ["WindDirection", "WindStrength", "GustPhase"],
                 "driver": "BP_Saskarta_WindDriver (existing, 0.1 s timer)"},
        "defaults": {"wpo_disable_distance_cm": NEAR_CM, "card_max_draw_distance_cm": NEAR_CM,
                     "shadow_cache_invalidation": "Static", "nanite": "keep; WPO meshes need 'Evaluate World Position Offset' on (programmable raster)"},
        "methods": METHODS,
        "totals": {"entries": sum(len(x["items"]) for x in sites_out), "objects": sum(totals.values()),
                   "objects_by_method": {k: v for k, v in totals.items() if v}},
        "budget": {"frame_ms_at_60fps": 16.67, "headroom_pct": 15, "ambient_cap_ms": 0.25,
                   "worst_site": worst["site"], "worst_site_ms_all_on_screen": round(worst["gpu_us_all_on_screen"] / 1000.0, 3)},
        "sites": sites_out,
    }


def dump(d) -> str:
    return json.dumps(d, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    text = dump(build())
    if "--check" in sys.argv:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != text
        print("stale" if stale else "up to date")
        return 1 if stale else 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    d = json.loads(text)
    print("wrote", OUT.name, d["totals"], d["budget"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
