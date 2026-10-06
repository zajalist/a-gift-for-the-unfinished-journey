"""Offline checks for the ending's Level Sequences, CIN_15/18/19/24 (+ CIN_25's clock). No editor.

    python -m pytest Tools/Cinematics/tests -q -p no:cacheprovider

What an editor lane would otherwise find out at render time: the road frame is the runner's, the plans frame
their subjects at every key (and wherever the pawn may stop), no camera sits in the ground or behind a hill, the
emitted chunks run under python_run's rules, the story data matches the plans, and the probe chunk is usable.
"""
import json
import math
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CIN = HERE.parent
REPO = CIN.parents[1]
sys.path.insert(0, str(CIN))
import build_cinematics as bc  # noqa: E402

STORY = json.loads((REPO / "docs" / "story" / "story-events.json").read_text(encoding="utf-8"))
ENDING = list(bc.ENDING)
BANNED = ("try", "getattr", "import time", "open(", ".replace(", "new_level(")
needs_heightmap = pytest.mark.skipif(bc.terrain() is None, reason="no Saved/TerrainRebuild/Current_u16.png")


def test_spline_walk_matches_every_profile_sample():
    """The polyline walk (the runner's origin) lands on all 102 road-profile samples within 10 cm."""
    for s in json.loads(bc.ROAD_PROFILE.read_text(encoding="utf-8"))["samples"]:
        f = bc.spline_frame_at_ue(s["ue_spline_distance_m"])
        assert math.hypot(f["x"] - s["x_cm"], f["y"] - s["y_cm"]) < 10.0, s["dist_m"]


def test_road_frame_does_not_cut_corners():
    """4,790 is 1.96 m past spline point 4 (UE 221.84 m vs point 4 at 223.80 m): the frame is on segment 4 -> 3
    (yaw 137.3), not on the chord between the 50 m samples (which was 6.4 m off)."""
    f = bc.road_frame(4790)
    if bc.probe_ending().get("frames", {}).get("4790", {}).get("probed"):
        pytest.skip("probed frame")
    p4 = bc.spline_points()[4]
    assert abs(f["yaw"] - 137.3) < 0.2
    assert 150.0 < math.hypot(f["x"] - p4[0], f["y"] - p4[1]) < 220.0


@pytest.mark.parametrize("cid", ENDING + ["CIN_23_THE_MARK"])
def test_plan_frames_its_targets_at_every_key(cid):
    assert bc.check(cid, strict=True, quiet=True) == 0


def test_b18_is_196_cm_past_spline_point_4():
    pts = bc.spline_points()
    ue_p4 = sum(math.dist(a, b) for a, b in zip(pts[:4], pts[1:5])) / 100.0
    assert abs(ue_p4 - 223.80) < 0.01
    assert abs((ue_p4 - bc.ue_m_for_road_m(4790)) - 1.96) < 0.02


@pytest.mark.parametrize("cid", ["CIN_15_IN_RANGE", "CIN_18_COLLAPSE", "CIN_19_HATCH", "CIN_23_THE_MARK"])
def test_every_camera_holds_wherever_the_pawn_stops(cid):
    """Every stop point in the window: clearance, framing, lines of sight, and the cameras on the carrier stay on it."""
    assert bc.window_check(cid, quiet=True) == 0


def test_cin15_window_is_the_whole_range_b15_can_land_in():
    """B15 fires at 4,520 (queued behind B14) and the crown drops behind the shoulder at ~4,610."""
    st = bc.window_stops(bc.plan_cin15())
    assert st[0] <= 4520 and st[-1] >= 4610 and len(st) >= 90


@needs_heightmap
def test_the_old_spline_origin_is_caught(monkeypatch):
    """The runner before RoadCineOrigin put the origin at the spline's z: the POV eye went 1.5 m under the ground for
    a stop at 4,555 and the carrier left CIN15_S2_Long's frame from ~4,590. The window check must see that."""
    monkeypatch.setattr(bc, "ORIGIN_Z", "spline")
    assert bc.window_check("CIN_15_IN_RANGE", quiet=True) == 1
    r = bc.window_report("CIN_15_IN_RANGE")
    clear, stop, _ = r["low"]["CIN15_S1_POV90"]
    assert clear < 0.0                                               # under the ground
    assert r["drift"]["CIN15_S1_POV90"][0] > 300.0                   # metres off the carrier's eye
    assert r["out"][("CIN15_S2_Long", "carrier")][0] > 1.0           # the carrier out of the long shot


@needs_heightmap
def test_origin_is_the_carriers_feet_at_every_stop():
    """The origin z is the ground under the spline point (the carrier's feet), not the spline z, which is up to ~6 m
    off it inside CIN_15's window."""
    worst = 0.0
    for m in bc.window_stops(bc.plan_cin15()):
        f = bc.road_frame(m)
        assert abs(f["z"] - bc.ground_z(f["x"], f["y"])) < 0.01
        worst = max(worst, abs(f["z"] - f["spline_z"]))
    assert worst > 500.0


def test_runner_source_uses_the_feet_origin():
    """The offline plans assume FSaskartaEventLogic::RoadCineOrigin; the runner must call it for TransformOrigin."""
    src = (REPO / "Plugins" / "SaskartaCore" / "Source" / "SaskartaCore" / "Private" / "SaskartaEventRunner.cpp").read_text(encoding="utf-8")
    hdr = (REPO / "Plugins" / "SaskartaCore" / "Source" / "SaskartaCore" / "Public" / "SaskartaEventLogic.h").read_text(encoding="utf-8")
    assert "FSaskartaEventLogic::RoadCineOrigin(" in src and "TransformOrigin = FTransform(Yaw, Loc)" in src
    assert "PawnLocation.Z - FMath::Max(0.f, PawnHalfHeight)" in hdr


def test_cin23_frames_the_keeper_where_he_stops():
    """CIN_23 plays where B23 stops the Keeper (the origin), ~18 m short of the High Voice StandPoint, which is the
    capsule centre at the plate since the set moved onto the mast: the plan must not frame the StandPoint."""
    plan = bc.plan_cin23()
    s1 = next(c for c in plan["cams"] if c["name"] == "CIN23_S1_LowTilt")
    k = s1["targets"]["keeper"]
    assert abs(k[0]) < 1e-6 and abs(k[1]) < 1e-6 and 90.0 < k[2] < 110.0
    fr = bc.road_frame(plan["road_m"])
    assert bc.to_local(fr, bc.probe_ending()["high_voice"]["stand"])[0] > 1500.0


@needs_heightmap
@pytest.mark.parametrize("cid", ENDING)
def test_no_camera_in_the_ground_or_behind_a_hill(cid):
    assert bc.terrain_check(cid, quiet=True) == 0


@needs_heightmap
def test_heights_are_from_the_feet_not_the_spline():
    """At 4,575 the landscape is ~1 m above the spline. The origin is the carrier's feet, so the eye is keyed at
    carrier_eye_z over it, and the frame keeps the spline z only for reference."""
    fr = bc.road_frame(bc.probe_ending()["cin15_road_m"])
    assert abs(bc.ground_local(fr)) < 0.01
    assert abs(fr["z"] - fr["spline_z"]) > 50.0
    eye = bc.plan_cin15()["cams"][0]["keys"][0][3]
    assert abs(eye - bc.probe_ending()["carrier_eye_z"]) < 0.01


@pytest.mark.parametrize("cid", ENDING + ["CIN_25_END_CARD"])
def test_emit_writes_runnable_chunks(cid, tmp_path):
    assert bc.emit(cid, tmp_path) == 0
    names = sorted(f.name for f in tmp_path.glob("*.py"))
    for f in tmp_path.glob("*.py"):
        text = f.read_text(encoding="utf-8")
        compile(text, str(f), "exec")
        assert not [w for w in BANNED if w in text], f.name
        # The body attachment rig retains 1,081 motion keys; the displayed exterior camera is smaller.
        assert len(text) < (100000 if (cid, f.name) == ("CIN_19_HATCH", "10_body_anchor.py") else 20000), f.name
    plan = bc.PLANS[cid]()
    assert names[0] == "00_setup.py" and names[-2:] == ["90_save.py", "99_read.py"]
    assert sum(n.startswith("10_cam_") for n in names) == len(plan["cams"])
    assert ("70_fade.py" in names) == bool(plan.get("fade"))
    assert ("80_cuts.py" in names) == bool(plan["shots"])


@pytest.mark.parametrize("cid", ENDING + ["CIN_25_END_CARD"])
def test_story_data_matches_plan(cid):
    c = STORY["cinematics"][cid]
    plan = bc.PLANS[cid]()
    assert c["sequence"].rsplit("/", 1)[1] == plan["asset"]
    assert abs(c["duration_s"] - plan["duration"]) < 1e-6
    assert c["blend_out_s"] == pytest.approx(plan["blend_out"]) or cid == "CIN_19_HATCH"   # CIN_19: the runner's 1.6 s blend
    assert c["relative_to_pawn"] == (plan.get("frame") == "local")
    for cue in c["cues"]:
        assert 0.0 <= cue["at_s"] <= plan["duration"], cue


@pytest.mark.parametrize("cid", ENDING)
def test_shots_cover_the_duration_and_keys_sit_in_their_sections(cid):
    plan = bc.PLANS[cid]()
    shots = plan["shots"]
    assert shots[0][0] == 0.0 and abs(shots[-1][1] - plan["duration"]) < 1e-6
    for a, b in zip(shots, shots[1:]):
        assert abs(a[1] - b[0]) < 1e-6
    ranges = bc.cam_ranges(plan)
    for c in plan["cams"]:
        t0, t1 = ranges[c["name"]]
        assert all(t0 - 1e-6 <= k[0] <= t1 + 1e-6 for k in c["keys"]), c["name"]


@pytest.mark.parametrize("cid", ["CIN_24_TRANSMISSION", "CIN_25_END_CARD"])
def test_fade_keys_are_in_range(cid):
    f = bc.PLANS[cid]()["fade"]
    d = bc.PLANS[cid]()["duration"]
    assert all(0.0 <= t <= d and 0.0 <= v <= 1.0 for t, v, _ in f["keys"])


def test_cin25_clock_matches_the_roll():
    p = bc.plan_cin25()
    assert p["duration"] == STORY["cinematics"]["CIN_25_END_CARD"]["duration_s"] == 17.0 + bc.roll_seconds() + 3.0
    cue = next(c for c in STORY["cinematics"]["CIN_25_END_CARD"]["cues"] if c["id"] == "CreditsRoll")
    assert cue["duration_s"] == bc.roll_seconds()


def test_probe_chunk_is_python_run_safe(tmp_path):
    out = tmp_path / "probe.py"
    bc.emit_probe_ending(out)
    text = out.read_text(encoding="utf-8")
    compile(text, str(out), "exec")
    assert not [w for w in BANNED if w in text]
    assert "PROBE_JSON " in text and "BP_Saskarta_Road" in text


def test_merge_probe_sets_the_note_and_the_capsule_heights():
    got = {"carrier_eye_z": 130.0, "capsule_root_local": [-250.0, 0.0, 50.0], "capsule_hatch_local": [-250.0, 0.0, 115.0],
           "keeper_half_height_cm": 90.0, "frames": {"4790": {"x": 1.0, "y": 2.0, "z": 3.0, "yaw": 137.0, "probed": True}}}
    pe = bc.merge_probe("noise\nPROBE_JSON " + json.dumps(got) + "\n", "2026-09-28")
    assert pe["note"].startswith("PROBED 2026-09-28") and "high_voice" in pe["note"]
    assert pe["capsule_floor_z"] == 50.0 and pe["capsule_rim_z"] == 115.0 and pe["half_rise_eye_z"] == 140.0
    assert pe["frames"]["4790"]["probed"] and pe["keeper_half_height_cm"] == 90.0
    assert bc.probe_ending()["note"] != pe["note"]          # merge_probe does not write the file


def test_frames_report_is_world_space():
    rows = bc.frames_report("CIN_18_COLLAPSE")
    ext = [r for r in rows if r["cam"] == "CIN18_S3_ExtShutdown"]
    fr = bc.road_frame(4790)
    assert ext and all(math.hypot(r["loc"][0] - fr["x"], r["loc"][1] - fr["y"]) < 1500 for r in ext)
