"""First Light road data (gen_first_light_road.py, storyline-first-light.md 4.2-4.4) and the lid / placement tools.

    python -m pytest -q Tools/GameFlow/tests/test_first_light_road.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools" / "GameFlow"))
sys.path.insert(0, str(ROOT / "Tools" / "World"))

import gen_first_light_road as gen  # noqa: E402

EVENTS = json.loads((ROOT / "docs/story/story-events.json").read_text(encoding="utf-8"))


def all_queries():
    for b in EVENTS["hud_beats"]:
        for a in b["actions"]:
            if a["type"] == "ShowHudQuery":
                yield b["distance_m"], a
    for c in EVENTS["cinematics"].values():
        for a in c.get("cues", []):
            if a["type"] == "ShowHudQuery":
                yield None, a


def test_generator_is_idempotent():
    assert gen.main(check=True) == 0


def test_no_question_column_and_no_question_items():
    # ROUTE_BOARD_V3.md: the ?-column is cut; the ?-items (APRICOT, LAMP, HERON, NAME ON BAG, FIRE, KETTLE, VALLEY,
    # SWALLOWS, the doubled IY-LA'HAR-DZEHIY) go and the site result lines stay. CIN_01's canon scan keeps MOUNTAIN?.
    for m, a in all_queries():
        assert "column" not in a and "result" not in a, a
        if m is not None:
            assert "?" not in a["text"], a
    texts = {a["text"] for m, a in all_queries() if m is not None}
    assert {"ROOF . NO FRUIT", "HOOK . NO LAMP", "POST 2 . NO WALL", "HORN 1 . IN SCREE", "LABEL . ILLEGIBLE"} <= texts


def test_crt_lines_have_no_forbidden_glyphs():
    for _m, a in all_queries():
        assert not any(ch in a["text"] for ch in "×—−·°"), a


def test_road_query_ids_that_remain():
    ids = {a["id"].split("_")[0].rstrip("A") for _m, a in all_queries()}
    assert {f"Q{n:02d}" for n in range(1, 21)} - ids == {"Q04", "Q07", "Q18"}


def test_hud_beats_are_road_ordered_and_ue_falls():
    beats = EVENTS["hud_beats"]
    assert [b["distance_m"] for b in beats] == sorted(b["distance_m"] for b in beats)
    ue = [b["ue_distance_from_p0_m"] for b in beats]
    assert all(a > b for a, b in zip(ue, ue[1:]))


def test_wrecks_and_voice():
    ids = {b["id"] for b in EVENTS["hud_beats"]}
    assert {"WR01_CARRIER_01", "WR03_CARRIER_03", "WR04_CARRIER_04", "WR05_CARRIER_05", "WR06_CARRIER_06"} <= ids
    wr01 = next(b for b in EVENTS["hud_beats"] if b["id"] == "WR01_CARRIER_01")
    assert wr01["actions"][1] == {"type": "PlayCarrierLine", "id": "CV_WRECK_01"}
    wr06 = next(b for b in EVENTS["hud_beats"] if b["id"] == "WR06_CARRIER_06")
    assert all(a["type"] == "ShowHudQuery" for a in wr06["actions"])  # text only
    cues = EVENTS["cinematics"]["CIN_06_ROAD_AHEAD"]["cues"]
    assert any(c.get("id") == "CV_WRECK_02" for c in cues)
    assert max(c["at_s"] for c in cues) < EVENTS["cinematics"]["CIN_06_ROAD_AHEAD"]["duration_s"]
    voice = {x["id"]: x["text"] for x in json.loads((ROOT / "docs/story/carrier-voice-lines.json").read_text(encoding="utf-8"))["lines"]}
    assert voice["CV_WRECK_01"] == "Carrier one. No response."
    assert voice["CV_BOOT_02"] == "Handover. Carrier seven. Units one to six: lost."


def test_status_lines_fade_at_the_collapse():
    b18 = next(b for b in EVENTS["beats"] if b["id"] == "B18_COLLAPSE")
    assert b18["actions"][0]["target_tag"] == "HudStatus" and b18["actions"][0]["value"] == 0
    assert not any(a.get("id") == "HUD_COLUMN_FADE" for a in b18["actions"])


def test_boot_strings_are_terminal_ascii():
    spec = json.loads((ROOT / "Tools/GameFlow/specs/BPC_CarrierVision.json").read_text(encoding="utf-8"))
    v = {x["name"]: x.get("default") for x in spec["variables"]}
    assert v["Boot2Line"] == "HANDOVER - CARRIER 07 / UNITS 01-06 LOST"
    assert v["BootSubHeader"].endswith("1946 AA")
    assert all(ord(ch) < 128 for ch in v["Boot2Line"] + v["BootSubHeader"])


def test_marks_positions_and_scripts_validate():
    import place_first_light_marks as pfl
    doc = pfl.load()
    ids = [i["id"] for i in doc["items"]]
    assert ids[:6] == [f"WRECK_{n:02d}" for n in range(1, 7)] and {"G0", "G1", "G2", "G3", "G4", "DEPOT_MOUTH"} <= set(ids)
    silt = [i["silt"] for i in doc["items"] if i["kind"] == "wreck"]
    assert silt == sorted(silt, reverse=True) and silt[-1] == 0.0  # 01 most buried, 06 clean
    for step in ("place", "status", "save", "clear"):
        for s in pfl.scripts(step, doc, doc["items"]):
            assert "try" not in s
    assert len(pfl.scripts("place", doc, doc["items"])) == -(-len(doc["items"]) // pfl.PER_CALL)


def test_caption_widget_has_the_column_and_date():
    tree = json.loads((ROOT / "Tools/GameFlow/specs/WBP_Saskarta_Caption.tree.json").read_text(encoding="utf-8"))
    names = {n["name"] for n in tree["tree"]}
    assert {"HudQuestions", "HudDate"} <= names
    graph = (ROOT / "Tools/GameFlow/specs/WBP_Saskarta_Caption.graph.json").read_text(encoding="utf-8")
    assert '"HudColumn"' in graph


def test_lid_generator_runs():
    r = subprocess.run([sys.executable, str(ROOT / "Tools/Story/gen_lid_notes.py")], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert (ROOT / "Saved/Story/LidNotes/T_FL_LidNotes_PLACEHOLDER.png").exists()
