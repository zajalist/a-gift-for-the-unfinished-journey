"""Emit a narrowly scoped editor patch for CIN_01's first-play skip rule.

    python Tools/GameFlow/patch_cin01_skip.py check
    python Tools/GameFlow/patch_cin01_skip.py emit

The generated chunks update only CIN_01_DIRECTIVE.SkipRule in DA_Saskarta_Story.
They preserve all other cinematic fields and all unrelated story arrays. Run only
after explicitly loading the chunks in the editor; this script itself is offline.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORY_JSON = ROOT / "docs" / "story" / "story-events.json"
ASSET = "/Game/SaskartaGaea/Story/DA_Saskarta_Story"
CINEMATIC = "CIN_01_DIRECTIVE"


def load_policy():
    story = json.loads(STORY_JSON.read_text(encoding="utf-8"))
    data = story["cinematics"][CINEMATIC]
    if data.get("skip") != "HoldAlways" or float(data.get("skip_min_s", 0.0)) != 1.0:
        raise ValueError("CIN_01 source policy must be HoldAlways with a 1.0 s hold")
    return {"asset": ASSET, "cinematic": CINEMATIC, "skip_min_s": 1.0}


HEAD = '''import unreal
story = unreal.load_asset(PATCH['asset'])
if story is None:
    raise RuntimeError('story asset missing: ' + PATCH['asset'])

def by_id(rows):
    result = {}
    for row in rows:
        key = str(row.get_editor_property('id'))
        if key in result:
            raise RuntimeError('duplicate cinematic id ' + key)
        result[key] = row
    return result

rows = story.get_editor_property('cinematics')
cinematics = by_id(rows)
if PATCH['cinematic'] not in cinematics:
    raise RuntimeError('missing owned cinematic ' + PATCH['cinematic'])
target = cinematics[PATCH['cinematic']]
if abs(float(target.get_editor_property('skip_min_s')) - PATCH['skip_min_s']) > 0.001:
    raise RuntimeError('CIN_01 SkipMinS differs from source policy')
if target.get_editor_property('skip_rule') not in (unreal.SaskartaSkipRule.HOLD_AFTER_SEEN,
                                                     unreal.SaskartaSkipRule.HOLD_ALWAYS):
    raise RuntimeError('unexpected existing CIN_01 SkipRule')
'''

APPLY = '''
before_unowned = [(str(row.get_editor_property('id')), row.export_text()) for row in rows
                  if str(row.get_editor_property('id')) != PATCH['cinematic']]
keep_fields = ('id', 'sequence', 'duration_s', 'blend_in_s', 'blend_out_s', 'letterbox',
               'skip_min_s', 'stop_pawn', 'relative_to_pawn', 'cues', 'hand_back', 'final_state')
before_target = {field: target.get_editor_property(field) for field in keep_fields}
revised = []
for original in rows:
    row = original.copy()
    if str(original.get_editor_property('id')) == PATCH['cinematic']:
        row.set_editor_property('skip_rule', unreal.SaskartaSkipRule.HOLD_ALWAYS)
    revised.append(row)
story.set_editor_property('cinematics', revised)
after = by_id(story.get_editor_property('cinematics'))
target_after = after[PATCH['cinematic']]
if target_after.get_editor_property('skip_rule') != unreal.SaskartaSkipRule.HOLD_ALWAYS:
    raise RuntimeError('CIN_01 SkipRule write did not stick')
if any(target_after.get_editor_property(field) != value for field, value in before_target.items()):
    raise RuntimeError('unowned CIN_01 fields changed')
after_unowned = [(str(row.get_editor_property('id')), row.export_text()) for row in story.get_editor_property('cinematics')
                 if str(row.get_editor_property('id')) != PATCH['cinematic']]
if before_unowned != after_unowned:
    raise RuntimeError('unowned cinematic records changed')
print('CIN01_SKIP_APPLIED rule=HoldAlways min=1.0 unowned=preserved saved=False')
'''

VERIFY = '''
target = by_id(story.get_editor_property('cinematics'))[PATCH['cinematic']]
if target.get_editor_property('skip_rule') != unreal.SaskartaSkipRule.HOLD_ALWAYS:
    raise RuntimeError('CIN_01 SkipRule is not HoldAlways')
if abs(float(target.get_editor_property('skip_min_s')) - PATCH['skip_min_s']) > 0.001:
    raise RuntimeError('CIN_01 SkipMinS mismatch')
print('CIN01_SKIP_VERIFIED rule=HoldAlways min=1.0')
'''


def chunks(policy=None):
    policy = load_policy() if policy is None else policy
    if policy != {"asset": ASSET, "cinematic": CINEMATIC, "skip_min_s": 1.0}:
        raise ValueError("unexpected asset-patch scope or policy")
    head = "PATCH = " + repr(policy) + "\n" + HEAD
    result = {
        "10_apply.py": head + APPLY,
        "20_verify.py": head + VERIFY,
        "90_save.py": head + VERIFY + "\nif not unreal.EditorAssetLibrary.save_loaded_asset(story, False):\n    raise RuntimeError('story save failed')\nprint('CIN01_SKIP_SAVED ' + PATCH['asset'])\n",
    }
    for name, source in result.items():
        compile(source, name, "exec")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("check", "emit"))
    parser.add_argument("out", nargs="?", default="Saved/OpeningSkip/CIN01StoryPatch")
    args = parser.parse_args()
    result = chunks()
    if args.step == "emit":
        folder = ROOT / args.out
        folder.mkdir(parents=True, exist_ok=True)
        for name, source in result.items():
            (folder / name).write_text(source, encoding="utf-8")
    print(json.dumps({"chunks": len(result), "asset": ASSET, "cinematic": CINEMATIC,
                      "skip_rule": "HoldAlways", "skip_min_s": 1.0}))


if __name__ == "__main__":
    main()
