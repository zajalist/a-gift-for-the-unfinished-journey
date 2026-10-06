"""The ending's editor steps as small python_run chunks (task ENDING-PREP; RUNBOOK_Ending.md is the order).

    python Tools/GameFlow/editor/ending_editor.py survey          # read-only: beacon, crown, mast, taggings, traveller, meshes
    python Tools/GameFlow/editor/ending_editor.py mi              # MI_HighVoice_Glow if missing (M_Glow, Col 4/1.8/0.6)
    python Tools/GameFlow/editor/ending_editor.py mi-save
    python Tools/GameFlow/editor/ending_editor.py place           # spawn/update HighVoice_Ending on the L2 beacon
    python Tools/GameFlow/editor/ending_editor.py read            # read-back of HighVoice_Ending (+ the gate numbers)
    python Tools/GameFlow/editor/ending_editor.py save            # save the touched actor packages
    python Tools/GameFlow/editor/ending_editor.py trav [--at stand19]   # the one Keeper_Traveller (parked, or posed for a frame)
    python Tools/GameFlow/editor/ending_editor.py trav-save
    python Tools/GameFlow/editor/ending_editor.py lamp            # First Light: the hut-post lantern (hidden until B23L_LAMP)
    python Tools/GameFlow/editor/ending_editor.py lamp-save
    python Tools/GameFlow/editor/ending_editor.py story-import    # DA_Saskarta_Story from docs/story (prints the report)
    python Tools/GameFlow/editor/ending_editor.py story-save
    python Tools/GameFlow/editor/ending_editor.py run-dir Saved/Ending/CIN_18_COLLAPSE   # emitted chunks, name order
    python Tools/GameFlow/editor/ending_editor.py run-file Saved/Ending/probe_chunk.py > Saved/Ending/probe_out.txt
    python Tools/GameFlow/editor/ending_editor.py watch Saved/Ending/bp.json -- node Tools/GameFlow/bpgraph.mjs build ...
                                                                  # a long job under the PIE / fault watchdog
    add --print to any step to print the chunk instead of sending it (paste it into python_run by hand)

Every step is one python_run call, well under the 5 s deadline, with none of python_run's banned words (checked
before sending). apply_look.python_run refuses while PIE runs (and for 30 s after). After every call the new part
of the editor log is scanned: an access violation, HCR-NATIVE or "unknown opcode" stops everything (memory
python-mesh-rebuild-crashed-editor: after a native fault, no further calls; the editor needs a restart).
Load, edit, save and unload are separate calls (memory wp-scripted-load-save-unload). Hold the editor gate
(Tools/GameFlow/editor_gate.py) around the whole run.

The High Voice set (V10, brief step 6c), placed by `place`:
  - the actor HighVoice_Ending (BP_Saskarta_HighVoice at /Game/SaskartaGaea/Story/HighVoice/), tag Saskarta.HighVoice,
    not spatially loaded, in the beacon's folder. It is the ONLY actor with that tag (CallHook resolves one actor by
    tag; `place` strips it from any other actor and says so).
  - MastBase: the landscape under the L2 beacon `HighVoice` (the beacon stands 0.5 m sunk, L2 report).
  - Crown: the engine sphere at the beacon's own Crown, read LIVE, scale 8.4 (it encloses the beacon's 8 m crown, so
    its glow ramp shows), MI_HighVoice_Glow, no shadow, no collision.
  - Column: legacy compatibility component, hidden with collision disabled. The
    transmission uses Crown practical glow; no vertical sky column is shown.
  - Plate: SM_ChamferCube (5 x 40 x 40 cm) on the MAST's down-road face (read live from the beacon's Mast0 bounds),
    130 cm over the Keeper's feet, facing the arriving road. The V10 hut is not placed; with --plate-at X,Y (a hut
    wall) the plate goes there instead.
  - StandPoint: 60 cm in front of the plate, facing it, at CAPSULE-CENTRE height (ground + 95): SnapKeeperToPlate
    teleports the Keeper's capsule there (the first plan put it at the sunk mast base: 50 cm inside the ground).
  - SeatPoint: 1.5 m from the mast foot toward the boot point (yaw -3.5), 100 cm over the ground, pitch -4.
  Ground heights: a live line trace (ignoring the beacon and the set), else the heightmap grid baked into the chunk
  (Saved/TerrainRebuild/Current_u16.png, the landscape's source; it matched L2's trace to 0.1 cm).
"""
from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "Tools" / "Look"))
sys.path.insert(0, str(ROOT / "Tools" / "Cinematics"))

BANNED = ("try", "getattr", "import time", "open(", ".replace(", "new_level(")
FAULTS = ("HCR-NATIVE", "Access violation", "EXCEPTION_ACCESS_VIOLATION", "unknown opcode", "Unhandled Exception")
LOG = ROOT / "Saved" / "Logs" / "saskartarad.log"

HV_BP = "/Game/SaskartaGaea/Story/HighVoice/BP_Saskarta_HighVoice.BP_Saskarta_HighVoice_C"
TRAV_BP = "/Game/SaskartaGaea/Characters/Traveller/BP_Saskarta_Traveller.BP_Saskarta_Traveller_C"
MI = "/Game/SaskartaGaea/Story/HighVoice/MI_HighVoice_Glow"
STORY_DA = "/Game/SaskartaGaea/Story/DA_Saskarta_Story"
STORY_FILE = ROOT / "Content" / "SaskartaGaea" / "Story" / "DA_Saskarta_Story.uasset"
BEACON_XY = (298079.6, 483050.0)       # L2: the beacon at spline point 0
GRID_HALF_M = 12                        # the baked heightmap grid: +-12 m around the beacon, 1 m cells
PARK_ROAD_M = 4750.0                    # where the hidden traveller waits: 40 m of road before the collapse (27 m
                                        # straight, round spline point 4), behind every CIN_18/19 camera (they look up-road)


def stand_yaw() -> float:
    """The road's heading into point 0 (segment 1 -> 0): the Keeper faces the plate along it."""
    import build_cinematics as bc
    p0, p1 = bc.spline_points()[0], bc.spline_points()[1]
    return round(math.degrees(math.atan2(p0[1] - p1[1], p0[0] - p1[0])), 2)


def height_grid() -> list | None:
    """Heights (cm) on a 1 m grid around the beacon, rows along +Y, or None without the heightmap."""
    import build_cinematics as bc
    if bc.terrain() is None:
        return None
    x0, y0 = BEACON_XY[0] - GRID_HALF_M * 100.0, BEACON_XY[1] - GRID_HALF_M * 100.0
    n = 2 * GRID_HALF_M + 1
    return [[round(bc.ground_z(x0 + i * 100.0, y0 + j * 100.0), 1) for i in range(n)] for j in range(n)]


# ----------------------------------------------------------------------------- chunks
# Placeholders are __NAME__; fill() substitutes them. The engine rejects try
# statements, while identifiers such as try_create_connection remain inspectable.

HEAD = """import unreal, math
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
acts = eas.get_all_level_actors()
hvcls = unreal.load_object(None, '__HV_BP__')
beacon = [a for a in acts if a.get_actor_label() == 'HighVoice' and a.get_class() != hvcls]
mine = [a for a in acts if a.get_class() == hvcls]
tagged = [a for a in acts if 'Saskarta.HighVoice' in [str(t) for t in a.tags]]
"""

SURVEY = HEAD + """
trcls = unreal.load_object(None, '__TRAV_BP__')
print('beacon', len(beacon), 'ending HV', len(mine), 'tagged Saskarta.HighVoice', [str(a.get_actor_label()) for a in tagged])
for b in beacon:
    print(' beacon', str(b.get_actor_location()), str(b.get_class().get_path_name()), str(b.get_folder_path()), 'spatial', b.get_editor_property('is_spatially_loaded'))
    for c in b.get_components_by_class(unreal.StaticMeshComponent):
        o, e, r = unreal.SystemLibrary.get_component_bounds(c)
        print('  ', c.get_name(), 'at', str(c.get_world_location()), 'bounds o', str(o), 'e', str(e))
for a in mine:
    print(' ending', str(a.get_actor_label()), str(a.get_actor_location()), [str(t) for t in a.tags])
tr = [a for a in acts if a.get_class() == trcls]
print('travellers', len(tr), [(str(a.get_actor_label()), str(a.get_actor_location())) for a in tr])
print('MI exists', unreal.EditorAssetLibrary.does_asset_exist('__MI__'))
for p in ('/Game/LevelPrototyping/Meshes/SM_Cylinder', '/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Tile_10MPillar', '/Game/LevelPrototyping/Meshes/SM_ChamferCube', '/Engine/BasicShapes/Sphere'):
    m = unreal.load_asset(p)
    bb = m.get_bounds()
    print('mesh', p.split('/')[-1], 'origin', str(bb.origin), 'extent', str(bb.box_extent))
near = 0
for a in acts:
    q = a.get_actor_location()
    if abs(q.x - __BX__) < 2500 and abs(q.y - __BY__) < 2500:
        near += 1
        print(' near', str(a.get_actor_label()), a.get_class().get_name(), str(q))
print('actors loaded within 25 m of point 0:', near)
"""

MI_CREATE = """import unreal
E = unreal.EditorAssetLibrary
p = '__MI__'
if E.does_asset_exist(p):
    print('exists', p)
else:
    f = unreal.MaterialInstanceConstantFactoryNew()
    mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset('MI_HighVoice_Glow', '/Game/SaskartaGaea/Story/HighVoice', unreal.MaterialInstanceConstant, f)
    mi.set_editor_property('parent', unreal.load_asset('/Game/DemoTemplate/Materials/M_Glow'))
    unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(mi, 'Col', unreal.LinearColor(4.0, 1.8, 0.6, 1.0))
    unreal.MaterialEditingLibrary.update_material_instance(mi)
    print('created', p, 'parent', str(mi.get_editor_property('parent').get_name()))
"""

MI_SAVE = """import unreal
print('saved', unreal.EditorAssetLibrary.save_asset('__MI__', False))
"""

PLACE = HEAD + """
G = __GRID__
GX0 = __BX__ - __HALF__ * 100.0
GY0 = __BY__ - __HALF__ * 100.0
def grid_z(x, y):
    fx = min(max((x - GX0) / 100.0, 0.0), 2 * __HALF__ - 0.001)
    fy = min(max((y - GY0) / 100.0, 0.0), 2 * __HALF__ - 0.001)
    i = int(fx); j = int(fy); u = fx - i; v = fy - j
    return G[j][i] * (1 - u) * (1 - v) + G[j][i + 1] * u * (1 - v) + G[j + 1][i] * (1 - u) * v + G[j + 1][i + 1] * u * v
w = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
if len(beacon) != 1:
    print('STOP: expected one L2 beacon labelled HighVoice, found', len(beacon))
else:
    b = beacon[0]
    base0 = b.get_actor_location()
    a = mine[0] if mine else eas.spawn_actor_from_class(hvcls, unreal.Vector(base0.x, base0.y, base0.z + 50.0), unreal.Rotator(0, 0, 0))
    ign = [b, a]
    def ground(x, y):
        h = unreal.SystemLibrary.line_trace_single(w, unreal.Vector(x, y, base0.z + 3000.0), unreal.Vector(x, y, base0.z - 3000.0), unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, False, ign, unreal.DrawDebugTrace.NONE, True)
        t = h.to_tuple() if h is not None else None
        gz = grid_z(x, y) if G else base0.z + 50.0
        if t and t[0]:
            return t[4].z, 'trace', round(t[4].z - gz, 1)
        return gz, 'grid' if G else 'beacon', 0.0
    comps = {c.get_name(): c for c in a.get_components_by_class(unreal.SceneComponent)}
    need = ['MastBase', 'StandPoint', 'SeatPoint', 'Plate', 'Crown', 'Column']
    miss = [n for n in need if n not in comps]
    if miss:
        print('STOP: BP_Saskarta_HighVoice lacks components', miss)
    else:
        a.set_actor_label('HighVoice_Ending')
        a.set_editor_property('is_spatially_loaded', False)
        a.set_folder_path(str(b.get_folder_path()))
        a.set_editor_property('tags', [unreal.Name('Saskarta.HighVoice')])
        for o in tagged:
            if o != a:
                o.set_editor_property('tags', [t for t in o.tags if str(t) != 'Saskarta.HighVoice'])
                print('UNTAGGED', str(o.get_actor_label()), str(o.get_package().get_name()), '(save it too)')
        gb, src, dz = ground(base0.x, base0.y)
        if src != 'trace':
            gb = base0.z + 50.0
        base = unreal.Vector(base0.x, base0.y, gb)
        a.set_actor_location(base, False, False)
        a.set_actor_rotation(unreal.Rotator(0, 0, 0), False)
        mi = unreal.load_asset('__MI__')
        NC = unreal.CollisionEnabled.NO_COLLISION
        comps['MastBase'].set_world_location(base, False, False)
        bcr = [c for c in b.get_components_by_class(unreal.StaticMeshComponent) if 'rown' in c.get_name()]
        crown = bcr[0].get_world_location() if bcr else unreal.Vector(base.x, base.y, base.z + 4250.0)
        cr = comps['Crown']
        cr.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Sphere'))
        cr.set_material(0, mi)
        cr.set_world_location(crown, False, False)
        cr.set_world_scale3d(unreal.Vector(8.4, 8.4, 8.4))
        cr.set_editor_property('cast_shadow', False)
        cr.set_collision_enabled(NC)
        col_mesh = None
        for p in ('/Game/LevelPrototyping/Meshes/SM_Cylinder', '/Game/EasyAtmos/EpicContentDemo/DemoRoom/Meshes/Tile_10MPillar'):
            m = unreal.load_asset(p)
            bb = m.get_bounds()
            low = bb.origin.z - bb.box_extent.z
            print('column candidate', p.split('/')[-1], 'lowest z', round(low, 1), 'height', round(2 * bb.box_extent.z, 1))
            if col_mesh is None and abs(low) < 2.0:
                col_mesh = m
        if col_mesh is None:
            col_mesh = unreal.load_asset('/Game/LevelPrototyping/Meshes/SM_Cylinder')
            print('WARNING: no base-pivot column mesh; the column grows both ways from the mast foot')
        co = comps['Column']
        co.set_static_mesh(col_mesh)
        co.set_material(0, mi)
        co.set_world_location(base, False, False)
        co.set_world_scale3d(unreal.Vector(1.0, 1.0, 0.01))
        co.set_editor_property('cast_shadow', False)
        co.set_collision_enabled(NC)
        co.set_visibility(False, True)
        co.set_editor_property('hidden_in_game', True)
        SY = __STAND_YAW__
        ux = math.cos(math.radians(SY + 180.0)); uy = math.sin(math.radians(SY + 180.0))
        PA = __PLATE_AT__
        if PA:
            px, py = PA[0], PA[1]
        else:
            mast = [c for c in b.get_components_by_class(unreal.StaticMeshComponent) if c.get_name().startswith('Mast')]
            face = 30.0
            if mast:
                o, e, r = unreal.SystemLibrary.get_component_bounds(mast[0])
                face = (o.x - base.x) * ux + (o.y - base.y) * uy + e.x * abs(ux) + e.y * abs(uy)
            px, py = base.x + ux * (face + 3.0), base.y + uy * (face + 3.0)
            print('mast face', round(face, 1), 'cm from the foot toward the road')
        sx, sy = px + ux * 60.0, py + uy * 60.0
        gs, ssrc, sdz = ground(sx, sy)
        pl = comps['Plate']
        pm = unreal.load_asset('/Game/LevelPrototyping/Meshes/SM_ChamferCube')
        pb = pm.get_bounds()
        sc = unreal.Vector(0.05, 0.4, 0.4)
        c0, s0 = math.cos(math.radians(SY)), math.sin(math.radians(SY))
        ox, oy, oz = pb.origin.x * sc.x, pb.origin.y * sc.y, pb.origin.z * sc.z
        pz = gs + 130.0
        pl.set_static_mesh(pm)
        pl.set_world_rotation(unreal.Rotator(0, 0, SY), False, False)
        pl.set_world_scale3d(sc)
        pl.set_world_location(unreal.Vector(px - (ox * c0 - oy * s0), py - (ox * s0 + oy * c0), pz - oz), False, False)
        pl.set_collision_enabled(NC)
        comps['StandPoint'].set_world_location(unreal.Vector(sx, sy, gs + 95.0), False, False)
        comps['StandPoint'].set_world_rotation(unreal.Rotator(0, 0, SY), False, False)
        ex, ey = base.x + math.cos(math.radians(-3.5)) * 150.0, base.y + math.sin(math.radians(-3.5)) * 150.0
        ge, esrc, edz = ground(ex, ey)
        comps['SeatPoint'].set_world_location(unreal.Vector(ex, ey, ge + 100.0), False, False)
        comps['SeatPoint'].set_world_rotation(unreal.Rotator(roll=0, pitch=-4.0, yaw=-3.5), False, False)
        print('placed', str(a.get_actor_label()), str(a.get_package().get_name()))
        print('ground', 'base', src, 'stand', ssrc, sdz, 'seat', esrc, edz, '(trace minus heightmap, cm)')
        print('crown', str(crown), 'from the beacon' if bcr else 'DEFAULT (no beacon Crown)')
"""

READ = HEAD + """
print('ending HV', len(mine), 'tagged', [str(a.get_actor_label()) for a in tagged])
for a in mine:
    print(str(a.get_actor_label()), 'spatial', a.get_editor_property('is_spatially_loaded'), [str(t) for t in a.tags], str(a.get_folder_path()), str(a.get_package().get_name()))
    for c in a.get_components_by_class(unreal.SceneComponent):
        r = c.get_world_rotation()
        extra = ''
        if isinstance(c, unreal.StaticMeshComponent):
            sm = c.get_editor_property('static_mesh')
            mt = c.get_material(0)
            extra = ' mesh ' + (str(sm.get_name()) if sm else 'None') + ' mat ' + (str(mt.get_name()) if mt else 'None') + ' scale ' + str(c.get_world_scale())
        print('  ', c.get_name(), str(c.get_world_location()), 'pitch', round(r.pitch, 1), 'yaw', round(r.yaw, 1), extra)
"""

SAVE_ACTORS = HEAD + """
pk = [a.get_package() for a in mine]
for o in acts:
    if o not in mine and o.get_actor_label() == 'HighVoice' and 'Saskarta.HighVoice' not in [str(t) for t in o.tags] and __SAVE_BEACON__:
        pk.append(o.get_package())
print('saving', [str(p.get_name()) for p in pk])
print(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True))
"""

# First Light (gen_first_light_ending.py B23L_LAMP): the lantern on the hut post. A warm point light and a small
# flame card, both tagged Saskarta.Reveal.HutLamp and hidden in game; SpawnOrReveal HutLamp shows them on the press.
# No shadows (60 fps), 8 m radius. Position: build_cinematics.fl_lamp (FL_LAMP_* from the StandPoint), always loaded.
LAMP = """import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
old = [a for a in eas.get_all_level_actors() if 'Saskarta.Reveal.HutLamp' in [str(t) for t in a.tags] or a.get_actor_label().startswith('FL_HutLamp_')]
for a in old:
    eas.destroy_actor(a)
loc = unreal.Vector(__LX__, __LY__, __LZ__)
L = eas.spawn_actor_from_class(unreal.PointLight, loc, unreal.Rotator(0, 0, 0))
L.set_actor_label('FL_HutLamp_Light')
c = L.point_light_component
c.set_editor_property('intensity_units', unreal.LightUnits.CANDELAS)
c.set_intensity(12.0)
c.set_light_color(unreal.LinearColor(1.0, 0.62, 0.3, 1.0))
c.set_attenuation_radius(800.0)
c.set_cast_shadows(False)
c.set_editor_property('source_radius', 3.0)
F = eas.spawn_actor_from_class(unreal.StaticMeshActor, loc, unreal.Rotator(0, 0, 0))
F.set_actor_label('FL_HutLamp_Flame')
F.static_mesh_component.set_static_mesh(unreal.load_object(None, '/Engine/BasicShapes/Sphere.Sphere'))
F.set_actor_scale3d(unreal.Vector(0.06, 0.06, 0.09))
F.static_mesh_component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
F.static_mesh_component.set_cast_shadow(False)
m = unreal.load_object(None, '__MI__')
if m:
    F.static_mesh_component.set_material(0, m)
for a in (L, F):
    a.tags = [unreal.Name('Saskarta.Reveal.HutLamp')]
    a.set_actor_hidden_in_game(True)
    a.set_folder_path('Story/HighVoice')
    a.set_editor_property('is_spatially_loaded', False)
print('lamp placed', [a.get_actor_label() for a in (L, F)], loc)
"""

LAMP_SAVE = """import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
pk = [a.get_package() for a in eas.get_all_level_actors() if 'Saskarta.Reveal.HutLamp' in [str(t) for t in a.tags]]
print('saving', [str(p.get_name()) for p in pk])
print(unreal.EditorLoadingAndSavingUtils.save_packages(pk, True))
"""

TRAV = """import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cls = unreal.load_object(None, '__TRAV_BP__')
tr = [a for a in eas.get_all_level_actors() if a.get_class() == cls]
print('travellers in level', len(tr))
if len(tr) > 1:
    print('STOP: more than one traveller; the carrier finds it by class. Delete the extras by hand.')
else:
    if not tr:
        tr = [eas.spawn_actor_from_class(cls, unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(0, 0, __YAW__))]
    a = tr[0]
    a.set_actor_label('Keeper_Traveller')
    a.set_editor_property('is_spatially_loaded', False)
    a.set_folder_path('Gameplay')
    a.set_actor_location_and_rotation(unreal.Vector(__X__, __Y__, __Z__), unreal.Rotator(0, 0, __YAW__), False, False)
    print('__MODE__', str(a.get_actor_label()), str(a.get_actor_location()), 'hidden start', a.get_editor_property('bStartHidden'), str(a.get_package().get_name()))
"""

TRAV_SAVE = """import unreal
eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
cls = unreal.load_object(None, '__TRAV_BP__')
tr = [a for a in eas.get_all_level_actors() if a.get_class() == cls]
print('saving', [str(a.get_package().get_name()) for a in tr])
print(unreal.EditorLoadingAndSavingUtils.save_packages([a.get_package() for a in tr], True))
"""

STORY_IMPORT = """import unreal
story = unreal.load_asset('__DA__')
report = unreal.SaskartaStoryImport.import_story_from_files(story, unreal.Paths.project_dir())  # -> report str, or None
print('import ok', report is not None)
print(str(report))
"""

STORY_SAVE = """import unreal
print('saved', unreal.EditorAssetLibrary.save_loaded_asset(unreal.load_asset('__DA__'), False))
"""


def fill(text: str, **kw) -> str:
    for k, v in kw.items():
        text = text.replace(f"__{k}__", str(v))
    left = [w for w in ("__HV_BP__", "__TRAV_BP__", "__MI__", "__BX__", "__BY__", "__GRID__", "__DA__") if w in text]
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    return text


def banned(script: str) -> list:
    return [w for w in BANNED if (re.search(r'\btry\b', script) if w == 'try' else w in script)]


def chunk(step: str, opts: dict) -> str:
    base = dict(HV_BP=HV_BP, TRAV_BP=TRAV_BP, MI=MI, BX=BEACON_XY[0], BY=BEACON_XY[1], DA=STORY_DA)
    if step == "survey":
        return fill(SURVEY, **base)
    if step == "mi":
        return fill(MI_CREATE, **base)
    if step == "mi-save":
        return fill(MI_SAVE, **base)
    if step == "place":
        grid = height_grid()
        pa = opts.get("plate_at")
        return fill(PLACE, **base, GRID=repr(grid) if grid else "None", HALF=GRID_HALF_M, STAND_YAW=stand_yaw(),
                    PLATE_AT=repr(tuple(pa)) if pa else "None")
    if step == "read":
        return fill(READ, **base)
    if step == "save":
        return fill(SAVE_ACTORS, **base, SAVE_BEACON="True" if opts.get("save_beacon") else "False")
    if step == "trav":
        x, y, z, yaw, mode = traveller_pose(opts.get("at"))
        return fill(TRAV, **base, X=round(x, 1), Y=round(y, 1), Z=round(z, 1), YAW=round(yaw, 2), MODE=mode)
    if step == "trav-save":
        return fill(TRAV_SAVE, **base)
    if step == "lamp":
        sys.path.insert(0, str(ROOT / "Tools" / "Cinematics"))
        import build_cinematics as bc
        lx, ly, lz = bc.fl_lamp()
        return fill(LAMP, **base, LX=round(lx, 1), LY=round(ly, 1), LZ=round(lz, 1))
    if step == "lamp-save":
        return fill(LAMP_SAVE, **base)
    if step == "story-import":
        return fill(STORY_IMPORT, **base)
    if step == "story-save":
        return fill(STORY_SAVE, **base)
    raise SystemExit(f"unknown step {step}")


def traveller_pose(at: str | None):
    """Parked: on the road 40 m before the collapse (behind every ending camera), 100 cm over the ground, facing
    up-road; hidden in game from BeginPlay (bStartHidden). `--at stand19` is an unsaved
    legacy exterior-shot pose for editor comparisons; CIN_19 now uses first-person spawnables."""
    import build_cinematics as bc
    if at == "stand19":
        plan = bc.plan_cin19_exterior()
        cam = next(c for c in plan["cams"] if c["name"] == "CIN19_S5_Wide")
        kx, ky, kz = bc.world_point(plan, cam["targets"]["keeper"])
        fr = bc.road_frame(plan["road_m"])
        return kx, ky, kz - 8.0, fr["yaw"], "posed for CIN19_S5 (do NOT save; park it again)"
    f = bc.spline_frame_at_ue(bc.ue_m_for_road_m(PARK_ROAD_M))
    g = bc.ground_z(f["x"], f["y"])
    return f["x"], f["y"], (f["z"] if g is None else g) + 100.0, f["yaw"], "parked"


# ----------------------------------------------------------------------------- sending

def log_size() -> int:
    return LOG.stat().st_size if LOG.exists() else 0


def new_faults(since: int) -> list:
    if not LOG.exists():
        return []
    with LOG.open("rb") as f:
        f.seek(since if LOG.stat().st_size >= since else 0)
        text = f.read().decode("utf-8", errors="replace")
    return [ln.strip()[:200] for ln in text.splitlines() if any(k in ln for k in FAULTS)]


def send(script: str, label: str) -> str:
    hits = banned(script)
    if hits:
        raise SystemExit(f"{label}: banned words for python_run: {hits}")
    from apply_look import python_run  # noqa: E402  (refuses while PIE runs)
    since = log_size()
    ok, out, err = python_run(script)
    print(f"--- {label}: {'ok' if ok else 'FAILED'}")
    if out.strip():
        print(out.rstrip())
    faults = new_faults(since)
    if faults:
        print("EDITOR FAULT in the log after this call; stop every editor call and ask for a restart:")
        for ln in faults[-5:]:
            print("   ", ln)
        raise SystemExit(6)
    if not ok:
        print(err, file=sys.stderr)
        raise SystemExit(1)
    if "STOP:" in out:
        raise SystemExit(3)
    return out


def run_dir(d: Path) -> int:
    files = sorted(d.glob("*.py"))
    if not files:
        raise SystemExit(f"no chunks in {d}")
    for f in files:
        send(f.read_text(encoding="utf-8"), f"{d.name}/{f.name}")
    print("ALL_OK", d.name, len(files), "chunks")
    return 0


PIE_START = ("Creating play world package", "Repeating last play command", "Play in editor total start")


def watch(out: Path, cmd: list[str]) -> int:
    """Run a long editor job (a bpgraph build) under a per-second log watchdog: the user pressing Play or an editor
    fault kills it at once (memory bpgraph-limits-use-cpp: a build kept sending nodes through PIE for 7 minutes).
    stdout goes to `out`, stderr to `out`.err. Exit 99 when the watchdog fired."""
    import subprocess
    import time as _t
    from apply_look import pie_running  # noqa: E402
    if pie_running():
        raise SystemExit("PIE is running: not starting")
    pos = log_size()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as so, Path(str(out) + ".err").open("w", encoding="utf-8") as se:
        p = subprocess.Popen(cmd, stdout=so, stderr=se, cwd=str(ROOT), shell=(os.name == "nt"))
        while p.poll() is None:
            _t.sleep(1.0)
            size = log_size()
            if size < pos:
                pos = 0
            with LOG.open("rb") as f:
                f.seek(pos)
                new = f.read().decode("utf-8", errors="replace")
            pos = size
            hit = [k for k in PIE_START + FAULTS if k in new]
            if hit:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
                print("WATCHDOG KILLED:", hit)
                return 99
    print("exit", p.returncode, "- report in", out)
    return p.returncode


def read_only(path: Path) -> bool:
    return path.exists() and not os.access(path, os.W_OK)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "watch":
        if "--" not in argv or len(argv) < 4:
            raise SystemExit("usage: ending_editor.py watch OUT.json -- <command ...>")
        i = argv.index("--")
        return watch(ROOT / argv[1], argv[i + 1:])
    args = [a for a in argv if not a.startswith("--")]
    flags = [a for a in argv if a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    step = args[0]
    opts = {"save_beacon": "--save-beacon" in flags}
    for fl in flags:
        if fl.startswith("--at="):
            opts["at"] = fl.split("=", 1)[1]
        if fl.startswith("--plate-at="):
            opts["plate_at"] = [float(v) for v in fl.split("=", 1)[1].split(",")]
    if "--at" in argv:
        opts["at"] = argv[argv.index("--at") + 1]
        args = [a for a in args if a != opts["at"]]
    if step == "run-dir":
        return run_dir(ROOT / args[1] if not Path(args[1]).is_absolute() else Path(args[1]))
    if step == "run-file":
        f = ROOT / args[1] if not Path(args[1]).is_absolute() else Path(args[1])
        send(f.read_text(encoding="utf-8"), f.name)
        return 0
    if step == "story-save" and read_only(STORY_FILE):
        raise SystemExit(f"{STORY_FILE} is read-only (committed, LFS lockable): make it writable first (attrib -r), then rerun")
    script = chunk(step, opts)
    if "--print" in flags:
        print(script)
        return 0
    send(script, step)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
