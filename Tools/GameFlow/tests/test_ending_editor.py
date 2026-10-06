"""Offline checks for Tools/GameFlow/editor/ending_editor.py (task ENDING-PREP). No editor.

    python -m pytest Tools/GameFlow/tests/test_ending_editor.py -q -p no:cacheprovider
"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Tools" / "GameFlow" / "editor"))
sys.path.insert(0, str(ROOT / "Tools" / "Cinematics"))
import ending_editor as ee  # noqa: E402
import build_cinematics as bc  # noqa: E402

STEPS = ["survey", "mi", "mi-save", "place", "read", "save", "trav", "trav-save", "story-import", "story-save"]


@pytest.mark.parametrize("step", STEPS)
def test_every_chunk_compiles_and_obeys_python_run(step):
    text = ee.chunk(step, {})
    compile(text, step, "exec")
    assert ee.banned(text) == [], step
    assert "__" not in text.replace("__init__", ""), step          # no unfilled placeholder
    assert len(text) < 30000


def test_place_with_a_hut_wall_plate_and_the_posed_traveller():
    text = ee.chunk("place", {"plate_at": [298163.6, 483845.6]})
    compile(text, "place", "exec")
    assert "PA = (298163.6, 483845.6)" in text
    posed = ee.chunk("trav", {"at": "stand19"})
    compile(posed, "trav", "exec")
    assert "do NOT save" in posed


def test_place_bakes_the_heightmap_grid():
    if bc.terrain() is None:
        pytest.skip("no heightmap")
    g = ee.height_grid()
    n = 2 * ee.GRID_HALF_M + 1
    assert len(g) == n and all(len(r) == n for r in g)
    centre = g[ee.GRID_HALF_M][ee.GRID_HALF_M]
    assert abs(centre - 10868.7) < 1.0          # L2's line trace at the beacon: 10868.7 cm


def test_stand_yaw_is_the_road_into_point_zero():
    assert abs(ee.stand_yaw() - 83.66) < 0.05


def test_parked_traveller_is_behind_the_ending_cameras():
    x, y, z, yaw, mode = ee.traveller_pose(None)
    fr = bc.road_frame(4790)
    local = bc.to_local(fr, (x, y, z))
    assert mode == "parked" and local[0] < -2000.0            # 27 m behind (40 m of road round point 4); the
    # farthest-back ending camera (CIN19_S5_Wide) is 9 m behind, all look up-road
    g = bc.ground_z(x, y)
    if g is not None:
        assert 50.0 < z - g < 150.0


def test_story_save_refuses_a_read_only_package(tmp_path, monkeypatch):
    f = tmp_path / "DA.uasset"
    f.write_bytes(b"x")
    f.chmod(0o444)
    monkeypatch.setattr(ee, "STORY_FILE", f)
    with pytest.raises(SystemExit) as e:
        ee.main(["story-save", "--print"])
    assert "read-only" in str(e.value)
    f.chmod(0o666)


def test_direct_pin_api_is_allowed_but_exception_handling_is_rejected():
    assert ee.banned('a.try_create_connection(b)') == []
    assert 'try' in ee.banned('try:\n    a.try_create_connection(b)\nexcept Exception:\n    pass')


def test_fault_scan_reads_only_new_log_lines(tmp_path, monkeypatch):
    log = tmp_path / "ed.log"
    log.write_text("old: EXCEPTION_ACCESS_VIOLATION\n", encoding="utf-8")
    monkeypatch.setattr(ee, "LOG", log)
    since = ee.log_size()
    assert ee.new_faults(since) == []
    with log.open("a", encoding="utf-8") as fh:
        fh.write("LogHayba: HCR-NATIVE-002 caught\n")
    assert len(ee.new_faults(since)) == 1


def test_watch_runs_a_job_and_kills_it_on_play(tmp_path, monkeypatch):
    import apply_look
    log = tmp_path / "ed.log"
    log.write_text("start\n", encoding="utf-8")
    monkeypatch.setattr(ee, "LOG", log)
    monkeypatch.setattr(apply_look, "pie_running", lambda *a, **k: False)
    out = tmp_path / "job.json"
    assert ee.watch(out, [sys.executable, "-c", "print('built')"]) == 0
    assert "built" in out.read_text(encoding="utf-8")
    import threading
    def press_play():
        import time as _t
        _t.sleep(1.5)
        with log.open("a", encoding="utf-8") as fh:
            fh.write("LogPlayLevel: Creating play world package: /Game/level/UEDPIE_0_Saskarta_WP\n")
    threading.Thread(target=press_play).start()
    assert ee.watch(tmp_path / "job2.json", [sys.executable, "-c", "import time; time.sleep(20)"]) == 99
