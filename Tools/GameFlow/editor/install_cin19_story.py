"""Prepare/check/install the current Story source with a strict CIN19 readback.

Preparation and check are offline. Run is for the sole editor owner with an
existing global lease. Re-prepare after other Story owners finish their edits;
the manifest pins every importer input and existing ending packets stay intact.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install_ending_folder as bounded

ROOT = bounded.ROOT
PACKET = bounded.PREPARED / 'cin19_story'
PACKAGE = '/Game/SaskartaGaea/Story/DA_Saskarta_Story'
INPUTS = (
    'docs/story/story-events.json', 'docs/story/radio-lines-for-translation.tsv',
    'docs/story/carrier-voice-lines.json', 'docs/story/caption-pages.json',
    'docs/story/road-profile.json', 'Saved/RadioRecordings/durations.json',
    'Tools/GameFlow/gen_first_light_ending.py',
    'Tools/GameFlow/editor/install_cin19_story.py',
)


def inputs(root):
    return {str(root / name): bounded.digest(root / name) if (root / name).is_file() else None
            for name in INPUTS}


def scripts(cine):
    head = f"import unreal\nasset = unreal.load_asset({PACKAGE!r})\nassert asset is not None, 'Missing Story asset'\n"
    apply = head + """report = unreal.SaskartaStoryImport.import_story_from_files(asset, unreal.Paths.project_dir())
assert report is not None and str(report).rstrip().endswith('problems 0'), 'Story import has problems: ' + str(report)
print('CIN19_STORY_IMPORTED', str(report))
"""
    save = head + """saved = unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
assert saved is True, 'Story save did not return True'
print('saved', saved)
"""
    # Compare every CIN19 cue/handoff field used by this change, including the
    # prompt guard; floats have been stored as float32 in the asset.
    def expected(action):
        return (action['type'], action.get('id', 'None'), round(action.get('at_s', -1), 3),
                round(action.get('duration_s', 0), 3), action.get('after_prompt', False))
    rows = [expected(q) for q in cine['cues']]
    final = [expected(q) for q in cine['final_state']]
    enums = sorted({row[0] for row in rows + final})
    import re
    enum_names = {name: re.sub(r'(?<!^)(?=[A-Z])', '_', name).upper() for name in enums}
    read = head + """matches = [c for c in asset.get_editor_property('cinematics') if str(c.get_editor_property('id')) == 'CIN_19_HATCH']
assert len(matches) == 1, 'Expected one CIN19'
cine = matches[0]
assert abs(cine.get_editor_property('duration_s') - 36.0) < 0.001
"""
    read += 'types = {' + ', '.join(f'{name!r}: unreal.SaskartaActionType.{enum_names[name]}' for name in enums) + '}\n'
    read += """def same(actual, wanted):
    assert len(actual) == len(wanted), 'CIN19 action count differs'
    for action, row in zip(actual, wanted):
        assert action.get_editor_property('type') == types[row[0]], str(row)
        assert str(action.get_editor_property('id')) == row[1], str(row)
        assert abs(action.get_editor_property('at_s') - row[2]) < 0.001, str(row)
        assert abs(action.get_editor_property('duration_s') - row[3]) < 0.001, str(row)
        assert action.get_editor_property('after_prompt') == row[4], str(row)
"""
    read += f"same(cine.get_editor_property('cues'), {rows!r})\n"
    read += f"same(cine.get_editor_property('final_state'), {final!r})\n"
    read += f"print('CIN19_STORY_VERIFIED cues {len(rows)} final {len(final)}')\n"
    return {'00_apply.py': apply, '90_save.py': save, '99_read.py': read}


def prepare(packet=PACKET, root=ROOT):
    cine = json.loads((root / INPUTS[0]).read_text(encoding='utf-8'))['cinematics']['CIN_19_HATCH']
    # Require the scoped production patch before pinning an install packet.
    sys.path.insert(0, str(root / 'Tools/GameFlow'))
    import gen_first_light_ending
    import copy
    if gen_first_light_ending.hatch_patch(copy.deepcopy(cine)) != cine:
        raise ValueError('Apply gen_first_light_ending.py --hatch-only before preparing')
    packet.mkdir(parents=True, exist_ok=True)
    for name, code in scripts(cine).items():
        compile(code, name, 'exec')
        if bounded.editor.banned(code):
            raise ValueError('Forbidden editor operation: ' + name)
        (packet / name).write_text(code, encoding='utf-8')
    manifest = {'status': 'prepared_not_installed', 'source_sha256': inputs(root),
                'script_sha256': {name: bounded.digest(packet / name) for name in scripts(cine)},
                'cin19': cine}
    bounded.save_state(packet / 'manifest.json', manifest)
    return check(packet, root)


def check(packet=PACKET, root=ROOT):
    manifest_path = packet / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['source_sha256'] != inputs(root):
        raise ValueError('Importer input changed; coordinate with Story owners and re-prepare')
    expected = manifest['script_sha256']
    if set(expected) != {'00_apply.py', '90_save.py', '99_read.py'} or {p.name for p in packet.glob('*.py')} != set(expected):
        raise ValueError('Unexpected Story packet filenames')
    for name, sha in expected.items():
        if bounded.digest(packet / name) != sha:
            raise ValueError('Story packet hash changed: ' + name)
        code = (packet / name).read_text(encoding='utf-8')
        compile(code, name, 'exec')
        if bounded.editor.banned(code):
            raise ValueError('Forbidden editor operation: ' + name)
    bounded.require_writable(bounded.package_file(PACKAGE, root))
    plan = {'folder': packet.name, 'prepared': str(packet.parent.resolve()),
            'audit_sha256': bounded.digest(manifest_path), 'script_sha256': expected,
            'input_sha256': {name: sha for name, sha in manifest['source_sha256'].items() if sha is not None},
            'groups': [{'id': '90_save.py', 'steps': sorted(expected), 'package': PACKAGE}]}
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'check', 'run'))
    parser.add_argument('--owner')
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    plan = prepare() if args.mode == 'prepare' else check()
    if args.mode != 'run':
        print(json.dumps(plan, indent=2))
        return
    if not args.owner:
        parser.error('run requires the existing global lease owner')
    connection = bounded.EditorConnection(args.owner)
    def guard():
        check()  # Also detects an optional source appearing between calls.
        connection.guard()
    journal = args.journal or bounded.PREPARED / 'install_logs' / ('cin19_story_' + plan['audit_sha256'][:12] + '.json')
    bounded.run_plan(plan, journal, connection.send, guard)


if __name__ == '__main__':
    main()
