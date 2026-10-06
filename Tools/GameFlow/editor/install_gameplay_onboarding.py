"""Offline preparation/check; root-only bounded onboarding data + two Loading graphs.

Never rebuilds a widget tree or touches PC, radio data, cinematics outside CIN01.
Original startup/ending installation packets and receipts remain unchanged.
"""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import shutil

import install_ending_folder as bounded

ROOT = bounded.ROOT
PACKET = ROOT / 'Saved/Verification/progressive_onboarding_20261001_v1'
LOADING = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Loading'
ONBOARDING = '/Game/SaskartaGaea/Story/DA_Saskarta_Onboarding'
STORY = '/Game/SaskartaGaea/Story/DA_Saskarta_Story'
SOURCE = ['docs/story/onboarding.json', 'docs/story/story-events.json',
          'Tools/GameFlow/specs/WBP_Saskarta_Loading.graph.json',
          'Tools/GameFlow/gen_loading_presentation.py', 'Tools/GameFlow/bpgraph.mjs',
          'Tools/GameFlow/editor/install_gameplay_onboarding.py',
          'Tools/GameFlow/editor/install_ending_folder.py', 'Tools/GameFlow/editor/ending_editor.py',
          'Tools/Perf/bounded_pie_profile.py']

STORY_HEAD = '''import unreal,json,hashlib
asset=unreal.load_asset('/Game/SaskartaGaea/Story/DA_Saskarta_Story')
assert asset is not None
rows=list(asset.get_editor_property('cinematics'))
indices=[i for i,c in enumerate(rows) if str(c.get_editor_property('id')).casefold()=='cin_01_directive']
assert len(indices)==1
index=indices[0]
def legacy(action):
    return action.get_editor_property('type')==unreal.SaskartaActionType.SHOW_CAPTION and str(action.get_editor_property('text')).startswith('W / RT')
def cleaned(items):
    out=[c.copy() for c in items]
    actions=list(out[index].get_editor_property('final_state'))
    assert len([a for a in actions if legacy(a)])<=1
    out[index].set_editor_property('final_state',[a.copy() for a in actions if not legacy(a)])
    return out
def fingerprint(items):
    return hashlib.sha256(json.dumps([r.export_text() for r in cleaned(items)],separators=(',',':')).encode()).hexdigest()
before=fingerprint(rows)
updated=cleaned(rows)
actions=list(updated[index].get_editor_property('final_state'))
assert len(actions)==5
assert [str(a.get_editor_property('id')).casefold() for a in actions]==['startanimdriver','none','none','enterplaying','cp0_dock']
'''


def hashes():
    return {str(ROOT / p): bounded.digest(ROOT / p) for p in SOURCE}


def prepare():
    assert not PACKET.exists(), 'Preserve existing packet; use a deliberate new revision'
    before = hashes()
    PACKET.mkdir(parents=True)
    data = PACKET / 'data'
    data.mkdir()
    value = (ROOT / 'docs/story/onboarding.json').read_text(encoding='utf-8')
    header = f'import unreal\nasset=unreal.load_asset({ONBOARDING!r})\nassert asset is not None\nvalue={value!r}\n'
    scripts = {
        '10_onboarding_apply.py': header + "asset.set_editor_property('json',value)\nassert asset.get_editor_property('json')==value\n",
        '90_onboarding_save.py': f"import unreal\nsaved=unreal.EditorAssetLibrary.save_asset({ONBOARDING!r},only_if_is_dirty=False)\nassert saved is True\nprint('saved',saved)\n",
        '99_onboarding_read.py': header + "assert asset.get_editor_property('json')==value\n",
        '20_story_preflight.py': STORY_HEAD + "print('ONBOARDING_STORY_OTHER '+before)\n",
        '21_story_apply.py': STORY_HEAD + "asset.set_editor_property('cinematics',updated)\nactual=list(asset.get_editor_property('cinematics'))\nassert [r.export_text() for r in actual]==[r.export_text() for r in updated]\nassert fingerprint(actual)==before\nprint('ONBOARDING_STORY_OTHER '+before)\n",
        '90_story_save.py': f"import unreal\nsaved=unreal.EditorAssetLibrary.save_asset({STORY!r},only_if_is_dirty=False)\nassert saved is True\nprint('saved',saved)\n",
        '99_story_read.py': STORY_HEAD + "assert [r.export_text() for r in rows]==[r.export_text() for r in updated]\nprint('ONBOARDING_STORY_OTHER '+before)\n",
    }
    for name, code in scripts.items():
        code += f"print('GAMEPLAY_ONBOARDING_OK {name}')\n"
        ast.parse(code)
        assert not bounded.editor.banned(code), name
        (data / name).write_text(code, encoding='utf-8')
    spec = json.loads((ROOT / 'Tools/GameFlow/specs/WBP_Saskarta_Loading.graph.json').read_text())
    spec['graphs'] = [g for g in spec['graphs'] if g['graph'] in {'EventGraph', 'RollHint'}]
    assert len(spec['graphs']) == 2
    spec['description'] = 'Only remove pre-title controls and replace loading hints with atmospheric notes. Existing tree/readiness/PC unchanged.'
    bounded.save_state(PACKET / 'Loading.onboarding.graph.json', spec)
    assert before == hashes()
    bounded.save_state(PACKET / 'manifest.json', {'status': 'prepared_not_installed', 'source_sha256': before,
        'files_sha256': {p.relative_to(PACKET).as_posix(): bounded.digest(p) for p in PACKET.rglob('*') if p.is_file()},
        'scope': 'Two Loading graphs; exact Onboarding JSON; remove only legacy CIN01 controls caption.'})


def check():
    m = json.loads((PACKET / 'manifest.json').read_text())
    assert hashes() == m['source_sha256'], 'Prepared source changed'
    for name, digest in m['files_sha256'].items():
        assert bounded.digest(PACKET / name) == digest, name
    return m


def validate_graphs(report):
    expected = json.loads((PACKET / 'Loading.onboarding.graph.json').read_text())
    assert report.get('ok') is True and report.get('reset_graphs') is True
    assert len(report['assets']) == 1 and report['assets'][0]['asset'] == LOADING
    a = report['assets'][0]
    assert a.get('compile_ok') is True and a.get('saved') is True
    assert not any(a.get(k) for k in ('errors', 'warnings', 'compile_errors', 'compile_warnings'))
    assert {g['graph'] for g in report['graphs']} == {'EventGraph', 'RollHint'} and len(report['graphs']) == 2
    for actual in report['graphs']:
        g = next(g for g in expected['graphs'] if g['graph'] == actual['graph'])
        assert actual['asset'] == LOADING and actual.get('compile_ok') is True
        assert not actual.get('missing') and not actual.get('missing_nodes')
        for k, n in {'nodes': len(g['nodes']), 'nodes_expected': len(g['nodes']),
                     'links_expected': len(g['links']), 'links_found': len(g['links']),
                     'defaults_expected': len(g['defaults']), 'defaults_verified': len(g['defaults'])}.items():
            assert actual[k] == n, (g['graph'], k)


def run(mode, owner):
    m = check()
    connection = bounded.EditorConnection(owner)
    targets = [LOADING] if mode == 'graphs' else [ONBOARDING, STORY]
    backup = PACKET / ('before_' + mode)
    if not backup.exists():
        connection.guard()
        backup.mkdir()
        for package in targets:
            path = bounded.package_file(package, ROOT)
            bounded.require_writable(path)
            for suffix in ('.uasset', '.uexp', '.ubulk'):
                f = path.with_suffix(suffix)
                if f.is_file(): shutil.copy2(f, backup / f.name)
    if mode == 'graphs':
        report = PACKET / 'loading-build.json'
        assert not report.exists(), 'Existing build report must be inspected; no blind replay'
        code = bounded.editor.watch(report, ['node', 'Tools/GameFlow/bpgraph.mjs', 'build', '--reset-graphs', str(PACKET / 'Loading.onboarding.graph.json')])
        connection.guard()
        check()
        assert code == 0, 'Graph build failed; preserved report is authoritative'
        validate_graphs(json.loads(report.read_text()))
        print('GAMEPLAY_LOADING_GRAPHS_SAVED_VERIFIED')
        return
    plan = dict(folder='data', prepared=str(PACKET), audit_sha256=bounded.digest(PACKET / 'manifest.json'),
                script_sha256={Path(k).name: v for k, v in m['files_sha256'].items() if k.startswith('data/')},
                input_sha256=m['source_sha256'], groups=[
                    dict(id='onboarding', package=ONBOARDING, steps=['10_onboarding_apply.py', '90_onboarding_save.py', '99_onboarding_read.py']),
                    dict(id='story', package=STORY, steps=['20_story_preflight.py', '21_story_apply.py', '90_story_save.py', '99_story_read.py'])])
    baseline = None
    def guard():
        check()
        connection.guard()
    def send(code, name):
        nonlocal baseline
        out = connection.send(code, name)
        assert 'GAMEPLAY_ONBOARDING_OK ' + name in out
        if name in {'20_story_preflight.py', '21_story_apply.py', '99_story_read.py'}:
            values = [s.removeprefix('ONBOARDING_STORY_OTHER ') for s in out.splitlines() if s.startswith('ONBOARDING_STORY_OTHER ')]
            assert len(values) == 1
            if name == '20_story_preflight.py': baseline = values[0]
            assert values[0] == baseline, 'Unrelated Story content changed'
        return out
    bounded.run_plan(plan, PACKET / 'data-install.json', send, guard, max_groups=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'check', 'graphs', 'data'])
    parser.add_argument('--owner')
    args = parser.parse_args()
    if args.mode == 'prepare': prepare()
    if args.mode in {'graphs', 'data'}:
        if not args.owner: parser.error('Requires existing root global lease --owner')
        run(args.mode, args.owner)
    else:
        check()
        print(json.dumps({'packet': str(PACKET), 'manifest_sha256': bounded.digest(PACKET / 'manifest.json')}, indent=2))


if __name__ == '__main__': main()
