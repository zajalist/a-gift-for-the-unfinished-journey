"""Emit a scoped story-asset patch without importing or editing narrative sources.

    python Tools/Drone/patch_story.py check
    python Tools/Drone/patch_story.py emit

Root backs up DA_Saskarta_Story, installs the drone sequences and voice, and then
runs 10_apply, 20_verify, 90_save separately with no PIE or standalone process.
Only two beats, two cinematics, one line and two additive feature tags are owned.
The runtime owns fall/swarm motion and SFX; the cues own voice and feed switches.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIDECAR = Path(__file__).with_name("story_sidecar.json")


def road_to_ue(road_m, samples):
    pairs = sorted((p["dist_m"], p["ue_spline_distance_m"]) for p in samples)
    for (r0, u0), (r1, u1) in zip(pairs, pairs[1:]):
        if r0 <= road_m <= r1:
            return u0 + (u1 - u0) * (road_m - r0) / (r1 - r0)
    raise ValueError(f"road milestone {road_m} outside profile")


def load_patch():
    data = json.loads(SIDECAR.read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "docs/story/road-profile.json").read_text(encoding="utf-8"))
    for beat in data["beats"].values():
        beat["ue_distance_m"] = round(road_to_ue(beat["road_m"], profile["samples"]), 4)
    return data


def validate(data):
    if set(data["beats"]) != {"OA1_OPTICS_FAIL", "OB1_DRONE"}:
        raise ValueError("patch beat scope changed")
    if set(data["cinematics"]) != {"CIN_A1_OPTICS_FAIL", "CIN_B1_DRONE"}:
        raise ValueError("patch cinematic scope changed")
    if set(data["lines"]) != {"CV_DRONE_02"}:
        raise ValueError("patch line scope changed")
    if data["beats"]["OA1_OPTICS_FAIL"]["road_m"] != 3700 or data["beats"]["OB1_DRONE"]["road_m"] != 3770:
        raise ValueError("patch differs from the shortened blind stretch")
    for cid, cine in data["cinematics"].items():
        times = [cue["at_s"] for cue in cine["cues"]]
        if times != sorted(times) or any(t < 0 or t >= cine["duration_s"] for t in times):
            raise ValueError(f"invalid cue time in {cid}")
        if any(cue["type"] == "PlaySfx" for cue in cine["cues"]):
            raise ValueError("native controller already owns fall and rotor SFX")


HEAD = '''import unreal, re
story = unreal.load_asset(PATCH['asset'])
if story is None:
    raise RuntimeError('story asset missing')

def by_id(rows):
    result = {}
    for row in rows:
        key = str(row.get_editor_property('id'))
        if key in result:
            raise RuntimeError('duplicate story id ' + key)
        result[key] = row
    return result

def preserve(rows, owned):
    return [(str(row.get_editor_property('id')), row.export_text()) for row in rows
            if str(row.get_editor_property('id')) not in owned]

def road_to_ue_live(road_m):
    # FVector2f has native serialization but no reflected Python fields in UE
    # 5.8: attribute access fails and to_tuple() is empty. Read its native text.
    pairs = []
    for point in story.get_editor_property('road_m_to_ue_m'):
        values = re.fullmatch(r'\\(X=([-+0-9.eE]+),Y=([-+0-9.eE]+)\\)', point.export_text())
        if values is None:
            raise RuntimeError('unrecognized native road pair ' + point.export_text())
        pairs.append((float(values.group(1)), float(values.group(2))))
    pairs.sort()
    for (r0, u0), (r1, u1) in zip(pairs, pairs[1:]):
        if r0 <= road_m <= r1:
            return u0 + (u1 - u0) * (road_m - r0) / (r1 - r0)
    raise RuntimeError('story road profile does not contain drone milestone')

for field in ('beats', 'cinematics', 'lines'):
    have = by_id(story.get_editor_property(field))
    for key in PATCH[field]:
        if key not in have:
            raise RuntimeError('missing owned record ' + key)
assets = {}
for path in ([c['sequence'] for c in PATCH['cinematics'].values()]
             + [line['sound'] for line in PATCH['lines'].values()]):
    assets[path] = unreal.load_asset(path)
    if assets[path] is None:
        raise RuntimeError('install drone asset before story patch: ' + path)
# Both tags must suppress the old separate recovery and drone-only branches.
beats_by_id = by_id(story.get_editor_property('beats'))
if 'Drone' not in [str(n) for n in beats_by_id['OA2_OPTICS_BACK'].get_editor_property('excludes_tags')]:
    raise RuntimeError('legacy optics recovery is not excluded by Drone')
if 'AuxSensors' not in [str(n) for n in beats_by_id['OB1_DRONE_SOLO'].get_editor_property('excludes_tags')]:
    raise RuntimeError('legacy drone-only beat is not excluded by AuxSensors')
for data in PATCH['beats'].values():
    if abs(road_to_ue_live(data['road_m']) - data['ue_distance_m']) > 1.0:
        raise RuntimeError('live story road profile differs by more than 1 m')
'''

APPLY = '''
before = {field: preserve(story.get_editor_property(field), PATCH[field])
          for field in ('beats', 'cinematics', 'lines')}
old_tags = list(story.get_editor_property('enabled_tags'))
guard = ([x.export_text() for x in story.get_editor_property('glances')],
         [x.export_text() for x in story.get_editor_property('road_m_to_ue_m')],
         story.get_editor_property('gap_s'), story.get_editor_property('drive_lighting_road_progress'))
ACTION_TYPES = {'PlayCarrierLine': unreal.SaskartaActionType.PLAY_CARRIER_LINE,
                'SetMode': unreal.SaskartaActionType.SET_MODE,
                'ShowCaption': unreal.SaskartaActionType.SHOW_CAPTION}

def action(data):
    row = unreal.SaskartaEventAction()
    for name, value in data.items():
        if name == 'type':
            value = ACTION_TYPES[value]
        elif name == 'id':
            value = unreal.Name(value)
        elif name == 'text':
            value = unreal.Text(value)
        row.set_editor_property(name, value)
    return row

revised = {}
for field in ('beats', 'cinematics', 'lines'):
    rows = []
    for original in story.get_editor_property(field):
        key = str(original.get_editor_property('id'))
        data = PATCH[field].get(key)
        row = original.copy()
        if data is not None:
            print('DRONE_STORY_BEFORE ' + field + ' ' + key + ' ' + original.export_text())
            if field == 'beats':
                trigger = row.get_editor_property('trigger').copy()
                trigger.set_editor_property('road_m', data['road_m'])
                trigger.set_editor_property('ue_distance_m', road_to_ue_live(data['road_m']))
                trigger.set_editor_property('one_shot', True)
                row.set_editor_property('trigger', trigger)
                row.set_editor_property('requires_tags', [unreal.Name(n) for n in PATCH['enable_tags']])
                row.set_editor_property('priority', unreal.SaskartaEventPriority.CINEMATIC)
            elif field == 'cinematics':
                for name, value in data.items():
                    if name == 'sequence':
                        value = assets[value]
                    elif name == 'skip_rule':
                        value = unreal.SaskartaSkipRule.HOLD_AFTER_SEEN
                    elif name == 'hand_back':
                        value = unreal.Name(value)
                    elif name in ('cues', 'final_state'):
                        value = [action(a) for a in value]
                    row.set_editor_property(name, value)
            else:
                row.set_editor_property('english', data['english'])
                sound = assets[data['sound']]
                row.set_editor_property('sound', sound)
                row.set_editor_property('duration_s', sound.get_editor_property('duration'))
        rows.append(row)
    revised[field] = rows
# Construct and check every replacement before the first asset write.
for field, rows in revised.items():
    if preserve(rows, PATCH[field]) != before[field]:
        raise RuntimeError('unowned story data changed in ' + field)
for field, rows in revised.items():
    story.set_editor_property(field, rows)
tags = list(old_tags)
for name in PATCH['enable_tags']:
    if name not in [str(t) for t in tags]:
        tags.append(unreal.Name(name))
story.set_editor_property('enabled_tags', tags)
for field in revised:
    if preserve(story.get_editor_property(field), PATCH[field]) != before[field]:
        raise RuntimeError('unowned story data changed after write in ' + field)
after_guard = ([x.export_text() for x in story.get_editor_property('glances')],
               [x.export_text() for x in story.get_editor_property('road_m_to_ue_m')],
               story.get_editor_property('gap_s'), story.get_editor_property('drive_lighting_road_progress'))
if guard != after_guard or not set(str(t) for t in old_tags).issubset(set(str(t) for t in tags)):
    raise RuntimeError('unowned story settings changed')
print('DRONE_STORY_APPLIED beats=2 cinematics=2 lines=1 unowned=preserved saved=False')
'''

VERIFY = '''
for key, data in PATCH['beats'].items():
    row = by_id(story.get_editor_property('beats'))[key]
    trigger = row.get_editor_property('trigger')
    if abs(trigger.get_editor_property('road_m') - data['road_m']) > 0.01:
        raise RuntimeError('drone road milestone mismatch ' + key)
    if abs(trigger.get_editor_property('ue_distance_m') - road_to_ue_live(data['road_m'])) > 0.01:
        raise RuntimeError('drone spline milestone mismatch ' + key)
    if not trigger.get_editor_property('one_shot'):
        raise RuntimeError('drone beat can repeat ' + key)
for key, data in PATCH['cinematics'].items():
    row = by_id(story.get_editor_property('cinematics'))[key]
    for name in ('duration_s', 'blend_in_s', 'blend_out_s', 'letterbox', 'stop_pawn', 'relative_to_pawn'):
        if row.get_editor_property(name) != data[name]:
            raise RuntimeError('drone cinematic mismatch ' + key + '.' + name)
    if str(row.get_editor_property('hand_back')) != data['hand_back']:
        raise RuntimeError('drone handback mismatch ' + key)
    for name in ('cues', 'final_state'):
        actual = list(row.get_editor_property(name))
        expected = data[name]
        if len(actual) != len(expected):
            raise RuntimeError('drone cue count mismatch ' + key)
        for a, d in zip(actual, expected):
            for prop, value in d.items():
                if prop == 'type':
                    enums = {'PlayCarrierLine': unreal.SaskartaActionType.PLAY_CARRIER_LINE,
                             'SetMode': unreal.SaskartaActionType.SET_MODE,
                             'ShowCaption': unreal.SaskartaActionType.SHOW_CAPTION}
                    ok = a.get_editor_property(prop) == enums[value]
                elif prop in ('id', 'text'):
                    ok = str(a.get_editor_property(prop)) == value
                elif isinstance(value, float):
                    ok = abs(a.get_editor_property(prop) - value) < 0.001
                else:
                    ok = a.get_editor_property(prop) == value
                if not ok:
                    raise RuntimeError('drone cue mismatch ' + key + '.' + prop)
for key, data in PATCH['lines'].items():
    row = by_id(story.get_editor_property('lines'))[key]
    if row.get_editor_property('english') != data['english']:
        raise RuntimeError('swarm voice subtitle mismatch')
    if row.get_editor_property('sound') != assets[data['sound']]:
        raise RuntimeError('swarm voice asset mismatch')
if not set(PATCH['enable_tags']).issubset(set(str(t) for t in story.get_editor_property('enabled_tags'))):
    raise RuntimeError('drone chain tags missing')
print('DRONE_STORY_VERIFIED 3700 -> 3770; single chain; skip final states retained')
'''


def chunks(data=None):
    data = load_patch() if data is None else data
    validate(data)
    head = "PATCH = " + repr(data) + "\n" + HEAD
    result = {"10_apply.py": head + APPLY, "20_verify.py": head + VERIFY,
              "90_save.py": head + VERIFY + "\nif not unreal.EditorAssetLibrary.save_loaded_asset(story, False):\n    raise RuntimeError('story save failed')\nprint('DRONE_STORY_SAVED ' + PATCH['asset'])\n"}
    for name, source in result.items():
        compile(source, name, "exec")
        if any(token in source for token in ("try", "getattr", "import time", "open(", ".replace(", "new_level(")):
            raise ValueError("banned editor token in " + name)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=("check", "emit"))
    ap.add_argument("out", nargs="?", default="Saved/Drone/StoryPatch")
    args = ap.parse_args()
    data = load_patch()
    result = chunks(data)
    if args.step == "emit":
        folder = ROOT / args.out
        folder.mkdir(parents=True, exist_ok=True)
        for name, source in result.items():
            (folder / name).write_text(source, encoding="utf-8")
    print(json.dumps({"chunks": len(result), "asset": data["asset"], "beats": data["beats"]}))


if __name__ == "__main__":
    main()
