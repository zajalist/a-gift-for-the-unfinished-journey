"""Place the First Light road marks: wrecks 01-06, the depot mouth, grates G0-G4 (storyline-first-light.md 4.3-4.4).

Data: Tools/World/first_light_marks.json (python Tools/GameFlow/gen_first_light_road.py writes it). Runs on the host and
sends small python_run scripts to Hayba through place_setdress's transport and prelude (banned-text check, <= 3 items
a call so each call stays well inside the 5 s deadline). Never saves in the same call as an edit; never starts PIE.

    python Tools/World/place_first_light_marks.py plan                      # offline: what goes where
    python Tools/World/place_first_light_marks.py script place WRECK_01     # print the editor script, send nothing
    python Tools/World/place_first_light_marks.py place <ids|wrecks|grates|mouth|all> --owner OWNER
    python Tools/World/place_first_light_marks.py status
    python Tools/World/place_first_light_marks.py save --owner OWNER        # the placed actors' packages, 20 a call
    python Tools/World/place_first_light_marks.py clear <ids|...> --owner OWNER --yes
    python Tools/World/place_first_light_marks.py load <id> --owner OWNER      # WP actors in a box round one mark
    python Tools/World/place_first_light_marks.py capture <ids> --owner OWNER  # -> Saved/Screenshots/FirstLight/<id>.png
    python Tools/World/place_first_light_marks.py unload <id> --owner OWNER

Load the WP cells around a mark first (place_setdress.py's load step, or the editor), then place, look, save.
Actors go to the outliner folder Set/FirstLight/<id>, tagged FL_MARK and the id. Wrecks are SK_Carrier frozen on the
last frame of A_Carrier_Shutdown (no tick), sunk by silt, numbered by a decal (T_FL_Stencil_NN, see gen_lid_notes.py
--stencils). Grates are a SM_B01_floor01 lip with a MI_SquareGrid plate flush to the ground and an
EasyAtmos_HangingDust above (the 7 s breath is a follow-up Niagara user parameter; the preset is continuous).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import place_setdress as psd  # noqa: E402

MARKS = os.path.join(HERE, 'first_light_marks.json')
PER_CALL = 3
FOLDER = 'Set/FirstLight/'

BODY_PLACE = r'''
out = []
for it in ITEMS:
    lbl = 'FL_' + it['id']
    for a in eas.get_all_level_actors():
        if a.get_actor_label().startswith(lbl + '_'):
            eas.destroy_actor(a)
    x, y, z = it['loc_cm']
    g = trace_ground(x, y, z + 2000.0, z - 3000.0, [])
    gz = g[0] if g is not None else z
    made = []
    low = [0.0]
    def put(path, name, dx, dy, dz, yaw_add=0.0, scale=(1.0, 1.0, 1.0), pitch=0.0, ext=(0.0, 0.0), align=False):
        asset = eal.load_asset(path)
        if asset is None:
            out.append('MISSING ' + path)
            return None
        yaw = it['yaw'] + yaw_add
        c = math.cos(math.radians(it['yaw']))
        s = math.sin(math.radians(it['yaw']))
        px, py = x + dx * c - dy * s, y + dx * s + dy * c
        # contact: the lowest landscape point under the piece's centre and footprint corners, so no edge floats
        cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        zs = []
        for (ex, ey) in ((0.0, 0.0), (ext[0], ext[1]), (ext[0], -ext[1]), (-ext[0], ext[1]), (-ext[0], -ext[1])):
            h = trace_ground(px + ex * cy - ey * sy, py + ex * sy + ey * cy, gz + 3000.0, gz - 3000.0, [])
            if h is not None:
                zs.append(h[0])
        pz = min(zs) if len(zs) > 0 else gz
        roll = 0.0
        if align and len(zs) == 5:
            # flush pieces (grate lip and plate) follow the slope: tilt to the corner samples, sit at their mean
            pitch = math.degrees(math.atan2(((zs[1] + zs[2]) - (zs[3] + zs[4])) * 0.5, 2.0 * ext[0]))
            roll = -math.degrees(math.atan2(((zs[1] + zs[3]) - (zs[2] + zs[4])) * 0.5, 2.0 * ext[1]))
            pz = sum(zs[1:]) / 4.0
        else:
            low[0] = max(low[0], (max(zs) - pz) if len(zs) > 0 else 0.0)
        loc = V(px, py, pz + dz)
        a = eas.spawn_actor_from_object(asset, loc, unreal.Rotator(roll, pitch, yaw))
        a.set_actor_label(lbl + '_' + name)
        a.set_folder_path(FOLDER + it['id'])
        a.set_actor_scale3d(V(scale[0], scale[1], scale[2]))
        a.tags = [unreal.Name('FL_MARK'), unreal.Name(it['id'])]
        made.append(a)
        return a
    kind = it['kind']
    if kind == 'wreck':
        a = put(ASSETS['wreck_mesh'], 'husk', 0.0, 0.0, -it['sink_cm'])
        if a is not None:
            comp = a.skeletal_mesh_component
            anim = eal.load_asset(ASSETS['wreck_pose'])
            if anim is not None:
                comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
                comp.override_animation_data(anim, False, False, anim.get_play_length(), 0.0)
            comp.set_editor_property('visibility_based_anim_tick_option', unreal.VisibilityBasedAnimTickOption.ONLY_TICK_POSE_WHEN_RENDERED)
            comp.set_editor_property('ld_max_draw_distance', float(CULL['wreck']))
            comp.set_editor_property('cast_shadow', True)
            mi = eal.load_asset(ASSETS['stencil_mi'] + it['stencil'])
            if mi is not None:
                # the number on the husk's right flank: the decal projects along its X, into the side
                c = math.cos(math.radians(it['yaw']))
                s = math.sin(math.radians(it['yaw']))
                d = eas.spawn_actor_from_class(unreal.DecalActor, V(x - 95.0 * s, y + 95.0 * c, a.get_actor_location().z + 60.0),
                                               unreal.Rotator(0.0, 0.0, it['yaw'] - 90.0))
                d.set_actor_label(lbl + '_stencil')
                d.set_folder_path(FOLDER + it['id'])
                d.tags = [unreal.Name('FL_MARK'), unreal.Name(it['id'])]
                dc = d.decal
                dc.set_decal_material(mi)
                dc.set_editor_property('decal_size', V(40.0, 30.0, 30.0))
                dc.set_editor_property('fade_screen_size', 0.002)
                made.append(d)
    elif kind == 'grate':
        f = put(ASSETS['grate_frame'], 'lip', 0.0, 0.0, -8.0, scale=(0.9, 0.6, 0.15), ext=(137.0, 91.0), align=True)
        p = put(ASSETS['grate_plate'], 'plate', 0.0, 0.0, 1.5, scale=(1.2, 0.8, 1.0), ext=(60.0, 40.0), align=True)
        if p is not None:
            p.static_mesh_component.set_material(0, eal.load_asset(ASSETS['grate_material']))
        # EasyAtmos_HangingDust is a preset data asset: BP_EasyAtmos draws it (its construction script reads Preset)
        d = put(ASSETS['dust_bp'], 'breath', 0.0, 0.0, 40.0)
        if d is not None:
            d.set_editor_property('Preset', eal.load_asset(ASSETS['dust']))
        for m in (f, p):
            if m is not None:
                m.static_mesh_component.set_editor_property('ld_max_draw_distance', float(CULL['grate']))
    elif kind == 'mouth':
        # arch01's pivot is its centre (163 cm half height): lift it by that x scale; wall01 and the cradle sit on theirs
        put(ASSETS['mouth_arch'], 'arch', 0.0, 0.0, 163.0 * 1.6 - 10.0, 90.0, scale=(1.6, 1.6, 1.6), ext=(395.0, 74.0))
        put(ASSETS['mouth_wall'], 'wall_l', 0.0, -520.0, -10.0, 90.0, ext=(199.0, 25.0))
        put(ASSETS['mouth_wall'], 'wall_r', 0.0, 520.0, -10.0, 90.0, ext=(199.0, 25.0))
        for b in range(it['bays']):
            put(ASSETS['bay_cradle'], 'bay%02d' % (b + 1), -900.0 - 260.0 * (b // 2), -180.0 + 360.0 * (b % 2), -5.0, 90.0,
                ext=(160.0, 98.0))
        put(ASSETS['tow_track'], 'tow', 900.0, 0.0, 12.0, ext=(152.0, 73.0))
    out.append('PLACED %s ground=%s z=%.0f actors=%d max_slope_sink=%.0fcm' % (it['id'], 'landscape' if g else 'none', gz,
                                                                              len(made), low[0]))
print('\n'.join(out))
'''

BODY_GROUND = r'''
zs = []
for (gx, gy) in XY:
    g = trace_ground(gx, gy, Z + 5000.0, Z - 5000.0, [])
    zs.append(str(round(g[0], 1)) if g is not None else str(Z))
print('GROUND ' + ' '.join(zs))
'''

BODY_STATUS = r'''
n = {}
for a in eas.get_all_level_actors():
    if 'FL_MARK' in [str(t) for t in a.tags]:
        k = str(a.tags[1]) if len(a.tags) > 1 else '?'
        n[k] = n.get(k, 0) + 1
print('STATUS ' + ' '.join('%s=%d' % kv for kv in sorted(n.items())))
'''

BODY_SAVE = r'''
have = [a for a in eas.get_all_level_actors() if 'FL_MARK' in [str(t) for t in a.tags]]
chunk = have[FROM:FROM + 20]
pkgs = [a.get_package() for a in chunk]
ok = unreal.EditorLoadingAndSavingUtils.save_packages(pkgs, True) if len(pkgs) > 0 else True
print('SAVED %d of %d ok=%s' % (len(pkgs), len(have), ok))
'''

BODY_CLEAR = r'''
gone = 0
for a in eas.get_all_level_actors():
    tg = [str(t) for t in a.tags]
    if 'FL_MARK' in tg and len(tg) > 1 and tg[1] in IDS:
        eas.destroy_actor(a)
        gone += 1
print('CLEARED %d' % gone)
'''


def load():
    with open(MARKS, encoding='utf-8') as f:
        return json.load(f)


def pick(doc, names):
    items = doc['items']
    if not names or names == ['all']:
        return items
    out = []
    for n in names:
        kinds = {'wrecks': 'wreck', 'grates': 'grate', 'mouth': 'mouth'}
        out += [i for i in items if i['kind'] == kinds.get(n) or i['id'] == n]
    return out


def scripts(step, doc, items):
    common = {'ASSETS': doc['assets'], 'CULL': doc['cull_distance_cm'], 'FOLDER': FOLDER}
    if step == 'place':
        return [psd.validate(psd.build_script(BODY_PLACE, ITEMS=items[i:i + PER_CALL], **common))
                for i in range(0, len(items), PER_CALL)]
    if step == 'status':
        return [psd.validate(psd.build_script(BODY_STATUS))]
    if step == 'save':
        return [psd.validate(psd.build_script(BODY_SAVE, FROM=i)) for i in range(0, 40, 20)]
    if step == 'clear':
        return [psd.validate(psd.build_script(BODY_CLEAR, IDS=[i['id'] for i in items]))]
    raise SystemExit('unknown step ' + step)


LOAD_HALF_CM = {'wreck': 6000.0, 'grate': 5000.0, 'mouth': 6000.0}
STATE_DIR = os.path.join(psd.ROOT, 'Saved', 'FirstLight')
# capture framing per kind: back along the road and to the side (cm, road frame), height above the mark, FOV
VIEW = {'wreck': (-650.0, 650.0, 320.0, 55.0), 'grate': (-300.0, 150.0, 200.0, 55.0), 'mouth': (2200.0, 1400.0, 1100.0, 60.0)}


def box_of(it):
    h = LOAD_HALF_CM[it['kind']]
    x, y = it['loc_cm'][0], it['loc_cm'][1]
    return [x - h, y - h, x + h, y + h]


def state_path(it):
    return os.path.join(STATE_DIR, 'loaded_%s.json' % it['id'])


def wp_load(h, it):
    loaded = []
    for _ in range(10):
        out = h.run(psd.validate(psd.build_script(psd.LOAD_BODY, BOX=box_of(it), ALREADY=loaded, LIMIT=20,
                                                  MAX_LAND=psd.MAX_LANDSCAPE_PROXIES, CLASS_FIELD='native_class')))
        r = out.get('result', out)
        std = r.get('data', {}).get('stdout', '') if isinstance(r, dict) else ''
        print((std or str(r))[-200:])
        for line in std.splitlines():
            if line.startswith('LOADED '):
                loaded = list(dict.fromkeys(loaded + json.loads(line[7:])))
        if ' DONE' in std or not std:
            break
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(it), 'w', encoding='utf-8') as f:
        json.dump(loaded, f)
    print('loaded %d actors for %s' % (len(loaded), it['id']))


def wp_unload(h, it):
    want = json.load(open(state_path(it), encoding='utf-8')) if os.path.exists(state_path(it)) else []
    for i in range(0, len(want), 20):
        print(str(h.run(psd.validate(psd.build_script(psd.UNLOAD_BODY, BOX=box_of(it), WANT=want[i:i + 20]))))[:200])
    if os.path.exists(state_path(it)):
        os.remove(state_path(it))


def capture(it, flip=False):
    sys.path.insert(0, os.path.join(psd.ROOT, 'Tools', 'Look'))
    import capture_look
    bx, sd, up, fov = VIEW[it['kind']]
    if flip:
        # the other side, higher: for a mark whose first view is blocked by a bank or fog
        bx, sd, up = -bx, -sd, up * 2.0
    x, y, z = it['loc_cm']
    c, s = math.cos(math.radians(it['yaw'])), math.sin(math.radians(it['yaw']))
    cam = [x + bx * c - sd * s, y + bx * s + sd * c, z + up]
    # the camera stands `up` above the ground under it (a slope can put the mark's z inside the hill)
    h = psd.Hayba(int(os.environ.get('HAYBA_PORT', 52342)))
    h.connect()
    r = h.run(psd.validate(psd.build_script(BODY_GROUND, XY=[[cam[0], cam[1]], [x, y]], Z=z)))
    r = r.get('result', r)
    zs = [float(v) for v in r.get('data', {}).get('stdout', '').split()[1:]]
    if len(zs) == 2:
        cam[2] = zs[0] + up
        z = zs[1]
    look = [x, y, z + (250.0 if it['kind'] == 'mouth' else 60.0)]
    label = 'FL_CAPTURE_' + it['id']
    setup = psd.validate(psd.build_script(psd.CAPTURE_SHOOT_BODY, CAM=cam, LOOK=look, LABEL=label, SIZE=[1600, 900], FOV=fov))
    export = psd.validate(psd.build_script(psd.CAPTURE_EXPORT_BODY, LABEL=label, NAME=it['id'], OUT_REL='Screenshots/FirstLight'))
    ok, out, err = capture_look.run_capture_scripts(setup, capture_look.PUMP_SCRIPT.replace('__LABEL__', label), export,
                                                    psd.CAPTURE_SETTLE_S, True, capture_label=label)
    print(out[-300:])
    if not ok:
        raise SystemExit(err or 'capture failed')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('step', choices=['plan', 'script', 'place', 'status', 'save', 'clear', 'load', 'unload', 'capture'])
    ap.add_argument('names', nargs='*')
    ap.add_argument('--owner', default='')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--flip', action='store_true', help='capture: view from the other side, higher')
    ap.add_argument('--port', type=int, default=int(os.environ.get('HAYBA_PORT', 52342)))
    args = ap.parse_args(argv)
    doc = load()
    if args.step == 'plan':
        for i in doc['items']:
            print('%-12s %-6s road %6s m  lat %5s  silt %4s  %s' % (i['id'], i['kind'], i['road_m'], i.get('lateral_m', ''),
                                                                   i.get('silt', ''), i['where']))
        return 0
    if args.step == 'script':
        sub = args.names[0] if args.names else 'place'
        for s in scripts(sub, doc, pick(doc, args.names[1:])):
            print(s)
        return 0
    if args.step == 'clear' and not args.yes:
        raise SystemExit('clear destroys actors: pass --yes')
    if args.step != 'status':
        ns = argparse.Namespace(owner=args.owner, dry_run=False, no_gate_check=False)
        psd.gate_check(ns, 'place')
    if psd.pie_running():
        raise SystemExit('PIE is running: not sending anything')
    if args.step == 'capture':
        for it in pick(doc, args.names):
            capture(it, args.flip)
        return 0
    h = psd.Hayba(args.port)
    h.connect()
    if args.step in ('load', 'unload'):
        for it in pick(doc, args.names):
            (wp_load if args.step == 'load' else wp_unload)(h, it)
        return 0
    for s in scripts(args.step, doc, pick(doc, args.names)):
        msg = h.run(s)
        r = msg.get('result', msg)
        d = r.get('data', {}) if isinstance(r, dict) else {}
        print((d.get('stdout', '') + d.get('stderr', '')).strip() or json.dumps(r, ensure_ascii=False)[:2000])
    return 0


if __name__ == '__main__':
    sys.exit(main())
