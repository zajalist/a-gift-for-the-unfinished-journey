"""Install only PC_Saskarta.StepCards after the Loading widget has been saved.

check is offline. prepare/build/finish require the root's exclusive editor lease,
no PIE, a pinned plan hash, and an exact hash of the already installed widget.
The backup is evidence for a manual rollback with Unreal closed; this helper
never swaps a loaded .uasset or retries an ambiguous failed build.
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

PC = '/Game/SaskartaGaea/GameFlow/PC_Saskarta'
WIDGET = '/Game/SaskartaGaea/GameFlow/UI/WBP_Saskarta_Loading'
SPEC = ROOT / 'Tools/GameFlow/specs/PC_Saskarta.loading_reveal.json'
WIDGET_SPEC = ROOT / 'Tools/GameFlow/specs/WBP_Saskarta_Loading.graph.json'
JOURNAL = ROOT / 'Saved/Verification/loading_reveal_20261002/install.json'


def plan():
    spec = json.loads(SPEC.read_text(encoding='utf-8'))
    widget = json.loads(WIDGET_SPEC.read_text(encoding='utf-8'))
    if spec['asset'] != PC or widget['asset'] != WIDGET:
        raise ValueError('Loading reveal plan escaped its pinned assets')
    if [g['graph'] for g in spec['graphs']] != ['StepCards'] or [f['name'] for f in spec['functions']] != ['StepCards']:
        raise ValueError('PC reveal scope must contain exactly StepCards')
    if 'BeginPresentation' not in {f['name'] for f in widget['functions']}:
        raise ValueError('Widget spec lacks BeginPresentation')
    graph = spec['graphs'][0]
    links = graph['links']
    expected = (['removeHayba.then', 'loadingShown.execute'],
                ['loadingShown.then', 'beginPresentation.execute'],
                ['beginPresentation.then', 'world.execute'])
    if graph['nodes'].get('beginPresentation', {}).get('call') != 'BeginPresentation' or any(links.count(e) != 1 for e in expected):
        raise ValueError('PC reveal lacks the unique show/reset/world execution chain')
    if any(a == 'loadingShown.then' and b != 'beginPresentation.execute' for a, b in links):
        raise ValueError('PC reveal bypasses BeginPresentation')
    files = [SPEC, WIDGET_SPEC, ROOT / 'Tools/GameFlow/gen_loading_specs.py',
             ROOT / 'Tools/GameFlow/gen_loading_presentation.py',
             ROOT / 'Tools/GameFlow/bpgraph.mjs', Path(__file__).resolve()]
    result = {'asset': PC, 'widget_dependency': WIDGET,
              'sha256': {str(f.relative_to(ROOT)): digest(f) for f in files}}
    result['plan_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result, spec


def verify_report(report, spec):
    graph = spec['graphs'][0]
    assets, graphs = report.get('assets', []), report.get('graphs', [])
    if report.get('ok') is not True or report.get('reset_graphs') is not True or len(assets) != 1 or len(graphs) != 1:
        raise ValueError('StepCards build lacks exact successful report')
    asset, row = assets[0], graphs[0]
    if asset.get('asset') != PC or asset.get('compile_ok') is not True or asset.get('saved') is not True or any(
            asset.get(k) for k in ('compile_errors', 'compile_warnings', 'errors', 'warnings')):
        raise ValueError('PC did not compile/save cleanly')
    counts = {'nodes': len(graph['nodes']), 'nodes_expected': len(graph['nodes']),
              'links_expected': len(graph['links']), 'links_found': len(graph['links']),
              'defaults_expected': len(graph.get('defaults', {})),
              'defaults_verified': len(graph.get('defaults', {}))}
    if row.get('asset') != PC or row.get('graph') != 'StepCards' or row.get('compile_ok') is not True or any(
            row.get(k) != v for k, v in counts.items()) or row.get('missing') or row.get('missing_nodes'):
        raise ValueError('StepCards node/link/default readback differs')


def verify_inputs(state):
    if digest(package_file(WIDGET, ROOT)) != state['widget_sha256']:
        raise ValueError('Installed widget changed after reveal preparation')
    backup = Path(state['backup'])
    for filename, expected in state['backup_sha256'].items():
        if not (backup / filename).is_file() or digest(backup / filename) != expected:
            raise ValueError('PC rollback backup changed: ' + filename)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('check', 'prepare', 'build', 'finish'))
    parser.add_argument('--owner')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--widget-sha256', help='SHA256 of the compiled/saved WBP .uasset, for prepare')
    parser.add_argument('--journal', type=Path, default=JOURNAL)
    args = parser.parse_args()
    p, spec = plan()
    if args.mode == 'check':
        print(json.dumps(p, indent=2))
        return
    if not args.owner or args.plan_sha256 != p['plan_sha256']:
        parser.error('Live mode requires root owner and exact reviewed plan hash')
    pc_file, widget_file = package_file(PC, ROOT), package_file(WIDGET, ROOT)
    require_writable(pc_file)
    if not widget_file.is_file():
        raise ValueError('Compiled Loading widget package is missing')
    connection = EditorConnection(args.owner)
    connection.guard()
    if args.mode == 'prepare':
        if args.journal.exists():
            raise ValueError('Reveal journal already exists; inspect it before any retry')
        if not args.widget_sha256 or digest(widget_file).lower() != args.widget_sha256.lower():
            raise ValueError('Installed widget SHA256 was not pinned exactly')
        widget_info = connection.rpc('blueprint_get_info', {'path': WIDGET}, connection.owner, connection.token, 30)
        widget_functions = {row.get('name') if isinstance(row, dict) else row
                            for row in widget_info.get('functions', [])}
        if 'BeginPresentation' not in widget_functions:
            raise ValueError('Compiled Loading widget does not expose BeginPresentation yet')
        widget_graph = connection.rpc('blueprint_inspect_graph',
                                      {'path': WIDGET, 'graph_name': 'BeginPresentation'},
                                      connection.owner, connection.token, 30)
        if not widget_graph.get('nodes'):
            raise ValueError('Saved Loading widget BeginPresentation graph cannot be inspected')
        backup = args.journal.parent / 'PC_Saskarta-before'
        backup.mkdir(parents=True, exist_ok=False)
        copies = {}
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            source = pc_file.with_suffix(suffix)
            if source.exists():
                shutil.copy2(source, backup / source.name)
                copies[source.name] = digest(source)
        if pc_file.name not in copies:
            raise ValueError('PC source package was not backed up')
        state = {'phase': 'prepared', 'plan': p, 'widget_sha256': digest(widget_file),
                 'pc_before_sha256': digest(pc_file), 'backup': str(backup), 'backup_sha256': copies,
                 'rollback': 'Manual only: close Unreal, verify backup hashes, then restore exact PC package.'}
        save_state(args.journal, state)
        print('LOADING_REVEAL_PREPARED', args.journal)
        return
    state = json.loads(args.journal.read_text(encoding='utf-8'))
    if state.get('plan') != p:
        raise ValueError('Reveal source plan changed after preparation')
    verify_inputs(state)
    if args.mode == 'build':
        if state.get('phase') != 'prepared' or digest(pc_file) != state['pc_before_sha256']:
            raise ValueError('PC changed or reveal build was already attempted')
        report_path = args.journal.with_name('stepcards-build.json')
        if report_path.exists():
            raise ValueError('Prior build report exists; inspect before any retry')
        import ending_editor
        command = ['node', 'Tools/GameFlow/bpgraph.mjs', 'build', '--reset-graphs', str(SPEC.relative_to(ROOT))]
        state.update(phase='building', command=command, report=str(report_path))
        save_state(args.journal, state)
        code = ending_editor.watch(report_path, command)
        connection.guard()
        if code != 0 or plan()[0] != p:
            raise ValueError('StepCards build failed or source changed; backup and report retained')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        verify_report(report, spec)
        verify_inputs(state)
        state.update(phase='built', report_sha256=digest(report_path), pc_installed_sha256=digest(pc_file))
        save_state(args.journal, state)
        print('LOADING_REVEAL_BUILT', state['pc_installed_sha256'])
        return
    if state.get('phase') != 'built' or digest(pc_file) != state['pc_installed_sha256']:
        raise ValueError('PC changed after guarded build')
    report_path = Path(state['report'])
    if digest(report_path) != state['report_sha256']:
        raise ValueError('StepCards report changed after build')
    verify_report(json.loads(report_path.read_text(encoding='utf-8')), spec)
    connection.guard()
    state['phase'] = 'complete'
    save_state(args.journal, state)
    print('LOADING_REVEAL_COMPLETE', state['pc_installed_sha256'])


if __name__ == '__main__':
    main()
