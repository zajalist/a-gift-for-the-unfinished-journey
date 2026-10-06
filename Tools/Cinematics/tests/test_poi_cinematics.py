"""Offline checks for the POI discovery beats (task CINEPOI; docs/story/POI_CINEMATICS.md). No editor.

    python -m pytest Tools/Cinematics/tests -q
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CIN = HERE.parent
REPO = CIN.parents[1]
sys.path.insert(0, str(CIN))
import build_cinematics as bc  # noqa: E402
import gen_poi_events as gp  # noqa: E402

STORY = json.loads((REPO / "docs" / "story" / "story-events.json").read_text(encoding="utf-8"))
GLANCE_TARGETS = json.loads((REPO / "Tools" / "GameFlow" / "glance_targets.json").read_text(encoding="utf-8"))
POI_CINES = sorted(bc.POI_PLANS)
POI_BEATS = [b for b in STORY["optional_beats"] if b.get("tier") == "poi"]


def test_generated_files_are_current():
    story, gt = gp.build(STORY, GLANCE_TARGETS)
    assert story == STORY, "run python Tools/Cinematics/gen_poi_events.py"
    assert gt == GLANCE_TARGETS


@pytest.mark.parametrize("cid", POI_CINES + ["CIN_23_THE_MARK"])
def test_plan_frames_its_targets(cid):
    assert bc.check(cid) == 0


@pytest.mark.parametrize("cid", POI_CINES + ["CIN_23_THE_MARK"])
def test_emit_writes_chunks(cid, tmp_path):
    assert bc.emit(cid, tmp_path) == 0
    for f in tmp_path.glob("*.py"):
        compile(f.read_text(encoding="utf-8"), str(f), "exec")
    assert (tmp_path / "80_cuts.py").exists() and (tmp_path / "90_save.py").exists()


@pytest.mark.parametrize("cid", POI_CINES)
def test_data_matches_plan(cid):
    c = STORY["cinematics"][cid]
    assert c["keep_station_playing"] is True
    plan = bc.PLANS[cid]()
    assert c["sequence"].rsplit("/", 1)[1] == plan["asset"]
    assert abs(c["duration_s"] - plan["duration"]) < 1e-6
    assert c["blend_out_s"] == plan["blend_out"]
    assert c["skip"] == "HoldAlways" and "PoiCine" in c["requires_tags"]
    assert c["relative_to_pawn"] == (plan.get("frame") == "local")
    for cue in c["cues"]:
        assert 0.0 <= cue["at_s"] <= plan["duration"]


@pytest.mark.parametrize("cid", POI_CINES)
def test_shots_cover_the_duration(cid):
    plan = bc.PLANS[cid]()
    shots = plan["shots"]
    assert shots[0][0] == 0.0 and abs(shots[-1][1] - plan["duration"]) < 1e-6
    for a, b in zip(shots, shots[1:]):
        assert abs(a[1] - b[0]) < 1e-6
    names = {c["name"] for c in plan["cams"]}
    assert {s[2] for s in shots} <= names


def test_discovery_beat_lengths():
    """Discovery beats are 4-10.5 s (the last 2 s are the hand-back blend); CIN_06F only adds 4 s to CIN_06."""
    for cid in POI_CINES:
        d = bc.PLANS[cid]()["duration"]
        if cid == "CIN_06F_CREST_FORT":
            assert d - bc.plan_cin06()["duration"] == 4.0
        else:
            assert 4.0 <= d <= 10.5, cid
    for gid, g in STORY["glances"].items():
        if gid.startswith(("GP_", "GZ_")):
            assert g["ease_in_s"] + g["hold_s"] <= 4.0 and not g["lock_move"]


def test_road_m_matches_ue_m():
    for b in POI_BEATS:
        if b["trigger"] == "pass":
            assert abs(bc.ue_m_for_road_m(b["distance_m"]) - b["ue_distance_from_p0_m"]) < 0.1, b["id"]


def _camera_beats():
    """Road m of every beat that takes the camera (cinematic or glance), mandatory and POI (with PoiCine and
    PoiGlance on, so CIN_06F replaces CIN_06). Optional scenes A/B and CIN_03/11X/23 are left out."""
    out = []
    for b in STORY["beats"]:
        for a in b.get("actions", []):
            if a["type"] in ("PlayCinematic", "Glance") and not set(a.get("requires_tags", [])) - {"PoiCine"}:
                out.append((b["distance_m"], a["id"]))
                break
    for b in POI_BEATS:
        if b["trigger"] == "pass" and any(a["type"] in ("PlayCinematic", "Glance") for a in b["actions"]):
            out.append((b["distance_m"], b["id"]))
    return sorted(out)


def test_spacing_one_camera_beat_per_300_m():
    cams = [c for c in _camera_beats() if c[0] < 4500]          # the ending chain is its own pacing
    gaps = [(b[0] - a[0], a[1], b[1]) for a, b in zip(cams, cams[1:])]
    short = [g for g in gaps if g[0] < 275]
    # the one documented exception: the airship is in sight only from 550 to 710 m, 250 m after G03
    assert short == [(250, "G03_PROMISE", "P04_AIRSHIP")], short


def test_glance_targets_exist_and_zone_volumes_sit_in_zones():
    tether = json.loads((REPO / "Tools" / "World" / "tether_paths.json").read_text(encoding="utf-8"))
    zones = {z["id"]: z for z in tether["zones"]}
    for gid, g in STORY["glances"].items():
        assert g["target_tag"] in GLANCE_TARGETS, gid
    for b in POI_BEATS:
        for a in b["actions"]:
            if a["type"] == "Glance":
                assert a["id"] in STORY["glances"]
            if a["type"] == "PlayCinematic":
                assert a["id"] in STORY["cinematics"]
        if b["trigger"].startswith("volume:"):
            v = b["volume"]
            z = zones[b["id"][3:]]
            assert v["trigger_id"] == b["trigger"].split(":", 1)[1]
            assert v["centre_cm"][:2] == z["centre_cm"][:2] and v["extent_cm"][0] < z["radius_cm"]


def test_poi_cinematic_budget():
    total = sum(bc.PLANS[c]()["duration"] for c in POI_CINES) - bc.plan_cin06()["duration"]
    assert total <= 60.0, total
