"""Grounded Tripo relay hut for the High Voice summit.

The modular V10 hut is an offline plan, not a saved level set. This small site
places the imported stone shell and radio desk on the same shelf, with a single
level flagstone plinth. It leaves the mast, ending actor, and its hooks alone.

    python Tools/World/story_sets/summit_tripo.py plan
    python Tools/World/story_sets/summit_tripo.py editor load --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor survey --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py preflight --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor place --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py level --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor settle --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor material --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py light --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor check2 --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor capture --views walk_far,walk_near,front,rear,left,right,floor --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor save --owner LANE_SUMMIT
    python Tools/World/story_sets/summit_tripo.py editor unload --owner LANE_SUMMIT

Run visual review before save. Never run the old V10/S26 modular editor placement
after this site, since those recipes describe a different hut shell.
"""

import copy
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
WORLD = os.path.join(ROOT, 'Tools', 'World')
sys.path.insert(0, WORLD)
sys.path.insert(0, os.path.join(ROOT, 'Tools', 'Story'))
import build_road_profile as brp  # noqa: E402
import place_setdress as sd  # noqa: E402
import setdress_catalog as catalog  # noqa: E402

SITE = 'S26_HighVoiceTripo'
OUT = os.path.join(HERE, 'S26_Tripo.json')
V10 = os.path.join(HERE, 'V10.json')
BOUNDS = os.path.join(ROOT, 'Saved', 'Tripo', 'imported_bounds.json')
C = (297254.0, 483334.0)
YAW = 198.66
# The imported hut's open doorway faces local +X. Turn that face toward the
# station frame's +Y, leaving the walkway/camera frame fixed.
TRIPO_FRONT_OFFSET_DEG = 90.0
SHELL_SCALE = 0.75
PLINTH_SCALE = 1.5
PLINTH_XY_CM = (310.0 * PLINTH_SCALE, 307.0 * PLINTH_SCALE)
TRIPO = '/Game/SaskartaGaea/Environment/Tripo02/SM_T2_'
CAT = catalog.load()
TERRAIN = brp.Terrain(brp.HEIGHTMAP)


def world_xy(x_cm, y_cm):
    a = math.radians(YAW)
    return (round(C[0] + x_cm * math.cos(a) - y_cm * math.sin(a), 1),
            round(C[1] + x_cm * math.sin(a) + y_cm * math.cos(a), 1))


def ground(x_cm, y_cm):
    return float(TERRAIN.height(x_cm, y_cm) * 100.0)


def footprint_ground(half_x_cm, half_y_cm, steps=7):
    z = []
    for i in range(steps):
        for j in range(steps):
            x = -half_x_cm + 2 * half_x_cm * i / (steps - 1)
            y = -half_y_cm + 2 * half_y_cm * j / (steps - 1)
            z.append(ground(*world_xy(x, y)))
    return min(z), max(z)


def imported_size(mesh, scale, bounds):
    src = bounds[TRIPO + mesh]['size_cm']
    return [round(float(v) * scale / 100.0, 4) for v in src]


def placement(template, idx, key, asset, local_xy, scale, size_m, group,
              contact='rest', mode='physics', sink_cm=0.0, collision=True):
    x, y = world_xy(*local_xy)
    row = copy.deepcopy(template)
    row.update(id=f'{SITE}_{idx:03d}', key=key, asset=asset, kind='SM',
               cat='building' if key == 'T2_stone_hut' else 'wall' if idx == 0 else 'prop',
               x_cm=x, y_cm=y, ground_z_cm=round(ground(x, y), 1),
               yaw=YAW + (TRIPO_FRONT_OFFSET_DEG if key.startswith('T2_') else 0.0),
               pitch=0.0, roll=0.0, scale=scale, scale_range=[scale, scale],
               size_m=size_m, group=group, folder=f'Set/{SITE}/{group}',
               ism=False, stack=idx != 0, attach=False, parent=None, run_id=None,
               collision=collision, foliage_exclude=True, draw_distance_cm=75000.0,
               cast_shadow=True, contact=contact, block=None,
               material_set='wood' if key in ('T2_radio_desk', 'AB_Chair_A_low', 'MV_box_03') else 'stone',
               requires_import=True, imported=True, verdict='use', fallback=None,
               settle=dict(mode=mode, sink_cm=sink_cm, max_tilt_deg=0,
                           rand_tilt_deg=0, z_rule='min' if idx == 0 else 'max',
                           drop_cm=0, z_offset_cm=0))
    return row


def make():
    original = json.load(open(V10, encoding='utf8'))
    src = original['sites'][0]
    bounds = json.load(open(BOUNDS, encoding='utf8'))
    template = src['placements'][0]
    low, high = footprint_ground(PLINTH_XY_CM[0] / 2, PLINTH_XY_CM[1] / 2)
    plinth_h_cm = high - low + 6.0
    # Six centimetres at the door is a worn threshold, not a floating shelf.
    door_xy = world_xy(-25.0, 178.35)
    door_ground = ground(*door_xy)
    slab_top = high + 3.0
    assert 2.0 <= slab_top - door_ground <= 12.0, (slab_top, door_ground)
    assert plinth_h_cm < 65.0, plinth_h_cm
    items = [
        placement(template, 0, 'B01_floor01', CAT['B01_floor01']['path'], (0, 0), PLINTH_SCALE,
                  [4.65, 4.605, round(plinth_h_cm / 100.0, 4)], 'foundation',
                  contact='rigid', mode='none'),
        placement(template, 1, 'T2_stone_hut', TRIPO + 'stone_hut', (0, 0), SHELL_SCALE,
                  imported_size('stone_hut', SHELL_SCALE, bounds), 'shell', sink_cm=3.0,
                  collision=False),
        # The imported desk already includes the microphone, radio and papers.
        placement(template, 2, 'T2_radio_desk', TRIPO + 'radio_desk', (10, -88), 0.60,
                  imported_size('radio_desk', 0.60, bounds), 'interior'),
        placement(template, 3, 'AB_Chair_A_low', CAT['AB_Chair_A_low']['path'], (109, -18), 1.0,
                  [v / 100.0 for v in CAT['AB_Chair_A_low']['size_cm']], 'interior'),
        placement(template, 4, 'MV_box_03', CAT['MV_box_03']['path'], (148, -118), 1.0,
                  [v / 100.0 for v in CAT['MV_box_03']['size_cm']], 'interior'),
        placement(template, 5, 'AB_Clay_Pot_B', CAT['AB_Clay_Pot_B']['path'], (-155, -105), 1.0,
                  [v / 100.0 for v in CAT['AB_Clay_Pot_B']['size_cm']], 'interior'),
    ]
    # The end shot's walking line must be empty: no actor in the doorway or the
    # five-to-seven-metre exterior corridor heading toward the valley.
    door = [door_xy[0], door_xy[1], round(slab_top, 1)]
    front = world_xy(-25, 178.35 + 300)
    floor = [front[0], front[1], round(ground(*front) + 55, 1)]
    focus = [door[0], door[1], door[2] + 120]
    site = copy.deepcopy(src)
    site.update(id=SITE, name='High Voice Tripo relay hut and room', centre_cm=list(C),
                radius_m=24.0, placements=items, ground=[],
                story_owned=['summit relay station: ending agent owns plate, mast and cameras'],
                story='A coherent kept relay hut and its operator desk; the older man enters and emerges while the drone rests outside.',
                notes='Supersedes the offline V10 modular shell and S26 furniture plan. Do not place those recipes.',
                counts=dict(placements=len(items), actors=len(items), ism_instances=0, decals=0, lines=0),
                views=[
                    dict(name='walk_far', cam_cm=[297789.5, 480801.2, 11463.8], look_cm=focus),
                    dict(name='walk_near', cam_cm=[297540.0, 482310.0, round(ground(297540, 482310) + 170, 1)], look_cm=focus),
                    dict(name='front', cam_cm=[floor[0], floor[1], floor[2] + 140], look_cm=focus),
                    dict(name='rear', cam_cm=[296850.0, 483650.0, round(ground(296850, 483650) + 190, 1)], look_cm=[*C, slab_top + 130]),
                    dict(name='left', cam_cm=[297010.0, 482800.0, round(ground(297010, 482800) + 170, 1)], look_cm=[*C, slab_top + 130]),
                    dict(name='right', cam_cm=[297540.0, 483750.0, round(ground(297540, 483750) + 170, 1)], look_cm=[*C, slab_top + 130]),
                    dict(name='floor', cam_cm=floor, look_cm=[door[0], door[1], door[2] + 105]),
                ], waivers=[])
    doc = dict(generated_by='Tools/World/story_sets/summit_tripo.py', level='/Game/level/Saskarta_WP',
               anchor=dict(hut_centre_cm=list(C), site_yaw=YAW,
                           hut_yaw=(YAW + TRIPO_FRONT_OFFSET_DEG) % 360, scale=SHELL_SCALE,
                           doorway_cm=door, outward_yaw=(YAW + 90) % 360,
                           floor_camera_cm=floor, plinth_top_cm=round(slab_top, 1),
                           plinth_bottom_cm=round(low - 3.0, 1),
                           plinth_height_cm=round(plinth_h_cm, 1)), sites=[site])
    return doc


PREFLIGHT = r'''
if world.get_path_name().split('.')[0] != '/Game/level/Saskarta_WP':
    raise RuntimeError('Wrong level for summit work')
if not eal.does_asset_exist(HUT) or not eal.does_asset_exist(DESK):
    raise RuntimeError('The imported Tripo summit assets are missing')
old = [a.get_actor_label() for a in eas.get_all_level_actors()
       if a.get_actor_label().startswith('SD_V10_HighVoice_02') or
       a.get_actor_label().startswith('SD_S26_HighVoiceHut_')]
if old:
    raise RuntimeError('The modular hut already exists: ' + str(old[:12]))
print('SUMMIT_PREFLIGHT level and assets OK, old modular hut absent')
'''


LEVEL = r'''
matches = [a for a in eas.get_all_level_actors() if a.get_actor_label() == LABEL]
if len(matches) != 1:
    raise RuntimeError('Expected one flagstone foundation, got ' + str(len(matches)))
a = matches[0]
b = a.static_mesh_component.static_mesh.get_bounds()
sx = float(a.get_actor_scale3d().x)
sy = float(a.get_actor_scale3d().y)
if abs(sx - SCALE) > 0.01 or abs(sy - SCALE) > 0.01:
    raise RuntimeError('Foundation XY scale changed')
samples = []
for fx in (-1.0, -0.66, -0.33, 0.0, 0.33, 0.66, 1.0):
    for fy in (-1.0, -0.66, -0.33, 0.0, 0.33, 0.66, 1.0):
        q = apply(axes(YAW, 0.0, 0.0),
                  ((b.origin.x + fx * b.box_extent.x) * sx,
                   (b.origin.y + fy * b.box_extent.y) * sy, 0.0))
        h = trace_ground(C[0] + q[0], C[1] + q[1], 12000.0, 9000.0, [a])
        if h is None:
            raise RuntimeError('Missing summit landscape contact')
        samples.append(h[0])
lo, hi = min(samples), max(samples)
height = hi - lo + 6.0
sz = height / (2.0 * b.box_extent.z)
a.set_actor_scale3d(V(sx, sy, sz))
bottom_local = (b.origin.z - b.box_extent.z) * sz
loc = a.get_actor_location()
a.set_actor_location(V(loc.x, loc.y, lo - 3.0 - bottom_local), False, True)
print('SUMMIT_LEVEL bottom=' + str(round(lo - 3.0, 1)) +
      ' top=' + str(round(hi + 3.0, 1)) + ' relief=' + str(round(hi - lo, 1)) +
      ' scale_z=' + str(round(sz, 3)) + ' DONE')
'''

PACKAGES = r'''
actors = [a for a in eas.get_all_level_actors()
          if 'SD_' + SITE in [str(t) for t in a.tags]]
for a in sorted(actors, key=lambda x: x.get_actor_label()):
    print('SUMMIT_PACKAGE ' + a.get_actor_label() + ' ' + a.get_package().get_name())
print('SUMMIT_PACKAGES ' + str(len(actors)) + ' DONE')
'''

DIAG = r'''
for a in eas.get_all_level_actors():
    if a.get_actor_label() in ('FL_HutLamp_Light', 'FL_HutLamp_Flame'):
        l = a.get_actor_location()
        print('SUMMIT_DIAG', a.get_actor_label(), round(l.x, 1), round(l.y, 1), round(l.z, 1))
for name, xy in [('door', DOOR[:2]), ('rest', REST[:2]), ('plate', PLATE[:2]), ('stand', STAND[:2])]:
    h = trace_ground(xy[0], xy[1], 12000.0, 9000.0, [])
    print('SUMMIT_GROUND', name, round(h[0], 1) if h else None)
'''

LIGHT = r'''
label = 'SD_' + SITE + '_Light'
old = [a for a in eas.get_all_level_actors() if a.get_actor_label() == label]
if len(old) > 1:
    raise RuntimeError('Duplicate summit fill lights')
a = old[0] if old else eas.spawn_actor_from_class(unreal.PointLight, V(POS[0], POS[1], POS[2]))
a.set_actor_label(label)
a.set_actor_location(V(POS[0], POS[1], POS[2]), False, True)
a.tags = [unreal.Name('SD_' + SITE)]
a.set_folder_path('Set/' + SITE + '/light')
a.set_editor_property('is_spatially_loaded', False)
c = a.point_light_component
c.set_editor_property('intensity_units', unreal.LightUnits.CANDELAS)
c.set_intensity(5.0)
c.set_light_color(unreal.LinearColor(1.0, 0.66, 0.37, 1.0))
c.set_attenuation_radius(650.0)
c.set_cast_shadows(False)
print('SUMMIT_LIGHT ' + label + ' at ' + str(POS) + ' DONE')
'''

SURFACE = r'''
found = [a for a in eas.get_all_level_actors() if a.get_actor_label() == 'SD_' + SITE + '_001']
if len(found) != 1:
    raise RuntimeError('Load the saved summit hut actor before changing its surface')
a = found[0]
c = a.static_mesh_component
a.modify()
c.modify()
original = eal.load_asset(BASE)
if original is None:
    raise RuntimeError('Imported Tripo hut material missing')
if RESTORE:
    c.set_material(0, original)
    for i, value in ((4, 0.45), (5, 0.96), (6, 0.92), (7, 0.88)):
        c.set_default_custom_primitive_data_float(i, value)
    print('SUMMIT_SURFACE original restored')
else:
    mi = eal.load_asset(VARIANT)
    if mi is None:
        mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            'MI_T2_stone_hut_S26', '/Game/SaskartaGaea/Environment/Tripo02/Materials',
            unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    mel = unreal.MaterialEditingLibrary
    mel.set_material_instance_parent(mi, original)
    for name, value in (('SD_PaletteMatch', 0.12), ('SD_BaseStrength', 0.18)):
        ok = mel.set_material_instance_scalar_parameter_value(mi, name, value)
        print('SUMMIT_SURFACE_PARAMETER', name, value, ok)
    mel.update_material_instance(mi)
    c.set_material(0, mi)
    for i, value in ((4, 0.10), (5, 1.0), (6, 1.0), (7, 1.0)):
        c.set_default_custom_primitive_data_float(i, value)
    print('SUMMIT_SURFACE variant assigned', mi.get_path_name())
'''

SURFACE_SAVE = r'''
found = [a for a in eas.get_all_level_actors() if a.get_actor_label() == 'SD_' + SITE + '_001']
if len(found) != 1:
    raise RuntimeError('Summit hut actor not loaded')
a = found[0]
mi = eal.load_asset(VARIANT)
if mi is None or a.static_mesh_component.get_material(0) != mi:
    raise RuntimeError('Summit material variant not assigned')
print('SUMMIT_SURFACE_SAVE', eal.save_loaded_asset(mi, False),
      unreal.EditorLoadingAndSavingUtils.save_packages([a.get_package()], True),
      a.get_package().get_name(), mi.get_path_name())
'''


def editor_step(step, argv):
    sd.SITES_V2_JSON = OUT
    sd.OVERHEAD_KEYS.add('T2_stone_hut')
    if step in ('preflight', 'level', 'packages', 'diag', 'light', 'surface', 'surface-restore', 'surface-save'):
        import argparse
        ap = argparse.ArgumentParser()
        ap.add_argument('--owner', default='')
        ap.add_argument('--dry-run', action='store_true')
        ap.add_argument('--no-gate-check', action='store_true')
        ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
        args = ap.parse_args(argv)
        if step != 'packages':
            sd.gate_check(args, 'place')
        r = sd.Runner(args)
        if step == 'preflight':
            r.send('S26_Tripo_preflight', sd.build_script(PREFLIGHT,
                   HUT=TRIPO + 'stone_hut', DESK=TRIPO + 'radio_desk'))
        elif step == 'level':
            r.send('S26_Tripo_level', sd.build_script(LEVEL, LABEL='SD_' + SITE + '_000',
                   C=list(C), YAW=YAW, SCALE=PLINTH_SCALE))
        elif step == 'diag':
            door = make()['anchor']['doorway_cm']
            rest = make()['anchor']['floor_camera_cm']
            plate = [*world_xy(120, 178.35), door[2] + 130]
            stand = [*world_xy(120, 254), ground(*world_xy(120, 254))]
            r.send('S26_Tripo_diag', sd.build_script(DIAG, DOOR=door, REST=rest, PLATE=plate, STAND=stand))
        elif step == 'light':
            pos = [*world_xy(-190, 300), round(make()['anchor']['plinth_top_cm'] + 250, 1)]
            r.send('S26_Tripo_light', sd.build_script(LIGHT, SITE=SITE, POS=pos))
        elif step in ('surface', 'surface-restore'):
            r.send('S26_Tripo_surface', sd.build_script(SURFACE, SITE=SITE,
                   BASE=TRIPO.replace('/SM_T2_', '/Materials/MI_T2_') + 'stone_hut',
                   VARIANT='/Game/SaskartaGaea/Environment/Tripo02/Materials/MI_T2_stone_hut_S26',
                   RESTORE=step == 'surface-restore'))
        elif step == 'surface-save':
            r.send('S26_Tripo_surface_save', sd.build_script(SURFACE_SAVE, SITE=SITE,
                   VARIANT='/Game/SaskartaGaea/Environment/Tripo02/Materials/MI_T2_stone_hut_S26'))
        else:
            r.send('S26_Tripo_packages', sd.build_script(PACKAGES, SITE=SITE))
        return
    sys.argv = ['place_setdress.py', step, SITE, *argv]
    if '--v2' not in sys.argv:
        sys.argv.append('--v2')
    sd.main()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'capture-audit':
        from PIL import Image, ImageChops, ImageStat
        directory = os.path.join(ROOT, 'Saved', 'Screenshots', 'SetDressV2', SITE)
        names = ('walk_far', 'walk_near', 'front', 'rear', 'left', 'right', 'floor')
        shots = []
        for name in names:
            path = os.path.join(directory, name + '.png')
            data = open(path, 'rb').read()
            shot = Image.open(path).convert('RGB').resize((160, 90))
            sdv = max(ImageStat.Stat(shot).stddev)
            assert sdv > 8.0, (name, 'blank or stale render', sdv)
            shots.append((name, hashlib.sha256(data).hexdigest(), shot))
        assert len({h for _, h, _ in shots}) == len(shots), 'identical captures: check live camera updates'
        for i in range(len(shots)):
            for j in range(i + 1, len(shots)):
                delta = ImageStat.Stat(ImageChops.difference(shots[i][2], shots[j][2])).mean
                assert max(delta) > 4.0, (shots[i][0], shots[j][0], 'near-identical captures')
        print('SUMMIT_CAPTURES 7 distinct rendered viewpoints')
        return
    if len(sys.argv) > 1 and sys.argv[1] in ('editor', 'preflight', 'level', 'packages', 'diag', 'light',
                                             'surface', 'surface-restore', 'surface-save'):
        action = sys.argv[2] if sys.argv[1] == 'editor' else sys.argv[1]
        rest = sys.argv[3:] if sys.argv[1] == 'editor' else sys.argv[2:]
        editor_step(action, rest)
        return
    doc = make()
    with open(OUT, 'w', encoding='utf8') as fh:
        json.dump(doc, fh, indent=1)
        fh.write('\n')
    a = doc['anchor']
    print('SUMMIT_PLAN hut', a['hut_centre_cm'], 'yaw', a['hut_yaw'],
          'door', a['doorway_cm'], 'plinth', a['plinth_bottom_cm'], a['plinth_top_cm'],
          'actors', len(doc['sites'][0]['placements']))


if __name__ == '__main__':
    main()
