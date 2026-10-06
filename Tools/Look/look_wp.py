"""Load and unload the landscape proxies a look capture needs (task FOG3B).

    python Tools/Look/look_wp.py tiles  <view>     # offline: the proxies capture_look.py <view> needs
    python Tools/Look/look_wp.py load   <view>     # load them (one python_run)
    python Tools/Look/look_wp.py unload <view>     # unload and unpin them (one python_run)

In the editor, World Partition keeps most landscape tiles unloaded, and a capture over an unloaded tile shows
a hole or a floating slab (LOOK.md, "Why captures use a temporary SceneCapture2D"). A view needs the tile under
the camera and the ones its 70 deg frustum crosses out to about 600 m: at most 4 (LOOK.md's rule), picked here by
how many rays of the frustum cross each tile. Tile = 510 m, index floor((x + 18920) / 51000), floor((y - 50) / 51000),
label LandscapeStreamingProxy_<ix>_<iy>_0 (LOOK.md's table: road_200 -> 12_8, 11_8, 11_7, 12_7).

Load, capture and unload are separate calls (memory: WP scripted load/save/unload); nothing is saved. Captures
never edit these actors, so unload leaves nothing dirty; it also unpins them. Wrap it in
Tools/GameFlow/editor_gate.py acquire/release; python_run refuses while PIE runs.
"""
import argparse
import math
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "Tools" / "Story"))

from apply_look import check_banned, python_run  # noqa: E402

TILE_CM = 51000.0
ORIGIN_CM = (-18920.0, 50.0)
MAX_TILES = 4
REACH_M = 600.0
HALF_FOV_DEG = 35.0

OP = r'''
import unreal
lib = unreal.WorldPartitionBlueprintLibrary
WANT = __WANT__
got = lib.get_intersecting_actor_descs(lib.get_editor_world_bounds())
descs = got[1] if isinstance(got, tuple) else got
gs = [d.get_editor_property("guid") for d in descs if str(d.get_editor_property("label")) in WANT]
if gs:
    lib.__OP__(gs)
__UNPIN__
print("__OP__ " + str(len(gs)) + " of " + str(len(WANT)) + " " + str(WANT))
'''


def tile_of(x_cm, y_cm):
    return int(math.floor((x_cm - ORIGIN_CM[0]) / TILE_CM)), int(math.floor((y_cm - ORIGIN_CM[1]) / TILE_CM))


def view_tiles(view):
    """The (up to MAX_TILES) proxy labels under and ahead of the view, most-crossed first (the camera's tile first)."""
    import capture_look
    x, y, _z, _pitch, yaw = capture_look.view_pose(view)
    hits = Counter()
    for da in range(-int(HALF_FOV_DEG), int(HALF_FOV_DEG) + 1, 5):
        a = math.radians(yaw + da)
        for s in range(0, int(REACH_M) + 1, 10):
            hits[tile_of(x + math.cos(a) * s * 100.0, y + math.sin(a) * s * 100.0)] += 1
    own = tile_of(x, y)
    order = [own] + [t for t, _n in hits.most_common() if t != own]
    return [f"LandscapeStreamingProxy_{i}_{j}_0" for i, j in order[:MAX_TILES]]


def op_script(labels, load):
    return check_banned(OP.replace("__WANT__", repr(labels)).replace("__OP__", "load_actors" if load else "unload_actors")
                        .replace("__UNPIN__", "" if load else "if gs:" + chr(10) + "    lib.unpin_actors(gs)"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["tiles", "load", "unload"])
    ap.add_argument("view")
    a = ap.parse_args(argv)
    labels = view_tiles(a.view)
    if a.step == "tiles":
        print(a.view, labels)
        return 0
    ok, out, err = python_run(op_script(labels, a.step == "load"))
    print(out.strip())
    if not ok or err:
        print("python_run failed:", err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
