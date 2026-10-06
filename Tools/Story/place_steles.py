"""Place the Saskartan inscription steles (task INSCR; LANE4, 2026-09-28).

    python Tools/Story/place_steles.py plan      # offline: print the way-stone and dock-post positions
    python Tools/Story/place_steles.py place     # editor: spawn/update the stones and their glyph decals (no save)
    python Tools/Story/place_steles.py save      # editor: save the stele actors, in chunks of 20

- I05 way-stones ("rzag-zririt"): 34 short upright stones along the verge, about every 138 m of road, alternating
  sides, 4.8 m off the centre line, each with a 20 x 45 cm carved-glyph decal (MI_Glyph_I05_Carved) on its
  road-facing side; per-stone wear 0.1-0.85 in the decal colour alpha (some nearly worn away).
- I02 carrier dock ("dinigaradzah"): two tall posts flanking the road at the dock (road metre 6), the glyph at
  45 x 110 cm on the first and a fainter repeat on the second.
Bodies: the brief's fallback (Geometry Script is not used; rebuilding meshes from python has crashed this editor):
AshesOfBazaar SM_Pillar_A_01 with Light_Foliage MI_Rock_01 (its own ornament material read as a pattern), scaled to about 30 x 20 x 75 cm (way-stones) and 60 x 40 x 220 cm (dock posts).
Labels Stele_WayStone_<i>, Stele_WayStone_<i>_Glyph, Stele_DockPost_<A|B>, Stele_DockPost_<A|B>_Glyph.
The bodies are now replaced by the dedicated stele meshes (SourceArt/Steles, Tools/Look/import_steles.py swap):
re-running `place` puts the pillar and MI_Rock_01 back, so run `import_steles.py swap` (and save) after it.
"""
import argparse
import math
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
sys.path.insert(0, str(ROOT / "Tools" / "Story"))
from apply_look import check_banned, python_run  # noqa: E402

MESH = "/Game/AshesOfBazaar/Meshes/SM_Pillar_A_01"
MESH_EXT = (31.0, 42.0, 102.0)          # half extents (cm), pivot at the base
WAY_COUNT = 34
WAY_START, WAY_END = 60.0, 4700.0
WAY_OFFSET_M = 4.8
WAY_SIZE = (30.0, 20.0, 75.0)           # the stone: depth (toward the road), width, height (cm)
DOCK_M = 6.0
DOCK_OFFSET_M = 3.8
DOCK_SIZE = (40.0, 60.0, 220.0)


def plan():
    from build_road_profile import SPLINE_POINTS_CM, Road, Terrain, HEIGHTMAP
    road, ter = Road(SPLINE_POINTS_CM), Terrain(HEIGHTMAP)
    rng = random.Random(505)
    items = []

    def spot(m, side_m, size, kind, name, glyph, gsize, wear):
        p, q = road.xy(m), road.xy(m + 5.0)
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n                       # UE road-right (+Y when travel is +X)
        x, y = p[0] + nx * side_m * 100.0, p[1] + ny * side_m * 100.0
        z = float(ter.height(x, y)) * 100.0 - 8.0      # sunk a little into the ground
        to_road = math.degrees(math.atan2(-ny * math.copysign(1, side_m), -nx * math.copysign(1, side_m)))
        yaw = to_road + rng.uniform(-12.0, 12.0)
        items.append({"name": name, "kind": kind, "x": round(float(x), 1), "y": round(float(y), 1), "z": round(z, 1),
                      "yaw": round(yaw, 2), "lean": round(rng.uniform(-4.0, 4.0), 2),
                      "scale": [round(size[0] / (2 * MESH_EXT[0]), 3), round(size[1] / (2 * MESH_EXT[1]), 3),
                                round(size[2] / (2 * MESH_EXT[2]), 3)],
                      "face": size[0] / 2.0, "gz": round(size[2] * 0.55, 1), "glyph": glyph,
                      "gsize": gsize, "wear": round(wear, 2)})

    step = (WAY_END - WAY_START) / (WAY_COUNT - 1)
    for i in range(WAY_COUNT):
        side = WAY_OFFSET_M if i % 2 == 0 else -WAY_OFFSET_M
        wear = rng.choice([0.1, 0.2, 0.35, 0.5, 0.65, 0.85])
        spot(WAY_START + i * step + rng.uniform(-15.0, 15.0), side, WAY_SIZE, "way", f"Stele_WayStone_{i}",
             "MI_Glyph_I05_Carved", (20.0, 45.0), wear)
    # Unreal's +Y is camera-right: the negative offset is the post in the opening's centre frame.
    # B teaches the reading; A is the worn repeat to the right, outside that frame.
    spot(DOCK_M, DOCK_OFFSET_M, DOCK_SIZE, "dock", "Stele_DockPost_A", "MI_Glyph_I02_Carved", (45.0, 110.0), 0.75)
    spot(DOCK_M, -DOCK_OFFSET_M, DOCK_SIZE, "dock", "Stele_DockPost_B", "MI_Glyph_I02_Carved", (45.0, 110.0), 0.15)
    return items


PLACE = r'''
import unreal, math
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
ITEMS = __ITEMS__
have = {}
for a in eas.get_all_level_actors():
    if a.get_actor_label().startswith('Stele_'):
        have[a.get_actor_label()] = a
mesh = unreal.load_asset('__MESH__')
n = 0
for it in ITEMS:
    s = have.get(it['name'])
    if s is None:
        s = eas.spawn_actor_from_object(mesh, unreal.Vector(it['x'], it['y'], it['z']))
        s.set_actor_label(it['name'])
    s.set_actor_location(unreal.Vector(it['x'], it['y'], it['z']), False, False)
    s.set_actor_rotation(unreal.Rotator(roll=it['lean'], pitch=0.0, yaw=it['yaw']), False)
    s.set_actor_scale3d(unreal.Vector(it['scale'][0], it['scale'][1], it['scale'][2]))
    s.set_folder_path('Story/Steles')
    c = s.static_mesh_component
    c.set_editor_property('ld_max_draw_distance', 15000.0)
    c.set_editor_property('cast_shadow', True)
    rock = unreal.load_asset('/Game/Light_Foliage/Materials/MI_Rock_01')
    for mi in range(c.get_num_materials()):
        c.set_material(mi, rock)
    g = have.get(it['name'] + '_Glyph')
    yaw = math.radians(it['yaw'])
    fx, fy = math.cos(yaw), math.sin(yaw)
    gx = it['x'] + fx * it['face']
    gy = it['y'] + fy * it['face']
    if g is None:
        g = eas.spawn_actor_from_class(unreal.DecalActor, unreal.Vector(gx, gy, it['z'] + it['gz']))
        g.set_actor_label(it['name'] + '_Glyph')
    g.set_actor_location(unreal.Vector(gx, gy, it['z'] + it['gz']), False, False)
    g.set_actor_rotation(unreal.Rotator(roll=0.0, pitch=0.0, yaw=it['yaw'] + 180.0), False)
    g.set_folder_path('Story/Steles')
    d = g.decal
    d.set_decal_material(unreal.load_asset('/Game/SaskartaGaea/Inscriptions/' + it['glyph']))
    d.set_editor_property('decal_size', unreal.Vector(12.0, it['gsize'][0] * 0.5, it['gsize'][1] * 0.5))
    d.set_editor_property('decal_color', unreal.LinearColor(1.0, 1.0, 1.0, it['wear']))
    d.set_editor_property('fade_screen_size', 0.002)
    n += 1
print('STELES ' + str(n))
'''

SAVE = r'''
import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
pk = [a.get_package() for a in eas.get_all_level_actors() if a.get_actor_label().startswith('Stele_')]
CHUNK = __CHUNK__
part = pk[CHUNK * 20:(CHUNK + 1) * 20]
print('SAVE ' + str(len(pk)) + ' ' + str(len(part)) + ' ' + str(unreal.EditorLoadingAndSavingUtils.save_packages(part, True) if part else 'none'))
'''


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["plan", "place", "save"])
    a = ap.parse_args(argv)
    if a.step == "plan":
        for it in plan():
            print(it["name"], it["x"], it["y"], it["z"], it["yaw"], it["wear"])
        return 0
    if a.step == "place":
        items = plan()
        for i in range(0, len(items), 6):
            ok, out, err = python_run(check_banned(PLACE.replace("__ITEMS__", repr(items[i:i + 6])).replace("__MESH__", MESH)))
            print(out.strip() if ok else err)
            if not ok:
                return 1
        return 0
    for chunk in range(4):
        ok, out, err = python_run(check_banned(SAVE.replace("__CHUNK__", str(chunk))))
        print(out.strip() if ok else err)
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
