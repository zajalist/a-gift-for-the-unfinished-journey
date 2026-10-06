"""Root-only guarded Loading tree install; no live work in check mode.

tree backs up Loading and PC, stages only the dedicated Loading designer tree.
build runs the two pinned graph specs under the existing watchdog and records
their exact verified node/link/default counts. finish reads the full tree, compiles the
widget and requires saved True for exactly Loading and PC. Never replay a failed
journal automatically. Existing Caption/KeyPrompt assets are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from install_ending_folder import EditorConnection, ROOT, digest, package_file, require_writable, save_state

ASSET = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Loading'
PC = '/Game/SaskartaGaea/GameFlow/PC_Saskarta'
SPECS = ROOT / 'Tools/GameFlow/specs'
TREE = SPECS / 'WBP_Saskarta_Loading.tree.json'
GRAPH = SPECS / 'WBP_Saskarta_Loading.graph.json'
PC_GRAPH = SPECS / 'PC_Saskarta.loading_presentation.json'
JOURNAL = ROOT / 'Saved/Verification/startup_presentation_20261001/install-v1.json'


def walk(nodes):
    for node in nodes:
        yield node
        yield from walk(node.get('children', []))


def plan():
    spec = json.loads(TREE.read_text(encoding='utf-8'))
    graph = json.loads(GRAPH.read_text(encoding='utf-8'))
    pc_graph = json.loads(PC_GRAPH.read_text(encoding='utf-8'))
    if spec['asset'] != ASSET or graph['asset'] != ASSET or pc_graph['asset'] != PC:
        raise ValueError('Packet escaped its two permitted assets')
    if {g['graph'] for g in pc_graph['graphs']} != {'PollRoad', 'PollTitle'}:
        raise ValueError('PC scope must be exactly the two readiness polls')
    names = [n['name'] for n in walk(spec['tree'])]
    if len(names) != len(set(names)) or len(names) > 40:
        raise ValueError('Duplicate names or tree exceeds bounded native result size')
    if not set(spec['variables']) <= set(names):
        raise ValueError('Widget variable outside new designer tree')
    files = [TREE, GRAPH, PC_GRAPH, Path(__file__).resolve(),
             ROOT / 'Tools/GameFlow/gen_loading_specs.py', ROOT / 'Tools/GameFlow/gen_loading_presentation.py',
             ROOT / 'Tools/GameFlow/bpgraph.mjs',
             HERE / 'install_ending_folder.py', HERE / 'ending_editor.py',
             ROOT / 'Tools/Perf/bounded_pie_profile.py']
    p = {'assets': [ASSET, PC], 'widget_count': len(names),
         'sha256': {str(f.relative_to(ROOT)): digest(f) for f in files}}
    p['plan_sha256'] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()
    return p, spec


def validate_graph_report(report):
    """Accept only this packet's complete compile/save and graph readback report."""
    expected = {}
    for path in (GRAPH, PC_GRAPH):
        spec = json.loads(path.read_text(encoding='utf-8'))
        expected.update({(spec['asset'], g['graph']): g for g in spec['graphs']})
    assets = report.get('assets', [])
    if report.get('ok') is not True or report.get('reset_graphs') is not True:
        raise ValueError('Graph build did not report complete success')
    if len(assets) != 2 or {a.get('asset') for a in assets} != {ASSET, PC}:
        raise ValueError('Graph report covers wrong assets')
    for asset in assets:
        if asset.get('compile_ok') is not True or asset.get('saved') is not True or any(
                asset.get(key) for key in ('compile_errors', 'compile_warnings', 'errors', 'warnings')):
            raise ValueError('Graph asset did not compile/save cleanly')
    graphs = report.get('graphs', [])
    if len(graphs) != len(expected) or {(g.get('asset'), g.get('graph')) for g in graphs} != expected.keys():
        raise ValueError('Graph report omits or adds packet functions')
    for row in graphs:
        spec = expected[row['asset'], row['graph']]
        counts = {'nodes': len(spec['nodes']), 'nodes_expected': len(spec['nodes']),
                  'links_expected': len(spec['links']), 'links_found': len(spec['links']),
                  'defaults_expected': len(spec.get('defaults', {})), 'defaults_verified': len(spec.get('defaults', {}))}
        if row.get('compile_ok') is not True or row.get('missing') or row.get('missing_nodes') or any(
                row.get(key) != value for key, value in counts.items()):
            raise ValueError('Graph links/defaults/nodes were not fully verified: ' + row['graph'])



class Installer:
    def __init__(self, connection, journal, state):
        self.connection, self.journal, self.state = connection, journal, state

    def call(self, command, params):
        event = {'command': command, 'params': params, 'status': 'started'}
        self.state['events'].append(event)
        save_state(self.journal, self.state)
        try:
            if plan()[0] != self.state['plan']:
                raise ValueError('Prepared source changed after review')
            self.connection.guard()
            result = self.connection.rpc(command, params, self.connection.owner, self.connection.token, 30)
            event['result'] = result
            self.connection.guard()
            if not isinstance(result, dict) or result.get('ok') is False or result.get('error'):
                raise RuntimeError('Native operation failed')
            for key in ('_truncated', 'stdout_truncated', 'stderr_truncated', 'stderr',
                        'failed', 'unknown_slot_props', 'warnings', 'errors'):
                if result.get(key):
                    raise RuntimeError('Native operation returned ' + key + '; inspect recorded evidence')
            event['status'] = 'ok'
        except BaseException as error:
            event.update(status='failed', error=str(error))
            save_state(self.journal, self.state)
            raise
        save_state(self.journal, self.state)
        print('STARTUP_STEP_OK', command, flush=True)
        return result

    def read(self):
        rows, offset, total = {}, 0, None
        for _ in range(6):
            data = self.call('ui_layout_snapshot', {'widget_blueprint_path': ASSET, 'offset': offset, 'limit': 30})
            count = data.get('total_widget_count')
            if not isinstance(count, int) or count > 150 or data.get('matched_widget_count') != count:
                raise ValueError('Unbounded or filtered Loading inventory')
            if total is not None and total != count:
                raise ValueError('Loading inventory changed during pagination')
            total = count
            page = data.get('widgets', [])
            if data.get('offset') != offset or data.get('widget_count') != len(page):
                raise ValueError('Unexpected snapshot page')
            for item in page:
                if item['name'] in rows:
                    raise ValueError('Duplicate snapshot widget')
                rows[item['name']] = item
            if data.get('has_more') is False:
                if len(rows) != total:
                    raise ValueError('Incomplete Loading inventory')
                return rows
            if not page or data.get('next_offset') != offset + len(page):
                raise ValueError('Invalid pagination cursor')
            offset = data['next_offset']
        raise ValueError('Loading snapshot exceeded six-page budget')

    def tree(self, spec):
        # All dependencies must already exist; this task creates no assets.
        self.call('python_run', {'script': "import unreal\npaths=" + repr([
            '/Game/SaskartaGaea/GameFlow/UI/Fonts/Font_Terminal',
            '/Game/SaskartaGaea/GameFlow/Materials/MI_UI_RadioCRT',
            '/Game/SaskartaGaea/GameFlow/UI/Textures/T_UI_EmberGlow',
            '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_KeyPrompt']) +
            "\nfor path in paths:\n assert unreal.load_asset(path) is not None,path\nprint('STARTUP_DEPENDENCIES_OK')"})
        before = self.read()
        roots = [name for name, row in before.items() if not row.get('parent')]
        if len(roots) != 1 or before[roots[0]]['class'] != 'CanvasPanel':
            raise ValueError('Expected one existing Loading CanvasPanel root')
        if not {'ProgressFill', 'EmberGlow'} <= before.keys():
            raise ValueError('Existing Loading tree differs from canonical graph dependencies')
        self.state.update(before=before, root=roots[0], phase='tree-started')
        save_state(self.journal, self.state)
        for name, row in before.items():
            if row.get('parent') == roots[0]:
                self.call('ui_mutate_tree', {'widget_blueprint_path': ASSET, 'operation': 'remove', 'widget_name': name})
        if set(self.read()) != {roots[0]}:
            raise ValueError('Original Loading children were not completely removed')
        built = self.call('ui_build_tree', {'widget_blueprint_path': ASSET,
                                           'parent_widget_name': roots[0], 'tree': spec['tree']})
        expected = {n['name'] for n in walk(spec['tree'])}
        if built.get('created') != len(expected) or set(built.get('names', [])) != expected:
            raise ValueError('Exact newly-created widget count/names differ')
        for name, slot in spec['slots'].items():
            props = {k: v for k, v in slot.items() if k != 'anchors'}
            props.update(anchors_min=slot['anchors'][:2], anchors_max=slot['anchors'][2:])
            self.call('ui_set_widget_properties', {'widget_blueprint_path': ASSET, 'widget_name': name, 'slot_props': props})
        for name in spec['variables']:
            self.call('ui_set_variable', {'widget_blueprint_path': ASSET, 'widget_name': name, 'is_variable': True})
        if set(self.read()) != expected | {roots[0]}:
            raise ValueError('Staged tree inventory differs')
        self.state['phase'] = 'tree-staged'
        save_state(self.journal, self.state)
        print('STARTUP_TREE_STAGED_UNSAVED: run this helper build then finish')

    def build(self, spec):
        import ending_editor
        self.connection.guard()
        if plan()[0] != self.state['plan']:
            raise ValueError('Source changed after tree stage')
        report_path = self.journal.with_name(self.journal.stem + '-graphs.json')
        if report_path.exists():
            raise ValueError('Graph evidence already exists; inspect before retrying')
        command = ['node', 'Tools/GameFlow/bpgraph.mjs', 'build', '--reset-graphs',
                   str(GRAPH.relative_to(ROOT)), str(PC_GRAPH.relative_to(ROOT))]
        self.state.update(phase='graphs-started', build_command=command,
                          build_inputs={str(f.relative_to(ROOT)): digest(f) for f in (GRAPH, PC_GRAPH)},
                          graph_report=str(report_path))
        save_state(self.journal, self.state)
        code = ending_editor.watch(report_path, command)
        self.connection.guard()
        if code != 0 or plan()[0] != self.state['plan']:
            raise ValueError('Pinned graph build failed or source changed; inspect retained report')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        validate_graph_report(report)
        self.state.update(phase='graphs-verified', graph_report_sha256=digest(report_path))
        save_state(self.journal, self.state)
        print('STARTUP_GRAPHS_COMPILED_SAVED_READBACK_OK')

    def finish(self, spec):
        report_path = Path(self.state['graph_report'])
        if self.state.get('phase') != 'graphs-verified' or digest(report_path) != self.state.get('graph_report_sha256'):
            raise ValueError('Exact successful graph build evidence required before finish')
        validate_graph_report(json.loads(report_path.read_text(encoding='utf-8')))
        expected = {n['name'] for n in walk(spec['tree'])} | {self.state['root']}
        if set(self.read()) != expected:
            raise ValueError('Staged tree inventory changed')
        compiled = self.call('ui_compile_widget', {'widget_blueprint_path': ASSET, 'save_on_success': False})
        if compiled.get('success') is not True or compiled.get('compiled_clean') is not True:
            raise ValueError('Loading widget did not compile cleanly')
        compiled_pc = self.call('blueprint_compile', {'path': PC, 'save': False})
        if compiled_pc.get('ok') is not True:
            raise ValueError('Independent PC compilation failed')
        for asset in (ASSET, PC):
            require_writable(package_file(asset, ROOT))
            result = self.call('python_run', {'script': 'import unreal\nbp=unreal.load_asset(' + repr(asset) +
                ")\nassert bp is not None\nsaved=unreal.EditorAssetLibrary.save_loaded_asset(bp,False)\nassert saved is True\nprint('STARTUP_SAVED_TRUE')"})
            if result.get('ok') is not True or 'STARTUP_SAVED_TRUE' not in result.get('stdout', ''):
                raise ValueError('Strict save True was not confirmed')
        self.state.update(phase='saved', saved_sha256={a: digest(package_file(a, ROOT)) for a in (ASSET, PC)})
        save_state(self.journal, self.state)
        print('STARTUP_PRESENTATION_COMPILED_SAVED_OK')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'tree', 'build', 'finish'))
    parser.add_argument('--owner')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--journal', type=Path, default=JOURNAL)
    args = parser.parse_args()
    p, spec = plan()
    if args.mode == 'check':
        print(json.dumps(p, indent=2))
        return
    if not args.owner or args.plan_sha256 != p['plan_sha256']:
        parser.error('Live operation requires owner and exact reviewed plan hash')
    for asset in (ASSET, PC):
        require_writable(package_file(asset, ROOT))
    if args.mode == 'tree':
        if args.journal.exists():
            raise ValueError('Journal exists; inspect it. No automatic replay.')
        backup = args.journal.parent / (args.journal.stem + '-before')
        backup.mkdir(parents=True, exist_ok=False)
        originals = {}
        for asset in (ASSET, PC):
            target = package_file(asset, ROOT)
            for suffix in ('.uasset', '.uexp', '.ubulk'):
                source = target.with_suffix(suffix)
                if source.exists():
                    require_writable(source)
                    shutil.copy2(source, backup / source.name)
                    originals[source.name] = digest(source)
        state = {'plan': p, 'phase': 'preflight', 'backup': str(backup), 'original_sha256': originals, 'events': []}
    else:
        state = json.loads(args.journal.read_text(encoding='utf-8'))
        phase = 'tree-staged' if args.mode == 'build' else 'graphs-verified'
        if state['plan'] != p or state['phase'] != phase:
            raise ValueError('Operation requires this exact ' + phase + ' journal')
    install = Installer(EditorConnection(args.owner), args.journal, state)
    getattr(install, args.mode)(spec)


if __name__ == '__main__':
    main()
